"""The add-on's tab (web.py) with the FAKE center and HA: only the Supervisor's address gets in, links under X-Ingress-Path, every form
needs the user's anti-CSRF token, pairing and unpairing from the tab, and the Bom dia form (speakers from the home, schedule) that
tests, saves here and sends to the center."""
import os
import re
import time
import unittest
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

from iq_edge import briefing, prefs, ready, settings, voice, voice_http, web
from iq_edge.center import Center
from tests.fakes import EdgeCase

INGRESS = '/api/hassio_ingress/AbCdEf123_-'
USER = {'X-Remote-User-Id': 'u-123', 'X-Remote-User-Name': 'franco', 'X-Remote-User-Display-Name': 'Franco <C>'}


class WebCase(EdgeCase):
    peers = '127.0.0.1'

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {'IQ_INGRESS_PEERS': self.peers})
        env.start()
        self.addCleanup(env.stop)
        self.edge = Center()
        self.app = web.App(self.edge)
        self.server = web.start(self.app, host='127.0.0.1', port=0)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def call(self, method, path, form=None, headers=None):
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=60)
        sent = {'X-Ingress-Path': INGRESS, **USER, **(headers or {})}
        body = None
        if form is not None:
            body = urlencode(form, doseq=True)
            sent['Content-Type'] = 'application/x-www-form-urlencoded'
        connection.request(method, path, body, sent)
        answer = connection.getresponse()
        text = answer.read().decode('utf-8')
        connection.close()
        return answer.status, text, answer

    def token(self, html):
        return re.search(r'name="csrf" value="([0-9a-f]{40})"', html).group(1)


class OnlyTheSupervisorTests(WebCase):
    peers = '172.30.32.2'

    def test_any_other_address_is_refused(self):
        for method, path in (('GET', '/'), ('GET', '/bom-dia'), ('GET', '/style.css'), ('POST', '/parear')):
            self.assertEqual(self.call(method, path, {} if method == 'POST' else None)[0], 403)


