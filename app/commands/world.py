"""Commands for world runtime actions exposed by the HTTP API."""

from __future__ import annotations

from app.domain.value_objects import ActorType
from app.services.worlds import WorldsService


class WorldLifecycleCommands:
    """Keep HTTP handlers limited to authorization, dispatch, and envelopes."""

    def __init__(self, worlds: WorldsService) -> None:
        self._worlds = worlds

    @staticmethod
    def _result_id(value: object) -> str:
        if not isinstance(value, str):
            raise TypeError("world lifecycle service returned a non-string identifier")
        return value

    def start(self, *, world_id: str, actor_user_id: str) -> str:
        return self._result_id(
            self._worlds.start(
                world_id=world_id,
                actor_type=ActorType.USER,
                actor_user_id=actor_user_id,
            )
        )

    def stop(self, *, world_id: str, actor_user_id: str) -> str:
        return self._result_id(
            self._worlds.stop(
                world_id=world_id,
                actor_type=ActorType.USER,
                actor_user_id=actor_user_id,
            )
        )

    def kill(self, *, world_id: str, actor_user_id: str) -> str:
        return self._result_id(
            self._worlds.kill(
                world_id=world_id,
                actor_type=ActorType.USER,
                actor_user_id=actor_user_id,
            )
        )
