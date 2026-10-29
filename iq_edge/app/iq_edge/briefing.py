"""Resumo falado da casa ("bom dia") — copia do iq-api do Orange Pi (lote H2), adaptada ao add-on IQ (lotes A4 e A5).

Mudancas desta copia: HA_URL/HA_TOKEN vem de settings (no add-on: http://supervisor/core e o SUPERVISOR_TOKEN); o arquivo
de preferencias fica em /data (settings.data_dir()); as preferencias aceitam `schedule` {time "HH:MM", days [0..6]}
(a fala automatica do add-on, schedule.py). IA (lote A5): a casa nunca tem chave; `compose` manda SO os dados (nomes, clima,
aberto/alarme se a casa entra, manchetes candidatas por fonte com o limite) ao centro (POST briefing-compose, contrato v2,
center.Center.compose) e usa `text` + `picks` da resposta; casa nao pareada ou qualquer erro = texto por regra, como antes.
O resto (coleta, cartoes, alto-falante, volume, reserva) e o mesmo.
O centro NUNCA chama servico por aqui: so o Bom dia da propria casa (horario, evento iq_bom_dia ou "Falar agora") fala.

Quem diz "bom dia" (ou "resumo do dia") ao assistente recebe, em uns 30
segundos de fala: quem esta em casa, o clima, o que esta aberto ou destravado,
o alarme e as manchetes das fontes configuradas (o estado da casa, aberto e
alarme, sai com IQ_BRIEFING_CASA=nao). Ao mesmo tempo, o painel
(cartao `iq-orbe-card`) recebe o evento `iq_briefing` do Home Assistant com os
mesmos dados em cartoes.

Desenho:

- Deteccao LOCAL (regex), sem IA: "bom dia" so conta se for a frase inteira
  (ou quase). "bom dia, acende a luz da sala" continua sendo um comando, e
  "boa noite" nunca dispara resumo -- e o nome de uma cena.
- O idioma da resposta e o da frase ("good morning" -> ingles).
- Os DADOS sao coletados por codigo (estado do HA, previsao, RSS). A IA so
  escreve o texto falado a partir deles; os cartoes nunca passam pela IA.
- Sem o centro (casa nao pareada), ou se a IA falhar, vale um texto montado
  por regra: o resumo funciona igual, so soa menos natural.
- Manchetes sao texto de terceiros: o centro as passa a IA marcadas como
  dados nao confiaveis, e elas nunca viram HTML nos cartoes.

Configuracao (variaveis lidas na hora, todas opcionais):

  IQ_BRIEFING_FEEDS           "Orlando=https://...,Brasil=https://..."
  IQ_BRIEFING_WEATHER_ENTITY  entidade `weather.*` (padrao: a primeira)
  IQ_BRIEFING_TEMP_SENSOR     sensor real de temperatura (ex.: o de fora da casa): vira a
                              temperatura ATUAL; maxima e minima seguem da previsao. Se o
                              sensor falhar, vale a temperatura do `weather.*`
  IQ_BRIEFING_CARD_SECONDS    quanto tempo os cartoes ficam no painel (40)
  IQ_BRIEFING_TEMP_UNIT       F, C, FC (as duas) ou IDIOMA (C em portugues, F em ingles;
                              nesse modo a fala diz so "23 graus", sem o nome da unidade)
  IQ_BRIEFING_FEED_ITEMS      manchetes CANDIDATAS por fonte (padrao 12)
  IQ_BRIEFING_PICK            maximo de manchetes mostradas por fonte (padrao 2)
  IQ_BRIEFING_PICK_MAP        maximo por fonte, ex.: "EUA=3,Brasil=2"
  IQ_BRIEFING_NEWS_RULES      criterio de importancia (texto livre; ha um padrao)
  IQ_BRIEFING_MAX_WORDS       tamanho maximo da fala (padrao 110)
  IQ_BRIEFING_CASA            sim (padrao) ou nao/off/0: com "nao", o resumo NAO fala nem
                              mostra o estado da casa (aberto/fechado, alarme); fica so
                              cumprimento (com os nomes), clima e noticias
  IQ_BRIEFING_CLIMA           sim (padrao) ou nao: com "nao", sem clima (fala e cartao)
  IQ_BRIEFING_TOTAL           total de noticias somando as fontes, ex.: "6-7" (sem padrao)
  IQ_BRIEFING_PREFS_FILE      arquivo das preferencias vindas do centro (lote H2; padrao
                              /opt/iq-assistant/data/briefing-prefs.json)

PREFERENCIAS DO CENTRO (lote H2, contrato v1): o centro (IQ Business) grava, pela rota
PUT /v1/briefing-prefs (edge_prefs.py), um JSON com fontes, escolhas por fonte, total,
maximo de palavras, regras, casa ligada, clima, alto-falante, volume, motor de voz,
idioma e unidade. Se o arquivo existe e e valido, ele VALE NO LUGAR do .env para esses
itens; sem arquivo (ou com arquivo invalido) tudo segue o .env, como antes. O resto
(voz, satelite, atrasos, entidade de clima) continua so no .env. POST
/v1/briefing-preview monta o texto com as preferencias enviadas, SEM falar e sem gravar.

Fontes com o MESMO nome em IQ_BRIEFING_FEEDS se juntam numa so (ex.: duas fontes
dos EUA). A IA escolhe, entre as candidatas, so o que importa (ver as regras).

Voz premium num alto-falante (opcional; todas juntas ou nenhuma):

  IQ_BRIEFING_SPEAKER         media_player que conta o resumo (ex.: o Sonos da sala)
  IQ_BRIEFING_TTS_ENGINE      entidade tts que gera a voz (ex.: ElevenLabs)
  IQ_BRIEFING_TTS_VOICE       id da voz em portugues (e em ingles, se a outra faltar)
  IQ_BRIEFING_TTS_VOICE_EN    id da voz em ingles (opcional)
  IQ_BRIEFING_SPEAKER_VOLUME  volume do resumo (0.65 ou 65); depois volta ao anterior
  IQ_BRIEFING_IGNORAR         entidades (ou nomes) que NAO contam como "aberto"
                              (ex.: a porta do quarto que dispara o bom dia)
  IQ_BRIEFING_SPEAKER_BUSY    o que fazer se o alto-falante estiver TOCANDO (TV, musica):
                              "voice" (padrao: fala pelo aparelho de voz, sem interromper)
                              ou "interromper" (fala por cima, com o volume do resumo)
  IQ_BRIEFING_SPEAKER_WAIT    segundos que espera o alto-falante voltar se estiver
                              indisponivel na hora (padrao 8; o Sonos oscila)
  IQ_BRIEFING_SPEAKER_DELAY   segundos de espera antes de tocar (padrao 2): o
                              aparelho de voz diz "Um instante." primeiro
  IQ_BRIEFING_SATELLITE       assist_satellite de reserva: se o alto-falante ou a
                              voz premium falharem, o resumo e falado nele

PEDIDO AUTOMATICO: uma automacao do HA (sem aparelho de voz) chama com o texto
"bom dia automatico". Nesse caso nao ha "Um instante." (sem espera) e, se o
alto-falante nao estiver disponivel, o resumo e falado pelo IQ_BRIEFING_SATELLITE
-- devolver o texto nao adiantaria, porque ninguem o falaria.

Com isso o aparelho de voz responde so "Um instante." e o resumo inteiro sai no
alto-falante escolhido. Sem isso (ou se o alto-falante/a voz nao estiverem
disponiveis na hora), o aparelho de voz fala o resumo todo, como antes.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlsplit

import requests

from . import settings

HA_URL = settings.ha_url()
HA_TOKEN = settings.ha_token()


logger = logging.getLogger("iq_edge.briefing")


# --------------------------------------------------------------------------
# Preferencias vindas do centro (lote H2, contrato v1)
# --------------------------------------------------------------------------

_PREFS_LOCK = threading.Lock()
_PREFS_CACHE: dict[str, Any] = {"path": None, "mtime": None, "prefs": None}
_PREFS_LOCAL = threading.local()  # "Testar": as preferencias do formulario, so nesta thread
_UNIDADES = {"language": "IDIOMA", "C": "C", "F": "F", "FC": "FC"}


def prefs_path() -> str:
    return os.getenv("IQ_BRIEFING_PREFS_FILE", "").strip() or str(settings.data_dir() / "briefing-prefs.json")


def _inteiro(valor: Any, minimo: int, maximo: int, campo: str) -> int:
    if isinstance(valor, bool):
        raise ValueError(campo)
    try:
        numero = valor if isinstance(valor, int) else int(str(valor).strip())
    except (TypeError, ValueError):
        raise ValueError(campo) from None
    if not minimo <= numero <= maximo:
        raise ValueError(campo)
    return numero


def validar_prefs(prefs: Any) -> dict[str, Any]:
    """A mesma conferencia do centro (business/briefing_prefs.py validate). ValueError com o campo."""
    if not isinstance(prefs, dict):
        raise ValueError("prefs")
    fontes = prefs.get("sources")
    if not isinstance(fontes, list) or not 1 <= len(fontes) <= 20:
        raise ValueError("sources")
    limpas = []
    for item in fontes:
        nome = " ".join(str((item or {}).get("name") or "").split()) if isinstance(item, dict) else ""
        url = str(item.get("url") or "").strip() if isinstance(item, dict) else ""
        partes = urlsplit(url)
        if not nome or len(nome) > 40 or len(url) > 500 or partes.scheme not in ("http", "https") or not partes.hostname \
                or partes.username or partes.password or any(c.isspace() for c in url):
            raise ValueError("sources")
        limpas.append({"name": nome, "url": url})
    nomes = list(dict.fromkeys(f["name"] for f in limpas))
    escolhas = prefs.get("picks") if isinstance(prefs.get("picks"), dict) else {}
    total_min = _inteiro(prefs.get("total_min"), 1, 20, "total_min")
    total_max = _inteiro(prefs.get("total_max"), 1, 20, "total_max")
    if total_min > total_max:
        raise ValueError("total_min")
    regras = prefs.get("rules") if prefs.get("rules") is not None else ""
    if not isinstance(regras, str) or len(regras.strip()) > 2000:
        raise ValueError("rules")
    alto_falante = prefs.get("speaker") or ""
    if not isinstance(alto_falante, str) or (alto_falante and not re.fullmatch(r"media_player\.[a-z0-9_]{1,255}", alto_falante)):
        raise ValueError("speaker")
    motor = prefs.get("tts_engine") or ""
    if not isinstance(motor, str) or (motor and not re.fullmatch(r"tts\.[a-z0-9_]{1,120}|[a-z0-9_]{1,40}", motor)):
        raise ValueError("tts_engine")
    if prefs.get("language") not in ("pt", "en"):
        raise ValueError("language")
    if prefs.get("temp_unit") not in _UNIDADES:
        raise ValueError("temp_unit")
    for chave in ("house_state", "weather"):
        if not isinstance(prefs.get(chave), bool):
            raise ValueError(chave)
    volume = prefs.get("volume")
    limpo = {
        "house_state": prefs["house_state"], "weather": prefs["weather"], "sources": limpas,
        "picks": {n: _inteiro(escolhas.get(n, 1), 0, 6, "picks") for n in nomes},
        "total_min": total_min, "total_max": total_max, "max_words": _inteiro(prefs.get("max_words"), 40, 300, "max_words"),
        "rules": regras.strip(), "speaker": alto_falante,
        "volume": None if volume in (None, "") else _inteiro(volume, 0, 100, "volume"),
        "tts_engine": motor, "language": prefs["language"], "temp_unit": prefs["temp_unit"],
    }
    if prefs.get("schedule") is not None:  # lote A4: a fala automatica do add-on
        limpo["schedule"] = validar_horario(prefs["schedule"])
    return limpo


def validar_horario(valor: Any) -> dict[str, Any]:
    """{"time": "HH:MM", "days": [0..6]} (0 = segunda; sem dias = sem fala automatica). A mesma conferencia do centro."""
    if not isinstance(valor, dict) or not isinstance(valor.get("time"), str) \
            or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", valor["time"]):
        raise ValueError("schedule")
    dias = valor.get("days")
    if not isinstance(dias, list) or len(dias) > 7 \
            or not all(isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 6 for d in dias):
        raise ValueError("schedule")
    return {"time": valor["time"], "days": sorted(set(dias))}


def ler_prefs() -> dict[str, Any] | None:
    """As preferencias do centro (arquivo, relido so quando muda), ou None: vale o .env. Arquivo invalido = None + aviso no log."""
    local = getattr(_PREFS_LOCAL, "prefs", None)
    if local is not None:
        return local
    caminho = prefs_path()
    try:
        marca = os.stat(caminho).st_mtime_ns
    except OSError:
        return None
    with _PREFS_LOCK:
        if _PREFS_CACHE["path"] == caminho and _PREFS_CACHE["mtime"] == marca:
            return _PREFS_CACHE["prefs"]
    try:
        with open(caminho, encoding="utf-8") as arquivo:
            prefs = validar_prefs((json.load(arquivo) or {}).get("prefs"))
    except (OSError, ValueError, AttributeError, TypeError):
        logger.warning("Resumo: preferencias do centro ilegiveis em %s; usando o .env.", caminho)
        prefs = None
    with _PREFS_LOCK:
        _PREFS_CACHE.update(path=caminho, mtime=marca, prefs=prefs)
    return prefs


def gravar_prefs(versao: Any, prefs: Any) -> dict[str, Any]:
    """PUT /v1/briefing-prefs: confere, grava atomicamente (arquivo 600) e devolve a versao confirmada."""
    versao = _inteiro(versao, 1, 10**9, "version")
    limpas = validar_prefs(prefs)
    caminho = prefs_path()
    pasta = os.path.dirname(caminho) or "."
    os.makedirs(pasta, exist_ok=True)
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    temporario = os.path.join(pasta, f".briefing-prefs.{os.getpid()}.{threading.get_ident()}.tmp")
    descritor = os.open(temporario, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descritor, "w", encoding="utf-8") as arquivo:
            json.dump({"version": versao, "saved_at": agora, "prefs": limpas}, arquivo, ensure_ascii=False)
        os.replace(temporario, caminho)
    except BaseException:
        try:
            os.unlink(temporario)
        except OSError:
            pass
        raise
    with _PREFS_LOCK:
        _PREFS_CACHE.update(path=None, mtime=None, prefs=None)
    return {"ok": True, "version": versao, "saved_at": agora}


@contextmanager
def usando_prefs(prefs: dict[str, Any]):
    """"Testar": estas preferencias valem so dentro do bloco e so nesta thread (o bom dia de verdade nao muda)."""
    _PREFS_LOCAL.prefs = validar_prefs(prefs)
    try:
        yield _PREFS_LOCAL.prefs
    finally:
        _PREFS_LOCAL.prefs = None


def _pref(chave: str) -> Any:
    prefs = ler_prefs()
    return None if prefs is None else prefs.get(chave)


def _env_unidade() -> str:
    unidade = _pref("temp_unit")
    return _UNIDADES[unidade] if unidade in _UNIDADES else os.getenv("IQ_BRIEFING_TEMP_UNIT", "")


def _clima_ligado() -> bool:
    valor = _pref("weather")
    if isinstance(valor, bool):
        return valor
    return os.getenv("IQ_BRIEFING_CLIMA", "").strip().lower() not in ("nao", "não", "0", "off")


def _total() -> tuple[int, int] | None:
    prefs = ler_prefs()
    if prefs is not None:
        return prefs["total_min"], prefs["total_max"]
    m = re.fullmatch(r"\s*(\d{1,2})\s*(?:-|a|to)?\s*(\d{1,2})?\s*", os.getenv("IQ_BRIEFING_TOTAL", ""))
    if not m:
        return None
    menor, maior = int(m.group(1)), int(m.group(2) or m.group(1))
    return (menor, maior) if 1 <= menor <= maior <= 20 else None


def _motor_tts(do_env: str) -> str:
    """O motor de voz: a entidade tts.* do centro, ou um nome (ex.: elevenlabs) que escolhe a do .env se ela for desse
    fornecedor; sem isso, o do .env."""
    valor = _pref("tts_engine") or ""
    if valor.startswith("tts."):
        return valor
    if valor and do_env and valor in do_env.lower():
        return do_env
    if valor and not do_env:
        return "tts." + valor
    return do_env


# --------------------------------------------------------------------------
# Deteccao
# --------------------------------------------------------------------------

_SAUDACOES = {"pt": ("bom dia",), "en": ("good morning",)}
_RESUMOS = {
    "pt": (
        "resumo do dia",
        "resumo da casa",
        "me atualiza",
        "me atualize",
        "como esta a casa",
        "o que ha de novo hoje",
    ),
    "en": (
        "daily briefing",
        "morning briefing",
        "house briefing",
        "brief me",
        "catch me up",
        "how is the house",
        "hows the house",
    ),
}
_ENFEITES = {"oi", "ola", "e", "ai", "hey", "hi", "hello", "ei"}
# Se sobra um destes depois da saudacao, e um pedido de verdade e nao um
# cumprimento ("bom dia ori acende a luz").
_VERBOS_DE_PEDIDO = {
    "acende", "apaga", "liga", "desliga", "abre", "fecha", "toca", "coloca",
    "cria", "marca", "qual", "quanto", "quantos", "quem", "como", "que",
    "turn", "open", "close", "play", "set", "what", "how", "who", "create",
}


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    limpo = re.sub(r"[^a-z0-9 ]+", " ", sem_acento.lower())
    return re.sub(r"\s+", " ", limpo).strip()


def detect_briefing(texto: str) -> str | None:
    """Devolve "pt" ou "en" se a frase pede o resumo da casa; senao None."""
    norm = _normalizar(texto)
    if not norm:
        return None
    palavras = norm.split()
    while palavras and palavras[0] in _ENFEITES:
        palavras.pop(0)
    norm = " ".join(palavras)

    for idioma, frases in _SAUDACOES.items():
        for frase in frases:
            if norm == frase or norm.startswith(frase + " "):
                resto = norm[len(frase):].split()
                if len(resto) <= 3 and not any(p in _VERBOS_DE_PEDIDO for p in resto):
                    return idioma

    if len(palavras) <= 8:
        for idioma, frases in _RESUMOS.items():
            if any(frase in norm for frase in frases):
                return idioma
    return None


# --------------------------------------------------------------------------
# Coleta -- Home Assistant
# --------------------------------------------------------------------------


def _ha_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}


def fetch_states() -> list[dict[str, Any]]:
    if not HA_URL or not HA_TOKEN:
        return []
    resposta = requests.get(f"{HA_URL}/api/states", headers=_ha_headers(), timeout=10)
    resposta.raise_for_status()
    return resposta.json()


def fetch_forecast(entity_id: str) -> dict[str, Any] | None:
    """Previsao do dia (a primeira da lista diaria). None se nao der."""
    if not HA_URL or not HA_TOKEN or not entity_id:
        return None
    try:
        resposta = requests.post(
            f"{HA_URL}/api/services/weather/get_forecasts?return_response",
            headers=_ha_headers(),
            json={"entity_id": entity_id, "type": "daily"},
            timeout=10,
        )
        resposta.raise_for_status()
        lista = (
            (resposta.json().get("service_response") or {})
            .get(entity_id, {})
            .get("forecast")
            or []
        )
        return lista[0] if lista else None
    except (requests.RequestException, ValueError, AttributeError, TypeError):
        return None


def publish_cards(cards: list[dict[str, Any]], duracao: int) -> bool:
    """Manda os cartoes ao painel como evento do HA. Melhor esforco: o
    resumo falado nao depende disto."""
    if not HA_URL or not HA_TOKEN:
        return False
    try:
        resposta = requests.post(
            f"{HA_URL}/api/events/iq_briefing",
            headers=_ha_headers(),
            json={"cartoes": cards, "duracao": duracao},
            timeout=8,
        )
        resposta.raise_for_status()
        return True
    except requests.RequestException:
        logger.warning("Nao consegui publicar os cartoes do resumo no HA.", exc_info=True)
        return False


_CONDICOES = {
    "clear-night": ("céu limpo", "clear", "mdi:weather-night"),
    "cloudy": ("nublado", "cloudy", "mdi:weather-cloudy"),
    "exceptional": ("tempo incomum", "unusual weather", "mdi:alert-circle-outline"),
    "fog": ("neblina", "foggy", "mdi:weather-fog"),
    "hail": ("granizo", "hail", "mdi:weather-hail"),
    "lightning": ("tempestade", "thunderstorms", "mdi:weather-lightning"),
    "lightning-rainy": ("tempestade com chuva", "thunderstorms with rain", "mdi:weather-lightning-rainy"),
    "partlycloudy": ("parcialmente nublado", "partly cloudy", "mdi:weather-partly-cloudy"),
    "pouring": ("chuva forte", "heavy rain", "mdi:weather-pouring"),
    "rainy": ("chuva", "rain", "mdi:weather-rainy"),
    "snowy": ("neve", "snow", "mdi:weather-snowy"),
    "snowy-rainy": ("chuva com neve", "sleet", "mdi:weather-snowy-rainy"),
    "sunny": ("céu limpo e sol", "sunny", "mdi:weather-sunny"),
    "windy": ("ventania", "windy", "mdi:weather-windy"),
    "windy-variant": ("ventania", "windy", "mdi:weather-windy-variant"),
}

_ABERTURAS = {
    "door": ("porta", "door"),
    "window": ("janela", "window"),
    "garage_door": ("garagem", "garage"),
    "opening": ("abertura", "opening"),
}
_ALARMES_ARMADOS = {
    "armed_home", "armed_away", "armed_night", "armed_vacation", "armed_custom_bypass",
}


def collect_house(
    states: list[dict[str, Any]],
    weather_entity: str | None = None,
    ignorar: set[str] | None = None,
    temp_sensor: str | None = None,
) -> dict[str, Any]:
    """Resume os estados do HA no que o resumo precisa: clima atual, o que
    esta aberto/destravado, alarme e quem esta em casa."""
    clima: dict[str, Any] | None = None
    abertos: list[str] = []
    alarme: str | None = None
    pessoas: list[str] = []
    entidade_clima: str | None = None

    for s in states:
        entity_id = str(s.get("entity_id") or "")
        dominio = entity_id.split(".", 1)[0]
        estado = str(s.get("state") or "")
        attrs = s.get("attributes") or {}
        nome = str(attrs.get("friendly_name") or entity_id)
        if estado in ("unavailable", "unknown", ""):
            continue
        ignorado = bool(ignorar) and (entity_id.lower() in ignorar or nome.lower() in ignorar)

        if dominio == "weather":
            if weather_entity and entity_id != weather_entity:
                continue
            if clima is None:
                entidade_clima = entity_id
                clima = {
                    "condicao": estado,
                    "temperatura": attrs.get("temperature"),
                    "unidade": attrs.get("temperature_unit") or "",
                    "umidade": attrs.get("humidity"),
                }
        elif dominio == "binary_sensor" and attrs.get("device_class") in _ABERTURAS and estado == "on":
            if not ignorado:
                abertos.append(nome)
        elif dominio == "cover" and attrs.get("device_class") in ("garage", "door", "gate") and estado in ("open", "opening"):
            if not ignorado:
                abertos.append(nome)
        elif dominio == "lock" and estado == "unlocked":
            if not ignorado:
                abertos.append(nome + " (destravada)")
        elif dominio == "alarm_control_panel" and alarme is None:
            alarme = estado
        elif dominio == "person" and estado == "home":
            pessoas.append(nome)

    if clima is not None and temp_sensor:
        for e in states:
            if str(e.get("entity_id")) != temp_sensor:
                continue
            try:
                valor = float(e.get("state"))
            except (TypeError, ValueError):
                break  # indisponivel/desconhecido: vale a temperatura do weather
            clima["unidade_previsao"] = clima["unidade"]
            clima["temperatura"] = valor
            clima["unidade"] = str((e.get("attributes") or {}).get("unit_of_measurement") or clima["unidade"])
            clima["fonte_temperatura"] = "sensor"
            break

    return {
        "clima": clima,
        "entidade_clima": entidade_clima,
        "abertos": abertos,
        "alarme": alarme,
        "pessoas": pessoas,
    }


# --------------------------------------------------------------------------
# Coleta -- noticias (RSS/Atom)
# --------------------------------------------------------------------------

_TTL_FEED_SEGUNDOS = 600
_LIMITE_BYTES_FEED = 1_500_000
_cache_feeds: dict[tuple[str, int], tuple[float, list[str]]] = {}


def _limpar_titulo(valor: str | None) -> str:
    texto = html.unescape(valor or "")
    texto = re.sub(r"<[^>]+>", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()[:140]


def parse_feed(conteudo: bytes, limite: int = 3) -> list[str]:
    """Titulos das primeiras entradas de um RSS 2.0 ou Atom."""
    try:
        raiz = ET.fromstring(conteudo)
    except ET.ParseError:
        return []
    titulos: list[str] = []
    for elemento in raiz.iter():
        marca = elemento.tag.rsplit("}", 1)[-1] if isinstance(elemento.tag, str) else ""
        if marca not in ("item", "entry"):
            continue
        for filho in elemento:
            if isinstance(filho.tag, str) and filho.tag.rsplit("}", 1)[-1] == "title":
                titulo = _limpar_titulo(filho.text)
                if titulo:
                    titulos.append(titulo)
                break
        if len(titulos) >= limite:
            break
    return titulos


def fetch_feed(url: str, limite: int = 3, *, getter: Callable[..., Any] | None = None) -> list[str]:
    """Manchetes de um feed, com cache de 10 minutos (o feed do g1 passa de
    500 KB e a pessoa pode repetir o pedido). Falha vira lista vazia."""
    agora = time.monotonic()
    chave = (url, limite)
    guardado = _cache_feeds.get(chave)
    if guardado and agora - guardado[0] < _TTL_FEED_SEGUNDOS:
        return list(guardado[1])
    try:
        pegar = getter or requests.get
        resposta = pegar(url, timeout=6, headers={"User-Agent": "Mozilla/5.0 IQAssistant"}, stream=True)
        resposta.raise_for_status()
        conteudo = b""
        for bloco in resposta.iter_content(65536):
            conteudo += bloco
            if len(conteudo) > _LIMITE_BYTES_FEED:
                break
        titulos = parse_feed(conteudo, limite)
    except (requests.RequestException, AttributeError, TypeError):
        logger.warning("Nao consegui ler o feed de noticias do resumo.", exc_info=True)
        return []
    if titulos:
        _cache_feeds[chave] = (agora, titulos)
    return titulos


def configured_feeds() -> list[tuple[str, str]]:
    """As fontes do centro (lote H2) ou IQ_BRIEFING_FEEDS: "Orlando=https://...,Brasil=https://..." """
    prefs = ler_prefs()
    if prefs is not None:
        return [(f["name"], f["url"]) for f in prefs["sources"]]
    pares: list[tuple[str, str]] = []
    for parte in os.getenv("IQ_BRIEFING_FEEDS", "").split(","):
        nome, separador, url = parte.partition("=")
        nome, url = nome.strip(), url.strip()
        if separador and nome and url.startswith(("http://", "https://")):
            pares.append((nome, url))
    return pares


# --------------------------------------------------------------------------
# Texto falado e cartoes
# --------------------------------------------------------------------------

_T = {
    "pt": {
        "bom_dia": "Bom dia",
        "aberto": "Aberto ou destravado agora: {itens}.",
        "fechado": "A casa está toda fechada.",
        "alarme_armado": "O alarme está armado.",
        "alarme_disparado": "Atenção: o alarme disparou.",
        "chuva": "chance de chuva de {p}%",
        "agora": "Agora faz {t}{u}, {cond}",
        "maxmin": "máxima de {hi} e mínima de {lo}{u}",
        "falha_casa": "Não consegui falar com a casa agora. Tente de novo em instantes.",
        "ack": "Um instante.",
        "titulo_clima": "Clima", "titulo_casa": "Casa",
        "em_casa": "Em casa: {nomes}",
        "alarme": "Alarme: {estado}",
        "armado": "armado", "desarmado": "desarmado", "disparado": "disparado",
        "max": "Máxima {hi}{u} · mínima {lo}{u}", "chuva_card": "Chuva: {p}%",
        "tudo_fechado": "Tudo fechado",
        "noticias_fonte": "Em {fonte}: {titulos}.",
        "ou": "ou",
        "lingua": "português do Brasil", "palavras": 110,
    },
    "en": {
        "bom_dia": "Good morning",
        "aberto": "Open or unlocked right now: {itens}.",
        "fechado": "The house is all closed up.",
        "alarme_armado": "The alarm is armed.",
        "alarme_disparado": "Heads up: the alarm went off.",
        "chuva": "{p}% chance of rain",
        "agora": "It is {t}{u} right now, {cond}",
        "maxmin": "high of {hi} and low of {lo}{u}",
        "falha_casa": "I couldn't reach the house right now. Please try again in a moment.",
        "ack": "One moment.",
        "titulo_clima": "Weather", "titulo_casa": "Home",
        "em_casa": "At home: {nomes}",
        "alarme": "Alarm: {estado}",
        "armado": "armed", "desarmado": "disarmed", "disparado": "triggered",
        "max": "High {hi}{u} · low {lo}{u}", "chuva_card": "Rain: {p}%",
        "tudo_fechado": "All closed",
        "noticias_fonte": "In {fonte}: {titulos}.",
        "ou": "or",
        "lingua": "American English", "palavras": 105,
    },
}


def _numero(valor: Any) -> str:
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return ""
    return str(int(round(n)))


def _modo_unidade(idioma: str = "pt") -> str:
    """"F", "C", "FC" (as duas) ou "" (mantem a unidade da fonte). Com IDIOMA, a
    unidade segue o idioma da fala: Celsius em portugues, Fahrenheit em ingles."""
    v = _env_unidade().strip().upper()
    if v in ("IDIOMA", "AUTO", "LANG", "LINGUA"):
        return "C" if idioma == "pt" else "F"
    if v in ("FC", "CF", "BOTH", "AMBAS", "F+C", "F/C", "C/F"):
        return "FC"
    return v[:1] if v[:1] in ("F", "C") else ""


def _unidade_implicita() -> bool:
    """No modo IDIOMA a unidade e obvia (portugues = Celsius, ingles = Fahrenheit), entao a
    fala nao a repete -- cada palavra falada custa credito de voz."""
    return _env_unidade().strip().upper() in ("IDIOMA", "AUTO", "LANG", "LINGUA")


def _nome_da_unidade(u: str) -> str:
    return {"F": "Fahrenheit", "C": "Celsius"}.get("F" if "F" in u.upper() else ("C" if "C" in u.upper() else ""), "")


def _letra_da_unidade(u: str) -> str:
    return "F" if "F" in u.upper() else ("C" if "C" in u.upper() else "")


def _converter_se(valor: Any, origem: str, alvo: str) -> Any:
    return _converter(valor, origem, alvo) if origem and origem != alvo else valor


def _clima_resumido(dados: dict[str, Any], previsao: dict[str, Any] | None, idioma: str) -> dict[str, str]:
    clima = dados.get("clima") or {}
    cond = _CONDICOES.get(str(clima.get("condicao")), (str(clima.get("condicao") or ""),) * 2 + ("mdi:weather-partly-cloudy",))
    nome_cond = cond[0] if idioma == "pt" else cond[1]
    # A temperatura atual pode vir de um sensor (ex.: em Fahrenheit) enquanto a previsao
    # vem em outra unidade (ex.: Celsius do met.no): cada uma com a sua origem.
    u_temp = str(clima.get("unidade") or "")
    o_temp = _letra_da_unidade(u_temp)
    o_prev = _letra_da_unidade(str(clima.get("unidade_previsao") or u_temp))
    previsao = previsao or {}
    temp, alta, baixa = clima.get("temperatura"), previsao.get("temperature"), previsao.get("templow")
    modo = _modo_unidade(idioma)
    u = u_temp
    temp2 = alta2 = baixa2 = None
    u2 = ""
    if modo == "FC" and (o_temp or o_prev):
        # primaria em Fahrenheit, secundaria em Celsius
        f_vals = (_converter_se(temp, o_temp, "F"), _converter_se(alta, o_prev, "F"), _converter_se(baixa, o_prev, "F"))
        c_vals = (_converter_se(temp, o_temp, "C"), _converter_se(alta, o_prev, "C"), _converter_se(baixa, o_prev, "C"))
        (temp, alta, baixa), u = f_vals, "°F"
        (temp2, alta2, baixa2), u2 = c_vals, "°C"
    else:
        alvo = modo if modo in ("F", "C") else (o_temp or o_prev)
        if alvo:
            temp = _converter_se(temp, o_temp, alvo)
            alta = _converter_se(alta, o_prev, alvo)
            baixa = _converter_se(baixa, o_prev, alvo)
            u = "°" + alvo
    prefixo = "graus " if idioma == "pt" else "degrees "
    nome1, nome2 = _nome_da_unidade(u), _nome_da_unidade(u2)
    return {
        "cond": nome_cond,
        "icone": cond[2],
        "temp": _numero(temp),
        "u": u,
        # Unidade por extenso para a fala: "25 graus" sozinho nao diz se e
        # Celsius ou Fahrenheit (a casa de Orlando mistura as duas).
        "uf": prefixo.strip() if (_unidade_implicita() or not nome1) else (prefixo + nome1),
        "hi": _numero(alta),
        "lo": _numero(baixa),
        "chuva": _numero(previsao.get("precipitation_probability")),
        # segunda unidade (modo FC)
        "temp2": _numero(temp2),
        "hi2": _numero(alta2),
        "lo2": _numero(baixa2),
        "u2": u2,
        "n2": nome2,
    }


def _converter(valor: Any, origem: str, destino: str) -> Any:
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return valor
    if origem == "C" and destino == "F":
        return n * 9 / 5 + 32
    if origem == "F" and destino == "C":
        return (n - 32) * 5 / 9
    return n


def _cartao_casa(dados: dict[str, Any], idioma: str) -> dict[str, Any]:
    """O cartao "Casa": o que esta aberto (ou tudo fechado), o alarme e quem esta em casa."""
    t = _T[idioma]
    linhas_casa: list[str] = []
    alerta = False
    if dados.get("abertos"):
        alerta = True
        linhas_casa.extend(dados["abertos"][:4])
    else:
        linhas_casa.append(t["tudo_fechado"])
    alarme = dados.get("alarme")
    if alarme == "triggered":
        alerta = True
        linhas_casa.append(t["alarme"].format(estado=t["disparado"]))
    elif alarme in _ALARMES_ARMADOS:
        linhas_casa.append(t["alarme"].format(estado=t["armado"]))
    elif alarme == "disarmed":
        linhas_casa.append(t["alarme"].format(estado=t["desarmado"]))
    if dados.get("pessoas"):
        linhas_casa.append(t["em_casa"].format(nomes=", ".join(dados["pessoas"])))
    return {
        "icone": "mdi:door-open" if dados.get("abertos") else "mdi:home-lock",
        "titulo": t["titulo_casa"],
        "linhas": linhas_casa,
        **({"tom": "alerta"} if alerta else {}),
    }


def build_cards(
    dados: dict[str, Any],
    previsao: dict[str, Any] | None,
    noticias: list[tuple[str, list[str]]],
    idioma: str,
    *,
    casa: bool | None = None,
) -> list[dict[str, Any]]:
    """Clima, Casa (se o estado da casa entra; `casa=False` = o Bom dia preparado, que ganha o cartao na hora) e noticias."""
    t = _T[idioma]
    cartoes: list[dict[str, Any]] = []

    if dados.get("clima"):
        c = _clima_resumido(dados, previsao, idioma)
        linhas = []
        if c["temp"]:
            base = f"{c['temp']}{c['u']}" + (f" / {c['temp2']}{c['u2']}" if c["temp2"] else "")
            linhas.append(f"{base} · {c['cond']}")
        else:
            linhas.append(c["cond"])
        if c["hi"] and c["lo"]:
            if c["hi2"] and c["lo2"]:
                linhas.append(
                    t["max"].format(
                        hi=f"{c['hi']}{c['u']} / {c['hi2']}{c['u2']}",
                        lo=f"{c['lo']}{c['u']} / {c['lo2']}{c['u2']}",
                        u="",
                    )
                )
            else:
                linhas.append(t["max"].format(hi=c["hi"], lo=c["lo"], u=c["u"]))
        if c["chuva"]:
            linhas.append(t["chuva_card"].format(p=c["chuva"]))
        cartoes.append({"icone": c["icone"], "titulo": t["titulo_clima"], "linhas": linhas})

    if _casa_ligada() if casa is None else casa:
        cartoes.append(_cartao_casa(dados, idioma))

    for fonte, titulos in noticias:
        if titulos:
            cartoes.append({"icone": "mdi:newspaper-variant-outline", "titulo": fonte, "linhas": titulos})
    return cartoes


def _casa_ligada() -> bool:
    """A preferencia do centro ou IQ_BRIEFING_CASA: False (nao/não/0/off) tira o estado da casa do resumo."""
    valor = _pref("house_state")
    if isinstance(valor, bool):
        return valor
    return os.getenv("IQ_BRIEFING_CASA", "").strip().lower() not in ("nao", "não", "0", "off")


def _lista_nomes(nomes: list[str], idioma: str) -> str:
    if len(nomes) <= 1:
        return "".join(nomes)
    e = " e " if idioma == "pt" else " and "
    return ", ".join(nomes[:-1]) + e + nomes[-1]


def _saudacao(dados: dict[str, Any], idioma: str) -> str:
    """ "Bom dia, Victtor e Matheus." (os nomes de quem esta em casa agora)."""
    saudacao = _T[idioma]["bom_dia"]
    if dados.get("pessoas"):
        saudacao += ", " + _lista_nomes(dados["pessoas"], idioma)
    return saudacao + "."


def _frases_casa(dados: dict[str, Any], idioma: str) -> list[str]:
    """As frases fixas do estado da casa: o que esta aberto (ou tudo fechado) e o alarme armado ou disparado."""
    t = _T[idioma]
    partes = [t["aberto"].format(itens=", ".join(dados["abertos"][:4]))] if dados.get("abertos") else [t["fechado"]]
    if dados.get("alarme") == "triggered":
        partes.append(t["alarme_disparado"])
    elif dados.get("alarme") in _ALARMES_ARMADOS:
        partes.append(t["alarme_armado"])
    return partes


def prefixo_da_hora(dados: dict[str, Any], idioma: str) -> str:
    """O comeco da fala do Bom dia preparado, montado NA HORA de falar: cumprimento com quem esta em casa agora e, com o
    estado da casa ligado, as frases fixas do que esta aberto e do alarme (nunca ficam velhos)."""
    return " ".join([_saudacao(dados, idioma)] + (_frases_casa(dados, idioma) if _casa_ligada() else []))


def juntar_fala(prefixo: str, corpo: str) -> str:
    return " ".join(parte for parte in (prefixo.strip(), corpo.strip()) if parte)


def build_spoken_fallback(
    dados: dict[str, Any],
    previsao: dict[str, Any] | None,
    noticias: list[tuple[str, list[str]]],
    idioma: str,
    *,
    preparo: bool = False,
) -> str:
    """Texto falado montado por regra, usado sem IA ou quando ela falha. `preparo`: so clima e noticias (o Bom dia
    preparado ganha o cumprimento e a casa na hora de falar)."""
    t = _T[idioma]
    partes = [] if preparo else [_saudacao(dados, idioma)]

    if dados.get("clima"):
        c = _clima_resumido(dados, previsao, idioma)
        unidade_agora = " " + c["uf"] + (f", {c['temp2']} {c['n2']}" if c["temp2"] else "")
        frase = t["agora"].format(t=c["temp"], u=unidade_agora, cond=c["cond"]) if c["temp"] else c["cond"]
        extras = []
        if c["hi"] and c["lo"]:
            unidade_maxmin = " " + c["uf"]
            if c["hi2"] and c["lo2"]:
                unidade_maxmin += f", {t['ou']} {c['hi2']} e {c['lo2']} {c['n2']}" if idioma == "pt" else f", {t['ou']} {c['hi2']} and {c['lo2']} {c['n2']}"
            extras.append(t["maxmin"].format(hi=c["hi"], lo=c["lo"], u=unidade_maxmin))
        if c["chuva"]:
            extras.append(t["chuva"].format(p=c["chuva"]))
        if extras:
            frase += "; " + ", ".join(extras)
        partes.append(frase + ".")

    if _casa_ligada() and not preparo:
        partes.extend(_frases_casa(dados, idioma))

    for fonte, titulos in noticias:
        if titulos:
            partes.append(t["noticias_fonte"].format(fonte=fonte, titulos="; ".join(titulos[:2])))
    return " ".join(partes)


_REGRAS_NOTICIAS_PADRAO = (
    "Escolha as noticias por IMPORTANCIA, nao por volume. "
    "Fontes locais (ex.: Orlando): so o que muda o dia de quem mora na regiao -- alertas de "
    "tempo e furacao, obras e mudancas grandes, eventos grandes, economia local; ignore crimes "
    "triviais, acidentes de rotina, prisoes, fofocas e curiosidades. "
    "Fontes dos EUA: as principais noticias nacionais e mundiais do dia; evite mortes, crimes e "
    "tragedias, a nao ser que sejam de impacto nacional ou historico. "
    "Fontes do Brasil: apenas grandes acontecimentos, no nivel de um plantao de telejornal "
    "(decisoes de peso do governo e do Judiciario, eleicoes, grandes desastres, economia); ignore "
    "esporte, celebridades e policial local. "
    "Em qualquer fonte, se nada for realmente relevante, escolha ZERO noticias dela."
)

# Filtro por regra, usado so quando a IA nao esta disponivel (ela julga melhor:
# uma morte de impacto nacional passa, um crime local nao).
_PALAVRAS_PESADAS = re.compile(
    r"\b(kill(?:ed|s|ing)?|dead|dies|died|death|deaths|fatal(?:ly)?|shot|shooting|stab(?:bed|bing)?|"
    r"murder(?:ed)?|homicide|arrest(?:ed|s)?|police|suspect|sentenced|charged|robbery|assault|"
    r"crash(?:es|ed)?|drown(?:ed|ing)?|bod(?:y|ies)|morre|morrem|morreu|morte|mortes|morto|mortos|"
    r"morta|assassin\w*|preso|presa|presos|presas|tiroteio|baleado\w*|acidente\w*|pol[ií]cia|"
    r"esfaque\w*|estupro|roubo|furto|homic[ií]dio\w*|feminic[ií]dio\w*|chacina|v[ií]tima\w*)\b",
    re.IGNORECASE,
)


def filtrar_por_regra(titulos: list[str]) -> list[str]:
    return [t for t in titulos if not _PALAVRAS_PESADAS.search(t)]


def _limites_por_fonte(nomes: list[str]) -> dict[str, int]:
    """Maximo de manchetes mostradas por fonte: as escolhas do centro (lote H2) ou
    IQ_BRIEFING_PICK (2) e, por fonte, IQ_BRIEFING_PICK_MAP ("EUA=3,Brasil=2")."""
    escolhas = _pref("picks")
    if isinstance(escolhas, dict):
        return {nome: max(0, min(6, int(escolhas.get(nome, 1)))) for nome in nomes}
    try:
        base = int(os.getenv("IQ_BRIEFING_PICK", "2") or 2)
    except ValueError:
        base = 2
    mapa: dict[str, int] = {}
    for parte in os.getenv("IQ_BRIEFING_PICK_MAP", "").split(","):
        nome, separador, n = parte.partition("=")
        if separador and n.strip().isdigit():
            mapa[nome.strip().lower()] = int(n)
    return {nome: max(0, min(6, mapa.get(nome.lower(), base))) for nome in nomes}


def _aplicar_selecao(
    escolhas: Any,
    candidatas: list[tuple[str, list[str]]],
    limites: dict[str, int],
) -> list[tuple[str, list[str]]] | None:
    """Traduz os indices devolvidos pela IA (`picks` do centro: {"source", "indices"}) nos titulos escolhidos. Indice
    invalido, repetido ou de fonte desconhecida e ignorado. None se a IA nao
    devolveu uma selecao utilizavel (quem chama usa o filtro por regra)."""
    if not isinstance(escolhas, list):
        return None
    por_nome = {nome.lower(): (nome, titulos) for nome, titulos in candidatas}
    selecionados: dict[str, list[str]] = {nome: [] for nome, _ in candidatas}
    for item in escolhas:
        if not isinstance(item, dict):
            continue
        alvo = por_nome.get(str(item.get("source", item.get("fonte", ""))).strip().lower())
        indices = item.get("indices")
        if alvo is None or not isinstance(indices, list):
            continue
        nome, titulos = alvo
        for i in indices:
            if isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(titulos):
                titulo = titulos[i]
                if titulo not in selecionados[nome] and len(selecionados[nome]) < limites.get(nome, 2):
                    selecionados[nome].append(titulo)
    return [(nome, selecionados[nome]) for nome, _ in candidatas]


# A IA do Bom dia fica no centro (lote A5): __main__ registra o Center do add-on (usar_centro); sem ele, ou com a casa
# nao pareada, vale o texto por regra.
_CENTRO: Any | None = None
_LIMITE_PEDIDO = 60_000  # bytes do corpo de briefing-compose (o centro aceita ate 64 KiB)
_MAX_FALA = 4000  # caracteres: a fala do centro ja vem curta (<= 1,5 x max_words); isto so protege o TTS


def usar_centro(cliente: Any | None) -> None:
    """O objeto que escreve a fala: `cliente.compose(pedido) -> {"text", "picks", ...}` (levanta erro se nao der) e
    `cliente.paired()`. None desliga a IA."""
    global _CENTRO
    _CENTRO = cliente


def _ai_client() -> Any | None:
    """O centro (Center), so se a casa estiver pareada; None = texto por regra."""
    cliente = _CENTRO
    try:
        return cliente if cliente is not None and cliente.paired() else None
    except Exception:
        return None


def _alarme_dito(estado: str | None, idioma: str) -> str | None:
    """O estado do alarme como a fala diria ("desarmado", "armado", "disparado"); None sem alarme."""
    if not estado:
        return None
    t = _T[idioma]
    if estado == "triggered":
        return t["disparado"]
    if estado in _ALARMES_ARMADOS:
        return t["armado"]
    if estado == "disarmed":
        return t["desarmado"]
    return str(estado)[:40]


def _regras_e_palavras(idioma: str) -> tuple[str, int]:
    """O criterio de importancia (as regras do centro/.env, ou o padrao, mais o total pedido) e o maximo de palavras."""
    t = _T[idioma]
    try:
        palavras = int(_pref("max_words") or os.getenv("IQ_BRIEFING_MAX_WORDS", "") or t["palavras"])
    except ValueError:
        palavras = t["palavras"]
    regras = (_pref("rules") or os.getenv("IQ_BRIEFING_NEWS_RULES", "") or "").strip() or _REGRAS_NOTICIAS_PADRAO
    total = _total()
    extra = (
        f" No total, somando todas as fontes, escolha entre {total[0]} e {total[1]} noticias"
        " (menos, se nao houver o que valha)."
    ) if total else ""
    return regras[: 2000 - len(extra)] + extra, max(40, min(300, palavras))


def pedido_ia(
    dados: dict[str, Any],
    previsao: dict[str, Any] | None,
    candidatas: list[tuple[str, list[str]]],
    idioma: str,
    limites: dict[str, int],
    *,
    preparo: bool = False,
) -> dict[str, Any]:
    """O corpo de POST briefing-compose (contrato v2, lote A5): so dados, nunca instrucao. Clima com as duas unidades quando
    houver; aberto e alarme so com o estado da casa ligado; manchetes candidatas por fonte (ate 20 fontes, 30 titulos de
    ate 300 caracteres) com o limite de cada uma; fonte sem titulo ou com limite 0 nao vai. Acima de ~60 KB, saem os
    ultimos titulos das fontes mais longas (os indices continuam valendo: so o fim da lista sai). `preparo` (o Bom dia
    preparado antes): sem nomes e sem a casa, que entram na hora de falar."""
    casa = _casa_ligada() and not preparo
    clima = None
    if dados.get("clima"):
        c = _clima_resumido(dados, previsao, idioma)
        clima = {
            "temp": c["temp"] or None,
            "unit": _letra_da_unidade(c["u"]) or None,
            "temp2": c["temp2"] or None,
            "unit2": (_letra_da_unidade(c["u2"]) or None) if c["temp2"] else None,
            "condition": c["cond"],
            "high": c["hi"] or None,
            "low": c["lo"] or None,
            "rain": c["chuva"] or None,
        }
    regras, palavras = _regras_e_palavras(idioma)
    pedido: dict[str, Any] = {
        "language": idioma,
        "max_words": palavras,
        "rules": regras,
        "house_state": casa,
        "facts": {
            "names": [] if preparo else [str(n) for n in (dados.get("pessoas") or [])][:20],
            "weather": clima,
            "open": [str(a) for a in (dados.get("abertos") or [])][:20] if casa else [],
            "alarm": _alarme_dito(dados.get("alarme"), idioma) if casa else None,
        },
        "candidates": [
            {"source": nome, "limit": limites[nome], "titles": [str(t)[:300] for t in titulos[:30]]}
            for nome, titulos in candidatas
            if titulos and limites.get(nome)
        ][:20],
    }
    while pedido["candidates"] and len(json.dumps(pedido)) > _LIMITE_PEDIDO:
        maior = max(pedido["candidates"], key=lambda fonte: len(fonte["titles"]))
        maior["titles"].pop()
        if not maior["titles"]:
            pedido["candidates"].remove(maior)
    return pedido


_SAUDACAO_NO_COMECO = re.compile(r"^\s*(?:bom dia|good morning)\b[\s,;:!.\-]*", re.IGNORECASE)


def _sem_saudacao(texto: str) -> str:
    """O texto da IA para o Bom dia preparado sem o "Bom dia" do comeco (o cumprimento com os nomes entra na hora)."""
    resto = _SAUDACAO_NO_COMECO.sub("", texto, count=1).strip()
    return resto[:1].upper() + resto[1:]


def compose(
    dados: dict[str, Any],
    previsao: dict[str, Any] | None,
    candidatas: list[tuple[str, list[str]]],
    idioma: str,
    *,
    client: Any | None = None,
    preparo: bool = False,
) -> tuple[str, list[tuple[str, list[str]]]]:
    """Devolve (fala, noticias escolhidas). Com o centro, a IA de la escolhe as importantes e
    escreve a fala; sem ele (ou com qualquer erro), vale o filtro por regra e o texto por regra.
    `preparo`: a fala sem cumprimento e sem a casa (o Bom dia preparado; prefixo_da_hora completa na hora)."""
    limites = _limites_por_fonte([nome for nome, _ in candidatas])
    por_regra = [(nome, filtrar_por_regra(titulos)[: limites[nome]]) for nome, titulos in candidatas]
    fallback = build_spoken_fallback(dados, previsao, por_regra, idioma, preparo=preparo)
    ativo = client if client is not None else _ai_client()
    if ativo is None:
        return fallback, por_regra
    try:
        pedido = pedido_ia(dados, previsao, candidatas, idioma, limites, preparo=preparo)
        resposta = ativo.compose(pedido)
        texto = str(resposta.get("text") or "").strip() if isinstance(resposta, dict) else ""
        if preparo:
            texto = _sem_saudacao(texto)
        if not texto:
            logger.warning("Bom dia: o centro respondeu sem texto; usando o texto por regra.")
            return fallback, por_regra
        enviadas = {fonte["source"]: len(fonte["titles"]) for fonte in pedido["candidates"]}
        escolhidas = _aplicar_selecao(
            resposta.get("picks"), [(nome, titulos[: enviadas.get(nome, 0)]) for nome, titulos in candidatas], limites
        )
        return texto[:_MAX_FALA], escolhidas if escolhidas is not None else por_regra
    except Exception as erro:  # nunca o pedido nem a resposta no log: so o motivo curto
        motivo = str(getattr(erro, "reason", "") or erro.__class__.__name__)[:40]
        logger.warning("Bom dia: IA pelo centro indisponivel (%s); usando o texto por regra.", motivo)
        return fallback, por_regra


def compose_spoken(
    dados: dict[str, Any],
    previsao: dict[str, Any] | None,
    noticias: list[tuple[str, list[str]]],
    idioma: str,
    *,
    client: Any | None = None,
) -> str:
    """So o texto falado (ver `compose`)."""
    return compose(dados, previsao, noticias, idioma, client=client)[0]


# --------------------------------------------------------------------------
# Orquestracao
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Voz premium num alto-falante (ex.: ElevenLabs tocando no Sonos da sala)
# --------------------------------------------------------------------------


def speaker_config() -> dict[str, Any] | None:
    """Configuracao da voz premium; None se nao estiver configurada."""
    alto_falante = (_pref("speaker") or os.getenv("IQ_BRIEFING_SPEAKER", "")).strip()
    motor = _motor_tts(os.getenv("IQ_BRIEFING_TTS_ENGINE", "").strip())
    if not alto_falante or not motor:
        return None
    voz_pt = os.getenv("IQ_BRIEFING_TTS_VOICE", "").strip()
    try:
        atraso = max(0.0, min(15.0, float(os.getenv("IQ_BRIEFING_SPEAKER_DELAY", "2") or 2)))
    except ValueError:
        atraso = 2.0
    volume = None
    do_centro = _pref("volume")
    bruto = str(do_centro) if isinstance(do_centro, int) else os.getenv("IQ_BRIEFING_SPEAKER_VOLUME", "").strip().replace(",", ".")
    if bruto:
        try:
            v = float(bruto)
            v = v / 100 if v > 1 else v
            if 0 < v <= 1:
                volume = round(v, 2)
        except ValueError:
            volume = None
    try:
        espera = max(0.0, min(30.0, float(os.getenv("IQ_BRIEFING_SPEAKER_WAIT", "8") or 8)))
    except ValueError:
        espera = 8.0
    return {
        "speaker": alto_falante,
        "engine": motor,
        "volume": volume,
        "espera": espera,
        "ocupado": "interromper" if os.getenv("IQ_BRIEFING_SPEAKER_BUSY", "").strip().lower().startswith("interr") else "voice",
        "voz_pt": voz_pt,
        "voz_en": os.getenv("IQ_BRIEFING_TTS_VOICE_EN", "").strip() or voz_pt,
        "atraso": atraso,
        "satellite": os.getenv("IQ_BRIEFING_SATELLITE", "").strip(),
    }


def satellite() -> str:
    """O assist_satellite de reserva (opcao `satellite` do add-on), ou ""."""
    return os.getenv("IQ_BRIEFING_SATELLITE", "").strip()


def speaker_ready(cfg: dict[str, Any], estados: list[dict[str, Any]]) -> bool:
    """O alto-falante e o motor de voz existem e nao estao indisponiveis?
    Checado com os estados que o resumo ja leu, sem chamada extra."""
    por_id = {str(e.get("entity_id")): str(e.get("state")) for e in estados}
    return all(
        por_id.get(entidade, "unavailable") not in ("unavailable", "")
        for entidade in (cfg["speaker"], cfg["engine"])
    )


def speaker_busy(cfg: dict[str, Any], estados: list[dict[str, Any]]) -> bool:
    """O alto-falante esta tocando algo agora (TV pela barra, musica)?"""
    for e in estados:
        if str(e.get("entity_id")) == cfg["speaker"]:
            return str(e.get("state")) in ("playing", "buffering")
    return False


def _esperar_alto_falante(
    cfg: dict[str, Any],
    estados: list[dict[str, Any]],
    estados_fn: Callable[[], list[dict[str, Any]]],
    sleep_fn: Callable[[float], None],
) -> list[dict[str, Any]]:
    """O Sonos oscila (cai por alguns segundos e volta). Antes de desistir dele,
    relê os estados a cada 2 s por ate `espera` segundos."""
    esperado = 0.0
    while esperado < cfg["espera"]:
        sleep_fn(2.0)
        esperado += 2.0
        try:
            novos = estados_fn()
        except Exception:
            continue
        if novos and speaker_ready(cfg, novos):
            return novos
    return estados


def speak_on_speaker(fala: str, idioma: str, cfg: dict[str, Any]) -> bool:
    """tts.speak do HA: gera a voz e toca no alto-falante."""
    if not HA_URL or not HA_TOKEN:
        return False
    corpo: dict[str, Any] = {
        "entity_id": cfg["engine"],
        "media_player_entity_id": cfg["speaker"],
        "message": fala,
        "language": idioma,
    }
    voz = cfg["voz_en"] if idioma == "en" else cfg["voz_pt"]
    if voz:
        corpo["options"] = {"voice": voz}
    try:
        resposta = requests.post(
            f"{HA_URL}/api/services/tts/speak", headers=_ha_headers(), json=corpo, timeout=30
        )
        resposta.raise_for_status()
        return True
    except requests.RequestException:
        logger.warning("Resumo: nao consegui tocar a voz premium no alto-falante.", exc_info=True)
        return False


def announce_on_satellite(fala: str, satelite: str) -> bool:
    """Reserva: o aparelho de voz fala o resumo (voz do pipeline dele)."""
    if not HA_URL or not HA_TOKEN or not satelite:
        return False
    try:
        resposta = requests.post(
            f"{HA_URL}/api/services/assist_satellite/announce",
            headers=_ha_headers(),
            json={"entity_id": satelite, "message": fala},
            timeout=30,
        )
        resposta.raise_for_status()
        return True
    except requests.RequestException:
        logger.warning("Resumo: a reserva (anuncio no satelite) tambem falhou.", exc_info=True)
        return False


def get_speaker_volume(entidade: str) -> float | None:
    """Volume atual do alto-falante (0 a 1); None se nao der para ler."""
    if not HA_URL or not HA_TOKEN:
        return None
    try:
        resposta = requests.get(f"{HA_URL}/api/states/{entidade}", headers=_ha_headers(), timeout=8)
        resposta.raise_for_status()
        valor = (resposta.json().get("attributes") or {}).get("volume_level")
        return float(valor) if valor is not None else None
    except (requests.RequestException, TypeError, ValueError):
        return None


def set_speaker_volume(entidade: str, nivel: float) -> bool:
    if not HA_URL or not HA_TOKEN:
        return False
    try:
        resposta = requests.post(
            f"{HA_URL}/api/services/media_player/volume_set",
            headers=_ha_headers(),
            json={"entity_id": entidade, "volume_level": nivel},
            timeout=8,
        )
        resposta.raise_for_status()
        return True
    except requests.RequestException:
        logger.warning("Resumo: nao consegui ajustar o volume do alto-falante.", exc_info=True)
        return False


def _estimar_duracao(fala: str) -> float:
    """Duracao estimada da fala em segundos (~12 caracteres por segundo, mais uma
    margem). O anuncio de um alto-falante Sonos NAO aparece como "tocando" para o HA,
    entao nao da para esperar pelo fim observando o estado: o volume voltou depois de
    16 s, no meio de uma fala de ~40 s (2026-10-08)."""
    return max(6.0, len(fala) / 12.0) + 4.0


def wait_speaker_idle(entidade: str, minimo: float = 0.0, *, maximo: float = 150.0) -> None:
    """Espera a fala terminar: primeiro o tempo estimado (`minimo`) e, se o player
    ainda estiver tocando depois disso, ate ele parar."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < min(minimo, maximo):
        time.sleep(0.5)
    if HA_URL and HA_TOKEN:

        def estado() -> str:
            try:
                resposta = requests.get(f"{HA_URL}/api/states/{entidade}", headers=_ha_headers(), timeout=8)
                return str(resposta.json().get("state") or "")
            except (requests.RequestException, ValueError):
                return ""

        while time.monotonic() - t0 < maximo and estado() in ("playing", "buffering"):
            time.sleep(1.0)
    time.sleep(1.0)


