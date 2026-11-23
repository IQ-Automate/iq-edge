"""The voice router's door (lote J1b, 0.2.5): a second small HTTP server, on its own port (8098), for Home Assistant Core's community
integration "webhook-conversation" (EuleMitKeule/webhook-conversation, versions 1.x). Core reaches it on the Supervisor's internal network
at http://<this add-on's host name>:8098/v1/conversation; config.yaml does not publish the port on the host.

The integration's request (POST, JSON, one per spoken sentence; every field but the text is ignored):
  query            the latest user message (the text)            -- used; without it, the last "user" item of `messages`
  conversation_id  the conversation's id                          -- used (a follow-up goes to the same conversation)
  language         "pt-BR", "en", ...                             -- used
  agent_id         the integration's own entity (conversation.x)  -- used only to catch a router pointed at itself
  user_id, user_name, device_id, device_info, messages, system_prompt, exposed_entities (a JSON text or a list), stream -- ignored
With an agent by address (option voice_agent_url) the request is not rebuilt: its bytes go to the agent as they came (user_id, device_id,
device_info and the rest included) and the agent's answer goes back as it is: status, content type and body (voice.Forwarded).
The answer: `{"output": "<speech>"}` (the integration's default output field) or, when the request says `"stream": true`
(the integration's "response streaming"), its line format: {"type":"begin"}, {"type":"item","content":"<speech>"}, {"type":"end"},
one JSON per line. Anything else it may add (tool_calls...) is not used.

Basic authentication on every request (the integration supports only that): user `iq`, the password the add-on made on its first start
(/data/voice.json, mode 600; the tab shows it behind Home Assistant's login). It is compared in constant time and never logged.
Only POST /v1/conversation is served, JSON only: 401 without the right credentials, 405 for another method, 404 for another path,
411 without a length, 413 over 4 MiB, 400 for a body that is not what is expected. Nothing of a request is ever logged."""
import base64
import hmac
import json
import logging
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import settings
from .voice import Forwarded

logger = logging.getLogger('iq_edge.voice')
USER = 'iq'
PATH = '/v1/conversation'
MAX_BODY = 4 * 1024 * 1024  # a home with many exposed entities sends them all with each sentence
MIN_PASSWORD = 32


def password_path():
    return settings.data_dir() / 'voice.json'


def password():
    """The router's password: the one in /data/voice.json or, on the first start (or if the file is unusable), a new one
    (secrets.token_urlsafe(32) = 43 characters) written there with mode 600. Never logged."""
    stored = settings.read_json(password_path(), {})
    value = stored.get('password') if isinstance(stored, dict) else None
    if isinstance(value, str) and len(value) >= MIN_PASSWORD:
        return value
    value = secrets.token_urlsafe(32)
    settings.write_json(password_path(), {'password': value})
    logger.info('Senha do roteador de voz criada.')
    return value


def check_basic(header, secret):
    """True only for Basic credentials with user `iq` and this password. Both are always compared, in constant time."""
    good = False
    if isinstance(header, str) and header[:6].lower() == 'basic ':
        try:
            user, _, given = base64.b64decode(header[6:].strip(), validate=True).decode('utf-8').partition(':')
        except ValueError:  # bad base64 or bytes that are not UTF-8
            user, given = '', ''
        same_user = hmac.compare_digest(user.encode(), USER.encode())
        same_password = hmac.compare_digest(given.encode(), secret.encode())
        good = same_user and same_password
    return good


def parse_request(data):
    """(text, language, conversation_id, agent_id) of the integration's JSON; text '' = there is none."""
    if not isinstance(data, dict):
        return '', '', '', ''
    text = data.get('query')
    if not isinstance(text, str) or not text.strip():
        text = ''
        for message in reversed(data.get('messages') if isinstance(data.get('messages'), list) else []):
            if isinstance(message, dict) and message.get('role') == 'user' and isinstance(message.get('content'), str):
                text = message['content']
                break
    text = text.strip()
    short = lambda key, size: data[key].strip()[:size] if isinstance(data.get(key), str) else ''  # noqa: E731
    return text, short('language', 16), short('conversation_id', 200), short('agent_id', 200)


