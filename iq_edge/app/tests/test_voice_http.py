"""The voice router's door (voice_http.py, port 8098): the password (first start, mode 600, never logged), Basic authentication on every
request (constant-time compare), only POST /v1/conversation, JSON only, the body limit, and the request/response contract of the
community integration "webhook-conversation" (non-streaming `{"output": ...}` and its streaming lines), end to end with the router,
the FAKE center and the FAKE Home Assistant. With an agent by address the door hands the router the request's own bytes and gives Home
Assistant the agent's answer unchanged (status, content type, body), or the router's spoken sentence in the integration's shape."""
import base64
import hmac
import json
import logging
import os
import stat
import unittest
from http.client import HTTPConnection
from unittest import mock

from iq_edge import settings, voice, voice_http
from iq_edge.center import Center
from tests.fakes import EdgeCase, FakeAgent, conversation_response

AGENT = 'conversation.iq_assistant'
TEXT = 'liga o ar condicionado do quarto'


def basic(user, password):
    return 'Basic ' + base64.b64encode(f'{user}:{password}'.encode()).decode()


class StubRouter:
    """Records what the door hands to the router and answers a fixed sentence (or raises)."""

    def __init__(self, speech='Tudo certo, é pra já.', error=None):
        self.speech, self.error, self.calls, self.raws = speech, error, [], []

    def handle(self, text, language='', conversation_id='', caller='', raw=None):
        self.calls.append((text, language, conversation_id, caller))
        self.raws.append(raw)
        if self.error:
            raise self.error
        return self.speech


class Records(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage() + ' ' + str(record.exc_text or '') + ' ' + str(record.args))


class DoorCase(EdgeCase):
    router_class = StubRouter

    def setUp(self):
        super().setUp()
        self.records = Records()
        root = logging.getLogger()
        level = root.level
        root.setLevel(logging.DEBUG)
        root.addHandler(self.records)
        self.addCleanup(root.setLevel, level)
        self.addCleanup(root.removeHandler, self.records)
        self.router = self.make_router()
        self.server = voice_http.start(self.router, host='127.0.0.1', port=0)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.password = voice_http.password()

    def make_router(self):
        return StubRouter()

    def call(self, method='POST', path=voice_http.PATH, body=None, auth=True, headers=None, raw=None):
        """(status, headers, body bytes). `auth`: True = the right credentials; a string = that Authorization header; None/False = none."""
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=30)
        sent = {'Content-Type': 'application/json'}
        if auth is True:
            sent['Authorization'] = basic(voice_http.USER, self.password)
        elif auth:
            sent['Authorization'] = auth
        sent.update(headers or {})
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        connection.request(method, path, data, sent)
        answer = connection.getresponse()
        content = answer.read()
        connection.close()
        return answer.status, answer, content

    def ask(self, **fields):
        body = {'query': TEXT, 'language': 'pt-BR', 'conversation_id': 'conv-1', 'agent_id': 'conversation.iq_router', 'stream': False}
        body.update(fields)
        return self.call(body={key: value for key, value in body.items() if value is not None})


class PasswordTests(DoorCase):
    def test_created_on_the_first_start_in_a_private_file(self):
        path = voice_http.password_path()
        self.assertEqual(path, settings.data_dir() / 'voice.json')
        self.assertGreaterEqual(len(self.password), 32)
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), {'password': self.password})
        if os.name == 'posix':  # Windows has no such mode (the writer test below covers it there)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)  # like edge.json
        self.assertEqual(voice_http.password(), self.password)  # the same one on every later start

    def test_a_missing_or_weak_file_makes_a_new_password(self):
        first = self.password
        voice_http.password_path().unlink()
        second = voice_http.password()
        self.assertNotEqual(first, second)
        self.assertGreaterEqual(len(second), 32)
        settings.write_json(voice_http.password_path(), {'password': 'short'})  # a hand-edited, weak value is not kept
        third = voice_http.password()
        self.assertGreaterEqual(len(third), 32)
        self.assertNotIn(third, (first, second, 'short'))
        voice_http.password_path().write_text('not json', encoding='utf-8')
        self.assertGreaterEqual(len(voice_http.password()), 32)

    def test_it_is_written_through_the_private_writer(self):
        voice_http.password_path().unlink()
        with mock.patch.object(settings, 'write_json', wraps=settings.write_json) as writer:
            voice_http.password()
        self.assertTrue(writer.called)
        self.assertIs(writer.call_args.kwargs.get('private', True), True)  # mode 600 from the first byte, atomically

    def test_it_is_never_logged(self):
        secret = self.password  # made by the server's start, with the log already listening
        self.router.speech = 'ok'
        self.call(body={'query': TEXT}, auth=basic('iq', secret))
        self.call(body={'query': TEXT}, auth=basic('iq', 'wrong-' + secret))
        self.call(method='GET')
        self.call(body={'query': TEXT}, auth=None)
        logged = '\n'.join(self.records.lines)
        self.assertNotIn(secret, logged)
        self.assertNotIn(base64.b64encode(f'iq:{secret}'.encode()).decode(), logged)
        self.assertIn('Senha do roteador de voz criada.', logged)  # that it was made, yes; what it is, never


