"""Minecraft server abstraction port (Document 14).

Defines the capability record, readiness evaluator, EULA state model,
property schema validator, and Java compatibility matrix that Minecraft
adapters implement. Services depend on this interface.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol

from app.domain.value_objects import EulaState, ServerReadinessLevel, ServerType


def _version_tuple(version: str) -> tuple[int, ...]:
    """Comparable numeric prefix for Minecraft versions such as 1.20.4."""
    parts: list[int] = []
    for raw in version.split('.'):
        digits = ''
        for char in raw:
            if not char.isdigit():
                break
            digits += char
        if digits == '':
            break
        parts.append(int(digits))
    return tuple(parts)


def _version_lt(left: str, right: str) -> bool:
    return _version_tuple(left) < _version_tuple(right)


def _version_gt(left: str, right: str) -> bool:
    return _version_tuple(left) > _version_tuple(right)


@dataclass(frozen=True)
class MinecraftCapabilities:
    """Declared capabilities for a server type + version.

    ``False``/``None`` means "not provided" per Doc 14 section 2 semantics.
    """

    rcon: bool = False
    protocol_ping: bool = False
    paper_api: bool = False
    save_coordination: str | None = None  # 'rcon' | 'paper_api' | None
    tps_metric: bool = False


# --- EULA (Doc 14 section 5) -------------------------------------------------

def detect_eula(world_dir: str, file_name: str = 'eula.txt') -> EulaState:
    """Read ``eula.txt`` from a world directory and return its state."""
    path = os.path.join(world_dir, file_name)
    if not os.path.exists(path):
        return EulaState.NOT_PRESENT

    with open(path, 'r', encoding='utf-8', errors='replace') as handle:
        content = handle.read()

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith('#') or '=' not in stripped:
            continue
        key, _, value = stripped.partition('=')
        if key.strip().lower() == 'eula':
            return (
                EulaState.ACCEPTED
                if value.strip().lower() == 'true'
                else EulaState.UNACCEPTED
            )
    return EulaState.UNACCEPTED


def write_eula_acceptance(
    world_dir: str, file_name: str = 'eula.txt', *, operator_id: str | None = None
) -> None:
    """Write an accepted ``eula.txt`` — the ONLY ``eula=true`` writer.

    Called exclusively after explicit audited operator acceptance
    (ConfigEdit Entity=eula, Doc 14 section 5 / gate1 Module 4).
    """
    path = os.path.join(world_dir, file_name)
    with open(path, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(
            '# By changing the setting below to TRUE you are indicating your '
            'agreement to our EULA.\n'
        )
        handle.write('# https://aka.ms/MinecraftEULA\n')
        if operator_id:
            handle.write('# Explicitly accepted via mcmanager audit pipeline\n')
            handle.write(f'# Accepted by Operator: {operator_id}\n')
        handle.write('eula=true\n')


# --- Readiness (Doc 14 section 3) ---------------------------------------------

@dataclass(frozen=True)
class ReadinessState:
    """Snapshot of the signals available for a world's readiness ladder."""

    process_alive: bool = False
    port_bound: bool = False
    rcon_ready: bool = False
    probe_ok: bool = False
    operationally_valid: bool = False


def evaluate_readiness(
    state: ReadinessState, target_level: ServerReadinessLevel
) -> ServerReadinessLevel:
    """Pure evaluator: highest confirmed level at-or-below the target.

    A level is only confirmed when every lower level is also confirmed, so
    the ladder climbs one signal at a time and stops at the first gap.
    """
    highest = ServerReadinessLevel.PROCESS_ALIVE
    for level in (
        ServerReadinessLevel.PROCESS_ALIVE,
        ServerReadinessLevel.PORT_BOUND,
        ServerReadinessLevel.RCON_READY,
        ServerReadinessLevel.PROBE_OK,
        ServerReadinessLevel.OPERATIONALLY_VALID,
    ):
        if level.rank > target_level.rank:
            # Above the target: the type cannot reach a higher signal.
            break
        if not getattr(state, level.value):
            break
        highest = level
    return highest


# --- server.properties schema (Doc 14 section 6) --------------------------------

@dataclass(frozen=True)
class PropertySpec:
    """One schema row for a property across a version range."""

    key: str
    value_type: str  # 'int' | 'str' | 'bool' | 'enum'
    default: str | int | None = None
    min_supported_version: str = '1.0'
    max_supported_version: str | None = None  # None = still current
    deprecated_in: str | None = None
    replaced_by_gamerule: str | None = None
    enum_values: tuple[str, ...] = ()


def validate_property_schema(
    *,
    key: str,
    value: object,
    server_type: ServerType,
    mc_version: str,
    specs: dict[str, PropertySpec],
) -> tuple[bool, str | None]:
    """Validate a property for the server type/version against the schema.

    Returns ``(ok, error_code)`` where error_code is
    ``CONFIG_INVALID_KEY`` or ``CONFIG_INVALID_VALUE``.
    """
    spec = specs.get(key)
    if spec is None:
        return False, 'CONFIG_INVALID_KEY'
    if _version_lt(mc_version, spec.min_supported_version):
        return False, 'CONFIG_INVALID_KEY'
    if (
        spec.max_supported_version is not None
        and spec.deprecated_in is None
        and _version_gt(mc_version, spec.max_supported_version)
    ):
        return False, 'CONFIG_INVALID_KEY'

    if spec.value_type == 'int':
        if not isinstance(value, int):
            return False, 'CONFIG_INVALID_VALUE'
    elif spec.value_type == 'bool':
        if not isinstance(value, bool):
            return False, 'CONFIG_INVALID_VALUE'
    elif spec.value_type == 'enum':
        if value not in spec.enum_values:
            return False, 'CONFIG_INVALID_VALUE'
    elif not isinstance(value, str):
        return False, 'CONFIG_INVALID_VALUE'
    return True, None