def _entregar_no_alto_falante(
    fala: str,
    idioma: str,
    cfg: dict[str, Any],
    speak_fn: Callable[[str, str, dict[str, Any]], bool],
    announce_fn: Callable[[str, str], bool],
    sleep_fn: Callable[[float], None],
    get_volume_fn: Callable[[str], float | None] | None = None,
    set_volume_fn: Callable[[str, float], bool] | None = None,
    wait_fn: Callable[[str, float], None] | None = None,
) -> None:
    """Espera o aparelho de voz terminar o "Um instante." e toca o resumo. Se
    nao der, cai na reserva (satelite) em vez de ficar em silencio.

    Com `volume` configurado, o alto-falante fala nesse volume e depois volta ao
    que estava -- mas so se ninguem mexeu no volume durante a fala, e nunca se o
    volume anterior nao pode ser lido (melhor nao mexer do que deixar errado)."""
    sleep_fn(cfg["atraso"])
    get_volume = get_volume_fn or get_speaker_volume
    set_volume = set_volume_fn or set_speaker_volume
    alvo = cfg.get("volume")
    anterior = None
    if alvo is not None:
        try:
            lido = get_volume(cfg["speaker"])
            if lido is not None and abs(lido - alvo) >= 0.01:
                anterior = lido
                set_volume(cfg["speaker"], alvo)
        except Exception:
            logger.warning("Resumo: erro ao ajustar o volume.", exc_info=True)
            anterior = None
    ok = False
    try:
        ok = speak_fn(fala, idioma, cfg)
    except Exception:
        logger.warning("Resumo: erro ao tocar no alto-falante.", exc_info=True)
    if anterior is not None:
        try:
            if ok:
                (wait_fn or wait_speaker_idle)(cfg["speaker"], _estimar_duracao(fala))
            atual = get_volume(cfg["speaker"])
            if atual is not None and abs(atual - alvo) < 0.02:
                set_volume(cfg["speaker"], anterior)
        except Exception:
            logger.warning("Resumo: erro ao restaurar o volume.", exc_info=True)
    if not ok and cfg.get("satellite"):
        try:
            announce_fn(fala, cfg["satellite"])
        except Exception:
            logger.warning("Resumo: erro na reserva do satelite.", exc_info=True)


