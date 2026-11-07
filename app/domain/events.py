"""Domain events emitted by stateful domain operations."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.value_objects import WorldState


@dataclass(frozen=True)
class WorldStateChanged:
    """A world lifecycle transition, timestamped at the decision point."""

    world_id: str
    previous_state: WorldState
    new_state: WorldState
    occurred_at: int


@dataclass(frozen=True)
class WorldDeleted:
    """A world tombstone created after DeleteWorld completes."""

    world_id: str
    occurred_at: int