class AuthTests(DoorCase):
    def test_every_request_needs_the_credentials(self):
        for auth in (None, False, 'Basic', 'Basic !!!not-base64!!!', 'Bearer ' + self.password, basic('iq', 'wrong' + self.password),
                     basic('iq', ''), basic('root', self.password), basic('', self.password), basic('iq ', self.password),
                     'Basic ' + base64.b64encode(b'\xff\xfe:\xff').decode(), 'basic' + base64.b64encode(f'iq:{self.password}'.encode()).decode()):
            status, answer, content = self.call(body={'query': TEXT}, auth=auth)
            self.assertEqual(status, 401, auth)
            self.assertIn('Basic', answer.getheader('WWW-Authenticate'))
            self.assertEqual(json.loads(content), {'error': 'unauthorized'})
        self.assertEqual(self.router.calls, [])  # nothing reached the router

    def test_the_right_credentials_get_in(self):
        status, _, content = self.call(body={'query': TEXT}, auth=basic('iq', self.password))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(content), {'output': 'Tudo certo, é pra já.'})
        status = self.call(body={'query': TEXT}, auth='basic ' + base64.b64encode(f'iq:{self.password}'.encode()).decode())[0]
        self.assertEqual(status, 200)  # the scheme's case does not matter
        self.assertEqual(len(self.router.calls), 2)

    def test_the_other_methods_and_paths_also_ask_for_the_credentials_first(self):
        for method in ('GET', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'):
            self.assertEqual(self.call(method=method, auth=None)[0], 401, method)
        self.assertEqual(self.call(path='/', auth=None, body={})[0], 401)

    def test_the_comparison_is_constant_time_and_always_covers_user_and_password(self):
        calls, original = [], hmac.compare_digest

        def compare(first, second):
            calls.append((first, second))
            return original(first, second)
        with mock.patch.object(voice_http.hmac, 'compare_digest', side_effect=compare):
            self.assertEqual(self.call(body={'query': TEXT}, auth=basic('someone', 'wrong'))[0], 401)
            self.assertEqual(len(calls), 2)  # the user was wrong and the password was still compared
            self.assertEqual(self.call(body={'query': TEXT})[0], 200)
            self.assertEqual(len(calls), 4)
            self.assertEqual(self.call(body={'query': TEXT}, auth='Bearer x')[0], 401)
            self.assertEqual(len(calls), 4)  # not Basic at all: nothing to compare
        self.assertTrue(all(isinstance(a, bytes) and isinstance(b, bytes) for a, b in calls))
        self.assertIn((self.password.encode(), self.password.encode()), calls)
        with open(voice_http.__file__, encoding='utf-8') as handle:
            source = handle.read()
        self.assertNotIn('== secret', source)
        self.assertNotIn('password ==', source)


class ServedOnlyTests(DoorCase):
    def test_other_methods_are_405(self):
        for method in ('GET', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'):
            status, answer, content = self.call(method=method)
            self.assertEqual(status, 405, method)
            self.assertEqual(answer.getheader('Allow'), 'POST')
            self.assertEqual(json.loads(content), {'error': 'method'})
        status, answer, content = self.call(method='HEAD')
        self.assertEqual((status, content), (405, b''))

    def test_nothing_else_is_served(self):
        for path in ('/', '/v1', '/v1/conversation/', '/v1/conversations', '/v1/ha-conversation', '/style.css', '/api/states', '/../etc/passwd',
                     '/favicon.ico', '/%76%31/conversation'):
            status, _, content = self.call(path=path, body={'query': TEXT})
            self.assertEqual(status, 404, path)
            self.assertEqual(json.loads(content), {'error': 'path'})
        self.assertEqual(self.call(path=voice_http.PATH + '?x=1', body={'query': TEXT})[0], 200)  # a query string changes nothing
        self.assertEqual(self.router.calls[0][0], TEXT)

    def test_the_answers_are_json_only(self):
        for status, answer, content in (self.ask(), self.call(auth=None), self.call(method='GET'), self.call(path='/x', body={}),
                                        self.call(raw=b'{')):
            self.assertTrue(answer.getheader('Content-Type').startswith('application/json'), status)
            self.assertEqual(answer.getheader('Cache-Control'), 'no-store')
            self.assertEqual(answer.getheader('X-Content-Type-Options'), 'nosniff')
            self.assertIsInstance(json.loads(content), dict)
        self.assertNotIn('Python', self.ask()[1].getheader('Server'))  # no version of the language or the library in the header


class BodyLimitTests(DoorCase):
    def test_over_the_limit_is_413_without_reading_the_body(self):
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=30)
        connection.putrequest('POST', voice_http.PATH)
        connection.putheader('Authorization', basic('iq', self.password))
        connection.putheader('Content-Length', str(voice_http.MAX_BODY + 1))
        connection.endheaders()
        answer = connection.getresponse()
        self.assertEqual((answer.status, json.loads(answer.read())), (413, {'error': 'too_big'}))
        connection.close()
        self.assertEqual(self.router.calls, [])

    def test_a_big_but_allowed_body_goes_through(self):
        entities = json.dumps([{'entity_id': f'light.l{index}', 'name': 'Luz ' * 5, 'state': 'on', 'aliases': [], 'area_id': None} for index in range(4000)])
        self.assertGreater(len(entities), 300 * 1024)
        status, _, content = self.ask(exposed_entities=entities)  # the owner's installation sends them as a JSON text
        self.assertEqual(status, 200)
        self.assertEqual(self.router.calls[0][0], TEXT)

    def test_a_missing_or_bad_length_is_411(self):
        for length in (None, 'abc', '-5'):
            connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=30)
            connection.putrequest('POST', voice_http.PATH)
            connection.putheader('Authorization', basic('iq', self.password))
            if length is not None:
                connection.putheader('Content-Length', length)
            connection.endheaders()
            answer = connection.getresponse()
            self.assertEqual((answer.status, json.loads(answer.read())), (411, {'error': 'length'}), length)
            connection.close()

    def test_bodies_that_are_not_what_is_expected_are_400(self):
        for raw, error in ((b'', 'json'), (b'{', 'json'), (b'\xff\xfe', 'json'), (b'[]', 'query'), (b'"text"', 'query'), (b'null', 'query'),
                           (b'{}', 'query'), (b'{"query": ""}', 'query'), (b'{"query": "   "}', 'query'), (b'{"query": 5}', 'query'),
                           (b'{"messages": [{"role": "assistant", "content": "oi"}]}', 'query'), (b'{"messages": "x"}', 'query')):
            status, _, content = self.call(raw=raw)
            self.assertEqual((status, json.loads(content)), (400, {'error': error}), raw)
        self.assertEqual(self.router.calls, [])