def make_handler(router, secret):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'IQEdge'
        sys_version = ''
        timeout = 30  # a client that stops sending does not hold a thread

        def log_message(self, *args):  # nothing of the request goes to the log
            pass

        def send_json(self, status, data, extra=(), content_type='application/json; charset=utf-8', lines=False):
            """JSON only; `lines`: `data` is a list sent one JSON per line (the integration's streaming format)."""
            self.close_connection = True
            items = data if lines else [data]
            payload = ''.join(json.dumps(item, ensure_ascii=False) + ('\n' if lines else '') for item in items).encode('utf-8')
            self.send_response(status)
            for key, value in (('Content-Type', content_type), ('Content-Length', str(len(payload))), ('Cache-Control', 'no-store'),
                               ('X-Content-Type-Options', 'nosniff')) + tuple(extra):
                self.send_header(key, value)
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(payload)

        def send_forwarded(self, answer):
            """An agent's own answer, as it is: its status, its content type (when it sent one) and its body."""
            self.close_connection = True
            self.send_response(answer.status)
            for key, value in (('Content-Type', answer.content_type), ('Content-Length', str(len(answer.body))),
                               ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff')):
                if value:
                    self.send_header(key, value)
            self.end_headers()
            self.wfile.write(answer.body)

        def authorized(self):
            if check_basic(self.headers.get('Authorization'), secret):
                return True
            self.send_json(401, {'error': 'unauthorized'}, (('WWW-Authenticate', 'Basic realm="iq-edge"'),))
            return False

        def other(self):
            if self.authorized():
                self.send_json(405, {'error': 'method'}, (('Allow', 'POST'),))

        do_GET = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = other

        def do_POST(self):
            if not self.authorized():
                return
            if self.path.split('?', 1)[0] != PATH:
                return self.send_json(404, {'error': 'path'})
            try:
                size = int(self.headers.get('Content-Length') or '')
            except ValueError:
                return self.send_json(411, {'error': 'length'})
            if size < 0:
                return self.send_json(411, {'error': 'length'})
            if size > MAX_BODY:
                return self.send_json(413, {'error': 'too_big'})
            raw = self.rfile.read(size)
            try:
                data = json.loads(raw)
            except ValueError:
                return self.send_json(400, {'error': 'json'})
            text, language, conversation_id, agent_id = parse_request(data)
            if not text:
                return self.send_json(400, {'error': 'query'})
            try:
                speech = router.handle(text, language, conversation_id, agent_id, raw)
            except Exception:  # the house keeps an answer: never the text, never a trace with it
                logger.warning('O roteador de voz falhou numa conversa.')
                speech = ''
            if isinstance(speech, Forwarded):
                return self.send_forwarded(speech)
            if not speech:
                speech = 'Desculpe, não consegui responder agora.' if not language.lower().startswith('en') else \
                    'Sorry, I could not answer right now.'
            if data.get('stream') is True:  # the integration's "response streaming": one JSON per line
                return self.send_json(200, [{'type': 'begin'}, {'type': 'item', 'content': speech}, {'type': 'end'}],
                                      content_type='application/x-ndjson; charset=utf-8', lines=True)
            return self.send_json(200, {'output': speech})

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):  # a client that dropped or stalled: nothing about it (or its address) is printed
        pass


def start(router, host='0.0.0.0', port=None):
    """The router's server (a thread per request), already serving in its own thread. Returns it (`shutdown()` stops it)."""
    server = Server((host, settings.voice_port() if port is None else port), make_handler(router, password()))
    threading.Thread(target=server.serve_forever, name='iq-edge-voice', daemon=True).start()
    return server
