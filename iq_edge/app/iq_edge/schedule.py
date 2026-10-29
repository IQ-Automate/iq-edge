"""The Bom dia's automatic speech: at the time and on the days the client chose in the tab (prefs `schedule`), in the home's time
zone (Home Assistant's /api/config, read by the heartbeat; TZ of the container until then). Checked every 20 s; it speaks once per
day and time (kept in /data/state.json, so a restart in the same minute does not speak twice) and up to 2 minutes late (a busy
moment). The owner's Orange Pi keeps its own trigger in Home Assistant; this is only the add-on's.

Lote A5: the Preparer composes the Bom dia ahead (ready.py) on the same tick: from `prepare_minutes` (30) before the chosen time on a
chosen day or, for a home without a schedule that uses Home Assistant's event iq_bom_dia (heard in the last 14 days), from
`prepare_at` (06:00); renewed every 30 minutes until it is spoken, up to 4 hours after that time, then discarded."""
import logging
import os
import threading
from datetime import datetime, timedelta, timezone

from . import briefing, prefs, ready

TICK = 20
LATE = timedelta(minutes=2)
logger = logging.getLogger('iq_edge.schedule')


_ZONE = {'name': '', 'at': 0.0}


def ha_time_zone():
    """The home's time zone from Home Assistant's /api/config (read again every hour; '' when it cannot be read): the schedule
    speaks at the home's local time even before the add-on is paired (the heartbeat keeps it fresh afterwards)."""
    import time
    from . import relay
    if time.monotonic() - _ZONE['at'] < 3600 and _ZONE['at']:
        return _ZONE['name']
    try:
        status, config = relay.call_ha('GET', '/api/config')
        name = str(config.get('time_zone') or '') if status == 200 and isinstance(config, dict) else ''
    except relay.RelayError:
        name = ''
    _ZONE.update(name=name, at=time.monotonic())
    return name


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


REFRESH = timedelta(minutes=30)
WINDOW_AFTER = timedelta(hours=4)
EVENT_RECENT = timedelta(days=14)


def _hhmm(value, default):
    try:
        hour, minute = (int(x) for x in str(value).split(':'))
        if 0 <= hour < 24 and 0 <= minute < 60:
            return hour, minute
    except ValueError:
        pass
    return default


def prepare_minutes():
    """IQ_BRIEFING_PREPARE_MINUTES (option prepare_minutes): 0 to 180, default 30; 0 turns the preparation off."""
    try:
        return max(0, min(180, int(os.getenv('IQ_BRIEFING_PREPARE_MINUTES', '') or 30)))
    except ValueError:
        return 30


def prepare_window(now, schedule, minutes, prepare_at, event_recent):
    """(start, end) of today's preparation in the home's local time, or None. A chosen day: `minutes` before the chosen time until
    4 h after it. No days chosen (the home speaks by Home Assistant's event): from `prepare_at` until 4 h after, only when the event
    was heard in the last 14 days. A day not chosen, minutes 0 or nothing to trigger it: None."""
    if minutes <= 0:
        return None
    days = (schedule or {}).get('days') if isinstance(schedule, dict) else None
    if days:
        if now.weekday() not in days:
            return None
        hour, minute = _hhmm(schedule.get('time'), (7, 0))
        at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return at - timedelta(minutes=minutes), at + WINDOW_AFTER
    if not event_recent:
        return None
    hour, minute = _hhmm(prepare_at, (6, 0))
    at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return at, at + WINDOW_AFTER


def _parse(value):
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


class Preparer:
    """Keeps the prepared Bom dia fresh inside today's window (prepare_window): prepares when there is none, it is 30 minutes old or
    the preferences changed; stops once the Bom dia was spoken in the window; discards it when the window ends. Only when something
    can speak it (a speaker with a voice engine, or the reserve satellite). The composing runs on its own thread (`spawn`)."""

    def __init__(self, prepare=ready.prepare, spawn=None, can_speak=None):
        self.prepare = prepare
        self.spawn = spawn or (lambda job: threading.Thread(target=job, name='iq-edge-prepare', daemon=True).start())
        self.can_speak = can_speak or (lambda: briefing.speaker_config() is not None or bool(briefing.satellite()))
        self.busy = threading.Lock()

    def tick(self, now):
        """One check at `now` (the home's local time). True when a preparation started."""
        now = now if now.tzinfo else now.astimezone()
        state = prefs.state()
        heard = _parse(state.get('last_event_at'))
        window = prepare_window(now, prefs.load()[1].get('schedule'), prepare_minutes(),
                                os.getenv('IQ_BRIEFING_PREPARE_AT', '').strip() or '06:00',
                                bool(heard and now - heard < EVENT_RECENT))
        data = ready.load()
        if window is None or not window[0] <= now < window[1]:
            if data and ((window and now >= window[1]) or ready.age(data, now) >= ready.MAX_AGE):
                ready.discard()
            return False
        spoken = _parse(state.get('last_spoken_at'))
        if (spoken and spoken >= window[0]) or not self.can_speak():
            return False
        language = briefing.idioma_automatico()
        if data and data.get('language') == language and data.get('key') == briefing.chave_preparo(language) \
                and ready.age(data, now) < REFRESH:
            return False
        if not self.busy.acquire(blocking=False):
            return False  # the last one is still composing

        def job():
            try:
                self.prepare(language, now)
            except Exception:
                logger.exception('Erro ao preparar o Bom dia.')
            finally:
                self.busy.release()
        self.spawn(job)
        return True


class Scheduler:
    def __init__(self, zone_name=lambda: '', speak=prefs.speak_now, clock=None, preparer=None):
        self.zone_name, self.speak, self.clock, self.preparer = zone_name, speak, clock, preparer
        self.stop = threading.Event()

    def now(self):
        if self.clock:
            return self.clock()
        zone = _zone(self.zone_name())
        return datetime.now(zone) if zone else datetime.now().astimezone()

    def tick(self):
        """One check; True when it spoke. Then the preparation of the Bom dia (when there is a Preparer)."""
        schedule = prefs.load()[1].get('schedule')
        now = self.now()
        last = prefs.state().get('last_spoken')
        if not due(now, schedule, last):
            if self.preparer:
                self.preparer.tick(now)
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