class ContractTests(DoorCase):
    """The request the integration sends (README + source of EuleMitKeule/webhook-conversation 1.x) and what it expects back."""

    def test_the_request_as_the_integration_sends_it(self):
        body = {'conversation_id': '01K8ZABC', 'user_id': 'u1', 'user_name': 'Franco', 'language': 'pt-BR',
                'agent_id': 'conversation.iq_router', 'device_id': 'dev1', 'device_info': {'name': 'Tablet', 'manufacturer': 'X', 'model': 'Y'},
                'messages': [{'role': 'user', 'content': 'antiga'}, {'role': 'assistant', 'content': 'resposta'}],
                'query': TEXT, 'exposed_entities': json.dumps([{'entity_id': 'light.sala', 'name': 'Sala', 'state': 'on', 'aliases': [],
                                                                'area_id': None, 'area_name': None}]),
                'system_prompt': 'Você é o assistente da casa.', 'stream': False}
        status, answer, content = self.call(body=body)
        self.assertEqual((status, json.loads(content)), (200, {'output': 'Tudo certo, é pra já.'}))
        self.assertEqual(self.router.calls, [(TEXT, 'pt-BR', '01K8ZABC', 'conversation.iq_router')])

    def test_exposed_entities_as_a_list_or_missing_and_other_new_fields_do_not_matter(self):
        for extra in ({'exposed_entities': [{'entity_id': 'light.sala'}]}, {'exposed_entities': None}, {'tool_calls': [], 'new_field': {'a': 1}},
                      {'stream': 'false', 'user_id': None, 'device_id': None, 'device_info': None}):
            self.assertEqual(self.ask(**extra)[0], 200, extra)

    def test_the_text_comes_from_query_else_from_the_last_user_message(self):
        self.call(body={'query': '  tem texto  '})
        self.call(body={'messages': [{'role': 'user', 'content': 'primeira'}, {'role': 'assistant', 'content': 'x'},
                                     {'role': 'user', 'content': 'a última'}, {'role': 'tool_result', 'content': 'y'}]})
        self.call(body={'query': '', 'messages': [{'role': 'user', 'content': 'sem query'}]})
        self.assertEqual([call[0] for call in self.router.calls], ['tem texto', 'a última', 'sem query'])

    def test_only_the_text_is_required(self):
        self.assertEqual(self.call(body={'query': 'oi'})[0], 200)
        self.assertEqual(self.router.calls[-1], ('oi', '', '', ''))
        self.call(body={'query': 'oi', 'language': 'x' * 100, 'conversation_id': 'c' * 500, 'agent_id': 5})
        self.assertEqual((len(self.router.calls[-1][1]), len(self.router.calls[-1][2]), self.router.calls[-1][3]), (16, 200, ''))

    def test_streaming_answers_in_the_integrations_line_format(self):
        status, answer, content = self.ask(stream=True)
        self.assertEqual(status, 200)
        self.assertTrue(answer.getheader('Content-Type').startswith('application/x-ndjson'))
        lines = content.decode('utf-8').split('\n')
        self.assertEqual(lines[-1], '')  # one JSON per line, each ending in a newline
        self.assertEqual([json.loads(line) for line in lines[:-1]],
                         [{'type': 'begin'}, {'type': 'item', 'content': 'Tudo certo, é pra já.'}, {'type': 'end'}])
        self.assertTrue(all('\n' not in line for line in lines))
        self.router.speech = 'duas\nlinhas'  # a line break inside the speech is escaped: it cannot split the stream
        lines = self.ask(stream=True)[2].decode('utf-8').split('\n')
        self.assertEqual(json.loads(lines[1])['content'], 'duas\nlinhas')
        self.assertEqual(len(lines), 4)
        self.assertEqual(json.loads(self.ask(stream='true')[2]), {'output': 'duas\nlinhas'})  # only the boolean true streams

    def test_a_router_that_breaks_still_answers_with_a_sentence(self):
        self.router.error = RuntimeError('boom ' + TEXT)
        status, _, content = self.ask()
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(content), {'output': 'Desculpe, não consegui responder agora.'})
        self.assertEqual(json.loads(self.ask(language='en-US')[2]), {'output': 'Sorry, I could not answer right now.'})
        self.router.error, self.router.speech = None, ''
        self.assertEqual(json.loads(self.ask()[2]), {'output': 'Desculpe, não consegui responder agora.'})
        self.assertNotIn(TEXT, '\n'.join(self.records.lines))  # not even the error that carried the words

    def test_the_router_gets_the_bytes_of_the_request_exactly_as_they_came(self):
        raw = ('{ "query" : "' + TEXT + '",\n  "user_id":"u-7", "device_id": "dev-1",  "x": [1,  2] , "y":"Você" }').encode('utf-8')
        self.assertEqual(self.call(raw=raw)[0], 200)
        self.assertEqual(self.router.raws, [raw])  # not parsed and written again: the same bytes

    def test_the_answer_of_an_agent_by_address_goes_back_as_it_is(self):
        for answer, content_type in ((voice.Forwarded(200, 'application/json; charset=utf-8', b'{"output": "do agente antigo"}'),
                                      'application/json; charset=utf-8'),
                                     (voice.Forwarded(422, 'text/plain', b'recusado \xc3\xa9 isso'), 'text/plain'),
                                     (voice.Forwarded(200, None, b'sem tipo'), None),
                                     (voice.Forwarded(204, None, b''), None)):
            self.router.speech = answer
            for stream in (False, True):  # the agent already answers in the shape of the request: nothing is wrapped
                status, reply, content = self.ask(stream=stream)
                self.assertEqual((status, content), (answer.status, answer.body))
                self.assertEqual(reply.getheader('Content-Type'), content_type)
                self.assertEqual(reply.getheader('Content-Length'), str(len(answer.body)))
                self.assertEqual(reply.getheader('Cache-Control'), 'no-store')
                self.assertEqual(reply.getheader('X-Content-Type-Options'), 'nosniff')
        self.assertNotIn('Python', reply.getheader('Server'))

    def test_unicode_both_ways(self):
        self.router.speech = 'Açaí, “pão” e café ☕'
        status, _, content = self.ask(query='Está calor, não é? ação')
        self.assertEqual(json.loads(content.decode('utf-8'))['output'], 'Açaí, “pão” e café ☕')
        self.assertEqual(self.router.calls[-1][0], 'Está calor, não é? ação')


