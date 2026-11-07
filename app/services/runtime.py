"""Runtime lifecycle and supervisor entry points (Doc 8 / Gate 3)."""

from __future__ import annotations

from app.domain.value_objects import ActorType
from app.services.worlds import WorldsService


class RuntimeService:
    """Expose the runtime-only API while retaining the legacy WorldsService facade."""

    def __init__(self, lifecycle: WorldsService) -> None:
        self._lifecycle = lifecycle

    def start(
        self,
        *,
        world_id: str,
        actor_type: ActorType = ActorType.USER,
        actor_user_id: str | None = None,
    ) -> str:
        return self._lifecycle.start(
            world_id=world_id, actor_type=actor_type, actor_user_id=actor_user_id
        )

    def restart_and_confirm(self, world_id: str) -> bool:
        """Perform the post-restore verification start and wait for readiness."""
        self._lifecycle.start(
            world_id=world_id,
            actor_type=ActorType.SYSTEM,
            _allow_world_conflict=True,
        )
        return True

    def stop(
        self,
        *,
        world_id: str,
        actor_type: ActorType = ActorType.USER,
        actor_user_id: str | None = None,
    ) -> str:
        return self._lifecycle.stop(
            world_id=world_id, actor_type=actor_type, actor_user_id=actor_user_id
        )

    def kill(
        self,
        *,
        world_id: str,
        actor_type: ActorType = ActorType.USER,
        actor_user_id: str | None = None,
    ) -> str:
        return self._lifecycle.kill(
            world_id=world_id, actor_type=actor_type, actor_user_id=actor_user_id
        )

    def poll_running(self) -> list[str]:
        return self._lifecycle.poll_running()

    def reconcile(self) -> list[str]:
        return self._lifecycle.reconcile()

    def supervisor_interval_seconds(self) -> float:
        return self._lifecycle.supervisor_interval_seconds()
