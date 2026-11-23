"""The voice router (lote J1b, 0.2.5): the center's voice-route call (Center.voice_route) and the flow (voice.Router) with the FAKE
center and the FAKE Home Assistant (its conversation API): local, the agent, the fallbacks, the three modes, no agent configured, the
conversation ids, the counters and the rule that no word of a request is kept or logged."""
import logging
import os
import time
import unittest
from unittest import mock

from iq_edge import center as center_module
from iq_edge import settings, voice
from iq_edge.center import Center, NoRoute
from tests.fakes import EdgeCase, conversation_response

AGENT = 'conversation.iq_assistant'
TEXT = 'acende a luz da sala de jantar'
ROUTE = {'route': 'agent', 'category': 'compound', 'sensitive': False, 'confidence': 0.9, 'engine': 'jev', 'reason': 'test', 'ms': 12}


def decision(**changes):
    return (200, dict(ROUTE, **changes), {})


class Records(logging.Handler):
    """Every log record of the process while a test runs: the words of a request must be in none of them."""

    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage() + ' ' + str(record.exc_text or '') + ' ' + str(record.args))


class VoiceCase(EdgeCase):
    def setUp(self):
        super().setUp()
        self.edge = Center()
        self.assertEqual(self.edge.pair('123456'), (True, ''))
        self.router = voice.Router(self.edge)
        self.records = Records()
        root = logging.getLogger()
        self.level = root.level
        root.setLevel(logging.DEBUG)
        root.addHandler(self.records)
        self.addCleanup(root.setLevel, self.level)
        self.addCleanup(root.removeHandler, self.records)

    def options(self, agent=None, mode=None):
        for name, value in (('IQ_VOICE_AGENT', agent), ('IQ_VOICE_ROUTE', mode)):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def agents(self):
        """The agent_id of every call that reached Home Assistant's conversation API, in order."""
        return [body['agent_id'] for body in self.ha.conversations]

    def assertNoWords(self, *texts):
        """The words of the request are not in the log, the counters, the problem note or the conversation memory."""
        kept = repr(self.router.stats()) + repr(self.router.memory.items) + '\n'.join(self.records.lines)
        for text in texts or (TEXT,):
            self.assertNotIn(text, kept)


class CenterVoiceRouteTests(VoiceCase):
    def test_the_call_and_its_answer(self):
        self.center.route_answer = decision(route='local', category='simple', engine='jev')
        answer = self.edge.voice_route(TEXT, 'pt')
        self.assertEqual((answer['route'], answer['category'], answer['sensitive'], answer['engine']), ('local', 'simple', False, 'jev'))
        sent = self.center.routed[0]
        self.assertEqual(sent['body'], {'text': TEXT, 'language': 'pt'})
        self.assertEqual(sent['headers']['X-IQ-Edge-Contract'], '2')  # the same session and authentication as briefing-compose
        self.assertEqual(sent['headers']['Authorization'], 'Bearer ' + 'C' * 43)
        self.assertEqual(sent['headers']['X-IQ-Edge-Home'], 'home-1')
        self.assertEqual(self.center.log[-1][:2], ('POST', 'voice-route'))

    def test_not_paired_makes_no_call(self):
        edge = Center()
        os.environ['IQ_DATA_DIR'] = os.path.join(self.tmp.name, 'other')
        with self.assertRaises(NoRoute) as raised:
            edge.voice_route(TEXT, 'pt')
        self.assertEqual(raised.exception.reason, 'unpaired')
        self.assertEqual(self.center.routed, [])

    def test_sensitive_never_stays_local(self):
        self.center.route_answer = decision(route='local', sensitive=True)  # a contradiction: the safer side wins
        answer = self.edge.voice_route(TEXT, 'pt')
        self.assertEqual((answer['route'], answer['sensitive']), ('agent', True))
        self.center.route_answer = decision(route='agent', category='simple', sensitive=False)
        self.assertEqual(self.edge.voice_route(TEXT, 'pt')['route'], 'agent')  # agent is never turned into local

    def test_errors_become_a_short_reason(self):
        for status, reason in ((401, 'revoked'), (410, 'home_deleted'), (413, 'too_big'), (422, 'invalid'), (429, 'rate'),
                               (500, 'http_500'), (503, 'http_503'), (404, 'http_404')):
            self.center.route_answer = (status, {'error': 'x'}, {})
            with self.assertRaises(NoRoute) as raised:
                self.edge.voice_route(TEXT, 'pt')
            self.assertEqual(raised.exception.reason, reason)
        self.assertTrue(self.edge.paired())  # a 401 here is only "no route": the loop decides about a revoked credential

    def test_malformed_answers(self):
        for answer in (b'not json', b'[]', b'null', json_bytes({'route': 'maybe'}), json_bytes({'route': None}), json_bytes({'category': 'simple'})):
            self.center.route_answer = (200, answer, {})
            with self.assertRaises(NoRoute) as raised:
                self.edge.voice_route(TEXT, 'pt')
            self.assertEqual(raised.exception.reason, 'bad_response', answer)
        self.center.route_answer = decision(category='weird', engine='other', reason='x' * 100)  # unknown values are made harmless
        answer = self.edge.voice_route(TEXT, 'pt')
        self.assertEqual((answer['category'], answer['engine'], len(answer['reason'])), ('unknown', 'none', 40))

    def test_a_slow_center_is_left_behind_after_the_budget(self):
        self.center.route_delay = 1.5
        started = time.monotonic()
        with self.assertRaises(NoRoute) as raised:
            self.edge.voice_route(TEXT, 'pt', budget=0.3)
        self.assertEqual(raised.exception.reason, 'timeout')
        self.assertLess(time.monotonic() - started, 1.0)
        with mock.patch.object(center_module, 'ROUTE_BUDGET', 0.2):  # the default budget is a module constant (about 2 s)
            with self.assertRaises(NoRoute):
                self.edge.voice_route(TEXT, 'pt')
        self.assertEqual(center_module.ROUTE_BUDGET, 2.0)

    def test_a_center_that_is_down(self):
        self.center.stop()
        with self.assertRaises(NoRoute) as raised:
            self.edge.voice_route(TEXT, 'pt')
        self.assertIn(raised.exception.reason, ('offline', 'timeout'))  # a closed port: refused at once on Linux, a connect timeout on Windows


