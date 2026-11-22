# mcmanager

Minecraft server management software for local networks, built with Python and
Flask. The manager supports multiple independent server worlds and versions.
This is a ground-up rebuild of WebServerByJP focused on concurrent servers and
portability.

## Project layout

- `app/` is the distributable application directory. It contains the startup
  entry point, runtime dependencies, database migrations, the `.env.example`,
  and the location reserved for curated runtime documentation.
- `docs/`, `tests/`, and `benchmarks/` are repository-only project
  documentation, verification suites, and performance tooling; they are not
  required in an app-only production copy.
- `app/data/` contains ignored, machine-local databases, secrets, backups,
  logs, and Minecraft server/world files; `app/runtimes/` contains downloaded
  Java runtimes.
- `dev_tools/` and `dev_artifacts/` contain development-only scripts and
  generated reports/scratch data.

## Work tracking

Use [docs/WORKBOARD.md](docs/WORKBOARD.md) as the current implementation,
verification, and release tracker; it is the source of truth for work status.
Follow [docs/AGENT_DEVELOPMENT_WORKFLOW_SPEC.md](docs/AGENT_DEVELOPMENT_WORKFLOW_SPEC.md)
for the development lifecycle. Numbered product documents and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) remain authoritative for product
behavior and architecture.
Use [Audits/](Audits/) for current audit findings, realignment records, and
supporting verification evidence. Older audit snapshots are retained under
[`old doc/`](old%20doc/) and must not be presented as current evidence.

## Development

Install development dependencies and run tests from the repository root:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```

Start the app from the repository root with:

```console
python app/main.py
```

For an app-only deployment, copy `app/`, install its runtime dependencies from
`requirements.txt`, copy `.env.example` to `.env` in that directory, and run
`python main.py` from inside it. The `.env` file is local configuration and
must not be committed. Open [http://127.0.0.1:5000](http://127.0.0.1:5000) and
complete the initial administrator setup.
