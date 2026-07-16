# Architecture Instructions

## Purpose

This file defines mandatory architectural guidance for AI coding
assistants working on the project.

## General Rules

-   Read **Documents 2--9** before making any architectural decisions.
-   Treat the design documents as the source of truth.
-   If implementation conflicts with the documents, follow the
    documents.

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
-   Reuse shared UI components whenever possible.

## Coding Standards

-   Prefer readability over cleverness.
-   Keep functions focused and small.
-   Write clear docstrings where appropriate.
-   Add tests for new functionality when practical.

## Before Completing Any Task

Verify that:

-   The implementation aligns with Documents 2--9.
-   No architectural rules were violated.
-   Naming remains consistent.
-   Existing abstractions are reused instead of duplicated.
-   The design remains extensible.