def json_bytes(value):
    import json
    return json.dumps(value).encode()


class FlowTests(VoiceCase):
    def test_local_path(self):
        self.options(agent=AGENT)
        self.center.route_answer = decision(route='local', category='simple')
        self.ha.conversation_answers['conversation.home_assistant'] = (200, conversation_response('Luz acesa.', 'action_done', 'loc-1'))
        self.assertEqual(self.router.handle(TEXT, 'pt-BR', 'in-1'), 'Luz acesa.')
        self.assertEqual(self.agents(), ['conversation.home_assistant'])  # the agent was not asked
        self.assertEqual(self.ha.conversations[0], {'text': TEXT, 'agent_id': 'conversation.home_assistant', 'language': 'pt-BR'})
        self.assertEqual(self.center.routed[0]['body'], {'text': TEXT, 'language': 'pt'})  # the center gets the language's first part
        stats = self.router.stats()
        self.assertEqual((stats['local'], stats['agent'], stats['fallback'], stats['failed']), (1, 0, 0, 0))
        self.assertNoWords()

    def test_local_error_falls_back_to_the_agent(self):
        self.options(agent=AGENT)
        self.center.route_answer = decision(route='local', category='simple')
        # the fake's default: the local assistant answers an error response (no intent matched), the agent a sentence
        self.assertEqual(self.router.handle(TEXT, 'pt', 'in-1'), 'Resposta do assistente.')
        self.assertEqual(self.agents(), ['conversation.home_assistant', AGENT])
        stats = self.router.stats()
        self.assertEqual((stats['local'], stats['agent'], stats['fallback'], stats['failed']), (0, 0, 1, 0))
        self.assertEqual(stats['problem'], 'local:error_response')
        self.assertNoWords()

    def test_local_that_gives_no_answer_at_all_falls_back_too(self):
        self.options(agent=AGENT)
        self.center.route_answer = decision(route='local')
        for answer in ((500, {'message': 'boom'}), (404, {'message': 'Agent not found'}), (200, {'unexpected': True}),
                       (200, conversation_response('', 'action_done')), (200, conversation_response('   ', 'query_answer'))):
            self.ha.conversation_answers['conversation.home_assistant'] = answer
            self.ha.conversations.clear()
            self.assertEqual(self.router.handle(TEXT, 'pt'), 'Resposta do assistente.', answer)
            self.assertEqual(self.agents(), ['conversation.home_assistant', AGENT])
        self.assertEqual(self.router.stats()['fallback'], 5)

    def test_agent_path(self):
        self.options(agent=AGENT)
        self.center.route_answer = decision(route='agent', category='compound')
        self.assertEqual(self.router.handle(TEXT, 'pt', 'in-1'), 'Resposta do assistente.')
        self.assertEqual(self.agents(), [AGENT])
        self.assertEqual(self.ha.conversations[0]['text'], TEXT)
        stats = self.router.stats()
        self.assertEqual((stats['local'], stats['agent'], stats['fallback'], stats['failed']), (0, 1, 0, 0))
        self.assertNoWords()

    def test_sensitive_and_agent_decisions_never_become_local(self):
        self.options(agent=AGENT)
        for answer in (decision(route='agent', category='simple', sensitive=True), decision(route='agent', category='simple'),
                       decision(route='local', category='simple', sensitive=True)):  # even a contradictory one: the agent
            self.center.route_answer = answer
            self.ha.conversations.clear()
            self.router.handle('tranca a porta da frente', 'pt')
            self.assertEqual(self.agents(), [AGENT], answer)
        self.assertEqual(self.router.stats()['agent'], 3)

    def test_observe_asks_counts_and_always_goes_to_the_agent(self):
        self.options(agent=AGENT, mode='observe')
        self.center.route_answer = decision(route='local', category='simple')
        self.router.handle(TEXT, 'pt')
        self.center.route_answer = decision(route='agent')
        self.router.handle(TEXT, 'pt')
        self.assertEqual(len(self.center.routed), 2)
        self.assertEqual(self.agents(), [AGENT, AGENT])  # never the local assistant
        stats = self.router.stats()
        self.assertEqual((stats['observed_local'], stats['observed_agent'], stats['agent'], stats['local'], stats['fallback']), (1, 1, 2, 0, 0))
        self.center.stop()  # in observe a center that does not answer is not a "fallback": the agent was the plan anyway
        self.router.handle(TEXT, 'pt')
        stats = self.router.stats()
        self.assertEqual((stats['agent'], stats['fallback'], stats['center_errors']), (3, 0, 1))

    def test_off_never_asks_the_center(self):
        self.options(agent=AGENT, mode='off')
        self.center.route_answer = decision(route='local')
        self.assertEqual(self.router.handle(TEXT, 'pt'), 'Resposta do assistente.')
        self.assertEqual((self.center.routed, self.agents()), ([], [AGENT]))
        stats = self.router.stats()
        self.assertEqual((stats['agent'], stats['center_calls'], stats['center_avg_ms']), (1, 0, None))

    def test_empty_or_unknown_mode_means_on(self):
        self.options(agent=AGENT, mode='')
        self.center.route_answer = decision(route='local')
        self.ha.conversation_answers['conversation.home_assistant'] = (200, conversation_response('Feito.', 'action_done'))
        self.assertEqual(self.router.handle(TEXT, 'pt'), 'Feito.')
        os.environ['IQ_VOICE_ROUTE'] = 'sometimes'
        self.assertEqual(settings.voice_route_mode(), 'on')

    def test_the_center_that_cannot_answer_sends_to_the_agent(self):
        self.options(agent=AGENT)
        cases = [('401', lambda: setattr(self.center, 'route_answer', (401, {'error': 'unauthorized'}, {}))),
                 ('410', lambda: setattr(self.center, 'route_answer', (410, {'error': 'gone'}, {}))),
                 ('429', lambda: setattr(self.center, 'route_answer', (429, {'error': 'rate'}, {}))),
                 ('500', lambda: setattr(self.center, 'route_answer', (500, {'error': 'x'}, {}))),
                 ('malformed', lambda: setattr(self.center, 'route_answer', (200, b'<html>', {}))),
                 ('no route', lambda: setattr(self.center, 'route_answer', (200, {'category': 'simple'}, {}))),
                 ('down', lambda: self.center.stop())]
        for name, break_it in cases:
            break_it()
            self.ha.conversations.clear()
            self.assertEqual(self.router.handle(TEXT, 'pt'), 'Resposta do assistente.', name)
            self.assertEqual(self.agents(), [AGENT], name)
        stats = self.router.stats()
        self.assertEqual((stats['fallback'], stats['agent'], stats['failed'], stats['center_errors']), (7, 0, 0, 7))
        self.assertNoWords()

    def test_a_slow_center_sends_to_the_agent_within_the_budget(self):
        self.options(agent=AGENT)
        self.center.route_delay = 1.5
        self.center.route_answer = decision(route='local')
        with mock.patch.object(center_module, 'ROUTE_BUDGET', 0.3):
            started = time.monotonic()
            self.assertEqual(self.router.handle(TEXT, 'pt'), 'Resposta do assistente.')
        self.assertLess(time.monotonic() - started, 1.2)
        self.assertEqual(self.agents(), [AGENT])
        stats = self.router.stats()
        self.assertEqual((stats['fallback'], stats['problem']), (1, 'center:timeout'))
        self.assertGreaterEqual(stats['center_avg_ms'], 250)

    def test_a_home_that_is_not_paired_goes_to_the_agent_without_calling(self):
        self.options(agent=AGENT)
        self.edge.forget()
        self.assertEqual(self.router.handle(TEXT, 'pt'), 'Resposta do assistente.')
        self.assertEqual((self.center.routed, self.agents()), ([], [AGENT]))
        stats = self.router.stats()
        self.assertEqual((stats['fallback'], stats['center_calls']), (1, 0))  # no call = not in the average

    def test_no_agent_configured_says_so(self):
        self.center.route_answer = decision(route='agent')
        self.assertEqual(settings.voice_agent(), '')
        pt = self.router.handle(TEXT, 'pt-BR')
        self.assertIn('sem assistente configurado', pt)
        self.assertEqual(self.router.handle(TEXT, 'en-US'), 'The IQ voice router has no assistant configured. Choose one in the add-on options.')
        self.assertEqual(self.agents(), [])
        stats = self.router.stats()
        self.assertEqual((stats['failed'], stats['problem']), (2, 'agent:none'))
        self.options(agent='', mode='off')  # an empty option is the same as none; the sentence does not depend on the mode
        self.assertIn('sem assistente', self.router.handle(TEXT, ''))
        self.options(agent='not-an-entity')  # an invalid value counts as none
        self.assertEqual(settings.voice_agent(), '')
        self.assertNoWords()

    def test_without_an_agent_the_local_assistant_still_answers_what_it_understands(self):
        self.center.route_answer = decision(route='local')
        self.ha.conversation_answers['conversation.home_assistant'] = (200, conversation_response('Feito.', 'action_done'))
        self.assertEqual(self.router.handle(TEXT, 'pt'), 'Feito.')
        del self.ha.conversation_answers['conversation.home_assistant']  # ...and when it does not, there is no agent to fall back to
        self.assertIn('sem assistente configurado', self.router.handle(TEXT, 'pt'))

    def test_an_agent_that_is_the_router_itself_is_not_called(self):
        self.options(agent='conversation.iq_router')
        self.center.route_answer = decision(route='agent')
        answer = self.router.handle(TEXT, 'en', caller='conversation.iq_router')
        self.assertIn('the router itself', answer)
        self.assertEqual(self.agents(), [])
        self.assertEqual(self.router.stats()['problem'], 'agent:itself')
        self.assertEqual(self.router.handle(TEXT, 'pt', caller='conversation.other'), 'Resposta do assistente.')

    def test_long_text_skips_the_center(self):
        self.options(agent=AGENT)
        self.center.route_answer = decision(route='local')
        long_text = 'a' * (voice.MAX_ROUTE_TEXT + 1)
        self.assertEqual(self.router.handle(long_text, 'pt'), 'Resposta do assistente.')
        self.assertEqual((self.center.routed, self.agents()), ([], [AGENT]))
        self.assertEqual(self.router.stats()['agent'], 1)
        self.router.handle('b' * voice.MAX_ROUTE_TEXT, 'pt')  # exactly 500 is still asked
        self.assertEqual(len(self.center.routed), 1)

    def test_the_agent_that_fails(self):
        self.options(agent=AGENT)
        self.center.route_answer = decision(route='agent')
        for answer, expected in (((500, {'message': 'boom'}), 'Não consegui falar com o assistente agora'),
                                 ((200, {'weird': 1}), 'Não consegui falar com o assistente agora'),
                                 ((200, conversation_response('', 'action_done')), 'Não consegui falar com o assistente agora'),
                                 # Home Assistant's own error sentence is spoken (it is the agent's answer), but it counts as a failure
                                 ((200, conversation_response('Desculpe, deu erro.', 'error', code='unknown')), 'Desculpe, deu erro.')):
            self.ha.conversation_answers[AGENT] = answer
            self.assertIn(expected, self.router.handle(TEXT, 'pt'))
        self.ha.conversation_answers[AGENT] = (500, {'message': 'boom'})
        self.assertEqual(self.router.handle(TEXT, 'en-US'), 'I could not reach the assistant right now. Please try again in a moment.')
        stats = self.router.stats()
        self.assertEqual((stats['failed'], stats['agent']), (5, 0))
        self.ha.stop()  # Home Assistant itself is gone
        self.assertIn('Não consegui falar', self.router.handle(TEXT, 'pt'))
        self.assertEqual(self.router.stats()['problem'], 'agent:offline')
        self.assertNoWords()

    def test_a_slow_agent_is_waited_for(self):
        self.options(agent=AGENT)
        self.center.route_answer = decision(route='agent')
        self.ha.conversation_delay = 0.4
        self.assertEqual(self.router.handle(TEXT, 'pt'), 'Resposta do assistente.')


