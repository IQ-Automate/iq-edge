"""Where the add-on finds things.

Inside Home Assistant (the Supervisor starts the container): the Core API is http://supervisor/core/api/ with the add-on's own
SUPERVISOR_TOKEN (config.yaml: homeassistant_api: true); the options the person typed are in /data/options.json; /data is the add-on's
private, persistent folder (in Home Assistant backups): the credential (edge.json, mode 600), the Bom dia (briefing-prefs.json, 600)
and the small state file live there.

Outside Home Assistant (tests, a developer's machine) the same code runs with environment variables:
  HA_URL, HA_TOKEN            the Home Assistant to talk to (default http://supervisor/core and $SUPERVISOR_TOKEN)
  IQ_CENTER_URL               the platform (default: the option center_url, else https://business.iqautom8.com)
  IQ_DATA_DIR                 instead of /data
  IQ_PAIRING_CODE             instead of the option pairing_code
  IQ_SUPERVISOR_URL           instead of http://supervisor (only used to clear the code from the options after pairing)
  IQ_INGRESS_PORT, IQ_INGRESS_PEERS   the tab's port (8099) and who may open it (only 172.30.32.2, the Supervisor; tests only)
Nothing here is ever logged."""
import json
import os
import platform
import secrets
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


def options():
    """The add-on's options (center_url, pairing_code); the environment wins (tests)."""
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
