"""Lote A5, the Bom dia prepared ahead (ready.py + schedule.Preparer) against the FAKE center and HA: prepared at the right time
(a fake clock), renewed every 30 minutes until spoken, discarded 4 h after the time; the speech uses the prepared text (no feed, no AI
at that moment) when it is under 2 hours old, with the greeting and the house added at the time of speech; the voice is cached
ahead with tts_get_url once, and its failure is ignored."""
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


class WindowTests(EdgeCase):
    def test_the_window_of_the_day(self):
        thursday = local(5)
        self.assertEqual(schedule.prepare_window(thursday, EVERY_DAY, 30, '06:00', False), (local(6, 30), local(11)))
        self.assertIsNone(schedule.prepare_window(thursday, {'time': '07:00', 'days': [0]}, 30, '06:00', True))  # not a chosen day
        self.assertIsNone(schedule.prepare_window(thursday, EVERY_DAY, 0, '06:00', True))  # 0 = off
        self.assertEqual(schedule.prepare_window(thursday, {'time': '07:00', 'days': []}, 30, '05:30', True), (local(5, 30), local(9, 30)))
        self.assertIsNone(schedule.prepare_window(thursday, {'time': '07:00', 'days': []}, 30, '05:30', False))  # nothing triggers it
        self.assertEqual(schedule.prepare_window(thursday, None, 30, 'xx', True), (local(6), local(10)))
        with mock.patch.dict(os.environ, {'IQ_BRIEFING_PREPARE_MINUTES': '500'}):
            self.assertEqual(schedule.prepare_minutes(), 180)
        with mock.patch.dict(os.environ, {'IQ_BRIEFING_PREPARE_MINUTES': ''}):
            self.assertEqual(schedule.prepare_minutes(), 30)


class PreparerTests(ReadyCase):
    def test_prepared_at_the_time_renewed_until_spoken_and_discarded_after(self):
        self.assertFalse(self.preparer.tick(local(6, 29)))
        self.assertIsNone(ready.load())
        self.assertTrue(self.preparer.tick(local(6, 30)))
        data = ready.load()
        self.assertEqual((data['text'], data['language']), ('Hoje tem obras na avenida.', 'pt'))  # no greeting: it comes at the time
        self.assertEqual([c['titulo'] for c in data['cards']], ['Cidade'])  # no house card: it comes at the time
        sent = self.center.composed[0]['body']
        self.assertEqual((sent['facts']['names'], sent['house_state'], sent['facts']['open']), ([], False, []))  # nothing of the house
        if os.name == 'posix':
            self.assertEqual(os.stat(ready.path()).st_mode & 0o777, 0o600)
        self.assertFalse(self.preparer.tick(local(6, 45)))  # fresh
        self.assertTrue(self.preparer.tick(local(7, 1)))  # 31 minutes old: renewed
        self.assertEqual(len(self.center.composed), 2)
        prefs.set_state(last_spoken_at=local(7, 5).astimezone(timezone.utc).isoformat())
        self.assertFalse(self.preparer.tick(local(7, 40)))  # spoken: no more renewals
        self.assertEqual(len(self.center.composed), 2)
        self.assertIsNotNone(ready.load())
        self.assertFalse(self.preparer.tick(local(11, 0)))  # 4 h after the time: discarded
        self.assertIsNone(ready.load())

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
        self.assertEqual(self.ha.tts_requests, [{'engine_id': 'tts.google_pt', 'language': 'pt', 'options': {'voice': 'voz-pt'},
                                                 'message': 'Bom dia, Franco. A casa está toda fechada. Hoje tem obras na avenida.'}])
        self.assertEqual(len(self.ha.requests_to('/core/api/tts_proxy/')), 1)  # the audio was generated (downloaded once)
        self.assertEqual([p for p, _ in self.ha.service_calls if 'tts' in p or 'media_player' in p], [])  # nothing played

    def test_a_failure_of_the_voice_cache_is_ignored(self):
        self.ha.tts_fail = True
        with self.assertNoLogs('iq_edge.briefing', level='WARNING'):
            data = ready.prepare('pt')
        self.assertEqual(data['text'], 'Hoje tem obras na avenida.')
        self.assertEqual(len(self.ha.tts_requests), 1)
        self.assertIsNotNone(ready.fresh('pt'))
