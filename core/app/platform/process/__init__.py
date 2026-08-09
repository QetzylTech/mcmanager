"""Platform process-control adapters (Document 13).

Only this package touches OS-level process APIs. POSIX/Windows/Fake all
implement ``app.ports.process_control.ProcessControlPort``.
"""

from __future__ import annotations