class ConversationIdTests(VoiceCase):
    def test_a_follow_up_goes_to_the_same_conversation(self):
        self.options(agent=AGENT)
        self.center.route_answer = decision(route='agent')
        self.ha.conversation_answers[AGENT] = lambda body: (200, conversation_response('Ok.', 'query_answer', body.get('conversation_id') or 'agent-conv-9'))
        self.router.handle('primeira', 'pt', 'incoming-A')
        self.router.handle('segunda', 'pt', 'incoming-A')
        self.router.handle('outra pessoa', 'pt', 'incoming-B')
        self.router.handle('sem id', 'pt', '')
        sent = [body.get('conversation_id') for body in self.ha.conversations]
        self.assertEqual(sent, [None, 'agent-conv-9', None, None])  # B and "no id" start their own; the router's id is never sent
        self.assertNotIn('incoming-A', sent)

    def test_the_local_assistant_has_its_own_conversation_id(self):
        self.options(agent=AGENT)
        self.ha.conversation_answers['conversation.home_assistant'] = lambda body: (200, conversation_response('Feito.', 'action_done', 'local-conv-1'))
        self.ha.conversation_answers[AGENT] = lambda body: (200, conversation_response('Ok.', 'query_answer', 'agent-conv-1'))
        for route, text in (('local', 'um'), ('agent', 'dois'), ('local', 'tres'), ('agent', 'quatro')):
            self.center.route_answer = decision(route=route)
            self.router.handle(text, 'pt', 'incoming-A')
        by_agent = {}
        for body in self.ha.conversations:
            by_agent.setdefault(body['agent_id'], []).append(body.get('conversation_id'))
        self.assertEqual(by_agent, {'conversation.home_assistant': [None, 'local-conv-1'], AGENT: [None, 'agent-conv-1']})

    def test_the_memory_is_bounded_and_expires(self):
        now = [100.0]
        memory = voice.Memory(size=3, seconds=60, clock=lambda: now[0])
        for index in range(5):
            memory.put(('agent', f'in-{index}'), f'conv-{index}')
        self.assertEqual(len(memory), 3)
        self.assertEqual((memory.get(('agent', 'in-0')), memory.get(('agent', 'in-4'))), ('', 'conv-4'))
        now[0] += 61
        self.assertEqual(memory.get(('agent', 'in-4')), '')  # expired
        memory.put(('agent', 'z'), 'conv-z')  # putting prunes everything that expired
        self.assertEqual(len(memory), 1)
        memory.put(('agent', 'a'), '1')
        now[0] += 30
        memory.put(('agent', 'b'), '2')
        now[0] += 40  # 'a' is 70 s old, 'b' 40 s: putting prunes the expired ones
        memory.put(('agent', 'c'), '3')
        self.assertEqual((memory.get(('agent', 'a')), memory.get(('agent', 'b')), memory.get(('agent', 'c'))), ('', '2', '3'))

    def test_the_memory_keeps_ids_never_words(self):
        self.options(agent=AGENT)
        self.center.route_answer = decision(route='agent')
        self.router.handle(TEXT, 'pt', 'incoming-A')
        self.assertTrue(self.router.memory.items)
        self.assertNotIn('luz', repr(self.router.memory.items))
        self.assertNoWords()


