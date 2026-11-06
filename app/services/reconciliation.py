"""Boot-time runtime attachment and orphan-session reconciliation."""

from __future__ import annotations

from app.services.runtime import RuntimeService


class ReconciliationService:
    """Keep boot reconciliation separate so failures remain startup-visible."""

    def __init__(self, runtime: RuntimeService) -> None:
        self._runtime = runtime

    def reconcile(self) -> list[str]:
        return self._runtime.reconcile()
