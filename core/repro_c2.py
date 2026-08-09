"""Debug reproduction for C2-native exit-code classification."""

from __future__ import annotations

import sys
import tempfile
import time

from pathlib import Path

from app.platform.process.base import LiveRegistry
from app.platform.process.windows import WindowsProcessAdapter
from app.ports.process_control import SpawnRequest

SCRIPT = Path('tests/adapters/fake_server/fake_server.py').resolve()
tmp = tempfile.mkdtemp()

adapter = WindowsProcessAdapter(LiveRegistry())
req = SpawnRequest(
    world_id='repro',
    launch_command=[sys.executable, str(SCRIPT), '--port=0', '--marker=world-repro'],
    cwd=tmp,
    env={},
)
res = adapter.spawn(req)
handle = res.handle
print('spawned pid:', handle.pid, 'error:', res.spawn_error)

deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    if adapter.poll(handle).alive:
        break
    time.sleep(0.05)
print('alive after spawn:', adapter.poll(handle).alive)

sent = adapter.write_stdin(handle, 'stop')
print('write_stdin:', sent)

deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    status = adapter.poll(handle)
    if not status.alive:
        print('EXITED status:', status)
        break
    time.sleep(0.05)
else:
    print('STILL RUNNING')

import psutil

proc = psutil.Process(handle.pid)
try:
    print('psutil running:', proc.is_running(), 'status:', proc.status())
    print('psutil create_time:', proc.create_time())
except psutil.NoSuchProcess:
    print('psutil: NoSuchProcess (gone)')

entry = adapter._registry.get('repro')
if entry is not None and entry.popen is not None:
    try:
        print('popen.poll():', entry.popen.poll())
    except Exception as exc:
        print('popen.poll raised:', repr(exc))
else:
    print('popen missing; entry:', entry is not None)
