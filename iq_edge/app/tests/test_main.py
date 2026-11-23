"""python -m iq_edge (0.2.5): the voice router's door starts with the add-on, from the options, with its own password and port, and a port
that is taken never stops the rest of the add-on. The signals and the Home Assistant event listener are replaced; the servers are real."""
import base64
import json
import logging
import os
import socket
import threading
import time
import unittest
from http.client import HTTPConnection
from unittest import mock

from iq_edge import __main__ as main_module
from iq_edge import briefing, settings, voice_http
from tests.fakes import EdgeCase


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class Records(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


class MainTests(EdgeCase):
    def start(self, voice_port):
        self.web_port = free_port()
        env = mock.patch.dict(os.environ, {'IQ_INGRESS_PORT': str(self.web_port), 'IQ_VOICE_PORT': str(voice_port), 'IQ_INGRESS_PEERS': '127.0.0.1'})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(briefing.usar_centro, None)  # main() hands the center to the Bom dia
        self.handlers = {}
        fake_signal = mock.Mock(SIGTERM=15, SIGINT=2)
        fake_signal.signal = lambda number, handler: self.handlers.__setitem__(number, handler)
        for target in (mock.patch.object(main_module, 'signal', fake_signal), mock.patch.object(main_module, 'Listener')):
            target.start()
            self.addCleanup(target.stop)
        self.records = Records()
        root = logging.getLogger()
        self.addCleanup(root.setLevel, root.level)
        root.setLevel(logging.INFO)  # (main()'s basicConfig does nothing once the root logger has a handler)
        root.addHandler(self.records)
        self.addCleanup(logging.getLogger().removeHandler, self.records)
        self.thread = threading.Thread(target=main_module.main, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        if self.handlers.get(15) and self.thread.is_alive():
            self.handlers[15]()
            self.thread.join(10)

    def wait_for(self, port):
        for _ in range(100):
            try:
                socket.create_connection(('127.0.0.1', port), timeout=1).close()
                return True
            except OSError:
                time.sleep(0.1)
        return False

    def post(self, port, password, user='iq'):
        connection = HTTPConnection('127.0.0.1', port, timeout=30)
        auth = 'Basic ' + base64.b64encode(f'{user}:{password}'.encode()).decode()
        connection.request('POST', '/v1/conversation', json.dumps({'query': 'oi', 'language': 'pt'}), {'Authorization': auth})
        answer = connection.getresponse()
        data = answer.read()
        connection.close()
        return answer.status, json.loads(data)

    def test_the_door_starts_with_the_add_on_and_stops_with_it(self):
        settings.write_json(settings.data_dir() / 'options.json', {'center_url': self.center.url, 'voice_agent': 'conversation.iq_assistant',
                                                                 'voice_route': 'observe'}, private=False)
        port = free_port()
        self.start(port)
        self.assertTrue(self.wait_for(port))
        self.assertEqual((os.environ['IQ_VOICE_AGENT'], os.environ['IQ_VOICE_ROUTE']), ('conversation.iq_assistant', 'observe'))
        password = voice_http.password()
        self.assertGreaterEqual(len(password), 32)
        self.assertEqual(self.post(port, 'wrong')[0], 401)
        status, answer = self.post(port, password)  # not paired: the center is not asked, the agent (the fake HA) answers
        self.assertEqual((status, answer), (200, {'output': 'Resposta do assistente.'}))
        self.assertEqual([body['agent_id'] for body in self.ha.conversations], ['conversation.iq_assistant'])
        connection = HTTPConnection('127.0.0.1', self.web_port, timeout=30)  # the tab is still there, with the new page
        connection.request('GET', '/assistente', headers={'X-Ingress-Path': '/api/hassio_ingress/abc'})
        page = connection.getresponse().read().decode('utf-8')
        connection.close()
        self.assertIn('/v1/conversation', page)
        self.assertNotIn(password, page)
        logged = '\n'.join(self.records.lines)
        self.assertIn('Roteador de voz na porta', logged)
        self.assertIn('assistente escolhido', logged)
        self.assertNotIn(password, logged)
        self.assertNotIn('conversation.iq_assistant', logged)
        self.stop()
        self.assertFalse(self.thread.is_alive())

    def test_without_options_the_router_runs_and_says_there_is_no_assistant(self):
        settings.write_json(settings.data_dir() / 'options.json', {'center_url': self.center.url}, private=False)
        for name in ('IQ_VOICE_AGENT', 'IQ_VOICE_ROUTE'):
            os.environ.pop(name, None)
        port = free_port()
        self.start(port)
        self.assertTrue(self.wait_for(port))
        self.assertNotIn('IQ_VOICE_AGENT', os.environ)
        status, answer = self.post(port, voice_http.password())
        self.assertEqual(status, 200)
        self.assertIn('sem assistente configurado', answer['output'])
        self.assertIn('sem assistente escolhido', '\n'.join(self.records.lines))

    def test_a_port_that_is_taken_does_not_stop_the_add_on(self):
        with mock.patch.object(main_module.voice_http, 'start', side_effect=OSError('address in use')):  # (Windows lets a port be shared)
            self.start(8098)
            self.assertTrue(self.wait_for(self.web_port))  # the tab works as before
            connection = HTTPConnection('127.0.0.1', self.web_port, timeout=30)
            connection.request('GET', '/', headers={'X-Ingress-Path': '/api/hassio_ingress/abc'})
            page = connection.getresponse().read().decode('utf-8')
            connection.close()
            self.assertNotIn('/assistente', page)  # no router, no Assistente tab
            self.assertIn('Não consegui abrir o roteador de voz', '\n'.join(self.records.lines))
            self.stop()


if __name__ == '__main__':
    unittest.main()
