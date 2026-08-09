"""Real Minecraft Spike (Gate 1) — validate the Readiness Hierarchy against
real server jars.

Usage:
    python spike_real_minecraft.py --java <path-to-java>
        [--vanilla-jar server.jar] [--paper-jar paper.jar] [--forge-jar forge.jar]
        [--mc-version 1.21] [--world-dir D:/mcmanager-worlds] [--timeout-s 180]

For each server type supplied, the spike:

1. Runs the Doc 14 pre-launch gate (EULA + Java + JAR + port) — refusing to
   spawn when the gate fails.
2. Spawns via the platform ProcessControlPort adapter (no shell).
3. Polls the readiness ladder: process_alive -> port_bound -> rcon_ready.
4. Reports the reached level and tears down through the escalation ladder.

The world is declared "running" only when the full hierarchy for that type is
green (Doc 14 section 3). Logs are captured every 2s as advisory evidence.

Known limitations: a real protocol ping probe and Paper API check require a
full Minecraft protocol/client implementation (later phases) — the spike
stops at ``RCON_READY`` for Vanilla/Forge and logs ``PROBE_OK`` as the
remaining step. Fabric can pass using the same ladder as Vanilla.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

from app.domain.value_objects import ServerReadinessLevel, ServerType
from app.infrastructure.minecraft.eula import accept
from app.infrastructure.minecraft.gate import (
    LaunchContext,
    build_launch_argv,
    validate_launch,
)
from app.infrastructure.minecraft.readiness import evaluate, port_is_bound
from app.infrastructure.minecraft.rcon import RconClient
from app.platform.process_health import create_process_adapter
from app.ports.minecraft import MinecraftCapabilities, ReadinessState


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Real Minecraft spike (Gate 1)')
    parser.add_argument('--java', required=True, help='path to a java runtime binary')
    parser.add_argument('--vanilla-jar', help='path to a Vanilla server jar')
    parser.add_argument('--paper-jar', help='path to a Paper server jar')
    parser.add_argument('--forge-jar', help='path to a Forge server jar')
    parser.add_argument('--mc-version', default='1.21')
    parser.add_argument('--base-port', type=int, default=25565)
    parser.add_argument('--world-dir', help='base dir for spike world folders')
    parser.add_argument('--timeout-s', type=float, default=180.0)
    return parser.parse_args(argv)


def _spike_world(java: str, jar_path: str, server_type: ServerType, base_port: int,
                 mc_version: str, world_root: str, timeout_s: float,
                 adapter_provider=create_process_adapter) -> int:
    """Run one spike world; returns 0 on success, non-zero on failure."""

    def _report(level: ServerReadinessLevel) -> None:
        print(f'    [spike] readiness level: {level.value}')

    from app.ports.process_control import SpawnRequest

    world_dir = Path(world_root) / f'spike-{server_type.value}'
    world_dir.mkdir(parents=True, exist_ok=True)
    accept(str(world_dir))  # spike worlds get an explicit, audited acceptance

    port = base_port
    rcon_port = base_port + 10
    context = LaunchContext(
        world_id=f'spike-{server_type.value}',
        server_type=server_type,
        mc_version=mc_version,
        world_dir=str(world_dir),
        java_path=java,
        server_jar_path=jar_path,
        port=port,
        rcon_enabled=True,
        rcon_port=rcon_port,
        launch_args=['nogui'],
    )

    print(f'== {server_type.value} spike @ {jar_path} (port {port}, rcon {rcon_port})')
    gate = validate_launch(context)
    if not gate.passed:
        print(f'    [gate] REJECTED: {gate.error_code} — {gate.detail}')
        return 2
    print(f'    [gate] passed (java {gate.java_major})')

    caps = MinecraftCapabilities(rcon=True, protocol_ping=True)
    adapter = adapter_provider()
    argv = build_launch_argv(java, ['-Xmx1G', '-Xms512M'], jar_path, ['nogui'])
    result = adapter.spawn(
        SpawnRequest(
            world_id=context.world_id,
            launch_command=argv,
            cwd=str(world_dir),
            env={},
            stdout_channel='stdout',
            stderr_channel='stderr',
        )
    )
    if result.handle is None:
        print(f'    [spawn] FAILED: {result.spawn_error}')
        return 3
    handle = result.handle
    print(f'    [spawn] pid={handle.pid}')

    deadline = time.monotonic() + timeout_s
    reached: ServerReadinessLevel | None = None
    rcon: RconClient | None = None
    rcon_ready = False
    last_lines: list[str] = []

    try:
        while time.monotonic() < deadline:
            status = adapter.poll(handle)
            if not status.alive:
                print(f'    [poll] process exited: {status.exit_class.value} '
                      f'(code {status.exit_code})')
                return 4

            try:
                last_lines = [
                    line for _ch, _no, line in adapter.tail_replay(handle, 0)
                ][-12:]
            except Exception:
                pass

            state = ReadinessState(
                process_alive=True,
                port_bound=port_is_bound('127.0.0.1', port, 0.7),
                rcon_ready=rcon_ready,
                probe_ok=False,
                operationally_valid=False,
            )
            level = evaluate(server_type=server_type, caps=caps, state=state)
            if level != reached:
                reached = level
                _report(level)

            if reached.rank >= ServerReadinessLevel.RCON_READY.rank and not rcon_ready:
                try:
                    rcon = RconClient('127.0.0.1', rcon_port, 'spike-pass', timeout_s=2.0)
                    rcon.connect()
                    if rcon.ping():
                        rcon_ready = True
                        state = ReadinessState(
                            process_alive=True,
                            port_bound=True,
                            rcon_ready=True,
                            probe_ok=False,
                            operationally_valid=False,
                        )
                        print(f'    [rcon] ready — {server_type.value} at RCON_READY')
                except Exception as exc:  # noqa: BLE001 — spike diagnostics
                    print(f'    [rcon] probe failed ({exc}); keep waiting')
                    if rcon is not None:
                        try:
                            rcon.close()
                        except Exception:
                            pass

            if rcon_ready:
                print(f'    [READY] {server_type.value} reached RCON_READY '
                      f'— hierarchy ceiling for this spike')
                return 0

            if reached.rank < ServerReadinessLevel.PORT_BOUND.rank:
                print('    … waiting for port to bind…')
                time.sleep(2)
                continue
            time.sleep(1.0)

        print(f'    [timeout] reached {reached.value if reached else "none"} '
              f'(target rcon_ready)')
        print('    last log lines:')
        for line in last_lines[-8:]:
            print(f'      | {line}')
        return 5
    finally:
        if rcon is not None:
            try:
                rcon.close()
            except Exception:
                pass
        try:
            outcome = adapter.terminate(handle, graceful_deadline_s=10)
            print(f'    [teardown] terminate={outcome.exit_class.value} '
                  f'resolved={outcome.resolved}')
        except Exception as exc:  # noqa: BLE001
            print(f'    [teardown] failed: {exc}')
        finally:
            adapter.close_handle(handle)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not (args.vanilla_jar or args.paper_jar or args.forge_jar):
        print('error: at least one server jar is required')
        return 2

    world_root = args.world_dir or tempfile.mkdtemp(prefix='mcmanager-spike-')
    failures = 0

    spikes = [
        (args.vanilla_jar, ServerType.VANILLA),
        (args.paper_jar, ServerType.PAPER),
        (args.forge_jar, ServerType.FORGE),
    ]
    for jar_path, server_type in spikes:
        if not jar_path:
            continue
        rc = _spike_world(
            args.java, jar_path, server_type, args.base_port, args.mc_version,
            world_root, args.timeout_s,
        )
        failures += 0 if rc == 0 else 1
        print()

    if failures:
        print(f'spike finished with {failures} failure(s)')
        return 1
    print('spike finished: all supplied server types reached RCON_READY')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
