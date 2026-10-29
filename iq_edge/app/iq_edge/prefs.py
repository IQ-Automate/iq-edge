"""The home's Bom dia in the add-on: one file (/data/briefing-prefs.json, mode 600, written by briefing.gravar_prefs) that the tab
edits, the center's 'prefs' job replaces and the speech reads. Same format as contract v1 (the center's KEYS) + `schedule`
{time "HH:MM", days [0=Monday..6]} for the automatic speech. A save without `schedule` keeps the home's own.

The tab's "Salvar" writes here first (nothing is lost without internet) and marks it to be sent; the center answers with its version
number (then the file carries it). A change from the center is confirmed with the version it sent."""
import copy
import threading
from datetime import datetime, timezone

from . import briefing, ready, settings

DEFAULTS = {  # a new home, before anyone saved: weather and a few headlines in Portuguese; no speaker chosen yet
    'house_state': True, 'weather': True,
    'sources': [{'name': 'Brasil', 'url': 'https://g1.globo.com/rss/g1/'}, {'name': 'EUA', 'url': 'https://feeds.npr.org/1001/rss.xml'}],
    'picks': {'Brasil': 3, 'EUA': 2}, 'total_min': 4, 'total_max': 5, 'max_words': 150, 'rules': '',
    'speaker': '', 'volume': None, 'tts_engine': '', 'language': 'pt', 'temp_unit': 'language',
    'schedule': {'time': '07:00', 'days': []},
}
_LOCK = threading.Lock()


def _state_path():
    return settings.data_dir() / 'state.json'


def state():
    data = settings.read_json(_state_path(), {}) or {}
    return data if isinstance(data, dict) else {}


def set_state(**values):
    with _LOCK:
        data = state()
        data.update(values)
        settings.write_json(_state_path(), data, private=True)


def load():
    """(version, prefs, saved_at): the file when it is valid; (0, DEFAULTS, None) otherwise."""
    data = settings.read_json(briefing.prefs_path(), None)
    if isinstance(data, dict):
        try:
            return int(data.get('version') or 0), briefing.validar_prefs(data.get('prefs')), data.get('saved_at')
        except (TypeError, ValueError):
            pass
    return 0, copy.deepcopy(DEFAULTS), None


def _with_schedule(values):
    if isinstance(values, dict) and values.get('schedule') is None:
        current = load()[1].get('schedule')
        if current:
            values = dict(values, schedule=current)
    return values


def apply_from_center(version, values):
    """The center's 'prefs' job (contract v1's PUT): {"ok": true, "version": n, "saved_at": iso}. ValueError when invalid."""
    with _LOCK:
        answer = briefing.gravar_prefs(version, _with_schedule(values))
    set_state(prefs_pending=None)
    return answer


def save_local(values, user=None):
    """The tab's "Salvar": validated and written now (the version number stays until the center answers); marked to be sent."""
    clean = briefing.validar_prefs(_with_schedule(values))
    with _LOCK:
        briefing.gravar_prefs(max(load()[0], 1), clean)
    set_state(prefs_pending={'user': {'id': str((user or {}).get('id') or '')[:80], 'name': str((user or {}).get('name') or '')[:60]}})
    return clean


def mark_synced(version):
    """The center kept the tab's change as `version`: the file carries that number (same values)."""
    with _LOCK:
        current = load()[1]
        briefing.gravar_prefs(version, current)
    set_state(prefs_pending=None)


def pending():
    return state().get('prefs_pending')


def preview(values, language=None):
    """The text with these values (nothing spoken, nothing saved): the center's 'preview' job and the tab's "Testar"."""
    return briefing.preview(values, language)


def speak_now(language=None):
    """"Falar agora", the schedule and Home Assistant's event iq_bom_dia: the whole Bom dia on the chosen speaker (or, without one,
    on the reserve satellite) in the background. `language` ('pt'/'en') wins over the saved one. The Bom dia prepared ahead
    (ready.py) is used when it is under 2 hours old; otherwise it is composed now. (spoken?, text)."""
    if briefing.speaker_config() is None and not briefing.satellite():
        return False, ''
    language = language if language in ('pt', 'en') else briefing.idioma_automatico()
    text = briefing.handle('bom dia automatico', idioma_pedido=language, pronto=ready.fresh(language)) or ''
    if text != briefing._T[language]['falha_casa']:  # Home Assistant answered: the preparation of this morning can stop
        set_state(last_spoken_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
    return True, text
