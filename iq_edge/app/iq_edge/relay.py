"""The center's 'ha' jobs, run on this home's Home Assistant — only what the allow-list below permits, checked AGAIN here (the center
checks too; the add-on never trusts a job). Nothing physical: /api/services is read with GET only; no POST to /api/services/*, no
events, no templates, no other path. Writes only on the configuration of automations, scripts and scenes (a proposal the owner
approved on the platform) and the configuration check.

  GET     /api/config · /api/states · /api/states/<entity_id> · /api/services
  GET/POST/DELETE  /api/config/{automation,script,scene}/config/<id>
  POST    /api/config/core/check_config

Answers: {"ok": true, "status": <HA's HTTP status>, "data": <HA's JSON or null>} or {"ok": false, "error": forbidden · offline ·
too_big · bad_response · invalid, "detail": "..."}. Direct connection (no proxy from the environment), no redirect followed, answers
up to MAX_RESPONSE. The Supervisor token goes only in the Authorization header of each call; never in a log or an answer."""
import json
import re

import requests

from . import settings

MAX_RESPONSE = 5 * 1024 * 1024
TIMEOUT = 10
ENTITY = r'[a-z0-9_]{1,64}\.[a-z0-9_]{1,255}'
CONFIG = re.compile(r'/api/config/(automation|script|scene)/config/[A-Za-z0-9_-]{1,64}')
ALLOWED = (
    (('GET',), re.compile(r'/api/config')),
    (('GET',), re.compile(r'/api/states')),
    (('GET',), re.compile(r'/api/states/' + ENTITY)),
    (('GET',), re.compile(r'/api/services')),
    (('GET', 'POST', 'DELETE'), CONFIG),
    (('POST',), re.compile(r'/api/config/core/check_config')),
)
MAX_BODY = 64 * 1024


class RelayError(Exception):
    def __init__(self, code, detail=''):
        self.code, self.detail = code, detail
        super().__init__(code)


def allowed(method, path):
    """True only for a method and an exact path of the allow-list (never a query string, never /api/services/<anything>)."""
    if not isinstance(method, str) or not isinstance(path, str) or '?' in path or '#' in path or '..' in path:
        return False
    return any(method in methods and pattern.fullmatch(path) for methods, pattern in ALLOWED)


_SESSION = requests.Session()
_SESSION.trust_env = False  # no proxy from the environment: the token goes straight to the Supervisor


def call_ha(method, path, body=None, timeout=TIMEOUT):
    """(status, data) of one call to this home's Home Assistant (through the Supervisor). RelayError on a failure."""
    headers = {'Authorization': 'Bearer ' + settings.ha_token(), 'Accept': 'application/json'}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    try:
        with _SESSION.request(method, settings.ha_url() + path, data=data, headers=headers, timeout=timeout,
                              allow_redirects=False, stream=True) as answer:
            raw = answer.raw.read(MAX_RESPONSE + 1, decode_content=True)
            status = answer.status_code
    except requests.RequestException as error:
        raise RelayError('offline', error.__class__.__name__) from None
    if len(raw) > MAX_RESPONSE:
        raise RelayError('too_big')
    if 300 <= status < 400:
        raise RelayError('bad_response', 'redirect refused')
    if not raw.strip():
        return status, None
    try:
        return status, json.loads(raw)
    except ValueError:
        if status >= 400:  # an error page that is not JSON: the status says enough
            return status, None
        raise RelayError('bad_response', 'not JSON') from None


def execute(request):
    """One 'ha' job → its result (see the module's docstring)."""
    if not isinstance(request, dict):
        return {'ok': False, 'error': 'invalid', 'detail': 'request'}
    method, path, body = request.get('method'), request.get('path'), request.get('body')
    if not allowed(method, path):
        return {'ok': False, 'error': 'forbidden', 'detail': f'{str(method)[:10]} {str(path)[:120]}'}
    if body is not None and (method != 'POST' or not isinstance(body, dict) or len(json.dumps(body)) > MAX_BODY):
        return {'ok': False, 'error': 'invalid', 'detail': 'body'}
    try:
        status, data = call_ha(method, path, body if method == 'POST' else None)
    except RelayError as error:
        return {'ok': False, 'error': error.code, 'detail': error.detail}
    return {'ok': True, 'status': status, 'data': data}


def home_snapshot():
    """What the heartbeat says: (ha_version, health 'ok'|'ha_unreachable', programs {automations, scripts, scenes} or None,
    the home's time zone from /api/config — the schedule speaks in it)."""
    try:
        status, config = call_ha('GET', '/api/config')
    except RelayError:
        return '', 'ha_unreachable', None, ''
    if status != 200 or not isinstance(config, dict):
        return '', 'ha_unreachable', None, ''
    programs = None
    try:
        status, states = call_ha('GET', '/api/states')
        if status == 200 and isinstance(states, list):
            domains = [str(s.get('entity_id', '')).split('.', 1)[0] for s in states if isinstance(s, dict)]
            programs = {'automations': domains.count('automation'), 'scripts': domains.count('script'), 'scenes': domains.count('scene')}
    except RelayError:
        pass
    return str(config.get('version') or '')[:40], 'ok', programs, str(config.get('time_zone') or '')[:60]


def entities(prefixes):
    """[(entity_id, friendly name)] of this home whose id starts with one of `prefixes` (the Bom dia form's speakers and voices)."""
    try:
        status, states = call_ha('GET', '/api/states')
    except RelayError:
        return []
    if status != 200 or not isinstance(states, list):
        return []
    out = []
    for row in states:
        entity = row.get('entity_id') if isinstance(row, dict) else None
        if isinstance(entity, str) and entity.startswith(tuple(prefixes)):
            out.append((entity, str((row.get('attributes') or {}).get('friendly_name') or '')[:80]))
    return sorted(out)[:100]
