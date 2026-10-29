"""The add-on against a FAKE center and a FAKE Home Assistant (tests/fakes.py): pairing with the options' code (and the code leaves the
options), a refused code is never sent again by itself, poll → run → result, a forbidden path is refused here, the heartbeat, prefs
and preview jobs, the client's Bom dia sent (and re-sent after a failure), rotation, revocation, back-off and an expired job never runs."""
import json
import os
import stat
import unittest
from unittest import mock

from iq_edge import center as center_module, prefs
from iq_edge.center import Center
from tests.fakes import EdgeCase


class PairingTests(EdgeCase):
    def test_pairs_with_the_options_code_and_clears_it(self):
        from iq_edge import settings
        settings.write_json(settings.data_dir() / 'options.json', {'center_url': 'https://business.iqautom8.com', 'pairing_code': '123456'},
                            private=False)
        with mock.patch.dict(os.environ, {'IQ_PAIRING_CODE': '123 456'}):
            edge = Center()
            self.assertEqual(edge.step(), 0)
        self.assertTrue(edge.paired())
        saved = json.loads(edge.path().read_text(encoding='utf-8'))
        self.assertEqual((saved['home_id'], saved['home_name'], saved['credential']), ('home-1', 'Casa <Teste>', 'C' * 43))
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(os.stat(edge.path()).st_mode), 0o600)
        self.assertEqual(self.center.pair_info['code'], '123456')
        self.assertEqual((self.center.pair_info['addon_version'], self.center.pair_info['arch'], self.center.pair_info['ha_version']),
                         ('0.2.0', 'amd64', '2026.10.4'))
        self.assertEqual(self.ha.options_posts, [{'options': {'center_url': self.center.url, 'pairing_code': ''}}])
        public = edge.public()
        self.assertEqual((public['state'], public['paired'], public['home_name']), ('paired', True, 'Casa <Teste>'))
        self.assertNotIn('C' * 43, json.dumps(public))

    def test_unreadable_options_are_never_written_back(self):
        from iq_edge import settings
        with mock.patch.dict(os.environ, {'IQ_PAIRING_CODE': '123456'}), self.assertLogs('iq_edge.center', level='WARNING') as logs:
            self.assertEqual(Center().step(), 0)  # no options.json: paired, but the Supervisor is never asked to replace the options
        self.assertEqual(self.ha.options_posts, [])
        self.assertIn('Não consegui ler as opções', logs.output[0])
        (settings.data_dir() / 'options.json').write_text('{not json', encoding='utf-8')
        Center().clear_option_code()
        self.assertEqual(self.ha.options_posts, [])

    def test_a_refused_code_is_not_sent_again_by_itself(self):
        with mock.patch.dict(os.environ, {'IQ_PAIRING_CODE': '999999'}):
            edge = Center()
            self.assertEqual(edge.step(), 5)
            self.assertEqual(edge.step(), 5)
        self.assertEqual(len([e for e in self.center.log if e[1] == 'pair']), 1)
        self.assertEqual(edge.public()['state'], 'code_refused')
        self.assertEqual(edge.pair('12-34-5'), (False, 'format'))
        self.assertEqual(edge.pair('123456'), (True, ''))  # a new code (typed in the tab) works

    def test_no_code_no_call(self):
        edge = Center()
        self.assertEqual(edge.step(), 5)
        self.assertEqual(self.center.log, [])


class PairedCase(EdgeCase):
    def setUp(self):
        super().setUp()
        self.edge = Center()
        self.assertEqual(self.edge.pair('123456'), (True, ''))
        self.center.log.clear()


