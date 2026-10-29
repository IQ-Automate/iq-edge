"""The add-on's tab in Home Assistant (ingress, port 8099): "Estado" (paired or not, last contact, version, the center's AI for the Bom
dia, the Bom dia prepared ahead, Home Assistant's event iq_bom_dia, Parear / Desparear) and
"Bom dia" (sources, how many, total, words, rules, speaker among the home's media_player, volume, voice engine, language, unit, the
automatic speech's time and days; "Testar" shows the text, "Salvar" keeps it here and sends it to the platform, "Falar agora").

Only the Supervisor's ingress proxy (172.30.32.2) may connect (any other address gets 403): Home Assistant already signed the person
in and tells who it is (X-Remote-User-*; trusted only because of that). Plain HTML, no script, relative links under X-Ingress-Path,
forms POST with an anti-CSRF token per Home Assistant user. Standard library only (http.server, one thread per request)."""
import hashlib
import hmac
import html
import logging
import re
import secrets
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from . import briefing, prefs, ready, relay, schedule, settings

logger = logging.getLogger('iq_edge.web')
INGRESS = re.compile(r'/api/hassio_ingress/[A-Za-z0-9_-]{1,128}')
SOURCE_LINE = re.compile(r'^\s*(.+?)\s*[=|]\s*(https?://\S+)\s*$')
PICK_LINE = re.compile(r'^\s*(.+?)\s*[=|:]\s*(\d{1,2})\s*$')
MAX_FORM = 64 * 1024
DAYS = (('seg', 'Mon'), ('ter', 'Tue'), ('qua', 'Wed'), ('qui', 'Thu'), ('sex', 'Fri'), ('sáb', 'Sat'), ('dom', 'Sun'))
UNITS = (('language', 'pelo idioma', 'by language'), ('C', '°C', '°C'), ('F', '°F', '°F'), ('FC', '°F e °C', '°F and °C'))
ENGINES = (('elevenlabs', 'ElevenLabs'), ('google', 'Google'))
CSP = "default-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'; frame-ancestors 'self'; base-uri 'none'"
FIELDS = {
    'sources': ('Fontes: de 1 a 20 linhas "Nome = endereço http(s)"', 'Sources: 1 to 20 lines "Name = http(s) address"'),
    'picks': ('Quantas por fonte: de 0 a 6', 'How many per source: 0 to 6'),
    'total_min': ('Total de notícias: de 1 a 20, o menor primeiro', 'Total of news: 1 to 20, the smaller first'),
    'total_max': ('Total de notícias: de 1 a 20, o menor primeiro', 'Total of news: 1 to 20, the smaller first'),
    'max_words': ('Máximo de palavras: de 40 a 300', 'Maximum words: 40 to 300'),
    'rules': ('Regras com até 2000 caracteres', 'Rules up to 2000 characters'),
    'speaker': ('Alto-falante: um media_player da casa', 'Speaker: a media_player of the home'),
    'volume': ('Volume: de 0 a 100', 'Volume: 0 to 100'),
    'tts_engine': ('Motor de voz inválido', 'Invalid voice engine'),
    'schedule': ('Fala automática: horário HH:MM', 'Automatic speech: time HH:MM'),
}
STYLE = """
:root{--bg:#f7f4ee;--card:#fffdf9;--text:#2b2620;--muted:#6f675c;--line:#e4ddd0;--accent:#8a5a1f;--ok:#2f6b3f;--warn:#9a5b00}
@media (prefers-color-scheme:dark){:root{--bg:#171410;--card:#221e19;--text:#f1ebe2;--muted:#b4aa9b;--line:#3a332a;--accent:#d7a65f;--ok:#7fc18f;--warn:#e0a94f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:720px;margin:0 auto;padding:16px}nav{display:flex;gap:8px;margin-bottom:16px}nav a{padding:8px 16px;border-radius:8px;
color:var(--text);text-decoration:none;border:1px solid var(--line);min-height:44px;display:inline-flex;align-items:center}
nav a.on{background:var(--accent);border-color:var(--accent);color:var(--bg)}section{background:var(--card);border:1px solid var(--line);
border-radius:12px;padding:16px;margin-bottom:16px}h1{font-size:20px;margin:0 0 4px}h2{font-size:17px;margin:0 0 8px}.muted{color:var(--muted);font-size:13px}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;border:1px solid currentColor}.ok{color:var(--ok)}.warn{color:var(--warn)}
label{display:block;margin:12px 0 4px;font-size:13px;color:var(--muted)}input,select,textarea{width:100%;font:inherit;font-size:16px;padding:8px 12px;
border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--text);min-height:44px}textarea{min-height:96px}
.check{display:flex;align-items:center;gap:8px;margin:8px 0;color:var(--text);font-size:15px}.check input{width:20px;min-height:20px;height:20px}
.days{display:flex;flex-wrap:wrap;gap:8px}.days .check{margin:0;padding:8px 12px;border:1px solid var(--line);border-radius:8px;min-height:44px}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px}.actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}
button,.button{font:inherit;font-weight:600;padding:8px 16px;border-radius:8px;min-height:44px;border:1px solid var(--accent);background:transparent;
color:var(--accent);cursor:pointer;text-decoration:none;display:inline-flex;align-items:center}button.primary{background:var(--accent);color:var(--bg)}
button.danger{border-color:var(--warn);color:var(--warn)}.note{padding:12px;border-radius:8px;border:1px solid var(--line);margin-bottom:16px}
.text{white-space:pre-wrap}.code{font-family:Consolas,monospace;font-size:20px;letter-spacing:4px}dl{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;margin:0}
dt{color:var(--muted);font-size:13px}dd{margin:0}
"""


