"""Domain invariants shared by entities and lifecycle transitions."""

from __future__ import annotations

from app.domain.value_objects import WorldState


class DomainInvariantError(ValueError):
    """Raised when a domain entity cannot represent a valid business state."""


def validate_world_instance(
    world_id: str,
    state: WorldState,
    pre_backup_state: WorldState | None,
    deleted_at: int | None = None,
) -> None:
    """Validate identity and backup-state invariants for a world."""
    if not isinstance(world_id, str) or not world_id:
        raise DomainInvariantError("world_id must be a non-empty string")
    if not isinstance(state, WorldState):
        raise DomainInvariantError("state must be a WorldState")
    if state is WorldState.BACKING_UP:
        if pre_backup_state not in (WorldState.OFF, WorldState.RUNNING):
            raise DomainInvariantError(
                "backing_up worlds require pre_backup_state to be off or running"
            )
    elif pre_backup_state is not None:
        raise DomainInvariantError(
            "pre_backup_state is only set while the world is backing_up"
        )
    if deleted_at is not None:
        if isinstance(deleted_at, bool) or not isinstance(deleted_at, int):
            raise DomainInvariantError("deleted_at must be an integer timestamp")
        if state is not WorldState.OFF:
            raise DomainInvariantError("only an off world can be tombstoned")