def _dados_da_casa(estados: list[dict[str, Any]]) -> dict[str, Any]:
    ignorar = {x.strip().lower() for x in os.getenv("IQ_BRIEFING_IGNORAR", "").split(",") if x.strip()}
    return collect_house(
        estados,
        os.getenv("IQ_BRIEFING_WEATHER_ENTITY") or None,
        ignorar or None,
        os.getenv("IQ_BRIEFING_TEMP_SENSOR", "").strip() or None,
    )


def _compor(
    idioma: str,
    estados_fn: Callable[[], list[dict[str, Any]]],
    fetch_forecast_fn: Callable[[str], dict[str, Any] | None] | None,
    fetch_feed_fn: Callable[[str, int], list[str]] | None,
    client: Any | None,
    feeds: list[tuple[str, str]] | None,
    *,
    preparo: bool = False,
) -> tuple[str, list[tuple[str, list[str]]], dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]] | None:
    """Coleta (estados, previsao, RSS) e escreve a fala; None se o HA nao respondeu. Usado pelo bom dia, pelo "Testar" e
    pelo Bom dia preparado (`preparo`)."""
    previsao_fn = fetch_forecast_fn or fetch_forecast
    feed_fn = fetch_feed_fn or (lambda url, n: fetch_feed(url, n))
    fontes = feeds if feeds is not None else configured_feeds()
    itens = max(3, min(30, int(os.getenv("IQ_BRIEFING_FEED_ITEMS", "12") or 12)))

    try:
        estados = estados_fn()
    except Exception:
        logger.warning("Resumo: nao consegui ler os estados do HA.", exc_info=True)
        estados = []
    if not estados:
        return None

    dados = _dados_da_casa(estados)
    if not _clima_ligado():  # lote H2: "Falar o clima" desligado (nem fala, nem cartao, nem previsao)
        dados["clima"] = None
        dados["entidade_clima"] = None

    with ThreadPoolExecutor(max_workers=4) as pool:
        f_previsao = pool.submit(previsao_fn, dados["entidade_clima"]) if dados.get("entidade_clima") else None
        f_feeds = [(nome, pool.submit(feed_fn, url, itens)) for nome, url in fontes]
        try:
            previsao = f_previsao.result(timeout=12) if f_previsao else None
        except Exception:
            previsao = None
        candidatas: dict[str, list[str]] = {}
        for nome, futuro in f_feeds:
            try:
                titulos = futuro.result(timeout=12)
            except Exception:
                titulos = []
            # fontes com o mesmo nome se juntam (ex.: duas fontes dos EUA)
            acumulado = candidatas.setdefault(nome, [])
            acumulado.extend(t for t in titulos if t not in acumulado)

    fala, noticias = compose(dados, previsao, list(candidatas.items()), idioma, client=client, preparo=preparo)
    return fala, noticias, dados, previsao, estados


