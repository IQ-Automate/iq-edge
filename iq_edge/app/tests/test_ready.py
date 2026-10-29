"""Lote A5, the Bom dia prepared ahead (ready.py + schedule.Preparer) against the FAKE center and HA: prepared once at the right
time (a fake clock, also across midnight), renewed only after 90 minutes and at most twice, never after it was spoken, discarded
at the end of its window; the speech uses the prepared text (no feed, no AI at that moment) when it is under 2 hours old, with the
greeting and the house added at the time of speech; the voice is cached ahead with tts_get_url only when the text changed, and its
failure is ignored."""
import os
import time
from datetime import datetime, timedelta, timezone
from unittest import mock

from iq_edge import briefing, prefs, ready, schedule, settings
from iq_edge.center import Center
from tests.fakes import EdgeCase

EVERY_DAY = {'time': '07:00', 'days': [0, 1, 2, 3, 4, 5, 6]}
AI = {'text': 'Bom dia! Hoje tem obras na avenida.', 'picks': [{'source': 'Cidade', 'indices': [0]}], 'model': 'gpt-4o-mini', 'words': 7}


def local(hour, minute=0, day=29):
    return datetime(2026, 10, day, hour, minute).astimezone()


class ReadyCase(EdgeCase):
    def setUp(self):
        super().setUp()
        self.edge = Center()
        self.assertEqual(self.edge.pair('123456'), (True, ''))
        briefing.usar_centro(self.edge)
        self.addCleanup(briefing.usar_centro, None)
        self.center.compose_answer = (200, AI, {})
        prefs.save_local(self.prefs(schedule=EVERY_DAY))
        self.preparer = schedule.Preparer(spawn=lambda job: job())

    def feeds_read(self):
        return len(self.ha.requests_to('/rss'))

    def status_page(self):
        """The tab's Estado page as the Supervisor's proxy would get it."""
        from http.client import HTTPConnection
        from iq_edge import web
        with mock.patch.dict(os.environ, {'IQ_INGRESS_PEERS': '127.0.0.1'}):
            server = web.start(web.App(self.edge), host='127.0.0.1', port=0)
            try:
                connection = HTTPConnection('127.0.0.1', server.server_port, timeout=30)
                connection.request('GET', '/', headers={'X-Ingress-Path': '/api/hassio_ingress/abc', 'X-Remote-User-Id': 'u'})
                text = connection.getresponse().read().decode('utf-8')
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
        return text


class WindowTests(EdgeCase):
    def test_the_window_of_the_day(self):
        thursday = local(5)
        self.assertEqual(schedule.prepare_window(thursday, EVERY_DAY, 30, '06:00', False), (local(6, 30), local(11)))
        self.assertIsNone(schedule.prepare_window(thursday, {'time': '07:00', 'days': [0]}, 30, '06:00', True))  # not a chosen day
        self.assertIsNone(schedule.prepare_window(thursday, EVERY_DAY, 0, '06:00', True))  # 0 = off
        self.assertEqual(schedule.prepare_window(thursday, {'time': '07:00', 'days': []}, 30, '05:30', True), (local(5, 30), local(9, 30)))
        self.assertIsNone(schedule.prepare_window(thursday, {'time': '07:00', 'days': []}, 30, '05:30', False))  # nothing triggers it
        self.assertEqual(schedule.prepare_window(thursday, None, 30, 'xx', True), (local(6), local(10)))
        self.assertEqual(schedule.prepare_window(local(11, 30), EVERY_DAY, 30, '06:00', False), (local(6, 30, day=30), local(11, day=30)))

    def test_a_time_just_after_midnight_is_prepared_the_evening_before_on_the_right_day(self):
        thursday_0010 = {'time': '00:10', 'days': [3]}  # 2026-10-29 is a Thursday (3)
        window = (local(23, 40, day=28), local(4, 10, day=29))
        self.assertEqual(schedule.prepare_window(local(23, 45, day=28), thursday_0010, 30, '06:00', False), window)
        self.assertEqual(schedule.prepare_window(local(0, 5, day=29), thursday_0010, 30, '06:00', False), window)
        self.assertEqual(schedule.prepare_window(local(23, 0, day=28), thursday_0010, 30, '06:00', False), window)  # the next one
        wednesday_0010 = {'time': '00:10', 'days': [2]}
        self.assertIsNone(schedule.prepare_window(local(23, 45, day=28), wednesday_0010, 30, '06:00', False))  # Thursday's 00:10: not chosen
        self.assertEqual(schedule.prepare_window(local(23, 0, day=27), wednesday_0010, 30, '06:00', False),
                         (local(23, 40, day=27), local(4, 10, day=28)))
        with mock.patch.dict(os.environ, {'IQ_BRIEFING_PREPARE_MINUTES': '500'}):
            self.assertEqual(schedule.prepare_minutes(), 180)
        with mock.patch.dict(os.environ, {'IQ_BRIEFING_PREPARE_MINUTES': ''}):
            self.assertEqual(schedule.prepare_minutes(), 30)


