"""Guarded lifecycle transitions for world instances."""

from __future__ import annotations

import enum
from dataclasses import replace

from app.domain.entities import WorldInstance
from app.domain.events import WorldDeleted, WorldStateChanged
from app.domain.invariants import DomainInvariantError
from app.domain.value_objects import WorldState


class InvalidWorldTransition(ValueError):
    """Raised when a requested world transition violates the lifecycle."""


class WorldTransitionIntent(enum.Enum):
    """Explicit authorization context for guarded transitions to ``off``."""

    ORDINARY = "ordinary"
    CRASH_ACKNOWLEDGEMENT = "crash_acknowledgement"
    ERROR_ACKNOWLEDGEMENT = "error_acknowledgement"
    EULA_ACCEPTANCE = "eula_acceptance"


def _validate_occurred_at(occurred_at: int) -> None:
    if isinstance(occurred_at, bool) or not isinstance(occurred_at, int):
        raise InvalidWorldTransition("occurred_at must be an integer timestamp")


_ALLOWED_TRANSITIONS: dict[WorldState, frozenset[WorldState]] = {
    WorldState.OFF: frozenset(
        {
            WorldState.QUEUED,
            WorldState.BACKING_UP,
            WorldState.RESTORING,
            WorldState.EULA_REQUIRED,
        }
    ),
    WorldState.QUEUED: frozenset({WorldState.OFF, WorldState.STARTING}),
    WorldState.STARTING: frozenset(
        {
            WorldState.RUNNING,
            WorldState.ERROR,
        }
    ),
    WorldState.RUNNING: frozenset(
        {
            WorldState.STOPPING,
            WorldState.BACKING_UP,
            WorldState.CRASHED,
        }
    ),
    WorldState.STOPPING: frozenset({WorldState.OFF}),
    WorldState.RESTORING: frozenset(
        {WorldState.OFF, WorldState.ERROR}
    ),
    WorldState.BACKING_UP: frozenset(
        {WorldState.OFF, WorldState.RUNNING, WorldState.ERROR}
    ),
    WorldState.CRASHED: frozenset({WorldState.OFF}),
    WorldState.ERROR: frozenset({WorldState.OFF}),
    WorldState.EULA_REQUIRED: frozenset({WorldState.OFF}),
}


def transition_world(
    world: WorldInstance,
    new_state: WorldState,
    *,
    occurred_at: int,
    intent: WorldTransitionIntent = WorldTransitionIntent.ORDINARY,
) -> tuple[WorldInstance, WorldStateChanged]:
    """Return a validated replacement world and its lifecycle event."""
    _validate_occurred_at(occurred_at)
    if not isinstance(intent, WorldTransitionIntent):
        raise InvalidWorldTransition(f"unknown world transition intent: {intent!r}")
    if world.deleted_at is not None:
        raise InvalidWorldTransition(f"world {world.world_id} is tombstoned")
    if not isinstance(new_state, WorldState):
        raise InvalidWorldTransition(f"unknown world state: {new_state!r}")
    if new_state is not world.state and new_state not in _ALLOWED_TRANSITIONS[world.state]:
        raise InvalidWorldTransition(
            f"world {world.world_id} cannot transition "
            f"from {world.state.value} to {new_state.value}"
        )
    guarded_exit_intents = {
        WorldState.CRASHED: WorldTransitionIntent.CRASH_ACKNOWLEDGEMENT,
        WorldState.ERROR: WorldTransitionIntent.ERROR_ACKNOWLEDGEMENT,
        WorldState.EULA_REQUIRED: WorldTransitionIntent.EULA_ACCEPTANCE,
    }
    required_intent = (
        guarded_exit_intents.get(world.state)
        if new_state is WorldState.OFF
        else None
    )
    if required_intent is not None and intent is not required_intent:
        raise InvalidWorldTransition(
            f"transition from {world.state.value} to off requires "
            f"{required_intent.value}"
        )
    if intent is not WorldTransitionIntent.ORDINARY and intent is not required_intent:
        raise InvalidWorldTransition(
            f"{intent.value} is not valid for transition from "
            f"{world.state.value} to {new_state.value}"
        )

    pre_backup_state = world.pre_backup_state
    if new_state is WorldState.BACKING_UP and world.state is not WorldState.BACKING_UP:
        pre_backup_state = world.state
    elif world.state is WorldState.BACKING_UP and new_state is not WorldState.BACKING_UP:
        if new_state is not world.pre_backup_state and new_state is not WorldState.ERROR:
            raise InvalidWorldTransition(
                "a backup must restore the world to pre_backup_state or enter error"
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


def tombstone_world(
    world: WorldInstance,
    *,
    occurred_at: int,
) -> tuple[WorldInstance, WorldDeleted]:
    """Tombstone an off world and return its typed deletion event."""
    _validate_occurred_at(occurred_at)
    if world.deleted_at is not None:
        raise InvalidWorldTransition(f"world {world.world_id} is already tombstoned")
    if world.state is not WorldState.OFF:
        raise InvalidWorldTransition("only an off world can be deleted")

    try:
        deleted = replace(world, deleted_at=occurred_at)
    except DomainInvariantError as exc:
        raise InvalidWorldTransition(str(exc)) from exc
    return deleted, WorldDeleted(world_id=world.world_id, occurred_at=occurred_at)
