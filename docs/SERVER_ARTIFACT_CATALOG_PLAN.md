# In-App Server Artifact Catalog and Downloader Plan

**Status:** Proposed implementation plan; application behavior is not yet
implemented. The user-approved first-release decisions are recorded below;
the governing contracts must be reconciled and independently reviewed before
application implementation. This plan records the requested replacement of
the ignored `app/data/serverjars/minecraft_server_archive.py` utility with an
application module. It does not authorize deleting the local utility or archive
before the cutover criteria below pass.

## Goal

Move server-software discovery, download, verification, cataloging, and
world-provisioning into MCManager. Operators must be able to use the app
without running a separate Python script. After successful cutover, the
external downloader is removed while existing server artifacts and recoverable
metadata are preserved.

## Current behavior to replace

The local utility supports Vanilla, Purpur, Paper, Fabric, Forge, and NeoForge.
It discovers provider metadata, defaults to recent/recommended provider
artifacts, and optionally enumerates all builds where the provider API permits
it. Downloads are concurrent; existing files are skipped unless forced;
partial files use a `.part` suffix, retry up to three times, and are renamed
into place after a non-empty response. It records provider/version/build data,
source URL, size, SHA-256, download time, and Vanilla's expected SHA-1 in a
JSON manifest. The default destination is relative to the process working
directory, and manifest file keys are absolute paths.

The script does not install Forge/NeoForge installers into runnable servers.
Fabric artifacts are launchers that may fetch additional components at first
run. The app must preserve these distinctions instead of treating every
downloaded `.jar` as a runnable server.

## Target architecture

- `ServerArtifactService` owns provider catalog orchestration, artifact
  selection, durable download-job lifecycle, verification, provenance, and
  provisioning decisions. It does not contain provider HTTP parsing or route
  logic.
- `ServerArtifactProviderPort` defines the metadata and download contract.
  Provider-specific HTTPS clients live under
  `app/infrastructure/minecraft/providers/`.
- The existing filesystem/storage boundary owns safe writes into a
  manager-controlled artifact root at `<manager-data-root>/serverjars`. The
  root is resolved from application configuration, never the process working
  directory or an arbitrary provider-supplied path. Downloads obey the
  architecture storage guard's 10 GB default free-space reserve
  (10,000,000,000 bytes).
- Thin API routes expose catalog, download-job, and artifact status operations.
  The World Template Catalog UI is the operator entry point. Exact routes,
  permissions, response shapes, and error codes are defined in Document 10.
- CreateWorld selects an already acquired artifact, validates its provider,
  Minecraft version, build, and artifact kind, and provisions it into the
  stable world directory. It must not depend on a live provider request during
  world creation. Start continues to require a valid runnable server setup.
- Use a durable `Download` Operation for each acquisition. Downloads are
  cancellable through `Running`; cancellation closes the response and removes
  only that operation's `.part` file. Interrupted jobs are reconciled on
  restart and can be retried explicitly. Catalog refresh is a bounded metadata
  read and does not create an Operation.
- The authoritative catalog is SQLite. The legacy JSON manifest is migration
  input only. Migration runs are durable `ServerArtifactMigration` Operations
  with recorded backup, staging, outcome, and rollback state.

## Approved first-release behavior

- Discover and download Vanilla, Purpur, Paper, Fabric, Forge, and NeoForge
  artifacts. Latest/recommended is the default selection. Enumerating all
  builds is explicit opt-in and paginated at 50 results per page.
- `POST /api/worlds` requires an explicit `server_artifact_id`. The selected
  template defines compatibility constraints; it does not store or silently
  select the artifact.
- Only verified runnable artifacts for Vanilla, Paper, or Purpur may be
  provisioned by this release. Fabric launchers and Forge/NeoForge installers
  remain catalogued with their actual artifact kind and are rejected by
  CreateWorld. Provider-specific preparation is out of scope until a separate
  plan is approved.
- Artifact APIs use dedicated `server_artifact.view` and
  `server_artifact.manage` grants; the existing Admin/Superadmin baseline
  remains. Legacy migration additionally requires Admin+ step-up.
- Idempotency follows Document 10: the same key and operation type replay the
  original Operation, including when a retry body differs. Clients must use a
  new key for a new request; this feature does not introduce a payload-conflict
  exception.
- At most two downloads run concurrently. Each artifact is limited to 1 GiB;
  the architecture's 10 GB (10,000,000,000-byte) free-space reserve is enforced before and during
  transfer. A transfer makes at most three attempts with bounded backoff.
  Re-downloading an existing artifact requires an explicit force flag and never
  overwrites a different content digest.