def _e(value):
    return html.escape(str(value if value is not None else ''), quote=True)


def _hhmm(iso, zone_name=''):
    """hh:mm of an ISO moment in the home's time zone (the machine's when it is not known); '—' when it cannot be read."""
    try:
        moment = datetime.fromisoformat(str(iso))
    except ValueError:
        return '—'
    moment = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    zone = schedule._zone(zone_name)
    return (moment.astimezone(zone) if zone else moment.astimezone()).strftime('%H:%M')


def _ago(iso, pt):
    try:
        moment = datetime.fromisoformat(str(iso))
    except ValueError:
        return '—'
    minutes = max(0, int((datetime.now(timezone.utc) - (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc))).total_seconds() // 60))
    if minutes < 1:
        return 'agora' if pt else 'just now'
    if minutes < 60:
        return f'há {minutes} min' if pt else f'{minutes} min ago'
    hours = minutes // 60
    return (f'há {hours} h' if pt else f'{hours} h ago') if hours < 48 else (f'há {hours // 24} dias' if pt else f'{hours // 24} days ago')


def parse_form(form, current):
    """The Bom dia form → prefs (validated by briefing.validar_prefs, which raises ValueError(<field>))."""
    one = lambda name, default='': (form.get(name) or [default])[0]  # noqa: E731
    sources, names = [], []
    for line in one('sources').splitlines():
        if not line.strip():
            continue
        match = SOURCE_LINE.match(line)
        if not match:
            raise ValueError('sources')
        sources.append({'name': ' '.join(match.group(1).split()), 'url': match.group(2)})
        names.append(' '.join(match.group(1).split()))
    picks = {}
    for line in one('picks').splitlines():
        if line.strip():
            match = PICK_LINE.match(line)
            if not match:
                raise ValueError('picks')
            picks[' '.join(match.group(1).split())] = int(match.group(2))
    number = lambda name: one(name).strip() or None  # noqa: E731
    values = {'house_state': one('house_state') == 'on', 'weather': one('weather') == 'on', 'sources': sources,
              'picks': {n: picks.get(n, current.get('picks', {}).get(n, 1)) for n in dict.fromkeys(names)},
              'total_min': number('total_min'), 'total_max': number('total_max'), 'max_words': number('max_words'), 'rules': one('rules'),
              'speaker': one('speaker').strip(), 'volume': number('volume'), 'tts_engine': one('tts_engine').strip(),
              'language': one('language', 'pt'), 'temp_unit': one('temp_unit', 'language'),
              'schedule': {'time': one('time', '07:00').strip()[:5], 'days': [d for d in range(7) if one(f'day{d}') == 'on']}}
    return briefing.validar_prefs(values)


class App:
    """What the pages need: the center client (status, pair, unpair, send_prefs, the AI's last answer), the listener of Home
    Assistant's event iq_bom_dia (None outside Home Assistant) and a per-process secret for the CSRF tokens."""

    def __init__(self, center, listener=None):
        self.center, self.listener = center, listener
        self.secret = secrets.token_bytes(32)

    def csrf(self, user_id):
        return hmac.new(self.secret, (user_id or '-').encode(), hashlib.sha256).hexdigest()[:40]


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'IQEdge'
        sys_version = ''

        def log_message(self, *args):  # nothing of the request (forms carry codes and texts) goes to the log
            pass

        # ---- helpers ----
        def pt(self):
            return not (self.headers.get('Accept-Language') or '').lower().startswith('en')

        def t(self, pt, en):
            return pt if self.pt() else en

        def base(self):
            path = (self.headers.get('X-Ingress-Path') or '').strip()
            return path if INGRESS.fullmatch(path) else '.'

        def header(self, name):
            value = self.headers.get(name) or ''
            try:  # http.server reads headers as latin-1; Home Assistant sends UTF-8 (a name with accents)
                return value.encode('latin-1').decode('utf-8').strip()
            except (UnicodeEncodeError, UnicodeDecodeError):
                return value.strip()

        def user(self):
            return {'id': self.header('X-Remote-User-Id')[:80],
                    'name': (self.header('X-Remote-User-Display-Name') or self.header('X-Remote-User-Name'))[:60]}

        def allowed(self):
            return self.client_address[0] in settings.ingress_peers()

        def send(self, status, body, content_type='text/html; charset=utf-8'):
            payload = body.encode('utf-8')
            self.send_response(status)
            for key, value in (('Content-Type', content_type), ('Content-Length', str(len(payload))), ('Cache-Control', 'no-store'),
                               ('X-Content-Type-Options', 'nosniff'), ('Referrer-Policy', 'same-origin'), ('Content-Security-Policy', CSP)):
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(payload)

        def page(self, title, active, body, status=200):
            base = self.base()
            nav = (f'<nav><a href="{_e(base)}/"{" class=on" if active == "estado" else ""}>{self.t("Estado", "Status")}</a>'
                   f'<a href="{_e(base)}/bom-dia"{" class=on" if active == "bomdia" else ""}>{self.t("Bom dia", "Good morning")}</a></nav>')
            lang = 'pt-BR' if self.pt() else 'en'
            return self.send(status, f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" '
                                     f'content="width=device-width,initial-scale=1"><title>{_e(title)} · IQ</title>'
                                     f'<link rel="stylesheet" href="{_e(base)}/style.css"></head><body><main>{nav}{body}'
                                     f'<p class="muted">IQ Edge {settings.VERSION} · {_e(settings.arch())}</p></main></body></html>')

        def token_field(self):
            return f'<input type="hidden" name="csrf" value="{_e(app.csrf(self.user()["id"]))}">'

        def form_data(self):
            try:
                size = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                size = -1
            if not 0 <= size <= MAX_FORM:
                return None
            raw = self.rfile.read(size).decode('utf-8', 'replace')
            form = parse_qs(raw, keep_blank_values=True, max_num_fields=200)
            sent = (form.get('csrf') or [''])[0]
            if not hmac.compare_digest(sent.encode(), app.csrf(self.user()['id']).encode()):
                return None
            return form

        # ---- routes ----
        def do_GET(self):
            if not self.allowed():
                self.close_connection = True
                return self.send(403, 'Forbidden', 'text/plain; charset=utf-8')
            path = self.path.split('?', 1)[0]
            if path == '/style.css':
                return self.send(200, STYLE, 'text/css; charset=utf-8')
            if path in ('/', ''):
                return self.status_page()
            if path == '/bom-dia':
                return self.briefing_page()
            if path == '/desparear':
                return self.unpair_page()
            return self.send(404, self.t('Página não encontrada', 'Page not found'), 'text/plain; charset=utf-8')

        def do_POST(self):
            if not self.allowed():
                self.close_connection = True
                return self.send(403, 'Forbidden', 'text/plain; charset=utf-8')
            path = self.path.split('?', 1)[0]
            form = self.form_data()
            if form is None:
                return self.page(self.t('Recusado', 'Refused'), '', f'<section><h1>{self.t("Pedido recusado", "Request refused")}</h1><p>'
                                 f'{self.t("Abra a página de novo e tente outra vez.", "Open the page again and try once more.")}</p></section>', 403)
            if path == '/parear':
                return self.pair(form)
            if path == '/desparear':
                return self.unpair(form)
            if path == '/bom-dia':
                return self.briefing_post(form)
            if path == '/falar':
                spoken, _ = prefs.speak_now()
                note = self.t('Falando o Bom dia no alto-falante escolhido.', 'Speaking the good morning on the chosen speaker.') if spoken else \
                    self.t('Escolha o alto-falante e o motor de voz e salve antes.', 'Choose the speaker and the voice engine and save first.')
                return self.briefing_page(note=note, tone='ok' if spoken else 'warn')
            return self.send(404, 'Not found', 'text/plain; charset=utf-8')

        # ---- Estado ----
        def status_page(self, note='', tone=''):
            info = app.center.public()
            box = f'<p class="note {tone}" role="status">{_e(note)}</p>' if note else ''
            if info['paired']:
                online = info.get('last_contact') and info.get('problem') != 'offline'
                badge = f'<span class="badge ok">{self.t("Pareado", "Paired")}</span>' if online else \
                    f'<span class="badge warn">{self.t("Sem contato com a plataforma", "No contact with the platform")}</span>'
                body = (f'<section><h1>{self.t("Casa", "Home")}: {_e(info["home_name"])}</h1>{badge}<dl>'
                        + f'<dt>{self.t("Pareado em", "Paired on")}</dt><dd>{_e(str(info.get("paired_at") or "")[:10])}</dd>'
                        + f'<dt>{self.t("Último contato", "Last contact")}</dt><dd>{_e(_ago(info["last_contact"], self.pt()) if info.get("last_contact") else "—")}</dd>'
                        + self.bom_dia_rows(info)
                        + f'<dt>{self.t("Plataforma", "Platform")}</dt><dd>{_e(info["center"])}</dd>'
                        + f'<dt>{self.t("Versão", "Version")}</dt><dd>{_e(info["version"])} · {_e(info["arch"])}</dd></dl>'
                        + f'<div class="actions"><a class="button" href="{_e(self.base())}/bom-dia">{self.t("Bom dia →", "Good morning →")}</a>'
                        + f'<a class="button" href="{_e(self.base())}/desparear">{self.t("Desparear", "Unpair")}</a></div></section>')
                return self.page(self.t('Estado', 'Status'), 'estado', box + body)
            reason = {'code': self.t('A plataforma recusou o código (errado, vencido ou já usado). Gere outro na plataforma.',
                                     'The platform refused the code (wrong, expired or used). Generate another one on the platform.'),
                      'revoked': self.t('A plataforma desconectou esta casa. Gere um código novo para parear de novo.',
                                        'The platform disconnected this home. Generate a new code to pair again.'),
                      'offline': self.t('Sem contato com a plataforma agora. Confira a internet da casa.',
                                        'No contact with the platform now. Check the home\'s internet.'),
                      'rate': self.t('Muitas tentativas: aguarde 15 minutos.', 'Too many attempts: wait 15 minutes.')}.get(info.get('problem'), '')
            warn = f'<p class="note warn" role="alert">{_e(reason)}</p>' if reason and not note else ''
            body = (f'<section><h1>{self.t("Conectar esta casa à IQ", "Connect this home to IQ")}</h1>'
                    f'<span class="badge warn">{self.t("Não pareado", "Not paired")}</span>'
                    f'<p>{self.t("Na plataforma IQ, a IQ gera um código de 6 dígitos para esta casa. Digite-o aqui.", "On the IQ platform, IQ generates a 6-digit code for this home. Type it here.")}</p>'
                    f'<form method="post" action="{_e(self.base())}/parear">{self.token_field()}'
                    f'<label for="code">{self.t("Código de pareamento", "Pairing code")}</label>'
                    f'<input id="code" name="code" inputmode="numeric" autocomplete="one-time-code" maxlength="9" required>'
                    f'<div class="actions"><button class="primary" type="submit">{self.t("Parear", "Pair")}</button></div></form></section>')
            return self.page(self.t('Estado', 'Status'), 'estado', box + warn + body)

        def bom_dia_rows(self, info):
            """"IA pelo centro: ok/sem resposta (última vez hh:mm)", "Bom dia preparado às hh:mm" or "ainda não preparado" and, inside
            Home Assistant, whether the event iq_bom_dia is being heard."""
            zone = app.center.time_zone or schedule.ha_time_zone()
            if info.get('ai_ok') is None:
                ai = self.t('ainda não usada', 'not used yet')
            else:
                ai = (self.t('ok', 'ok') if info['ai_ok'] else self.t('sem resposta', 'no answer')) \
                    + self.t(f' (última vez {_hhmm(info.get("ai_at"), zone)})', f' (last time {_hhmm(info.get("ai_at"), zone)})')
            data = ready.load()
            if data and ready.age(data) < ready.MAX_AGE:
                at = _hhmm(data.get('prepared_at'), zone)
                prepared = self.t(f'preparado às {at}', f'prepared at {at}')
            else:
                prepared = self.t('ainda não preparado', 'not prepared yet')
            rows = (f'<dt>{self.t("IA pelo centro", "AI by the platform")}</dt><dd>{_e(ai)}</dd>'
                    f'<dt>{self.t("Bom dia", "Good morning")}</dt><dd>{_e(prepared)}</dd>')
            if app.listener is not None:
                state = app.listener.public().get('state')
                heard = {'listening': ('ouvindo', 'listening'),
                         'auth_failed': ('o Home Assistant recusou o acesso', 'Home Assistant refused the access')}.get(
                    state, ('sem conexão com o Home Assistant', 'no connection to Home Assistant'))
                rows += f'<dt>{self.t("Evento iq_bom_dia", "Event iq_bom_dia")}</dt><dd>{_e(self.t(*heard))}</dd>'
            return rows

        def pair(self, form):
            ok, reason = app.center.pair((form.get('code') or [''])[0])
            if ok:
                return self.status_page(self.t('Casa pareada com a plataforma IQ.', 'Home paired with the IQ platform.'), 'ok')
            if reason == 'format':
                return self.status_page(self.t('Digite os 6 dígitos do código.', 'Type the 6 digits of the code.'), 'warn')
            return self.status_page()

        def unpair_page(self):
            if not app.center.paired():
                return self.status_page()
            body = (f'<section><h1>{self.t("Desparear esta casa?", "Unpair this home?")}</h1>'
                    f'<p>{self.t("A plataforma IQ deixa de alcançar esta casa até alguém parear de novo com um código novo. O Bom dia continua funcionando aqui.", "The IQ platform stops reaching this home until someone pairs again with a new code. The good morning keeps working here.")}</p>'
                    f'<form method="post" action="{_e(self.base())}/desparear">{self.token_field()}<div class="actions">'
                    f'<button class="danger" type="submit">{self.t("Confirmar desparear", "Confirm unpair")}</button>'
                    f'<a class="button" href="{_e(self.base())}/">{self.t("Cancelar", "Cancel")}</a></div></form></section>')
            return self.page(self.t('Desparear', 'Unpair'), 'estado', body)

        def unpair(self, form):
            if not app.center.paired():
                return self.status_page()
            if app.center.unpair(self.user()):
                return self.status_page(self.t('Despareado. Para desfazer, gere um código na plataforma e pareie de novo.',
                                               'Unpaired. To undo, generate a code on the platform and pair again.'), 'ok')
            return self.status_page(self.t('Sem contato com a plataforma: nada mudou. Tente de novo.', 'No contact with the platform: nothing changed. Try again.'), 'warn')

        # ---- Bom dia ----
        def briefing_page(self, values=None, note='', tone='', text=None, status=200):
            version, current, saved_at = prefs.load()
            p = values or current
            pending = prefs.pending()
            speakers = relay.entities(('media_player.',))
            engines = relay.entities(('tts.',))
            box = f'<p class="note {tone}" role="status">{_e(note)}</p>' if note else ''
            sync = (self.t('Alterações ainda não chegaram à plataforma: vão quando a conexão voltar.', 'Changes have not reached the platform yet: they go when the connection is back.')
                    if pending else (self.t(f'Versão {version} · salva {_ago(saved_at, True)}', f'Version {version} · saved {_ago(saved_at, False)}') if saved_at else
                                     self.t('Valores iniciais: nada salvo ainda.', 'Initial values: nothing saved yet.')))
            check = lambda name, on, label: f'<label class="check"><input type="checkbox" name="{name}"{" checked" if on else ""}> {label}</label>'  # noqa: E731
            source_lines = '\n'.join(f'{s["name"]} = {s["url"]}' for s in p['sources'])
            pick_lines = '\n'.join(f'{n} = {k}' for n, k in p['picks'].items())
            options = lambda items, chosen: ''.join(f'<option value="{_e(v)}"{" selected" if v == chosen else ""}>{_e(n)}</option>' for v, n in items)  # noqa: E731
            speaker_items = [('', self.t('— nenhum —', '— none —'))] + [(e, n or e) for e, n in speakers]
            if p['speaker'] and p['speaker'] not in [e for e, _ in speakers]:
                speaker_items.append((p['speaker'], p['speaker']))
            engine_items = list(ENGINES) + [(e, n or e) for e, n in engines]
            if p['tts_engine'] and p['tts_engine'] not in [v for v, _ in engine_items]:
                engine_items.append((p['tts_engine'], p['tts_engine']))
            engine_items = [('', self.t('— escolha —', '— choose —'))] + engine_items
            schedule = p.get('schedule') or {'time': '07:00', 'days': []}
            days = ''.join(check(f'day{i}', i in schedule['days'], self.t(*names)) for i, names in enumerate(DAYS))
            result = ''
            if text is not None:
                words = int(text.get('words') or 0)
                result = (f'<section><h2>{self.t("Teste", "Test")}</h2><p class="text">{_e(text["text"])}</p><p class="muted">'
                          + self.t(f'{words} palavras · nada foi falado nem salvo', f'{words} words · nothing spoken or saved') + '</p></section>')
            body = (f'{box}{result}<form method="post" action="{_e(self.base())}/bom-dia">{self.token_field()}'
                    f'<section><h1>{self.t("Bom dia", "Good morning")}</h1><p class="muted">{_e(sync)}</p>'
                    + check('house_state', p['house_state'], self.t('Ler o estado da casa (portas, janelas, alarme)', 'Read the house state (doors, windows, alarm)'))
                    + check('weather', p['weather'], self.t('Falar o clima', 'Speak the weather'))
                    + f'</section><section><h2>{self.t("Notícias", "News")}</h2>'
                    f'<label for="sources">{self.t("Fontes: uma por linha, “Nome = endereço RSS”", "Sources: one per line, “Name = RSS address”")}</label>'
                    f'<textarea id="sources" name="sources" spellcheck="false">{_e(source_lines)}</textarea>'
                    f'<label for="picks">{self.t("Quantas de cada fonte (0 a 6): “Nome = 2”", "How many from each source (0 to 6): “Name = 2”")}</label>'
                    f'<textarea id="picks" name="picks" spellcheck="false">{_e(pick_lines)}</textarea>'
                    f'<div class="pair"><div><label for="total_min">{self.t("Total: mínimo", "Total: minimum")}</label>'
                    f'<input id="total_min" name="total_min" type="number" min="1" max="20" value="{_e(p["total_min"])}"></div>'
                    f'<div><label for="total_max">{self.t("Total: máximo", "Total: maximum")}</label>'
                    f'<input id="total_max" name="total_max" type="number" min="1" max="20" value="{_e(p["total_max"])}"></div></div>'
                    f'<label for="max_words">{self.t("Máximo de palavras", "Maximum words")}</label>'
                    f'<input id="max_words" name="max_words" type="number" min="40" max="300" value="{_e(p["max_words"])}">'
                    f'<label for="rules">{self.t("Regras de relevância", "Relevance rules")}</label>'
                    f'<textarea id="rules" name="rules" maxlength="2000">{_e(p["rules"])}</textarea></section>'
                    f'<section><h2>{self.t("Voz", "Voice")}</h2><label for="speaker">{self.t("Alto-falante", "Speaker")}</label>'
                    f'<select id="speaker" name="speaker">{options(speaker_items, p["speaker"])}</select>'
                    f'<div class="pair"><div><label for="volume">{self.t("Volume (0 a 100)", "Volume (0 to 100)")}</label>'
                    f'<input id="volume" name="volume" type="number" min="0" max="100" value="{_e(p["volume"] if p["volume"] is not None else "")}"></div>'
                    f'<div><label for="tts_engine">{self.t("Motor de voz", "Voice engine")}</label>'
                    f'<select id="tts_engine" name="tts_engine">{options(engine_items, p["tts_engine"])}</select></div></div>'
                    f'<div class="pair"><div><label for="language">{self.t("Idioma", "Language")}</label><select id="language" name="language">'
                    f'{options((("pt", "Português"), ("en", "English")), p["language"])}</select></div>'
                    f'<div><label for="temp_unit">{self.t("Unidade", "Unit")}</label><select id="temp_unit" name="temp_unit">'
                    f'{options([(v, self.t(a, b)) for v, a, b in UNITS], p["temp_unit"])}</select></div></div></section>'
                    f'<section><h2>{self.t("Fala automática", "Automatic speech")}</h2>'
                    f'<label for="time">{self.t("Horário", "Time")}</label><input id="time" name="time" type="time" value="{_e(schedule["time"])}">'
                    f'<label>{self.t("Dias (nenhum = desligada)", "Days (none = off)")}</label><div class="days">{days}</div></section>'
                    f'<div class="actions"><button class="primary" type="submit" name="action" value="save">{self.t("Salvar", "Save")}</button>'
                    f'<button type="submit" name="action" value="test">{self.t("Testar", "Test")}</button></div></form>'
                    f'<form method="post" action="{_e(self.base())}/falar">{self.token_field()}<div class="actions">'
                    f'<button type="submit">{self.t("Falar agora", "Speak now")}</button></div></form>')
            return self.page(self.t('Bom dia', 'Good morning'), 'bomdia', body, status)

        def briefing_post(self, form):
            action = (form.get('action') or ['save'])[0]
            current = prefs.load()[1]
            try:
                values = parse_form(form, current)
            except ValueError as error:
                field = str(error).split(':')[0].strip()
                message = FIELDS.get(field, ('Valores inválidos', 'Invalid values'))
                return self.briefing_page(note=self.t(*message), tone='warn', status=400)
            if action == 'test':
                try:
                    return self.briefing_page(values=values, text=prefs.preview(values), note=self.t('Teste com os valores do formulário (não salvos).', 'Test with the form values (not saved).'))
                except ValueError:
                    return self.briefing_page(values=values, note=self.t('Valores inválidos', 'Invalid values'), tone='warn', status=400)
            prefs.save_local(values, self.user())
            try:
                version = app.center.send_prefs(values, self.user())
            except ValueError:
                version = None
            if version:
                prefs.mark_synced(version)
                return self.briefing_page(note=self.t(f'Salvo. A plataforma guardou a versão {version}.', f'Saved. The platform kept version {version}.'), tone='ok')
            return self.briefing_page(note=self.t('Salvo nesta casa. A plataforma recebe quando a conexão voltar.', 'Saved in this home. The platform gets it when the connection is back.'), tone='ok')

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True


def serve(app, host='0.0.0.0', port=None):
    """The tab's server (a thread per request). Returns it; serve_forever runs in the caller's thread."""
    return Server((host, settings.ingress_port() if port is None else port), make_handler(app))


def start(app, host='0.0.0.0', port=None):
    server = serve(app, host, port)
    threading.Thread(target=server.serve_forever, name='iq-edge-web', daemon=True).start()
    return server
