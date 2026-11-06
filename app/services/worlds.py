"""World lifecycle orchestration (Gate 3 — the Start/Stop/Kill driver).

``WorldsService`` is the only service that drives world state transitions
(off -> starting -> running -> stopping -> off, or -> crashed/error). It
composes the pre-launch gate (Doc 14 §4), the platform process adapter
(Doc 13), and the readiness hierarchy (Doc 14 §3) behind one durable
Operation row per state change (Doc 9 §1.1 derived world lock), and records
every launch/stop in ``runtime_sessions``.

The supervisor cadence (1s running / 15s idle, ``tuning.py``) is driven by
``poll_running()``; ``reconcile()`` is the boot path that re-attaches worlds
with an open ``runtime_sessions`` row after a manager crash (Doc 13 §5.1).
"""

from __future__ import annotations

import json
import secrets
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.domain.entities import WorldInstance
from app.domain.lifecycle import InvalidWorldTransition, transition_world
from app.domain.tuning import (
    START_READINESS_TIMEOUT_S,
    STOP_GRACEFUL_DEADLINE_S,
    SUPERVISOR_POLL_IDLE_S,
    SUPERVISOR_POLL_RUNNING_S,
)
from app.domain.value_objects import (
    ActorType,
    EndReason,
    OperationStatus,
    OperationType,
    ServerType,
    WorldState,
)
from app.infrastructure.sqlite.connection import SqliteStore
from app.ports.clock import Clock
from app.ports.minecraft import (
    LaunchContext,
    MinecraftRconError,
    MinecraftRconPort,
    MinecraftServerPort,
)
from app.ports.process_control import (
    ProbeFingerprint,
    ProcessControlPort,
    ProcessHandle,
    SpawnRequest,
)
from app.ports.secrets_store import SecretsStore, SecretType
from app.services.configuration import ConfigurationService
from app.services.operations import OperationInput, OperationService
from app.services.realtime import LogFanout

_RCON_PORT_OFFSET = 10


class WorldLifecycleError(Exception):
    """Base error for world lifecycle failures."""


class WorldNotFoundError(WorldLifecycleError):
    """No live world row for the given id."""


class WorldConflictError(WorldLifecycleError):
    """The requested transition conflicts with the world's current state."""


class StartTimeoutError(WorldLifecycleError):
    """The readiness ladder did not reach the target level in time."""


class SpawnFailedError(WorldLifecycleError):
    """The process adapter refused to spawn the world."""


@dataclass(frozen=True)
class LaunchRecord:
    """Everything captured at spawn time for a runtime session."""

    handle: ProcessHandle
    session_id: str
    rcon_password: str | None
    rcon_port: int | None