class PreparerTests(ReadyCase):
    def test_prepared_once_renewed_after_90_minutes_at_most_twice_and_discarded_after(self):
        self.assertFalse(self.preparer.tick(local(6, 29)))
        self.assertIsNone(ready.load())
        self.assertTrue(self.preparer.tick(local(6, 30)))
        data = ready.load()
        self.assertEqual((data['text'], data['language']), ('Hoje tem obras na avenida.', 'pt'))  # no greeting: it comes at the time
        self.assertEqual([c['titulo'] for c in data['cards']], ['Cidade'])  # no house card: it comes at the time
        self.assertEqual(settings.parse_time(data['until']), local(11))
        sent = self.center.composed[0]['body']
        self.assertEqual((sent['facts']['names'], sent['house_state'], sent['facts']['open']), ([], False, []))  # nothing of the house
        if os.name == 'posix':
            self.assertEqual(os.stat(ready.path()).st_mode & 0o777, 0o600)
        for minute in ((6, 45), (7, 1), (7, 59)):
            self.assertFalse(self.preparer.tick(local(*minute)))  # under 90 minutes: kept
        self.assertEqual(len(self.center.composed), 1)
        self.assertTrue(self.preparer.tick(local(8, 1)))  # 91 minutes: the first renewal
        self.assertTrue(self.preparer.tick(local(9, 32)))  # the second
        self.assertEqual(len(self.center.composed), 3)
        prefs.save_local(self.prefs(schedule=EVERY_DAY, max_words=90))  # would need another one, but 2 renewals is the most
        self.assertFalse(self.preparer.tick(local(9, 40)))
        self.assertEqual(len(self.center.composed), 3)
        self.assertFalse(self.preparer.tick(local(11, 0)))  # the end of its window: discarded
        self.assertIsNone(ready.load())

    def test_spoken_in_the_window_means_no_renewal(self):
        self.assertTrue(self.preparer.tick(local(6, 30)))
        prefs.set_state(last_spoken_at=local(7, 5).astimezone(timezone.utc).isoformat())
        self.assertFalse(self.preparer.tick(local(8, 10)))
        self.assertEqual(len(self.center.composed), 1)
        self.assertIsNotNone(ready.load())

    def test_a_failed_start_never_leaves_the_preparer_stuck(self):
        def broken(job):
            raise RuntimeError('no thread')
        preparer = schedule.Preparer(spawn=broken)
        with self.assertRaises(RuntimeError):
            preparer.tick(local(6, 30))
        self.assertTrue(preparer.busy.acquire(blocking=False))  # released
        preparer.busy.release()

    def test_the_scheduler_reads_the_files_once_per_tick(self):
        runner = schedule.Scheduler(speak=lambda: (True, ''), clock=lambda: local(5, 0), preparer=self.preparer)
        with mock.patch.object(prefs, 'state', wraps=prefs.state) as state, mock.patch.object(prefs, 'load', wraps=prefs.load) as load:
            self.assertFalse(runner.tick())
        self.assertEqual((state.call_count, load.call_count), (1, 1))

    def test_new_preferences_prepare_again_and_nothing_without_a_speaker(self):
        self.assertTrue(self.preparer.tick(local(6, 30)))
        prefs.save_local(self.prefs(schedule=EVERY_DAY, max_words=90))
        self.assertIsNone(ready.fresh('pt'))  # prepared for other values: never spoken
        self.assertTrue(self.preparer.tick(local(6, 35)))
        self.assertEqual(self.center.composed[-1]['body']['max_words'], 90)
        ready.discard()
        prefs.save_local(self.prefs(schedule=EVERY_DAY, speaker='', tts_engine=''))
        with mock.patch.dict(os.environ, {'IQ_BRIEFING_SATELLITE': ''}):
            self.assertFalse(self.preparer.tick(local(6, 40)))  # nothing can speak it
        self.assertIsNone(ready.load())

    def test_a_home_without_schedule_prepares_only_when_it_uses_the_event(self):
        prefs.save_local(self.prefs(schedule={'time': '07:00', 'days': []}))
        with mock.patch.dict(os.environ, {'IQ_BRIEFING_PREPARE_AT': '05:30'}):
            self.assertFalse(self.preparer.tick(local(5, 30)))
            prefs.set_state(last_event_at=local(7, day=28).astimezone(timezone.utc).isoformat())
            self.assertFalse(self.preparer.tick(local(5, 29)))
            self.assertTrue(self.preparer.tick(local(5, 30)))
        self.assertIsNotNone(ready.load())

    def test_the_scheduler_prepares_on_its_tick_and_speaks_with_it(self):
        clock = [local(6, 30)]
        spoken = []
        runner = schedule.Scheduler(speak=lambda: spoken.append(ready.fresh('pt', clock[0])) or (True, ''), clock=lambda: clock[0],
                                    preparer=self.preparer)
        self.assertFalse(runner.tick())
        self.assertIsNotNone(ready.load())
        clock[0] = local(7, 0)
        self.assertTrue(runner.tick())
        self.assertEqual(spoken[0]['text'], 'Hoje tem obras na avenida.')


