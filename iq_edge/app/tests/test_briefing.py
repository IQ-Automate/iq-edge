"""Testes do resumo falado da casa ("bom dia") — copia dos testes do Orange Pi (lote H2) para o add-on IQ (lote A4): sem as
rotas FastAPI do contrato v1 do Pi, que o add-on nao tem. Lote A5: a IA e a do centro (briefing-compose); aqui um cliente
falso com `compose(pedido)` recebe o corpo do contrato. Tudo com dados e IA falsos: nenhum teste chama o Home Assistant, a
internet ou o centro de verdade."""

import os
import unittest
from types import SimpleNamespace
from unittest import mock

from iq_edge import briefing


ESTADOS = [
    {"entity_id": "weather.forecast_home", "state": "rainy",
     "attributes": {"temperature": 78.4, "temperature_unit": "°F", "humidity": 80}},
    {"entity_id": "binary_sensor.front_door_sensor_contact", "state": "off",
     "attributes": {"device_class": "door", "friendly_name": "Porta da frente"}},
    {"entity_id": "cover.garage_door", "state": "open",
     "attributes": {"device_class": "garage", "friendly_name": "Portão da garagem"}},
    {"entity_id": "lock.garage_door_lock_remotes", "state": "locked",
     "attributes": {"friendly_name": "Trava dos controles da garagem"}},
    {"entity_id": "alarm_control_panel.iq_home_alarm_manager", "state": "disarmed",
     "attributes": {"friendly_name": "Alarme"}},
    {"entity_id": "person.victtor", "state": "home", "attributes": {"friendly_name": "Victtor"}},
    {"entity_id": "person.matheus", "state": "home", "attributes": {"friendly_name": "Matheus"}},
    {"entity_id": "person.barbara", "state": "not_home", "attributes": {"friendly_name": "Bárbara"}},
    {"entity_id": "binary_sensor.janela_quebrada", "state": "unavailable",
     "attributes": {"device_class": "window", "friendly_name": "Janela"}},
]

