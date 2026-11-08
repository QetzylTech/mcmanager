"""Version-aware ``server.properties`` schema (Doc 14 section 6).

Two property classes: core manager-owned properties (managed only through
guarded editors) and version/server-type-dependent properties validated via
a capability schema keyed by (server_type, mc_version). Unknown-for-this-
version keys -> CONFIG_INVALID_KEY; bad format -> CONFIG_INVALID_VALUE.
Deprecated properties are preserved on disk, never silently deleted.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.value_objects import ServerType
from app.ports.minecraft import (
    PropertySpec,
    _version_tuple,
    default_property_specs,
    validate_property_schema,
)
from app.ports.minecraft import (
    parse_properties as parse_properties,
)

# Core manager-owned properties (Doc 14 section 6.1) — touched only through
# guarded editors, never the free-text file editor.
CORE_MANAGER_PROPERTIES = frozenset(
    {
        'server-port',
        'enable-rcon',
        'rcon.port',
        'rcon.password',
        'server-ip',
        'enable-query',
        'query.port',
        'level-name',
        'level-seed',
        'online-mode',
        'motd',
    }
)

# Version-scoped additions/removals (curated reference data, additive).
VERSIONED_SPECS: dict[str, PropertySpec] = {
    'max-players': PropertySpec('max-players', 'int', default=20),
    'view-distance': PropertySpec('view-distance', 'int', default=10),
    'spawn-protection': PropertySpec('spawn-protection', 'int', default=16),
    'white-list': PropertySpec('white-list', 'bool', default=False),
    'enforce-whitelist': PropertySpec('enforce-whitelist', 'bool', default=False),
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
    # Example of a property removed in modern versions (preserved on disk,
    # flagged obsolete, migration hint surfaced).
    'generator-settings': PropertySpec(
        'generator-settings',
        'str',
        max_supported_version='1.12',
        deprecated_in='1.7',
        replaced_by_gamerule='level-seed',
    ),
}


def _merged_specs() -> dict[str, PropertySpec]:
    merged = dict(default_property_specs())
    merged.update(VERSIONED_SPECS)
    return merged


@dataclass(frozen=True)
class PropertyValidation:
    """Validation result for a properties payload."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    deprecated_hints: list[str] = field(default_factory=list)


def validate_properties(
    *,
    properties: dict[str, object],
    server_type: ServerType,
    mc_version: str,
) -> PropertyValidation:
    """Validate a full properties dict against the merged schema.

    Deprecated-but-still-known keys pass validation but are flagged with a
    migration hint (never auto-deleted).
    """
    specs = _merged_specs()
    errors: list[str] = []
    hints: list[str] = []

    for key, value in properties.items():
        ok, error_code = validate_property_schema(
            key=key,
            value=value,
            server_type=server_type,
            mc_version=mc_version,
            specs=specs,
        )
        if not ok:
            errors.append(f'{key}: {error_code}')
            continue
        spec = specs[key]
        if (
            spec.deprecated_in is not None
            and _version_tuple(mc_version) >= _version_tuple(spec.deprecated_in)
        ):
            hint = f'{key}: deprecated in {spec.deprecated_in}'
            if spec.replaced_by_gamerule:
                hint += f' (replaced by {spec.replaced_by_gamerule})'
            hints.append(hint)

    return PropertyValidation(valid=not errors, errors=errors, deprecated_hints=hints)


def is_valid_key(key: str, server_type: ServerType, mc_version: str) -> bool:
    """Doc 14 section 6.2: is this property key valid for the version?"""
    specs = _merged_specs()
    spec = specs.get(key)
    if spec is None:
        return False
    if _version_tuple(mc_version) < _version_tuple(spec.min_supported_version):
        return False
    return not (
        spec.max_supported_version is not None
        and _version_tuple(mc_version) > _version_tuple(spec.max_supported_version)
    )


def is_valid_value(
    key: str, value: object, server_type: ServerType, mc_version: str
) -> bool:
    """Doc 14 section 6.2: does the value pass format constraints?"""
    specs = _merged_specs()
    ok, _error_code = validate_property_schema(
        key=key,
        value=value,
        server_type=server_type,
        mc_version=mc_version,
        specs=specs,
    )
    return ok


def allowed_keys(server_type: ServerType, mc_version: str) -> list[str]:
    """All valid keys for the version, sorted (UI catalog)."""
    return sorted(
        key for key in _merged_specs() if is_valid_key(key, server_type, mc_version)
    )
