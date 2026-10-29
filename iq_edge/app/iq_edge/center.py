"""The add-on's side of contract v2 with the IQ platform (the center's docs/EDGE_CONTRACT.md): pairing with the 6-digit code, the
long-poll for jobs (HTTPS going OUT of the home; nothing comes in), running each job, the heartbeat every 5 min, the credential's
rotation every 30 days, unpairing and the client's Bom dia sent to the center.

The credential (32 random bytes from the center, delivered once) lives only in /data/edge.json (mode 600) and in the Authorization
header of each call; never in a log, the tab or an answer. A code the center refused is never sent again by itself (it would spend
the code's 5 attempts): a new code (options or the tab) is needed. After pairing, the code is cleared from the options (Supervisor
API /addons/self/options). Errors back off 1 → 60 s; 401 = the owner (or the tab) unpaired it: the credential is forgotten."""
import hashlib
import logging
import socket
import threading
import time
from datetime import datetime, timezone

import requests

from . import prefs, relay, settings

CONTRACT = '2'
POLL_WAIT = 25
HEARTBEAT_EVERY = 300
ROTATE_EVERY = 30 * 24 * 3600
BACKOFF = (1, 2, 4, 8, 15, 30, 60)
MAX_RESULT = 5 * 1024 * 1024
logger = logging.getLogger('iq_edge.center')


class Revoked(Exception):
    """The center does not know this credential any more (unpaired)."""