PREVISAO = {"temperature": 84, "templow": 71, "precipitation_probability": 62}

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Feed</title>
<item><title><![CDATA[Furacao se aproxima da Florida]]></title></item>
<item><title>Escola &amp; comunidade &lt;b&gt;celebram&lt;/b&gt;</title></item>
<item><title>Terceira noticia</title></item>
<item><title>Quarta noticia</title></item></channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<title>Alertas</title><entry><title>Alerta de enchente</title></entry>
<entry><title>Outro alerta</title></entry></feed>"""


def centro_falso(resposta):
    """Um centro falso: `compose(pedido)` guarda o pedido e devolve `resposta` (ou levanta, se for uma excecao)."""
    pedidos = []

    def compose(pedido):
        pedidos.append(pedido)
        if isinstance(resposta, BaseException):
            raise resposta
        return resposta

    return SimpleNamespace(compose=compose), pedidos


class DeteccaoTest(unittest.TestCase):
    def test_saudacoes_e_pedidos_de_resumo(self) -> None:
        casos = {
            "bom dia": "pt", "Bom dia!": "pt", "bom dia ori": "pt",
            "oi, bom dia": "pt", "Bom dia, Jarvis.": "pt",
            "good morning": "en", "Good morning Jarvis": "en",
            "resumo do dia": "pt", "me atualiza": "pt", "daily briefing": "en",
            "how is the house": "en",
        }
        for frase, idioma in casos.items():
            with self.subTest(frase=frase):
                self.assertEqual(briefing.detect_briefing(frase), idioma)

    def test_o_que_nao_e_resumo(self) -> None:
        for frase in (
            "boa noite",  # nome de uma cena, nunca resumo
            "bom dia acende a luz da sala",
            "bom dia, qual a temperatura da sala?",
            "good morning turn on the lights",
            "acende a luz da sala",
            "o dia esta bom",
            "",
        ):
            with self.subTest(frase=frase):
                self.assertIsNone(briefing.detect_briefing(frase))


class FeedTest(unittest.TestCase):
    def setUp(self) -> None:
        briefing._cache_feeds.clear()

    def test_rss_com_cdata_e_entidades(self) -> None:
        titulos = briefing.parse_feed(RSS, 3)
        self.assertEqual(len(titulos), 3)
        self.assertEqual(titulos[0], "Furacao se aproxima da Florida")
        # tag que vem escapada no titulo e removida, nunca vira HTML
        self.assertEqual(titulos[1], "Escola & comunidade celebram")

    def test_atom(self) -> None:
        self.assertEqual(briefing.parse_feed(ATOM, 5), ["Alerta de enchente", "Outro alerta"])

    def test_xml_quebrado_vira_lista_vazia(self) -> None:
        self.assertEqual(briefing.parse_feed(b"<rss><item>", 3), [])

    def test_fetch_usa_cache_por_dez_minutos(self) -> None:
        chamadas = []

        def getter(url, **kwargs):
            chamadas.append(url)
            return SimpleNamespace(
                raise_for_status=lambda: None,
                iter_content=lambda n: [RSS],
            )

        a = briefing.fetch_feed("https://exemplo/feed", 3, getter=getter)
        b = briefing.fetch_feed("https://exemplo/feed", 3, getter=getter)
        self.assertEqual(a, b)
        self.assertEqual(len(chamadas), 1)

    def test_falha_de_rede_vira_lista_vazia(self) -> None:
        import requests

        def getter(url, **kwargs):
            raise requests.ConnectionError("fora do ar")

        self.assertEqual(briefing.fetch_feed("https://exemplo/x", 3, getter=getter), [])

    def test_feeds_configurados(self) -> None:
        valor = "Orlando=https://a.com/rss, Brasil = https://b.com/rss ,lixo,x=ftp://c"
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_FEEDS": valor}):
            self.assertEqual(
                briefing.configured_feeds(),
                [("Orlando", "https://a.com/rss"), ("Brasil", "https://b.com/rss")],
            )
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_FEEDS": ""}):
            self.assertEqual(briefing.configured_feeds(), [])


class ColetaTest(unittest.TestCase):
    def test_resume_a_casa(self) -> None:
        d = briefing.collect_house(ESTADOS)
        self.assertEqual(d["clima"]["condicao"], "rainy")
        self.assertEqual(d["entidade_clima"], "weather.forecast_home")
        self.assertEqual(d["abertos"], ["Portão da garagem"])
        self.assertEqual(d["alarme"], "disarmed")
        self.assertEqual(d["pessoas"], ["Victtor", "Matheus"])

    def test_indisponivel_nao_conta_como_aberto(self) -> None:
        d = briefing.collect_house(ESTADOS)
        self.assertNotIn("Janela", d["abertos"])

    def test_tranca_destravada_conta(self) -> None:
        estados = [
            {"entity_id": "lock.porta", "state": "unlocked", "attributes": {"friendly_name": "Porta da frente"}},
        ]
        self.assertEqual(briefing.collect_house(estados)["abertos"], ["Porta da frente (destravada)"])

    def test_casa_fechada(self) -> None:
        fechada = [e for e in ESTADOS if e["entity_id"] != "cover.garage_door"]
        self.assertEqual(briefing.collect_house(fechada)["abertos"], [])


class CartoesETextoTest(unittest.TestCase):
    NOTICIAS = [("Orlando", ["Hurricane watch for Florida"]), ("Brasil", ["Eleições 2026", "Outra"])]

    def setUp(self) -> None:
        self.dados = briefing.collect_house(ESTADOS)

    def test_cartoes_em_portugues(self) -> None:
        c = briefing.build_cards(self.dados, PREVISAO, self.NOTICIAS, "pt")
        self.assertEqual([x["titulo"] for x in c], ["Clima", "Casa", "Orlando", "Brasil"])
        self.assertIn("78°F · chuva", c[0]["linhas"][0])
        self.assertEqual(c[0]["icone"], "mdi:weather-rainy")
        self.assertIn("Máxima 84°F · mínima 71°F", c[0]["linhas"])
        self.assertIn("Chuva: 62%", c[0]["linhas"])
        self.assertEqual(c[1]["tom"], "alerta")
        self.assertIn("Portão da garagem", c[1]["linhas"])
        self.assertIn("Em casa: Victtor, Matheus", c[1]["linhas"])

    def test_cartoes_em_ingles(self) -> None:
        c = briefing.build_cards(self.dados, PREVISAO, self.NOTICIAS, "en")
        self.assertEqual(c[0]["titulo"], "Weather")
        self.assertEqual(c[1]["titulo"], "Home")
        self.assertIn("At home: Victtor, Matheus", c[1]["linhas"])
        self.assertIn("rain", c[0]["linhas"][0])

    def test_casa_fechada_sem_alerta(self) -> None:
        fechada = briefing.collect_house([e for e in ESTADOS if e["entity_id"] != "cover.garage_door"])
        c = briefing.build_cards(fechada, PREVISAO, [], "pt")
        self.assertNotIn("tom", c[1])
        self.assertIn("Tudo fechado", c[1]["linhas"])
        self.assertEqual(c[1]["icone"], "mdi:home-lock")

    def test_alarme_disparado_e_alerta(self) -> None:
        estados = [dict(e) for e in ESTADOS if e["entity_id"] != "cover.garage_door"]
        for e in estados:
            if e["entity_id"].startswith("alarm_control_panel"):
                e["state"] = "triggered"
        d = briefing.collect_house(estados)
        casa = [c for c in briefing.build_cards(d, None, [], "pt") if c["titulo"] == "Casa"][0]
        # casa fechada, mas o alarme disparou: continua sendo alerta
        self.assertEqual(casa["tom"], "alerta")
        self.assertIn("Alarme: disparado", casa["linhas"])

    def test_fala_por_regra_em_portugues(self) -> None:
        f = briefing.build_spoken_fallback(self.dados, PREVISAO, self.NOTICIAS, "pt")
        self.assertTrue(f.startswith("Bom dia, Victtor e Matheus."))
        self.assertIn("Agora faz 78 graus Fahrenheit, chuva", f)
        self.assertIn("máxima de 84 e mínima de 71 graus Fahrenheit", f)
        self.assertIn("chance de chuva de 62%", f)
        self.assertIn("Portão da garagem", f)
        self.assertIn("Em Orlando: Hurricane watch for Florida.", f)

    def test_fala_por_regra_em_ingles(self) -> None:
        f = briefing.build_spoken_fallback(self.dados, PREVISAO, self.NOTICIAS, "en")
        self.assertTrue(f.startswith("Good morning, Victtor and Matheus."))
        self.assertIn("62% chance of rain", f)
        self.assertIn("In Brasil:", f)

    def test_casa_fechada_na_fala(self) -> None:
        fechada = briefing.collect_house([e for e in ESTADOS if e["entity_id"] != "cover.garage_door"])
        f = briefing.build_spoken_fallback(fechada, None, [], "pt")
        self.assertIn("A casa está toda fechada.", f)


class UnidadeTest(unittest.TestCase):
    """A casa de Orlando mistura Celsius (previsao) e Fahrenheit (sensores)."""

    DADOS_C = {"clima": {"condicao": "sunny", "temperatura": 25.0, "unidade": "°C"}}
    PREVISAO_C = {"temperature": 30, "templow": 20, "precipitation_probability": 10}

    def test_mantem_a_unidade_de_origem_por_padrao(self) -> None:
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_TEMP_UNIT": ""}):
            f = briefing.build_spoken_fallback(self.DADOS_C, self.PREVISAO_C, [], "pt")
        self.assertIn("25 graus Celsius", f)

    def test_converte_para_fahrenheit(self) -> None:
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_TEMP_UNIT": "F"}):
            f = briefing.build_spoken_fallback(self.DADOS_C, self.PREVISAO_C, [], "pt")
            c = briefing.build_cards(self.DADOS_C, self.PREVISAO_C, [], "pt")
        self.assertIn("Agora faz 77 graus Fahrenheit", f)
        self.assertIn("máxima de 86 e mínima de 68 graus Fahrenheit", f)
        self.assertEqual(c[0]["linhas"][0], "77°F · céu limpo e sol")

    def test_converte_para_celsius_em_ingles(self) -> None:
        dados = {"clima": {"condicao": "sunny", "temperatura": 77.0, "unidade": "°F"}}
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_TEMP_UNIT": "c"}):
            f = briefing.build_spoken_fallback(dados, None, [], "en")
        self.assertIn("25 degrees Celsius", f)

    def test_mesma_unidade_nao_converte(self) -> None:
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_TEMP_UNIT": "C"}):
            f = briefing.build_spoken_fallback(self.DADOS_C, None, [], "pt")
        self.assertIn("25 graus Celsius", f)


class NoticiasImportantesTest(unittest.TestCase):
    """A IA escolhe so o que importa; sem IA vale o filtro por regra."""

    CANDIDATAS = [
        ("Orlando", ["Man shot in Kissimmee parking lot", "Hurricane watch issued for Orange County", "Road closures planned for I-4 this week"]),
        ("EUA", ["Senate passes major budget bill", "Two killed in highway crash in Ohio", "Fed holds interest rates steady"]),
        ("Brasil", ["Homem é preso por furto em Contagem", "STF decide sobre ação histórica", "Time vence o clássico"]),
    ]

    def setUp(self) -> None:
        self.dados = briefing.collect_house(ESTADOS)
        env = mock.patch.dict(os.environ, {"IQ_BRIEFING_PICK": "2", "IQ_BRIEFING_PICK_MAP": "EUA=3", "IQ_BRIEFING_NEWS_RULES": "", "IQ_BRIEFING_MAX_WORDS": ""})
        env.start()
        self.addCleanup(env.stop)

    def test_filtro_por_regra_tira_crime_e_morte(self) -> None:
        titulos = ["Man shot in parking lot", "Senate passes budget", "Homem morre em acidente", "Fed holds rates", "Police arrest suspect"]
        self.assertEqual(briefing.filtrar_por_regra(titulos), ["Senate passes budget", "Fed holds rates"])

    def test_limites_por_fonte(self) -> None:
        lim = briefing._limites_por_fonte(["Orlando", "EUA", "Brasil"])
        self.assertEqual(lim, {"Orlando": 2, "EUA": 3, "Brasil": 2})

    def test_ia_escolhe_e_os_cartoes_usam_a_escolha(self) -> None:
        cliente, pedidos = centro_falso({
            "text": "Bom dia, tem alerta de furacao.", "model": "gpt-4o-mini", "words": 6,
            "picks": [{"source": "Orlando", "indices": [1]}, {"source": "EUA", "indices": [0, 2]}, {"source": "Brasil", "indices": [1]}],
        })
        fala, escolhidas = briefing.compose(self.dados, PREVISAO, self.CANDIDATAS, "pt", client=cliente)
        self.assertEqual(fala, "Bom dia, tem alerta de furacao.")
        self.assertEqual(escolhidas, [
            ("Orlando", ["Hurricane watch issued for Orange County"]),
            ("EUA", ["Senate passes major budget bill", "Fed holds interest rates steady"]),
            ("Brasil", ["STF decide sobre ação histórica"]),
        ])
        # as regras de importancia e todas as candidatas, com o limite de cada fonte, foram ao centro
        pedido = pedidos[0]
        self.assertIn("ZERO noticias", pedido["rules"])
        self.assertEqual(pedido["candidates"], [
            {"source": "Orlando", "limit": 2, "titles": self.CANDIDATAS[0][1]},
            {"source": "EUA", "limit": 3, "titles": self.CANDIDATAS[1][1]},
            {"source": "Brasil", "limit": 2, "titles": self.CANDIDATAS[2][1]},
        ])

    def test_fonte_sem_nada_importante_fica_de_fora(self) -> None:
        cliente, _ = centro_falso({"text": "Bom dia.", "picks": [
            {"source": "Orlando", "indices": []}, {"source": "EUA", "indices": [0]}, {"source": "Brasil", "indices": []}]})
        _, escolhidas = briefing.compose(self.dados, PREVISAO, self.CANDIDATAS, "pt", client=cliente)
        cartoes = briefing.build_cards(self.dados, PREVISAO, escolhidas, "pt")
        self.assertEqual([c["titulo"] for c in cartoes], ["Clima", "Casa", "EUA"])

    def test_indices_invalidos_repetidos_ou_acima_do_limite_sao_ignorados(self) -> None:
        cliente, _ = centro_falso({"text": "Bom dia.", "picks": [
            {"source": "orlando", "indices": [9, -1, 1, 1, 0, 2, True, "1"]}, {"source": "Marte", "indices": [0]}, "lixo"]})
        _, escolhidas = briefing.compose(self.dados, PREVISAO, self.CANDIDATAS, "pt", client=cliente)
        orlando = dict(escolhidas)["Orlando"]
        self.assertEqual(orlando, ["Hurricane watch issued for Orange County", "Man shot in Kissimmee parking lot"])  # max 2, sem repetir
        self.assertEqual(dict(escolhidas)["EUA"], [])

    def test_resposta_sem_selecao_usa_o_filtro_por_regra(self) -> None:
        cliente, _ = centro_falso({"text": "Bom dia, tudo certo."})
        fala, escolhidas = briefing.compose(self.dados, PREVISAO, self.CANDIDATAS, "pt", client=cliente)
        self.assertEqual(fala, "Bom dia, tudo certo.")
        self.assertEqual(dict(escolhidas)["Orlando"], ["Hurricane watch issued for Orange County", "Road closures planned for I-4 this week"])
        self.assertNotIn("Two killed in highway crash in Ohio", dict(escolhidas)["EUA"])

    def test_sem_ia_cartoes_e_fala_usam_o_filtro(self) -> None:
        with mock.patch("iq_edge.briefing._ai_client", return_value=None):
            fala, escolhidas = briefing.compose(self.dados, PREVISAO, self.CANDIDATAS, "pt")
        self.assertIn("Hurricane watch issued for Orange County", fala)
        self.assertNotIn("Man shot", fala)
        self.assertEqual(dict(escolhidas)["Brasil"], ["STF decide sobre ação histórica", "Time vence o clássico"])

    def test_regras_proprias_substituem_as_padrao(self) -> None:
        cliente, pedidos = centro_falso({"text": "Bom dia.", "picks": []})
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_NEWS_RULES": "So esporte, nada alem disso.", "IQ_BRIEFING_TOTAL": "2-3"}):
            briefing.compose(self.dados, PREVISAO, self.CANDIDATAS, "pt", client=cliente)
        self.assertEqual(pedidos[0]["rules"], "So esporte, nada alem disso.")
        self.assertEqual((pedidos[0]["total_min"], pedidos[0]["total_max"]), (2, 3))  # o total vai nos campos do contrato

    def test_tamanho_maximo_configuravel_e_limitado(self) -> None:
        cliente, pedidos = centro_falso({"text": "Bom dia.", "picks": []})
        for valor, esperado in (("60", 60), ("10", 40), ("900", 300)):
            with mock.patch.dict(os.environ, {"IQ_BRIEFING_MAX_WORDS": valor}):
                briefing.compose(self.dados, PREVISAO, self.CANDIDATAS, "pt", client=cliente)
            self.assertEqual(pedidos[-1]["max_words"], esperado)

    def test_regras_longas_sao_cortadas_em_2000(self) -> None:
        cliente, pedidos = centro_falso({"text": "Bom dia.", "picks": []})
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_NEWS_RULES": "x" * 5000, "IQ_BRIEFING_TOTAL": "4-5"}):
            briefing.compose(self.dados, PREVISAO, self.CANDIDATAS, "pt", client=cliente)
        self.assertEqual(len(pedidos[0]["rules"]), 2000)
        self.assertEqual((pedidos[0]["total_min"], pedidos[0]["total_max"]), (4, 5))  # o total pedido nunca se perde

    def test_limites_do_centro_sao_cortados_antes_de_enviar(self) -> None:
        cliente, pedidos = centro_falso({"text": "Bom dia.", "picks": []})
        dados = {"pessoas": ["N" * 100] * 25, "abertos": ["A" * 200] * 70, "alarme": "estado_de_alarme_muito_longo_" * 3,
                 "clima": {"condicao": "c" * 90, "temperatura": 20.0, "unidade": "°C"}}
        briefing.compose(dados, None, [], "pt", client=cliente)
        fatos = pedidos[0]["facts"]
        self.assertEqual((len(fatos["names"]), max(map(len, fatos["names"]))), (20, 80))
        self.assertEqual((len(fatos["open"]), max(map(len, fatos["open"]))), (60, 120))
        self.assertEqual((len(fatos["alarm"]), len(fatos["weather"]["condition"])), (40, 40))
        self.assertNotIn("total_min", pedidos[0])  # sem total pedido, os campos opcionais nao vao
        sem_unidade = {"clima": {"condicao": "rainy", "temperatura": 20.0, "unidade": ""}}
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_TEMP_UNIT": ""}):
            briefing.compose(sem_unidade, None, [], "pt", client=cliente)
        self.assertIsNone(pedidos[1]["facts"]["weather"])  # unidade so "C" ou "F": sem ela, o clima nao vai

    def test_corpo_grande_fica_abaixo_de_64_kb_e_os_indices_continuam_valendo(self) -> None:
        candidatas = [(f"Fonte {i}", [f"{i}-{j} " + "manchete longa " * 30 for j in range(40)]) for i in range(25)]
        cliente, pedidos = centro_falso({"text": "Bom dia.", "picks": [{"source": "Fonte 0", "indices": [0, 29, 39]}]})
        _, escolhidas = briefing.compose(self.dados, PREVISAO, candidatas, "pt", client=cliente)
        import json
        pedido = pedidos[0]
        self.assertLessEqual(len(json.dumps(pedido).encode()), 64 * 1024)
        self.assertLessEqual(len(pedido["candidates"]), 20)
        self.assertTrue(all(len(f["titles"]) <= 30 and all(len(t) <= 300 for t in f["titles"]) for f in pedido["candidates"]))
        enviados = len(pedido["candidates"][0]["titles"])
        esperado = [candidatas[0][1][0]] + ([candidatas[0][1][29]] if enviados > 29 else [])
        self.assertEqual(dict(escolhidas)["Fonte 0"], esperado)  # 39 nunca foi enviado: descartado
        self.assertEqual(dict(escolhidas)["Fonte 24"], [])  # fonte que nao foi ao centro fica sem noticia

    def test_fontes_homonimas_viram_uma_e_os_picks_valem_por_nome(self) -> None:
        cliente, pedidos = centro_falso({"text": "Bom dia.", "picks": [{"source": "EUA", "indices": [3, 0]}, {"source": "Brasil", "indices": []}]})
        candidatas = [("EUA", ["NPR um", "NPR dois"]), ("Brasil", ["G1 um"]), ("eua", ["BBC um", "NPR dois", "BBC dois"])]
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_PICK_MAP": "EUA=3"}):
            _, escolhidas = briefing.compose(self.dados, PREVISAO, candidatas, "pt", client=cliente)
        self.assertEqual([(f["source"], f["titles"]) for f in pedidos[0]["candidates"]],
                         [("EUA", ["NPR um", "NPR dois", "BBC um", "BBC dois"]), ("Brasil", ["G1 um"])])
        self.assertEqual(escolhidas, [("EUA", ["BBC dois", "NPR um"]), ("Brasil", [])])

    def test_fonte_sem_titulo_ou_com_limite_zero_nao_vai(self) -> None:
        cliente, pedidos = centro_falso({"text": "Bom dia.", "picks": []})
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_PICK_MAP": "EUA=0"}):
            briefing.compose(self.dados, PREVISAO, [("Orlando", []), ("EUA", ["Fed"]), ("Brasil", ["STF"])], "pt", client=cliente)
        self.assertEqual([f["source"] for f in pedidos[0]["candidates"]], ["Brasil"])

    def test_fontes_com_o_mesmo_nome_se_juntam(self) -> None:
        capturado = []
        feeds = {"https://npr": ["NPR um", "NPR dois"], "https://bbc": ["BBC um", "NPR dois"], "https://g": ["G1 um"]}
        with mock.patch("iq_edge.briefing._ai_client", return_value=None):
            briefing.handle(
                "bom dia",
                fetch_states_fn=lambda: ESTADOS,
                fetch_forecast_fn=lambda e: PREVISAO,
                fetch_feed_fn=lambda url, n: feeds[url],
                publish_fn=lambda c, d: capturado.append(c) or True,
                feeds=[("EUA", "https://npr"), ("EUA", "https://bbc"), ("Brasil", "https://g")],
            )
        cartoes = capturado[0]
        eua = [c for c in cartoes if c["titulo"] == "EUA"]
        self.assertEqual(len(eua), 1)
        self.assertEqual(eua[0]["linhas"], ["NPR um", "NPR dois", "BBC um"])  # 3 (limite do mapa), sem repetir


class DuasUnidadesTest(unittest.TestCase):
    """IQ_BRIEFING_TEMP_UNIT=FC: Fahrenheit e Celsius juntos."""

    DADOS_C = {"clima": {"condicao": "rainy", "temperatura": 25.0, "unidade": "°C"}}
    PREV_C = {"temperature": 29, "templow": 22, "precipitation_probability": 60}

    def _com(self, valor):
        env = mock.patch.dict(os.environ, {"IQ_BRIEFING_TEMP_UNIT": valor})
        env.start()
        self.addCleanup(env.stop)

    def test_fala_com_as_duas_unidades_em_portugues(self) -> None:
        self._com("FC")
        f = briefing.build_spoken_fallback(self.DADOS_C, self.PREV_C, [], "pt")
        self.assertIn("Agora faz 77 graus Fahrenheit, 25 Celsius, chuva", f)
        self.assertIn("máxima de 84 e mínima de 72 graus Fahrenheit, ou 29 e 22 Celsius", f)

    def test_fala_com_as_duas_unidades_em_ingles(self) -> None:
        self._com("fc")
        f = briefing.build_spoken_fallback(self.DADOS_C, self.PREV_C, [], "en")
        self.assertIn("It is 77 degrees Fahrenheit, 25 Celsius right now, rain", f)
        self.assertIn("high of 84 and low of 72 degrees Fahrenheit, or 29 and 22 Celsius", f)

    def test_cartoes_mostram_as_duas(self) -> None:
        self._com("FC")
        c = briefing.build_cards(self.DADOS_C, self.PREV_C, [], "pt")[0]
        self.assertEqual(c["linhas"][0], "77°F / 25°C · chuva")
        self.assertIn("Máxima 84°F / 29°C · mínima 72°F / 22°C", c["linhas"])

    def test_fonte_em_fahrenheit_tambem_vira_as_duas(self) -> None:
        self._com("FC")
        dados = {"clima": {"condicao": "sunny", "temperatura": 77.0, "unidade": "°F"}}
        c = briefing.build_cards(dados, None, [], "pt")[0]
        self.assertEqual(c["linhas"][0], "77°F / 25°C · céu limpo e sol")

    def test_ia_recebe_as_duas_unidades(self) -> None:
        self._com("FC")
        cliente, pedidos = centro_falso({"text": "Bom dia.", "picks": []})
        briefing.compose(self.DADOS_C, self.PREV_C, [], "pt", client=cliente)
        self.assertEqual(pedidos[0]["facts"]["weather"], {"temp": "77", "unit": "F", "temp2": "25", "unit2": "C", "condition": "chuva",
                                                           "high": "84", "low": "72", "rain": "60", "say_unit": True,
                                                           "high2": "29", "low2": "22"})

    def test_modo_f_continua_so_fahrenheit(self) -> None:
        self._com("F")
        c = briefing.build_cards(self.DADOS_C, self.PREV_C, [], "pt")[0]
        self.assertEqual(c["linhas"][0], "77°F · chuva")


class IaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dados = briefing.collect_house(ESTADOS)

    def test_usa_o_texto_da_ia_e_manda_so_os_dados_do_contrato(self) -> None:
        cliente, pedidos = centro_falso({"text": "Bom dia, tudo certo por aqui.", "picks": [{"source": "Orlando", "indices": [0]}]})
        fala = briefing.compose_spoken(self.dados, PREVISAO, [("Orlando", ["Furacao"])], "pt", client=cliente)
        self.assertEqual(fala, "Bom dia, tudo certo por aqui.")
        pedido = pedidos[0]
        self.assertEqual(set(pedido), {"language", "max_words", "rules", "house_state", "facts", "candidates"})
        self.assertEqual((pedido["language"], pedido["max_words"], pedido["house_state"]), ("pt", 110, True))
        self.assertEqual(pedido["facts"], {
            "names": ["Victtor", "Matheus"],  # nomes exatos, como no HA
            "weather": {"temp": "78", "unit": "F", "temp2": None, "unit2": None, "condition": "chuva",
                        "high": "84", "low": "71", "rain": "62", "say_unit": True},
            "open": ["Portão da garagem"],
            "alarm": "desarmado",
        })
        self.assertEqual(pedido["candidates"], [{"source": "Orlando", "limit": 2, "titles": ["Furacao"]}])

    def test_sem_o_estado_da_casa_nao_vai_aberto_nem_alarme(self) -> None:
        cliente, pedidos = centro_falso({"text": "Bom dia.", "picks": []})
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_CASA": "nao", "IQ_BRIEFING_CLIMA": "sim"}):
            briefing.compose(self.dados, PREVISAO, [], "pt", client=cliente)
        self.assertEqual((pedidos[0]["house_state"], pedidos[0]["facts"]["open"], pedidos[0]["facts"]["alarm"]), (False, [], None))
        self.assertEqual(pedidos[0]["facts"]["names"], ["Victtor", "Matheus"])

    def test_alarme_armado_ou_disparado_vai_no_idioma(self) -> None:
        cliente, pedidos = centro_falso({"text": "Good morning.", "picks": []})
        for estado, esperado in (("armed_away", "armed"), ("triggered", "triggered"), (None, None)):
            briefing.compose(dict(self.dados, alarme=estado), None, [], "en", client=cliente)
            self.assertEqual(pedidos[-1]["facts"]["alarm"], esperado)

    def test_ingles_pede_ingles(self) -> None:
        cliente, pedidos = centro_falso({"text": "Good morning.", "picks": []})
        briefing.compose_spoken(self.dados, PREVISAO, [], "en", client=cliente)
        self.assertEqual((pedidos[0]["language"], pedidos[0]["max_words"], pedidos[0]["facts"]["weather"]["condition"]), ("en", 105, "rain"))

    def test_ia_com_erro_cai_no_texto_por_regra_e_o_log_nao_tem_dados(self) -> None:
        erro = RuntimeError("Victtor Furacao")
        erro.reason = "rate"
        cliente, _ = centro_falso(erro)
        with self.assertLogs("iq_edge.briefing", level="WARNING") as logs:
            fala = briefing.compose_spoken(self.dados, PREVISAO, [("Orlando", ["Furacao"])], "pt", client=cliente)
        self.assertTrue(fala.startswith("Bom dia, Victtor e Matheus."))
        self.assertEqual(len(logs.output), 1)
        self.assertIn("(rate)", logs.output[0])
        self.assertNotIn("Victtor", logs.output[0])
        self.assertNotIn("Furacao", logs.output[0])

    def test_resposta_vazia_ou_estranha_cai_no_texto_por_regra(self) -> None:
        for resposta in ({"text": "   "}, {"picks": []}, ["lista"], None, {"text": None}):
            cliente, _ = centro_falso(resposta)
            fala = briefing.compose_spoken(self.dados, PREVISAO, [], "pt", client=cliente)
            self.assertTrue(fala.startswith("Bom dia"), resposta)
            self.assertIn("Portão da garagem", fala)

    def test_fala_longa_demais_e_cortada(self) -> None:
        cliente, _ = centro_falso({"text": "palavra " * 2000, "picks": []})
        self.assertLessEqual(len(briefing.compose_spoken(self.dados, PREVISAO, [], "pt", client=cliente)), 4000)

    def test_o_centro_registrado_so_vale_com_a_casa_pareada(self) -> None:
        cliente, pedidos = centro_falso({"text": "Bom dia do centro.", "picks": []})
        pareado = [False]
        cliente.paired = lambda: pareado[0]
        briefing.usar_centro(cliente)
        self.addCleanup(briefing.usar_centro, None)
        self.assertTrue(briefing.compose_spoken(self.dados, PREVISAO, [], "pt").startswith("Bom dia, Victtor"))
        self.assertEqual(pedidos, [])
        pareado[0] = True
        self.assertEqual(briefing.compose_spoken(self.dados, PREVISAO, [], "pt"), "Bom dia do centro.")

    def test_sem_chave_da_ia_cai_no_texto_por_regra(self) -> None:
        with mock.patch("iq_edge.briefing._ai_client", return_value=None):
            fala = briefing.compose_spoken(self.dados, PREVISAO, [], "pt")
        self.assertTrue(fala.startswith("Bom dia, Victtor e Matheus."))


class HandleTest(unittest.TestCase):
    def _handle(self, texto, *, estados=ESTADOS, feeds=None, feed_fn=None, previsao=PREVISAO):
        publicados = []
        fala = briefing.handle(
            texto,
            fetch_states_fn=lambda: estados,
            fetch_forecast_fn=lambda entidade: previsao,
            fetch_feed_fn=feed_fn or (lambda url, n: ["Manchete de " + url]),
            publish_fn=lambda cartoes, dur: publicados.append((cartoes, dur)) or True,
            client=None,
            feeds=feeds if feeds is not None else [("Orlando", "https://o"), ("Brasil", "https://b")],
        )
        return fala, publicados

    def setUp(self) -> None:
        # sem IA: o texto por regra e deterministico
        patcher = mock.patch("iq_edge.briefing._ai_client", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_pedido_comum_nao_e_resumo(self) -> None:
        fala, publicados = self._handle("acende a luz da sala")
        self.assertIsNone(fala)
        self.assertEqual(publicados, [])

    def test_bom_dia_fala_e_publica_os_cartoes(self) -> None:
        fala, publicados = self._handle("bom dia")
        self.assertTrue(fala.startswith("Bom dia, Victtor e Matheus."))
        self.assertIn("Em Orlando: Manchete de https://o.", fala)
        self.assertEqual(len(publicados), 1)
        cartoes, duracao = publicados[0]
        self.assertEqual([c["titulo"] for c in cartoes], ["Clima", "Casa", "Orlando", "Brasil"])
        self.assertEqual(duracao, 40)

    def test_good_morning_responde_em_ingles(self) -> None:
        fala, publicados = self._handle("good morning")
        self.assertTrue(fala.startswith("Good morning, Victtor and Matheus."))
        self.assertEqual(publicados[0][0][0]["titulo"], "Weather")

    def test_ha_fora_do_ar_responde_com_honestidade(self) -> None:
        fala, publicados = self._handle("bom dia", estados=[])
        self.assertIn("Não consegui falar com a casa", fala)
        self.assertEqual(publicados, [])

    def test_feed_que_falha_nao_derruba_o_resumo(self) -> None:
        def feed(url, n):
            if url == "https://o":
                raise RuntimeError("fora do ar")
            return ["So o Brasil respondeu"]

        fala, publicados = self._handle("bom dia", feed_fn=feed)
        self.assertIn("So o Brasil respondeu", fala)
        self.assertNotIn("Em Orlando", fala)
        self.assertEqual([c["titulo"] for c in publicados[0][0]], ["Clima", "Casa", "Brasil"])

    def test_sem_feeds_configurados(self) -> None:
        fala, publicados = self._handle("bom dia", feeds=[])
        self.assertTrue(fala.startswith("Bom dia"))
        self.assertEqual([c["titulo"] for c in publicados[0][0]], ["Clima", "Casa"])

    def test_sem_previsao_o_resumo_sai_assim_mesmo(self) -> None:
        fala, _ = self._handle("bom dia", previsao=None)
        self.assertIn("Agora faz 78 graus Fahrenheit, chuva", fala)
        self.assertNotIn("máxima", fala)


class AltoFalanteTest(unittest.TestCase):
    """Voz premium no Sonos: o aparelho de voz so diz "Um instante." e o
    resumo inteiro toca no alto-falante, com reserva se falhar."""

    ENV = {
        "IQ_BRIEFING_SPEAKER": "media_player.living",
        "IQ_BRIEFING_TTS_ENGINE": "tts.elevenlabs_text_to_speech",
        "IQ_BRIEFING_TTS_VOICE": "voz-pt-brian",
        "IQ_BRIEFING_TTS_VOICE_EN": "",
        "IQ_BRIEFING_SPEAKER_DELAY": "2",
        "IQ_BRIEFING_SATELLITE": "assist_satellite.sala",
    }
    ESTADOS_COM_VOZ = ESTADOS + [
        {"entity_id": "media_player.living", "state": "idle", "attributes": {}},
        {"entity_id": "tts.elevenlabs_text_to_speech", "state": "unknown", "attributes": {}},
    ]

    def setUp(self) -> None:
        patcher = mock.patch("iq_edge.briefing._ai_client", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, self.ENV)
        env.start()
        self.addCleanup(env.stop)
        self.tocou, self.anunciou, self.esperou = [], [], []

    def _handle(self, texto="bom dia", estados=None, speak_ok=True, speak_erro=False):
        def speak(fala, idioma, cfg):
            if speak_erro:
                raise RuntimeError("elevenlabs fora do ar")
            self.tocou.append((fala, idioma, cfg["voz_pt"], cfg["voz_en"]))
            return speak_ok

        return briefing.handle(
            texto,
            fetch_states_fn=lambda: estados if estados is not None else self.ESTADOS_COM_VOZ,
            fetch_forecast_fn=lambda e: PREVISAO,
            fetch_feed_fn=lambda url, n: ["Manchete"],
            publish_fn=lambda c, d: True,
            client=None,
            feeds=[("Orlando", "https://o")],
            speak_fn=speak,
            announce_fn=lambda fala, sat: self.anunciou.append((fala, sat)) or True,
            spawn_fn=lambda f: f(),
            sleep_fn=lambda s: self.esperou.append(s),
        )

    def test_aparelho_de_voz_so_diz_um_instante(self) -> None:
        resposta = self._handle()
        self.assertEqual(resposta, "Um instante.")
        self.assertEqual(len(self.tocou), 1)
        fala, idioma, voz_pt, voz_en = self.tocou[0]
        self.assertTrue(fala.startswith("Bom dia, Victtor e Matheus."))
        self.assertEqual(idioma, "pt")
        self.assertEqual(self.anunciou, [])

    def test_espera_o_um_instante_terminar(self) -> None:
        self._handle()
        self.assertEqual(self.esperou, [2.0])

    def test_ingles_usa_a_voz_pt_quando_nao_ha_voz_en(self) -> None:
        resposta = self._handle("good morning")
        self.assertEqual(resposta, "One moment.")
        self.assertEqual(self.tocou[0][1], "en")
        self.assertEqual(self.tocou[0][3], "voz-pt-brian")

    def test_voz_en_propria(self) -> None:
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_TTS_VOICE_EN": "voz-en-daniel"}):
            self._handle("good morning")
        self.assertEqual(self.tocou[0][3], "voz-en-daniel")

    def test_alto_falante_indisponivel_fala_no_aparelho_de_voz(self) -> None:
        estados = [dict(e) for e in self.ESTADOS_COM_VOZ]
        for e in estados:
            if e["entity_id"] == "media_player.living":
                e["state"] = "unavailable"
        resposta = self._handle(estados=estados)
        self.assertTrue(resposta.startswith("Bom dia, Victtor e Matheus."))
        self.assertEqual(self.tocou, [])

    def test_motor_de_voz_ausente_fala_no_aparelho_de_voz(self) -> None:
        resposta = self._handle(estados=ESTADOS)
        self.assertTrue(resposta.startswith("Bom dia"))
        self.assertEqual(self.tocou, [])

    def test_falha_ao_tocar_cai_na_reserva_do_satelite(self) -> None:
        resposta = self._handle(speak_ok=False)
        self.assertEqual(resposta, "Um instante.")
        self.assertEqual(len(self.anunciou), 1)
        self.assertEqual(self.anunciou[0][1], "assist_satellite.sala")
        self.assertTrue(self.anunciou[0][0].startswith("Bom dia"))

    def test_erro_ao_tocar_tambem_cai_na_reserva(self) -> None:
        self._handle(speak_erro=True)
        self.assertEqual(len(self.anunciou), 1)

    def test_sem_reserva_configurada_so_registra_a_falha(self) -> None:
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_SATELLITE": ""}):
            resposta = self._handle(speak_ok=False)
        self.assertEqual(resposta, "Um instante.")
        self.assertEqual(self.anunciou, [])

    def test_sem_configuracao_o_comportamento_antigo_continua(self) -> None:
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_SPEAKER": "", "IQ_BRIEFING_TTS_ENGINE": ""}):
            resposta = self._handle()
        self.assertTrue(resposta.startswith("Bom dia, Victtor e Matheus."))
        self.assertEqual(self.tocou, [])

    def test_so_metade_da_configuracao_nao_ativa(self) -> None:
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_TTS_ENGINE": ""}):
            self.assertIsNone(briefing.speaker_config())

    def test_atraso_invalido_vira_dois_segundos(self) -> None:
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_SPEAKER_DELAY": "abc"}):
            self.assertEqual(briefing.speaker_config()["atraso"], 2.0)


class VolumeDoResumoTest(unittest.TestCase):
    """65% so durante o resumo, e volta ao volume anterior."""

    ENV = {
        "IQ_BRIEFING_SPEAKER": "media_player.living",
        "IQ_BRIEFING_TTS_ENGINE": "tts.elevenlabs_text_to_speech",
        "IQ_BRIEFING_TTS_VOICE": "voz-brian",
        "IQ_BRIEFING_TTS_VOICE_EN": "",
        "IQ_BRIEFING_SPEAKER_DELAY": "2",
        "IQ_BRIEFING_SPEAKER_VOLUME": "65",
        "IQ_BRIEFING_SATELLITE": "assist_satellite.sala",
    }
    ESTADOS_COM_VOZ = ESTADOS + [
        {"entity_id": "media_player.living", "state": "idle", "attributes": {"volume_level": 0.72}},
        {"entity_id": "tts.elevenlabs_text_to_speech", "state": "unknown", "attributes": {}},
    ]

    def setUp(self) -> None:
        patcher = mock.patch("iq_edge.briefing._ai_client", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, self.ENV)
        env.start()
        self.addCleanup(env.stop)
        self.eventos = []

    def _handle(self, volumes, speak_ok=True):
        leituras = list(volumes)

        def get_volume(entidade):
            self.eventos.append(("le", entidade))
            return leituras.pop(0) if leituras else None

        def speak(fala, idioma, cfg):
            self.eventos.append(("fala", idioma))
            return speak_ok

        return briefing.handle(
            "bom dia",
            fetch_states_fn=lambda: self.ESTADOS_COM_VOZ,
            fetch_forecast_fn=lambda e: PREVISAO,
            fetch_feed_fn=lambda url, n: ["Manchete"],
            publish_fn=lambda c, d: True,
            client=None,
            feeds=[("Orlando", "https://o")],
            speak_fn=speak,
            announce_fn=lambda fala, sat: self.eventos.append(("reserva", sat)) or True,
            spawn_fn=lambda f: f(),
            sleep_fn=lambda s: None,
            get_volume_fn=get_volume,
            set_volume_fn=lambda entidade, nivel: self.eventos.append(("volume", nivel)) or True,
            wait_fn=lambda entidade, minimo: self.eventos.append(("espera", entidade, minimo)),
        )

    def _volumes(self):
        return [e[1] for e in self.eventos if e[0] == "volume"]

    def test_fala_a_65_e_volta_ao_anterior(self) -> None:
        # le 72% antes; depois da fala le 65% (ninguem mexeu)
        self.assertEqual(self._handle([0.72, 0.65]), "Um instante.")
        self.assertEqual(self._volumes(), [0.65, 0.72])
        ordem = [e[0] for e in self.eventos]
        self.assertEqual(ordem, ["le", "volume", "fala", "espera", "le", "volume"])

    def test_se_alguem_mexeu_no_volume_durante_a_fala_nao_restaura(self) -> None:
        self._handle([0.72, 0.40])
        self.assertEqual(self._volumes(), [0.65])

    def test_volume_ja_no_alvo_nao_mexe_em_nada(self) -> None:
        self._handle([0.65])
        self.assertEqual(self._volumes(), [])

    def test_volume_anterior_ilegivel_nao_mexe_em_nada(self) -> None:
        self._handle([])
        self.assertEqual(self._volumes(), [])
        self.assertIn(("fala", "pt"), self.eventos)

    def test_falha_ao_tocar_restaura_sem_esperar_e_cai_na_reserva(self) -> None:
        self._handle([0.72, 0.65], speak_ok=False)
        self.assertEqual(self._volumes(), [0.65, 0.72])
        self.assertNotIn("espera", [e[0] for e in self.eventos])
        self.assertIn(("reserva", "assist_satellite.sala"), self.eventos)

    def test_sem_configuracao_de_volume_o_volume_nao_e_tocado(self) -> None:
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_SPEAKER_VOLUME": ""}):
            self._handle([0.72])
        self.assertEqual(self._volumes(), [])
        self.assertNotIn("le", [e[0] for e in self.eventos])

    def test_formatos_do_volume(self) -> None:
        for bruto, esperado in (("65", 0.65), ("0.65", 0.65), ("0,65", 0.65), ("100", 1.0), ("0", None), ("abc", None), ("-5", None)):
            with mock.patch.dict(os.environ, {"IQ_BRIEFING_SPEAKER_VOLUME": bruto}):
                self.assertEqual(briefing.speaker_config()["volume"], esperado, bruto)


class PedidoAutomaticoTest(unittest.TestCase):
    """Automacao do HA ("bom dia automatico") e queda curta do Sonos."""

    ENV = {
        "IQ_BRIEFING_SPEAKER": "media_player.living",
        "IQ_BRIEFING_TTS_ENGINE": "tts.elevenlabs_text_to_speech",
        "IQ_BRIEFING_TTS_VOICE": "voz-brian",
        "IQ_BRIEFING_TTS_VOICE_EN": "",
        "IQ_BRIEFING_SPEAKER_DELAY": "2",
        "IQ_BRIEFING_SPEAKER_WAIT": "8",
        "IQ_BRIEFING_SPEAKER_VOLUME": "",
        "IQ_BRIEFING_SATELLITE": "assist_satellite.sala",
    }
    EXTRAS_OK = [
        {"entity_id": "media_player.living", "state": "idle", "attributes": {}},
        {"entity_id": "tts.elevenlabs_text_to_speech", "state": "unknown", "attributes": {}},
    ]
    EXTRAS_FORA = [
        {"entity_id": "media_player.living", "state": "unavailable", "attributes": {}},
        {"entity_id": "tts.elevenlabs_text_to_speech", "state": "unknown", "attributes": {}},
    ]

    def setUp(self) -> None:
        patcher = mock.patch("iq_edge.briefing._ai_client", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, self.ENV)
        env.start()
        self.addCleanup(env.stop)
        self.tocou, self.anunciou, self.esperou = [], [], []

    def _handle(self, texto, leituras):
        """`leituras`: lista de listas de estados devolvidas a cada leitura."""
        fila = list(leituras)

        def estados():
            return fila.pop(0) if len(fila) > 1 else fila[0]

        def speak(fala, idioma, cfg):
            self.tocou.append((fala, idioma, cfg["atraso"]))
            return True

        return briefing.handle(
            texto,
            fetch_states_fn=estados,
            fetch_forecast_fn=lambda e: PREVISAO,
            fetch_feed_fn=lambda url, n: ["Manchete"],
            publish_fn=lambda c, d: True,
            client=None,
            feeds=[("Orlando", "https://o")],
            speak_fn=speak,
            announce_fn=lambda fala, sat: self.anunciou.append((fala, sat)) or True,
            spawn_fn=lambda f: f(),
            sleep_fn=lambda s: self.esperou.append(s),
        )

    def test_texto_automatico_e_reconhecido(self) -> None:
        self.assertEqual(briefing.detect_briefing("bom dia automatico"), "pt")
        self.assertEqual(briefing.detect_briefing("Bom dia automático"), "pt")

    def test_automatico_fala_no_sonos_sem_esperar_o_um_instante(self) -> None:
        resposta = self._handle("bom dia automatico", [ESTADOS + self.EXTRAS_OK])
        self.assertEqual(resposta, "Um instante.")
        self.assertEqual(len(self.tocou), 1)
        self.assertEqual(self.tocou[0][2], 0.0)  # atraso zero
        self.assertEqual(self.anunciou, [])

    def test_pedido_de_voz_continua_esperando_o_um_instante(self) -> None:
        self._handle("bom dia", [ESTADOS + self.EXTRAS_OK])
        self.assertEqual(self.tocou[0][2], 2.0)

    def test_queda_curta_do_sonos_e_tolerada(self) -> None:
        # 1a leitura: Sonos indisponivel; na 2a (2 s depois) ja voltou
        resposta = self._handle(
            "bom dia automatico",
            [ESTADOS + self.EXTRAS_FORA, ESTADOS + self.EXTRAS_FORA, ESTADOS + self.EXTRAS_OK],
        )
        self.assertEqual(resposta, "Um instante.")
        self.assertEqual(len(self.tocou), 1)
        self.assertEqual(self.anunciou, [])
        self.assertIn(2.0, self.esperou)

    def test_automatico_com_sonos_fora_fala_no_satelite(self) -> None:
        resposta = self._handle("bom dia automatico", [ESTADOS + self.EXTRAS_FORA])
        self.assertEqual(resposta, "Um instante.")
        self.assertEqual(self.tocou, [])
        self.assertEqual(len(self.anunciou), 1)
        fala, satelite = self.anunciou[0]
        self.assertEqual(satelite, "assist_satellite.sala")
        self.assertTrue(fala.startswith("Bom dia, Victtor e Matheus."))
        self.assertEqual(sum(1 for e in self.esperou if e == 2.0), 4)  # esperou os 8 s antes de desistir

    def test_voz_com_sonos_fora_devolve_o_texto_para_o_aparelho_de_voz(self) -> None:
        resposta = self._handle("bom dia", [ESTADOS + self.EXTRAS_FORA])
        self.assertTrue(resposta.startswith("Bom dia, Victtor e Matheus."))
        self.assertEqual(self.anunciou, [])
        self.assertEqual(self.tocou, [])

    def test_automatico_sem_alto_falante_configurado_usa_o_satelite_do_ambiente(self) -> None:
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_SPEAKER": "", "IQ_BRIEFING_TTS_ENGINE": ""}):
            resposta = self._handle("bom dia automatico", [ESTADOS])
        self.assertEqual(resposta, "Um instante.")
        self.assertEqual(len(self.anunciou), 1)
        self.assertEqual(self.anunciou[0][1], "assist_satellite.sala")

    def test_automatico_sem_nenhum_destino_nao_quebra(self) -> None:
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_SPEAKER": "", "IQ_BRIEFING_TTS_ENGINE": "", "IQ_BRIEFING_SATELLITE": ""}):
            resposta = self._handle("bom dia automatico", [ESTADOS])
        self.assertEqual(resposta, "Um instante.")
        self.assertEqual(self.anunciou, [])

    def test_espera_configuravel(self) -> None:
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_SPEAKER_WAIT": "0"}):
            self._handle("bom dia automatico", [ESTADOS + self.EXTRAS_FORA])
        self.assertNotIn(2.0, self.esperou)
        self.assertEqual(len(self.anunciou), 1)
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_SPEAKER_WAIT": "abc"}):
            self.assertEqual(briefing.speaker_config()["espera"], 8.0)


class EsperaDoFimDaFalaTest(unittest.TestCase):
    """Bug de 2026-10-08: o volume voltou 16 s depois, no meio da fala, porque o
    anuncio do Sonos nao aparece como "tocando"."""

    def test_estimativa_cresce_com_o_texto(self) -> None:
        self.assertEqual(briefing._estimar_duracao("x" * 120), 14.0)
        self.assertEqual(briefing._estimar_duracao("curto"), 10.0)  # minimo de 6 s + margem
        self.assertGreater(briefing._estimar_duracao("x" * 600), briefing._estimar_duracao("x" * 300))

    def test_uma_fala_de_resumo_pede_bem_mais_que_os_15_s_do_bug(self) -> None:
        fala = ("Bom dia, Victtor, Matheus e Bárbara! Hoje está nublado com chuva, 74 graus Fahrenheit, "
                "23 graus Celsius, máxima de 77 graus Fahrenheit, 25 graus Celsius. Um alerta importante: "
                "o furacão Isaías está se intensificando no Golfo, e o governador da Flórida decretou "
                "estado de emergência para 25 condados. Tenham um excelente dia.")
        self.assertGreater(briefing._estimar_duracao(fala), 25.0)

    def test_o_volume_so_volta_depois_da_espera(self) -> None:
        eventos = []
        leituras = [0.28, 0.65]
        briefing._entregar_no_alto_falante(
            "x" * 240,
            "pt",
            {"speaker": "media_player.living", "engine": "e", "voz_pt": "v", "voz_en": "v", "atraso": 0.0, "volume": 0.65, "satellite": ""},
            speak_fn=lambda f, i, c: eventos.append("fala") or True,
            announce_fn=lambda f, s: True,
            sleep_fn=lambda s: None,
            get_volume_fn=lambda e: leituras.pop(0),
            set_volume_fn=lambda e, n: eventos.append(("volume", n)) or True,
            wait_fn=lambda e, minimo: eventos.append(("espera", minimo)),
        )
        self.assertEqual(eventos, [("volume", 0.65), "fala", ("espera", 24.0), ("volume", 0.28)])


class AberturasIgnoradasTest(unittest.TestCase):
    """A porta do quarto dispara o bom dia: dizer "porta do quarto aberta" todo dia e ruido."""

    def test_entidade_ignorada_nao_conta_como_aberta(self) -> None:
        estados = ESTADOS + [
            {"entity_id": "binary_sensor.master_bedroom_door_contact", "state": "on",
             "attributes": {"device_class": "door", "friendly_name": "Master Bedroom Door"}},
        ]
        sem = briefing.collect_house(estados)
        self.assertIn("Master Bedroom Door", sem["abertos"])
        com = briefing.collect_house(estados, None, {"binary_sensor.master_bedroom_door_contact"})
        self.assertNotIn("Master Bedroom Door", com["abertos"])
        self.assertIn("Portão da garagem", com["abertos"])  # o resto continua

    def test_ignorar_pelo_nome_tambem_vale(self) -> None:
        estados = [
            {"entity_id": "binary_sensor.porta_x", "state": "on",
             "attributes": {"device_class": "door", "friendly_name": "Porta do Quarto"}},
        ]
        self.assertEqual(briefing.collect_house(estados, None, {"porta do quarto"})["abertos"], [])

    def test_handle_le_a_lista_do_ambiente(self) -> None:
        estados = ESTADOS + [
            {"entity_id": "binary_sensor.master_bedroom_door_contact", "state": "on",
             "attributes": {"device_class": "door", "friendly_name": "Master Bedroom Door"}},
        ]
        capturado = []
        with mock.patch("iq_edge.briefing._ai_client", return_value=None), \
                mock.patch.dict(os.environ, {"IQ_BRIEFING_IGNORAR": "binary_sensor.master_bedroom_door_contact, Outra Coisa"}):
            fala = briefing.handle(
                "bom dia",
                fetch_states_fn=lambda: estados,
                fetch_forecast_fn=lambda e: PREVISAO,
                fetch_feed_fn=lambda url, n: [],
                publish_fn=lambda c, d: capturado.append(c) or True,
                feeds=[],
            )
        self.assertNotIn("Master Bedroom", fala)
        casa = [c for c in capturado[0] if c["titulo"] == "Casa"][0]
        self.assertNotIn("Master Bedroom Door", casa["linhas"])


class SonosTocandoTest(unittest.TestCase):
    """Alguem vendo TV pela barra: o resumo nao interrompe, fala pelo Voice."""

    ENV = {
        "IQ_BRIEFING_SPEAKER": "media_player.living",
        "IQ_BRIEFING_TTS_ENGINE": "tts.elevenlabs_text_to_speech",
        "IQ_BRIEFING_TTS_VOICE": "voz-brian",
        "IQ_BRIEFING_TTS_VOICE_EN": "",
        "IQ_BRIEFING_SPEAKER_DELAY": "2",
        "IQ_BRIEFING_SPEAKER_WAIT": "8",
        "IQ_BRIEFING_SPEAKER_VOLUME": "65",
        "IQ_BRIEFING_SPEAKER_BUSY": "",
        "IQ_BRIEFING_SATELLITE": "assist_satellite.sala",
    }

    @staticmethod
    def _sonos(estado):
        return ESTADOS + [
            {"entity_id": "media_player.living", "state": estado, "attributes": {"volume_level": 0.3, "source": "TV"}},
            {"entity_id": "tts.elevenlabs_text_to_speech", "state": "unknown", "attributes": {}},
        ]

    def setUp(self) -> None:
        patcher = mock.patch("iq_edge.briefing._ai_client", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, self.ENV)
        env.start()
        self.addCleanup(env.stop)
        self.tocou, self.anunciou, self.volumes = [], [], []

    def _handle(self, texto, leituras):
        fila = list(leituras)

        def estados():
            return fila.pop(0) if len(fila) > 1 else fila[0]

        return briefing.handle(
            texto,
            fetch_states_fn=estados,
            fetch_forecast_fn=lambda e: PREVISAO,
            fetch_feed_fn=lambda url, n: ["Manchete"],
            publish_fn=lambda c, d: True,
            client=None,
            feeds=[("Orlando", "https://o")],
            speak_fn=lambda fala, idioma, cfg: self.tocou.append(fala) or True,
            announce_fn=lambda fala, sat: self.anunciou.append((fala, sat)) or True,
            spawn_fn=lambda f: f(),
            sleep_fn=lambda s: None,
            get_volume_fn=lambda e: 0.3,
            set_volume_fn=lambda e, n: self.volumes.append(n) or True,
            wait_fn=lambda e, m: None,
        )

    def test_tv_tocando_e_pedido_automatico_fala_pelo_voice(self) -> None:
        resposta = self._handle("bom dia automatico", [self._sonos("playing")])
        self.assertEqual(resposta, "Um instante.")
        self.assertEqual(self.tocou, [])
        self.assertEqual(self.volumes, [])  # nao mexe no volume da barra
        self.assertEqual(len(self.anunciou), 1)
        self.assertEqual(self.anunciou[0][1], "assist_satellite.sala")
        self.assertTrue(self.anunciou[0][0].startswith("Bom dia, Victtor e Matheus."))

    def test_tv_tocando_e_pedido_de_voz_devolve_o_texto_ao_aparelho_de_voz(self) -> None:
        resposta = self._handle("bom dia", [self._sonos("playing")])
        self.assertTrue(resposta.startswith("Bom dia, Victtor e Matheus."))
        self.assertEqual(self.tocou, [])
        self.assertEqual(self.anunciou, [])

    def test_buffering_tambem_conta_como_tocando(self) -> None:
        self._handle("bom dia automatico", [self._sonos("buffering")])
        self.assertEqual(self.tocou, [])
        self.assertEqual(len(self.anunciou), 1)

    def test_parado_ou_pausado_nao_e_tocando(self) -> None:
        for estado in ("idle", "paused"):
            self.tocou.clear()
            self.anunciou.clear()
            self._handle("bom dia automatico", [self._sonos(estado)])
            self.assertEqual(len(self.tocou), 1, estado)
            self.assertEqual(self.anunciou, [], estado)

    def test_estado_lido_na_hora_de_falar_vale_mais_que_o_do_comeco(self) -> None:
        # comecou ocioso; quando o resumo ficou pronto, a TV ja tinha ligado
        self._handle("bom dia automatico", [self._sonos("idle"), self._sonos("playing")])
        self.assertEqual(self.tocou, [])
        self.assertEqual(len(self.anunciou), 1)
        # e o contrario: comecou tocando, parou antes de falar
        self.tocou.clear()
        self.anunciou.clear()
        self._handle("bom dia automatico", [self._sonos("playing"), self._sonos("idle")])
        self.assertEqual(len(self.tocou), 1)
        self.assertEqual(self.anunciou, [])

    def test_modo_interromper_fala_por_cima(self) -> None:
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_SPEAKER_BUSY": "interromper"}):
            self._handle("bom dia automatico", [self._sonos("playing")])
        self.assertEqual(len(self.tocou), 1)
        self.assertEqual(self.anunciou, [])
        self.assertEqual(self.volumes, [0.65])
        self.assertEqual(briefing.speaker_config()["ocupado"], "voice")  # padrao apos o patch


class UnidadePeloIdiomaTest(unittest.TestCase):
    """IQ_BRIEFING_TEMP_UNIT=IDIOMA: Celsius em portugues, Fahrenheit em ingles."""

    # a previsao do HA da casa vem em Celsius; os sensores em Fahrenheit
    DADOS_C = {"clima": {"condicao": "rainy", "temperatura": 25.0, "unidade": "°C"}}
    PREV_C = {"temperature": 29, "templow": 22, "precipitation_probability": 60}
    DADOS_F = {"clima": {"condicao": "rainy", "temperatura": 77.0, "unidade": "°F"}}
    PREV_F = {"temperature": 84, "templow": 72, "precipitation_probability": 60}

    def setUp(self) -> None:
        env = mock.patch.dict(os.environ, {"IQ_BRIEFING_TEMP_UNIT": "IDIOMA"})
        env.start()
        self.addCleanup(env.stop)

    def test_portugues_so_em_celsius_na_fala_e_nos_cartoes(self) -> None:
        for dados, prev in ((self.DADOS_C, self.PREV_C), (self.DADOS_F, self.PREV_F)):
            f = briefing.build_spoken_fallback(dados, prev, [], "pt")
            self.assertIn("Agora faz 25 graus, chuva", f)
            self.assertIn("máxima de 29 e mínima de 22 graus", f)
            self.assertNotIn("Fahrenheit", f)
            self.assertNotIn("Celsius", f)  # a unidade e implicita no idioma: nao gasta credito de voz
            c = briefing.build_cards(dados, prev, [], "pt")[0]
            self.assertEqual(c["linhas"][0], "25°C · chuva")
            self.assertIn("Máxima 29°C · mínima 22°C", c["linhas"])

    def test_ingles_so_em_fahrenheit_na_fala_e_nos_cartoes(self) -> None:
        for dados, prev in ((self.DADOS_C, self.PREV_C), (self.DADOS_F, self.PREV_F)):
            f = briefing.build_spoken_fallback(dados, prev, [], "en")
            self.assertIn("It is 77 degrees right now, rain", f)
            self.assertIn("high of 84 and low of 72 degrees", f)
            self.assertNotIn("Celsius", f)
            self.assertNotIn("Fahrenheit", f)
            c = briefing.build_cards(dados, prev, [], "en")[0]
            self.assertEqual(c["linhas"][0], "77°F · rain")

    def test_a_ia_recebe_so_a_unidade_do_idioma(self) -> None:
        cliente, pedidos = centro_falso({"text": "Bom dia.", "picks": []})
        briefing.compose(self.DADOS_F, self.PREV_F, [], "pt", client=cliente)
        clima = pedidos[0]["facts"]["weather"]
        self.assertEqual((clima["temp"], clima["unit"], clima["temp2"], clima["unit2"], clima["high"]), ("25", "C", None, None, "29"))
        self.assertIs(clima["say_unit"], False)  # pelo idioma: a fala diz so "graus"
        self.assertNotIn("high2", clima)
        briefing.compose(self.DADOS_C, self.PREV_C, [], "en", client=cliente)
        clima = pedidos[1]["facts"]["weather"]
        self.assertEqual((clima["temp"], clima["unit"], clima["temp2"], clima["unit2"]), ("77", "F", None, None))

    def test_apelidos_do_modo_e_modos_antigos_continuam(self) -> None:
        for valor in ("idioma", "AUTO", "lang"):
            with mock.patch.dict(os.environ, {"IQ_BRIEFING_TEMP_UNIT": valor}):
                self.assertEqual(briefing._modo_unidade("pt"), "C")
                self.assertEqual(briefing._modo_unidade("en"), "F")
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_TEMP_UNIT": "FC"}):
            self.assertEqual(briefing._modo_unidade("pt"), "FC")
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_TEMP_UNIT": "F"}):
            self.assertEqual(briefing._modo_unidade("pt"), "F")
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_TEMP_UNIT": ""}):
            self.assertEqual(briefing._modo_unidade("pt"), "")


class UnidadeFalada(unittest.TestCase):
    """So o modo IDIOMA omite o nome da unidade; nos outros ela continua sendo dita."""

    DADOS = {"clima": {"condicao": "rainy", "temperatura": 25.0, "unidade": "°C"}}

    def test_modos_que_nao_sao_implicitos_continuam_dizendo_a_unidade(self) -> None:
        casos = {"C": "Agora faz 25 graus Celsius", "F": "Agora faz 77 graus Fahrenheit", "FC": "Agora faz 77 graus Fahrenheit, 25 Celsius"}
        for modo, esperado in casos.items():
            with mock.patch.dict(os.environ, {"IQ_BRIEFING_TEMP_UNIT": modo}):
                f = briefing.build_spoken_fallback(self.DADOS, None, [], "pt")
            self.assertIn(esperado, f, modo)

    def test_sem_previsao_maxima_minima_e_chuva_vao_nulas(self) -> None:
        cliente, pedidos = centro_falso({"text": "Bom dia.", "picks": []})
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_TEMP_UNIT": "C"}):
            briefing.compose(self.DADOS, None, [], "pt", client=cliente)
        self.assertEqual(pedidos[0]["facts"]["weather"], {"temp": "25", "unit": "C", "temp2": None, "unit2": None, "condition": "chuva",
                                                          "high": None, "low": None, "rain": None, "say_unit": True})


class SensorDeTemperaturaTest(unittest.TestCase):
    """Temperatura ATUAL do sensor de fora; maxima e minima seguem da previsao."""

    SENSOR = "sensor.temp_sensor_exterior_temperature"
    PREV = {"temperature": 25, "templow": 23, "precipitation_probability": 60}  # Celsius, como o met.no

    @staticmethod
    def _estados(valor="75.2", unidade="°F", sensor_estado=None):
        return [
            {"entity_id": "weather.forecast_home", "state": "rainy",
             "attributes": {"temperature": 23.4, "temperature_unit": "°C", "humidity": 90}},
            {"entity_id": "sensor.temp_sensor_exterior_temperature", "state": valor if sensor_estado is None else sensor_estado,
             "attributes": {"unit_of_measurement": unidade, "friendly_name": "Temperatura lá fora"}},
        ]

    def _dados(self, estados, sensor=SENSOR):
        return briefing.collect_house(estados, None, None, sensor)

    def setUp(self) -> None:
        env = mock.patch.dict(os.environ, {"IQ_BRIEFING_TEMP_UNIT": "IDIOMA"})
        env.start()
        self.addCleanup(env.stop)

    def test_portugues_atual_do_sensor_convertido_e_max_min_da_previsao(self) -> None:
        d = self._dados(self._estados())
        f = briefing.build_spoken_fallback(d, self.PREV, [], "pt")
        self.assertIn("Agora faz 24 graus, chuva; máxima de 25 e mínima de 23 graus", f)  # 75,2 F = 24 C; previsao ja em C
        c = briefing.build_cards(d, self.PREV, [], "pt")[0]
        self.assertEqual(c["linhas"][0], "24°C · chuva")
        self.assertIn("Máxima 25°C · mínima 23°C", c["linhas"])

    def test_ingles_atual_direto_em_f_e_previsao_convertida(self) -> None:
        d = self._dados(self._estados())
        f = briefing.build_spoken_fallback(d, self.PREV, [], "en")
        self.assertIn("It is 75 degrees right now, rain; high of 77 and low of 73 degrees", f)
        c = briefing.build_cards(d, self.PREV, [], "en")[0]
        self.assertEqual(c["linhas"][0], "75°F · rain")

    def test_sensor_em_celsius_tambem_funciona(self) -> None:
        d = self._dados(self._estados("22.0", "°C"))
        f = briefing.build_spoken_fallback(d, self.PREV, [], "pt")
        self.assertIn("Agora faz 22 graus", f)

    def test_sensor_indisponivel_cai_na_temperatura_do_weather(self) -> None:
        for ruim in ("unavailable", "unknown", "abc", ""):
            d = self._dados(self._estados(sensor_estado=ruim))
            f = briefing.build_spoken_fallback(d, self.PREV, [], "pt")
            self.assertIn("Agora faz 23 graus", f, ruim)  # 23,4 C do weather

    def test_sem_sensor_configurado_usa_o_weather(self) -> None:
        d = self._dados(self._estados(), sensor=None)
        self.assertIn("Agora faz 23 graus", briefing.build_spoken_fallback(d, self.PREV, [], "pt"))

    def test_sensor_que_nao_existe_cai_no_weather(self) -> None:
        d = self._dados(self._estados(), sensor="sensor.nao_existe")
        self.assertIn("Agora faz 23 graus", briefing.build_spoken_fallback(d, self.PREV, [], "pt"))

    def test_modo_fc_mistura_as_unidades_de_origem_certas(self) -> None:
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_TEMP_UNIT": "FC"}):
            d = self._dados(self._estados())
            c = briefing.build_cards(d, self.PREV, [], "pt")[0]
        self.assertEqual(c["linhas"][0], "75°F / 24°C · chuva")
        self.assertIn("Máxima 77°F / 25°C · mínima 73°F / 23°C", c["linhas"])

    def test_sem_conversao_a_previsao_acompanha_a_unidade_do_sensor(self) -> None:
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_TEMP_UNIT": ""}):
            d = self._dados(self._estados())
            c = briefing.build_cards(d, self.PREV, [], "pt")[0]
        self.assertEqual(c["linhas"][0], "75°F · chuva")
        self.assertIn("Máxima 77°F · mínima 73°F", c["linhas"])

    def test_handle_le_o_sensor_do_ambiente(self) -> None:
        capturado = []
        with mock.patch("iq_edge.briefing._ai_client", return_value=None), \
                mock.patch.dict(os.environ, {"IQ_BRIEFING_TEMP_SENSOR": self.SENSOR}):
            fala = briefing.handle(
                "bom dia",
                fetch_states_fn=lambda: self._estados(),
                fetch_forecast_fn=lambda e: self.PREV,
                fetch_feed_fn=lambda url, n: [],
                publish_fn=lambda c, d: capturado.append(c) or True,
                feeds=[],
            )
        self.assertIn("Agora faz 24 graus", fala)
        self.assertEqual(capturado[0][0]["linhas"][0], "24°C · chuva")


class CasaDesligadaTest(unittest.TestCase):
    """IQ_BRIEFING_CASA=nao: o resumo e so cumprimento, clima e noticias."""

    NOTICIAS = [("Orlando", ["Hurricane watch for Florida"]), ("Brasil", ["Eleições 2026"])]
    DESLIGADA = {"IQ_BRIEFING_CASA": "nao"}

    def setUp(self) -> None:
        # garagem aberta e alarme desarmado
        self.dados = briefing.collect_house(ESTADOS)
        # casa fechada e alarme disparado: o caso mais "falante" de todos
        estados = [dict(e) for e in ESTADOS if e["entity_id"] != "cover.garage_door"]
        for e in estados:
            if e["entity_id"].startswith("alarm_control_panel"):
                e["state"] = "triggered"
        self.dados_alarme = briefing.collect_house(estados)

    def _sem_opcao(self) -> None:
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("IQ_BRIEFING_CASA", None)

    # (a) texto por regra
    def test_fala_por_regra_sem_estado_da_casa_em_portugues(self) -> None:
        with mock.patch.dict(os.environ, self.DESLIGADA):
            for dados in (self.dados, self.dados_alarme):
                f = briefing.build_spoken_fallback(dados, PREVISAO, self.NOTICIAS, "pt")
                baixo = f.lower()
                for proibido in ("fechada", "aberto", "destravado", "alarme", "portão da garagem"):
                    self.assertNotIn(proibido, baixo)
                self.assertTrue(f.startswith("Bom dia, Victtor e Matheus."))
                self.assertIn("Agora faz 78 graus Fahrenheit, chuva", f)
                self.assertIn("chance de chuva de 62%", f)
                self.assertIn("Em Orlando: Hurricane watch for Florida.", f)

    def test_fala_por_regra_sem_estado_da_casa_em_ingles(self) -> None:
        with mock.patch.dict(os.environ, self.DESLIGADA):
            for dados in (self.dados, self.dados_alarme):
                f = briefing.build_spoken_fallback(dados, PREVISAO, self.NOTICIAS, "en")
                baixo = f.lower()
                for proibido in ("closed", "open", "unlocked", "alarm", "garage"):
                    self.assertNotIn(proibido, baixo)
                self.assertTrue(f.startswith("Good morning, Victtor and Matheus."))
                self.assertIn("62% chance of rain", f)
                self.assertIn("In Brasil:", f)

    def test_varias_formas_de_desligar(self) -> None:
        for valor in ("nao", "não", "NAO", "Não", "0", "off", " OFF "):
            with mock.patch.dict(os.environ, {"IQ_BRIEFING_CASA": valor}):
                self.assertFalse(briefing._casa_ligada(), valor)
                f = briefing.build_spoken_fallback(self.dados, PREVISAO, [], "pt")
                self.assertNotIn("Portão da garagem", f)

    # (b) cartoes
    def test_cartoes_sem_o_cartao_casa(self) -> None:
        with mock.patch.dict(os.environ, self.DESLIGADA):
            for idioma, clima, casa in (("pt", "Clima", "Casa"), ("en", "Weather", "Home")):
                c = briefing.build_cards(self.dados, PREVISAO, self.NOTICIAS, idioma)
                titulos = [x["titulo"] for x in c]
                self.assertEqual(titulos, [clima, "Orlando", "Brasil"])
                self.assertNotIn(casa, titulos)
                self.assertIn("78°F · " + ("chuva" if idioma == "pt" else "rain"), c[0]["linhas"][0])
                self.assertEqual(c[1]["linhas"], ["Hurricane watch for Florida"])
                self.assertEqual(c[2]["linhas"], ["Eleições 2026"])

    def test_cartoes_sem_clima_e_sem_casa_ficam_so_com_noticias(self) -> None:
        with mock.patch.dict(os.environ, self.DESLIGADA):
            c = briefing.build_cards({**self.dados_alarme, "clima": None}, None, self.NOTICIAS, "pt")
        self.assertEqual([x["titulo"] for x in c], ["Orlando", "Brasil"])

    # (c) IA
    def test_pedido_ao_centro_sem_o_estado_da_casa(self) -> None:
        cliente, pedidos = centro_falso({"text": "Bom dia, Victtor e Matheus.", "picks": []})
        with mock.patch.dict(os.environ, self.DESLIGADA):
            fala = briefing.compose_spoken(self.dados, PREVISAO, [("Orlando", ["Furacao"])], "pt", client=cliente)
        self.assertEqual(fala, "Bom dia, Victtor e Matheus.")
        pedido = pedidos[0]
        self.assertFalse(pedido["house_state"])
        self.assertEqual((pedido["facts"]["open"], pedido["facts"]["alarm"]), ([], None))
        self.assertNotIn("Portão da garagem", str(pedido))
        # o cumprimento, o clima e as noticias continuam nos dados
        self.assertEqual(pedido["facts"]["names"], ["Victtor", "Matheus"])
        self.assertEqual((pedido["facts"]["weather"]["temp"], pedido["facts"]["weather"]["unit"]), ("78", "F"))
        self.assertEqual(pedido["candidates"][0]["titles"], ["Furacao"])

    # (d) opcao ausente: tudo como antes
    def test_sem_a_opcao_tudo_como_antes(self) -> None:
        self._sem_opcao()
        self.assertTrue(briefing._casa_ligada())
        fechada = briefing.collect_house([e for e in ESTADOS if e["entity_id"] != "cover.garage_door"])
        self.assertIn("A casa está toda fechada.", briefing.build_spoken_fallback(fechada, None, [], "pt"))
        self.assertIn("The house is all closed up.", briefing.build_spoken_fallback(fechada, None, [], "en"))
        self.assertIn(
            "Aberto ou destravado agora: Portão da garagem.",
            briefing.build_spoken_fallback(self.dados, None, [], "pt"),
        )
        self.assertIn(
            "O alarme está armado.",
            briefing.build_spoken_fallback({**fechada, "alarme": "armed_away"}, None, [], "pt"),
        )
        self.assertIn(
            "Atenção: o alarme disparou.",
            briefing.build_spoken_fallback(self.dados_alarme, None, [], "pt"),
        )
        c = briefing.build_cards(self.dados, PREVISAO, self.NOTICIAS, "pt")
        self.assertEqual([x["titulo"] for x in c], ["Clima", "Casa", "Orlando", "Brasil"])
        self.assertEqual(c[1]["tom"], "alerta")

    def test_sem_a_opcao_o_pedido_ao_centro_leva_a_casa(self) -> None:
        self._sem_opcao()
        cliente, pedidos = centro_falso({"text": "Bom dia.", "picks": []})
        briefing.compose_spoken(self.dados, PREVISAO, [], "pt", client=cliente)
        self.assertTrue(pedidos[0]["house_state"])
        self.assertEqual((pedidos[0]["facts"]["open"], pedidos[0]["facts"]["alarm"]), (["Portão da garagem"], "desarmado"))

    def test_opcao_sim_equivale_a_ausente(self) -> None:
        for valor in ("sim", "SIM", "1", "on", ""):
            with mock.patch.dict(os.environ, {"IQ_BRIEFING_CASA": valor}):
                self.assertTrue(briefing._casa_ligada(), valor)


# --------------------------------------------------------------------------
# Lote H2: preferencias vindas do centro (arquivo) e as rotas do contrato v1
# --------------------------------------------------------------------------

import json
import tempfile
import threading


_PASTA_SEM_PREFS = tempfile.TemporaryDirectory()


def setUpModule() -> None:
    # Os testes acima leem o .env (mock.patch.dict): nenhum arquivo de preferencias de verdade (ex.: o do Orange Pi) pode valer neles.
    os.environ["IQ_BRIEFING_PREFS_FILE"] = os.path.join(_PASTA_SEM_PREFS.name, "nao-existe.json")


def tearDownModule() -> None:
    os.environ.pop("IQ_BRIEFING_PREFS_FILE", None)


PREFS_DO_CENTRO = {
    "house_state": False, "weather": True,
    "sources": [{"name": "EUA", "url": "https://feeds.npr.org/1001/rss.xml"},
                {"name": "EUA", "url": "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml"},
                {"name": "Orlando", "url": "https://www.wesh.com/local-news-rss"},
                {"name": "Brasil", "url": "https://g1.globo.com/rss/g1/"}],
    "picks": {"EUA": 4, "Orlando": 2, "Brasil": 2}, "total_min": 6, "total_max": 7, "max_words": 190,
    "rules": "Escolha por importancia, nao por volume.", "speaker": "media_player.living", "volume": 65,
    "tts_engine": "elevenlabs", "language": "pt", "temp_unit": "language",
}
ENV_VOZ = {"IQ_BRIEFING_SPEAKER": "media_player.cozinha", "IQ_BRIEFING_TTS_ENGINE": "tts.elevenlabs_text_to_speech",
           "IQ_BRIEFING_TTS_VOICE": "voz-brian", "IQ_BRIEFING_SPEAKER_VOLUME": "40", "IQ_BRIEFING_FEEDS": "Antiga=https://exemplo.com/rss",
           "IQ_BRIEFING_CASA": "sim", "IQ_BRIEFING_TEMP_UNIT": "F", "IQ_BRIEFING_PICK": "2", "IQ_BRIEFING_PICK_MAP": "",
           "IQ_BRIEFING_MAX_WORDS": "110", "IQ_BRIEFING_NEWS_RULES": "Regra do env.", "IQ_BRIEFING_TOTAL": "", "IQ_BRIEFING_CLIMA": ""}


def _ler_texto(caminho):
    with open(caminho, encoding="utf-8") as arquivo:
        return arquivo.read()


def _ler_json(caminho):
    return json.loads(_ler_texto(caminho))


def _cliente_falso(texto="Bom dia, Victtor."):
    return centro_falso({"text": texto, "picks": []})


class PreferenciasDoCentroTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.arquivo = os.path.join(self.pasta.name, "data", "briefing-prefs.json")
        env = mock.patch.dict(os.environ, dict(ENV_VOZ, IQ_BRIEFING_PREFS_FILE=self.arquivo))
        env.start()
        self.addCleanup(env.stop)

    def test_sem_arquivo_vale_o_env(self) -> None:
        self.assertIsNone(briefing.ler_prefs())
        self.assertEqual(briefing.configured_feeds(), [("Antiga", "https://exemplo.com/rss")])
        self.assertTrue(briefing._casa_ligada())
        self.assertEqual(briefing._modo_unidade("pt"), "F")
        self.assertEqual(briefing.speaker_config()["speaker"], "media_player.cozinha")
        self.assertEqual(briefing.speaker_config()["volume"], 0.4)
        self.assertIsNone(briefing._total())

    def test_o_arquivo_do_centro_vale_no_lugar_do_env(self) -> None:
        resposta = briefing.gravar_prefs(3, PREFS_DO_CENTRO)
        self.assertEqual((resposta["ok"], resposta["version"]), (True, 3))
        gravado = _ler_json(self.arquivo)
        self.assertEqual((gravado["version"], gravado["prefs"]["picks"]["EUA"]), (3, 4))
        if os.name == "posix":
            self.assertEqual(os.stat(self.arquivo).st_mode & 0o777, 0o600)
        self.assertEqual([n for n, _ in briefing.configured_feeds()], ["EUA", "EUA", "Orlando", "Brasil"])
        self.assertEqual(briefing._limites_por_fonte(["EUA", "Orlando", "Brasil", "Outra"]), {"EUA": 4, "Orlando": 2, "Brasil": 2, "Outra": 1})
        self.assertFalse(briefing._casa_ligada())
        self.assertEqual((briefing._modo_unidade("pt"), briefing._modo_unidade("en"), briefing._unidade_implicita()), ("C", "F", True))
        cfg = briefing.speaker_config()
        self.assertEqual((cfg["speaker"], cfg["engine"], cfg["volume"], cfg["voz_pt"]),
                         ("media_player.living", "tts.elevenlabs_text_to_speech", 0.65, "voz-brian"))  # a voz continua do .env
        self.assertEqual(briefing._total(), (6, 7))
        cliente, pedidos = _cliente_falso()
        briefing.compose(briefing.collect_house(ESTADOS), PREVISAO, [("EUA", ["Senado vota o orcamento"])], "pt", client=cliente)
        pedido = pedidos[0]
        self.assertEqual(pedido["max_words"], 190)
        self.assertTrue(pedido["rules"].startswith("Escolha por importancia, nao por volume."))
        self.assertEqual((pedido["total_min"], pedido["total_max"]), (6, 7))
        self.assertEqual(pedido["candidates"], [{"source": "EUA", "limit": 4, "titles": ["Senado vota o orcamento"]}])
        self.assertFalse(pedido["house_state"])

    def test_motor_de_voz_por_nome_ou_entidade(self) -> None:
        briefing.gravar_prefs(1, dict(PREFS_DO_CENTRO, tts_engine="tts.google_pt"))
        self.assertEqual(briefing.speaker_config()["engine"], "tts.google_pt")
        briefing.gravar_prefs(2, dict(PREFS_DO_CENTRO, tts_engine="google"))
        self.assertEqual(briefing.speaker_config()["engine"], "tts.elevenlabs_text_to_speech")  # outro fornecedor sem entidade: fica o .env
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_TTS_ENGINE": ""}):
            self.assertEqual(briefing.speaker_config()["engine"], "tts.google")

    def test_arquivo_invalido_volta_ao_env_e_preferencia_invalida_nao_grava(self) -> None:
        os.makedirs(os.path.dirname(self.arquivo), exist_ok=True)
        with open(self.arquivo, "w", encoding="utf-8") as arquivo:
            arquivo.write('{"version": 1, "prefs": {"sources": []}}')
        with self.assertLogs("iq_edge.briefing", level="WARNING"):
            self.assertIsNone(briefing.ler_prefs())
        self.assertEqual(briefing.configured_feeds(), [("Antiga", "https://exemplo.com/rss")])
        for ruim in ({"sources": []}, {"picks": {"EUA": 9}}, {"total_min": 8}, {"max_words": 10}, {"speaker": "light.sala"},
                     {"volume": 300}, {"language": "es"}, {"temp_unit": "K"}, {"house_state": "nao"},
                     {"sources": [{"name": "X", "url": "file:///etc/passwd"}]}):
            with self.subTest(ruim=ruim), self.assertRaises(ValueError):
                briefing.gravar_prefs(5, dict(PREFS_DO_CENTRO, **ruim))
        with self.assertRaises(ValueError):
            briefing.gravar_prefs(0, PREFS_DO_CENTRO)
        self.assertIn('"sources": []', _ler_texto(self.arquivo))  # nada foi trocado

    def test_clima_desligado_tira_o_clima_da_fala_e_dos_cartoes(self) -> None:
        briefing.gravar_prefs(1, dict(PREFS_DO_CENTRO, weather=False))
        cliente, pedidos = _cliente_falso()
        publicados, previsoes = [], []
        briefing.handle("bom dia", fetch_states_fn=lambda: ESTADOS, fetch_forecast_fn=lambda e: previsoes.append(e) or PREVISAO,
                        fetch_feed_fn=lambda url, n: [], publish_fn=lambda cartoes, d: publicados.append(cartoes) or True, client=cliente,
                        speak_fn=lambda *a: True, spawn_fn=lambda f: None)
        self.assertIsNone(pedidos[0]["facts"]["weather"])
        self.assertEqual(previsoes, [])
        self.assertNotIn("Clima", [c["titulo"] for c in publicados[0]])

    def test_pedido_automatico_fala_no_idioma_do_centro(self) -> None:
        briefing.gravar_prefs(1, dict(PREFS_DO_CENTRO, language="en", speaker="", house_state=True))
        cliente, pedidos = _cliente_falso("Good morning.")
        with mock.patch.dict(os.environ, {"IQ_BRIEFING_SPEAKER": "", "IQ_BRIEFING_SATELLITE": ""}):
            briefing.handle("bom dia automatico", fetch_states_fn=lambda: ESTADOS, fetch_forecast_fn=lambda e: None, fetch_feed_fn=lambda u, n: [],
                            publish_fn=lambda c, d: True, client=cliente, spawn_fn=lambda f: None)
        self.assertEqual(pedidos[0]["language"], "en")

    def test_testar_usa_o_formulario_so_nesta_thread_e_nao_fala_nem_grava(self) -> None:
        briefing.gravar_prefs(1, PREFS_DO_CENTRO)
        cliente, pedidos = _cliente_falso("Bom dia, Victtor. Em Orlando, 24 graus.")
        visto_em_outra_thread = []
        formulario = dict(PREFS_DO_CENTRO, max_words=80, rules="So economia.", sources=[{"name": "Teste", "url": "https://exemplo.com/a"}])

        def outra():
            visto_em_outra_thread.append(briefing.configured_feeds())

        original = briefing._compor

        def compor_e_olhar(*args, **kwargs):
            t = threading.Thread(target=outra)
            t.start()
            t.join()
            return original(*args, **kwargs)
        with mock.patch.object(briefing, "_compor", compor_e_olhar):
            resposta = briefing.preview(formulario, "pt", fetch_states_fn=lambda: ESTADOS, fetch_forecast_fn=lambda e: None,
                                        fetch_feed_fn=lambda url, n: ["Manchete " + url[-1]], client=cliente)
        self.assertEqual(resposta["text"], "Bom dia, Victtor. Em Orlando, 24 graus.")
        self.assertEqual(resposta["words"], 7)
        self.assertGreaterEqual(resposta["speech_seconds"], 2)
        self.assertEqual(pedidos[0]["max_words"], 80)
        self.assertTrue(pedidos[0]["rules"].startswith("So economia."))
        self.assertEqual([f["source"] for f in pedidos[0]["candidates"]], ["Teste"])
        self.assertEqual([n for n, _ in visto_em_outra_thread[0]], ["EUA", "EUA", "Orlando", "Brasil"])  # o bom dia de verdade nao mudou
        self.assertEqual([n for n, _ in briefing.configured_feeds()], ["EUA", "EUA", "Orlando", "Brasil"])
        self.assertEqual(_ler_json(self.arquivo)["prefs"]["max_words"], 190)  # nada gravado
        with self.assertRaises(ValueError):
            briefing.preview(dict(PREFS_DO_CENTRO, sources=[]), "pt")


if __name__ == "__main__":
    unittest.main()
