"""Concrete MinecraftServerPort — composed only at the bootstrap root."""

from __future__ import annotations

from app.domain.value_objects import EulaState, ServerReadinessLevel, ServerType
from app.infrastructure.minecraft.capabilities import capabilities_for
from app.infrastructure.minecraft.eula import accept, current_state
from app.infrastructure.minecraft.gate import build_launch_argv, validate_launch
from app.infrastructure.minecraft.rcon import RconClient
from app.infrastructure.minecraft.readiness import (
    build_state,
    evaluate,
    target_level_for,
)
from app.ports.minecraft import (
    GateResult,
    LaunchContext,
    MinecraftCapabilities,
    MinecraftRconPort,
    ReadinessState,
)


class MinecraftServerAdapter:
    """Infrastructure implementation of ``MinecraftServerPort`` (G1-1)."""

    def capabilities_for(self, server_type: ServerType) -> MinecraftCapabilities:
        return capabilities_for(server_type)

    def target_readiness_level(self, server_type: ServerType) -> ServerReadinessLevel:
        return target_level_for(server_type)

    def evaluate_readiness(
        self,
        *,
        server_type: ServerType,
        caps: MinecraftCapabilities,
        state: ReadinessState,
        rcon_enabled: bool = True,
    ) -> ServerReadinessLevel:
        return evaluate(
            server_type=server_type,
            caps=caps,
            state=state,
            rcon_enabled=rcon_enabled,
        )

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
    ) -> ReadinessState:
        return build_state(
            process_alive=process_alive,
            port=port,
            rcon_ready=rcon_ready,
            probe_ok=probe_ok,
            operationally_valid=operationally_valid,
            host=host,
            port_timeout_s=port_timeout_s,
            host_is_minecraft=host_is_minecraft,
        )

    def validate_launch(self, context: LaunchContext) -> GateResult:
        return validate_launch(context)

    def build_launch_argv(
        self, java_path: str, java_args: list[str], jar: str, jar_args: list[str]
    ) -> list[str]:
        return build_launch_argv(java_path, java_args, jar, jar_args)

    def detect_eula(self, world_dir: str) -> EulaState:
        return current_state(world_dir)

    def accept_eula(self, world_dir: str, operator_id: str | None = None) -> None:
        accept(world_dir, operator_id=operator_id)

    def open_rcon(
        self, host: str, port: int, password: str, timeout_s: float = 5.0
    ) -> MinecraftRconPort:
        return RconClient(host, port, password, timeout_s=timeout_s)
