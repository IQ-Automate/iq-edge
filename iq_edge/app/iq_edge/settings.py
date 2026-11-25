"""Where the add-on finds things.

Inside Home Assistant (the Supervisor starts the container): the Core API is http://supervisor/core/api/ with the add-on's own
SUPERVISOR_TOKEN (config.yaml: homeassistant_api: true); the options the person typed are in /data/options.json; /data is the add-on's
private, persistent folder (in Home Assistant backups): the credential (edge.json, mode 600), the Bom dia (briefing-prefs.json, 600)
and the small state file live there.

Outside Home Assistant (tests, a developer's machine) the same code runs with environment variables:
  HA_URL, HA_TOKEN            the Home Assistant to talk to (default http://supervisor/core and $SUPERVISOR_TOKEN)
  IQ_CENTER_URL               the platform (default: the option center_url, else https://business.iqautom8.com)
  IQ_DATA_DIR                 instead of /data
  IQ_MEDIA_DIR                instead of /media (the last Bom dia's audio, briefing.py)
  IQ_PAIRING_CODE             instead of the option pairing_code
  IQ_SUPERVISOR_URL           instead of http://supervisor (only used to clear the code from the options after pairing)
  IQ_INGRESS_PORT, IQ_INGRESS_PEERS   the tab's port (8099) and who may open it (only 172.30.32.2, the Supervisor; tests only)
  IQ_HA_WS_URL                instead of ws://supervisor/core/websocket (Home Assistant's event iq_bom_dia, events.py)
  IQ_VOICE_PORT, IQ_VOICE_HOSTNAME    the voice router's port (8098) and the host name shown on the tab (default: the container's)
Nothing here is ever logged.

The Bom dia's options (lote A5, all optional in config.yaml) become, at start, the IQ_BRIEFING_* variables briefing.py and
schedule.py read (BRIEFING_OPTIONS); an option left empty sets nothing (the code's default). The voice router's options (lote J1b,
0.2.5, VOICE_OPTIONS) work the same way (IQ_VOICE_AGENT, IQ_VOICE_ROUTE, and for an agent by address IQ_VOICE_AGENT_URL, _USER and
_PASSWORD; 0.2.7: IQ_VOICE_CHAT_AGENT, the agent that only chats); with neither voice_agent nor voice_agent_url set the voice router does not run at all (voice_enabled)."""
import ipaddress
import json
import os
import platform
import re
import secrets
import socket
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__

VERSION = __version__
DEFAULT_CENTER = 'https://business.iqautom8.com'
S6_ENV = Path('/run/s6/container_environment')  # s6-overlay keeps the container's variables here (a CMD may not inherit them)


def ha_url():
    return (os.getenv('HA_URL') or 'http://supervisor/core').rstrip('/')


def ha_token():
    token = os.getenv('HA_TOKEN') or os.getenv('SUPERVISOR_TOKEN') or ''
    if not token:
        try:
            token = (S6_ENV / 'SUPERVISOR_TOKEN').read_text(encoding='utf-8').strip()
        except OSError:
            token = ''
    return token.strip()


def supervisor_url():
    return (os.getenv('IQ_SUPERVISOR_URL') or 'http://supervisor').rstrip('/')


def data_dir():
    return Path(os.getenv('IQ_DATA_DIR') or '/data')


def media_dir():
    """Home Assistant's media folder as the add-on sees it (config.yaml: map media:rw); the last Bom dia's audio is kept in its
    iq-edge/ folder, so the repeat can play it. It is never created here: without the mapping the repeat is just off."""
    return Path(os.getenv('IQ_MEDIA_DIR') or '/media')


