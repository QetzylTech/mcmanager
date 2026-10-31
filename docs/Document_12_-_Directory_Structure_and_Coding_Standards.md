# Document 12: Directory Structure & Coding Standards

Physical folder layout making ARCHITECTURE layering rules a buildable tree. Dependency direction explicit and enforceable: **routes → commands/queries → services → ports → infrastructure → platform**. Locks coding tooling (lint/format/type) in CI.

Governing: layering — ARCHITECTURE (Web Application, Coding Standards); service boundaries — Doc 8 (one package per owning service); route catalog — Doc 10; tests — Doc 11; UI — Doc 4/5; process-control adapter — Doc 13; Minecraft adapter — Doc 14.

## 1 Technology baseline (locked)

- Python 3.11+, Flask, SQLite (primary store — ARCHITECTURE persistence).
- Frontend: vanilla HTML/CSS/JS served by Flask, per Doc 4/5; no separate SPA build step (low-hardware constraint). Asset bundling optional; all assets work unchunked/offline.
- Package manager: `pip` + `requirements.txt` (runtime) + `requirements-dev.txt` (test/lint). No build system beyond Flask's own.

## 2 Top-level layout

```
mcmanager/
├── app/                      # application package (the manager)
├── tests/                    # Doc 11 pyramid
├── benchmarks/               # Doc 11 performance suite + thresholds.json
├── migrations/               # schema_migrations versioned SQL (Doc 7)
├── docs/                     # ARCHITECTURE.md + Documents 4-14
├── static/                   # served assets (CSS/JS/images, Doc 4)
├── templates/                # Jinja2 templates (persistent shell + page fragments, Doc 5)
├── prototypes/               # legacy reference only — never imported by app/
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml            # tool config: black, isort, ruff, mypy, pytest (§5)
├── .env.example              # non-secret runtime config only; includes VERBOSE_LOGGING=false
└── README.md
```

Rules: `app/` never imports from `prototypes/`, `benchmarks/`, `tests/`, `docs/`. `docs/` may contain examples/DDL extracts but is never executed or imported. Only `migrations/` + `app/` may touch the live database.

## 3 Application package layout

