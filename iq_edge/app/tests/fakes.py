"""A FAKE IQ center (contract v2, in memory) and a FAKE Home Assistant (REST API through the 'Supervisor'), each an http.server in a
thread on 127.0.0.1. Nothing here reaches the internet. The fake HA also answers /addons/self/options (the Supervisor) and /rss
(a news feed), so the add-on's whole path runs locally."""
import json
import os
import re
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

TOKEN = 'supervisor-token-for-tests-only'
CONFIG = re.compile(r'/api/config/(automation|script|scene)/config/([^/?]+)')
RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Feed</title>
<item><title>Prefeitura anuncia obras na avenida</title></item><item><title>Chuva forte prevista para a tarde</title></item></channel></rss>"""


class _Server:
    def start(self, handler):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.server.daemon_threads = True
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)


class FakeHA(_Server):
    """Home Assistant's REST API as the Supervisor proxy serves it (Bearer = the add-on's token)."""

    def __init__(self):
        self.log, self.options_posts = [], []
        self.config = {'version': '2026.10.4', 'location_name': 'Casa Teste', 'time_zone': 'America/New_York'}
        self.states = [{'entity_id': 'media_player.sala', 'state': 'idle', 'attributes': {'friendly_name': 'Sonos <Sala>'}},
                       {'entity_id': 'tts.google_pt', 'state': 'unknown', 'attributes': {'friendly_name': 'Google PT'}},
                       {'entity_id': 'automation.porta', 'state': 'on', 'attributes': {'friendly_name': 'Porta'}},
                       {'entity_id': 'weather.casa', 'state': 'sunny', 'attributes': {'temperature': 25, 'temperature_unit': '°C'}},
                       {'entity_id': 'person.franco', 'state': 'home', 'attributes': {'friendly_name': 'Franco'}}]
        self.objects = {'automation': {'1': {'id': '1', 'alias': 'Porta'}}, 'script': {}, 'scene': {}}
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def answer(self, status, data=None, raw=None, content_type='application/json'):
                body = raw if raw is not None else (b'' if data is None else json.dumps(data).encode())
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def route(self, method):
                body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
                fake.log.append((method, self.path))
                if self.path.split('?', 1)[0] == '/rss':
                    return self.answer(200, raw=RSS, content_type='application/rss+xml')
                if self.headers.get('Authorization') != 'Bearer ' + TOKEN:
                    return self.answer(401, {'message': 'Unauthorized'})
                if self.path == '/addons/self/options' and method == 'POST':
                    fake.options_posts.append(json.loads(body))
                    return self.answer(200, {'result': 'ok'})
                path = self.path[len('/core'):] if self.path.startswith('/core/') else None
                if path is None:
                    return self.answer(404, {})
                match = CONFIG.fullmatch(path)
                if method == 'GET' and path == '/api/config':
                    return self.answer(200, fake.config)
                if method == 'GET' and path == '/api/states':
                    return self.answer(200, fake.states)
                if method == 'GET' and path.startswith('/api/states/'):
                    found = [s for s in fake.states if s['entity_id'] == path.rsplit('/', 1)[1]]
                    return self.answer(200, found[0]) if found else self.answer(404, {'message': 'Entity not found.'})
                if method == 'GET' and path == '/api/services':
                    return self.answer(200, [{'domain': 'light', 'services': {'turn_on': {}}}])
                if match and method == 'GET':
                    found = fake.objects[match[1]].get(match[2])
                    return self.answer(200, found) if found else self.answer(404, {'message': 'Resource not found'})
                if match and method == 'POST':
                    data = json.loads(body)
                    if data.get('bogus'):
                        return self.answer(400, {'message': 'Message malformed: extra keys not allowed'})
                    fake.objects[match[1]][match[2]] = dict(data, id=match[2])
                    return self.answer(200, {'result': 'ok'})
                if match and method == 'DELETE':
                    fake.objects[match[1]].pop(match[2], None)
                    return self.answer(200, {'result': 'ok'})
                if method == 'POST' and path == '/api/config/core/check_config':
                    return self.answer(200, {'result': 'valid', 'errors': None})
                if method == 'POST' and path.startswith('/api/services/'):
                    return self.answer(200, [])  # the Bom dia's own speech only (tts.speak, volume_set...); the relay never comes here
                if method == 'POST' and path.startswith('/api/events/'):
                    return self.answer(200, {'message': 'Event fired.'})
                return self.answer(404, {'message': 'Not found'})

            def do_GET(self):
                self.route('GET')

            def do_POST(self):
                self.route('POST')

            def do_DELETE(self):
                self.route('DELETE')

        self.start(Handler)

    def requests_to(self, prefix):
        return [(m, p) for m, p in self.log if p.startswith(prefix)]


class FakeCenter(_Server):
    """The IQ center's /api/edge/v1/* (contract v2), in memory: one code, one home; jobs queued by the test."""

    def __init__(self, code='123456'):
        self.code, self.credential, self.previous, self.home_id = code, None, None, 'home-1'
        self.jobs, self.results, self.heartbeats, self.prefs, self.log = [], {}, [], [], []
        self.revoked, self.next_version = False, 7
        # briefing-compose (lote A5): (status, JSON answer or raw bytes, extra headers); every call kept with its headers
        self.compose_answer = (503, {'error': 'no_key', 'message': 'no key'}, {})
        self.composed = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def answer(self, status, data=None):
                body = b'' if data is None else json.dumps(data).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('X-IQ-Edge-Contract', '2')
                self.end_headers()
                self.wfile.write(body)

            def authorized(self):
                auth = self.headers.get('Authorization') or ''
                ok = not fake.revoked and self.headers.get('X-IQ-Edge-Home') == fake.home_id and auth in (
                    'Bearer ' + str(fake.credential), 'Bearer ' + str(fake.previous))
                return ok and fake.credential is not None

            def route(self, method):
                body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
                data = json.loads(body) if body else {}
                path = self.path.split('?', 1)[0][len('/api/edge/v1/'):]
                fake.log.append((method, path, data))
                if self.headers.get('X-IQ-Edge-Contract') != '2':
                    return self.answer(400, {'error': 'contract'})
                if method == 'POST' and path == 'pair':
                    if data.get('code') != fake.code:
                        return self.answer(403, {'error': 'code'})
                    fake.code, fake.credential = None, 'C' * 43
                    fake.pair_info = data
                    return self.answer(200, {'home_id': fake.home_id, 'home_name': 'Casa <Teste>', 'credential': fake.credential,
                                             'poll_wait': 25, 'heartbeat_every': 300, 'contract': 2})
                if not self.authorized():
                    return self.answer(401, {'error': 'unauthorized'})
                if method == 'GET' and path == 'jobs':
                    if fake.jobs:
                        return self.answer(200, fake.jobs.pop(0))
                    return self.answer(204)
                match = re.fullmatch(r'jobs/([\w-]+)/result', path)
                if match:
                    fake.results[match[1]] = data
                    return self.answer(200, {'ok': True})
                if path == 'heartbeat':
                    fake.heartbeats.append(data)
                    return self.answer(200, {'ok': True, 'heartbeat_every': 300})
                if path == 'prefs':
                    fake.prefs.append(data)
                    fake.next_version += 1
                    return self.answer(200, {'ok': True, 'version': fake.next_version})
                if path == 'rotate':
                    fake.previous, fake.credential = fake.credential, 'R' * 43
                    return self.answer(200, {'credential': fake.credential, 'previous_valid_until': '2026-10-28T12:05:00+00:00'})
                if path == 'unpair':
                    fake.revoked = True
                    return self.answer(200, {'ok': True})
                if method == 'POST' and path == 'briefing-compose':
                    fake.composed.append({'body': data, 'headers': dict(self.headers), 'size': len(body)})
                    status, answer, extra = fake.compose_answer
                    raw = answer if isinstance(answer, bytes) else json.dumps(answer).encode()
                    self.send_response(status)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(raw)))
                    for name, value in extra.items():
                        self.send_header(name, value)
                    self.end_headers()
                    self.wfile.write(raw)
                    return None
                return self.answer(404, {'error': 'route'})

            def do_GET(self):
                self.route('GET')

            def do_POST(self):
                self.route('POST')

        self.start(Handler)

    def queue(self, kind, request, job_id='0f0f0f0f-0000-4000-8000-000000000001', deadline='2099-01-01T00:00:00+00:00'):
        self.jobs.append({'id': job_id, 'kind': kind, 'request': request, 'deadline': deadline, 'contract': 2})
        return job_id


