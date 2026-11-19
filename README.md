# mcmanager

Minecraft server management software for local networks, built with Python and Flask. The manager supports multiple independent server worlds and versions.

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

Start the app by running `app\start.bat` from Explorer or Command Prompt. The
batch file creates a local virtual environment, installs runtime dependencies
when they are missing, and starts the server on localhost:

```bat
app\start.bat
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000) and complete the initial
administrator setup.
