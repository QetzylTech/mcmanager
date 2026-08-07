# Document 14: Directory Structure & Coding Standards

Scope: the concrete physical folder layout of the manager codebase, making the layering
rules of ARCHITECTURE.md into a buildable directory tree. Dependency direction is explicit
and enforceable: **routes → commands/queries → services → ports → infrastructure →
platform**. Locks the coding-standards tooling (lint/format/type) in CI.

Governing contracts: layering rules — ARCHITECTURE.md (Web Application, Coding Standards);
service boundaries — Doc 8 (one package per owning service); route catalog — Document 12;
tests — Document 13; UI — Doc 4/5; process-control adapter — Document 15.

## 1. Technology Baseline (locked)

- Python (3.11+), Flask (web framework), SQLite (primary store — ARCHITECTURE.md
  persistence).
- Frontend: vanilla HTML/CSS/JS served by Flask, per Doc 4/5; no separate SPA build step
  (low-hardware constraint). Asset bundling optional; all assets must work unchunked/
  offline.
- Package manager: `pip` + `requirements.txt` (runtime) and `requirements-dev.txt`
  (test/lint tooling). No build system beyond Flask's own.

## 2. Top-Level Layout

```
mcmanager/
├── app/                      # application package (the manager)
├── tests/                    # Document 13 test pyramid
├── benchmarks/               # Document 13 performance suite + thresholds.json
├── migrations/               # schema_migrations versioned SQL (Doc 7)
├── docs/                     # ARCHITECTURE.md, CONTEXT_MAP.md, Documents 4-8, 11-15
├── static/                   # served assets (CSS/JS/images, Document 4)
├── templates/                # Jinja2 templates (persistent shell + page fragments, Doc 5)
├── prototypes/               # legacy reference material only — never imported by app/
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml            # tool config: black, isort, ruff, mypy, pytest (§5)
├── .env.example              # non-secret runtime config only
└── README.md
```

Rules:
- `app/` never imports from `prototypes/`, `benchmarks/`, `tests/`, or `docs/`.
- `docs/` may contain examples and DDL extracts but is never executed or imported.
- Only `migrations/` and `app/` may touch the live database.

## 3. Application Package Layout

