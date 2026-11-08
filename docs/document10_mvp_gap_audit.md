# Document 10 MVP API Gap Audit

This audit excludes manager lifecycle routes, cleanup endpoints/scopes,
middleware, shell, streams, and deployment files as requested.

## Implemented

- Added authenticated `GET /api/operations` and
  `GET /api/worlds/{world_id}/operations` with documented filters, sorting,
  pagination, and decoded operation data.
- Changed unknown operation reads to the canonical `OP_NOT_FOUND` response.
- Backed `/api/system/stats` with the existing cached metrics service and
  returned its freshness timestamp in response metadata.
- Reduced public `/api/health` to database status and version; moved component
  detail to authenticated diagnostics and added foreign-key, reconciliation,
  and operation-backlog checks.
- Added effective permission grants and current device context to session
  responses; serialized session and step-up expiry timestamps as ISO-8601 UTC.

## Bounded Blockers

- **Server-properties API:** Both documented routes are absent. A versioned
  schema validator and property parser exist, but there is no guarded editor
  service or operation-dispatch path to preserve managed keys, unknown and
  deprecated properties, and file content while validating and auditing edits.
  Define that application-service contract before adding route handlers.
- **Session settings visibility:** The session route now exposes roles, grants,
  and device context, but neither Document 10 nor the persisted schema defines
  how settings visibility is derived or shaped. Product policy is needed before
  returning that field.
- **Client-grant authorization:** Permission grants are now surfaced to the
  client, but request authorization is role-based in middleware and does not
  enforce per-client grants. Middleware was an explicit no-edit boundary; this
  requires a separately owned authorization change before claiming `C` route
  parity.
- **Complete diagnostics telemetry:** Diagnostics now report foreign-key
  status, reconciliation, and queued/in-flight operations. The application has
  no telemetry source for scheduler last/next tick, SQLite busy/wedge state,
  process-adapter last-poll health, or the last successful checkpoint. Those
  fields need instrumentation before they can be reported accurately.
- **Release version:** The health response currently reports `dev`; the repo has
  no declared build/package version source. Wire a release version at build or
  startup before treating this as production version metadata.