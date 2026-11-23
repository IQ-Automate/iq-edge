"""The voice router (lote J1b, 0.2.5): a spoken request comes in (voice_http.py), the IQ center says where it goes, and the answer is
spoken back.

  1. mode `off` (the option voice_route) or a text over 500 characters: the center is not asked, the request goes to the agent.
  2. otherwise the center decides (Center.voice_route): `local` goes to Home Assistant's own assistant (POST /api/conversation/process
     with agent_id conversation.home_assistant); `agent` goes to the agent the person chose (option voice_agent, a conversation.*
     entity: the old assistant, through Home Assistant itself). The add-on never turns `agent` into `local`: a sensitive request (lock,
     alarm, garage, turn everything off) is `agent` at the center and stays there.
  3. mode `observe`: the center is asked and its decision counted, but the request always goes to the agent.
  4. the house never loses its assistant: not paired, center down, slow (about 2 s), refusing or malformed = the agent; the local
     assistant answering with an error (it matched no intent) = the agent. No agent configured = a short spoken sentence says so.

Every request ends in exactly one outcome, counted since the start (the tab shows them): `local` (the local assistant answered),
`agent` (the agent, by the center's decision, the mode or the text size), `fallback` (the agent, because the center could not answer
or the local assistant did not), `failed` (nobody answered: no agent, the agent failed or the choice is this router itself).

The words of a request live only in the call: never in a log, a counter, the memory below or the tab. The memory keeps only the
conversation ids (the incoming one -> the id each Home Assistant agent gave back), bounded and expiring, so a follow-up goes to the
same conversation; the local assistant has its own conversation id."""
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone

from . import relay, settings
from .center import NoRoute

MAX_ROUTE_TEXT = 500  # the center takes 1 to 500 characters: a longer request is not even sent
LOCAL_AGENT = 'conversation.home_assistant'
LOCAL_TIMEOUT = 10
AGENT_TIMEOUT = 60  # the integration's own timeout (default 30 s, up to 300) should be longer; DOCS.md says 90
MEMORY_SIZE = 200
MEMORY_SECONDS = 30 * 60
SPOKEN = {
    'no_agent': ('O roteador de voz da IQ está sem assistente configurado. Escolha um nas opções do add-on.',
                 'The IQ voice router has no assistant configured. Choose one in the add-on options.'),
    'loop': ('O assistente escolhido no roteador é ele mesmo. Escolha outro nas opções do add-on.',
             'The assistant chosen in the router is the router itself. Choose another one in the add-on options.'),
    'failed': ('Não consegui falar com o assistente agora. Tente de novo em instantes.',
               'I could not reach the assistant right now. Please try again in a moment.'),
}


def spoken(code, language):
    """The router's own short sentence, in English when the request language is English, else in Portuguese."""
    portuguese, english = SPOKEN[code]
    return english if str(language or '').lower().startswith('en') else portuguese


class Memory:
    """(kind, incoming conversation id) -> the conversation id Home Assistant gave back; at most `size`, each kept `seconds`."""

    def __init__(self, size=MEMORY_SIZE, seconds=MEMORY_SECONDS, clock=time.monotonic):
        self.size, self.seconds, self.clock = size, seconds, clock
        self.items = OrderedDict()
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            found = self.items.get(key)
            if found is None:
                return ''
            if self.clock() - found[1] > self.seconds:
                del self.items[key]
                return ''
            return found[0]

    def put(self, key, value):
        with self.lock:
            now = self.clock()
            self.items.pop(key, None)
            self.items[key] = (value, now)
            while self.items and (len(self.items) > self.size or now - next(iter(self.items.values()))[1] > self.seconds):
                self.items.popitem(last=False)

    def __len__(self):
        with self.lock:
            return len(self.items)


