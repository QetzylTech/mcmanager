"""Readiness evaluator per server type (Document 14 section 3).

``starting -> running`` fires only at the highest available level for the
server type. Log strings are advisory evidence only — never the sole signal.
"""

from __future__ import annotations

import socket

from app.domain.value_objects import ServerReadinessLevel, ServerType
from app.infrastructure.minecraft.ping import ping_protocol
from app.ports.minecraft import MinecraftCapabilities, ReadinessState, evaluate_readiness

# Per-type default target levels (Doc 14 section 3).
DEFAULT_TARGET_LEVELS: dict[ServerType, ServerReadinessLevel] = {
    ServerType.VANILLA: ServerReadinessLevel.PROBE_OK,
    ServerType.PAPER: ServerReadinessLevel.OPERATIONALLY_VALID,
    ServerType.FABRIC: ServerReadinessLevel.PROBE_OK,
    ServerType.FORGE: ServerReadinessLevel.PROBE_OK,
}


def target_level_for(server_type: ServerType) -> ServerReadinessLevel:
    """Configured readiness target for a server type."""
    return DEFAULT_TARGET_LEVELS.get(server_type, ServerReadinessLevel.PROBE_OK)


def port_is_bound(host: str, port: int, timeout_s: float = 1.0) -> bool:
    """TCP connect probe (Doc 13 C8 minimum floor)."""
    if port <= 0:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def evaluate(
    *,
    server_type: ServerType,
    caps: MinecraftCapabilities,
    state: ReadinessState,
    rcon_enabled: bool = True,
) -> ServerReadinessLevel:
    """Resolve the world's current readiness level.

    The target level is capped by the server type's declared capabilities:
    a port-bound-only check is the minimum; the hierarchy is authoritative.
    """
    target = target_level_for(server_type)
    rcon_applicable = bool(caps.rcon and rcon_enabled)
    if not rcon_applicable:
        # RCON is not an applicable ladder rung (gate1 Module 4: skip level 3).
        state = ReadinessState(
            process_alive=state.process_alive,
            port_bound=state.port_bound,
            rcon_ready=True,
            probe_ok=state.probe_ok,
            operationally_valid=state.operationally_valid,
        )
        if target is ServerReadinessLevel.OPERATIONALLY_VALID:
            target = ServerReadinessLevel.PROBE_OK
    if target is ServerReadinessLevel.OPERATIONALLY_VALID and not caps.paper_api:
        target = ServerReadinessLevel.PROBE_OK
    return evaluate_readiness(state, target)


def build_state(
    *,
    process_alive: bool,
    port: int,
    rcon_ready: bool = False,
    probe_ok: bool = False,
    operationally_valid: bool = False,
    host: str = '127.0.0.1',
    port_timeout_s: float = 1.0,
    host_is_minecraft: bool = True,
) -> ReadinessState:
    """Build a ReadinessState from live signals.

    Higher readiness signals are only valid behind the lower ladder: a bound
    port is required before protocol-ping or higher signals can count, and a
    non-Minecraft listener never claims a probe outcome.
    """
    bound = port_is_bound(host, port, port_timeout_s)
    live_probe = (
        bound and process_alive and host_is_minecraft and ping_protocol(host, port, port_timeout_s)
    )
    effective_probe = bool(process_alive and bound and host_is_minecraft and probe_ok) or live_probe
    effective_rcon = bool(rcon_ready and bound and process_alive)
    effective_operational = bool(
        operationally_valid and process_alive and bound and rcon_ready and effective_probe
    )
    return ReadinessState(
        process_alive=process_alive,
        port_bound=bound,
        rcon_ready=effective_rcon,
        probe_ok=effective_probe,
        operationally_valid=effective_operational,
    )