def default_property_specs() -> dict[str, PropertySpec]:
    """Curated reference data: modern Vanilla/Paper core properties."""
    return {
        'server-port': PropertySpec('server-port', 'int'),
        'server-ip': PropertySpec('server-ip', 'str'),
        'online-mode': PropertySpec('online-mode', 'bool', default=True),
        'motd': PropertySpec('motd', 'str'),
        'level-name': PropertySpec('level-name', 'str'),
        'level-seed': PropertySpec('level-seed', 'str'),
        'enable-rcon': PropertySpec('enable-rcon', 'bool', default=False),
        'rcon.port': PropertySpec('rcon.port', 'int'),
        'rcon.password': PropertySpec('rcon.password', 'str'),
        'enable-query': PropertySpec('enable-query', 'bool', default=False),
        'query.port': PropertySpec('query.port', 'int'),
        'difficulty': PropertySpec(
            'difficulty',
            'enum',
            default='easy',
            enum_values=('peaceful', 'easy', 'normal', 'hard'),
        ),
        'gamemode': PropertySpec(
            'gamemode',
            'enum',
            default='survival',
            enum_values=('survival', 'creative', 'adventure', 'spectator'),
        ),
        'spawn-protection': PropertySpec('spawn-protection', 'int', default=16),
        'max-players': PropertySpec('max-players', 'int', default=20),
        'view-distance': PropertySpec('view-distance', 'int', default=10),
        'white-list': PropertySpec('white-list', 'bool', default=False),
        'enforce-whitelist': PropertySpec('enforce-whitelist', 'bool', default=False),
    }


# --- Java compatibility (Doc 14 section 7) -------------------------------------

@dataclass(frozen=True)
class JavaCompatibility:
    """Compatibility record per (server_type, mc_version)."""

    supported_major: tuple[int, ...]
    recommended_major: int
    minimum_major: int


JAVA_COMPATIBILITY: dict[tuple[ServerType, str], JavaCompatibility] = {
    (ServerType.VANILLA, '1.20'): JavaCompatibility((17, 21), 21, 17),
    (ServerType.VANILLA, '1.21'): JavaCompatibility((21,), 21, 21),
    (ServerType.PAPER, '1.20'): JavaCompatibility((17, 21), 21, 17),
    (ServerType.PAPER, '1.21'): JavaCompatibility((21,), 21, 21),
    (ServerType.FABRIC, '1.20'): JavaCompatibility((17, 21), 21, 17),
    (ServerType.FABRIC, '1.21'): JavaCompatibility((21,), 21, 21),
    (ServerType.FORGE, '1.20'): JavaCompatibility((17, 21), 21, 17),
    (ServerType.FORGE, '1.21'): JavaCompatibility((21,), 21, 21),
}


def java_compatibility_for(
    server_type: ServerType, mc_version: str
) -> JavaCompatibility | None:
    """Return the compatibility record, or None when unknown."""
    for (known_type, known_version), record in JAVA_COMPATIBILITY.items():
        if known_type is server_type and mc_version.startswith(known_version):
            return record
    return None


def java_major_compatible(
    *, server_type: ServerType, mc_version: str, java_major: int
) -> bool:
    """Doc 14 section 7: is this Java major within the supported range?"""
    record = java_compatibility_for(server_type, mc_version)
    if record is None:
        return False
    return java_major in record.supported_major


@dataclass(frozen=True)
class LaunchContext:
    """Launch-time inputs the pre-spawn gate validates (Doc 14 §4)."""

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


class MinecraftRconError(Exception):
    """RCON transport/protocol/allowlist failure (port-level)."""


class MinecraftRconPort(Protocol):
    """Session-scoped RCON client (Doc 14 §8)."""

    def connect(self) -> None: ...

    def ping(self) -> bool: ...

    def command(self, command: str) -> str: ...

    def close(self) -> None: ...


class MinecraftServerPort(Protocol):
    """Minecraft adapter port injected at the composition root (Doc 12 / G1-1)."""

    def capabilities_for(self, server_type: ServerType) -> MinecraftCapabilities: ...

    def target_readiness_level(self, server_type: ServerType) -> ServerReadinessLevel: ...

    def evaluate_readiness(
        self,
        *,
        server_type: ServerType,
        caps: MinecraftCapabilities,
        state: ReadinessState,
        rcon_enabled: bool = True,
    ) -> ServerReadinessLevel: ...

    def build_readiness_state(
        self,
        *,
        process_alive: bool,
        port: int,
        rcon_ready: bool = False,
        probe_ok: bool = False,
        operationally_valid: bool = False,
        host: str = '127.0.0.1',
        port_timeout_s: float = 1.0,
        host_is_minecraft: bool = True,
    ) -> ReadinessState: ...

    def validate_launch(self, context: LaunchContext) -> GateResult: ...

    def build_launch_argv(
        self, java_path: str, java_args: list[str], jar: str, jar_args: list[str]
    ) -> list[str]: ...

    def detect_eula(self, world_dir: str) -> EulaState: ...

    def accept_eula(self, world_dir: str, operator_id: str | None = None) -> None: ...

    def open_rcon(
        self, host: str, port: int, password: str, timeout_s: float = 5.0
    ) -> MinecraftRconPort: ...
