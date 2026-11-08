"""Fake Minecraft server binary (Document 13 section 6.2).

A tiny, stdlib-only program that behaves like a Minecraft server for
process-control purposes:

- Prints startup banner lines to stdout (incl. a configurable "ready"
  marker -- advisory evidence only, never the sole readiness signal).
- Optionally listens on a TCP port (connect-only probe target) and runs a
  minimal RCON frame responder for readiness level 3 + command tests.
- Writes ``tick`` lines at a configurable rate (log-ingestion source).
- Responds to commands via stdin (plain text) and via RCON:
  ``stop`` (graceful exit 0), ``save-all``, ``save-off``, ``save-on``,
  ``list``. ``--ignore-graceful`` / ``--ignore-rcon-stop`` simulate a server
  that refuses the graceful ladder for C10 escalation tests.
- ``--crash-after-ms`` for deterministic crash tests (exit 42, abnormal).
- ``--spawn-grandchild`` spawns a detached sleep child; killing the tree
  must also kill it (C6 orphan containment).
- ``--eula={not_present|unaccepted|accepted}`` writes/omits ``eula.txt``
  and refuses to stay up unless accepted (Doc 14 EULA-gate behaviour).

Run directly: ``python fake_server.py --port 25565 ...``. Importable for
tests to locate the script; never imported by ``app/``.
"""

from __future__ import annotations

import argparse
import os
import socket
import struct
import subprocess
import sys
import threading
import time

_MARKER = 'mcmanager:'

# Abnormal exit code for crash mode: must NOT be 0/1 (the adapter's
# ``_classify_exit`` treats 0/1 as stop-triggered/graceful).
CRASH_EXIT_CODE = 42


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Fake Minecraft server (Doc 13 test double)')
    parser.add_argument('--port', type=int, default=0, help='TCP listen port (0 = none)')
    parser.add_argument('--rcon-port', type=int, default=0, help='RCON listen port (0 = none)')
    parser.add_argument('--rcon-password')
    parser.add_argument('--marker', default='', help='world marker echoed into the banner')
    parser.add_argument('--tick-ms', type=int, default=0, help='write tick lines every N ms')
    parser.add_argument('--ready-ms', type=int, default=0, help='delay before "Done" ready line')
    parser.add_argument('--never-ready', action='store_true', help='suppress the ready line')
    parser.add_argument('--crash-after-ms', type=int, help='exit(42) after N ms')
    parser.add_argument(
        '--crash-after',
        type=_seconds_to_milliseconds,
        help='Document 13 alias: exit(42) after a duration such as 2s',
    )
    parser.add_argument('--spawn-grandchild', action='store_true', help='spawn a sleep child')
    parser.add_argument(
        '--eula',
        choices=('not_present', 'unaccepted', 'accepted'),
        default='accepted',
        help='eula.txt behaviour (default accepted so tests can focus elsewhere)',
    )
    parser.add_argument('--ignore-graceful', action='store_true', help='ignore TERM/stdin stop')
    parser.add_argument('--ignore-rcon-stop', action='store_true', help='ignore RCON stop')
    parser.add_argument('--save-slow-ms', type=int, help='save-all response delay')
    parser.add_argument(
        '--save-slow',
        action='store_true',
        help='Document 14 mode: delay save-all responses by one second',
    )
    parser.add_argument('--ignore-save-on', action='store_true', help='save-on has no effect')
    args = parser.parse_args(argv)
    if args.crash_after_ms is not None and args.crash_after is not None:
        parser.error('use only one of --crash-after-ms or --crash-after')
    args.crash_after_ms = (
        args.crash_after_ms if args.crash_after_ms is not None else args.crash_after or 0
    )
    if args.save_slow_ms is not None and args.save_slow:
        parser.error('use only one of --save-slow-ms or --save-slow')
    args.save_slow_ms = (
        args.save_slow_ms if args.save_slow_ms is not None else 1000 if args.save_slow else 0
    )
    return args


def _seconds_to_milliseconds(value: str) -> int:
    if value.endswith('s'):
        value = value[:-1]
    try:
        seconds = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('duration must be a number of seconds') from exc
    if seconds < 0:
        raise argparse.ArgumentTypeError('duration cannot be negative')
    return round(seconds * 1000)