class StatsAndLogTests(VoiceCase):
    def test_counters_and_the_average_time(self):
        self.options(agent=AGENT)
        ticks = iter([0.0, 0.1, 10.0, 10.3])
        router = voice.Router(self.edge, clock=lambda: next(ticks))
        self.center.route_answer = decision(route='agent')
        router.handle(TEXT, 'pt')
        router.handle(TEXT, 'pt')
        stats = router.stats()
        self.assertEqual((stats['center_calls'], stats['center_avg_ms'], stats['agent']), (2, 200, 2))
        self.assertTrue(stats['since'].startswith('20'))

    def test_every_request_ends_in_exactly_one_outcome(self):
        self.options(agent=AGENT)
        for answer in (decision(route='local'), decision(route='agent'), (500, {}, {})):
            self.center.route_answer = answer
            self.router.handle(TEXT, 'pt')
        stats = self.router.stats()
        self.assertEqual(stats['local'] + stats['agent'] + stats['fallback'] + stats['failed'], 3)

    def test_no_word_of_a_request_in_the_log_on_any_path(self):
        word = 'segredo-da-familia-xyz'
        self.options(agent=AGENT)
        for answer in (decision(route='local'), decision(route='agent'), (500, {}, {}), (200, b'junk', {})):
            self.center.route_answer = answer
            self.router.handle(f'{word} {TEXT}', 'pt', 'incoming-A')
        self.options(agent='')
        self.router.handle(f'{word} {TEXT}', 'pt')
        self.ha.stop()
        self.options(agent=AGENT)
        self.router.handle(f'{word} {TEXT}', 'pt')
        self.assertNoWords(word, TEXT)


