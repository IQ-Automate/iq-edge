"""Lote A5: the Bom dia written by the center's AI (POST briefing-compose, contract v2) against the FAKE center and HA (tests/fakes.py).
The body has the contract's shape and goes with the credential; `text` and `picks` are used (speech and cards); 401/410/422/429/502/503,
a non-JSON answer, no center or an unpaired home → the rule text, one try only, nothing personal in the log; the tab's status line."""
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from unittest import mock

from iq_edge import briefing, prefs, settings
from iq_edge.center import Center, NoAI
from tests.fakes import EdgeCase

PICKS = {'text': 'Bom dia, Franco. Chuva forte à tarde.', 'picks': [{'source': 'Cidade', 'indices': [1]}], 'model': 'gpt-4o-mini', 'words': 7}


class ComposeCase(EdgeCase):
    def setUp(self):
        super().setUp()
        self.edge = Center()
        self.assertEqual(self.edge.pair('123456'), (True, ''))
        self.center.log.clear()
        briefing.usar_centro(self.edge)
        self.addCleanup(briefing.usar_centro, None)
        prefs.save_local(self.prefs())

    def speak(self):
        """The whole Bom dia ("Falar agora" path) with the speech itself caught: (text spoken, cards published)."""
        spoken, cards = [], []
        briefing.handle('bom dia automatico', publish_fn=lambda c, d: cards.append(c) or True,
                        spawn_fn=lambda job: spoken.append(job), speak_fn=lambda *a: True)
        return spoken, cards