class WorldsService:
    """Composes gate + adapter + readiness ladder behind Operation rows."""

    def __init__(
        self,
        store: SqliteStore,
        clock: Clock,
        operations: OperationService,
        process_adapter: ProcessControlPort,
        secrets: SecretsStore,
        minecraft: MinecraftServerPort,
        logs: LogFanout | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._operations = operations
        self._adapter = process_adapter
        self._secrets = secrets
        self._minecraft = minecraft
        self._logs = logs

    # ------------------------------------------------------------------ start

    def start(
        self,
        *,
        world_id: str,
        actor_type: ActorType = ActorType.USER,
        actor_user_id: str | None = None,
        _allow_world_conflict: bool = False,
    ) -> str:
        """Run the full Start ladder. Returns the handle's session_id."""
        # Fast-fail before consuming the derived world lock.
        pre = self._world(world_id)
        if pre["state"] in (
            WorldState.STARTING.value,
            WorldState.RUNNING.value,
            WorldState.STOPPING.value,
        ):
            raise WorldConflictError(f'world {world_id} is already {pre["state"]}')
        pre_context = self._launch_context(pre)
        pre_gate = self._minecraft.validate_launch(pre_context)
        if not pre_gate.passed:
            if pre_gate.error_code == "EULA_NOT_ACCEPTED":
                self._set_world_state(world_id, WorldState.EULA_REQUIRED)
            raise WorldLifecycleError(f"{pre_gate.error_code}: {pre_gate.detail}")

        op = self._operations.create(
            OperationInput(
                op_type=OperationType.START,
                actor_type=actor_type,
                world_id=world_id,
                actor_user_id=actor_user_id,
            ),
            allow_world_conflict=_allow_world_conflict,
        )
        op_id = op["op_id"]
        try:
            self._operations.transition(
                op_id, OperationStatus.RUNNING, checkpoint={"stage": "validating"}
            )
            world = self._world(world_id)
            if world["state"] in (
                WorldState.STARTING.value,
                WorldState.RUNNING.value,
                WorldState.STOPPING.value,
            ):
                # A concurrent transition won the race: release the lock.
                self._operations.transition(
                    op_id, OperationStatus.CANCELLED, message="conflict with current state"
                )
                raise WorldConflictError(f'world {world_id} is already {world["state"]}')

            context = self._launch_context(world)
            gate = self._minecraft.validate_launch(context)
            if not gate.passed:
                self._fail_op(op_id, gate.error_code or "GATE_REJECTED", gate.detail)
                if gate.error_code == "EULA_NOT_ACCEPTED":
                    self._set_world_state(world_id, WorldState.EULA_REQUIRED)
                else:
                    self._set_world_state(world_id, WorldState.ERROR)
                raise WorldLifecycleError(f"{gate.error_code}: {gate.detail}")

            rcon_port, rcon_password = self._provision_rcon(context, world_id)
            argv = self._launch_command(world, context)
            session_id = f"rs_{uuid.uuid4().hex[:16]}"
            self._set_world_state(world_id, WorldState.STARTING)
            result = self._adapter.spawn(
                SpawnRequest(
                    world_id=world_id,
                    launch_command=argv,
                    cwd=context.world_dir,
                    env={},
                    session_id=session_id,
                    log_dir=str(self._log_root(world_id)),
                )
            )
            if result.handle is None:
                self._fail_op(op_id, "SPAWN_FAILED", result.spawn_error)
                self._set_world_state(world_id, WorldState.ERROR)
                raise SpawnFailedError(result.spawn_error or "spawn failed")

            session_id = self._open_session(
                world_id=world_id,
                world=world,
                context=context,
                handle=result.handle,
                argv=argv,
                rcon_port=rcon_port,
                rcon_password=rcon_password,
                session_id=session_id,
            )
            if self._logs is not None:
                self._attach_log_sink(world_id, result.handle)

            readiness = self._await_readiness(
                world_id=world_id,
                world=world,
                handle=result.handle,
                rcon_port=rcon_port,
                rcon_password=rcon_password,
            )
            self._set_world_state(world_id, WorldState.RUNNING)
            self._operations.transition(
                op_id,
                OperationStatus.COMPLETED,
                checkpoint={
                    "stage": "running",
                    "readiness": readiness,
                    "session_id": session_id,
                },
                data={"session_id": session_id},
            )
            return session_id
        except (WorldConflictError, StartTimeoutError, SpawnFailedError, WorldLifecycleError):
            raise
        except Exception as exc:
            self._fail_op(op_id, "START_ERROR", str(exc))
            self._set_world_state(world_id, WorldState.ERROR)
            raise WorldLifecycleError(str(exc)) from exc

    def _await_readiness(
        self,
        *,
        world_id: str,
        world: dict[str, Any],
        handle: ProcessHandle,
        rcon_port: int | None,
        rcon_password: str | None,
    ) -> str:
        server_type = ServerType(world["server_type"])
        target = self._minecraft.target_readiness_level(server_type)
        caps = self._minecraft.capabilities_for(server_type)
        port = int(world["port"])
        deadline = time.monotonic() + START_READINESS_TIMEOUT_S
        rcon: MinecraftRconPort | None = None
        rcon_ready = False

        while time.monotonic() < deadline:
            status = self._adapter.poll(handle)
            if not status.alive:
                raise StartTimeoutError(
                    f"world {world_id} process exited before ready: {status.exit_class.value}"
                )
            if rcon_port and rcon_password:
                if rcon is None:
                    rcon = self._rcon_client(rcon_port, rcon_password)
                    try:
                        rcon.connect()
                    except MinecraftRconError:
                        rcon.close()
                        rcon = None
                else:
                    try:
                        rcon_ready = rcon.ping()
                    except MinecraftRconError:
                        rcon_ready = False
                        rcon.close()
                        rcon = None
            state = self._minecraft.build_readiness_state(
                process_alive=True,
                port=port,
                rcon_ready=rcon_ready,
                host_is_minecraft=True,
                port_timeout_s=0.5,
            )
            level = self._minecraft.evaluate_readiness(
                server_type=server_type,
                caps=caps,
                state=state,
            )
            if level.rank >= target.rank:
                return level.value
            time.sleep(0.25)

        self._teardown(handle)
        raise StartTimeoutError(f"world {world_id} did not reach {target.value} in time")

    # ------------------------------------------------------------------- stop

    def stop(
        self,
        *,
        world_id: str,
        actor_type: ActorType = ActorType.USER,
        actor_user_id: str | None = None,
    ) -> str:
        """Graceful stop ladder: stdin stop -> RCON stop -> terminate(60s)."""
        self._world(world_id)
        op = self._operations.create(
            OperationInput(
                op_type=OperationType.STOP,
                actor_type=actor_type,
                world_id=world_id,
                actor_user_id=actor_user_id,
            )
        )
        op_id = op["op_id"]
        try:
            self._operations.transition(
                op_id, OperationStatus.RUNNING, checkpoint={"stage": "stopping"}
            )
            self._set_world_state(world_id, WorldState.STOPPING)
            closed = self._attempt_graceful_stop(world_id)
            self._close_session(
                world_id, EndReason.GRACEFUL_STOP if closed else EndReason.FORCED_STOP
            )
            self._set_world_state(world_id, WorldState.OFF)
            self._operations.transition(
                op_id, OperationStatus.COMPLETED, checkpoint={"stage": "off", "graceful": closed}
            )
            return str(op_id)
        except Exception as exc:
            self._fail_op(op_id, "STOP_ERROR", str(exc))
            raise WorldLifecycleError(str(exc)) from exc

    def _attempt_graceful_stop(self, world_id: str) -> bool:
        handle = self._resolve_handle(world_id)
        if handle is None:
            return True
        if self._adapter.write_stdin(handle, "stop").delivered and self._wait_exit(
            handle, STOP_GRACEFUL_DEADLINE_S
        ):
            return True
        try:
            self._rcon_command_quiet(world_id, "stop")
            if self._wait_exit(handle, STOP_GRACEFUL_DEADLINE_S):
                return True
        except MinecraftRconError:
            pass
        outcome = self._adapter.terminate(handle, graceful_deadline_s=STOP_GRACEFUL_DEADLINE_S)
        return bool(outcome.resolved and "grace" in outcome.exit_class.value)

    # ------------------------------------------------------------------- kill

    def kill(
        self,
        *,
        world_id: str,
        actor_type: ActorType = ActorType.USER,
        actor_user_id: str | None = None,
    ) -> str:
        """Immediate forced termination (graceful_deadline_s=0, C3)."""
        self._world(world_id)
        op = self._operations.create(
            OperationInput(
                op_type=OperationType.KILL,
                actor_type=actor_type,
                world_id=world_id,
                actor_user_id=actor_user_id,
            )
        )
        op_id = op["op_id"]
        try:
            self._operations.transition(
                op_id, OperationStatus.RUNNING, checkpoint={"stage": "killing"}
            )
            self._set_world_state(world_id, WorldState.STOPPING)
            handle = self._resolve_handle(world_id)
            if handle is not None:
                self._adapter.terminate(handle, graceful_deadline_s=0)
            self._close_session(world_id, EndReason.FORCED_STOP)
            self._set_world_state(world_id, WorldState.OFF)
            self._operations.transition(
                op_id, OperationStatus.COMPLETED, checkpoint={"stage": "off"}
            )
            return str(op_id)
        except Exception as exc:
            self._fail_op(op_id, "KILL_ERROR", str(exc))
            raise WorldLifecycleError(str(exc)) from exc

    # ------------------------------------------------------- supervisor / boot

    def poll_running(self) -> list[str]:
        """Supervisor cadence: classify crashes for worlds with open sessions.

        Returns the world_ids whose processes are no longer alive. The
        caller (scheduler/supervisor loop) publishes notifications.
        """
        crashed: list[str] = []
        for row in self._open_sessions():
            world_id = row["world_id"]
            handle = self._resolve_handle(world_id)
            alive = False
            if handle is not None:
                alive = self._adapter.poll(handle).alive
            if alive:
                continue
            operation = self._operations.create(
                OperationInput(
                    op_type=OperationType.CRASH_DETECTED,
                    actor_type=ActorType.SYSTEM,
                    world_id=world_id,
                    data={"detected_at": self._clock.now()},
                ),
                allow_world_conflict=True,
            )
            operation_id = str(operation['op_id'])
            self._operations.transition(
                operation_id,
                OperationStatus.RUNNING,
                checkpoint={'stage': 'crash_detected'},
            )
            self._close_session(world_id, EndReason.CRASHED)
            self._set_world_state(world_id, WorldState.CRASHED)
            self._operations.transition(
                operation_id,
                OperationStatus.COMPLETED,
                checkpoint={'stage': 'crashed'},
            )
            crashed.append(world_id)
        return crashed

    def supervisor_interval_seconds(self) -> float:
        """Return the locked supervisor cadence for active vs. idle runtimes."""
        row = self._store.reader().execute(
            """
            SELECT 1
            FROM world_instances
            WHERE deleted_at IS NULL AND state IN (?, ?, ?)
            LIMIT 1
            """,
            (WorldState.STARTING.value, WorldState.RUNNING.value, WorldState.STOPPING.value),
        ).fetchone()
        return SUPERVISOR_POLL_RUNNING_S if row is not None else SUPERVISOR_POLL_IDLE_S

    def reconcile(self) -> list[str]:
        """Boot reconciliation (Doc 13 §5.1): re-attach open sessions.

        A fresh adapter has an empty registry; this re-attaches by probing
        the launch fingerprint captured at spawn time. Returns re-attached
        world_ids.
        """
        reattached: list[str] = []
        for row in self._open_sessions():
            world_id = row["world_id"]
            snapshot = json.loads(row["launch_args_snapshot"] or "{}")
            fingerprint = ProbeFingerprint(
                pid=snapshot.get("pid"),
                spawn_epoch=snapshot.get("spawn_epoch"),
                cwd=snapshot.get("cwd"),
                launch_marker=snapshot.get("launch_marker"),
            )
            probe = self._adapter.probe(world_id, str(row["session_id"]), fingerprint=fingerprint)
            if probe.found and probe.matched_launch:
                self._set_world_state(world_id, WorldState.RUNNING)
                reattached.append(world_id)
            else:
                self._close_session(world_id, EndReason.RECONCILED_MISSING)
                self._set_world_state(world_id, WorldState.CRASHED)
        return reattached

    # ------------------------------------------------------------- read model

    def world_summary(self, world_id: str) -> dict[str, Any]:
        world = self._world(world_id)
        return {
            "world_id": world["world_id"],
            "display_name": world["display_name"],
            "server_type": world["server_type"],
            "mc_version": world["mc_version"],
            "port": world["port"],
            "state": world["state"],
            "addressing_strategy": world["addressing_strategy"],
            "addressing_value": world["addressing_value"],
        }

    def list_worlds(self) -> list[dict[str, Any]]:
        rows = (
            self._store.reader()
            .execute(
                "SELECT * FROM world_instances WHERE deleted_at IS NULL ORDER BY created_at DESC"
            )
            .fetchall()
        )
        return [self.world_summary(row["world_id"]) for row in rows]

    # ---------------------------------------------------------------- helpers

    def _world(self, world_id: str) -> dict[str, Any]:
        row = (
            self._store.reader()
            .execute("SELECT * FROM world_instances WHERE world_id = ?", (world_id,))
            .fetchone()
        )
        if row is None:
            raise WorldNotFoundError(world_id)
        return dict(row)

    def _launch_context(self, world: dict[str, Any]) -> LaunchContext:
        java = (
            self._store.reader()
            .execute(
                "SELECT executable_path FROM java_runtimes WHERE runtime_id = ?",
                (world["java_runtime_id"],),
            )
            .fetchone()
        )
        if java is None:
            raise WorldLifecycleError(f'java runtime missing: {world["java_runtime_id"]}')
        world_dir = self._world_dir(world)
        raw = world.get("launch_args")
        parsed_override: list[str] | None = None
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except (ValueError, TypeError):
                parsed = None
            if (
                isinstance(parsed, list)
                and parsed
                and all(isinstance(part, str) for part in parsed)
            ):
                parsed_override = parsed

        launch_args = parsed_override if parsed_override is not None else self._launch_args(world)
        jar = self._find_jar(world_dir) if parsed_override is None else ""
        return LaunchContext(
            world_id=world["world_id"],
            server_type=ServerType(world["server_type"]),
            mc_version=world["mc_version"],
            world_dir=str(world_dir),
            java_path=java["executable_path"],
            server_jar_path=jar,
            port=int(world["port"]),
            rcon_enabled=True,
            rcon_port=int(world["port"]) + _RCON_PORT_OFFSET,
            launch_args=launch_args,
        )

    def _world_dir(self, world: dict[str, Any]) -> Path:
        if world["addressing_strategy"] == "path":
            candidate = Path(world["addressing_value"])
            if candidate.is_absolute():
                return candidate
        try:
            root = ConfigurationService(self._store, self._clock).resolve_effective(
                world["world_id"]
            )["minecraft_root_path"]
        except KeyError:
            root = "worlds"
        base = Path(str(root))
        return base / str(world["display_name"])

    def _log_root(self, world_id: str) -> Path:
        try:
            root = ConfigurationService(self._store, self._clock).resolve_effective(
                world_id
            )['log_root_path']
        except KeyError:
            root = 'logs'
        return Path(str(root or 'logs'))

    def _find_jar(self, world_dir: Path) -> str:
        candidates = sorted(world_dir.glob("*.jar")) if world_dir.exists() else []
        if candidates:
            return str(candidates[0])
        return ""

    def _launch_command(self, world: dict[str, Any], context: LaunchContext) -> list[str]:
        """Explicit argv for the spawn. A world row storing a full argv list
        (e.g. a test double or custom launcher) wins; otherwise the gate
        builds ``java -Xmx... -jar jar nogui`` — never a shell string."""
        raw = world.get("launch_args")
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except (ValueError, TypeError):
                parsed = None
            if (
                isinstance(parsed, list)
                and parsed
                and all(isinstance(part, str) for part in parsed)
            ):
                return parsed
        return self._minecraft.build_launch_argv(
            context.java_path,
            self._extra_java_args(world),
            context.server_jar_path,
            context.launch_args,
        )

    def _launch_args(self, world: dict[str, Any]) -> list[str]:
        try:
            data = json.loads(world["launch_args"] or "{}")
        except (ValueError, TypeError):
            return []
        if isinstance(data, list):
            # Full-argv override: nothing extra to append server-side.
            return []
        return list(data.get("server_args", []))

    def _extra_java_args(self, world: dict[str, Any]) -> list[str]:
        try:
            data = json.loads(world.get("launch_args") or "{}")
        except (ValueError, TypeError):
            return []
        if isinstance(data, dict):
            return list(data.get("java_args", []))
        return []

    def _provision_rcon(self, context: LaunchContext, world_id: str) -> tuple[int, str]:
        rcon_port = context.rcon_port
        password = secrets.token_urlsafe(12)
        world_dir = Path(context.world_dir)
        world_dir.mkdir(parents=True, exist_ok=True)
        props_path = world_dir / "server.properties"
        props: dict[str, str] = {}
        if props_path.exists():
            for line in props_path.read_text(encoding="utf-8", errors="replace").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, _, value = stripped.partition("=")
                props[key.strip()] = value.strip()
        props["enable-rcon"] = "true"
        props["rcon.port"] = str(rcon_port)
        props["rcon.password"] = password
        lines = [f"{key}={value}" for key, value in props.items()]
        props_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        return rcon_port, password

    def _open_session(
        self,
        *,
        world_id: str,
        world: dict[str, Any],
        context: LaunchContext,
        handle: ProcessHandle,
        argv: list[str],
        rcon_port: int | None,
        rcon_password: str | None,
        session_id: str,
    ) -> str:
        secret_id = None
        if rcon_port and rcon_password:
            secret_id = self._secrets.store(
                secret_type=SecretType.RCON_CREDENTIAL,
                associated_entity_type="runtime_session",
                associated_entity_id=session_id,
                plaintext=rcon_password,
            )
        launch_marker = next(
            (part for part in argv if "--marker=" in part or part.endswith(".jar")),
            argv[-1] if argv else "",
        )
        snapshot = json.dumps(
            {
                "argv": argv,
                "pid": handle.pid,
                "spawn_epoch": handle.spawn_epoch,
                "cwd": context.world_dir,
                "launch_marker": launch_marker,
            }
        )
        now = int(self._clock.now())
        connection = self._store.writer()
        connection.execute(
            """
            INSERT INTO runtime_sessions (
                session_id, world_id, started_at, ended_at, end_reason,
                rcon_secret_id, port_used, java_runtime_id, launch_args_snapshot,
                rcon_port, created_at
            ) VALUES (?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                world_id,
                now,
                secret_id,
                int(world["port"]),
                world["java_runtime_id"],
                snapshot,
                rcon_port,
                now,
            ),
        )
        connection.commit()
        return session_id

    def _attach_log_sink(self, world_id: str, handle: ProcessHandle) -> None:
        def sink(*, world_id: str, session_token: str, channel: str, line: str) -> None:
            if self._logs is not None:
                self._logs.append(
                    world_id=world_id,
                    session_id=session_token or "",
                    channel=channel,
                    line=line,
                    ts=int(self._clock.now()),
                )

        self._adapter.tail(handle, sink)

    def _resolve_handle(self, world_id: str) -> ProcessHandle | None:
        probe = self._adapter.probe(world_id, "")
        return probe.handle if probe.found else None

    def _rcon_client(self, port: int, password: str) -> MinecraftRconPort:
        return self._minecraft.open_rcon("127.0.0.1", port, password, timeout_s=1.0)

    def _rcon_command_quiet(self, world_id: str, command: str) -> None:
        row = (
            self._store.reader()
            .execute(
                """
            SELECT rcon_secret_id, rcon_port FROM runtime_sessions
            WHERE world_id = ? AND ended_at IS NULL ORDER BY created_at DESC LIMIT 1
            """,
                (world_id,),
            )
            .fetchone()
        )
        if row is None or not row["rcon_port"] or not row["rcon_secret_id"]:
            return
        password = self._secrets.read(row["rcon_secret_id"])
        client = self._minecraft.open_rcon("127.0.0.1", row["rcon_port"], password)
        try:
            client.connect()
            client.command(command)
        finally:
            client.close()

    def _wait_exit(self, handle: ProcessHandle, timeout_s: int) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if not self._adapter.poll(handle).alive:
                return True
            time.sleep(0.5)
        return not self._adapter.poll(handle).alive

    def _teardown(self, handle: ProcessHandle) -> None:
        try:
            self._adapter.terminate(handle, graceful_deadline_s=STOP_GRACEFUL_DEADLINE_S)
        finally:
            self._adapter.close_handle(handle)

    def _close_session(self, world_id: str, reason: EndReason) -> None:
        now = int(self._clock.now())
        connection = self._store.writer()
        connection.execute(
            "UPDATE runtime_sessions SET ended_at = ?, end_reason = ? WHERE world_id = ? AND ended_at IS NULL",
            (now, reason.value, world_id),
        )
        connection.commit()

    def _open_sessions(self) -> list[dict[str, Any]]:
        rows = (
            self._store.reader()
            .execute("SELECT * FROM runtime_sessions WHERE ended_at IS NULL")
            .fetchall()
        )
        return [dict(row) for row in rows]

    def _set_world_state(self, world_id: str, state: WorldState) -> None:
        connection = self._store.writer()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT state, pre_backup_state FROM world_instances WHERE world_id = ?",
                (world_id,),
            ).fetchone()
            if row is None:
                raise WorldNotFoundError(f"world not found: {world_id}")
            world = WorldInstance(
                world_id=world_id,
                state=WorldState(row["state"]),
                pre_backup_state=(
                    WorldState(row["pre_backup_state"])
                    if row["pre_backup_state"] is not None
                    else None
                ),
            )
            try:
                transitioned, _ = transition_world(
                    world,
                    state,
                    occurred_at=int(self._clock.now()),
                )
            except InvalidWorldTransition as exc:
                raise WorldConflictError(str(exc)) from exc
            connection.execute(
                """
                UPDATE world_instances
                SET state = ?, pre_backup_state = ?, updated_at = ?
                WHERE world_id = ?
                """,
                (
                    transitioned.state.value,
                    transitioned.pre_backup_state.value
                    if transitioned.pre_backup_state is not None
                    else None,
                    int(self._clock.now()),
                    world_id,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def _fail_op(self, op_id: str, error_code: str, message: str | None) -> None:
        self._operations.transition(
            op_id,
            OperationStatus.FAILED,
            error_code=error_code,
            message=message,
        )
