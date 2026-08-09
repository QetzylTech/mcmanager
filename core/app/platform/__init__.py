"""Platform adapters — the ONLY package that touches OS process APIs.

Leaf-only: imported by nothing except the composition root and adapter
bindings (Doc 12 section 4).
"""

from __future__ import annotations
