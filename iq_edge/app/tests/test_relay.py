"""The allow-list of the center's 'ha' jobs, checked again in the home (relay.py), against the FAKE Home Assistant."""
import unittest
from unittest import mock

from iq_edge import relay
from tests.fakes import EdgeCase


class AllowListTests(unittest.TestCase):
    def test_only_what_the_contract_allows(self):
        good = [('GET', '/api/config'), ('GET', '/api/states'), ('GET', '/api/states/light.sala'), ('GET', '/api/services'),
                ('GET', '/api/config/automation/config/abc-1'), ('POST', '/api/config/script/config/boa_noite'),
                ('DELETE', '/api/config/scene/config/123'), ('POST', '/api/config/core/check_config')]
        bad = [('POST', '/api/services/light/turn_on'), ('GET', '/api/services/light'), ('POST', '/api/services'), ('POST', '/api/states/light.x'),
               ('DELETE', '/api/states'), ('POST', '/api/events/x'), ('POST', '/api/template'), ('GET', '/api/config?x=1'),
               ('GET', '/api/config/automation/config/../../x'), ('PUT', '/api/config'), ('GET', '/api/hassio/addons'), ('GET', '/api/'),
               ('GET', '/api/config/core/check_config'), ('GET', '/api/config/dashboard/config/x'), ('GET', 'http://evil/api/config'),
               (None, '/api/config'), ('GET', None)]
        for method, path in good:
            self.assertTrue(relay.allowed(method, path), (method, path))
        for method, path in bad:
            self.assertFalse(relay.allowed(method, path), (method, path))


class ExecuteTests(EdgeCase):
    def test_reads_writes_and_refusals(self):
        self.assertEqual(relay.execute({'method': 'GET', 'path': '/api/states/media_player.sala'})['data']['state'], 'idle')
        self.assertEqual(relay.execute({'method': 'GET', 'path': '/api/states/light.nada'}), {'ok': True, 'status': 404, 'data': {'message': 'Entity not found.'}})
        self.assertEqual(relay.execute({'method': 'POST', 'path': '/api/config/core/check_config'})['data']['result'], 'valid')
        self.assertEqual(relay.execute({'method': 'DELETE', 'path': '/api/config/automation/config/1'})['status'], 200)
        self.assertNotIn('1', self.ha.objects['automation'])
        self.assertEqual(relay.execute({'method': 'GET', 'path': '/api/config', 'body': {'x': 1}})['error'], 'invalid')
        self.assertEqual(relay.execute('x')['error'], 'invalid')
        self.assertEqual(relay.execute({'method': 'POST', 'path': '/api/services/lock/unlock', 'body': {}})['error'], 'forbidden')
        self.assertEqual(self.ha.requests_to('/core/api/services/'), [])

    def test_too_big_and_offline(self):
        with mock.patch.object(relay, 'MAX_RESPONSE', 100):
            self.assertEqual(relay.execute({'method': 'GET', 'path': '/api/states'})['error'], 'too_big')
        self.ha.stop()
        answer = relay.execute({'method': 'GET', 'path': '/api/config'})
        self.assertEqual((answer['ok'], answer['error']), (False, 'offline'))
        self.assertEqual(relay.home_snapshot()[1], 'ha_unreachable')


if __name__ == '__main__':
    unittest.main()
