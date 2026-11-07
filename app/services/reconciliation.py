"""Boot-time runtime attachment and orphan-session reconciliation."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.runtime import RuntimeService


@dataclass(frozen=True)
class ReconciliationHealth:
    """Observable outcome of the latest reconciliation attempt."""

    status: str
    reattached_world_ids: tuple[str, ...] = ()
    error: str | None = None


class ReconciliationService:
    """Keep boot reconciliation separate and expose its fail-closed health."""

    def __init__(self, runtime: RuntimeService) -> None:
        self._runtime = runtime
        self._health = ReconciliationHealth(status='not_started')

    @property
    def health(self) -> ReconciliationHealth:
        """Return the latest reconciliation outcome without suppressing errors."""
        return self._health

    def reconcile(self) -> list[str]:
        self._health = ReconciliationHealth(status='running')
        try:
            reattached = tuple(self._runtime.reconcile())
        except Exception as exc:
            self._health = ReconciliationHealth(
                status='failed',
                error=str(exc),
            )
            raise
        self._health = ReconciliationHealth(
            status='healthy',
            reattached_world_ids=reattached,
        )
        return list(reattached)
