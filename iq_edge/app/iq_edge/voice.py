"""The voice router (lote J1b, 0.2.5): a spoken request comes in (voice_http.py), the IQ center says where it goes, and the answer is
spoken back.

  1. mode `off` (the option voice_route) or a text over 500 characters: the center is not asked, the request goes to the agent.
  2. otherwise the center decides (Center.voice_route): `local` goes to Home Assistant's own assistant (POST /api/conversation/process
     with agent_id conversation.home_assistant); `agent` goes to the agent the person chose. The add-on never turns `agent` into
     `local`: a sensitive request (lock, alarm, garage, turn everything off) is `agent` at the center and stays there.

The agent is one of two kinds. By address (option voice_agent_url, 0.2.5): the request is handed over UNTOUCHED, the very bytes Home
Assistant sent (user_id, device_id, device_info and the exposed entities included: the old server needs them to know who speaks and
from where), by POST with Basic authentication when voice_agent_user is set; its answer (status, content type, body) goes back to Home
Assistant unchanged (handle returns a Forwarded). By entity (option voice_agent, a conversation.* entity of Home Assistant): only the
words go, through /api/conversation/process; who speaks and the device are lost. The address wins when both are set. Every way into
the agent (mode off, observe, the center saying `agent`, the center failing, a long text, the local assistant failing) ends in the same
step (_to_agent).
  3. mode `observe`: the center is asked and its decision counted, but the request always goes to the agent.
  4. the house never loses its assistant: not paired, center down, slow (about 2 s), refusing or malformed = the agent; the local
     assistant answering with an error (it matched no intent) = the agent. No agent configured = a short spoken sentence says so; so
     does an address that is refused (not http or https, a user or password inside it, or this add-on's own listener: it would call
     itself) and an agent by address that cannot be reached or answers 5xx. A 4xx or 3xx of the agent is handed back as it is.

Every request ends in exactly one outcome, counted since the start (the tab shows them): `local` (the local assistant answered),
`agent` (the agent, by the center's decision, the mode or the text size), `fallback` (the agent, because the center could not answer
or the local assistant did not), `failed` (nobody answered: no agent, the agent failed or the choice is this router itself).

The words of a request live only in the call: never in a log, a counter, the memory below or the tab; nor does the agent's address,
user or password (and an exception of the HTTP library, which carries the address, is never logged: only a short code is kept). The
memory keeps only the conversation ids (the incoming one -> the id each Home Assistant agent gave back), bounded and expiring, so a
follow-up goes to the same conversation; the local assistant has its own conversation id (an agent by address has its own, inside the
request it gets)."""
import threading
import time
from collections import OrderedDict, namedtuple
from datetime import datetime, timezone

import requests

from . import relay, settings
from .center import NoRoute

MAX_ROUTE_TEXT = 500  # the center takes 1 to 500 characters: a longer request is not even sent
LOCAL_AGENT = 'conversation.home_assistant'
LOCAL_TIMEOUT = 10
AGENT_TIMEOUT = 60  # the integration's own timeout (default 30 s, up to 300) should be longer; DOCS.md says 90
AGENT_URL_TIMEOUT = (10, 90)  # an agent by address: seconds to connect, seconds to wait for its answer (the integration's own is 90)
MAX_AGENT_ANSWER = 4 * 1024 * 1024
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


Forwarded = namedtuple('Forwarded', 'status content_type body')  # an agent's answer, to go back to Home Assistant as it is (bytes)


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
        self.agent_session = requests.Session()  # an agent by address: its own session, no proxy from the environment
        self.agent_session.trust_env = False
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
            decision = self.center.voice_route(text, (language or 'pt').split('-')[0].split('_')[0].lower() or 'pt')
            problem = ''
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

    def _forward(self, address, raw):
        """(Forwarded or None, problem): the request's own bytes by POST to the agent's address. problem '' = a 2xx (hand it back);
        'http_<n>' for a 3xx or 4xx (handed back all the same, but it is a failure); for a 5xx, 'offline', 'timeout', 'bad_login',
        'too_big' there is no answer to hand back. No redirect is followed. Nothing is logged: the library's exceptions carry the
        address, so only their kind becomes a code."""
        user = settings.voice_agent_user()
        auth = (user, settings.voice_agent_password()) if user else None
        try:
            with self.agent_session.post(address, data=raw, headers={'Content-Type': 'application/json'}, auth=auth,
                                         timeout=AGENT_URL_TIMEOUT, allow_redirects=False, stream=True) as answer:
                chunks, size = [], 0
                for chunk in answer.iter_content(64 * 1024):
                    size += len(chunk)
                    if size > MAX_AGENT_ANSWER:
                        return None, 'too_big'
                    chunks.append(chunk)
                status, content_type = answer.status_code, answer.headers.get('Content-Type')
        except requests.Timeout:
            return None, 'timeout'
        except UnicodeError:  # a user or password that Basic authentication cannot carry
            return None, 'bad_login'
        except requests.RequestException:
            return None, 'offline'
        if status >= 500:
            return None, f'http_{status}'
        return Forwarded(status, content_type, b''.join(chunks)), '' if 200 <= status < 300 else f'http_{status}'

    def _to_agent(self, text, language, conversation_id, caller, raw, how):
        """The one way into the agent. An address wins over an entity; an address that is set but refused is never replaced by the
        entity (the person must see it is wrong): the spoken sentence says so."""
        address, refused = settings.voice_agent_url_state()
        if refused:
            self._count('failed')
            self._note('agent:' + ('itself' if refused == 'itself' else 'bad_url'))
            return spoken('loop' if refused == 'itself' else 'no_agent', language)
        if address and raw is not None:  # (without the request's bytes there is nothing to hand over: only the entity can answer)
            answer, problem = self._forward(address, raw)
            if problem:
                self._count('failed')
                self._note('agent:' + problem)
            else:
                self._count('fallback' if how == 'fallback' else 'agent')
            return answer if answer is not None else spoken('failed', language)
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

    def handle(self, text, language='', conversation_id='', caller='', raw=None):
        """What goes back to Home Assistant for one request: the text to speak (a str) or, from an agent by address, its own answer
        (a Forwarded). `caller` is the entity that sent it (the integration's own agent id), only to catch a router pointed at itself;
        `raw` is the request exactly as it arrived (bytes), which an agent by address gets untouched."""
        route, how = self.decide(text, language)
        if route == 'local':
            speech, problem = self._converse('local', LOCAL_AGENT, text, language, conversation_id, LOCAL_TIMEOUT)
            if not problem and speech:
                self._count('local')
                return speech
            self._note('local:' + (problem or 'empty'))
            how = 'fallback'  # Home Assistant's own assistant did not answer (no intent matched...): the agent does
        return self._to_agent(text, language, conversation_id, caller, raw, how)