class _StopController:
    """Shared stop flag; safe for RCON/stdin threads + main loop."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def request(self) -> None:
        self._event.set()

    def requested(self) -> bool:
        return self._event.is_set()


def _write_eula(args: argparse.Namespace) -> str:
    """Return 'refuse' when the server must exit immediately for EULA."""
    if args.eula == 'not_present':
        return 'ok'
    if args.eula == 'unaccepted':
        with open('eula.txt', 'w', encoding='utf-8', newline='\n') as handle:
            handle.write('# By changing the setting below to TRUE you are indicating your\n')
            handle.write('# agreement to our EULA. (https://aka.ms/MinecraftEULA)\n')
            handle.write('eula=false\n')
        print('[FakeServer] Failed to load eula.txt')
        print('[FakeServer] You need to agree to the EULA in order to run the server.')
        return 'refuse'
    with open('eula.txt', 'w', encoding='utf-8', newline='\n') as handle:
        handle.write('eula=true\n')
    return 'ok'


def _install_signal_handlers(args: argparse.Namespace, controller: _StopController) -> None:
    """POSIX SIGTERM handling; Windows has no TERM (CTRL_BREAK needs a console)."""
    if os.name != 'posix':
        return

    import signal as _signal

    def _on_term(_signum: int, _frame: object) -> None:
        if args.ignore_graceful:
            print('[FakeServer] ignoring SIGTERM (--ignore-graceful)')
            return
        print('[FakeServer] SIGTERM received, shutting down')
        controller.request()

    _signal.signal(_signal.SIGTERM, _on_term)


def _run_tcp_listener(port: int) -> None:
    """Accept connections; answer the legacy Minecraft ping (C8 + level-4)."""

    def _serve() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('127.0.0.1', port))
            listener.listen(8)
            while True:
                try:
                    conn, _addr = listener.accept()
                except OSError:
                    return
                try:
                    conn.settimeout(1.0)
                    raw = conn.recv(2)
                    if raw == b'\xfe\x01':
                        # Legacy server-list-ping: 0xFF + magic + UTF-16BE payload.
                        conn.sendall(b'\xff\x00\x07localhost\x00\x63\x00\xdd\x00\x01\x00\x00')
                    else:
                        conn.sendall(b'Hello from FakeServer\r\n')
                except OSError:
                    pass
                finally:
                    try:
                        conn.close()
                    except OSError:
                        pass

    threading.Thread(target=_serve, name='fake-tcp-listener', daemon=True).start()


def _run_rcon(args: argparse.Namespace, controller: _StopController, stop_code: int) -> None:
    """Minimal Minecraft RCON responder (request_id, type, payload)."""

    def _handle(conn: socket.socket) -> None:
        authenticated = False
        try:
            while True:
                raw_len = _recv_exact(conn, 4)
                if raw_len is None:
                    return
                (length,) = struct.unpack('<i', raw_len)
                body = _recv_exact(conn, length)
                if body is None:
                    return
                request_id, ptype = struct.unpack('<ii', body[:8])
                payload = body[8:-2].decode('utf-8', errors='replace')

                if ptype == 3:  # auth
                    if payload == args.rcon_password:
                        authenticated = True
                        _respond(conn, request_id, 2, '')
                    else:
                        _respond(conn, -1, 2, '')
                    continue
                if not authenticated:
                    _respond(conn, -1, 2, '')
                    return
                if ptype != 2:  # command
                    _respond(conn, request_id, 0, '')
                    continue
                response = _dispatch_rcon_command(args, controller, payload, stop_code)
                _respond(conn, request_id, 0, response)
        except (OSError, struct.error):
            return
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _serve() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('127.0.0.1', args.rcon_port))
            listener.listen(4)
            while True:
                try:
                    conn, _addr = listener.accept()
                except OSError:
                    return
                threading.Thread(target=_handle, args=(conn,), daemon=True).start()

    threading.Thread(target=_serve, name='fake-rcon-listener', daemon=True).start()


def _recv_exact(conn: socket.socket, nbytes: int) -> bytes | None:
    chunks: list[bytes] = []
    remaining = nbytes
    while remaining > 0:
        chunk = conn.recv(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b''.join(chunks)


def _respond(conn: socket.socket, request_id: int, ptype: int, payload: str) -> None:
    body = struct.pack('<ii', request_id, ptype) + payload.encode('utf-8') + b'\x00\x00'
    conn.sendall(struct.pack('<i', len(body)) + body)


def _dispatch_rcon_command(
    args: argparse.Namespace, controller: _StopController, command: str, stop_code: int
) -> str:
    normalized = command.strip().lower()
    if normalized == 'stop':
        if args.ignore_rcon_stop:
            return 'Cannot stop the server from the console without a stop request.'
        controller.request()
        return 'Stopping the server...'
    if normalized == 'list':
        return 'There are 0 of a max of 20 players online:'
    if normalized == 'save-all':
        if args.save_slow_ms > 0:
            time.sleep(args.save_slow_ms / 1000.0)
        return 'Saved the game'
    if normalized == 'save-off':
        return 'Autosave disabled'
    if normalized == 'save-on':
        if args.ignore_save_on:
            return 'Autosave is already disabled'
        return 'Autosave enabled'
    return f'Unknown command: {command}'


def _run_stdin(args: argparse.Namespace, controller: _StopController, stop_code: int) -> None:
    """Read plain-text commands from stdin (graceful stop ladder step 2)."""

    def _handle_line(raw: bytes) -> bool:
        line = raw.decode('utf-8', errors='replace').strip()
        if not line:
            return False
        if line.lower() == 'stop':
            if args.ignore_graceful:
                print('[FakeServer] ignoring stdin stop (--ignore-graceful)')
                return False
            print('[FakeServer] Stopping the server (stdin stop)')
            controller.request()
            return True
        if line.lower() in ('save-all', 'save-off', 'save-on', 'list'):
            print(f'[FakeServer] {_dispatch_rcon_command(args, controller, line, stop_code)}')
        return False

    def _loop() -> None:
        pending = bytearray()
        while not controller.requested():
            try:
                chunk = os.read(sys.stdin.fileno(), 4096)
            except (OSError, ValueError):
                return
            if not chunk:
                if pending:
                    _handle_line(bytes(pending))
                return
            pending.extend(chunk)
            while b'\n' in pending:
                raw, _, remainder = pending.partition(b'\n')
                pending[:] = remainder
                if _handle_line(raw):
                    return

    threading.Thread(target=_loop, name='fake-stdin', daemon=True).start()


def _spawn_grandchild() -> None:
    """Detached sleep child -- must die with the tree (C6)."""
    code = 'import time; time.sleep(300)'
    subprocess.Popen(
        [sys.executable, '-c', code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )


def main(argv: list[str] | None = None) -> int:
    # The adapter reads stdout/stderr through pipes; without line buffering the
    # lines would sit in Python's block buffer and never be observed (C5/C12).
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass

    args = _parse_args(argv)
    if args.rcon_password is None:
        args.rcon_password = 'test-pass'
        try:
            with open('server.properties', encoding='utf-8') as properties:
                for line in properties:
                    key, separator, value = line.partition('=')
                    if separator and key.strip() == 'rcon.password':
                        args.rcon_password = value.strip()
                        break
        except OSError:
            pass
    controller = _StopController()
    stop_code = 1

    _install_signal_handlers(args, controller)

    if _write_eula(args) == 'refuse':
        print('[FakeServer] EULA not accepted; refusing to start.')
        return 1

    if args.spawn_grandchild:
        _spawn_grandchild()
        print('[FakeServer] grandchild spawned')

    if args.port > 0:
        _run_tcp_listener(args.port)
        print(f'[FakeServer] listening on 127.0.0.1:{args.port}')
    if args.rcon_port > 0:
        _run_rcon(args, controller, stop_code)
        print(f'[FakeServer] rcon listening on 127.0.0.1:{args.rcon_port}')

    if args.marker:
        print(f'[FakeServer] marker={args.marker}')

    _run_stdin(args, controller, stop_code)

    print('[FakeServer] Starting minecraft server version 1.21')
    print('[FakeServer] Loading properties')

    started = time.monotonic()
    tick_count = 0
    crash_deadline = started + args.crash_after_ms / 1000.0 if args.crash_after_ms > 0 else None
    ready_deadline = started + args.ready_ms / 1000.0 if not args.never_ready else None
    ready_printed = False

    # One tick line per ``tick_ms`` milliseconds (time-based, so
    # ``--tick-ms=1`` yields a steady high-rate stream for C5/C13).
    next_tick = started + args.tick_ms / 1000.0 if args.tick_ms > 0 else None

    while not controller.requested():
        now = time.monotonic()
        if crash_deadline is not None and now >= crash_deadline:
            print('[FakeServer] Crashed unexpectedly (--crash-after-ms)')
            return CRASH_EXIT_CODE
        if ready_deadline is not None and not ready_printed and now >= ready_deadline:
            print('Done (1.234s)! For help, type "help"')
            ready_printed = True
            # Once ready, the ready line stays printed; never re-emitted.
            ready_deadline = None
        if next_tick is not None and now >= next_tick:
            tick_count += 1
            print(f'[FakeServer] tick {tick_count}')
            next_tick += args.tick_ms / 1000.0
        time.sleep(0.01)

    print('[FakeServer] Stopping the server')
    print('[FakeServer] Stopping server')
    time.sleep(0.05)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
