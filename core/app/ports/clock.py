"""Clock port — injectable epoch-seconds source (Document 11).

Deterministic clocks make timeout/cooldown/step-up tests fast and race-free.
"""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    """Source of monotonically increasing epoch time."""

    def now(self) -> float:
        """Current time in epoch seconds with sub-second precision."""
        ...


class SystemClock:
    """Production clock backed by ``time.time``."""

    def now(self) -> float:
        return time.time()
