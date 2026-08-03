# Architecture Instructions

## Purpose

This file defines mandatory architectural guidance for AI coding
assistants working on the project.

## General Rules

-   Read **Documents 2--10** before making any architectural decisions.
-   Treat the design documents as the source of truth.
-   If implementation conflicts with the documents, follow the
    documents.
-   If two documents conflict with each other, **Document 10
    (Precedence & Conflict Resolution) governs.** Check it before
    assuming a lower-numbered document is still accurate — several
    points in Documents 1 and 3 have been explicitly superseded there
    (nav-bar alert behavior, secrets storage location, among others).
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

## Operations

-   All state-changing actions must execute as durable Operations.
-   Maintain auditability.
-   Emit domain events where appropriate.
-   Ensure operations are restart-safe whenever practical.

## Web Application

-   Use Python and Flask.
-   Keep API endpoints thin.
-   Place business logic in services and domain layers.
-   Avoid embedding business logic in routes or templates.

## User Interface

-   Follow the CSS Style Guide (Document 4).
-   Follow the Navigation & Workflow Blueprint (Document 5).
-   Do not introduce page-specific styling systems.
-   Reuse shared UI components whenever possible — including the
    Status Indicator component (Document 4 §17) for any state display,
    rather than inventing a one-off badge/label treatment.

## Coding Standards

-   Prefer readability over cleverness.
-   Keep functions focused and small.
-   Write clear docstrings where appropriate.
-   Add tests for new functionality when practical.

## Before Completing Any Task

Verify that:

-   The implementation aligns with Documents 2--10.
-   No architectural rules were violated.
-   Naming remains consistent.
-   Existing abstractions are reused instead of duplicated.
-   The design remains extensible.