class CenterError(Exception):
    def __init__(self, status, code=''):
        self.status, self.code = status, code
        super().__init__(f'HTTP {status} {code}'.strip())


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _parse(value):
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Center:
    def __init__(self, session=None, clock=time.time):
        self.session = session or requests.Session()
        self.session.trust_env = False  # the credential never goes through a proxy from the environment
        self.clock = clock
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.refused = set()  # digests of codes the center refused
        self.status = {'state': 'unpaired', 'problem': '', 'last_contact': None, 'last_job': None}
        self.last_heartbeat = 0.0
        self.failures = 0
        self.retry_after = 0.0
        self.time_zone = ''

    # ---- the credential file ----

    def path(self):
        return settings.data_dir() / 'edge.json'

    def credential(self):
        data = settings.read_json(self.path(), {}) or {}
        return data if isinstance(data, dict) and data.get('credential') and data.get('home_id') else {}

    def paired(self):
        return bool(self.credential())

    def public(self):
        """What the tab shows: never the credential."""
        data = self.credential()
        with self.lock:
            out = dict(self.status)
        out.update(paired=bool(data), home_name=data.get('home_name', ''), paired_at=data.get('paired_at'), center=settings.center_url(),
                   version=settings.VERSION, arch=settings.arch())
        if data and out['state'] in ('unpaired', 'code_refused'):
            out['state'] = 'paired'
        return out

    def _set(self, **values):
        with self.lock:
            self.status.update(values)

    def forget(self, state='unpaired', problem=''):
        try:
            self.path().unlink()
        except OSError:
            pass
        self._set(state=state, problem=problem)

    # ---- HTTP to the center ----

    def _request(self, method, route, body=None, timeout=20, credential=None, auth=True):
        """(status, data, headers). Revoked on 401 of an authenticated call; requests' errors go up (the loop backs off)."""
        headers = {'X-IQ-Edge-Contract': CONTRACT, 'Accept': 'application/json'}
        if auth:
            data = self.credential()
            if not data:
                raise Revoked()
            headers.update({'Authorization': 'Bearer ' + (credential or data['credential']), 'X-IQ-Edge-Home': data['home_id']})
        answer = self.session.request(method, settings.center_url() + '/api/edge/v1/' + route, json=body, headers=headers,
                                      timeout=timeout, allow_redirects=False)
        try:
            data = answer.json() if answer.content else None
        except ValueError:
            data = None
        if answer.status_code == 401 and auth:
            raise Revoked()
        return answer.status_code, data, answer.headers

    # ---- pairing ----

    def pair(self, code):
        """(ok, reason): ok · format (not 6 digits) · code (refused: wrong, expired or used) · rate · offline."""
        code = settings.normalize_code(code)
        if not code:
            return False, 'format'
        ha_version = relay.home_snapshot()[0]
        hostname = socket.gethostname()[:80]
        try:
            status, data, _ = self._request('POST', 'pair', {'code': code, 'hostname': hostname, 'addon_version': settings.VERSION,
                                                             'arch': settings.arch(), 'ha_version': ha_version}, auth=False)
        except requests.RequestException:
            self._set(problem='offline')
            return False, 'offline'
        if status == 200 and isinstance(data, dict) and data.get('credential') and data.get('home_id'):
            now = _now_iso()
            settings.write_json(self.path(), {'home_id': data['home_id'], 'home_name': str(data.get('home_name') or '')[:120],
                                              'credential': data['credential'], 'paired_at': now, 'rotated_at': now,
                                              'center': settings.center_url()})
            self.refused.discard(_digest(code))
            self._set(state='paired', problem='', last_contact=now)
            logger.info('Pareado com a plataforma (casa %s).', str(data.get('home_name') or '')[:60])
            self.clear_option_code()
            return True, ''
        if status in (400, 403):
            self.refused.add(_digest(code))
            self._set(state='code_refused', problem='code')
            logger.warning('A plataforma recusou o código de pareamento (inválido, vencido ou já usado).')
            return False, 'code'
        if status == 429:
            self._set(problem='rate')
            return False, 'rate'
        self._set(problem='offline')
        return False, 'offline'

    def clear_option_code(self):
        """After pairing, the code leaves the add-on's options (Supervisor API; only inside Home Assistant)."""
        token = settings.ha_token()
        if not token:
            return
        options = settings.options()
        body = {'options': {'center_url': str(options.get('center_url') or settings.DEFAULT_CENTER), 'pairing_code': ''}}
        try:
            self.session.post(settings.supervisor_url() + '/addons/self/options', json=body, timeout=10, allow_redirects=False,
                              headers={'Authorization': 'Bearer ' + token})
        except requests.RequestException:
            logger.info('Não consegui limpar o código nas opções (ele já não vale).')

    # ---- jobs ----

    def poll_once(self, wait=POLL_WAIT):
        """A job (dict) or None; the center holds the call up to `wait` seconds."""
        status, data, headers = self._request('GET', f'jobs?wait={int(wait)}', timeout=wait + 20)
        self._set(last_contact=_now_iso(), problem='')
        try:
            self.retry_after = float(headers.get('Retry-After') or 0)
        except ValueError:
            self.retry_after = 0.0
        if status == 200 and isinstance(data, dict) and data.get('id'):
            return data
        if status in (204, 429):
            return None
        raise CenterError(status, (data or {}).get('error', '') if isinstance(data, dict) else '')

    def run_job(self, job):
        """The job's result. A job past its deadline is never run (the center gave up on it)."""
        deadline = _parse(job.get('deadline'))
        if deadline and datetime.now(timezone.utc) > deadline:
            return None
        kind, request = job.get('kind'), job.get('request')
        self._set(last_job=_now_iso())
        if kind == 'ha':
            return relay.execute(request)
        if kind == 'prefs':
            try:
                return {'ok': True, 'status': 200, 'data': prefs.apply_from_center((request or {}).get('version'), (request or {}).get('prefs'))}
            except ValueError as error:
                return {'ok': False, 'error': 'refused', 'detail': f'invalid: {error}'}
            except OSError:
                return {'ok': False, 'error': 'error', 'detail': 'could not write the preferences file'}
        if kind == 'preview':
            try:
                return {'ok': True, 'status': 200, 'data': prefs.preview((request or {}).get('prefs'), (request or {}).get('language'))}
            except ValueError as error:
                return {'ok': False, 'error': 'refused', 'detail': f'invalid: {error}'}
        if kind == 'ping':
            return {'ok': True, 'status': 200, 'data': {'pong': True, 'addon_version': settings.VERSION}}
        return {'ok': False, 'error': 'invalid', 'detail': 'kind'}

    def answer(self, job, result):
        if result is None:
            return
        import json
        if len(json.dumps(result, ensure_ascii=False)) > MAX_RESULT:
            result = {'ok': False, 'error': 'too_big', 'detail': 'answer of Home Assistant too large'}
        status, _, _ = self._request('POST', f'jobs/{job["id"]}/result', result, timeout=30)
        if status not in (200, 409):
            raise CenterError(status)

    # ---- heartbeat, rotation, the client's Bom dia, unpair ----

    def heartbeat(self):
        version, health, programs, time_zone = relay.home_snapshot()
        if time_zone:
            self.time_zone = time_zone
        body = {'ha_version': version, 'addon_version': settings.VERSION, 'health': health}
        if programs:
            body['programs'] = programs
        status, _, _ = self._request('POST', 'heartbeat', body)
        if status != 200:
            raise CenterError(status)
        self.last_heartbeat = self.clock()

    def rotate_if_due(self):
        data = self.credential()
        rotated = _parse(data.get('rotated_at') or data.get('paired_at'))
        if not data or (rotated and (datetime.now(timezone.utc) - rotated).total_seconds() < ROTATE_EVERY):
            return False
        status, answer, _ = self._request('POST', 'rotate', {})
        if status != 200 or not isinstance(answer, dict) or not answer.get('credential'):
            raise CenterError(status)
        settings.write_json(self.path(), dict(data, credential=answer['credential'], rotated_at=_now_iso()))  # the old one works 5 min more
        logger.info('Credencial trocada (rotina de 30 dias).')
        return True

    def send_prefs(self, values, user=None):
        """The client's Bom dia to the center → the version number there, or None (no connection: sent later by the loop)."""
        if not self.paired():
            return None
        body = {'prefs': values}
        if user and user.get('name'):
            body['user'] = {'id': str(user.get('id') or '')[:80], 'name': str(user['name'])[:60]}
        try:
            status, answer, _ = self._request('POST', 'prefs', body)
        except (requests.RequestException, Revoked):
            return None
        if status == 200 and isinstance(answer, dict) and isinstance(answer.get('version'), int):
            return answer['version']
        if status == 422:
            raise ValueError((answer or {}).get('message', 'prefs') if isinstance(answer, dict) else 'prefs')
        return None

    def sync_pending(self):
        pending = prefs.pending()
        if not pending:
            return
        version = self.send_prefs(prefs.load()[1], pending.get('user'))
        if version:
            prefs.mark_synced(version)

    def unpair(self, user=None):
        """"Desparear" in the tab: the center revokes it; locally the credential is forgotten. False = no connection (nothing changed)."""
        body = {'user': {'name': str((user or {}).get('name') or '')[:60]}} if user else {}
        try:
            status, _, _ = self._request('POST', 'unpair', body)
        except Revoked:
            status = 401
        except requests.RequestException:
            return False
        if status in (200, 401):
            self.forget('unpaired')
            logger.info('Despareado pela aba IQ.')
            return True
        return False

    # ---- the loop ----

    def step(self):
        """One turn of the loop (tests call it directly): pair from the options, or heartbeat/rotate/sync when due, then one poll and its
        job. Returns the seconds to wait before the next turn."""
        if not self.paired():
            code = settings.pairing_code()
            if code and _digest(code) not in self.refused:
                ok, reason = self.pair(code)
                return 0 if ok else 5 if reason != 'offline' else self._backoff()
            return 5
        try:
            if self.clock() - self.last_heartbeat >= HEARTBEAT_EVERY:
                self.heartbeat()
                self.rotate_if_due()
                self.sync_pending()
            job = self.poll_once()
            self.failures = 0
            if job:
                self.answer(job, self.run_job(job))
                return 0
            return self.retry_after
        except Revoked:
            self.forget('revoked', 'revoked')
            logger.warning('A plataforma não reconhece mais esta casa (despareada): gere um novo código.')
            return 5
        except (requests.RequestException, CenterError) as error:
            self._set(problem='offline')
            logger.info('Sem contato com a plataforma (%s); tentando de novo.', error.__class__.__name__)
            return self._backoff()

    def _backoff(self):
        self.failures += 1
        return BACKOFF[min(self.failures - 1, len(BACKOFF) - 1)]

    def run(self):
        while not self.stop.is_set():
            try:
                wait = self.step()
            except Exception:  # never stop the add-on; never the credential in the log
                logger.exception('Erro inesperado no ciclo da plataforma.')
                wait = self._backoff()
            if wait:
                self.stop.wait(wait)
