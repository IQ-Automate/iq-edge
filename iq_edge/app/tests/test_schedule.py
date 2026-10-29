"""The Bom dia's automatic speech (schedule.py): the chosen days and time, up to 2 minutes late, once per day and time."""
import unittest
from datetime import datetime

from iq_edge import prefs, schedule
from tests.fakes import EdgeCase

PLAN = {'time': '07:00', 'days': [0, 1, 2, 3, 4]}  # Monday to Friday


class DueTests(unittest.TestCase):
    def test_days_time_and_once(self):
        monday = datetime(2026, 10, 26, 7, 0, 30)
        self.assertTrue(schedule.due(monday, PLAN, None))
        self.assertTrue(schedule.due(monday.replace(minute=1, second=50), PLAN, None))  # a bit late is fine
        self.assertFalse(schedule.due(monday.replace(minute=2, second=0), PLAN, None))
        self.assertFalse(schedule.due(monday.replace(hour=6, minute=59), PLAN, None))
        self.assertFalse(schedule.due(monday, PLAN, '2026-10-26 07:00'))  # already spoken
        self.assertFalse(schedule.due(datetime(2026, 10, 25, 7, 0, 30), PLAN, None))  # Sunday
        self.assertFalse(schedule.due(monday, {'time': '07:00', 'days': []}, None))
        self.assertFalse(schedule.due(monday, None, None))


class TickTests(EdgeCase):
    def test_speaks_once_at_the_time(self):
        prefs.save_local(self.prefs(schedule=PLAN))
        spoken = []
        clock = [datetime(2026, 10, 27, 7, 0, 10)]
        runner = schedule.Scheduler(speak=lambda: spoken.append(1) or (True, ''), clock=lambda: clock[0])
        self.assertTrue(runner.tick())
        self.assertFalse(runner.tick())  # the same minute again (or after a restart): nothing
        clock[0] = datetime(2026, 10, 28, 7, 1, 0)
        self.assertTrue(runner.tick())
        self.assertEqual(len(spoken), 2)
        self.assertEqual(prefs.state()['last_spoken'], '2026-10-28 07:00')

    def test_the_home_time_zone_comes_from_home_assistant(self):
        schedule._ZONE.update(name='', at=0.0)
        self.addCleanup(schedule._ZONE.update, name='', at=0.0)
        self.assertEqual(schedule.ha_time_zone(), 'America/New_York')
        runner = schedule.Scheduler(zone_name=schedule.ha_time_zone)
        if schedule._zone('America/New_York'):  # the image has tzdata (apk); a machine without a time zone database uses local time
            self.assertEqual(str(runner.now().tzinfo), 'America/New_York')
        self.assertIsNotNone(runner.now().tzinfo)


if __name__ == '__main__':
    unittest.main()
