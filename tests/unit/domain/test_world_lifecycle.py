"""World lifecycle behavior specified by Document 6."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.domain.entities import WorldInstance
from app.domain.events import WorldDeleted, WorldStateChanged
from app.domain.invariants import DomainInvariantError
from app.domain.lifecycle import (
    InvalidWorldTransition,
    WorldTransitionIntent,
    tombstone_world,
    transition_world,
)
from app.domain.value_objects import WorldState

DOCUMENTED_TRANSITIONS = (
    (WorldState.OFF, WorldState.QUEUED),
    (WorldState.OFF, WorldState.BACKING_UP),
    (WorldState.OFF, WorldState.RESTORING),
    (WorldState.OFF, WorldState.EULA_REQUIRED),
    (WorldState.QUEUED, WorldState.OFF),
    (WorldState.QUEUED, WorldState.STARTING),
    (WorldState.STARTING, WorldState.RUNNING),
    (WorldState.STARTING, WorldState.ERROR),
    (WorldState.RUNNING, WorldState.STOPPING),
    (WorldState.RUNNING, WorldState.CRASHED),
    (WorldState.RUNNING, WorldState.BACKING_UP),
    (WorldState.STOPPING, WorldState.OFF),
    (WorldState.RESTORING, WorldState.OFF),
    (WorldState.RESTORING, WorldState.ERROR),
    (WorldState.BACKING_UP, WorldState.OFF),
    (WorldState.BACKING_UP, WorldState.RUNNING),
    (WorldState.BACKING_UP, WorldState.ERROR),
)


@pytest.mark.parametrize(("old_state", "new_state"), DOCUMENTED_TRANSITIONS)
def test_documented_world_transition_is_accepted(
    old_state: WorldState, new_state: WorldState
) -> None:
    pre_backup_state = None
    if old_state is WorldState.BACKING_UP:
        pre_backup_state = (
            new_state
            if new_state in {WorldState.OFF, WorldState.RUNNING}
            else WorldState.OFF
        )
    world = WorldInstance(
        world_id="world-1",
        state=old_state,
        pre_backup_state=pre_backup_state,
    )

    updated, event = transition_world(world, new_state, occurred_at=123)

    assert updated.state is new_state
    assert event == WorldStateChanged(
        world_id="world-1",
        previous_state=old_state,
        new_state=new_state,
        occurred_at=123,
    )
    assert isinstance(event, WorldStateChanged)


@pytest.mark.parametrize(
    ("current_state", "requested_state"),
    (
        (WorldState.OFF, WorldState.RUNNING),
        (WorldState.RUNNING, WorldState.RESTORING),
        (WorldState.CRASHED, WorldState.STARTING),
        (WorldState.ERROR, WorldState.STARTING),
        (WorldState.EULA_REQUIRED, WorldState.STARTING),
        (WorldState.EULA_REQUIRED, WorldState.RUNNING),
    ),
)
def test_lifecycle_rejects_transitions_that_bypass_documented_guards(
    current_state: WorldState, requested_state: WorldState
) -> None:
    world = WorldInstance(world_id="world-1", state=current_state)

    with pytest.raises(InvalidWorldTransition):
        transition_world(world, requested_state, occurred_at=123)


def test_lifecycle_rejects_every_undocumented_world_state_transition() -> None:
    allowed = set(DOCUMENTED_TRANSITIONS)
    for current_state in WorldState:
        for requested_state in WorldState:
            if (
                current_state is requested_state
                or (current_state, requested_state) in allowed
            ):
                continue
            world = WorldInstance(
                world_id="world-1",
                state=current_state,
                pre_backup_state=(
                    WorldState.OFF
                    if current_state is WorldState.BACKING_UP
                    else None
                ),
            )

            with pytest.raises(InvalidWorldTransition):
                transition_world(world, requested_state, occurred_at=123)


@pytest.mark.parametrize(
    "current_state",
    (WorldState.CRASHED, WorldState.ERROR, WorldState.EULA_REQUIRED),
)
def test_guarded_states_cannot_be_cleared_by_an_ordinary_transition(
    current_state: WorldState,
) -> None:
    world = WorldInstance(world_id="world-1", state=current_state)

    with pytest.raises(InvalidWorldTransition):
        transition_world(world, WorldState.OFF, occurred_at=123)


@pytest.mark.parametrize(
    ("current_state", "intent"),
    (
        (WorldState.CRASHED, WorldTransitionIntent.CRASH_ACKNOWLEDGEMENT),
        (WorldState.ERROR, WorldTransitionIntent.ERROR_ACKNOWLEDGEMENT),
        (WorldState.EULA_REQUIRED, WorldTransitionIntent.EULA_ACCEPTANCE),
    ),
)
def test_guarded_states_require_their_matching_transition_intent(
    current_state: WorldState,
    intent: WorldTransitionIntent,
) -> None:
    world = WorldInstance(world_id="world-1", state=current_state)

    updated, _ = transition_world(
        world,
        WorldState.OFF,
        occurred_at=123,
        intent=intent,
    )

    assert updated.state is WorldState.OFF


def test_guarded_transition_rejects_an_unrelated_intent() -> None:
    world = WorldInstance(world_id="world-1", state=WorldState.EULA_REQUIRED)

    with pytest.raises(InvalidWorldTransition):
        transition_world(
            world,
            WorldState.OFF,
            occurred_at=123,
            intent=WorldTransitionIntent.ERROR_ACKNOWLEDGEMENT,
        )


@pytest.mark.parametrize(
    ("starting_state", "expected_resume_state"),
    ((WorldState.OFF, WorldState.OFF), (WorldState.RUNNING, WorldState.RUNNING)),
)
def test_backup_restores_its_exact_pre_backup_state(
    starting_state: WorldState, expected_resume_state: WorldState
) -> None:
    initial = WorldInstance(world_id="world-1", state=starting_state)

    backing_up, _ = transition_world(
        initial, WorldState.BACKING_UP, occurred_at=1
    )
    restored, _ = transition_world(
        backing_up, expected_resume_state, occurred_at=2
    )

    assert backing_up.pre_backup_state is starting_state
    assert restored.state is expected_resume_state
    assert restored.pre_backup_state is None


@pytest.mark.parametrize(
    ("invalid_resume_state", "initial_state"),
    (
        (WorldState.OFF, WorldState.RUNNING),
        (WorldState.RUNNING, WorldState.OFF),
    ),
)
def test_backup_cannot_resume_to_a_state_other_than_its_origin(
    invalid_resume_state: WorldState, initial_state: WorldState
) -> None:
    backing_up, _ = transition_world(
        WorldInstance(world_id="world-1", state=initial_state),
        WorldState.BACKING_UP,
        occurred_at=1,
    )

    with pytest.raises(InvalidWorldTransition):
        transition_world(backing_up, invalid_resume_state, occurred_at=2)


def test_failed_backup_transitions_to_error_and_clears_resume_state() -> None:
    backing_up, _ = transition_world(
        WorldInstance(world_id="world-1", state=WorldState.RUNNING),
        WorldState.BACKING_UP,
        occurred_at=1,
    )

    failed, _ = transition_world(backing_up, WorldState.ERROR, occurred_at=2)

    assert failed.state is WorldState.ERROR
    assert failed.pre_backup_state is None


def test_world_entity_rejects_invalid_identity_and_backup_state() -> None:
    with pytest.raises(DomainInvariantError):
        WorldInstance(world_id="")
    with pytest.raises(DomainInvariantError):
        WorldInstance(world_id=1)  # type: ignore[arg-type]
    with pytest.raises(DomainInvariantError):
        WorldInstance(world_id="world-1", state="off")  # type: ignore[arg-type]
    with pytest.raises(DomainInvariantError):
        WorldInstance(world_id="world-1", state=WorldState.BACKING_UP)
    with pytest.raises(DomainInvariantError):
        WorldInstance(
            world_id="world-1",
            state=WorldState.BACKING_UP,
            pre_backup_state=WorldState.EULA_REQUIRED,
        )
    with pytest.raises(DomainInvariantError):
        WorldInstance(world_id="world-1", pre_backup_state=WorldState.OFF)
    with pytest.raises(DomainInvariantError):
        WorldInstance(
            world_id="world-1",
            state=WorldState.RUNNING,
            deleted_at=100,
        )
    with pytest.raises(DomainInvariantError):
        WorldInstance(world_id="world-1", deleted_at="deleted")  # type: ignore[arg-type]
    with pytest.raises(DomainInvariantError):
        WorldInstance(world_id="world-1", deleted_at=True)  # type: ignore[arg-type]


def test_transition_rejects_non_enum_state_without_mutating_world() -> None:
    world = WorldInstance(world_id="world-1")

    with pytest.raises(InvalidWorldTransition):
        transition_world(world, "running", occurred_at=123)  # type: ignore[arg-type]

    assert world.state is WorldState.OFF


@pytest.mark.parametrize("occurred_at", (True, "123", 1.5))
def test_transition_rejects_non_integer_timestamps(
    occurred_at: object,
) -> None:
    world = WorldInstance(world_id="world-1")

    with pytest.raises(InvalidWorldTransition, match="integer timestamp"):
        transition_world(
            world,
            WorldState.QUEUED,
            occurred_at=occurred_at,  # type: ignore[arg-type]
        )

    assert world.state is WorldState.OFF


def test_transition_rejects_an_unknown_intent_without_leaking_attribute_errors() -> None:
    world = WorldInstance(world_id="world-1")

    with pytest.raises(InvalidWorldTransition, match="unknown world transition intent"):
        transition_world(
            world,
            WorldState.QUEUED,
            occurred_at=123,
            intent="ordinary",  # type: ignore[arg-type]
        )


def test_transition_translates_inconsistent_entity_invariant_to_lifecycle_error() -> None:
    world = WorldInstance(world_id="world-1")
    object.__setattr__(world, "pre_backup_state", WorldState.OFF)

    with pytest.raises(InvalidWorldTransition):
        transition_world(world, WorldState.QUEUED, occurred_at=123)


def test_world_and_emitted_event_are_immutable() -> None:
    world = WorldInstance(world_id="world-1")
    updated, event = transition_world(world, WorldState.QUEUED, occurred_at=123)

    with pytest.raises(FrozenInstanceError):
        updated.state = WorldState.RUNNING  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        event.new_state = WorldState.RUNNING  # type: ignore[misc]
    assert world.state is WorldState.OFF


def test_delete_world_tombstones_only_an_off_world_with_a_typed_event() -> None:
    world = WorldInstance(world_id="world-1")

    deleted, event = tombstone_world(world, occurred_at=789)

    assert deleted.state is WorldState.OFF
    assert deleted.deleted_at == 789
    assert isinstance(event, WorldDeleted)
    assert event.world_id == "world-1"
    assert event.occurred_at == 789
    with pytest.raises(FrozenInstanceError):
        event.world_id = "another-world"  # type: ignore[misc]


@pytest.mark.parametrize(
    "state",
    tuple(state for state in WorldState if state is not WorldState.OFF),
)
def test_delete_world_rejects_any_non_off_state(state: WorldState) -> None:
    world = WorldInstance(
        world_id="world-1",
        state=state,
        pre_backup_state=WorldState.OFF if state is WorldState.BACKING_UP else None,
    )

    with pytest.raises(InvalidWorldTransition):
        tombstone_world(world, occurred_at=789)


@pytest.mark.parametrize("occurred_at", (True, "789", 1.5))
def test_delete_world_rejects_non_integer_timestamps(occurred_at: object) -> None:
    world = WorldInstance(world_id="world-1")

    with pytest.raises(InvalidWorldTransition, match="integer timestamp"):
        tombstone_world(
            world,
            occurred_at=occurred_at,  # type: ignore[arg-type]
        )

    assert world.deleted_at is None


def test_tombstoned_world_cannot_transition_or_be_deleted_again() -> None:
    world, _ = tombstone_world(WorldInstance(world_id="world-1"), occurred_at=789)

    with pytest.raises(InvalidWorldTransition):
        transition_world(world, WorldState.QUEUED, occurred_at=790)
    with pytest.raises(InvalidWorldTransition):
        tombstone_world(world, occurred_at=790)


def test_transition_event_timestamp_and_state_types_are_preserved() -> None:
    _, event = transition_world(
        WorldInstance(world_id="world-1"),
        WorldState.QUEUED,
        occurred_at=456,
    )

    assert event.occurred_at == 456
    assert event.previous_state is WorldState.OFF
    assert event.new_state is WorldState.QUEUED