- Download progress and terminal failures are durable and auditable. A running
  Download may be cooperatively cancelled; its unpublished temporary file is
  removed. Provider calls, redirects, file destinations, and response sizes are
  constrained by the documented security contract.

## Artifact identity, creation, and integrity contract

Use a SQLite-backed `server_artifacts` catalog and durable `Download`
Operations. Each catalog row has a stable `artifact_id` derived from the
SHA-256 of canonical JSON containing provider, game version, build, artifact
kind, and content SHA-256. Artifact kind is one of `runnable_server`,
`launcher`, or `installer` in this release. Store those source fields, the
managed-root-relative path, size, upstream checksums, source URL, and
verification/download timestamps. An identical descriptor and digest resolves
to the same ID; different bytes never overwrite an existing artifact record.

Add nullable `server_artifact_id` and immutable
`server_artifact_provenance_json` fields to `world_instances` in a schema
migration. Null remains valid for legacy worlds. The snapshot records the
artifact ID, provider, game version, build, kind, SHA-256, source checksum,
runtime relative path (`server.jar`), runtime server-file SHA-256, and
non-secret provisioning metadata. The first release has no preparation
recipe. For a copied runnable artifact, the runtime hash equals the catalog
content hash. Installer/launcher preparation is not supported in this release.
This preserves provenance if a catalog row is later retired.

Require `server_artifact_id` in `POST /api/worlds`. Resolve it to a verified
catalog entry and reject missing, incompatible, non-runnable, or unsupported
provider artifacts before queuing CreateWorld. Only Vanilla, Paper, and Purpur
runnable artifacts are provisionable in this release. Persist the selected ID
and provenance snapshot with the world record. Follow Document 10's existing
same-key/same-operation-type replay behavior; a distinct request must use a
new key. Provision through a world-ID-scoped temporary directory, verify the
artifact as `server.jar`, verify the copied runtime hash, then atomically
publish it. The launch context must use that exact contained path; a custom
full-argv override is accepted only if its `-jar` target resolves to the same
`server.jar`. A replay must not copy again; recovery may accept an existing
target only when its recorded hash matches.

Immediately before spawn, re-hash the world-local configured server file and
compare it with the provenance runtime hash. Require a verified runnable
Vanilla, Paper, or Purpur artifact; installer-only and launcher artifacts fail
before spawn. A mismatch returns `SERVER_ARTIFACT_INTEGRITY_FAILED`, marks the
Start operation failed with that error, and records the audit event. Legacy
worlds without provenance retain the existing non-empty-file check and are
explicitly reported as unverified; do not infer their trust from the old
manifest.

## Legacy manifest migration policy

Migration is an explicit, restartable catalog operation, not a startup side
effect. The legacy source root is the existing `<application-root>/data/serverjars`
directory (currently `app/data/serverjars`); the destination is the configured
manager data root's `serverjars` directory. Resolve both roots once at
operation start and record the root kind in the migration run. If they resolve
to the same directory, migrate in place; otherwise copy only verified
candidates through destination `.part` files, recheck SHA-256, and atomically
publish without overwriting a different digest. Keep all source files intact.
Back up the original manifest byte-for-byte under the source root before
processing and never follow its absolute paths. Resolve candidates only beneath
the legacy source root: require a unique contained candidate matching the
recorded filename, size, and SHA-256. Missing hashes, ambiguous matches,
path escapes, invalid metadata, and digest mismatches become durable unresolved
records with reason codes; they are not imported as verified artifacts.
Duplicate identity plus digest deduplicates; identity collisions with different
digests remain separate content-addressed artifacts and are never overwritten.

Inventory archive files not referenced by a successfully matched entry as
durable orphan records for explicit review; expose these records and unresolved
entries through a paginated migration-detail API. Preserve all orphan files.
Build and validate the replacement
catalog in a staging location, then atomically publish it. Keep the source
manifest, archive, and backup until acceptance. On any failure, leave the old
manifest/catalog active and report the failed entry; rollback removes only
new staging data and restores the byte-for-byte backup if publication had
already started.

## NeoForge version mapping

Do not subtract 20 from the first NeoForge version component. When provider
metadata does not expose an explicit Minecraft version, parse a supported
`M.m.build` NeoForge version as Minecraft `1.M.m` and validate it against
provider fixtures before catalog publication. Required fixtures include
`20.2.88 -> 1.20.2`, `20.4.237 -> 1.20.4`, `21.1.172 -> 1.21.1`, and
`21.4.34 -> 1.21.4`; malformed or unsupported forms fail explicitly rather
than guessing. Prefer explicit provider metadata whenever available.

