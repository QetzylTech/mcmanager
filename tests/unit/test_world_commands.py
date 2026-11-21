from __future__ import annotations

import pytest

from app.commands.world import WorldLifecycleCommands
from app.domain.value_objects import ActorType, OperationType


class RecordingWorlds:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def enqueue_start(self, **kwargs):
        self.calls.append(("enqueue_start", kwargs))
        return {"op_id": "op-1"}, False

    def enqueue_stop(self, **kwargs):
        self.calls.append(("enqueue_stop", kwargs))
        return {"op_id": "op-2"}, True

    def enqueue_kill(self, **kwargs):
        self.calls.append(("enqueue_kill", kwargs))
        return {"op_id": "op-3"}, False

    def start(self, **kwargs):
        self.calls.append(("start", kwargs))
        return "op-start"

    def stop(self, **kwargs):
        self.calls.append(("stop", kwargs))
        return "op-stop"

    def kill(self, **kwargs):
        self.calls.append(("kill", kwargs))
        return "op-kill"


@pytest.mark.parametrize(
    ("operation", "method"),
    (
        (OperationType.START, "enqueue_start"),
        (OperationType.STOP, "enqueue_stop"),
        (OperationType.KILL, "enqueue_kill"),
    ),
)
def test_enqueue_dispatches_lifecycle_action_with_user_identity(operation, method):
    worlds = RecordingWorlds()

    response, replayed = WorldLifecycleCommands(worlds).enqueue(
        op_type=operation,
        world_id="world-1",
        actor_user_id="user-1",
        idempotency_key="request-1",
    )

    assert worlds.calls == [
        (
            method,
            {
                "world_id": "world-1",
                "actor_type": ActorType.USER,
                "actor_user_id": "user-1",
                "idempotency_key": "request-1",
            },
        )
    ]
    assert response["op_id"].startswith("op-")
    assert replayed is (operation is OperationType.STOP)


def test_enqueue_rejects_non_lifecycle_operation():
    with pytest.raises(ValueError, match="unsupported world lifecycle operation"):
        WorldLifecycleCommands(RecordingWorlds()).enqueue(
            op_type=OperationType.RESTORE,
            world_id="world-1",
            actor_user_id="user-1",
            idempotency_key="request-1",
        )


@pytest.mark.parametrize(
    ("method", "expected"),
    (("start", "op-start"), ("stop", "op-stop"), ("kill", "op-kill")),
)
def test_immediate_lifecycle_actions_return_service_operation_id(method, expected):
    worlds = RecordingWorlds()

    result = getattr(WorldLifecycleCommands(worlds), method)(
        world_id="world-1",
        actor_user_id="user-1",
    )

    assert result == expected
    assert worlds.calls == [
        (
            method,
            {
                "world_id": "world-1",
                "actor_type": ActorType.USER,
                "actor_user_id": "user-1",
            },
        )
    ]


def test_immediate_lifecycle_action_rejects_invalid_service_identifier():
    worlds = RecordingWorlds()
    worlds.start = lambda **_kwargs: None

    with pytest.raises(TypeError, match="non-string identifier"):
        WorldLifecycleCommands(worlds).start(world_id="world-1", actor_user_id="user-1")