class ComposeTests(ComposeCase):
    def test_text_and_picks_from_the_center_and_the_body_of_the_contract(self):
        self.center.compose_answer = (200, PICKS, {})
        answer = prefs.preview(self.prefs())
        self.assertEqual(answer['text'], PICKS['text'])
        sent = self.center.composed[0]
        self.assertEqual((sent['headers']['Authorization'], sent['headers']['X-IQ-Edge-Home'], sent['headers']['X-IQ-Edge-Contract']),
                         ('Bearer ' + 'C' * 43, 'home-1', '2'))
        self.assertLessEqual(sent['size'], 64 * 1024)
        body = sent['body']
        self.assertEqual(set(body), {'language', 'max_words', 'rules', 'house_state', 'facts', 'candidates'})
        self.assertEqual((body['language'], body['max_words'], body['house_state']), ('pt', 120, True))
        self.assertEqual(set(body['facts']), {'names', 'weather', 'open', 'alarm'})
        self.assertEqual((body['facts']['names'], body['facts']['weather'], body['facts']['open'], body['facts']['alarm']),
                         (['Franco'], None, [], None))  # weather off in these prefs; nothing open; no alarm
        self.assertEqual(body['candidates'], [{'source': 'Cidade', 'limit': 2,
                                               'titles': ['Prefeitura anuncia obras na avenida', 'Chuva forte prevista para a tarde']}])
        self.assertIn('total', body['rules'].lower())
        # the cards use the center's pick (index 1), the speech is the center's text
        self.center.compose_answer = (200, PICKS, {})
        spoken, cards = self.speak()
        self.assertEqual([c['linhas'] for c in cards[0] if c['titulo'] == 'Cidade'], [['Chuva forte prevista para a tarde']])
        self.assertEqual(len(spoken), 1)
        self.assertTrue(self.edge.public()['ai_ok'])

    def test_every_error_is_the_rule_text_after_one_try(self):
        cases = ((503, {'error': 'no_key'}, {}, 'no_key'), (429, {'error': 'rate'}, {'Retry-After': '600'}, 'rate'),
                 (502, {'error': 'ai_failed'}, {}, 'ai_failed'), (422, {'error': 'invalid: facts'}, {}, 'invalid'),
                 (410, {'error': 'home_deleted'}, {}, 'home_deleted'), (500, {'error': 'server'}, {}, 'http_500'),
                 (200, b'<html>not json</html>', {}, 'bad_response'), (200, {'text': '  ', 'picks': []}, {}, 'bad_response'))
        for status, answer, headers, reason in cases:
            with self.subTest(status=status, reason=reason):
                self.center.composed.clear()
                self.center.compose_answer = (status, answer, headers)
                with self.assertLogs('iq_edge.briefing', level='WARNING') as logs:
                    text = prefs.preview(self.prefs())['text']
                self.assertTrue(text.startswith('Bom dia, Franco.'), text)
                self.assertIn('Prefeitura anuncia obras na avenida', text)  # the rule text with the rule's headlines
                self.assertEqual(len(self.center.composed), 1)  # one try
                self.assertIn(f'({reason})', logs.output[0])
                self.assertFalse(any('Franco' in line or 'Prefeitura' in line for line in logs.output))
                public = self.edge.public()
                self.assertIs(public['ai_ok'], False)
                self.assertTrue(public['ai_at'])
        self.assertTrue(self.edge.paired())  # 410 never forgets the credential

    def test_revoked_is_the_rule_text_and_the_loop_forgets_it(self):
        self.center.revoked = True
        with self.assertLogs('iq_edge.briefing', level='WARNING') as logs:
            self.assertTrue(prefs.preview(self.prefs())['text'].startswith('Bom dia, Franco.'))
        self.assertIn('(revoked)', logs.output[0])
        self.assertTrue(self.edge.paired())  # compose changes nothing; the loop's next call forgets it
        self.edge.last_heartbeat = self.edge.clock()
        self.edge.step()
        self.assertFalse(self.edge.paired())

    def test_no_center_or_unpaired_is_the_rule_text_without_a_call(self):
        self.center.stop()
        with self.assertLogs('iq_edge.briefing', level='WARNING') as logs:
            self.assertTrue(prefs.preview(self.prefs())['text'].startswith('Bom dia, Franco.'))
        self.assertIn('(offline)', logs.output[0])
        self.edge.forget()
        with self.assertRaises(NoAI) as error:
            self.edge.compose({'language': 'pt'})
        self.assertEqual(error.exception.reason, 'unpaired')
        logger = logging.getLogger('iq_edge.briefing')
        with mock.patch.object(logger, 'warning') as warning:
            self.assertTrue(prefs.preview(self.prefs())['text'].startswith('Bom dia, Franco.'))
        warning.assert_not_called()  # not paired: the rule text is the normal path, not a failure

    def test_a_preview_job_never_waits_past_its_deadline(self):
        self.center.compose_answer = (200, PICKS, {})
        self.edge.last_heartbeat = self.edge.clock()
        soon = (datetime.now(timezone.utc) + timedelta(seconds=6)).isoformat()
        job = self.center.queue('preview', {'prefs': self.prefs(), 'language': 'pt'}, job_id='v', deadline=soon)
        started = time.monotonic()
        self.edge.step()
        self.assertLess(time.monotonic() - started, 6)
        self.assertEqual(self.center.composed, [])  # too close to the deadline: no AI call at all
        self.assertTrue(self.center.results[job]['data']['text'].startswith('Bom dia, Franco.'))
        later = (datetime.now(timezone.utc) + timedelta(seconds=50)).isoformat()
        job = self.center.queue('preview', {'prefs': self.prefs(), 'language': 'pt'}, job_id='w', deadline=later)
        self.edge.step()
        self.assertEqual(self.center.results[job]['data']['text'], PICKS['text'])
        self.assertIsNone(getattr(self.edge._local, 'deadline', None))

    def test_the_status_tab_line(self):
        public = self.edge.public()
        self.assertEqual((public['ai_ok'], public['ai_at']), (None, None))
        self.center.compose_answer = (200, PICKS, {})
        prefs.preview(self.prefs())
        self.assertIs(self.edge.public()['ai_ok'], True)
        self.assertNotIn('C' * 43, json.dumps(self.edge.public()))


class OptionsKeptTests(EdgeCase):
    def test_pairing_clears_only_the_code_and_keeps_the_other_options(self):
        settings.write_json(settings.data_dir() / 'options.json', {'center_url': 'https://business.iqautom8.com', 'pairing_code': '123456',
                                                                   'weather_entity': 'weather.casa', 'speaker_wait': 12}, private=False)
        with mock.patch.dict(os.environ, {'IQ_PAIRING_CODE': '123456'}):
            self.assertEqual(Center().step(), 0)
        self.assertEqual(self.ha.options_posts, [{'options': {'center_url': self.center.url, 'pairing_code': '',
                                                              'weather_entity': 'weather.casa', 'speaker_wait': 12}}])
