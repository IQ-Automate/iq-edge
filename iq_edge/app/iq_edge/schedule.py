"""The Bom dia's automatic speech: at the time and on the days the client chose in the tab (prefs `schedule`), in the home's time
zone (Home Assistant's /api/config, read by the heartbeat; TZ of the container until then). Checked every 20 s; it speaks once per
day and time (kept in /data/state.json, so a restart in the same minute does not speak twice) and up to 2 minutes late (a busy
moment). The owner's Orange Pi keeps its own trigger in Home Assistant; this is only the add-on's."""
import logging
import threading
from datetime import datetime, timedelta

from . import prefs

TICK = 20
LATE = timedelta(minutes=2)
logger = logging.getLogger('iq_edge.schedule')


def _zone(name):
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:  # unknown name or no time zone database
        return None


def due(now, schedule, last):
    """True when `now` (local time of the home) is the chosen time of a chosen day, or up to LATE after it, and it did not speak yet."""
    if not isinstance(schedule, dict) or not schedule.get('days'):
        return False
    try:
        hour, minute = (int(x) for x in str(schedule.get('time')).split(':'))
    except ValueError:
        return False
    if now.weekday() not in schedule['days']:
        return False
    at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    key = at.strftime('%Y-%m-%d %H:%M')
    return at <= now < at + LATE and last != key


class Scheduler:
    def __init__(self, zone_name=lambda: '', speak=prefs.speak_now, clock=None):
        self.zone_name, self.speak, self.clock = zone_name, speak, clock
        self.stop = threading.Event()

    def now(self):
        if self.clock:
            return self.clock()
        zone = _zone(self.zone_name())
        return datetime.now(zone) if zone else datetime.now().astimezone()

    def tick(self):
        """One check; True when it spoke."""
        schedule = prefs.load()[1].get('schedule')
        now = self.now()
        last = prefs.state().get('last_spoken')
        if not due(now, schedule, last):
            return False
        prefs.set_state(last_spoken=now.replace(hour=int(schedule['time'][:2]), minute=int(schedule['time'][3:]), second=0,
                                                microsecond=0).strftime('%Y-%m-%d %H:%M'))
        spoken, _ = self.speak()
        logger.info('Bom dia automático: %s.', 'falando' if spoken else 'sem alto-falante e motor de voz escolhidos')
        return spoken

    def run(self):
        while not self.stop.wait(TICK):
            try:
                self.tick()
            except Exception:
                logger.exception('Erro no Bom dia automático.')
