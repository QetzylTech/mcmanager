"""Minecraft adapter — Doc 14 capability record evaluation."""

from __future__ import annotations

from app.domain.value_objects import ServerType
from app.ports.minecraft import MinecraftCapabilities


CAPABILITY_MATRIX: dict[ServerType, MinecraftCapabilities] = {
    ServerType.VANILLA: MinecraftCapabilities(
        rcon=True,
        protocol_ping=True,
        save_coordination='rcon',
        tps_metric=False,
    ),
    ServerType.PAPER: MinecraftCapabilities(
        rcon=True,
        protocol_ping=True,
        paper_api=True,
        save_coordination='paper_api',
        tps_metric=True,
    ),
    ServerType.FABRIC: MinecraftCapabilities(
        rcon=True,
        protocol_ping=True,
        save_coordination='rcon',
        tps_metric=False,
    ),
    ServerType.FORGE: MinecraftCapabilities(
        rcon=True,
        protocol_ping=True,
        save_coordination='rcon',
        tps_metric=False,
    ),
}


def capabilities_for(server_type: ServerType) -> MinecraftCapabilities:
    """Return the declared capability record (Doc 14 section 2).

    Unknown types raise; the UI renders only supported actions.
    """
    if server_type not in CAPABILITY_MATRIX:
        raise ValueError(f'unknown server type: {server_type}')
    return CAPABILITY_MATRIX[server_type]