```
app/
├── __init__.py               # create_app() factory; registers blueprints; boot reconciliation hook (Doc 7 §6)
├── config.py                 # env/instance config loading (paths, refresh rates — non-secret)
├── bootstrap.py              # setup state machine (Manager lifecycle, Doc 6 §2.10); applied after create_app
├── shell/                    # PRESENTATION PLANE (ARCHITECTURE §4)
│   ├── __init__.py
│   ├── routes.py             # page routes (HTML), thin — render templates only, no business logic
│   ├── templates/            # shared shell layout, page fragments (Doc 4)
│   ├── static/               # shell-level JS (BroadcastChannel SSE connection manager and client listeners) and CSS build entry
│   └── client_stream.py      # shell-owned shared client state + SSE hub client-side contract
├── web/                      # HTTP/API + session gateway + realtime streams
│   ├── __init__.py
│   ├── middleware.py         # session authn, CSRF, step-up enforcement, throttling hooks (Doc 10)
│   ├── errors.py             # error envelope + error-code mapping (Doc 10)
│   ├── serializers.py        # DB epoch → ISO-8601 and entity → JSON shapes (Doc 10)
│   ├── api/                  # /api blueprints — THIN routes
│   │   ├── __init__.py       # registers every blueprint
│   │   ├── auth.py           # /api/auth*
│   │   ├── session.py        # /api/session
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
│   └── streams/              # /stream SSE blueprints (Doc 10)
│       ├── __init__.py
│       ├── manager_events.py # /stream/events
│       ├── world_events.py   # /stream/worlds/{id}/events
│       ├── world_logs.py     # /stream/worlds/{id}/logs
│       ├── restore_logs.py   # /stream/restore_logs
│       └── metrics.py        # /stream/metrics
├── commands/                 # COMMAND & QUERY layer (thin dispatch, no business logic)
│   ├── __init__.py           # registry: op_type -> Command class
│   ├── base.py               # Command protocol: preconditions -> create Operation -> dispatch; Query protocol
│   ├── world.py              # CreateWorld, DeleteWorld, RenameWorld handlers
│   ├── runtime.py            # Start, Stop, Kill handlers
│   ├── backup.py             # Backup, ManagerBackup handlers
│   ├── restore.py            # Restore, corrective-rollback handlers
│   ├── cleanup.py            # Cleanup dry/wet handlers
│   ├── sync.py               # Sync (re)trigger handler
│   ├── config.py             # ConfigEdit handlers for every versioned entity (Doc 9)
│   ├── crash.py              # CrashDetected (system-actor) handler
│   └── queries.py            # read models via services (world list/detail, histories, stats)
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
│   ├── entities.py           # aggregate roots + child entities
│   ├── value_objects.py      # typed enums/VOs from Doc 6 (WorldState, TriggerType, Severity, SyncOutcome, EndReason, ...)
│   ├── lifecycle.py          # state-machine transition guards (Doc 6)
│   ├── invariants.py         # business invariants (Doc 6) as pure predicates
│   ├── events.py             # domain event definitions (Doc 6 catalog)
│   └── deletion_tiers.py     # Tier 1/Tier 2 classification table (Doc 6); read by cleanup + schema tooling
├── ports/                    # PORT interfaces (abstract; no implementation)
│   ├── __init__.py
│   ├── process_control.py    # ProcessControlPort (Doc 13) — spawn/track/kill/tail
│   ├── filesystem.py         # FilesystemPort (guarded path ops, disk-usage checks)
│   ├── backup_engine.py      # native portable backup engine port
│   ├── sync_transport.py     # SyncAdapter port (NAS/Drive, Doc 6)
│   ├── notification.py       # future NotificationAdapter port (Discord/webhook, Doc 6)
│   ├── metrics_export.py     # future MetricsExportAdapter port (Prometheus/Grafana, Doc 6)
│   ├── clock.py              # Clock port (injectable epoch-seconds source — Doc 11)
│   ├── secrets_store.py      # SecretsStore port in front of `secrets` table (Doc 7)
│   └── minecraft.py          # MinecraftServerPort (Doc 14) — capability record, readiness
│                             # evaluator, EULA detect/accept, version-aware properties
│                             # validator, save-coordination commands
├── infrastructure/           # concrete port implementations
│   ├── __init__.py
│   ├── sqlite/
│   │   ├── __init__.py
│   │   ├── connection.py     # PRAGMA foreign_keys=ON enforcement on every connection (ARCHITECTURE)
│   │   ├── repository.py     # generic row<->entity mapping
│   │   ├── operations_repo.py# derived world lock query (Doc 9)
│   │   ├── audit_repo.py     # insert-only audit persistence
│   │   └── migrations.py     # schema_migrations runner + PRAGMA foreign_key_check sweep (Doc 7)
│   ├── secrets.py            # SecretsStore impl: encrypt-at-rest in `secrets` table (Doc 7)
│   ├── filesystem.py         # FilesystemPort impl (path-policy enforcement)
│   ├── backup_engine.py      # native portable backup engine (ZIP + SHA-256, Doc 14 §11)
│   ├── minecraft/            # MinecraftServerPort impls (Doc 14) — per server type
│   │   ├── __init__.py
│   │   ├── capabilities.py   # capability records per server type (Doc 14 §2)
│   │   ├── readiness.py      # readiness-level evaluator (Doc 14 §3)
│   │   ├── eula.py           # eula.txt detection + explicit acceptance write (Doc 14 §5)
│   │   ├── properties_schema.py  # version-aware server.properties schema (Doc 14 §6)
│   │   ├── java_compatibility.py # Java major compatibility matrix (Doc 14 §7)
│   │   └── rcon.py           # RCON client + safe command allowlist (Doc 14 §8)
│   ├── sync_transport/
│   │   ├── nas.py            # network-storage target (first supported)
│   │   └── google_drive.py   # future target — stub behind port
│   └── metrics.py            # metrics collector impl (psutil or equivalent), cadence per Doc 10
└── platform/                 # PLATFORM ADAPTERS — OS-specific, the ONLY place platform imports live
    ├── __init__.py
    ├── process/
    │   ├── base.py           # shared cross-platform process-supervision helpers (Doc 13)
    │   ├── posix.py          # POSIX impl (no systemd/journalctl — pure posix_spawn/subprocess, Doc 13)
    │   ├── windows.py        # Windows impl (CREATE_NEW_PROCESS_GROUP / job objects, Doc 13)
    │   └── tailing.py        # bounded line-buffer + SSE-ready line emitter (Doc 13)
    ├── paths.py              # per-OS default root resolution (manager config/data/logs)
    └── process_health.py     # PID reuse guards, orphan detection, exit-status classification (Doc 13)
```

## 4 Dependency rule (enforced)

Physical, not just stylistic:

```
templates/ static/     (presentation)
   →  web/             (routes/streams)
   →  commands/        (thin dispatch)
   →  services/        (business rules)
   →  ports/           (interfaces)
   →  infrastructure/  (storage, engines)
   →  platform/        (OS-specific)
```

- **Imports only flow downward.** `services/` may import `domain/`, `ports/`, `infrastructure/` (via DI wiring, not concrete lookup). `web/` may import `commands/` + `services/` but never `infrastructure/` or `platform/` directly.
- `domain/` imports nothing outside itself + stdlib — no Flask, no SQLite, no adapter.
- `platform/` is leaf-only: imported by nothing except the composition root (§5) and `infrastructure/` where an adapter is platform-bound. No `services/` module ever imports `platform/` directly.
- **DI wiring lives in one composition root** (`app/bootstrap.py` + `app/__init__.py`): all port→implementation bindings resolved there. Services receive ports via constructor injection; never import a concrete implementation.
- Enforced in CI: boundary test (Doc 11 §2 Maintainability gate) asserts the import graph — `services/*` importing `platform/*` fails the build. Tooling: `import-linter` (or equivalent) in `requirements-dev.txt` with contracts in `pyproject.toml`.

