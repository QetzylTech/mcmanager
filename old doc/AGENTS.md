# AGENTS.md

This file is a duplicate of `ARCHITECTURE.md` (both contained the same architecture instructions; ARCHITECTURE.md additionally documents the Document 10 supersession rule and the one-canonical-file rule).

The canonical version is **ARCHITECTURE.md** — read that file for the full instructions.

- Read Documents 2--11 before architectural decisions; the design documents are the source of truth.
- Preserve the modular monolith; no microservices.
- All state-changing actions execute as durable Operations, including CreateWorld/DeleteWorld.
- Tier 1 entities are never deleted; Tier 2 are soft-deleted and physically removed only by Cleanup.
- Python + Flask; thin endpoints; business logic in services/domain; UI follows Documents 4 and 5.
