"""Lote A5: Home Assistant's event `iq_bom_dia` speaks the Bom dia now, over the FAKE websocket API (tests/fake_ws.py): auth with the
add-on's token, the subscription, one speech per event (language from event_data; a repeat within a minute is ignored), fragmented
messages and ping frames, Home Assistant's own ping after a silence, reconnection with back-off and a refused token."""
import os
import threading
import unittest
from unittest import mock

from iq_edge import briefing, events, prefs
from tests.fake_ws import FakeWebSocketHA
from tests.fakes import TOKEN, EdgeCase


class ListenerCase(EdgeCase):
    token = TOKEN

    def setUp(self):
        super().setUp()
        self.ws = FakeWebSocketHA()
        self.addCleanup(self.ws.stop)
        self.spoken, self.now = [], [1000.0]
        self.said = threading.Event()
        self.listener = events.Listener(url=self.ws.url, token=self.token, speak=self.speak, spawn=lambda job: job(),
                                        clock=lambda: self.now[0], backoff=(0.05, 0.1), silence=0.3)
        self.thread = threading.Thread(target=self.listener.run, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 5)
        self.addCleanup(self.listener.close)

    def speak(self, language=None):
        self.spoken.append(language)
        self.said.set()
        return True, 'Um instante.'

    def subscribed(self, count=1):
        self.assertTrue(self.ws.wait(lambda ws: len(ws.subscriptions) >= count), 'no subscription')

    def until(self, test):
        for _ in range(100):
            if test():
                return True
            self.said.wait(0.05)
        return False

    def heard(self, count):
        for _ in range(100):
            if len(self.spoken) >= count:
                return
            self.said.wait(0.05)
            self.said.clear()
        self.fail(f'spoken {len(self.spoken)} times, expected {count}')


class EventTests(ListenerCase):
    def test_one_event_one_speech_with_its_language(self):
        self.subscribed()
        auth, subscribe = self.ws.received[0], self.ws.received[1]
        self.assertEqual(auth, {'type': 'auth', 'access_token': TOKEN})
        self.assertEqual(subscribe, {'id': 1, 'type': 'subscribe_events', 'event_type': 'iq_bom_dia'})
        self.assertTrue(self.until(lambda: self.listener.public()['state'] == 'listening'))
        self.ws.fire({'language': 'en'})
        self.heard(1)
        self.ws.fire({'language': 'en'}, fragments=3)  # the same minute: an automation that fired twice
        self.ws.ping_frame()
        self.assertTrue(self.ws.wait(lambda ws: ws.pongs == [b'hi']))  # the pong also proves the fragmented event was read
        self.assertEqual(self.spoken, ['en'])
        self.now[0] += 61
        self.ws.fire({'language': 'es'}, fragments=4)  # unknown language: the saved one
        self.heard(2)
        self.now[0] += 61
        self.ws.fire({})
        self.heard(3)
        self.assertEqual(self.spoken, ['en', None, None])
        self.assertTrue(prefs.state().get('last_event_at'))
        self.assertTrue(self.listener.public()['last_event'])

    def test_home_assistants_ping_after_a_silence_keeps_the_connection(self):
        self.subscribed()
        self.assertTrue(self.ws.wait(lambda ws: any(m.get('type') == 'ping' for m in ws.received), 3))
        self.assertEqual(self.ws.connections, 1)  # the pong came: still the first connection

    def test_no_pong_means_a_dead_connection_and_it_reconnects(self):
        self.ws.answer_pings = False
        self.subscribed()
        self.subscribed(2)
        self.assertGreaterEqual(self.ws.connections, 2)

    def test_reconnects_after_home_assistant_restarts(self):
        self.subscribed()
        self.ws.drop()
        self.subscribed(2)
        self.now[0] += 61
        self.ws.fire({'language': 'pt'})
        self.heard(1)
        self.assertEqual(self.spoken, ['pt'])


class RefusedTokenTests(ListenerCase):
    token = 'wrong-token'

    def test_a_refused_token_never_subscribes_and_tries_again(self):
        self.assertTrue(self.ws.wait(lambda ws: ws.connections >= 3))
        self.assertEqual(self.ws.subscriptions, [])
        self.assertTrue(self.until(lambda: self.listener.public()['state'] == 'auth_failed'))
        self.assertEqual(self.spoken, [])


class NoServerTests(unittest.TestCase):
    def test_back_off_one_to_sixty_seconds(self):
        listener = events.Listener(url='ws://127.0.0.1:9/core/websocket', token=TOKEN)
        self.assertEqual([listener._backoff() for _ in range(9)], [1, 2, 4, 8, 15, 30, 60, 60, 60])
        self.assertEqual(events.ws_url(), 'ws://supervisor/core/websocket')
        with mock.patch.dict(os.environ, {'IQ_HA_WS_URL': 'ws://127.0.0.1:8123/api/websocket'}):
            self.assertEqual(events.ws_url(), 'ws://127.0.0.1:8123/api/websocket')

    def test_the_token_never_goes_to_the_log(self):
        listener = events.Listener(url='ws://127.0.0.1:9/core/websocket', token='secret-token-xyz', backoff=(0.01,))
        with self.assertLogs('iq_edge.events', level='INFO') as logs:
            thread = threading.Thread(target=listener.run, daemon=True)
            thread.start()
            listener.stop.wait(0.2)
            listener.close()
            thread.join(5)
        self.assertFalse(any('secret-token-xyz' in line for line in logs.output))


class SpeakNowTests(EdgeCase):
    def test_speak_now_language_and_the_satellite_alone(self):
        with mock.patch.object(briefing, 'handle', return_value='One moment.') as handle:
            with mock.patch.dict(os.environ, {'IQ_BRIEFING_SATELLITE': ''}):
                self.assertEqual(prefs.speak_now('en'), (False, ''))  # no speaker, no satellite: nothing to speak on
            handle.assert_not_called()
            with mock.patch.dict(os.environ, {'IQ_BRIEFING_SATELLITE': 'assist_satellite.cozinha'}):
                self.assertEqual(prefs.speak_now('en'), (True, 'One moment.'))
            handle.assert_called_once_with('bom dia automatico', idioma_pedido='en')

    def test_the_event_language_wins_over_the_saved_one(self):
        prefs.save_local(self.prefs(language='pt', speaker='', tts_engine=''))
        said = []
        with mock.patch.dict(os.environ, {'IQ_BRIEFING_SATELLITE': 'assist_satellite.cozinha'}):
            text = briefing.handle('bom dia automatico', idioma_pedido='en', publish_fn=lambda c, d: True,
                                   spawn_fn=lambda job: job(), announce_fn=lambda text, sat: said.append((text, sat)) or True)
        self.assertEqual(text, 'One moment.')
        self.assertTrue(said[0][0].startswith('Good morning, Franco.'))
        self.assertEqual(said[0][1], 'assist_satellite.cozinha')


if __name__ == '__main__':
    unittest.main()
