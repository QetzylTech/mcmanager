"""Domain entities and their construction-time invariants."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.invariants import validate_world_instance
from app.domain.value_objects import WorldState


@dataclass(frozen=True)
class WorldInstance:
    """World identity and lifecycle state owned by the domain layer."""

    world_id: str
    state: WorldState = WorldState.OFF
    pre_backup_state: WorldState | None = None
    deleted_at: int | None = None

    def __post_init__(self) -> None:
        validate_world_instance(
            self.world_id,
            self.state,
            self.pre_backup_state,
            self.deleted_at,
        )