class RealRouterCase(DoorCase):
    """The door with the real router, the fake center and the fake Home Assistant."""

    def make_router(self):
        self.edge = Center()
        self.assertEqual(self.edge.pair('123456'), (True, ''))
        return voice.Router(self.edge)


class EndToEndTests(RealRouterCase):

    def test_a_simple_request_is_answered_by_the_local_assistant(self):
        os.environ['IQ_VOICE_AGENT'] = AGENT
        self.center.route_answer = (200, {'route': 'local', 'category': 'simple', 'sensitive': False, 'confidence': 0.99, 'engine': 'jev',
                                          'reason': 'simple', 'ms': 4}, {})
        self.ha.conversation_answers['conversation.home_assistant'] = (200, conversation_response('Ar ligado.', 'action_done', 'loc-1'))
        status, _, content = self.ask(language='pt-BR')
        self.assertEqual((status, json.loads(content)), (200, {'output': 'Ar ligado.'}))
        self.assertEqual([body['agent_id'] for body in self.ha.conversations], ['conversation.home_assistant'])

    def test_a_request_the_center_sends_to_the_agent(self):
        os.environ['IQ_VOICE_AGENT'] = AGENT
        self.center.route_answer = (200, {'route': 'agent', 'category': 'compound', 'sensitive': False, 'confidence': None, 'engine': 'none',
                                          'reason': 'compound', 'ms': 2}, {})
        self.assertEqual(json.loads(self.ask()[2]), {'output': 'Resposta do assistente.'})
        self.assertEqual([body['agent_id'] for body in self.ha.conversations], [AGENT])

    def test_a_conversation_answered_by_the_center_comes_back_in_the_integrations_shape(self):
        """0.2.7: the center's Claude speech goes back as {"output": ...}, or in the streaming lines when the request asks for them;
        the conversation id is the integration's own (the router only keeps the history under it, in memory)."""
        os.environ['IQ_VOICE_AGENT'] = AGENT
        self.center.route_answer = (200, {'route': 'agent', 'category': 'chat', 'sensitive': False, 'engine': 'jev', 'reason': 'chat'}, {})
        self.center.chat_answer = (200, {'answer': 'ok', 'speech': 'Porque o céu espalha a luz azul.', 'engine': 'claude', 'ms': 700}, {})
        self.assertEqual(json.loads(self.ask(query='por que o céu é azul?')[2]), {'output': 'Porque o céu espalha a luz azul.'})
        lines = self.ask(query='e o pôr do sol?', stream=True)[2].decode('utf-8').split('\n')
        self.assertEqual([json.loads(line) for line in lines[:-1]],
                         [{'type': 'begin'}, {'type': 'item', 'content': 'Porque o céu espalha a luz azul.'}, {'type': 'end'}])
        self.assertEqual(self.ha.conversations, [])  # neither the main agent nor the local assistant
        self.assertEqual([call['body'].get('history') for call in self.center.chatted],
                         [None, [{'role': 'user', 'text': 'por que o céu é azul?'},
                                 {'role': 'assistant', 'text': 'Porque o céu espalha a luz azul.'}]])  # the same conversation_id: conv-1
        self.center.chat_answer = (200, {'answer': 'none', 'reason': 'off', 'ms': 1}, {})  # not turned on: the main agent answers
        self.assertEqual(json.loads(self.ask(query='mais uma')[2]), {'output': 'Resposta do assistente.'})
        self.assertEqual([body['agent_id'] for body in self.ha.conversations], [AGENT])

    def test_no_agent_configured_is_a_spoken_sentence_not_an_http_error(self):
        os.environ.pop('IQ_VOICE_AGENT', None)
        status, _, content = self.ask(language='en')
        self.assertEqual(status, 200)
        self.assertIn('no assistant configured', json.loads(content)['output'])

    def test_no_word_of_a_request_or_the_password_in_the_log(self):
        os.environ['IQ_VOICE_AGENT'] = AGENT
        word = 'palavra-secreta-qwerty'
        for route in ('local', 'agent'):
            self.center.route_answer = (200, {'route': route, 'category': 'simple', 'sensitive': False, 'engine': 'jev'}, {})
            self.ask(query=f'{word} {TEXT}')
        self.center.stop()
        self.ask(query=f'{word} {TEXT}')
        self.call(body={'query': word}, auth='Basic ' + base64.b64encode(f'iq:{self.password}x'.encode()).decode())
        logged = '\n'.join(self.records.lines)
        for secret in (word, TEXT, self.password):
            self.assertNotIn(secret, logged)