class Router:
    def __init__(self, center, call_ha=None, clock=time.monotonic):
        self.center = center
        self.call_ha = call_ha or relay.call_ha
        self.clock = clock
        self.memory = Memory(clock=clock)
        self.lock = threading.Lock()
        self.since = datetime.now(timezone.utc).isoformat(timespec='seconds')
        self.counts = dict.fromkeys(('local', 'agent', 'fallback', 'failed', 'center_calls', 'center_ms', 'center_errors',
                                     'observed_local', 'observed_agent'), 0)
        self.problem = ''  # the last problem as a short code (never a word of a request)

    # ---- the tab's numbers ----

    def _count(self, *names, **extra):
        with self.lock:
            for name in names:
                self.counts[name] += 1
            for name, value in extra.items():
                self.counts[name] += value

    def _note(self, problem):
        with self.lock:
            self.problem = problem

    def stats(self):
        with self.lock:
            out = dict(self.counts, since=self.since, problem=self.problem)
        out['center_avg_ms'] = round(out['center_ms'] / out['center_calls']) if out['center_calls'] else None
        return out

    # ---- Home Assistant's conversation API ----

    def _ask_ha(self, agent_id, text, language, conversation_id, timeout):
        """(speech, conversation id, problem): problem '' = answered; 'offline', 'http_<n>', 'bad_response' = no answer;
        'error_response' (Home Assistant's response_type error: it did not understand, or the agent failed) keeps its speech."""
        body = {'text': text, 'agent_id': agent_id}
        if language:
            body['language'] = language
        if conversation_id:
            body['conversation_id'] = conversation_id
        try:
            status, data = self.call_ha('POST', '/api/conversation/process', body, timeout=timeout)
        except relay.RelayError:
            return '', '', 'offline'
        if status != 200:
            return '', '', f'http_{status}'
        response = data.get('response') if isinstance(data, dict) else None
        if not isinstance(response, dict):
            return '', '', 'bad_response'
        block = response.get('speech')
        plain = block.get('plain') if isinstance(block, dict) else None
        speech = plain.get('speech') if isinstance(plain, dict) else ''
        speech = speech.strip() if isinstance(speech, str) else ''
        new_id = data.get('conversation_id')
        new_id = new_id if isinstance(new_id, str) and 0 < len(new_id) <= 200 else ''
        if response.get('response_type') == 'error':
            return speech, new_id, 'error_response'
        return speech, new_id, '' if speech else 'bad_response'

    def _converse(self, kind, agent_id, text, language, incoming, timeout):
        key = (kind, incoming) if incoming else None
        speech, new_id, problem = self._ask_ha(agent_id, text, language, self.memory.get(key) if key else '', timeout)
        if key and new_id:
            self.memory.put(key, new_id)
        return speech, problem

    # ---- the flow ----

    def decide(self, text, language):
        """(route, how): route 'local' or 'agent'; how '' (the center decided or the mode says so) or 'fallback' (mode on and the
        center could not answer). Mode observe asks the center and counts its decision, but the route is always 'agent'."""
        mode = settings.voice_route_mode()
        if mode == 'off' or len(text) > MAX_ROUTE_TEXT:
            return 'agent', ''
        started = self.clock()
        try:
            decision, problem = self.center.voice_route(text, (language or 'pt').split('-')[0].split('_')[0].lower() or 'pt'), ''
        except NoRoute as error:
            decision, problem = None, str(error.reason)
        if problem != 'unpaired':  # a home that is not paired makes no call: it is not part of the average
            self._count('center_calls', center_ms=max(0, round((self.clock() - started) * 1000)))
        if decision is None:
            self._count('center_errors')
            self._note('center:' + problem)
            return 'agent', 'fallback' if mode == 'on' else ''
        if mode == 'observe':
            self._count('observed_' + decision['route'])
            return 'agent', ''
        return decision['route'], ''

    def handle(self, text, language='', conversation_id='', caller=''):
        """The text to speak for one request. `caller` is the entity that sent it (the integration's own agent id), only to catch a
        router pointed at itself."""
        route, how = self.decide(text, language)
        if route == 'local':
            speech, problem = self._converse('local', LOCAL_AGENT, text, language, conversation_id, LOCAL_TIMEOUT)
            if not problem and speech:
                self._count('local')
                return speech
            self._note('local:' + (problem or 'empty'))
            how = 'fallback'  # Home Assistant's own assistant did not answer (no intent matched...): the agent does
        agent = settings.voice_agent()
        if not agent:
            self._count('failed')
            self._note('agent:none')
            return spoken('no_agent', language)
        if agent == str(caller or '').strip().lower():
            self._count('failed')
            self._note('agent:itself')
            return spoken('loop', language)
        speech, problem = self._converse('agent', agent, text, language, conversation_id, AGENT_TIMEOUT)
        if problem:  # no answer, or an error response: its sentence (when there is one) is spoken, but it counts as a failure
            self._count('failed')
            self._note('agent:' + problem)
            return speech if problem == 'error_response' and speech else spoken('failed', language)
        self._count('fallback' if how == 'fallback' else 'agent')
        return speech
