"""The add-on's tab (web.py) with the FAKE center and HA: only the Supervisor's address gets in, links under X-Ingress-Path, every form
needs the user's anti-CSRF token, pairing and unpairing from the tab, and the Bom dia form (speakers from the home, schedule) that
tests, saves here and sends to the center."""
import os
import re
import unittest
from http.client import HTTPConnection
from unittest import mock
from urllib.parse import urlencode

from iq_edge import prefs, ready, web
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


if __name__ == '__main__':
    unittest.main()
