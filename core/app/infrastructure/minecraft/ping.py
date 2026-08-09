"""Legacy Minecraft server-list-ping probe (Doc 14 readiness level 4)."""

from __future__ import annotations

import socket

_LEGACY_PING = b'\xfe\x01'
_PING_ACK = b'\xff'


def ping_protocol(host: str, port: int, timeout_s: float = 1.0) -> bool:
    """Send the legacy ``0xFE 0x01`` handshake and require a ``0xFF`` reply.

    Vanilla, Paper, Fabric, and Forge all answer the legacy ping; a plain
    TCP listener (or nothing) does not — so this is a true protocol probe,
    not a bare connect check (Doc 13 C8 is the bare-connect floor; this is
    the ladder's ``probe_ok`` signal).
    """
    if port <= 0:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout_s) as sock:
            sock.settimeout(timeout_s)
            sock.sendall(_LEGACY_PING)
            return sock.recv(1) == _PING_ACK
    except OSError:
        return False