class EdgeCase(unittest.TestCase):
    """A data folder, a fake HA (the Supervisor) and a fake center; the add-on's settings point at them through the environment."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ha, self.center = FakeHA(), FakeCenter()
        self.addCleanup(self.ha.stop)
        self.addCleanup(self.center.stop)
        env = mock.patch.dict(os.environ, {'HA_URL': self.ha.url + '/core', 'HA_TOKEN': TOKEN, 'IQ_CENTER_URL': self.center.url,
                                           'IQ_DATA_DIR': self.tmp.name, 'IQ_SUPERVISOR_URL': self.ha.url, 'IQ_PAIRING_CODE': '',
                                           'IQ_BRIEFING_PREFS_FILE': os.path.join(self.tmp.name, 'briefing-prefs.json'), 'IQ_EDGE_ARCH': 'amd64'})
        env.start()
        self.addCleanup(env.stop)
        from iq_edge import briefing
        patches = mock.patch.multiple(briefing, HA_URL=self.ha.url + '/core', HA_TOKEN=TOKEN)
        patches.start()
        self.addCleanup(patches.stop)

    def prefs(self, **extra):
        values = {'house_state': True, 'weather': False, 'sources': [{'name': 'Cidade', 'url': self.ha.url + '/rss'}], 'picks': {'Cidade': 2},
                  'total_min': 1, 'total_max': 2, 'max_words': 120, 'rules': '', 'speaker': 'media_player.sala', 'volume': 40,
                  'tts_engine': 'tts.google_pt', 'language': 'pt', 'temp_unit': 'language'}
        values.update(extra)
        return values
