"""RCON client + safe command allowlist (Doc 14 section 8)."""

from __future__ import annotations

import socket
import struct
import threading

# Minecraft RCON protocol constants
_TYPE_AUTH = 3
_TYPE_RESPONSE = 0
_TYPE_COMMAND = 2
_TYPE_AUTH_RESPONSE = 2

# The ONLY commands RuntimeService may issue (Doc 14 section 8 allowlist).
SAFE_COMMANDS = frozenset({'save-all', 'save-off', 'save-on', 'stop', 'list', 'tps', 'tick'})


class RconError(Exception):
    """Raised on RCON protocol/transport failures."""


class RconClient:
    """Minimal Minecraft RCON client (single request/response).

    Session-scoped: constructed per RuntimeSession with that session's
    rotated secret; the raw credential is never retained beyond the
    connection (Doc 14 section 8).
    """

    def __init__(self, host: str, port: int, password: str, timeout_s: float = 5.0) -> None:
        self._host = host
        self._port = port
        self._password = password
        self._timeout_s = timeout_s
        self._socket: socket.socket | None = None
        self._request_id = 1
        self._mutex = threading.Lock()

    def connect(self) -> None:
        """Open the connection and authenticate."""
        try:
            sock = socket.create_connection((self._host, self._port), timeout=self._timeout_s)
        except OSError as exc:
            raise RconError(f'connect failed: {exc}') from exc
        self._socket = sock
        try:
            self._authenticate()
        except RconError:
            self.close()
            raise

    def _authenticate(self) -> None:
        auth_id = self._next_request_id()
        self._send(auth_id, _TYPE_AUTH, self._password)
        request_id, ptype, _payload = self._receive()
        if request_id == -1:
            raise RconError('authentication rejected')
        if request_id != auth_id or ptype != _TYPE_AUTH_RESPONSE:
            raise RconError('unexpected auth response')

    def command(self, command: str) -> str:
        """Send a command and return the text response.

        Refuses any command outside the closed allowlist BEFORE reaching the
        wire (Doc 14 section 8, Doc 10 FORBIDDEN-class).
        """
        normalized = command.strip().lower()
        base = normalized.split(' ')[0]
        if base not in SAFE_COMMANDS:
            raise RconError(f'command not in allowlist: {base!r}')

        with self._mutex:
            if self._socket is None:
                self.connect()
            request_id = self._next_request_id()
            self._send(request_id, _TYPE_COMMAND, command)
            _req_id, _ptype, payload = self._receive()
        return payload

    def ping(self) -> bool:
        """RCON ready check: authenticated ``list`` round-trip (level 3)."""
        try:
            if self._socket is None:
                self.connect()
            self.command('list')
            return True
        except RconError:
            return False

    def close(self) -> None:
        with self._mutex:
            if self._socket is not None:
                try:
                    self._socket.close()
                except OSError:
                    pass
                self._socket = None

    def _next_request_id(self) -> int:
        request_id = self._request_id
        self._request_id += 1
        return request_id

    def _send(self, request_id: int, ptype: int, payload: str) -> None:
        if self._socket is None:
            raise RconError('not connected')
        body = struct.pack('<ii', request_id, ptype) + payload.encode('utf-8') + b'\x00\x00'
        packet = struct.pack('<i', len(body)) + body
        try:
            self._socket.sendall(packet)
        except OSError as exc:
            raise RconError(f'send failed: {exc}') from exc

    def _receive(self) -> tuple[int, int, str]:
        if self._socket is None:
            raise RconError('not connected')
        try:
            raw_len = self._recv_exact(4)
            (length,) = struct.unpack('<i', raw_len)
            body = self._recv_exact(length)
        except OSError as exc:
            raise RconError(f'receive failed: {exc}') from exc
        request_id, ptype = struct.unpack('<ii', body[:8])
        payload = body[8:-2].decode('utf-8', errors='replace')
        return request_id, ptype, payload

    def _recv_exact(self, nbytes: int) -> bytes:
        if self._socket is None:
            raise RconError('not connected')
        chunks: list[bytes] = []
        remaining = nbytes
        while remaining > 0:
            chunk = self._socket.recv(remaining)
            if not chunk:
                raise RconError('connection closed')
            chunks.append(chunk)
            remaining -= len(chunk)
        return b''.join(chunks)
