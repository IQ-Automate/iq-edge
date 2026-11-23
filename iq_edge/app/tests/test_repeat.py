"""0.2.6, "Repetir o último" (briefing.guardar_ultimo, repetir_ultimo and their helpers) against the FAKE Home Assistant: after a Bom dia
is spoken on the speaker the audio of what was spoken is kept in the media folder (the same tts_get_url request as the pre-cache), with a
data file that never holds the text; the repeat plays that file with media_player.play_media and NEVER asks Home Assistant for a voice
(no tts.speak, no tts_get_url, no satellite), so it costs nothing on the voice engine."""
import hashlib
import json
import logging
import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import requests

from iq_edge import briefing, prefs, settings
from tests.fakes import EdgeCase

AUDIO = b'ID3' + b'\0' * 2048  # what the fake Home Assistant serves at /api/tts_proxy/abc123.mp3
SPEECH = 'Bom dia. Hoje tem obras na avenida. Segredo-do-texto.'
VOICE_PATHS = ('/tts/speak', '/tts_get_url', '/tts_proxy/', 'assist_satellite')  # every way the add-on has to ask for a voice


class RepeatCase(EdgeCase):
    def setUp(self):
        super().setUp()
        self.media = Path(self.tmp.name) / 'media'
        self.media.mkdir()
        env = mock.patch.dict(os.environ, {'IQ_BRIEFING_TTS_VOICE': 'voz-pt', 'IQ_BRIEFING_SATELLITE': ''})
        env.start()
        self.addCleanup(env.stop)
        # A counter of its own: a Bom dia of another test module may still be "speaking" in a background thread (the whole suite runs
        # in one process), and it must neither make these repeats busy nor change this counter when it ends.
        counter = mock.patch.object(briefing, '_FALANDO', [0])
        counter.start()
        self.addCleanup(counter.stop)
        prefs.save_local(self.prefs())  # media_player.sala, tts.google_pt, volume 40
        self.cfg = briefing.speaker_config()
        self.audio = self.media / 'iq-edge' / 'bom-dia.mp3'
        self.last = settings.data_dir() / 'briefing-last.json'

    def keep(self, audio=AUDIO, **changes):
        """The files of a Bom dia spoken now, without asking the fake Home Assistant for anything."""
        self.assertTrue(briefing.guardar_ultimo(SPEECH, 'pt', self.cfg, baixar_fn=lambda *a: (audio, 'mp3')))
        if changes:
            settings.write_json(self.last, dict(settings.read_json(self.last), **changes))

    def voice_requests(self, since=0):
        return [path for _, path in self.ha.log[since:] if any(part in path for part in VOICE_PATHS)]

    def repeat(self, **fakes):
        """repetir_ultimo with everything injected that would wait or touch the speaker; returns (answer, plays)."""
        plays = []
        defaults = dict(spawn_fn=lambda job: job(), sleep_fn=lambda seconds: None, get_volume_fn=lambda entity: None,
                        set_volume_fn=lambda entity, level: True, wait_fn=lambda entity, seconds: None,
                        play_fn=lambda cfg, extension, seconds: plays.append((cfg['speaker'], extension, seconds)) or True)
        defaults.update(fakes)
        return briefing.repetir_ultimo(**defaults), plays