```
app/
├── __init__.py               # create_app() factory; registers blueprints; boot reconciliation hook (Doc 7 §6)
├── config.py                 # environment/instance config loading (paths, refresh rates — non-secret)
├── bootstrap.py              # setup state machine (Manager lifecycle, Doc 6 §2.10); applied after create_app
├── shell/                    # PRESENTATION PLANE (ARCHITECTURE.md §1)
│   ├── __init__.py
│   ├── routes.py             # page routes (HTML), thin — render templates only, no business logic
│   ├── templates/            # shared shell layout, page fragments (Doc 4)
│   ├── static/               # shell-level JS (per-tab SSE clients) and CSS build entry
│   └── client_stream.py      # shell-owned shared client state + SSE hub client-side contract
├── web/                      # HTTP/API & session gateway + realtime streams (ARCHITECTURE.md §1)
│   ├── __init__.py
│   ├── middleware.py         # session authn, CSRF, step-up enforcement, throttling hooks (Document 12)
│   ├── errors.py             # error envelope + error-code mapping (Document 12)
│   ├── serializers.py        # DB epoch → ISO-8601 and entity → JSON shapes (Document 12)
│   ├── api/                  # /api blueprints — THIN routes (ARCHITECTURE.md "Keep API endpoints thin")
│   │   ├── __init__.py       # registers every blueprint below
│   │   ├── auth.py           # /api/auth*            (Document 12)
│   │   ├── session.py        # /api/session          (Document 12)
│   │   ├── worlds.py         # /api/worlds*
│   │   ├── operations.py     # /api/operations*
│   │   ├── backups.py        # /api/backups*, /restores, /rollback
│   │   ├── cleanup.py        # /api/cleanup*
│   │   ├── sync.py           # /api/sync*
│   │   ├── schedules.py      # /api/schedules, /missed-runs
│   │   ├── settings.py       # /api/settings, /manager*, /setup
│   │   ├── templates_runtimes.py  # /api/templates, /api/java-runtimes
│   │   ├── admin.py          # /api/users, roles, permissions, devices
│   │   ├── notifications.py  # /api/notifications*
│   │   ├── audit.py          # /api/audit*
│   │   ├── files.py          # /api/worlds/*/files*
│   │   ├── logs.py           # /api/worlds/*/logs*
│   │   └── system.py         # /api/health, /api/system/stats, /api/diagnostics
│   └── streams/              # /stream SSE blueprints (Document 12)
│       ├── __init__.py
│       ├── manager_events.py # /stream/events
│       ├── world_events.py   # /stream/worlds/{id}/events
│       ├── world_logs.py     # /stream/worlds/{id}/logs
│       ├── restore_logs.py   # /stream/restore_logs
│       └── metrics.py        # /stream/metrics
├── commands/                 # COMMAND & QUERY layer (thin dispatch, no business logic)
│   ├── __init__.py           # registry: op_type -> Command class
│   ├── base.py               # Command protocol: preconditions -> create Operation -> dispatch; Query protocol
│   ├── world.py              # CreateWorld, DeleteWorld, RenameWorld command handlers
│   ├── runtime.py            # Start, Stop, Kill command handlers
│   ├── backup.py             # Backup, ManagerBackup command handlers
│   ├── restore.py            # Restore, corrective-rollback command handlers
│   ├── cleanup.py            # Cleanup dry/wet command handlers
│   ├── sync.py               # Sync (re)trigger command handler
│   ├── config.py             # ConfigEdit handlers for every versioned entity (Document 11)
│   ├── crash.py              # CrashDetected (system-actor) handler
│   └── queries.py            # read models assembled via services (world list/detail, histories, stats)
├── services/                 # SERVICE LAYER — one module per owning service (Doc 8)
│   ├── __init__.py
│   ├── world.py              # WorldService
│   ├── runtime.py            # RuntimeService
│   ├── operations.py         # OperationService
│   ├── backup.py             # BackupService
│   ├── restore.py            # RestoreService
│   ├── cleanup.py            # CleanupService — the ONLY place physical DELETE FROM appears
│   ├── sync.py               # SyncService
│   ├── scheduler.py          # SchedulerService
│   ├── auth.py               # AuthenticationService
│   ├── authorization.py      # AuthorizationService
│   ├── notifications.py      # NotificationService
│   ├── audit.py              # AuditService — insert-only (Doc 6)
│   ├── file_manager.py       # FileManagerService
│   ├── templates.py          # TemplateService
│   ├── java_runtimes.py      # JavaRuntimeService
│   ├── configuration.py      # ConfigurationService (3-tier inheritance, optimistic version checks)
│   ├── metrics.py            # MetricsService
│   └── reconciliation.py     # startup reconciliation orchestration (Doc 7 §6)
├── domain/                   # DOMAIN LAYER (Doc 6) — no I/O, no framework imports
│   ├── __init__.py
│   ├── entities.py           # aggregate roots + child entities (WorldInstance, Operation, ...)
│   ├── value_objects.py      # typed enums/VOs from Doc 6 (WorldState, TriggerType, Severity, SyncOutcome, EndReason, ...)
│   ├── lifecycle.py          # state-machine transition guards (Doc 6)
│   ├── invariants.py         # business invariants (Doc 6) as pure predicates
│   ├── events.py             # domain event definitions (Doc 6 catalog)
│   └── deletion_tiers.py     # Tier 1/Tier 2 classification table (Doc 6) — read by cleanup + schema tooling
├── ports/                    # PORT interfaces (abstract; no implementation)
│   ├── __init__.py
│   ├── process_control.py    # ProcessControlPort (Document 15) — spawn/track/kill/tail
│   ├── filesystem.py         # FilesystemPort (guarded path ops, disk-usage checks)
│   ├── backup_engine.py      # native portable backup engine port
│   ├── sync_transport.py     # SyncAdapter port (NAS/Drive, Doc 6)
│   ├── notification.py       # future NotificationAdapter port (Discord/webhook, Doc 6)
│   ├── metrics_export.py     # future MetricsExportAdapter port (Prometheus/Grafana, Doc 6)
│   ├── clock.py              # Clock port (injectable epoch-seconds source — Document 13)
│   └── secrets_store.py      # SecretsStore port in front of `secrets` table (Doc 7)
├── infrastructure/           # concrete implementations of ports
│   ├── __init__.py
│   ├── sqlite/
│   │   ├── __init__.py
│   │   ├── connection.py     # PRAGMA foreign_keys=ON enforcement on every connection (ARCHITECTURE.md)
│   │   ├── repository.py     # generic row<->entity mapping
│   │   ├── operations_repo.py# derived world lock query (Document 11)
│   │   ├── audit_repo.py     # insert-only audit persistence
│   │   └── migrations.py     # schema_migrations runner + PRAGMA foreign_key_check sweep (Doc 7)
│   ├── secrets.py            # SecretsStore impl: encrypt-at-rest in `secrets` table (Doc 7)
│   ├── filesystem.py         # FilesystemPort impl (path-policy enforcement)
│   ├── backup_engine.py      # native portable backup engine (zip/snapshot logic)
│   ├── sync_transport/
│   │   ├── nas.py            # network-storage target (first supported)
│   │   └── google_drive.py   # future target — stub behind port
│   └── metrics.py            # metrics collector impl (psutil or equivalent), cadence per Document 12
└── platform/                 # PLATFORM ADAPTERS — OS-specific, the ONLY place platform imports live
    ├── __init__.py
    ├── process/
    │   ├── base.py           # shared cross-platform process-supervision helpers (Document 15)
    │   ├── posix.py          # POSIX impl (no systemd/journalctl — pure posix_spawn/subprocess, Document 15)
    │   ├── windows.py        # Windows impl (CREATE_NEW_PROCESS_GROUP / job objects, Document 15)
    │   └── tailing.py        # bounded line-buffer + SSE-ready line emitter (Document 15)
    ├── paths.py              # per-OS default root resolution (manager config/data/logs)
    └── process_health.py     # PID reuse guards, orphan detection, exit-status classification (Document 15)
```

