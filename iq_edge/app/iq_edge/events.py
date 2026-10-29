"""Home Assistant's trigger for the Bom dia (lote A5): the add-on listens to the Core's event `iq_bom_dia` through the Supervisor's
websocket proxy (ws://supervisor/core/websocket, auth with SUPERVISOR_TOKEN as `access_token`; config.yaml homeassistant_api: true).
No new port and nothing comes in from outside: the add-on opens the connection. An automation fires the event (`action: event`,
`event: iq_bom_dia`, optional `event_data: {language: en}`) and the add-on speaks now, the same path as "Falar agora"
(prefs.speak_now). Two events less than a minute apart speak once (an automation that fires twice, a loop).

Standard library only: a small RFC 6455 client (masked frames, ping -> pong, close, fragmented messages, 1 MiB per message). After
30 s of silence it sends Home Assistant's own `ping`; a second silence means a dead connection. It reconnects with back-off
1 -> 60 s. The token never goes to the log.

  IQ_HA_WS_URL   instead of ws://supervisor/core/websocket (tests, a developer's machine)
"""
import base64
import hashlib
import json
import logging
import os
import secrets
import socket
import ssl
import struct
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from . import prefs, settings

EVENT = 'iq_bom_dia'
BACKOFF = (1, 2, 4, 8, 15, 30, 60)
COOLDOWN = 60
SILENCE = 30
FRAME_TIMEOUT = 30
MAX_MESSAGE = 1024 * 1024
GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
logger = logging.getLogger('iq_edge.events')


def ws_url():
    return (os.getenv('IQ_HA_WS_URL') or 'ws://supervisor/core/websocket').strip()


class WebSocketError(Exception):
    """The connection is unusable (closed, broken frame, timeout in the middle of a frame): reconnect."""


class AuthFailed(WebSocketError):
    """Home Assistant refused the token."""