class SaveTests(RepeatCase):
    def test_the_audio_and_the_data_are_kept_and_the_text_is_not(self):
        self.assertTrue(briefing.guardar_ultimo(SPEECH, 'pt', self.cfg))
        self.assertEqual(self.audio.read_bytes(), AUDIO)  # the bytes Home Assistant served
        data = json.loads(self.last.read_text(encoding='utf-8'))
        self.assertEqual({key: data[key] for key in ('language', 'speaker', 'volume', 'size', 'sha256', 'extension')},
                         {'language': 'pt', 'speaker': 'media_player.sala', 'volume': 0.4, 'size': len(AUDIO),
                          'sha256': hashlib.sha256(AUDIO).hexdigest(), 'extension': 'mp3'})
        self.assertLess(abs(datetime.now(timezone.utc) - settings.parse_time(data['spoken_at'])), timedelta(minutes=1))
        self.assertGreater(data['seconds'], 0)
        self.assertEqual(sorted(data), ['extension', 'language', 'seconds', 'sha256', 'size', 'speaker', 'spoken_at', 'volume'])
        for found in (self.last, self.audio):
            self.assertNotIn('Segredo', found.read_text(encoding='utf-8', errors='replace'))  # never the spoken text
        if os.name != 'nt':
            self.assertEqual(stat.S_IMODE(self.last.stat().st_mode), 0o600)
        self.assertEqual(sorted(path.name for path in self.audio.parent.iterdir()), ['bom-dia.mp3'])  # no temporary file left
        self.assertEqual([name for name in os.listdir(self.last.parent) if name.endswith('.tmp')], [])

    def test_it_asks_with_the_very_body_of_the_precache(self):
        briefing.precache_tts(SPEECH, 'pt', self.cfg)
        self.assertTrue(briefing.guardar_ultimo(SPEECH, 'pt', self.cfg))
        body = {'engine_id': 'tts.google_pt', 'language': 'pt', 'options': {'voice': 'voz-pt'}, 'message': SPEECH}
        self.assertEqual(self.ha.tts_requests, [body, body])
        self.assertEqual(briefing._corpo_tts_url(SPEECH, 'pt', self.cfg), body)
        english = briefing._corpo_tts_url('Good morning.', 'en', dict(self.cfg, voz_en='voz-en'))
        self.assertEqual(english, {'engine_id': 'tts.google_pt', 'language': 'en', 'options': {'voice': 'voz-en'}, 'message': 'Good morning.'})
        self.assertNotIn('options', briefing._corpo_tts_url(SPEECH, 'pt', dict(self.cfg, voz_pt='')))

    def test_a_speech_that_fell_back_to_no_voice_option_is_kept_without_it(self):
        cfg = dict(self.cfg, voz_pt_padrao=True)
        failed = mock.Mock(side_effect=requests.ConnectionError('boom'))
        worked = mock.Mock(raise_for_status=lambda: None)
        with mock.patch.object(briefing.requests, 'post', side_effect=[failed.side_effect, worked]) as post, \
                self.assertLogs('iq_edge.briefing', level='INFO'):
            self.assertTrue(briefing.speak_on_speaker(SPEECH, 'pt', cfg))
        self.assertNotIn('options', post.call_args.kwargs['json'])  # the second tts.speak had no voice option
        self.assertTrue(cfg['sem_voz'])
        self.assertTrue(briefing.guardar_ultimo(SPEECH, 'pt', cfg))
        self.assertEqual(self.ha.tts_requests, [{'engine_id': 'tts.google_pt', 'language': 'pt', 'message': SPEECH}])

    def test_a_failure_removes_the_old_files_and_logs_one_info_line(self):
        self.keep()
        self.assertTrue(self.audio.exists() and self.last.exists())
        with self.assertLogs('iq_edge.briefing', level='INFO') as logs:
            self.assertFalse(briefing.guardar_ultimo(SPEECH, 'pt', self.cfg, baixar_fn=lambda *a: None))
        self.assertEqual([record.levelno for record in logs.records], [logging.INFO])
        self.assertNotIn('Segredo', logs.output[0])
        self.assertFalse(self.audio.exists() or self.last.exists())  # a repeat never plays an older one
        self.assertEqual(briefing.ultimo_bom_dia()[0], 'none')

    def test_every_kind_of_failure_leaves_nothing_behind(self):
        def boom(*args):
            raise RuntimeError('boom')
        for download in (lambda *a: None, lambda *a: (b'', 'mp3'), boom):
            self.keep()
            self.assertFalse(briefing.guardar_ultimo(SPEECH, 'pt', self.cfg, baixar_fn=download))
            self.assertFalse(self.audio.exists() or self.last.exists())
        self.keep()
        self.ha.tts_fail = True  # Home Assistant refuses to give the audio (the real download)
        self.assertFalse(briefing.guardar_ultimo(SPEECH, 'pt', self.cfg))
        self.assertFalse(self.audio.exists() or self.last.exists())
        self.assertEqual(briefing.baixar_audio_da_fala(SPEECH, 'pt', self.cfg), None)

    def test_a_new_one_replaces_the_old_and_a_changed_extension_leaves_no_stale_file(self):
        self.keep()
        self.assertTrue(briefing.guardar_ultimo(SPEECH, 'en', self.cfg, baixar_fn=lambda *a: (b'RIFF-wave', 'wav')))
        self.assertEqual(sorted(path.name for path in self.audio.parent.iterdir()), ['bom-dia.wav'])
        self.assertEqual(settings.read_json(self.last)['extension'], 'wav')
        self.assertEqual(briefing.ultimo_bom_dia()[0], 'ok')

    def test_without_the_media_folder_nothing_is_asked_or_kept(self):
        os.rmdir(self.media)  # the add-on has no `map: media` (an old install): the repeat is simply off
        with self.assertLogs('iq_edge.briefing', level='INFO'):
            self.assertFalse(briefing.guardar_ultimo(SPEECH, 'pt', self.cfg))
        self.assertEqual((self.ha.tts_requests, self.last.exists(), self.media.exists()), ([], False, False))  # never created here

    def test_the_download_is_bounded(self):
        with mock.patch.object(briefing, '_LIMITE_AUDIO', 100):
            self.assertIsNone(briefing.baixar_audio_da_fala(SPEECH, 'pt', self.cfg))
        self.assertEqual(briefing.baixar_audio_da_fala(SPEECH, 'pt', self.cfg), (AUDIO, 'mp3'))

    def test_after_a_spoken_bom_dia_it_is_kept_after_the_end_event_and_the_volume(self):
        order = []
        levels = [0.2, 0.4]  # the speaker was at 20%; during the speech it is at the Bom dia's 40%

        def keep(fala, idioma, cfg):
            order.append('guardar')
            return briefing.guardar_ultimo(fala, idioma, cfg)
        briefing.handle('bom dia automatico', publish_fn=lambda cards, seconds: True, spawn_fn=lambda job: job(),
                        sleep_fn=lambda seconds: None, get_volume_fn=lambda entity: levels.pop(0),
                        set_volume_fn=lambda entity, level: order.append(('volume', level)) or True,
                        wait_fn=lambda entity, seconds: None, done_fn=lambda spoken, language: order.append(('done', spoken)),
                        speak_fn=lambda fala, idioma, cfg: order.append('fala') or True, guardar_fn=keep)
        self.assertEqual(order, [('volume', 0.4), 'fala', ('volume', 0.2), ('done', True), 'guardar'])
        self.assertEqual(briefing.ultimo_bom_dia()[0], 'ok')
        self.assertEqual(self.audio.read_bytes(), AUDIO)

    def test_the_voice_request_and_the_default_saver_of_handle(self):
        """handle() keeps the audio by itself (the default saver) when the speaker spoke, and not when it did not."""
        done = []
        for speaks in (True, False):
            self.last.unlink(missing_ok=True)
            briefing.handle('bom dia automatico', publish_fn=lambda cards, seconds: True, spawn_fn=lambda job: job(),
                            sleep_fn=lambda seconds: None, get_volume_fn=lambda entity: None, done_fn=lambda spoken, language: done.append(spoken),
                            speak_fn=lambda fala, idioma, cfg: speaks)
            self.assertEqual(self.last.exists(), speaks)
        self.assertEqual(done, [True, False])

    def test_only_the_satellite_speaking_forgets_the_old_audio(self):
        self.keep()
        cfg = dict(self.cfg, satellite='assist_satellite.sala', atraso=0.0)
        briefing._entregar_no_alto_falante(SPEECH, 'pt', cfg, lambda *a: False, lambda *a: False, lambda s: None, guardar_fn=briefing.guardar_ultimo)
        self.assertTrue(self.audio.exists() and self.last.exists())  # nothing was spoken: the last real one stays
        briefing._entregar_no_alto_falante(SPEECH, 'pt', cfg, lambda *a: False, lambda *a: True, lambda s: None, guardar_fn=briefing.guardar_ultimo)
        self.assertFalse(self.audio.exists() or self.last.exists())  # spoken by the satellite: no audio of it, so not the older one
        self.keep()
        briefing._anunciar_no_satelite(SPEECH, 'pt', 'assist_satellite.sala', lambda *a: True, lambda *a: None, lambda s: None, lambda: 0.0)
        self.assertFalse(self.audio.exists() or self.last.exists())


