"""Pre-launch validation gate (Doc 14 section 4).

Runs before Start dispatch and again immediately before spawn. Rejects with
error codes; no process is ever spawned past a failed gate.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from app.domain.value_objects import EulaState, ServerType
from app.infrastructure.minecraft.eula import current_state
from app.infrastructure.minecraft.java_compatibility import detect_java
from app.ports.minecraft import java_major_compatible

ERROR_JAVA_INCOMPATIBLE = 'JAVA_INCOMPATIBLE'
ERROR_EULA_NOT_ACCEPTED = 'EULA_NOT_ACCEPTED'
ERROR_JAR_MISSING = 'JAR_MISSING'
ERROR_WORLD_DIR_MISSING = 'WORLD_DIR_MISSING'
ERROR_PORT_CONFLICT = 'WORLD_PORT_CONFLICT'


@dataclass(frozen=True)
class LaunchContext:
    """The launch-time inputs the gate validates."""

    world_id: str
    server_type: ServerType
    mc_version: str
    world_dir: str
    java_path: str
    server_jar_path: str
    port: int
    rcon_enabled: bool = False
    rcon_port: int = 0
    launch_args: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GateResult:
    """Outcome of the pre-launch gate."""

    passed: bool
    error_code: str | None = None
    detail: str | None = None
    eula_state: EulaState | None = None
    java_major: int | None = None


def _port_conflict(port: int) -> bool:
    """True when the TCP port is already bound (checked for MC + RCON)."""
    if port <= 0:
        return False
    import socket

    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.5):
            return True
    except OSError:
        return False


def validate_launch(context: LaunchContext) -> GateResult:
    """Validate the full Doc 14 section 4 pre-launch set in order.

    1. World directory exists -> WORLD_DIR_MISSING.
    2. EULA state -> EULA_NOT_ACCEPTED (world -> eula_required).
    3. Server JAR exists -> JAR_MISSING.
    4. Port + RCON port availability -> WORLD_PORT_CONFLICT.
    5. Java compatibility -> JAVA_INCOMPATIBLE (no spawn).
    """
    if not os.path.isdir(context.world_dir):
        return GateResult(
            passed=False,
            error_code=ERROR_WORLD_DIR_MISSING,
            detail=f'world dir missing: {context.world_dir}',
        )

    eula_state = current_state(context.world_dir)
    if eula_state is not EulaState.ACCEPTED:
        return GateResult(
            passed=False,
            error_code=ERROR_EULA_NOT_ACCEPTED,
            detail='eula.txt not accepted',
            eula_state=eula_state,
        )

    if not os.path.isfile(context.server_jar_path):
        return GateResult(
            passed=False,
            error_code=ERROR_JAR_MISSING,
            detail=f'jar not found: {context.server_jar_path}',
        )

    if _port_conflict(context.port):
        return GateResult(
            passed=False,
            error_code=ERROR_PORT_CONFLICT,
            detail=f'port {context.port} already bound',
        )
    if context.rcon_enabled and _port_conflict(context.rcon_port):
        return GateResult(
            passed=False,
            error_code=ERROR_PORT_CONFLICT,
            detail=f'rcon port {context.rcon_port} already bound',
        )

    detection = detect_java(context.java_path)
    if detection is None or detection.major <= 0:
        return GateResult(
            passed=False,
            error_code=ERROR_JAVA_INCOMPATIBLE,
            detail=f'java not runnable at {context.java_path}',
        )
    if not java_major_compatible(
        server_type=context.server_type,
        mc_version=context.mc_version,
        java_major=detection.major,
    ):
        return GateResult(
            passed=False,
            error_code=ERROR_JAVA_INCOMPATIBLE,
            detail=(
                f'java {detection.major} incompatible with '
                f'{context.server_type.value} {context.mc_version}'
            ),
            java_major=detection.major,
        )

    return GateResult(passed=True, java_major=detection.major)


def build_launch_argv(java_path: str, java_args: list[str], jar: str, jar_args: list[str]) -> list[str]:
    """Assemble the data-driven argv (Doc 13 section 1.1: never a shell string).

    ``java_path -Xmx... -jar jar.jar -Xms... nogui`` etc.
    """
    return [java_path, *java_args, '-jar', jar, *jar_args]
