"""Guarded lifecycle transitions for world instances."""

from __future__ import annotations

from dataclasses import replace

from app.domain.entities import WorldInstance
from app.domain.events import WorldStateChanged
from app.domain.invariants import DomainInvariantError
from app.domain.value_objects import WorldState


class InvalidWorldTransition(ValueError):
    """Raised when a requested world transition violates the lifecycle."""


_ALLOWED_TRANSITIONS: dict[WorldState, frozenset[WorldState]] = {
    WorldState.OFF: frozenset(
        {
            WorldState.QUEUED,
            WorldState.STARTING,
            WorldState.BACKING_UP,
            WorldState.RESTORING,
            WorldState.EULA_REQUIRED,
            WorldState.ERROR,
        }
    ),
    WorldState.QUEUED: frozenset(
        {WorldState.OFF, WorldState.STARTING, WorldState.ERROR}
    ),
    WorldState.STARTING: frozenset(
        {
            WorldState.RUNNING,
            WorldState.OFF,
            WorldState.EULA_REQUIRED,
            WorldState.ERROR,
            WorldState.CRASHED,
        }
    ),
    WorldState.RUNNING: frozenset(
        {
            WorldState.STOPPING,
            WorldState.BACKING_UP,
            WorldState.CRASHED,
            WorldState.ERROR,
        }
    ),
    WorldState.STOPPING: frozenset(
        {WorldState.OFF, WorldState.CRASHED, WorldState.ERROR}
    ),
    WorldState.RESTORING: frozenset(
        {WorldState.OFF, WorldState.ERROR}
    ),
    WorldState.BACKING_UP: frozenset(
        {WorldState.OFF, WorldState.RUNNING, WorldState.ERROR}
    ),
    WorldState.CRASHED: frozenset({WorldState.STARTING}),
    WorldState.ERROR: frozenset({WorldState.STARTING}),
    WorldState.EULA_REQUIRED: frozenset(),
}


def transition_world(
    world: WorldInstance,
    new_state: WorldState,
    *,
    occurred_at: int,
) -> tuple[WorldInstance, WorldStateChanged]:
    """Return a validated replacement world and its lifecycle event."""
    if not isinstance(new_state, WorldState):
        raise InvalidWorldTransition(f"unknown world state: {new_state!r}")
    if new_state is not world.state and new_state not in _ALLOWED_TRANSITIONS[world.state]:
        raise InvalidWorldTransition(
            f"world {world.world_id} cannot transition "
            f"from {world.state.value} to {new_state.value}"
        )

    pre_backup_state = world.pre_backup_state
    if new_state is WorldState.BACKING_UP and world.state is not WorldState.BACKING_UP:
        pre_backup_state = world.state
    elif world.state is WorldState.BACKING_UP and new_state is not WorldState.BACKING_UP:
        if new_state is not world.pre_backup_state:
            raise InvalidWorldTransition(
                "a completed backup must restore the world to pre_backup_state"
            )
        pre_backup_state = None

    try:
        transitioned = replace(
            world,
            state=new_state,
            pre_backup_state=pre_backup_state,
        )
    except DomainInvariantError as exc:
        raise InvalidWorldTransition(str(exc)) from exc

    event = WorldStateChanged(
        world_id=world.world_id,
        previous_state=world.state,
        new_state=new_state,
        occurred_at=occurred_at,
    )
    return transitioned, event