class SpeechTests(ReadyCase):
    def test_the_speech_uses_the_prepared_text_with_the_house_of_now(self):
        ready.prepare('pt')
        feeds, composed = self.feeds_read(), len(self.center.composed)
        self.assertNotIn('Franco', ready.load()['text'])
        self.ha.states += [{'entity_id': 'cover.garagem', 'state': 'open', 'attributes': {'device_class': 'garage', 'friendly_name': 'Garagem'}},
                           {'entity_id': 'person.ana', 'state': 'home', 'attributes': {'friendly_name': 'Ana'}}]
        said, cards = [], []
        briefing.handle('bom dia automatico', pronto=ready.fresh('pt'), publish_fn=lambda c, d: cards.append(c) or True,
                        spawn_fn=lambda job: job(), sleep_fn=lambda s: None, get_volume_fn=lambda e: None,
                        speak_fn=lambda fala, idioma, cfg: said.append(fala) or True)
        self.assertEqual(said, ['Bom dia, Franco e Ana. Aberto ou destravado agora: Garagem. Hoje tem obras na avenida.'])
        self.assertEqual([c['titulo'] for c in cards[0]], ['Casa', 'Cidade'])
        self.assertIn('Em casa: Franco, Ana', cards[0][0]['linhas'])
        self.assertEqual(cards[0][1]['linhas'], ['Prefeitura anuncia obras na avenida'])
        self.assertEqual((self.feeds_read(), len(self.center.composed)), (feeds, composed))  # no feed, no AI at the time of speech

    def test_speak_now_speaks_the_prepared_text_at_once(self):
        ready.prepare('pt')
        feeds, composed = self.feeds_read(), len(self.center.composed)
        self.assertEqual(prefs.speak_now(), (True, 'Um instante.'))
        for _ in range(100):
            calls = [body for path, body in self.ha.service_calls if path == '/api/services/tts/speak']
            if calls:
                break
            time.sleep(0.05)
        self.assertEqual(calls[0]['message'], 'Bom dia, Franco. A casa está toda fechada. Hoje tem obras na avenida.')
        self.assertEqual((self.feeds_read(), len(self.center.composed)), (feeds, composed))
        self.assertTrue(prefs.state().get('last_spoken_at'))

    def test_older_than_two_hours_or_another_language_composes_now(self):
        ready.prepare('pt')
        data = ready.load()
        settings.write_json(ready.path(), dict(data, prepared_at=(datetime.now(timezone.utc) - timedelta(hours=2, minutes=1)).isoformat()))
        self.assertIsNone(ready.fresh('pt'))
        self.assertIn('ainda não preparado', self.status_page())  # the tab never says "prepared" for a text the speech refuses
        ready.prepare('pt')
        self.assertIn('preparado às', self.status_page())
        prefs.save_local(self.prefs(schedule=EVERY_DAY, max_words=90))
        self.assertIn('ainda não preparado', self.status_page())  # other values: refused by speak_now, so not "prepared"
        settings.write_json(ready.path(), dict(data, prepared_at=(datetime.now(timezone.utc) - timedelta(hours=2, minutes=1)).isoformat()))
        self.assertIsNone(ready.fresh('pt'))
        ready.prepare('pt')
        self.assertIsNotNone(ready.fresh('pt'))
        self.assertIsNone(ready.fresh('en'))  # the event asked for English: composed now
        composed = len(self.center.composed)
        with mock.patch.object(briefing, 'handle', wraps=briefing.handle) as handle:
            prefs.speak_now('en')
        self.assertIsNone(handle.call_args.kwargs['pronto'])
        self.assertEqual(len(self.center.composed), composed + 1)
        self.assertEqual(self.center.composed[-1]['body']['facts']['names'], ['Franco'])  # composed now: the whole Bom dia

    def test_old_text_outside_the_window_is_discarded(self):
        ready.prepare('pt', now=local(6, 30, day=27))
        self.assertFalse(self.preparer.tick(local(5, 0)))
        self.assertIsNone(ready.load())