def parse_time(value):
    """An ISO moment as an aware datetime (UTC when it carries no zone); None when it cannot be read."""
    try:
        moment = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def file_options():
    """/data/options.json exactly as the Supervisor wrote it; None when it cannot be read (then nothing may be written back:
    the Supervisor replaces all the options at once)."""
    try:
        data = json.loads((data_dir() / 'options.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def options():
    """The add-on's options (center_url, pairing_code, the Bom dia's); the environment wins (tests)."""
    try:
        data = json.loads((data_dir() / 'options.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    if os.getenv('IQ_CENTER_URL'):
        data['center_url'] = os.getenv('IQ_CENTER_URL')
    if os.getenv('IQ_PAIRING_CODE') is not None:
        data['pairing_code'] = os.getenv('IQ_PAIRING_CODE')
    return data


BRIEFING_OPTIONS = {
    'weather_entity': 'IQ_BRIEFING_WEATHER_ENTITY',
    'temp_sensor': 'IQ_BRIEFING_TEMP_SENSOR',
    'satellite': 'IQ_BRIEFING_SATELLITE',
    'tts_voice': 'IQ_BRIEFING_TTS_VOICE',
    'tts_voice_en': 'IQ_BRIEFING_TTS_VOICE_EN',
    'speaker_delay': 'IQ_BRIEFING_SPEAKER_DELAY',
    'speaker_wait': 'IQ_BRIEFING_SPEAKER_WAIT',
    'speaker_busy': 'IQ_BRIEFING_SPEAKER_BUSY',
    'card_seconds': 'IQ_BRIEFING_CARD_SECONDS',
    'prepare_minutes': 'IQ_BRIEFING_PREPARE_MINUTES',
    'prepare_at': 'IQ_BRIEFING_PREPARE_AT',
    'greet_names': 'IQ_BRIEFING_GREET_NAMES',
    'trash_organic_days': 'IQ_BRIEFING_TRASH_ORGANIC_DAYS',
    'trash_recycling_days': 'IQ_BRIEFING_TRASH_RECYCLING_DAYS',
}
WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')  # the position is the weekday number
DAY_OPTIONS = ('trash_organic_days', 'trash_recycling_days')  # the only list options: weekday names


def day_names(value):
    """The valid weekday names in `value` (a list from the Supervisor, or text such as "tuesday, thursday" separated by commas,
    semicolons or spaces), lower case, without repeats, in week order. Anything else is ignored; none valid: ()."""
    if isinstance(value, str):
        value = re.split(r'[\s,;]+', value)
    chosen = {str(item).strip().lower() for item in value} if isinstance(value, list) else set()
    return tuple(day for day in WEEKDAYS if day in chosen)


def apply_briefing_options():
    """At start: each Bom dia option that is set becomes its IQ_BRIEFING_* variable. Returns the option names applied (for the log;
    never the values). A weekday option (a list in the Supervisor's file) becomes its valid names separated by commas."""
    data = options()
    applied = []
    for option, variable in BRIEFING_OPTIONS.items():
        value = data.get(option)
        if option in DAY_OPTIONS:
            value = ','.join(day_names(value))
        elif isinstance(value, (dict, list)):
            continue
        if value is None or not str(value).strip():
            continue
        os.environ[variable] = str(value).strip()[:200]
        applied.append(option)
    return applied


VOICE_OPTIONS = {
    'voice_agent': 'IQ_VOICE_AGENT',
    'voice_chat_agent': 'IQ_VOICE_CHAT_AGENT',
    'voice_route': 'IQ_VOICE_ROUTE',
    'voice_agent_url': 'IQ_VOICE_AGENT_URL',
    'voice_agent_user': 'IQ_VOICE_AGENT_USER',
    'voice_agent_password': 'IQ_VOICE_AGENT_PASSWORD',
}
VOICE_AGENT = re.compile(r'conversation\.[a-z0-9_]{1,200}')
VOICE_MODES = ('on', 'observe', 'off')
AGENT_URL_MAX = 2000


def apply_voice_options():
    """At start: each voice router option that is set AND valid becomes its IQ_VOICE_* variable (an entity id that is not a
    `conversation.*`, or a mode that is not on/observe/off, is ignored: the default stands). The agent's address, user and password
    are taken as typed (the password untouched); an address that is not usable is kept all the same, so that the router knows it was
    set and says so (voice_agent_url_state). Returns the option names applied (for the log; never the values)."""
    data = options()
    applied = []
    for option, variable in VOICE_OPTIONS.items():
        value = data.get(option)
        if not isinstance(value, str):
            continue
        if option != 'voice_agent_password':
            value = value.strip()
        if option in ('voice_agent', 'voice_chat_agent', 'voice_route'):
            value = value.lower()
        if option in ('voice_agent', 'voice_chat_agent') and not VOICE_AGENT.fullmatch(value):
            continue
        if option == 'voice_route' and value not in VOICE_MODES:
            continue
        if not value.strip():  # empty (or only spaces) = not set
            continue
        os.environ[variable] = value
        applied.append(option)
    return applied


def voice_agent():
    """The conversation entity that gets the requests that are not simple; '' = none configured."""
    value = os.getenv('IQ_VOICE_AGENT', '').strip().lower()
    return value if VOICE_AGENT.fullmatch(value) else ''


def voice_chat_agent():
    """The conversation entity that gets the chat and general questions (0.2.7); '' = none configured (everything goes where it went in
    0.2.6). It must not control the house. It never turns the router on: voice_enabled looks only at the main agent."""
    value = os.getenv('IQ_VOICE_CHAT_AGENT', '').strip().lower()
    return value if VOICE_AGENT.fullmatch(value) else ''


def _own_address(host, port):
    """True when host:port is this add-on's own voice listener: its host name (any port: nothing else of this container is an agent), or
    this machine (localhost, 127.x, ::1, 0.0.0.0) on the listener's port."""
    host = host.lower().rstrip('.')
    own = addon_hostname().lower()
    if own and (host == own or host.startswith(own + '.')):
        return True
    try:
        address = ipaddress.ip_address(host)
        address = getattr(address, 'ipv4_mapped', None) or address
        here = address.is_loopback or address.is_unspecified
    except ValueError:
        here = host == 'localhost' or host.endswith('.localhost')
    return here and port == voice_port()


def _agent_url_problem(value):
    """'' when the router may call `value`; 'invalid' (not an http or https address with a host, or with a user or password inside)
    or 'itself' (it points at this add-on's own voice listener: the router would call itself)."""
    if len(value) > AGENT_URL_MAX or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        return 'invalid'
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return 'invalid'
    if parts.scheme.lower() not in ('http', 'https') or not parts.hostname or '@' in parts.netloc or port == 0:
        return 'invalid'
    return 'itself' if _own_address(parts.hostname, port or (443 if parts.scheme.lower() == 'https' else 80)) else ''


def voice_agent_url_state():
    """(address, problem) of the option voice_agent_url: ('', '') = not set; (address, '') = usable; ('', 'invalid') or ('', 'itself')
    = set but refused (see _agent_url_problem). The address is a secret of the home: never log it, never show it."""
    value = os.getenv('IQ_VOICE_AGENT_URL', '').strip()
    if not value:
        return '', ''
    problem = _agent_url_problem(value)
    return ('', problem) if problem else (value, '')


def voice_agent_kind():
    """What kind of agent is set: 'url' (by address), 'refused' (an address is set but refused), 'entity' (a conversation.* entity of
    Home Assistant) or '' (none). The address wins over the entity."""
    address, refused = voice_agent_url_state()
    return 'refused' if refused else 'url' if address else 'entity' if voice_agent() else ''


def voice_agent_user():
    return os.getenv('IQ_VOICE_AGENT_USER', '')


def voice_agent_password():
    return os.getenv('IQ_VOICE_AGENT_PASSWORD', '')


def voice_enabled():
    """The voice router runs only when an agent is set: voice_agent or voice_agent_url (even a refused address: the router then says so).
    Both empty = the add-on is what 0.2.4 was (no listener, no file). voice_route alone does not turn it on."""
    return bool(voice_agent() or os.getenv('IQ_VOICE_AGENT_URL', '').strip())


def voice_route_mode():
    """'on' (the center decides; also when empty), 'observe' (asks the center, always the agent) or 'off' (never asks the center)."""
    value = os.getenv('IQ_VOICE_ROUTE', '').strip().lower()
    return value if value in VOICE_MODES else 'on'


def voice_port():
    try:
        return int(os.getenv('IQ_VOICE_PORT', '8098'))
    except ValueError:
        return 8098


def addon_hostname():
    """The add-on's name on the Supervisor's internal network (the Supervisor sets it as the container's host name): what Home
    Assistant Core types in the integration's address."""
    return (os.getenv('IQ_VOICE_HOSTNAME') or socket.gethostname()).strip()[:100]


def center_url():
    """The platform's address: https only (http only to this machine, for tests); never a path, user or query."""
    value = str(options().get('center_url') or DEFAULT_CENTER).strip().rstrip('/')
    parts = urlsplit(value)
    local = parts.hostname in ('127.0.0.1', 'localhost')
    if parts.scheme not in ('https',) + (('http',) if local else ()) or not parts.hostname or parts.username or parts.password \
            or parts.query or parts.fragment or parts.path not in ('', '/'):
        return DEFAULT_CENTER
    return f'{parts.scheme}://{parts.netloc}'


def normalize_code(value):
    """The 6 digits of a pairing code ('' when it is not one); spaces and dashes are ignored."""
    code = ''.join(c for c in str(value or '') if not c.isspace() and c != '-')
    return code if len(code) == 6 and code.isdigit() else ''


def pairing_code():
    return normalize_code(options().get('pairing_code'))


def arch():
    value = os.getenv('IQ_EDGE_ARCH', '').strip()  # the Dockerfile passes BUILD_ARCH (amd64 · aarch64)
    if value:
        return value[:20]
    machine = platform.machine().lower()
    return {'x86_64': 'amd64', 'amd64': 'amd64', 'arm64': 'aarch64', 'aarch64': 'aarch64'}.get(machine, machine[:20])


def ingress_port():
    try:
        return int(os.getenv('IQ_INGRESS_PORT', '8099'))
    except ValueError:
        return 8099


def ingress_peers():
    """Only the Supervisor's ingress proxy may open the tab (official guidance); IQ_INGRESS_PEERS exists for the tests."""
    return {p.strip() for p in os.getenv('IQ_INGRESS_PEERS', '172.30.32.2').split(',') if p.strip()}


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def write_json(path, data, private=True):
    """Atomically (a temp file in the same folder, then replace) and, for a secret, mode 600 from the first byte."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.parent / f'.{path.name}.{secrets.token_hex(6)}.tmp'
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600 if private else 0o644)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise
