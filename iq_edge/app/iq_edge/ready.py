"""The Bom dia prepared ahead (lote A5, the owner's request): the slow part (news feeds, weather forecast and the text by the center's
AI) is done before the speech, so "Falar agora", Home Assistant's event iq_bom_dia and the schedule speak at once.

/data/briefing-ready.json (mode 600) = {text, cards, weather_card, language, key, prepared_at}: the text WITHOUT the greeting, the
names and the house (open/alarm); those are added at the time of speech with the fixed sentences of the rule text
(briefing.prefixo_da_hora), so they are never old. `key` changes with the preferences and the IQ_BRIEFING_* options: a text
prepared for other values is never spoken. A prepared text is used for 2 hours at most. schedule.Preparer decides when to
prepare (from `prepare_minutes` before the schedule, or `prepare_at` for a home that uses the event) and when to discard.

After preparing, Home Assistant is asked (best effort) to generate and cache the voice of the speech as it would be now
(POST /api/tts_get_url, same engine, message, language and voice as tts.speak): when the house did not change (same people,
nothing new open), the speech comes from that cache. Nothing is played then."""
import logging
from datetime import datetime, timedelta, timezone

from . import briefing, settings

MAX_AGE = timedelta(hours=2)
logger = logging.getLogger('iq_edge.ready')


def path():
    return settings.data_dir() / 'briefing-ready.json'


def _utc(now=None):
    moment = now or datetime.now(timezone.utc)
    return (moment if moment.tzinfo else moment.astimezone()).astimezone(timezone.utc)


def load():
    data = settings.read_json(path(), None)
    return data if isinstance(data, dict) and isinstance(data.get('text'), str) else None


def prepared_at(data):
    try:
        moment = datetime.fromisoformat(str((data or {}).get('prepared_at')))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def age(data, now=None):
    """How old the prepared text is (a timedelta); very old when its time cannot be read."""
    moment = prepared_at(data)
    return _utc(now) - moment if moment else timedelta(days=365)


def discard():
    try:
        path().unlink()
    except OSError:
        pass


def fresh(language, now=None):
    """The prepared Bom dia when it can be spoken now: the same language, the same preferences and options, under 2 hours."""
    data = load()
    if not data or data.get('language') != language or data.get('key') != briefing.chave_preparo(language):
        return None
    return data if timedelta(0) <= age(data, now) < MAX_AGE else None


def prepare(language, now=None, precache=True, **fns):
    """Compose now and keep it; then (best effort) the voice in Home Assistant's cache. The kept dict, or None (no Home Assistant)."""
    result = briefing.preparar(language, **fns)
    if result is None:
        return None
    data, prefix = result
    data['prepared_at'] = _utc(now).isoformat(timespec='seconds')
    settings.write_json(path(), data)
    logger.info('Bom dia preparado (%s).', language)
    if precache:
        cfg = briefing.speaker_config()
        if cfg is not None:
            briefing.precache_tts(briefing.juntar_fala(prefix, data['text']), language, cfg)
    return data