# --------------------------------------------------------------------------
# Bom dia preparado antes (lote A5, ready.py guarda; schedule.Preparer decide quando)
# --------------------------------------------------------------------------


def idioma_automatico() -> str:
    """O idioma da fala automatica: o salvo (aba ou centro), ou portugues."""
    return _pref("language") if _pref("language") in _T else "pt"


def chave_preparo(idioma: str) -> str:
    """O que, se mudar, invalida o Bom dia preparado: as preferencias (menos o horario), as opcoes IQ_BRIEFING_* e o idioma."""
    import hashlib

    prefs = {k: v for k, v in (ler_prefs() or {}).items() if k != "schedule"}
    env = {k: v for k, v in os.environ.items() if k.startswith("IQ_BRIEFING_") and not k.startswith("IQ_BRIEFING_PREPARE")}
    bruto = json.dumps({"prefs": prefs, "env": env, "language": idioma}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(bruto.encode()).hexdigest()[:32]


def preparar(
    idioma: str,
    *,
    fetch_states_fn: Callable[[], list[dict[str, Any]]] | None = None,
    fetch_forecast_fn: Callable[[str], dict[str, Any] | None] | None = None,
    fetch_feed_fn: Callable[[str, int], list[str]] | None = None,
    client: Any | None = None,
) -> tuple[dict[str, Any], str] | None:
    """O Bom dia preparado: (pronto, prefixo agora). `pronto` = {text, cards, weather_card, language, key} sem cumprimento,
    sem nomes e sem a casa (o texto pela IA do centro, ou por regra); `prefixo` e o comeco que a fala teria AGORA (so para
    adiantar o audio; nao e guardado). None se o HA nao respondeu."""
    composto = _compor(idioma, fetch_states_fn or fetch_states, fetch_forecast_fn, fetch_feed_fn, client, None, preparo=True)
    if composto is None:
        return None
    corpo, noticias, dados, previsao, _ = composto
    pronto = {
        "text": corpo,
        "cards": build_cards(dados, previsao, noticias, idioma, casa=False),
        "weather_card": bool(dados.get("clima")),
        "language": idioma,
        "key": chave_preparo(idioma),
    }
    return pronto, prefixo_da_hora(dados, idioma)


def precache_tts(fala: str, idioma: str, cfg: dict[str, Any]) -> bool:
    """Melhor esforco: pede ao HA para gerar e guardar em cache o audio desta fala (POST /api/tts_get_url com o mesmo motor,
    mensagem, idioma e voz de speak_on_speaker) e baixa o audio uma vez, para o tts.speak da hora sair do cache. Nada toca
    agora. Endpoint ausente ou erro: ignorado (a voz e gerada na hora, como antes)."""
    if not HA_URL or not HA_TOKEN or not fala:
        return False
    corpo: dict[str, Any] = {"engine_id": cfg["engine"], "message": fala, "language": idioma}
    voz = cfg["voz_en"] if idioma == "en" else cfg["voz_pt"]
    if voz:
        corpo["options"] = {"voice": voz}
    try:
        resposta = requests.post(f"{HA_URL}/api/tts_get_url", headers=_ha_headers(), json=corpo, timeout=60)
        resposta.raise_for_status()
        caminho = str((resposta.json() or {}).get("path") or "")
        if caminho.startswith("/api/tts_proxy/"):
            with requests.get(f"{HA_URL}{caminho}", headers=_ha_headers(), timeout=60, stream=True) as audio:
                audio.raise_for_status()
                for _ in audio.iter_content(65536):
                    pass
        return True
    except (requests.RequestException, ValueError, AttributeError):
        logger.info("Bom dia: o Home Assistant nao adiantou o audio da voz (ele sera gerado na hora).")
        return False


def preview(
    prefs: dict[str, Any],
    idioma: str | None = None,
    *,
    fetch_states_fn: Callable[[], list[dict[str, Any]]] | None = None,
    fetch_forecast_fn: Callable[[str], dict[str, Any] | None] | None = None,
    fetch_feed_fn: Callable[[str, int], list[str]] | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """POST /v1/briefing-preview ("Testar" no centro): o texto com ESTAS preferencias, sem publicar cartao, sem falar
    e sem gravar nada. ValueError se as preferencias forem invalidas."""
    inicio = time.monotonic()
    with usando_prefs(prefs) as limpas:
        lingua = idioma if idioma in _T else limpas["language"]
        composto = _compor(lingua, fetch_states_fn or fetch_states, fetch_forecast_fn, fetch_feed_fn, client, None)
    fala = composto[0] if composto else _T[lingua]["falha_casa"]
    return {
        "text": fala,
        "words": len(fala.split()),
        "speech_seconds": round(_estimar_duracao(fala) - 4.0),
        "elapsed_ms": int((time.monotonic() - inicio) * 1000),
    }


def handle(
    texto: str,
    *,
    fetch_states_fn: Callable[[], list[dict[str, Any]]] | None = None,
    fetch_forecast_fn: Callable[[str], dict[str, Any] | None] | None = None,
    fetch_feed_fn: Callable[[str, int], list[str]] | None = None,
    publish_fn: Callable[[list[dict[str, Any]], int], bool] | None = None,
    client: Any | None = None,
    feeds: list[tuple[str, str]] | None = None,
    speak_fn: Callable[[str, str, dict[str, Any]], bool] | None = None,
    announce_fn: Callable[[str, str], bool] | None = None,
    spawn_fn: Callable[[Callable[[], None]], None] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    get_volume_fn: Callable[[str], float | None] | None = None,
    set_volume_fn: Callable[[str, float], bool] | None = None,
    wait_fn: Callable[[str, float], None] | None = None,
    idioma_pedido: str | None = None,
    pronto: dict[str, Any] | None = None,
) -> str | None:
    """Se `texto` pede o resumo, devolve a fala (e publica os cartoes no
    painel). Se nao pede, devolve None e quem chamou segue o fluxo normal.
    `idioma_pedido` ("pt"/"en", ex.: o `language` do evento iq_bom_dia) vale no lugar do idioma salvo.
    `pronto` (o Bom dia preparado, ready.fresh): no pedido automatico, a fala e o prefixo da hora (cumprimento e casa
    com os estados de agora) + o texto pronto, sem RSS nem IA; idioma diferente = compoe na hora."""
    idioma = detect_briefing(texto)
    if idioma is None:
        return None
    if idioma_pedido in _T:
        idioma = idioma_pedido
    elif "automatico" in _normalizar(texto).split() and _pref("language") in _T:
        idioma = _pref("language")  # lote H2: o pedido automatico fala no idioma escolhido no centro

    estados_fn = fetch_states_fn or fetch_states
    publicar = publish_fn or publish_cards
    duracao = max(10, min(300, int(os.getenv("IQ_BRIEFING_CARD_SECONDS", "40") or 40)))

    automatico = "automatico" in _normalizar(texto).split()
    if automatico and isinstance(pronto, dict) and pronto.get("language") == idioma and isinstance(pronto.get("text"), str):
        try:
            estados = estados_fn()
        except Exception:
            logger.warning("Resumo: nao consegui ler os estados do HA.", exc_info=True)
            estados = []
        if not estados:
            return _T[idioma]["falha_casa"]
        dados = _dados_da_casa(estados)
        fala = juntar_fala(prefixo_da_hora(dados, idioma), pronto["text"])
        cartoes = [dict(c) for c in pronto.get("cards") or [] if isinstance(c, dict)]
        if _casa_ligada():
            cartoes.insert(1 if pronto.get("weather_card") and cartoes else 0, _cartao_casa(dados, idioma))
    else:
        composto = _compor(idioma, estados_fn, fetch_forecast_fn, fetch_feed_fn, client, feeds)
        if composto is None:
            return _T[idioma]["falha_casa"]
        fala, noticias, dados, previsao, estados = composto
        cartoes = build_cards(dados, previsao, noticias, idioma)
    try:
        publicar(cartoes, duracao)
    except Exception:
        logger.warning("Resumo: falha ao publicar cartoes.", exc_info=True)

    # Voz premium num alto-falante: o aparelho de voz so responde "Um instante."
    # e o resumo inteiro sai no alto-falante escolhido.
    cfg = speaker_config()
    sono = sleep_fn or time.sleep
    if cfg is not None:
        # estado do alto-falante NA HORA de falar (o resumo leva alguns segundos para
        # ficar pronto, e a TV pode ter ligado ou desligado nesse meio tempo)
        try:
            recentes = estados_fn()
            if recentes:
                estados = recentes
        except Exception:
            pass
    if cfg is not None and not speaker_ready(cfg, estados):
        estados = _esperar_alto_falante(cfg, estados, estados_fn, sono)
    # Tocando TV/musica: nao interrompe. Cai no mesmo caminho do alto-falante
    # indisponivel -- pedido de voz devolve o texto ao aparelho de voz; pedido
    # automatico fala pelo satelite.
    ocupado = (
        cfg is not None
        and cfg["ocupado"] == "voice"
        and speaker_ready(cfg, estados)
        and speaker_busy(cfg, estados)
    )
    if ocupado:
        logger.info("Resumo: o alto-falante esta tocando; falando pelo aparelho de voz.")
    if cfg is not None and speaker_ready(cfg, estados) and not ocupado:
        if automatico:
            cfg = {**cfg, "atraso": 0.0}  # nao ha "Um instante." para esperar
        tarefa = lambda: _entregar_no_alto_falante(  # noqa: E731
            fala,
            idioma,
            cfg,
            speak_fn or speak_on_speaker,
            announce_fn or announce_on_satellite,
            sleep_fn or time.sleep,
            get_volume_fn,
            set_volume_fn,
            wait_fn,
        )
        (spawn_fn or (lambda f: threading.Thread(target=f, daemon=True).start()))(tarefa)
        return _T[idioma]["ack"]
    if automatico:
        # Sem aparelho de voz ligado ao pedido, devolver o texto nao fala nada:
        # o resumo vai direto ao satelite (voz do pipeline dele).
        satelite = (cfg or {}).get("satellite") or os.getenv("IQ_BRIEFING_SATELLITE", "").strip()
        if satelite:
            anunciar = announce_fn or announce_on_satellite
            tarefa = lambda: anunciar(fala, satelite)  # noqa: E731
            (spawn_fn or (lambda f: threading.Thread(target=f, daemon=True).start()))(tarefa)
        return _T[idioma]["ack"]
    return fala
