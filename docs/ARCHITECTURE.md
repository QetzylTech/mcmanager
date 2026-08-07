# Architecture Instructions

## Purpose

This file defines mandatory architectural guidance for AI coding
assistants working on the project.

## General Rules

-   Read **Documents 2--11** before making any architectural decisions.
    This includes Document 11 (Concurrency, Locking & Conflict
    Resolution Model), which is the authoritative source for lock
    taxonomy, the mutual-exclusion matrix, optimistic concurrency, and
    queue/reject/preempt semantics — it supersedes Doc 8 §7's matrix
    wherever they differ.
-   Treat the design documents as the source of truth.
-   If implementation conflicts with the documents, follow the
    documents.
-   If two documents conflict with each other, **Document 11
    (Concurrency & Conflict Model) governs operational locking and
    concurrency**, and **Document 10 (Precedence & Conflict
    Resolution) governs all other disagreements.** Check them before
    assuming a lower-numbered document is still accurate — several
    points in Documents 1 and 3 have been explicitly superseded there
    (nav-bar alert behavior, secrets storage location, cleanup
    queueing semantics, among others).
-   Each numbered document exists as exactly one file in the project.
    If you ever find two files claiming to be the same document
    number, stop and flag it rather than guessing which one is
    current — do not assume the one with a higher revision suffix
    automatically wins.

## Architecture

-   Preserve the modular monolith architecture.
-   Do not introduce microservices.
-   Keep modules loosely coupled and highly cohesive.
-   Use dependency injection where appropriate.
-   Keep platform-specific code isolated behind adapters.
-   Use ports-and-adapters boundaries for OS-specific behavior,
    Minecraft-server-specific behavior, and storage-specific behavior.
-   Script-based adapters (e.g. `backup.sh`) are transitional only:
    they may exist to ease migrations but must be retired before the
    first stable release, and no new platform-specific script logic
    may be added. The native, portable backup engine in the manager
    stack is the only supported production path (Document 2 §4.1,
    Document 3 §5.8).

## Domain Model

-   Do not rename domain entities.
-   Do not invent new domain concepts unless explicitly required.
-   Preserve aggregate boundaries and ownership rules.
-   Follow the documented business invariants.
-   Every state-changing action executes as a durable Operation
    (Document 6/8) — including world creation and deletion
    (`CreateWorld`/`DeleteWorld`), not just the more obviously
    stateful actions like start/stop/backup/restore.
-   Follow the Global Deletion & Retention Model (Document 6): Tier 1
    entities are never deleted by anything; Tier 2 entities are
    soft-deleted (`deleted_at`) by normal actions and physically
    removed only by the Cleanup subsystem, never by any other route,
    command handler, or service.

## Persistence

-   Use SQLite as the primary persistent store.
-   Keep runtime state in memory.
-   Persist only durable state.
-   Follow the documented migration strategy.
-   **Global Persistence Invariant** (defined once here; referenced by name in Document 7 §0 — do not restate): every connection must run `PRAGMA foreign_keys = ON` before any other statement, and every boot must run a `PRAGMA foreign_key_check` sweep after migrations apply and before serving requests. Any violation is a startup-blocking critical error, never silently repaired.
-   Clients connecting during boot reconciliation are rehydrated
    immediately from the durable snapshot plus the last cached live
    snapshot — never shown a blank or unknown state while the first
    reconciliation cycle completes (Document 2 §2.2, Document 3 §7.4).

## Operations

-   All state-changing actions must execute as durable Operations.
-   Maintain auditability.
-   Emit domain events where appropriate.
-   Ensure operations are restart-safe whenever practical.
-   Runtime status must never depend on a single log line; the state
    resolver combines process state, health probes, startup signals,
    operation checkpoints, and crash markers. Log strings such as
    "Dedicated server took x seconds to load" are advisory only
    (Document 2 §2.2, Document 3 §7.1).
-   Follow the queue/reject/preempt semantics in Document 11 §6:
    Backup, Restore, and Cleanup duplicates are queued single-flight
    (auto-dispatch with the live stream surfacing queue position —
    never rejected outright, never requiring client polling);
    Start duplicates are ignored; DeleteWorld and ConfigEdit conflicts
    are rejected. Priority between waiting operations is contextual
    (manual/safety-critical first), per Document 11 §3.2.
-   Storage guards are contextual (job size + configurable absolute
    reserve, with a 10% bound only as an overflow safety net), never a
    flat 10% rule (Document 11 §1.2).

## Web Application

-   Use Python and Flask.
-   Keep API endpoints thin.
-   Place business logic in services and domain layers.
-   Avoid embedding business logic in routes or templates.

## User Interface

-   Follow the CSS Style Guide (Document 4).
-   Follow the Navigation & Workflow Blueprint (Document 5).
-   Do not introduce page-specific styling systems — except under
    Document 4 §0's Functional Appropriateness Exception: layout-only
    page-scoped classes are permitted for complex pages (World
    Maintenance, File Manager, Restore) when the shared system cannot
    express the needed layout without accumulating one-off exceptions.
    Component styling (buttons, panes, dropdowns, inputs, modals,
    status indicators) always stays shared.
-   Reuse shared UI components whenever possible — including the
    Status Indicator component (Document 4 §17) for any state display,
    rather than inventing a one-off badge/label treatment.
-   Multi-tab behavior: each tab opens its own independent connection
    to the shared server-side streams. Do not implement primary/secondary
    tab election, TTL heartbeats, BroadcastChannel forwarding, or any
    other client-side tab coordination (Document 2 §7.1,
    Document 3 §4.3/§5.1); a failing or closed tab must never orphan
    or disrupt other tabs.
-   Step-up verification is session-scoped and time-bounded (default
    10 minutes): one successful password verification authorizes
    subsequent sensitive actions in that window, so users are not
    forced to retype their password per action (Document 6 §2.14).

## Coding Standards

-   Prefer readability over cleverness.
-   Keep functions focused and small.
-   Write clear docstrings where appropriate.
-   Add tests for new functionality when practical.

## Before Completing Any Task

- [ ] Aligns with Docs 2--11 (Doc 11 for locking, Doc 10 for all other conflicts).
- [ ] No architectural rule violated (monolith, ports-and-adapters, Operation-based control, deletion tiers).
- [ ] Naming consistent with the docs (no renamed/duplicated domain concepts).
- [ ] Existing ports/adapters and shared components reused, not duplicated.