class RepeatTests(RepeatCase):
    def test_it_plays_the_kept_file_on_the_speaker(self):
        self.keep()
        before = self.audio.read_bytes()
        answer, plays = self.repeat()
        self.assertEqual(answer, 'ok')
        self.assertEqual(plays, [('media_player.sala', 'mp3', settings.read_json(self.last)['seconds'])])
        self.assertEqual(self.audio.read_bytes(), before)  # the same file, untouched

    def test_the_play_media_body(self):
        self.keep()
        before = len(self.ha.log)
        answer, _ = self.repeat(play_fn=None)  # the real play (HTTP to the fake Home Assistant)
        self.assertEqual(answer, 'ok')
        self.assertEqual(self.ha.service_calls[-1], ('/api/services/media_player/play_media', {
            'entity_id': 'media_player.sala', 'media_content_id': 'media-source://media_source/local/iq-edge/bom-dia.mp3',
            'media_content_type': 'music', 'announce': True}))
        self.assertEqual(self.voice_requests(before), [])

    def test_it_never_asks_for_a_voice_nor_fires_the_end_event(self):
        """The whole repeat, real requests to the fake Home Assistant, the satellite chosen and the play failing: not a single request
        to tts.speak, tts_get_url, the audio proxy or assist_satellite.announce, and no iq_bom_dia_done."""
        self.keep()
        self.ha.service_calls.clear()
        del self.ha.tts_requests[:]
        before = len(self.ha.log)
        with mock.patch.dict(os.environ, {'IQ_BRIEFING_SATELLITE': 'assist_satellite.sala'}):
            for play in (None, lambda cfg, extension, seconds: False):  # played; and refused by Home Assistant (no fallback)
                answer, _ = self.repeat(play_fn=play, get_volume_fn=briefing.get_speaker_volume, set_volume_fn=briefing.set_speaker_volume)
                self.assertEqual(answer, 'ok')
        self.assertEqual(self.voice_requests(before), [])
        self.assertEqual(self.ha.tts_requests, [])
        self.assertEqual([call for call in self.ha.service_calls if 'tts' in call[0] or 'satellite' in call[0]], [])
        self.assertEqual(self.ha.events, [])  # no iq_bom_dia_done, no cards
        self.assertEqual(len([call for call in self.ha.service_calls if call[0].endswith('/play_media')]), 1)

    def test_the_volume_rule_of_the_bom_dia(self):
        self.keep()
        events, levels = [], [0.2, 0.4]
        answer, _ = self.repeat(get_volume_fn=lambda entity: levels.pop(0),
                                set_volume_fn=lambda entity, level: events.append(('volume', level)) or True,
                                wait_fn=lambda entity, seconds: events.append(('wait', seconds)),
                                play_fn=lambda cfg, extension, seconds: events.append('play') or True)
        self.assertEqual(answer, 'ok')
        seconds = settings.read_json(self.last)['seconds']
        self.assertEqual(events, [('volume', 0.4), 'play', ('wait', seconds), ('volume', 0.2)])  # up for the play, back after it
        events.clear()
        levels[:] = [0.2, 0.3]  # someone moved it during the play: it stays
        self.repeat(get_volume_fn=lambda entity: levels.pop(0), set_volume_fn=lambda entity, level: events.append(('volume', level)) or True)
        self.assertEqual(events, [('volume', 0.4)])

    def test_the_reasons_for_playing_nothing(self):
        answer, plays = self.repeat()
        self.assertEqual((answer, plays), ('none', []))  # nothing kept yet
        self.keep()
        now = settings.parse_time(settings.read_json(self.last)['spoken_at'])
        for age, expected in ((timedelta(hours=19, minutes=59), 'ok'), (timedelta(hours=20), 'old'), (timedelta(days=3), 'old'),
                              (timedelta(minutes=-30), 'old')):  # a clock far in the future is no good either
            answer, plays = self.repeat(agora=now + age)
            self.assertEqual((answer, len(plays)), (expected, int(expected == 'ok')), age)
        self.audio.write_bytes(b'x' * len(AUDIO))  # same size, other content
        self.assertEqual(self.repeat()[0], 'missing')
        self.audio.write_bytes(AUDIO[:-1])
        self.assertEqual(self.repeat()[0], 'missing')
        self.audio.unlink()
        answer, plays = self.repeat()
        self.assertEqual((answer, plays), ('missing', []))
        self.keep()
        settings.write_json(self.last, dict(settings.read_json(self.last), spoken_at='not a date'))
        self.assertEqual(self.repeat()[0], 'none')
        self.last.write_text('[1, 2', encoding='utf-8')
        self.assertEqual(self.repeat()[0], 'none')

    def test_the_speaker_chosen_now_wins_and_without_one_nothing_plays(self):
        self.keep()
        prefs.save_local(self.prefs(speaker='media_player.cozinha'))
        answer, plays = self.repeat()
        self.assertEqual((answer, plays[0][0]), ('ok', 'media_player.cozinha'))
        prefs.save_local(self.prefs(speaker='', tts_engine=''))
        answer, plays = self.repeat()
        self.assertEqual((answer, plays), ('speaker', []))

    def test_a_bom_dia_being_spoken_or_an_earlier_repeat_blocks_it(self):
        self.keep()
        jobs = []
        self.assertEqual(self.repeat(spawn_fn=jobs.append)[0], 'ok')  # handed over, not run yet: it already counts as speaking
        self.assertEqual(self.repeat(), ('busy', []))  # a second one at the same time plays nothing
        jobs.pop()()  # the first one ends
        self.assertEqual(self.repeat()[0], 'ok')
        # a Bom dia delivery: handle() hands its task over wrapped, and while it runs a repeat plays nothing
        tasks, seen = [], []
        briefing.handle('bom dia automatico', publish_fn=lambda cards, seconds: True, spawn_fn=tasks.append, speak_fn=lambda *a: True)
        self.assertEqual(self.repeat()[0], 'ok')  # handed over but not started: the speaker is free
        with mock.patch.object(briefing, '_entregar_no_alto_falante', lambda *a, **k: seen.append(self.repeat()[0])):
            tasks[0]()
        self.assertEqual(seen, ['busy'])
        self.assertEqual(briefing._FALANDO, [0])
        self.assertEqual(self.repeat()[0], 'ok')  # and after it ends, it plays

    def test_an_error_while_handing_the_play_over_frees_the_repeat(self):
        self.keep()

        def broken(job):
            raise RuntimeError('no thread')
        with self.assertRaises(RuntimeError):
            self.repeat(spawn_fn=broken)
        self.assertEqual(self.repeat()[0], 'ok')
        self.assertEqual(briefing._FALANDO, [0])

    def test_a_play_that_raises_is_logged_and_frees_the_repeat(self):
        self.keep()

        def boom(cfg, extension, seconds):
            raise RuntimeError('boom')
        with self.assertLogs('iq_edge.briefing', level='WARNING'):
            self.assertEqual(self.repeat(play_fn=boom)[0], 'ok')
        self.assertEqual(self.repeat()[0], 'ok')

    def test_the_prefs_wrapper(self):
        self.keep()
        with mock.patch.object(briefing, 'repetir_ultimo', return_value='old') as repeat:
            self.assertEqual(prefs.repeat_last(), 'old')
        repeat.assert_called_once_with()