class AddressEndToEndTests(RealRouterCase):
    """An agent by ADDRESS, from Home Assistant's request to Home Assistant's answer: the old assistant's webhook is a FakeAgent."""

    def setUp(self):
        super().setUp()
        self.agent = FakeAgent()
        self.addCleanup(self.agent.stop)
        os.environ['IQ_VOICE_AGENT_URL'] = self.agent.address
        os.environ['IQ_VOICE_HOSTNAME'] = 'abc123-iq-edge'
        self.center.route_answer = (200, {'route': 'agent', 'category': 'compound', 'sensitive': False, 'engine': 'none'}, {})

    def test_the_agent_gets_the_very_bytes_and_its_answer_comes_back_unchanged(self):
        sent = ('{"conversation_id":"01K8Z","user_id":"u-7","user_name":"Franco","language":"pt-BR",'
                '"agent_id":"conversation.iq_router","device_id":"dev-tablet","device_info":{"name":"Tablet"},'
                '"query":"' + TEXT + '","exposed_entities":"[{\\"entity_id\\":\\"light.sala\\"}]","stream":false,"novo":{"a":[1, 2]}}').encode('utf-8')
        os.environ['IQ_VOICE_AGENT_USER'] = 'franco'
        os.environ['IQ_VOICE_AGENT_PASSWORD'] = 'senha-do-agente'
        self.agent.answer = (200, 'application/json', 'resposta própria do agente'.encode('utf-8'))
        status, reply, content = self.call(raw=sent)
        self.assertEqual((status, content), (200, 'resposta própria do agente'.encode('utf-8')))
        self.assertEqual(reply.getheader('Content-Type'), 'application/json')
        got = self.agent.requests[0]
        self.assertEqual(got['body'], sent)  # the very bytes, user_id and device_id included
        self.assertEqual(got['headers']['Content-Type'], 'application/json')
        self.assertEqual(got['headers']['Authorization'], 'Basic ' + base64.b64encode(b'franco:senha-do-agente').decode())
        self.assertEqual(self.ha.conversations, [])  # nothing through Home Assistant's conversation API
        for key in ('IQ_VOICE_AGENT_USER', 'IQ_VOICE_AGENT_PASSWORD'):
            del os.environ[key]
        self.agent.answer = (418, 'text/plain', b'sou um bule')  # a status of the agent's own goes back too
        status, reply, content = self.call(raw=sent)
        self.assertEqual((status, content, reply.getheader('Content-Type')), (418, b'sou um bule', 'text/plain'))
        self.assertNotIn('Authorization', self.agent.requests[1]['headers'])  # no user, no login

    def test_every_way_into_the_agent_goes_by_the_address_and_a_streaming_answer_is_kept(self):
        lines = b'{"type":"begin"}\n{"type":"item","content":"do agente"}\n{"type":"end"}\n'
        self.agent.answer = (200, 'application/x-ndjson; charset=utf-8', lines)
        cases = (('mode off', lambda: os.environ.__setitem__('IQ_VOICE_ROUTE', 'off'), TEXT),
                 ('center failing', lambda: (os.environ.pop('IQ_VOICE_ROUTE', None),
                                             setattr(self.center, 'route_answer', (500, {'error': 'x'}, {}))), TEXT),
                 ('long text', lambda: setattr(self.center, 'route_answer', (200, {'route': 'local', 'sensitive': False}, {})), 'b' * 501))
        for name, arrange, text in cases:
            arrange()
            body = json.dumps({'query': text, 'user_id': 'u-7', 'stream': True}).encode('utf-8')
            status, reply, content = self.call(raw=body)
            self.assertEqual((status, content, reply.getheader('Content-Type')), (200, lines, 'application/x-ndjson; charset=utf-8'), name)
            self.assertEqual(self.agent.requests[-1]['body'], body, name)
        self.assertEqual((len(self.agent.requests), self.ha.conversations), (3, []))

    def test_an_agent_that_is_down_or_fails_gets_a_spoken_sentence_in_the_shape_of_the_request(self):
        self.agent.answer = (503, 'application/json', b'{"output": "ISTO NAO DEVE SAIR"}')
        status, _, content = self.ask(language='pt-BR')
        self.assertEqual((status, json.loads(content)), (200, {'output': voice.spoken('failed', 'pt-BR')}))
        status, reply, content = self.ask(language='en-US', stream=True)  # the stream flag is respected, the language too
        self.assertEqual(status, 200)
        self.assertTrue(reply.getheader('Content-Type').startswith('application/x-ndjson'))
        self.assertEqual([json.loads(line) for line in content.decode('utf-8').splitlines()],
                         [{'type': 'begin'}, {'type': 'item', 'content': voice.spoken('failed', 'en-US')}, {'type': 'end'}])
        self.agent.stop()  # and an agent that is not there at all
        self.assertEqual(json.loads(self.ask(language='en')[2]), {'output': voice.spoken('failed', 'en')})
        self.assertEqual(self.router.stats()['failed'], 3)

    def test_an_address_that_is_refused_or_loops_is_a_spoken_sentence_not_an_error(self):
        for url, code in (('ftp://agent.local/hook', 'no_agent'), ('http://usuario:senha@agent.local/hook', 'no_agent'),
                          ('http://abc123-iq-edge:8098/v1/conversation', 'loop'), (f'http://127.0.0.1:{settings.voice_port()}/hook', 'loop')):
            os.environ['IQ_VOICE_AGENT_URL'] = url
            status, _, content = self.ask(language='en')
            self.assertEqual((status, json.loads(content)), (200, {'output': voice.spoken(code, 'en')}), url)
        self.assertEqual(self.agent.requests, [])

    def test_the_address_the_user_and_the_password_are_never_logged(self):
        logging.getLogger().setLevel(logging.INFO)  # the add-on's own level (at DEBUG the HTTP library names the host and path)
        os.environ['IQ_VOICE_AGENT_URL'] = self.agent.url + '/segredo-no-caminho?chave=valor-secreto'
        os.environ['IQ_VOICE_AGENT_USER'] = 'usuario-secreto'
        os.environ['IQ_VOICE_AGENT_PASSWORD'] = 'senha-secreta-xyz'
        for status in (200, 500):
            self.agent.answer = (status, 'application/json', b'{}')
            self.ask(query='palavra-secreta-qwerty ' + TEXT)
        self.agent.stop()
        self.ask(query='palavra-secreta-qwerty ' + TEXT)
        logged = '\n'.join(self.records.lines)
        for secret in ('segredo-no-caminho', 'chave=valor-secreto', 'usuario-secreto', 'senha-secreta-xyz', 'palavra-secreta-qwerty',
                       self.agent.url[len('http://'):], base64.b64encode(b'usuario-secreto:senha-secreta-xyz').decode(), self.password):
            self.assertNotIn(secret, logged)


if __name__ == '__main__':
    unittest.main()