class JobTests(PairedCase):
    def test_heartbeat_then_poll_run_and_answer(self):
        job = self.center.queue('ha', {'method': 'GET', 'path': '/api/config'})
        self.assertEqual(self.edge.step(), 0)
        beat = self.center.heartbeats[0]
        self.assertEqual((beat['ha_version'], beat['health'], beat['addon_version'], beat['programs']),
                         ('2026.10.4', 'ok', '0.2.0', {'automations': 1, 'scripts': 0, 'scenes': 0}))
        self.assertEqual(self.center.results[job], {'ok': True, 'status': 200, 'data': self.ha.config})
        self.assertEqual(self.edge.time_zone, 'America/New_York')
        self.assertEqual(self.edge.step(), 0.0)  # nothing queued: 204, poll again at once
        self.assertEqual(len(self.center.heartbeats), 1)  # the next one only in 5 minutes

    def test_writes_and_the_allow_list(self):
        self.edge.last_heartbeat = self.edge.clock()
        write = self.center.queue('ha', {'method': 'POST', 'path': '/api/config/automation/config/2', 'body': {'alias': 'Nova'}}, job_id='w')
        self.edge.step()
        self.assertEqual((self.center.results[write]['status'], self.ha.objects['automation']['2']['alias']), (200, 'Nova'))
        rejected = self.center.queue('ha', {'method': 'POST', 'path': '/api/config/automation/config/3', 'body': {'bogus': 1}}, job_id='r')
        self.edge.step()
        self.assertEqual((self.center.results[rejected]['status'], self.center.results[rejected]['data']['message'][:17]), (400, 'Message malformed'))
        for index, (method, path) in enumerate((('POST', '/api/services/light/turn_on'), ('GET', '/api/services/light/turn_on'),
                                                 ('POST', '/api/events/x'), ('GET', '/api/template'), ('DELETE', '/api/states/light.x'),
                                                 ('GET', '/api/config?x=1'), ('GET', '/api/config/automation/config/../x'))):
            job = self.center.queue('ha', {'method': method, 'path': path}, job_id=f'f{index}')
            self.edge.step()
            self.assertEqual(self.center.results[job]['error'], 'forbidden', path)
        self.assertEqual(self.ha.requests_to('/core/api/services/'), [])
        self.assertEqual(self.ha.requests_to('/core/api/events'), [])

    def test_prefs_and_preview_jobs(self):
        self.edge.last_heartbeat = self.edge.clock()
        prefs.save_local(self.prefs(schedule={'time': '06:30', 'days': [0, 2]}))
        job = self.center.queue('prefs', {'version': 4, 'prefs': self.prefs(max_words=90)}, job_id='p')
        self.edge.step()
        self.assertEqual((self.center.results[job]['ok'], self.center.results[job]['data']['version']), (True, 4))
        version, values, _ = prefs.load()
        self.assertEqual((version, values['max_words'], values['schedule']), (4, 90, {'time': '06:30', 'days': [0, 2]}))  # the home's schedule stays
        bad = self.center.queue('prefs', {'version': 5, 'prefs': {'sources': []}}, job_id='b')
        self.edge.step()
        self.assertEqual((self.center.results[bad]['ok'], self.center.results[bad]['error']), (False, 'refused'))
        preview = self.center.queue('preview', {'prefs': self.prefs(), 'language': 'pt'}, job_id='v')
        self.edge.step()
        answer = self.center.results[preview]
        self.assertTrue(answer['ok'], answer)
        self.assertIn('Franco', answer['data']['text'])
        self.assertIn('Prefeitura anuncia obras', answer['data']['text'])
        self.assertEqual(prefs.load()[0], 4)  # the test saved nothing
        self.assertEqual(self.ha.requests_to('/core/api/services/tts'), [])  # and spoke nothing
        ping = self.center.queue('ping', {}, job_id='g')
        self.edge.step()
        self.assertEqual(self.center.results[ping]['data'], {'pong': True, 'addon_version': '0.2.0'})

    def test_an_expired_job_never_runs(self):
        self.edge.last_heartbeat = self.edge.clock()
        late = self.center.queue('ha', {'method': 'POST', 'path': '/api/config/automation/config/9', 'body': {'alias': 'Tarde'}},
                                 job_id='late', deadline='2020-01-01T00:00:00+00:00')
        self.edge.step()
        self.assertNotIn(late, self.center.results)
        self.assertNotIn('9', self.ha.objects['automation'])


class LifeTests(PairedCase):
    def test_the_clients_bom_dia_goes_to_the_center_now_or_later(self):
        prefs.save_local(self.prefs(), {'id': 'u1', 'name': 'Franco'})
        self.assertEqual(self.edge.send_prefs(self.prefs(), {'id': 'u1', 'name': 'Franco'}), 8)
        self.assertEqual(self.center.prefs[0]['user'], {'id': 'u1', 'name': 'Franco'})
        self.center.stop()  # no center: kept here, sent by the loop when it is back
        self.assertIsNone(self.edge.send_prefs(self.prefs(), {}))
        self.assertTrue(prefs.pending())

    def test_rotation_every_30_days(self):
        self.assertFalse(self.edge.rotate_if_due())
        data = self.edge.credential()
        from iq_edge import settings
        settings.write_json(self.edge.path(), dict(data, rotated_at='2020-01-01T00:00:00+00:00'))
        self.assertTrue(self.edge.rotate_if_due())
        self.assertEqual(self.edge.credential()['credential'], 'R' * 43)
        self.edge.last_heartbeat = self.edge.clock()
        self.assertEqual(self.edge.step(), 0.0)  # the new credential works

    def test_revoked_forgets_the_credential(self):
        self.center.revoked = True
        self.edge.last_heartbeat = self.edge.clock()
        self.assertEqual(self.edge.step(), 5)
        self.assertFalse(self.edge.paired())
        self.assertEqual(self.edge.public()['problem'], 'revoked')

    def test_unpair_from_the_tab(self):
        self.assertTrue(self.edge.unpair({'name': 'Franco'}))
        self.assertEqual(self.center.log[-1], ('POST', 'unpair', {'user': {'name': 'Franco'}}))
        self.assertFalse(self.edge.paired())

    def test_backoff_without_the_center(self):
        self.center.stop()
        self.edge.last_heartbeat = self.edge.clock()
        self.assertEqual([self.edge.step() for _ in range(8)], [1, 2, 4, 8, 15, 30, 60, 60])
        self.assertTrue(self.edge.paired())  # no contact is not a revocation
        self.assertEqual(self.edge.public()['problem'], 'offline')

    def test_nothing_secret_in_the_log(self):
        with self.assertLogs('iq_edge', level='INFO') as logs:
            center_module.logger.info('marker')
            self.edge.unpair({})
            self.edge.pair('000000')
        self.assertFalse(any('C' * 43 in line or '000000' in line or '123456' in line for line in logs.output))


if __name__ == '__main__':
    unittest.main()