class WebSocket:
    """A minimal websocket client: JSON text messages, client frames masked, pings answered."""

    def __init__(self, url, timeout=10):
        parts = urlsplit(url)
        if parts.scheme not in ('ws', 'wss') or not parts.hostname:
            raise WebSocketError('url')
        sock = socket.create_connection((parts.hostname, parts.port or (443 if parts.scheme == 'wss' else 80)), timeout=timeout)
        try:
            if parts.scheme == 'wss':
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parts.hostname)
            key = base64.b64encode(secrets.token_bytes(16)).decode()
            host = parts.hostname if parts.port is None else f'{parts.hostname}:{parts.port}'
            path = (parts.path or '/') + (f'?{parts.query}' if parts.query else '')
            sock.sendall((f'GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                          f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
            head = b''
            while b'\r\n\r\n' not in head:
                chunk = sock.recv(4096)
                if not chunk or len(head) > 16384:
                    raise WebSocketError('handshake')
                head += chunk
            head, self.buffer = head.split(b'\r\n\r\n', 1)
            lines = head.decode('latin-1').split('\r\n')
            status = lines[0].split()
            headers = {name.strip().lower(): value.strip() for name, _, value in (line.partition(':') for line in lines[1:])}
            accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
            if len(status) < 2 or status[1] != '101' or headers.get('sec-websocket-accept') != accept:
                raise WebSocketError('handshake')
        except BaseException:
            sock.close()
            raise
        self.sock = sock
        self.lock = threading.Lock()

    def send(self, opcode, payload=b''):
        size = len(payload)
        if size < 126:
            header = struct.pack('!BB', 0x80 | opcode, 0x80 | size)
        elif size < 65536:
            header = struct.pack('!BBH', 0x80 | opcode, 0x80 | 126, size)
        else:
            header = struct.pack('!BBQ', 0x80 | opcode, 0x80 | 127, size)
        mask = secrets.token_bytes(4)
        with self.lock:
            self.sock.sendall(header + mask + bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload)))

    def send_json(self, data):
        self.send(0x1, json.dumps(data).encode())

    def _wait(self, timeout):
        """True when there is data to read; False after `timeout` seconds of silence."""
        if self.buffer:
            return True
        self.sock.settimeout(timeout)
        try:
            chunk = self.sock.recv(65536)
        except socket.timeout:
            return False
        if not chunk:
            raise WebSocketError('closed')
        self.buffer += chunk
        return True

    def _read(self, size):
        self.sock.settimeout(FRAME_TIMEOUT)
        while len(self.buffer) < size:
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                raise WebSocketError('timeout') from None
            if not chunk:
                raise WebSocketError('closed')
            self.buffer += chunk
        data, self.buffer = self.buffer[:size], self.buffer[size:]
        return data

    def _frame(self):
        first, second = self._read(2)
        size = second & 0x7F
        if size == 126:
            size = struct.unpack('!H', self._read(2))[0]
        elif size == 127:
            size = struct.unpack('!Q', self._read(8))[0]
        if size > MAX_MESSAGE:
            raise WebSocketError('too_big')
        mask = self._read(4) if second & 0x80 else None
        payload = self._read(size)
        if mask:
            payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        return bool(first & 0x80), first & 0x0F, payload

    def recv_json(self, timeout):
        """The next JSON message; None after `timeout` seconds without any frame. Pings are answered; a message that is not JSON is
        skipped; WebSocketError when the server closes."""
        parts, kind = [], None
        while True:
            if not self._wait(timeout if not parts else FRAME_TIMEOUT):
                if parts:
                    raise WebSocketError('timeout')
                return None
            fin, opcode, payload = self._frame()
            if opcode == 0x9:
                self.send(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x8:
                try:
                    self.send(0x8, payload[:2])
                except OSError:
                    pass
                raise WebSocketError('closed')
            if opcode in (0x1, 0x2) and kind is None:
                kind, parts = opcode, [payload]
            elif opcode == 0x0 and kind is not None:
                parts.append(payload)
            else:
                raise WebSocketError('protocol')
            if sum(len(part) for part in parts) > MAX_MESSAGE:
                raise WebSocketError('too_big')
            if fin:
                try:
                    data = json.loads(b''.join(parts).decode('utf-8'))
                except ValueError:
                    data = None
                parts, kind = [], None
                if isinstance(data, dict):
                    return data

    def close(self):
        try:
            self.send(0x8, struct.pack('!H', 1000))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class Listener:
    """Listens to `iq_bom_dia` while the add-on runs. `speak(language)` is prefs.speak_now; `spawn` runs it off this thread (the
    Bom dia takes seconds to compose; the connection must keep answering pings meanwhile)."""

    def __init__(self, url=None, token=None, speak=None, spawn=None, clock=time.monotonic, backoff=BACKOFF, silence=SILENCE):
        self.url, self.token = url, token
        self.speak = speak or prefs.speak_now
        self.spawn = spawn or (lambda job: threading.Thread(target=job, name='iq-edge-bom-dia', daemon=True).start())
        self.clock, self.backoff, self.silence = clock, backoff, silence
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.failures = 0
        self.last_spoken = None
        self.speaking = False
        self.socket = None
        self.status = {'state': 'off', 'last_event': None}

    def public(self):
        with self.lock:
            return dict(self.status)

    def _set(self, **values):
        with self.lock:
            self.status.update(values)

    def on_event(self, data):
        """One `iq_bom_dia`: speak now (in the background), unless one is being spoken now or the last successful one was less than
        COOLDOWN seconds ago (a failed speech never blocks the next event). True = speaking."""
        language = data.get('language') if isinstance(data, dict) else None
        language = language if language in ('pt', 'en') else None
        now = self.clock()
        with self.lock:
            self.status['last_event'] = _now_iso()
            if self.speaking or (self.last_spoken is not None and now - self.last_spoken < COOLDOWN):
                logger.info('Evento iq_bom_dia repetido em menos de 1 minuto: ignorado.')
                return False
            self.speaking = True
        try:
            prefs.set_state(last_event_at=_now_iso())
        except OSError:
            pass

        def job():
            spoken = False
            try:
                spoken, _ = self.speak(language)
                logger.info('Bom dia pelo evento do Home Assistant: %s.',
                            'falando' if spoken else 'sem alto-falante (nem satélite) escolhido')
            except Exception:
                logger.exception('Erro no Bom dia pelo evento do Home Assistant.')
            finally:
                with self.lock:
                    self.speaking = False
                    if spoken:
                        self.last_spoken = self.clock()
        try:
            self.spawn(job)
        except BaseException:
            with self.lock:
                self.speaking = False
            raise
        return True

    def listen(self):
        """One connection: auth, subscribe, then events until it breaks (WebSocketError/OSError) or `stop` is set."""
        ws = WebSocket(self.url or ws_url())
        self.socket = ws
        try:
            hello = ws.recv_json(10)
            if not hello or hello.get('type') != 'auth_required':
                raise WebSocketError('auth_required')
            ws.send_json({'type': 'auth', 'access_token': self.token or settings.ha_token()})
            answer = ws.recv_json(10)
            if not answer or answer.get('type') != 'auth_ok':
                raise AuthFailed('auth')
            ws.send_json({'id': 1, 'type': 'subscribe_events', 'event_type': EVENT})
            while True:
                answer = ws.recv_json(10)
                if answer is None:
                    raise WebSocketError('subscribe')
                if answer.get('id') == 1 and answer.get('type') == 'result':
                    if not answer.get('success'):
                        raise WebSocketError('subscribe')
                    break
            self.failures = 0
            self._set(state='listening')
            logger.info('Ouvindo o evento iq_bom_dia do Home Assistant.')
            next_id, pinged = 2, False
            while not self.stop.is_set():
                message = ws.recv_json(self.silence)
                if message is None:
                    if pinged:
                        raise WebSocketError('silence')
                    ws.send_json({'id': next_id, 'type': 'ping'})
                    next_id, pinged = next_id + 1, True
                    continue
                pinged = False
                event = message.get('event') if message.get('type') == 'event' and message.get('id') == 1 else None
                if isinstance(event, dict) and event.get('event_type', EVENT) == EVENT:
                    self.on_event(event.get('data') or {})
        finally:
            self.socket = None
            ws.close()

    def _backoff(self):
        wait = self.backoff[min(self.failures, len(self.backoff) - 1)]
        self.failures += 1
        return wait

    def run(self):
        while not self.stop.is_set():
            if self.public()['state'] in ('off', 'listening'):
                self._set(state='connecting')  # after a failure it keeps showing the failure until the next answer
            try:
                self.listen()
            except AuthFailed:
                if self.public()['state'] != 'auth_failed':  # every time it becomes refused (not on each retry)
                    logger.warning('O Home Assistant recusou o token do add-on no websocket; tentando de novo.')
                self._set(state='auth_failed')
            except (OSError, WebSocketError) as error:
                self._set(state='offline')
                if self.failures == 0:
                    logger.info('Sem o websocket do Home Assistant (%s); tentando de novo.', str(error)[:40] or error.__class__.__name__)
            except Exception:  # never stop the add-on
                self._set(state='offline')
                logger.exception('Erro inesperado no websocket do Home Assistant.')
            if not self.stop.is_set():
                self.stop.wait(self._backoff())
        self._set(state='off')

    def close(self):
        """Stop listening (tests and the add-on's stop): the open connection is closed, so the loop ends now."""
        self.stop.set()
        ws = self.socket
        if ws:
            try:
                ws.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
