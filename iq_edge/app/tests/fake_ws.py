"""A FAKE Home Assistant websocket API as the Supervisor proxies it (ws://127.0.0.1:<port>/core/websocket), on a thread: the RFC 6455
handshake, auth_required -> auth (the add-on's token) -> auth_ok / auth_invalid, subscribe_events -> result, `ping` -> `pong`. The
test fires events (whole or in fragments), sends ping frames and drops connections. Nothing leaves 127.0.0.1."""
import base64
import hashlib
import json
import socket
import struct
import threading

from tests.fakes import TOKEN

GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'


def _frame(opcode, payload, fin=True):
    size = len(payload)
    head = struct.pack('!B', (0x80 if fin else 0) | opcode)
    if size < 126:
        head += struct.pack('!B', size)
    elif size < 65536:
        head += struct.pack('!BH', 126, size)
    else:
        head += struct.pack('!BQ', 127, size)
    return head + payload


class _Conn:
    def __init__(self, sock):
        self.sock, self.buffer, self.lock = sock, b'', threading.Lock()

    def read(self, size):
        while len(self.buffer) < size:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError('closed')
            self.buffer += chunk
        data, self.buffer = self.buffer[:size], self.buffer[size:]
        return data

    def frame(self):
        first, second = self.read(2)
        size = second & 0x7F
        if size == 126:
            size = struct.unpack('!H', self.read(2))[0]
        elif size == 127:
            size = struct.unpack('!Q', self.read(8))[0]
        if not second & 0x80:
            raise ConnectionError('a client frame must be masked')
        mask = self.read(4)
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(self.read(size)))
        return first & 0x0F, payload

    def send(self, data):
        with self.lock:
            self.sock.sendall(data)

    def send_json(self, data):
        self.send(_frame(0x1, json.dumps(data).encode()))


class FakeWebSocketHA:
    def __init__(self, token=TOKEN):
        self.token, self.answer_pings = token, True
        self.received, self.pongs, self.connections, self.subscriptions = [], [], 0, []
        self.changed = threading.Condition()
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen()
        self.url = f'ws://127.0.0.1:{self.listener.getsockname()[1]}/core/websocket'
        self.open = []
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                sock, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(sock,), daemon=True).start()

    def _note(self, **change):
        with self.changed:
            for key, value in change.items():
                getattr(self, key).append(value)
            self.changed.notify_all()

    def _serve(self, sock):
        conn = _Conn(sock)
        try:
            head = b''
            while b'\r\n\r\n' not in head:
                head += sock.recv(4096)
            request, conn.buffer = head.split(b'\r\n\r\n', 1)
            lines = request.decode('latin-1').split('\r\n')
            headers = {k.strip().lower(): v.strip() for k, _, v in (line.partition(':') for line in lines[1:])}
            if lines[0].split()[1] != '/core/websocket' or headers.get('upgrade', '').lower() != 'websocket':
                sock.sendall(b'HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n')
                return sock.close()
            accept = base64.b64encode(hashlib.sha1((headers['sec-websocket-key'] + GUID).encode()).digest()).decode()
            sock.sendall(('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                          f'Sec-WebSocket-Accept: {accept}\r\n\r\n').encode())
            with self.changed:
                self.connections += 1
                self.open.append(conn)
                self.changed.notify_all()
            conn.send_json({'type': 'auth_required', 'ha_version': '2026.10.4'})
            while True:
                opcode, payload = conn.frame()
                if opcode == 0x8:
                    return sock.close()
                if opcode == 0xA:
                    self._note(pongs=payload)
                    continue
                message = json.loads(payload)
                self._note(received=message)
                if message.get('type') == 'auth':
                    if message.get('access_token') != self.token:
                        conn.send_json({'type': 'auth_invalid', 'message': 'Invalid access token or password'})
                        return sock.close()
                    conn.send_json({'type': 'auth_ok', 'ha_version': '2026.10.4'})
                elif message.get('type') == 'subscribe_events':
                    conn.send_json({'id': message['id'], 'type': 'result', 'success': True, 'result': None})
                    self._note(subscriptions=(conn, message['id'], message.get('event_type')))
                elif message.get('type') == 'ping' and self.answer_pings:
                    conn.send_json({'id': message['id'], 'type': 'pong'})
        except (OSError, ConnectionError, ValueError, IndexError):
            try:
                sock.close()
            except OSError:
                pass

    def wait(self, test, timeout=5):
        with self.changed:
            return self.changed.wait_for(lambda: test(self), timeout)

    def fire(self, data, event_type='iq_bom_dia', fragments=1):
        """The event to every subscription (the last connection), optionally split in `fragments` frames."""
        conn, sub_id, _ = self.subscriptions[-1]
        raw = json.dumps({'id': sub_id, 'type': 'event', 'event': {'event_type': event_type, 'data': data, 'origin': 'LOCAL',
                                                                   'time_fired': '2026-10-29T07:00:00+00:00'}}).encode()
        step = max(1, len(raw) // fragments)
        pieces = [raw[i:i + step] for i in range(0, len(raw), step)]
        conn.send(b''.join(_frame(0x1 if i == 0 else 0x0, piece, fin=i == len(pieces) - 1) for i, piece in enumerate(pieces)))

    def ping_frame(self, payload=b'hi'):
        self.subscriptions[-1][0].send(_frame(0x9, payload))

    def drop(self):
        """Every open connection is cut (Home Assistant restarted)."""
        for conn in list(self.open):
            try:
                conn.sock.shutdown(socket.SHUT_RDWR)
                conn.sock.close()
            except OSError:
                pass
        self.open.clear()

    def stop(self):
        self.listener.close()
        self.drop()
