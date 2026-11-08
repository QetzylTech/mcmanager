"""Minecraft adapter (Doc 14) — capabilities, readiness, EULA, Java,
server.properties validation, and the pre-launch gate."""

from __future__ import annotations

from app.infrastructure.minecraft.capabilities import (
    CAPABILITY_MATRIX,
    capabilities_for,
)
from app.infrastructure.minecraft.eula import accept, current_state, provision_eula_file
from app.infrastructure.minecraft.gate import (
    ERROR_EULA_NOT_ACCEPTED,
    ERROR_JAR_MISSING,
    ERROR_JAVA_INCOMPATIBLE,
    ERROR_PORT_CONFLICT,
    ERROR_WORLD_DIR_MISSING,
    GateResult,
    LaunchContext,
    build_launch_argv,
    validate_launch,
)
from app.infrastructure.minecraft.java_compatibility import (
    JavaDetection,
    compatibility_record,
    detect_java,
    java_compatible,
    recommended_java,
)
from app.infrastructure.minecraft.ping import ping_protocol
from app.infrastructure.minecraft.properties_schema import (
    CORE_MANAGER_PROPERTIES,
    PropertyValidation,
    allowed_keys,
    is_valid_key,
    is_valid_value,
    parse_properties,
    validate_properties,
)
from app.infrastructure.minecraft.rcon import SAFE_COMMANDS, RconClient, RconError
from app.infrastructure.minecraft.readiness import (
    DEFAULT_TARGET_LEVELS,
    build_state,
    evaluate,
    port_is_bound,
    target_level_for,
)

__all__ = [
    'CAPABILITY_MATRIX',
    'CORE_MANAGER_PROPERTIES',
    'DEFAULT_TARGET_LEVELS',
    'ERROR_EULA_NOT_ACCEPTED',
    'ERROR_JAVA_INCOMPATIBLE',
    'ERROR_JAR_MISSING',
    'ERROR_PORT_CONFLICT',
    'ERROR_WORLD_DIR_MISSING',
    'GateResult',
    'JavaDetection',
    'LaunchContext',
    'PropertyValidation',
    'RconClient',
    'RconError',
    'SAFE_COMMANDS',
    'accept',
    'allowed_keys',
    'build_launch_argv',
    'build_state',
    'capabilities_for',
    'compatibility_record',
    'current_state',
    'detect_java',
    'evaluate',
    'is_valid_key',
    'is_valid_value',
    'java_compatible',
    'port_is_bound',
    'parse_properties',
    'ping_protocol',
    'provision_eula_file',
    'recommended_java',
    'target_level_for',
    'validate_launch',
    'validate_properties',
]