class VoiceCacheTests(ReadyCase):
    def test_the_voice_is_cached_once_with_the_same_message(self):
        with mock.patch.dict(os.environ, {'IQ_BRIEFING_TTS_VOICE': 'voz-pt'}):
            ready.prepare('pt')
            ready.prepare('pt')  # the same text again: no new audio
        self.assertEqual(self.ha.tts_requests, [{'engine_id': 'tts.google_pt', 'language': 'pt', 'options': {'voice': 'voz-pt'},
                                                 'message': 'Bom dia, Franco. A casa está toda fechada. Hoje tem obras na avenida.'}])
        self.assertEqual(len(self.ha.requests_to('/core/api/tts_proxy/')), 1)  # the audio was generated (downloaded once)
        self.assertEqual([p for p, _ in self.ha.service_calls if 'tts' in p or 'media_player' in p], [])  # nothing played
        self.center.compose_answer = (200, dict(AI, text='Bom dia! Chuva forte à tarde.'), {})
        ready.prepare('pt')  # a new text: a new audio
        self.assertEqual(len(self.ha.tts_requests), 2)
        self.assertTrue(self.ha.tts_requests[1]['message'].endswith('Chuva forte à tarde.'))

    def test_a_failure_of_the_voice_cache_is_ignored(self):
        self.ha.tts_fail = True
        with self.assertNoLogs('iq_edge.briefing', level='WARNING'):
            data = ready.prepare('pt')
        self.assertEqual(data['text'], 'Hoje tem obras na avenida.')
        self.assertEqual(len(self.ha.tts_requests), 1)
        self.assertIsNotNone(ready.fresh('pt'))