## 4. Dependency Rule (enforced)

The layering rule from ARCHITECTURE.md is physical, not just stylistic:

```
templates/ static/     (presentation)
   →  web/             (routes/streams)
   →  commands/        (thin dispatch)
   →  services/        (business rules)
   →  ports/           (interfaces)
   →  infrastructure/  (storage, engines)
   →  platform/        (OS-specific)
```

- **Imports only flow downward** along that chain. `services/` may import `domain/`,
  `ports/`, `infrastructure/` (via DI wiring, not by concrete lookup). `web/` may import
  `commands/` and `services/` but never `infrastructure/` or `platform/` directly.
- `domain/` imports nothing outside itself and the stdlib — no Flask, no SQLite, no
  adapter.
- `platform/` is leaf-only: imported by nothing except the composition root (see §5) and
  `infrastructure/` where an adapter is platform-bound. No `services/` module ever imports
  `platform/` directly.
- **DI wiring lives in one composition root** (`app/bootstrap.py` + `app/__init__.py`):
  all port→implementation bindings are resolved there. Services receive ports via
  constructor injection; they never import a concrete implementation.
- Enforced in CI: a boundary test (Document 13 §2 Maintainability gate) asserts the import
  graph — e.g. `services/*` importing `platform/*` fails the build. Tooling:
  `import-linter` (or equivalent) in `requirements-dev.txt` with contracts in
  `pyproject.toml`.

## 5. Composition & Boot

`app/__init__.py::create_app()` sequence:

1. Load config (environment + instance file; non-secret only).
2. Open SQLite with `PRAGMA foreign_keys = ON`; run `schema_migrations`, then
   `PRAGMA foreign_key_check` sweep — any violation is startup-blocking (ARCHITECTURE.md
   global persistence invariant, Doc 7).
3. Build composition root: construct each port's concrete implementation (per-platform
   process adapter, filesystem, backup engine, secrets store, clock, sync transports) and
   inject into services.
4. Run startup reconciliation (Doc 7 §6) via `services/reconciliation.py` — must complete
   before serving requests.
5. Register blueprints: shell page routes + all `/api` + all `/stream`.
6. Start background scheduler tick (locked value in Doc 8) and metrics cadence
   (Document 12).