class StatusTests(WebCase):
    def test_unpaired_page_pairs_with_the_typed_code(self):
        status, html, answer = self.call('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn("default-src 'none'", answer.getheader('Content-Security-Policy'))
        self.assertNotIn('<script', html)
        self.assertIn(f'href="{INGRESS}/style.css"', html)
        self.assertIn(f'action="{INGRESS}/parear"', html)
        self.assertIn('Código de pareamento', html)
        token = self.token(html)
        self.assertEqual(self.call('POST', '/parear', {'code': '123456'})[0], 403)  # no token
        self.assertEqual(self.call('POST', '/parear', {'code': '123456', 'csrf': token}, {'X-Remote-User-Id': 'someone-else'})[0], 403)
        status, html, _ = self.call('POST', '/parear', {'code': '12 34 56', 'csrf': token})
        self.assertEqual(status, 200)
        self.assertIn('Casa pareada com a plataforma IQ.', html)
        self.assertIn('Casa: Casa &lt;Teste&gt;', html)
        self.assertNotIn('C' * 43, html)
        status, html, _ = self.call('GET', '/', headers={'Accept-Language': 'en-US,en'})
        self.assertIn('Home: Casa &lt;Teste&gt;', html)
        self.assertIn('>Unpair</a>', html)

    def test_refused_code_and_unpair_with_confirmation(self):
        html = self.call('GET', '/')[1]
        html = self.call('POST', '/parear', {'code': '000000', 'csrf': self.token(html)})[1]
        self.assertIn('A plataforma recusou o código', html)
        html = self.call('POST', '/parear', {'code': '123456', 'csrf': self.token(html)})[1]
        self.assertTrue(self.edge.paired())
        status, html, _ = self.call('GET', '/desparear')
        self.assertIn('Desparear esta casa?', html)
        self.assertIn(f'href="{INGRESS}/">Cancelar</a>', html)
        status, html, _ = self.call('POST', '/desparear', {'csrf': self.token(html)})
        self.assertIn('Despareado. Para desfazer', html)
        self.assertFalse(self.edge.paired())
        self.assertEqual(self.center.log[-1][2], {'user': {'name': 'Franco <C>'}})

    def test_the_bom_dia_lines_ai_by_the_center_prepared_and_the_event(self):
        self.edge.pair('123456')
        html = self.call('GET', '/')[1]
        self.assertIn('<dt>IA pelo centro</dt><dd>ainda não usada</dd>', html)
        self.assertIn('<dt>Bom dia</dt><dd>ainda não preparado</dd>', html)
        self.assertNotIn('Evento iq_bom_dia', html)  # outside Home Assistant there is no listener
        from iq_edge import briefing
        briefing.usar_centro(self.edge)
        self.addCleanup(briefing.usar_centro, None)
        prefs.save_local(self.prefs())
        ready.prepare('pt')  # the fake center answers 503 (no key): the rule text, and "no answer" on the tab
        self.app.listener = mock.Mock(public=lambda: {'state': 'listening'})
        html = self.call('GET', '/')[1]
        self.assertRegex(html, r'<dt>IA pelo centro</dt><dd>sem resposta \(última vez \d\d:\d\d\)</dd>')
        self.assertRegex(html, r'<dt>Bom dia</dt><dd>preparado às \d\d:\d\d</dd>')
        self.assertIn('<dt>Evento iq_bom_dia</dt><dd>ouvindo</dd>', html)
        self.center.compose_answer = (200, {'text': 'Bom dia!', 'picks': []}, {})
        prefs.preview(self.prefs())
        self.app.listener = mock.Mock(public=lambda: {'state': 'auth_failed'})
        html = self.call('GET', '/', headers={'Accept-Language': 'en'})[1]
        self.assertRegex(html, r'<dt>AI by the platform</dt><dd>ok \(last time \d\d:\d\d\)</dd>')
        self.assertIn('<dd>Home Assistant refused the access</dd>', html)


class BriefingTests(WebCase):
    def setUp(self):
        super().setUp()
        self.edge.pair('123456')

    def form(self, html, **changes):
        values = {'csrf': self.token(html), 'house_state': 'on', 'sources': f'Cidade = {self.ha.url}/rss\nOutra | {self.ha.url}/rss?x=1',
                  'picks': 'Cidade = 2', 'total_min': '1', 'total_max': '3', 'max_words': '120', 'rules': 'Só o que importa.',
                  'speaker': 'media_player.sala', 'volume': '40', 'tts_engine': 'tts.google_pt', 'language': 'pt', 'temp_unit': 'C',
                  'time': '06:45', 'day0': 'on', 'day4': 'on', 'action': 'save'}
        values.update(changes)
        return {k: v for k, v in values.items() if v is not None}

    def test_the_form_shows_the_home_and_saves_and_sends(self):
        status, html, _ = self.call('GET', '/bom-dia')
        self.assertEqual(status, 200)
        self.assertIn('<option value="media_player.sala">Sonos &lt;Sala&gt;</option>', html)
        self.assertIn('<option value="tts.google_pt">Google PT</option>', html)
        self.assertIn('Valores iniciais: nada salvo ainda.', html)
        self.assertIn(f'action="{INGRESS}/falar"', html)
        status, html, _ = self.call('POST', '/bom-dia', self.form(html))
        self.assertIn('Salvo. A plataforma guardou a versão 8.', html)
        version, values, _ = prefs.load()
        self.assertEqual((version, values['schedule'], values['temp_unit'], values['picks']),
                         (8, {'time': '06:45', 'days': [0, 4]}, 'C', {'Cidade': 2, 'Outra': 1}))
        sent = self.center.prefs[0]
        self.assertEqual((sent['user'], sent['prefs']['schedule']['time']), ({'id': 'u-123', 'name': 'Franco <C>'}, '06:45'))
        self.assertFalse(prefs.pending())
        self.assertIn('Versão 8', self.call('GET', '/bom-dia')[1])

    def test_test_shows_the_text_and_saves_nothing(self):
        html = self.call('GET', '/bom-dia')[1]
        status, html, _ = self.call('POST', '/bom-dia', self.form(html, action='test', max_words='90'))
        self.assertEqual(status, 200)
        self.assertIn('Prefeitura anuncia obras', html)
        self.assertIn('nada foi falado nem salvo', html)
        self.assertEqual(prefs.load()[0], 0)
        self.assertEqual(self.center.prefs, [])

    def test_invalid_values_and_offline_center(self):
        html = self.call('GET', '/bom-dia')[1]
        status, html, _ = self.call('POST', '/bom-dia', self.form(html, sources='sem endereço'))
        self.assertEqual(status, 400)
        self.assertIn('Fontes: de 1 a 20 linhas', html)
        status, html, _ = self.call('POST', '/bom-dia', self.form(html, time='25:00'))
        self.assertIn('Fala automática: horário HH:MM', html)
        self.center.stop()
        status, html, _ = self.call('POST', '/bom-dia', self.form(html))
        self.assertIn('Salvo nesta casa. A plataforma recebe quando a conexão voltar.', html)
        self.assertTrue(prefs.pending())
        self.assertIn('ainda não chegaram à plataforma', self.call('GET', '/bom-dia')[1])

    def test_speak_now(self):
        html = self.call('GET', '/bom-dia')[1]
        with mock.patch.object(prefs, 'speak_now', return_value=(False, '')):
            self.assertIn('Escolha o alto-falante e o motor de voz', self.call('POST', '/falar', {'csrf': self.token(html)})[1])
        with mock.patch.object(prefs, 'speak_now', return_value=(True, 'Um instante.')):
            self.assertIn('Falando o Bom dia', self.call('POST', '/falar', {'csrf': self.token(html)})[1])


class RepeatTests(WebCase):
    """0.2.6: "Repetir o último" next to "Falar agora": off, with the reason, when there is nothing to repeat; POST /repetir plays the saved
    audio (never the voice engine) and tells the person why when nothing plays."""

    def setUp(self):
        super().setUp()
        self.edge.pair('123456')
        self.media = Path(self.tmp.name) / 'media'
        self.media.mkdir()
        env = mock.patch.dict(os.environ, {'IQ_BRIEFING_SATELLITE': ''})
        env.start()
        self.addCleanup(env.stop)
        prefs.save_local(self.prefs())

    def keep(self):
        self.assertTrue(briefing.guardar_ultimo('Bom dia.', 'pt', briefing.speaker_config(), baixar_fn=lambda *a: (b'ID3' + b'\0' * 64, 'mp3')))

    def test_the_button_is_off_with_the_reason_until_there_is_something_to_repeat(self):
        html = self.call('GET', '/bom-dia')[1]
        self.assertIn(f'action="{INGRESS}/falar"', html)
        self.assertIn(f'action="{INGRESS}/repetir"', html)
        self.assertRegex(html, r'<button type="submit" disabled>Repetir o último</button>')
        self.assertIn('Ainda não há um Bom dia guardado para repetir.', html)
        english = self.call('GET', '/bom-dia', headers={'Accept-Language': 'en'})[1]
        self.assertRegex(english, r'<button type="submit" disabled>Repeat the last one</button>')
        self.assertIn('There is no good morning saved to repeat yet.', english)
        self.keep()
        html = self.call('GET', '/bom-dia')[1]
        self.assertRegex(html, r'<button type="submit">Repetir o último</button>')
        self.assertRegex(html, r'Repetir toca o áudio guardado do Bom dia das \d\d:\d\d; a voz não é gerada de novo\.')
        self.assertRegex(self.call('GET', '/bom-dia', headers={'Accept-Language': 'en'})[1], r'<button type="submit">Repeat the last one</button>')
        (self.media / 'iq-edge' / 'bom-dia.mp3').unlink()
        self.assertIn('O áudio guardado não está mais na pasta de mídia do Home Assistant.', self.call('GET', '/bom-dia')[1])

    def test_an_old_one_says_so(self):
        self.keep()
        last = settings.data_dir() / 'briefing-last.json'
        old = (datetime.now(timezone.utc) - timedelta(hours=21)).isoformat()
        settings.write_json(last, dict(settings.read_json(last), spoken_at=old))
        html = self.call('GET', '/bom-dia')[1]
        self.assertIn('O último Bom dia tem mais de 20 horas e não é mais repetido.', html)
        self.assertRegex(html, r'<button type="submit" disabled>')

    def test_post_needs_the_token_and_tells_why_nothing_played(self):
        html = self.call('GET', '/bom-dia')[1]
        self.assertEqual(self.call('POST', '/repetir', {})[0], 403)  # no token
        for answer, text in (('none', 'Ainda não há um Bom dia guardado para repetir.'),
                             ('old', 'O último Bom dia tem mais de 20 horas'), ('missing', 'O áudio guardado não está mais na pasta de mídia'),
                             ('speaker', 'Escolha o alto-falante e o motor de voz'), ('busy', 'Um Bom dia está falando agora.')):
            with mock.patch.object(prefs, 'repeat_last', return_value=answer):
                status, page, _ = self.call('POST', '/repetir', {'csrf': self.token(html)})
            self.assertEqual(status, 200)
            self.assertIn(text, page, answer)
            self.assertIn('class="note warn"', page)
        with mock.patch.object(prefs, 'repeat_last', return_value='ok'):
            page = self.call('POST', '/repetir', {'csrf': self.token(html)})[1]
            self.assertIn('Repetindo o último Bom dia no alto-falante escolhido.', page)
            self.assertIn('class="note ok"', page)
            self.assertIn('Repeating the last good morning', self.call('POST', '/repetir', {'csrf': self.token(html)},
                                                                      {'Accept-Language': 'en'})[1])

    def test_post_plays_the_saved_file_and_never_asks_for_a_voice(self):
        self.keep()
        html = self.call('GET', '/bom-dia')[1]
        before = len(self.ha.log)
        with mock.patch.object(briefing, '_estimar_duracao', return_value=0.0):
            page = self.call('POST', '/repetir', {'csrf': self.token(html)})[1]
        self.assertIn('Repetindo o último Bom dia', page)
        for _ in range(100):  # the play runs in the background
            if self.ha.service_calls:
                break
            time.sleep(0.05)
        self.assertEqual(self.ha.service_calls, [('/api/services/media_player/play_media', {
            'entity_id': 'media_player.sala', 'media_content_id': 'media-source://media_source/local/iq-edge/bom-dia.mp3',
            'media_content_type': 'music', 'announce': True})])
        paths = [path for _, path in self.ha.log[before:]]
        self.assertFalse([path for path in paths if any(part in path for part in ('/tts/speak', '/tts_get_url', '/tts_proxy/', 'assist_satellite'))])
        self.assertEqual((self.ha.tts_requests, self.ha.events), ([], []))


class AssistantTests(WebCase):
    """0.2.5: the Assistente page (the voice router): with the router off it says so and which options turn it on; with it running, what
    to type in the integration, the password only after the button, the mode, the kind of agent (never its address) and the counters;
    never a word of a request."""

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {'IQ_VOICE_HOSTNAME': 'abc123-iq-edge', 'IQ_VOICE_PORT': '8098', 'IQ_VOICE_AGENT': 'conversation.iq_assistant'})
        env.start()
        self.addCleanup(env.stop)
        self.edge.pair('123456')
        self.router = voice.Router(self.edge)
        self.app.voice = self.router
        self.password = voice_http.password()

    def test_with_the_router_off_the_page_says_so_and_shows_nothing_of_it(self):
        self.app.voice = None
        os.environ.pop('IQ_VOICE_AGENT')  # no voice option at all
        link = f'<a href="{INGRESS}/assistente">Assistente</a>'
        self.assertIn(link, self.call('GET', '/')[1])  # the section is always there
        self.assertIn('>Assistant</a>', self.call('GET', '/', headers={'Accept-Language': 'en'})[1])
        status, html, _ = self.call('GET', '/assistente')
        self.assertEqual(status, 200)
        self.assertIn('O roteador de voz está desligado', html)
        for option in ('voice_agent', 'voice_agent_url', 'voice_agent_user', 'voice_agent_password', 'Só voice_route não liga o roteador'):
            self.assertIn(option, html)
        for hidden in ('/v1/conversation', 'abc123-iq-edge', 'Mostrar a senha', 'Usuário', 'Foram ao assistente', 'Tempo médio', self.password):
            self.assertNotIn(hidden, html)
        english = self.call('GET', '/assistente', headers={'Accept-Language': 'en'})[1]
        self.assertIn('The voice router is off.', english)
        self.assertIn('voice_agent_url', english)
        self.assertIn('voice_route alone does not turn the router on', english)
        self.assertEqual(self.call('GET', '/assistente.js')[0], 404)
        self.assertEqual(self.call('POST', '/assistente/senha', {'csrf': self.app.csrf('u-123')})[0], 404)  # there is no password to show
        os.environ['IQ_VOICE_AGENT_URL'] = 'http://agent.local:5000/hook-secreto'  # options filled in, but the port did not open
        html = self.call('GET', '/assistente')[1]
        self.assertIn('não abriu a porta 8098', html)
        self.assertNotIn('desligado', html)
        self.assertIn('did not open port 8098', self.call('GET', '/assistente', headers={'Accept-Language': 'en'})[1])
        for secret in ('agent.local', 'hook-secreto'):
            self.assertNotIn(secret, html)

    def test_the_page_shows_the_address_user_mode_and_agent_but_not_the_password(self):
        status, html, answer = self.call('GET', '/assistente')
        self.assertEqual(status, 200)
        self.assertIn('<dd class="text">http://abc123-iq-edge:8098/v1/conversation</dd>', html)
        self.assertIn('<dt>Usuário</dt><dd>iq</dd>', html)
        self.assertIn('Ligado: o centro decide', html)
        self.assertIn('<dt>Assistente escolhido</dt><dd>conversation.iq_assistant</dd>', html)
        self.assertIn(f'action="{INGRESS}/assistente/senha"', html)
        self.assertIn('Mostrar a senha', html)
        self.assertNotIn(self.password, html)  # not until the button
        self.assertNotIn('<script', html)
        self.assertIn("script-src 'self'", answer.getheader('Content-Security-Policy'))
        self.assertIn("default-src 'none'", answer.getheader('Content-Security-Policy'))

    def test_the_button_reveals_the_password_with_a_copy_button(self):
        html = self.call('GET', '/assistente')[1]
        token = self.token(html)
        self.assertEqual(self.call('POST', '/assistente/senha', {})[0], 403)  # no token
        self.assertEqual(self.call('POST', '/assistente/senha', {'csrf': token}, {'X-Remote-User-Id': 'someone-else'})[0], 403)
        status, html, answer = self.call('POST', '/assistente/senha', {'csrf': token})
        self.assertEqual(status, 200)
        self.assertIn(f'<input id="voice-password" value="{self.password}" readonly', html)
        self.assertIn('data-copy="voice-password" data-done="Copiado">Copiar</button>', html)
        self.assertIn(f'<script src="{INGRESS}/assistente.js"></script>', html)
        self.assertEqual(answer.getheader('Cache-Control'), 'no-store')
        self.assertNotIn(self.password, self.call('GET', '/assistente')[1])  # the next visit hides it again
        status, script, answer = self.call('GET', '/assistente.js')
        self.assertEqual((status, answer.getheader('Content-Type')), (200, 'text/javascript; charset=utf-8'))
        self.assertIn('data-copy', script)
        self.assertIn('navigator.clipboard', script)
        self.assertIn('execCommand', script)  # the fallback when the page is not a secure context
        self.assertNotIn(self.password, script)
        english = self.call('POST', '/assistente/senha', {'csrf': token}, {'Accept-Language': 'en'})[1]
        self.assertIn('data-done="Copied">Copy</button>', english)

    def test_the_counters_and_the_modes(self):
        self.ha.conversation_answers['conversation.iq_assistant'] = (200, {'response': {'response_type': 'query_answer',
                                                                                         'speech': {'plain': {'speech': 'Oi.'}}}, 'conversation_id': 'c1'})
        self.center.route_answer = (200, {'route': 'agent', 'category': 'chat', 'sensitive': False, 'engine': 'jev'}, {})
        word = 'confidencial-xpto-123'
        self.router.handle(f'{word} ligar', 'pt')
        self.center.route_answer = (500, {}, {})
        self.router.handle(f'{word} desligar', 'pt')
        html = self.call('GET', '/assistente')[1]
        self.assertIn('<dt>Foram ao assistente local</dt><dd>0</dd>', html)
        self.assertIn('<dt>Foram ao assistente</dt><dd>1</dd>', html)
        self.assertIn('<dt>Plano B (centro ou assistente local sem resposta)</dt><dd>1</dd>', html)
        self.assertIn('<dt>Sem resposta de ninguém</dt><dd>0</dd>', html)
        self.assertRegex(html, r'<dt>Tempo médio da consulta ao centro</dt><dd>\d+ ms</dd>')
        self.assertIn('<dt>Último problema</dt><dd>center:http_500</dd>', html)
        self.assertNotIn(word, html)  # never a word of a request
        os.environ['IQ_VOICE_ROUTE'] = 'observe'
        html = self.call('GET', '/assistente')[1]
        self.assertIn('Observando: tudo vai ao assistente', html)
        self.assertIn('Decisões do centro (só observadas)', html)
        os.environ['IQ_VOICE_ROUTE'] = 'off'
        html = self.call('GET', '/assistente', headers={'Accept-Language': 'en'})[1]
        self.assertIn('Off: everything goes to the assistant', html)
        self.assertIn('<dt>Went to the local assistant</dt><dd>0</dd>', html)
        self.assertNotIn('Center decisions', html)

    def test_an_agent_by_address_is_named_by_its_kind_never_by_its_address(self):
        os.environ.update({'IQ_VOICE_AGENT_URL': 'http://agente-secreto.local:5000/caminho-secreto?token=chave-secreta',
                           'IQ_VOICE_AGENT_USER': 'usuario-secreto', 'IQ_VOICE_AGENT_PASSWORD': 'senha-secreta'})
        token = self.token(self.call('GET', '/assistente')[1])
        pages = [self.call('GET', '/assistente')[1], self.call('POST', '/assistente/senha', {'csrf': token})[1],
                 self.call('GET', '/assistente', headers={'Accept-Language': 'en'})[1]]
        self.assertIn('<dt>Assistente escolhido</dt><dd>agente por endereço</dd>', pages[0])
        self.assertIn('<dt>Chosen assistant</dt><dd>agent by address</dd>', pages[2])
        for html in pages:
            self.assertNotIn('conversation.iq_assistant', html)  # the address wins over the entity
            for secret in ('agente-secreto', 'caminho-secreto', 'chave-secreta', 'usuario-secreto', 'senha-secreta', ':5000'):
                self.assertNotIn(secret, html)
        self.assertIn(self.password, pages[1])  # (the router's own password, after the button, is what the page is for)
        os.environ['IQ_VOICE_AGENT_URL'] = 'ftp://usuario-secreto:senha-secreta@agente-secreto.local/x'  # refused, and still not shown
        html = self.call('GET', '/assistente')[1]
        self.assertIn('<dt>Assistente escolhido</dt><dd>agente por endereço (endereço recusado)</dd>', html)
        self.assertIn('agent by address (address refused)', self.call('GET', '/assistente', headers={'Accept-Language': 'en'})[1])
        for secret in ('agente-secreto', 'usuario-secreto', 'senha-secreta'):
            self.assertNotIn(secret, html)

    def test_no_agent_and_no_calls_yet(self):
        os.environ.pop('IQ_VOICE_AGENT')
        html = self.call('GET', '/assistente')[1]
        self.assertIn('nenhum (opções voice_agent ou voice_agent_url)', html)
        self.assertIn('<dt>Tempo médio da consulta ao centro</dt><dd>—</dd>', html)
        self.assertNotIn('Último problema', html)

    def test_the_other_pages_do_not_depend_on_the_router(self):
        """The Estado and Bom dia pages are the same with the router on or off, and both carry the Assistente link."""
        self.app.voice = None
        before = [self.call('GET', path)[1] for path in ('/', '/bom-dia')]
        self.app.voice = self.router
        after = [self.call('GET', path)[1] for path in ('/', '/bom-dia')]
        self.assertEqual(before, after)
        for html in after:
            self.assertIn(f'<a href="{INGRESS}/assistente">Assistente</a>', html)


if __name__ == '__main__':
    unittest.main()
