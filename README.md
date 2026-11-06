# mcmanager

Minecraft server management software for local networks, built with Python
and Flask. The manager supports multiple independent server worlds and
versions.

## Project layout

- `app/` and `migrations/` contain the application being built.
- `docs/`, `tests/`, and `benchmarks/` contain project documentation,
  verification suites, and performance tooling.
- `app/data/` contains ignored, machine-local databases, secrets, backups,
  logs, and Minecraft server/world files; `app/runtimes/` contains downloaded
  Java runtimes.
- `dev_tools/` and `dev_artifacts/` contain development-only scripts and
  generated reports/scratch data.

## Work tracking

The WBS and realignment Kanban board, including task dependencies and
acceptance evidence, is maintained in [docs/WORKBOARD.md](docs/WORKBOARD.md).

## Development

Run tests from the repository root:

```powershell
python -m pytest
```

Run the app from the repository root:

```powershell
python -m flask --app "app:create_app(database_path='app/data/manager.db', keyfile_path='app/data/secrets.key', migrations_dir='migrations')" run --host 127.0.0.1 --port 5000
```