## Phased implementation

1. **Approve behavior and contracts**
   - Inventory the external script and existing archive/manifest.
   - Carry the identity, CreateWorld provenance/idempotency, startup integrity,
     migration, and NeoForge rules above into Documents 5-10 and 14; define the
     API/UI envelopes, permissions, Operation lifecycle, and failure semantics.
     The approved defaults in this plan govern release scope, all-build paging,
     force-redownload, concurrency, retries, size limits, and disk-space safety.
     Installer/launcher preparation remains explicitly out of scope; these
     artifact kinds must not pass the runnable-server check.

2. **Build provider and storage boundaries**
   - Add the provider port, service, and one adapter per supported provider.
   - Parse provider responses defensively; constrain requests to HTTPS and
     documented provider hosts, validate redirects and destination paths, and
     surface provider failures instead of silently reporting success.
   - Implement at most two concurrent transfers, three bounded attempts,
     cooperative cancellation, the 1 GiB artifact limit, the architecture
     storage reserve, non-empty response checks, upstream checksum
     verification where available, local SHA-256, `.part` cleanup, atomic
     promotion, and transactional SQLite catalog updates.
   - Use stable relative artifact identities in the managed root; migrate
     legacy absolute manifest entries only when they resolve safely.

3. **Expose the feature in the app**
   - Add authorized API operations and World Template Catalog UI for listing
     supported providers/builds, starting and observing acquisition jobs, and
     selecting available artifacts.
   - Keep route handlers thin. Long-running work reports durable operation
     status and can recover or fail explicitly after manager restart.
   - Make catalog refresh and downloading safe on constrained hosts; never
     download every historical build implicitly.

4. **Connect artifacts to world creation and startup**
   - Resolve the explicit `server_artifact_id` request field to a verified
     local artifact and validate it against the selected template.
   - Provision/copy only a selected Vanilla, Paper, or Purpur runnable artifact
     into the stable world directory; do not invoke installer/launcher files.
   - Persist enough provenance to identify the exact provider, game version,
     build, artifact kind, and hashes used by the world.
   - Reject missing, corrupt, incompatible, or installer-only artifacts with
     documented errors before Start.

5. **Verify compatibility and cut over**
   - Use recorded provider fixtures and fake HTTP/filesystem implementations
     for deterministic unit/integration tests; no live downloads in normal
     tests.
   - Cover provider parsing, latest/all-build selection, retries, cancellation,
     partial-file cleanup, checksum mismatch, manifest migration, path safety,
     job restart recovery, artifact provisioning, and missing-jar startup
     guards.
   - Run cross-platform focused acceptance and browser flows for download,
     selection, world creation, and Start preparation.
   - Compare the new catalog with the existing archive and reconcile manifest
     provenance. Preserve all valid downloaded server files.
   - Remove the external downloader only after provider parity, migration,
     world provisioning, verification, and rollback evidence pass. Delete the
     specific ignored script file; do not delete the archive or manifest as
     part of script removal.

## Exit criteria

- The app can discover and acquire all six supported provider artifacts without
  invoking or requiring the external script.
- Download state, integrity, artifact kind, provenance, and failures are
  visible and durable.
- A selected Vanilla, Paper, or Purpur runnable artifact can be provisioned for
  a world; Fabric launchers and Forge/NeoForge installers are rejected rather
  than silently treated as runnable servers.
- Existing archive files are retained or safely migrated, with reproducible
  provenance.
- Focused tests and required platform/browser acceptance pass.
- No production code, deployment documentation, or tests reference the removed
  downloader script.

## Decisions resolved before implementation

The user approved the SQLite catalog and legacy-manifest migration, all-six
provider discovery/download with only runnable Vanilla/Paper/Purpur
provisioning, explicit CreateWorld artifact selection, Document 10 idempotency,
dedicated artifact grants, and the bounded discovery/download policy above.
The architecture's 10 GB (10,000,000,000-byte) storage reserve supersedes the proposed 2 GiB reserve
in the approval form. Provider preparation for Fabric/Forge/NeoForge remains
out of scope and requires a separate approved task. All corresponding
numbered-document contracts must pass independent review before implementation.

The work is tracked by `KB-G1-SERVER-JAR-CATALOG`; planning and pseudocode
updates are tracked separately by `KB-G1-SERVER-ARTIFACT-PLAN`.