## 5 Composition & boot

`app/__init__.py::create_app()` sequence:
1. Load config (environment + instance file; non-secret only).
2. Open SQLite with `PRAGMA foreign_keys = ON`; run `schema_migrations`, then `PRAGMA foreign_key_check` sweep — any violation startup-blocking (ARCHITECTURE persistence invariant, Doc 7).
3. Build composition root: construct each port's concrete implementation (per-platform process adapter, filesystem, backup engine, secrets store, clock, sync transports); inject into services.
4. Run startup reconciliation (Doc 7 §6) via `services/reconciliation.py` — must complete before serving requests.
5. Register blueprints: shell page routes + all `/api` + all `/stream`.
6. Start background scheduler tick (locked value Doc 8) + metrics cadence (Doc 10).

Split-deployment mode (topology B): worker process imports `commands/` + `services/` + scheduler directly, sharing the same SQLite store; never starts web blueprints. Both entry points (`wsgi` web, `worker` background) share the §5 composition root.

## 6 Naming & layout conventions

- Package = subsystem (ARCHITECTURE planes); module = one owning service/command/port/adapter — matching Doc 8's service list so capability ownership is discoverable by file path.
- One class per file for commands, ports, adapters. Services may be single classes; large services split into focused modules under a package only when the class exceeds ~200 lines AND cohesion stays intact (Doc 11; prefer extraction to a new collaborating service over a god-module).
- Route handlers keep the thin pattern: authenticate → authorize → validate payload → call command/query → serialize → respond. Any branch >~10 lines without a service call is a smell.
- File names `snake_case`; classes `PascalCase`; constants `UPPER_SNAKE`.

## 7 Tests layout

`tests/` mirrors `app/` and the Doc 11 pyramid:

```
tests/
├── conftest.py               # shared fixtures: sqlite schema, factories, clock, port fakes
├── unit/                     # Doc 11 — domain + services w/ port fakes
│   ├── domain/               #   lifecycle + invariant tests (Doc 6)
│   └── services/
├── integration/              # Doc 11 — services + real SQLite + adapters
│   ├── schema/               #   migrations + foreign_key_check sweep
│   ├── operations/           #   all 11 op types end-to-end service flows
│   ├── concurrency/          #   Doc 9 matrix parametrized
│   ├── optimistic_lock/      #   Doc 9 all versioned tables
│   ├── scheduler/            #   tick/dispatch/missed-run
│   ├── restore/              #   checkpoint interrupts at every stage
│   ├── audit/                #   audit-row exactness + immutability
│   └── security/             #   separate CI job (Doc 11)
├── e2e/                      # Doc 11 — real server + fake server binary
└── adapters/                 # Doc 13 conformance suite (per adapter, per OS);
                              # Doc 14 save-coordination + EULA behavior tests against the
                              # fake server (fake gains --save-slow / --ignore-save-on modes,
                              # Doc 14 §13)
```

Benchmarks live in `benchmarks/` with `thresholds.json` (Doc 11).

## 8 Coding standards (tooling locks)

| Tool | Role | Config location | Key settings |
|---|---|---|---|
| `black` | formatter | `pyproject.toml [tool.black]` | line length 100; single quotes |
| `isort` | import ordering | `pyproject.toml [tool.isort]` | profile=black; line_length=100 |
| `ruff` | linter | `pyproject.toml [tool.ruff]` | select E,F,W,I,UP,B,SIM; ignore E501 (black handles); ban non-test `except: pass`; no wildcard imports |
| `mypy` | static types | `pyproject.toml [tool.mypy]` | strict for `domain/`, `services/`, `ports/`, `commands/`; no `Any` in those layers |
| `pytest` | runner | `pyproject.toml [tool.pytest.ini_options]` | testpaths=tests; addopts `--strict-markers` |
| `import-linter` | import-graph enforcement | `pyproject.toml [tool.importlinter]` | contracts for the §4 dependency rules (layering + leaf platform + DI-root-only) |

Rules carried over from ARCHITECTURE and made mechanical:
- Functions focused and small; black/ruff enforce formatting; Doc 11 review + behavior criteria enforce size/cohesion; no hard 80-line function limit (readability wins) — instead a lint rule warns on functions >60 lines for review.
- Clear docstrings: ruff `D` rules enabled for `domain/`/`services/`/`ports/`/`commands/` (public functions require docstrings; private helpers exempt).
- No `typing.Any` in domain/services/ports/commands (mypy strict). `infrastructure/` + `platform/` may use narrow, commented exceptions only.
- Explicit types for all function signatures (mypy). No untyped register/DI maps without a `# type: ignore` + reason.
- No implicit stringly-typed enums: closed sets use `domain/value_objects.py` enums (Doc 6, Doc 11) — a string compared against a world state is a lint target.
- Do not hand-roll HTML escaping or security utilities — use framework/Jinja mechanisms (`{{ value }}` autoescapes); never a custom escaper.
