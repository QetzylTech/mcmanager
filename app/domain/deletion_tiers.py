"""Authoritative deletion-tier classification from Document 6."""

from __future__ import annotations

import enum


class DeletionTier(enum.Enum):
    """Persistence lifetime class for a domain entity."""

    TIER_1 = 1
    TIER_2 = 2


_TIER_1_ENTITIES = frozenset(
    {
        "audit_records",
        "notifications",
        "notification_reads",
        "missed_run_records",
        "sync_records",
        "sync_attempts",
    }
)
_TIER_2_ENTITIES = frozenset(
    {
        "world_instances",
        "devices",
        "java_runtimes",
        "templates",
        "users",
        "backup_artifacts",
        "schedules",
        "cleanup_policies",
        "roles",
        "permissions",
        "role_assignments",
        "client_sessions",
        "sync_targets",
    }
)


def get_deletion_tier(entity_name: str) -> DeletionTier | None:
    """Return the documented deletion tier, or ``None`` for non-tiered rows."""
    if entity_name in _TIER_1_ENTITIES:
        return DeletionTier.TIER_1
    if entity_name in _TIER_2_ENTITIES:
        return DeletionTier.TIER_2
    return None