class VoiceOptionTests(VoiceCase):
    def test_empty_options_set_nothing(self):
        os.environ.pop('IQ_VOICE_AGENT', None)
        os.environ.pop('IQ_VOICE_ROUTE', None)
        settings.write_json(settings.data_dir() / 'options.json', {'center_url': 'https://business.iqautom8.com', 'pairing_code': '',
                                                                 'voice_agent': '', 'voice_route': ''}, private=False)
        self.assertEqual(settings.apply_voice_options(), [])
        self.assertEqual((settings.voice_agent(), settings.voice_route_mode()), ('', 'on'))
        self.assertNotIn('IQ_VOICE_AGENT', os.environ)
        self.assertNotIn('IQ_VOICE_ROUTE', os.environ)
        (settings.data_dir() / 'options.json').unlink()  # no file at all
        self.assertEqual(settings.apply_voice_options(), [])

    def test_valid_options_become_the_variables_and_invalid_ones_are_ignored(self):
        os.environ.pop('IQ_VOICE_AGENT', None)
        os.environ.pop('IQ_VOICE_ROUTE', None)
        path = settings.data_dir() / 'options.json'
        settings.write_json(path, {'voice_agent': ' Conversation.IQ_Assistant ', 'voice_route': 'Observe'}, private=False)
        self.assertEqual(settings.apply_voice_options(), ['voice_agent', 'voice_route'])
        self.assertEqual((settings.voice_agent(), settings.voice_route_mode()), ('conversation.iq_assistant', 'observe'))
        for variable in settings.VOICE_OPTIONS.values():
            os.environ.pop(variable, None)
        for value in ('light.sala', 'conversation.', 'conversation.a b', ['conversation.a'], 5, True, None):
            settings.write_json(path, {'voice_agent': value, 'voice_route': 'sometimes'}, private=False)
            self.assertEqual(settings.apply_voice_options(), [], value)
            self.assertEqual((settings.voice_agent(), settings.voice_route_mode()), ('', 'on'))

    def test_the_port_and_the_host_name(self):
        self.assertEqual(settings.voice_port(), 8098)
        os.environ['IQ_VOICE_PORT'] = 'x'
        self.assertEqual(settings.voice_port(), 8098)
        os.environ['IQ_VOICE_PORT'] = '0'
        self.assertEqual(settings.voice_port(), 0)
        os.environ['IQ_VOICE_HOSTNAME'] = 'abc123-iq-edge'
        self.assertEqual(settings.addon_hostname(), 'abc123-iq-edge')
        os.environ.pop('IQ_VOICE_HOSTNAME')
        self.assertTrue(settings.addon_hostname())


if __name__ == '__main__':
    unittest.main()