Split-deployment mode (topology B): the worker process imports `commands/` + `services/` +
scheduler directly, sharing the same SQLite store; it never starts the web blueprints. Both
entry points (`wsgi` for web, `worker` for background) share the §5 composition root.

## 6. Naming & Layout Conventions

- Package = subsystem (ARCHITECTURE.md §1); module = one owning service, command class,
  port, or adapter — matching Doc 8's service list so capability ownership is discoverable
  by file path.
- One class per file for commands, ports, adapters. Services may be single classes; large
  services split into focused modules under a package only when the class exceeds ~200
  lines AND cohesion stays intact (Document 13 quality rules; prefer extraction to a new
  collaborating service over a god-module).
- Route handlers keep the thin pattern: authenticate → authorize → validate payload → call
  command/query → serialize → respond. Any branch longer than ~10 lines without a service
  call is a smell.
- File names `snake_case`; class names `PascalCase`; constants `UPPER_SNAKE`.

## 7. Tests Layout

`tests/` mirrors `app/` and the Document 13 pyramid:

```
tests/
├── conftest.py               # shared fixtures: sqlite schema, factories, clock, port fakes
├── unit/                     # Document 13 — domain + services w/ port fakes
│   ├── domain/               #   lifecycle + invariant tests (Doc 6)
│   └── services/
├── integration/              # Document 13 — services + real SQLite + adapters
│   ├── schema/               #   migrations + foreign_key_check sweep
│   ├── operations/           #   all 11 op types end-to-end service flows
│   ├── concurrency/          #   Document 11 matrix parametrized
│   ├── optimistic_lock/      #   Document 11 all versioned tables
│   ├── scheduler/            #   tick/dispatch/missed-run
│   ├── restore/              #   checkpoint interrupts at every stage
│   ├── audit/                #   audit-row exactness + immutability
│   └── security/             #   separate CI job (Document 13)
├── e2e/                      # Document 13 — real server + fake server binary
└── adapters/                 # Document 15 conformance suite (per adapter, per OS)
```

Benchmarks live in `benchmarks/` with `thresholds.json` (Document 13).

## 8. Coding Standards (Tooling Locks)

| Tool | Role | Config location | Key settings |
|---|---|---|---|
| `black` | formatter | `pyproject.toml [tool.black]` | line length 100; single quotes |
| `isort` | import ordering | `pyproject.toml [tool.isort]` | profile=black; line_length=100 |
| `ruff` | linter | `pyproject.toml [tool.ruff]` | select E,F,W,I,UP,B,SIM; ignore E501 (black handles); ban non-test `except: pass`; no wildcard imports |
| `mypy` | static types | `pyproject.toml [tool.mypy]` | strict mode for `domain/`, `services/`, `ports/`, `commands/`; no `Any` in those layers (ARCHITECTURE.md quality bar) |
| `pytest` | runner | `pyproject.toml [tool.pytest.ini_options]` | testpaths=tests; addopts `--strict-markers` |
| `import-linter` | import-graph enforcement | `pyproject.toml [tool.importlinter]` | contracts for the §4 dependency rules (layering + leaf platform + DI-root-only) |

Rules carried over from ARCHITECTURE.md and made mechanical:

- Functions focused and small: black/ruff enforce formatting; review + behavior criteria
  (Document 13) enforce size/cohesion; a hard 80-line function limit is NOT imposed by
  tools (readability wins over rigidity) — instead a lint rule warns on functions >60
  lines for review.
- Clear docstrings: ruff `D` rules enabled for `domain/`, `services/`, `ports/`,
  `commands/` (public functions require docstrings); private helpers exempt.
- No `typing.Any` in domain/services/ports/commands (mypy strict). `infrastructure/` and
  `platform/` may use narrow, commented exceptions only.
- Explicit types for all function signatures (mypy). No untyped register/DI maps without a
  `# type: ignore` plus reason.
- No implicit stringly-typed enums: closed sets use the `domain/value_objects.py` enums
  (Doc 6, Document 13) — a string compared against a world state is a lint target
  (`TY`-family custom rule or review).
- Do not hand-roll HTML escaping or security utilities — use the framework/Jinja
  mechanisms (`{{ value }}` autoescapes); never a custom escaper.
