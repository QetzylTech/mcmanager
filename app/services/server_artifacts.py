"""Server artifact discovery, durable downloads, migration, and provisioning."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from app.domain.value_objects import ActorType, OperationStatus, OperationType
from app.infrastructure.minecraft.providers import build_provider_adapters
from app.infrastructure.minecraft.providers.base import (
    ArtifactProviderError,
    SafeHttpClient,
    validate_provider_url,
)
from app.ports.clock import Clock
from app.ports.persistence import PersistencePort
from app.ports.server_artifacts import ArtifactDescriptor, ServerArtifactProviderPort
from app.services.operations import (
    OperationInput,
    OperationService,
    OperationStateError,
)

PROVIDERS = ("vanilla", "paper", "purpur", "fabric", "forge", "neoforge")
_RUNNABLE_PROVIDERS = frozenset({"vanilla", "paper", "purpur"})
_ARTIFACT_KINDS = frozenset({"runnable_server", "launcher", "installer"})
_MAX_ARTIFACT_BYTES = 1024**3
_MIN_FREE_BYTES = 10_000_000_000
_CHUNK_BYTES = 1024 * 1024
_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._+-]")
_logger = logging.getLogger(__name__)


class ServerArtifactError(RuntimeError):
    def __init__(self, code: str, message: str, *, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class ServerArtifactService:
    """Orchestrates provider metadata and manager-owned artifact storage."""

    def __init__(
        self,
        store: PersistencePort,
        clock: Clock,
        operations: OperationService,
        artifact_root: str | Path,
        legacy_root: str | Path,
        *,
        http: SafeHttpClient | None = None,
        providers: dict[str, ServerArtifactProviderPort] | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._operations = operations
        self.root = Path(artifact_root).resolve()
        self.legacy_root = Path(legacy_root).resolve()
        self._http = http or SafeHttpClient()
        self._providers = providers or build_provider_adapters(self._http)
        self._queue_lock = threading.Lock()
        self._dispatch_lock = threading.Lock()

    def discover(
        self, *, provider: str, scope: str = "latest", limit: int = 50, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if provider not in self._providers or scope not in {"latest", "all"}:
            raise ServerArtifactError("VALIDATION_ERROR", "Provider or scope is invalid.", status=400)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ServerArtifactError("VALIDATION_ERROR", "limit must be between 1 and 50.", status=400)
        offset = self._decode_cursor(cursor, provider, scope) if cursor else 0
        try:
            descriptors = self._providers[provider].discover(scope=scope)
        except ArtifactProviderError as exc:
            raise ServerArtifactError(
                "SERVER_ARTIFACT_PROVIDER_FAILED", str(exc), status=502
            ) from exc
        page = descriptors[offset : offset + limit]
        next_offset = offset + len(page)
        next_cursor = (
            self._encode_cursor(provider, scope, next_offset)
            if next_offset < len(descriptors)
            else None
        )
        return (
            [descriptor.public_dict() for descriptor in page],
            {"limit": limit, "next_cursor": next_cursor, "has_more": next_cursor is not None},
        )

    @staticmethod
    def provider_catalog() -> list[dict[str, Any]]:
        return [
            {
                "provider": provider,
                "artifact_kinds": (
                    ["runnable_server"]
                    if provider in _RUNNABLE_PROVIDERS
                    else ["launcher"] if provider == "fabric" else ["installer"]
                ),
                "provisionable": provider in _RUNNABLE_PROVIDERS,
            }
            for provider in PROVIDERS
        ]

    def list_catalog(
        self, *, provider: str | None, mc_version: str | None, limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
            raise ServerArtifactError("VALIDATION_ERROR", "Invalid pagination values.", status=400)
        clauses = ["status = 'available'", "deleted_at IS NULL"]
        params: list[Any] = []
        if provider is not None:
            if provider not in self._providers:
                raise ServerArtifactError("VALIDATION_ERROR", "Provider is invalid.", status=400)
            clauses.append("provider = ?")
            params.append(provider)
        if mc_version is not None:
            clauses.append("mc_version = ?")
            params.append(mc_version)
        where = " AND ".join(clauses)
        connection = self._store.reader()
        total = connection.execute(
            f"SELECT count(*) FROM server_artifacts WHERE {where}", params
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT * FROM server_artifacts WHERE {where}
            ORDER BY provider, mc_version, build, server_artifact_id
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
        return [self._public_artifact(dict(row)) for row in rows], {
            "limit": limit,
            "offset": offset,
            "total": int(total),
        }

    def get_artifact(self, artifact_id: str, *, verify_file: bool = True) -> dict[str, Any]:
        row = self._store.reader().execute(
            """
            SELECT * FROM server_artifacts
            WHERE server_artifact_id = ? AND status = 'available' AND deleted_at IS NULL
            """,
            (artifact_id,),
        ).fetchone()
        if row is None:
            raise ServerArtifactError("SERVER_ARTIFACT_NOT_FOUND", "Server artifact was not found.", status=404)
        artifact = dict(row)
        path = self._contained_path(self.root, artifact["relative_path"])
        if path is None or not path.is_file():
            raise ServerArtifactError(
                "SERVER_ARTIFACT_INTEGRITY_FAILED", "Catalog artifact file is missing or unsafe."
            )
        if verify_file and (
            path.stat().st_size != artifact["size_bytes"]
            or self._sha256_file(path) != artifact["sha256"]
        ):
            raise ServerArtifactError(
                "SERVER_ARTIFACT_INTEGRITY_FAILED", "Catalog artifact failed SHA-256 verification."
            )
        return self._public_artifact(artifact)

    def get_provisioning_record(self, artifact_id: str) -> tuple[dict[str, Any], Path]:
        artifact = self.get_artifact(artifact_id, verify_file=True)
        row = self._store.reader().execute(
            "SELECT relative_path, source_url FROM server_artifacts WHERE server_artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        if row is None:
            raise ServerArtifactError("SERVER_ARTIFACT_NOT_FOUND", "Server artifact was not found.", status=404)
        source = self._contained_path(self.root, row["relative_path"])
        if source is None:
            raise ServerArtifactError(
                "SERVER_ARTIFACT_INTEGRITY_FAILED", "Catalog artifact path is unsafe."
            )
        return artifact, source

    def world_provenance(self, artifact_id: str) -> dict[str, Any]:
        artifact, _ = self.get_provisioning_record(artifact_id)
        if (
            artifact["provider"] not in _RUNNABLE_PROVIDERS
            or artifact["artifact_kind"] != "runnable_server"
        ):
            raise ServerArtifactError(
                "SERVER_ARTIFACT_NOT_RUNNABLE",
                "Only verified Vanilla, Paper, or Purpur server jars can be provisioned.",
            )
        return self._provenance(artifact)

    def queue_download(
        self,
        *,
        descriptor_id: str,
        provider: str,
        mc_version: str,
        build: str,
        artifact_kind: str,
        force: bool,
        actor_user_id: str,
        idempotency_key: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, bool]:
        descriptor = self._resolve_descriptor(
            descriptor_id, provider, mc_version, build, artifact_kind
        )
        if (
            descriptor.advertised_size_bytes is not None
            and descriptor.advertised_size_bytes > _MAX_ARTIFACT_BYTES
        ):
            raise ServerArtifactError("SERVER_ARTIFACT_TOO_LARGE", "Artifact exceeds the 1 GiB limit.")
        if (
            descriptor.advertised_size_bytes is not None
            and descriptor.advertised_size_bytes <= 0
        ):
            raise ServerArtifactError(
                "SERVER_ARTIFACT_SIZE_MISMATCH",
                "Provider advertised an invalid artifact size.",
            )
        existing = self._store.reader().execute(
            """
            SELECT * FROM server_artifacts
            WHERE provider = ? AND mc_version = ? AND build = ? AND artifact_kind = ?
              AND status = 'available' AND deleted_at IS NULL
            ORDER BY downloaded_at DESC LIMIT 1
            """,
            (provider, mc_version, build, artifact_kind),
        ).fetchone()
        if existing is not None and not force:
            artifact = self.get_artifact(existing["server_artifact_id"], verify_file=True)
            return artifact, None, False
        with self._queue_lock:
            replay = self._operations.get_by_idempotency_key(OperationType.DOWNLOAD, idempotency_key)
            if replay is not None:
                return None, replay, True
            active = self._store.reader().execute(
                """
                SELECT data_json FROM operations
                WHERE op_type = ? AND status IN (?, ?, ?)
                """,
                (
                    OperationType.DOWNLOAD.value,
                    OperationStatus.QUEUED.value,
                    OperationStatus.VALIDATING.value,
                    OperationStatus.RUNNING.value,
                ),
            ).fetchall()
            identity = (provider, mc_version, build, artifact_kind)
            for row in active:
                data = self._json_object(row["data_json"])
                if tuple(data.get(field) for field in ("provider", "mc_version", "build", "artifact_kind")) == identity:
                    raise ServerArtifactError(
                        "OP_CONFLICT_IN_FLIGHT",
                        "A download for this provider artifact is already in flight.",
                    )
            operation, replayed = self._operations.create_with_replay(
                OperationInput(
                    op_type=OperationType.DOWNLOAD,
                    actor_type=ActorType.USER,
                    actor_user_id=actor_user_id,
                    idempotency_key=idempotency_key,
                    data={
                        "descriptor_id": descriptor_id,
                        "provider": provider,
                        "mc_version": mc_version,
                        "build": build,
                        "artifact_kind": artifact_kind,
                        "force": force,
                    },
                )
            )
        return None, operation, replayed

    def request_migration(
        self, *, actor_user_id: str, idempotency_key: str
    ) -> tuple[dict[str, Any], bool]:
        with self._queue_lock:
            replay = self._operations.get_by_idempotency_key(
                OperationType.SERVER_ARTIFACT_MIGRATION, idempotency_key
            )
            if replay is not None:
                return replay, True
            active = self._store.reader().execute(
                """
                SELECT 1 FROM operations
                WHERE op_type = ? AND status IN (?, ?, ?) LIMIT 1
                """,
                (
                    OperationType.SERVER_ARTIFACT_MIGRATION.value,
                    OperationStatus.QUEUED.value,
                    OperationStatus.VALIDATING.value,
                    OperationStatus.RUNNING.value,
                ),
            ).fetchone()
            if active is not None:
                raise ServerArtifactError(
                    "OP_CONFLICT_IN_FLIGHT", "A server artifact migration is already in flight."
                )
            try:
                return self._operations.create_with_replay(
                    OperationInput(
                        op_type=OperationType.SERVER_ARTIFACT_MIGRATION,
                        actor_type=ActorType.USER,
                        actor_user_id=actor_user_id,
                        idempotency_key=idempotency_key,
                        data={},
                    )
                )
            except sqlite3.IntegrityError as exc:
                if "operations.op_type" in str(exc).lower():
                    raise ServerArtifactError(
                        "OP_CONFLICT_IN_FLIGHT",
                        "A server artifact migration is already in flight.",
                    ) from exc
                raise

    def migration_detail(
        self, op_id: str, *, limit: int = 50, cursor: str | None = None
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ServerArtifactError("VALIDATION_ERROR", "limit must be between 1 and 50.", status=400)
        offset = self._decode_migration_cursor(cursor, op_id) if cursor else 0
        row = self._store.reader().execute(
            "SELECT * FROM server_artifact_migration_runs WHERE operation_id = ?",
            (op_id,),
        ).fetchone()
        if row is None:
            raise ServerArtifactError("OP_NOT_FOUND", "Server artifact migration was not found.", status=404)
        run = dict(row)
        total = self._store.reader().execute(
            "SELECT count(*) FROM server_artifact_migration_entries WHERE operation_id = ?",
            (op_id,),
        ).fetchone()[0]
        entries = self._store.reader().execute(
            """
            SELECT entry_id, entry_kind, source_index, source_name, relative_path,
                   outcome, reason_code, candidate_count, size_bytes, sha256,
                   server_artifact_id
            FROM server_artifact_migration_entries
            WHERE operation_id = ? ORDER BY source_index, entry_kind, entry_id
            LIMIT ? OFFSET ?
            """,
            (op_id, limit, offset),
        ).fetchall()
        next_offset = offset + len(entries)
        next_cursor = (
            self._encode_migration_cursor(op_id, next_offset)
            if next_offset < total
            else None
        )
        return (
            {
                "op_id": op_id,
                "outcome": run["outcome"],
                "source_manifest_sha256": run["source_manifest_sha256"],
                "unresolved_count": run["unresolved_count"],
                "orphan_count": run["orphan_count"],
                "rollback_status": run["rollback_status"],
            },
            [dict(entry) for entry in entries],
            {"limit": limit, "next_cursor": next_cursor, "has_more": next_cursor is not None},
        )

    def dispatch_queued_operations(self) -> list[str]:
        if not self._dispatch_lock.acquire(blocking=False):
            return []
        try:
            running = self._store.reader().execute(
                "SELECT count(*) FROM operations WHERE op_type = ? AND status = ?",
                (OperationType.DOWNLOAD.value, OperationStatus.RUNNING.value),
            ).fetchone()[0]
            slots = max(0, 2 - int(running))
            downloads = self._operations.list_queued((OperationType.DOWNLOAD,))[:slots]
            migrations = self._operations.list_queued(
                (OperationType.SERVER_ARTIFACT_MIGRATION,)
            )
            dispatched: list[str] = []
            claimed_downloads = []
            claimed_migrations = []
            for operation in downloads:
                claimed = self._operations.claim_queued(operation["op_id"])
                if claimed is None:
                    continue
                dispatched.append(claimed["op_id"])
                claimed_downloads.append(claimed)
            for operation in migrations[:1]:
                claimed = self._operations.claim_queued(operation["op_id"])
                if claimed is None:
                    continue
                dispatched.append(claimed["op_id"])
                claimed_migrations.append(claimed)
            if claimed_downloads:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = [
                        executor.submit(self._run_download, operation)
                        for operation in claimed_downloads
                    ]
                    for future in futures:
                        future.result()
            for operation in claimed_migrations:
                self._run_migration(operation)
            return dispatched
        finally:
            self._dispatch_lock.release()

    def reconcile(self) -> None:
        rows = self._store.reader().execute(
            """
            SELECT * FROM operations
            WHERE (op_type = ? AND status = ?)
               OR (op_type = ? AND status = ?)
            ORDER BY created_at, op_id
            """,
            (
                OperationType.DOWNLOAD.value,
                OperationStatus.RUNNING.value,
                OperationType.SERVER_ARTIFACT_MIGRATION.value,
                OperationStatus.RUNNING.value,
            ),
        ).fetchall()
        for row in rows:
            operation = dict(row)
            if operation["op_type"] == OperationType.DOWNLOAD.value:
                self._reconcile_download(operation)
            else:
                self._reconcile_migration(operation)

    def provision_world_artifact(
        self, artifact_id: str, directory: Path, *, operation_id: str
    ) -> dict[str, Any]:
        artifact, source = self.get_provisioning_record(artifact_id)
        if (
            artifact["provider"] not in _RUNNABLE_PROVIDERS
            or artifact["artifact_kind"] != "runnable_server"
        ):
            raise ServerArtifactError(
                "SERVER_ARTIFACT_NOT_RUNNABLE",
                "Only verified Vanilla, Paper, or Purpur server jars can be provisioned.",
            )
        target = directory / "server.jar"
        if target.is_symlink():
            raise ServerArtifactError(
                "SERVER_ARTIFACT_INTEGRITY_FAILED", "World server.jar must not be a symlink."
            )
        if target.exists():
            if target.is_file() and target.stat().st_size == artifact["size_bytes"] and self._sha256_file(target) == artifact["sha256"]:
                return self._provenance(artifact)
            raise ServerArtifactError(
                "SERVER_ARTIFACT_INTEGRITY_FAILED",
                "Existing world server.jar does not match the selected artifact.",
            )
        part = directory / f".server.jar.{operation_id}.part"
        if part.exists() or part.is_symlink():
            raise ServerArtifactError(
                "SERVER_ARTIFACT_INTEGRITY_FAILED", "World provisioning temporary file already exists."
            )
        shutil.copyfile(source, part)
        if part.stat().st_size != artifact["size_bytes"] or self._sha256_file(part) != artifact["sha256"]:
            part.unlink(missing_ok=True)
            raise ServerArtifactError(
                "SERVER_ARTIFACT_INTEGRITY_FAILED", "Provisioned server jar failed hash verification."
            )
        os.replace(part, target)
        return self._provenance(artifact)

    def verify_world_artifact(self, world: dict[str, Any], world_dir: Path) -> None:
        raw = world.get("server_artifact_provenance_json")
        if not raw:
            return
        try:
            provenance = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError) as exc:
            raise ServerArtifactError(
                "SERVER_ARTIFACT_INTEGRITY_FAILED", "World artifact provenance is invalid."
            ) from exc
        if (
            not isinstance(provenance, dict)
            or provenance.get("server_artifact_id") != world.get("server_artifact_id")
            or provenance.get("runtime_relative_path") != "server.jar"
            or provenance.get("provider") not in _RUNNABLE_PROVIDERS
            or provenance.get("artifact_kind") != "runnable_server"
            or provenance.get("sha256") != provenance.get("runtime_sha256")
        ):
            raise ServerArtifactError(
                "SERVER_ARTIFACT_INTEGRITY_FAILED", "World artifact provenance does not match."
            )
        target = self._contained_path(world_dir, provenance["runtime_relative_path"])
        if (
            target is None
            or not target.is_file()
            or target.is_symlink()
            or target.stat().st_size <= 0
            or self._sha256_file(target) != provenance.get("runtime_sha256")
        ):
            raise ServerArtifactError(
                "SERVER_ARTIFACT_INTEGRITY_FAILED", "World server jar failed SHA-256 verification."
            )

    @staticmethod
    def _provenance(artifact: dict[str, Any]) -> dict[str, Any]:
        return {
            "server_artifact_id": artifact["server_artifact_id"],
            "provider": artifact["provider"],
            "mc_version": artifact["mc_version"],
            "build": artifact["build"],
            "artifact_kind": artifact["artifact_kind"],
            "sha256": artifact["sha256"],
            "upstream_checksums": artifact.get("upstream_checksums", {}),
            "runtime_relative_path": "server.jar",
            "runtime_sha256": artifact["sha256"],
        }

    def _run_download(self, operation: dict[str, Any]) -> None:
        op_id = operation["op_id"]
        cancellation = self._operations.register_cancellation(op_id)
        part: Path | None = None
        final: Path | None = None
        relative: str | None = None
        promoted_final = False
        try:
            data = self._json_object(operation.get("data_json"))
            descriptor = self._resolve_descriptor(
                data.get("descriptor_id"),
                data.get("provider"),
                data.get("mc_version"),
                data.get("build"),
                data.get("artifact_kind"),
            )
            self.root.mkdir(parents=True, exist_ok=True)
            parts_root = self.root / ".parts"
            parts_root.mkdir(exist_ok=True)
            if parts_root.is_symlink():
                raise ServerArtifactError(
                    "SERVER_ARTIFACT_PATH_UNSAFE", "Artifact temporary directory is unsafe."
                )
            part = parts_root / f"{op_id}.part"
            if part.exists() or part.is_symlink():
                part.unlink()
            size, digest, checksums = self._download_with_retries(
                op_id, descriptor, part, cancellation
            )
            relative = self._final_relative_path(descriptor, digest)
            final = self._contained_path(self.root, relative)
            if final is None:
                raise ServerArtifactError(
                    "SERVER_ARTIFACT_PATH_UNSAFE", "Resolved artifact destination is unsafe."
                )
            final.parent.mkdir(parents=True, exist_ok=True)
            if final.parent.is_symlink():
                raise ServerArtifactError(
                    "SERVER_ARTIFACT_PATH_UNSAFE", "Artifact destination is a symlink."
                )
            self._operations.persist_download_promotion(
                op_id, relative_path=relative, size_bytes=size, sha256=digest
            )
            if final.exists():
                if not final.is_file() or final.stat().st_size != size or self._sha256_file(final) != digest:
                    raise ServerArtifactError(
                        "SERVER_ARTIFACT_PATH_UNSAFE", "Artifact destination already contains different bytes."
                    )
                part.unlink(missing_ok=True)
            else:
                os.replace(part, final)
                promoted_final = True
            artifact_id = self._publish_artifact(
                descriptor, relative, size, digest, checksums
            )
            promoted_final = False
            if part.exists():
                part.unlink(missing_ok=True)
            self._operations.transition(
                op_id,
                OperationStatus.COMPLETED,
                checkpoint={"stage": "completed", "progress_pct": 100},
                data={
                    "server_artifact_id": artifact_id,
                    "size_bytes": size,
                    "sha256": digest,
                },
            )
        except Exception as exc:
            if part is not None:
                part.unlink(missing_ok=True)
            if promoted_final and final is not None:
                referenced = (
                    self._store.reader().execute(
                        "SELECT 1 FROM server_artifacts WHERE relative_path = ?",
                        (relative,),
                    ).fetchone()
                    if relative is not None
                    else None
                )
                if referenced is None and final.is_file() and not final.is_symlink():
                    final.unlink(missing_ok=True)
            current = self._operations.get(op_id)
            if current is not None and current["status"] not in {
                OperationStatus.COMPLETED.value,
                OperationStatus.FAILED.value,
                OperationStatus.CANCELLED.value,
                OperationStatus.TIMED_OUT.value,
            }:
                code = (
                    exc.code
                    if isinstance(exc, ServerArtifactError)
                    else "SERVER_ARTIFACT_DOWNLOAD_FAILED"
                )
                try:
                    self._operations.transition(
                        op_id, OperationStatus.FAILED, error_code=code, message=str(exc)
                    )
                except OperationStateError:
                    _logger.exception("Could not fail server artifact download %s", op_id)
            if not isinstance(exc, ServerArtifactError):
                _logger.exception("Server artifact download failed: %s", op_id)
        finally:
            self._operations.unregister_cancellation(op_id, cancellation)

    def _download_with_retries(
        self,
        op_id: str,
        descriptor: ArtifactDescriptor,
        part: Path,
        cancellation: threading.Event,
    ) -> tuple[int, str, dict[str, str]]:
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                return self._download_once(op_id, descriptor, part, cancellation)
            except Exception as exc:
                last_error = exc
                part.unlink(missing_ok=True)
                if isinstance(exc, ServerArtifactError) and exc.code == "OP_CANCELLED":
                    raise
                if attempt < 3:
                    time.sleep(attempt)
        if last_error is None:
            raise ServerArtifactError("SERVER_ARTIFACT_DOWNLOAD_FAILED", "Download did not run.")
        if isinstance(last_error, ServerArtifactError):
            raise last_error
        raise ServerArtifactError(
            "SERVER_ARTIFACT_DOWNLOAD_FAILED", f"Download failed after three attempts: {last_error}"
        ) from last_error

    def _download_once(
        self,
        op_id: str,
        descriptor: ArtifactDescriptor,
        part: Path,
        cancellation: threading.Event,
    ) -> tuple[int, str, dict[str, str]]:
        expected = descriptor.advertised_size_bytes
        self._check_free_space(expected or 0)
        hashes = {"sha256": hashlib.sha256()}
        for algorithm, value in (descriptor.upstream_checksums or {}).items():
            try:
                hashes[algorithm.lower()] = hashlib.new(algorithm.lower())
            except ValueError as exc:
                raise ServerArtifactError(
                    "SERVER_ARTIFACT_CHECKSUM_UNSUPPORTED",
                    f"Provider checksum algorithm is unsupported: {algorithm}.",
                ) from exc
            if not re.fullmatch(r"[a-fA-F0-9]+", value):
                raise ServerArtifactError(
                    "SERVER_ARTIFACT_CHECKSUM_INVALID", "Provider checksum metadata is invalid."
                )
        total = 0
        last_persisted_pct = -1
        last_persisted_at = time.monotonic()
        self.root.mkdir(parents=True, exist_ok=True)
        with self._http.open(descriptor.source_url) as response, part.open("xb") as output:
            while True:
                if cancellation.is_set():
                    raise ServerArtifactError("OP_CANCELLED", "Download was cancelled.")
                chunk = response.read(_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_ARTIFACT_BYTES or (
                    expected is not None and total > expected
                ):
                    raise ServerArtifactError(
                        "SERVER_ARTIFACT_TOO_LARGE", "Downloaded artifact exceeds its size limit."
                    )
                self._check_free_space(len(chunk))
                output.write(chunk)
                for digest in hashes.values():
                    digest.update(chunk)
                progress_pct = (
                    min(99, int(total * 100 / expected)) if expected else 0
                )
                checkpoint = {
                    "stage": "downloading",
                    "progress_pct": progress_pct,
                    "bytes_received": total,
                    "bytes_expected": expected,
                }
                try:
                    self._operations.update_progress_in_memory(
                        op_id, progress_pct=progress_pct, step_name="downloading"
                    )
                except OperationStateError as exc:
                    if cancellation.is_set():
                        raise ServerArtifactError(
                            "OP_CANCELLED", "Download was cancelled."
                        ) from exc
                    raise
                now = time.monotonic()
                if (
                    progress_pct >= last_persisted_pct + 5
                    or now - last_persisted_at >= 5
                ):
                    self._operations.transition(
                        op_id, OperationStatus.RUNNING, checkpoint=checkpoint
                    )
                    last_persisted_pct = progress_pct
                    last_persisted_at = now
        if cancellation.is_set():
            raise ServerArtifactError("OP_CANCELLED", "Download was cancelled.")
        if total == 0:
            raise ServerArtifactError("SERVER_ARTIFACT_EMPTY", "Provider returned an empty artifact.")
        if expected is not None and total != expected:
            raise ServerArtifactError(
                "SERVER_ARTIFACT_SIZE_MISMATCH", "Downloaded size does not match provider metadata."
            )
        checksums = {name: digest.hexdigest() for name, digest in hashes.items()}
        for algorithm, expected_digest in (descriptor.upstream_checksums or {}).items():
            actual = checksums[algorithm.lower()]
            if actual.lower() != expected_digest.lower():
                raise ServerArtifactError(
                    "SERVER_ARTIFACT_CHECKSUM_MISMATCH",
                    f"Downloaded artifact does not match upstream {algorithm} checksum.",
                )
        return total, checksums["sha256"], checksums

    def _check_free_space(self, incoming_bytes: int) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(self.root).free
        if free - incoming_bytes < _MIN_FREE_BYTES:
            raise ServerArtifactError(
                "STORAGE_GUARD_TRIPPED",
                "Insufficient free space to preserve the 10 GB artifact reserve.",
            )

    def _publish_artifact(
        self,
        descriptor: ArtifactDescriptor,
        relative: str,
        size: int,
        digest: str,
        checksums: dict[str, str],
    ) -> str:
        identity = {
            "provider": descriptor.provider,
            "mc_version": descriptor.mc_version,
            "build": descriptor.build,
            "artifact_kind": descriptor.artifact_kind,
            "sha256": digest,
        }
        artifact_id = "sa_" + hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        now = int(self._clock.now())
        connection = self._store.writer()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT relative_path, sha256 FROM server_artifacts WHERE server_artifact_id = ?",
                (artifact_id,),
            ).fetchone()
            if existing is not None:
                if existing["relative_path"] != relative or existing["sha256"] != digest:
                    raise ServerArtifactError(
                        "SERVER_ARTIFACT_IDENTITY_CONFLICT",
                        "Existing artifact identity is inconsistent.",
                    )
            else:
                connection.execute(
                    """
                    INSERT INTO server_artifacts (
                        server_artifact_id, provider, mc_version, build, artifact_kind,
                        source_url, relative_path, size_bytes, sha256, upstream_checksums,
                        verified_at, downloaded_at, status, deleted_at, deleted_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'available', NULL, NULL, ?)
                    """,
                    (
                        artifact_id,
                        descriptor.provider,
                        descriptor.mc_version,
                        descriptor.build,
                        descriptor.artifact_kind,
                        descriptor.source_url,
                        relative,
                        size,
                        digest,
                        json.dumps(
                            {
                                key: value
                                for key, value in checksums.items()
                                if key != "sha256"
                            }
                        ),
                        now,
                        now,
                        now,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        return artifact_id

    def _resolve_descriptor(
        self, descriptor_id: Any, provider: Any, mc_version: Any, build: Any, kind: Any
    ) -> ArtifactDescriptor:
        if (
            not isinstance(provider, str)
            or provider not in self._providers
            or not isinstance(mc_version, str)
            or not isinstance(build, str)
            or not isinstance(kind, str)
            or kind not in _ARTIFACT_KINDS
        ):
            raise ServerArtifactError("VALIDATION_ERROR", "Artifact descriptor is invalid.", status=400)
        try:
            descriptor = self._providers[provider].resolve(
                mc_version=mc_version, build=build, artifact_kind=kind
            )
        except ArtifactProviderError as exc:
            raise ServerArtifactError(
                "SERVER_ARTIFACT_PROVIDER_FAILED", str(exc), status=502
            ) from exc
        if descriptor is None or descriptor.descriptor_id != descriptor_id:
            raise ServerArtifactError(
                "SERVER_ARTIFACT_DESCRIPTOR_STALE",
                "Artifact descriptor is no longer available; refresh discovery.",
            )
        validate_provider_url(descriptor.source_url)
        return descriptor

    def _run_migration(self, operation: dict[str, Any]) -> None:
        op_id = operation["op_id"]
        try:
            result = self._migrate_legacy_manifest(op_id)
            self._operations.transition(op_id, OperationStatus.COMPLETED, data=result)
        except Exception as exc:
            self._mark_migration_failed(op_id, str(exc))
            current = self._operations.get(op_id)
            if current is not None and current["status"] not in {
                OperationStatus.COMPLETED.value,
                OperationStatus.FAILED.value,
                OperationStatus.CANCELLED.value,
                OperationStatus.TIMED_OUT.value,
            }:
                self._operations.transition(
                    op_id,
                    OperationStatus.FAILED,
                    error_code="SERVER_ARTIFACT_MIGRATION_FAILED",
                    message=str(exc),
                )
            _logger.exception("Server artifact migration failed: %s", op_id)

    def _migrate_legacy_manifest(self, op_id: str) -> dict[str, Any]:
        source_root = self.legacy_root.resolve()
        manifest_path = source_root / "manifest.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise ServerArtifactError(
                "SERVER_ARTIFACT_MIGRATION_SOURCE_MISSING",
                "Legacy server artifact manifest was not found.",
            )
        raw = manifest_path.read_bytes()
        manifest_sha = hashlib.sha256(raw).hexdigest()
        backup_dir = source_root / ".migration-backups"
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / f"{op_id}-manifest.json"
        if backup_path.exists():
            raise ServerArtifactError(
                "SERVER_ARTIFACT_PATH_UNSAFE", "Migration backup already exists."
            )
        backup_path.write_bytes(raw)
        source_kind = (
            "configured_artifact_root"
            if source_root == self.root
            else "legacy_app_data"
        )
        now = int(self._clock.now())
        connection = self._store.writer()
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """
                INSERT INTO server_artifact_migration_runs (
                    operation_id, source_root_kind, source_manifest_sha256,
                    backup_relative_path, staging_relative_path, outcome,
                    unresolved_count, orphan_count, rollback_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, NULL, 'running', 0, 0, 'not_needed', ?, ?)
                """,
                (
                    op_id,
                    source_kind,
                    manifest_sha,
                    backup_path.relative_to(source_root).as_posix(),
                    now,
                    now,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ServerArtifactError(
                "SERVER_ARTIFACT_MIGRATION_MANIFEST_INVALID",
                "Legacy server artifact manifest is invalid JSON.",
            ) from exc
        entries = document.get("files") if isinstance(document, dict) else None
        if not isinstance(entries, dict):
            raise ServerArtifactError(
                "SERVER_ARTIFACT_MIGRATION_MANIFEST_INVALID",
                "Legacy manifest must contain a files object.",
            )
        import_rows: list[dict[str, Any]] = []
        records: list[dict[str, Any]] = []
        imported_paths: set[str] = set()
        for index, (key, metadata) in enumerate(entries.items()):
            record, artifact = self._migrate_entry(source_root, key, metadata, index, op_id)
            records.append(record)
            if artifact is not None:
                import_rows.append(artifact)
                imported_paths.add(artifact["source_relative_path"])
        orphan_index = 0
        for candidate in sorted(source_root.rglob("*.jar")):
            if candidate.is_symlink() or not candidate.is_file():
                continue
            relative = candidate.relative_to(source_root).as_posix()
            if relative in imported_paths or ".parts/" in relative or ".migration-backups/" in relative:
                continue
            records.append(
                {
                    "entry_kind": "orphan_file",
                    "source_index": orphan_index,
                    "source_name": self._safe_name(candidate.name),
                    "relative_path": relative,
                    "outcome": "orphan",
                    "reason_code": "UNREFERENCED_ARCHIVE_FILE",
                    "candidate_count": 1,
                    "size_bytes": candidate.stat().st_size,
                    "sha256": self._sha256_file(candidate),
                    "server_artifact_id": None,
                }
            )
            orphan_index += 1
        self._publish_migration(op_id, import_rows, records, manifest_sha)
        unresolved = sum(record["outcome"] == "unresolved" for record in records)
        orphan_count = sum(record["outcome"] == "orphan" for record in records)
        connection = self._store.writer()
        connection.execute(
            """
            UPDATE server_artifact_migration_runs
            SET outcome = 'succeeded', unresolved_count = ?, orphan_count = ?,
                updated_at = ?
            WHERE operation_id = ?
            """,
            (unresolved, orphan_count, int(self._clock.now()), op_id),
        )
        connection.commit()
        return {
            "operation_id": op_id,
            "outcome": "succeeded",
            "unresolved_count": unresolved,
            "orphan_count": orphan_count,
            "imported_count": len(import_rows),
        }

    def _migrate_entry(
        self, source_root: Path, key: Any, metadata: Any, index: int, op_id: str
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        raw_path = Path(str(key))
        source_name = self._safe_name(raw_path.name)
        def unresolved(reason: str, candidate_count: int = 0) -> tuple[dict[str, Any], None]:
            return (
                {
                    "entry_kind": "manifest_entry",
                    "source_index": index,
                    "source_name": source_name,
                    "relative_path": None,
                    "outcome": "unresolved",
                    "reason_code": reason,
                    "candidate_count": candidate_count,
                    "size_bytes": metadata.get("size") if isinstance(metadata, dict) else None,
                    "sha256": metadata.get("sha256") if isinstance(metadata, dict) else None,
                    "server_artifact_id": None,
                },
                None,
            )
        if not isinstance(metadata, dict):
            return unresolved("INVALID_METADATA")
        provider = metadata.get("provider")
        version = metadata.get("minecraft_version")
        checksum = metadata.get("sha256")
        size = metadata.get("size")
        upstream = {}
        if metadata.get("expected_sha1"):
            upstream["sha1"] = str(metadata["expected_sha1"]).lower()
        if (
            not isinstance(provider, str)
            or provider not in self._providers
            or not isinstance(version, str)
            or not version
        ):
            return unresolved("INVALID_PROVIDER_OR_VERSION")
        if not isinstance(checksum, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", checksum):
            return unresolved("MISSING_OR_INVALID_SHA256")
        if type(size) is not int or size <= 0:
            return unresolved("MISSING_OR_INVALID_SIZE")
        try:
            source_url = str(metadata.get("url") or "")
            validate_provider_url(source_url)
        except (ArtifactProviderError, ValueError):
            return unresolved("INVALID_SOURCE_URL")
        candidates = []
        for path in source_root.rglob(source_name):
            if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".jar":
                continue
            try:
                path.resolve().relative_to(source_root)
            except ValueError:
                continue
            if path.stat().st_size == size and self._sha256_file(path).lower() == checksum.lower():
                candidates.append(path)
        if len(candidates) != 1:
            return unresolved(
                "NO_MATCHING_CANDIDATE" if not candidates else "AMBIGUOUS_CANDIDATES",
                len(candidates),
            )
        candidate = candidates[0]
        artifact_kind = self._legacy_kind(provider, metadata)
        if artifact_kind is None:
            return unresolved("UNKNOWN_ARTIFACT_KIND", 1)
        build = self._legacy_build(provider, metadata, version)
        try:
            descriptor = self._providers[provider].resolve(
                mc_version=version, build=build, artifact_kind=artifact_kind
            )
        except Exception:
            descriptor = None
        if descriptor is not None:
            source_url = descriptor.source_url
            upstream.update(descriptor.upstream_checksums or {})
        relative = candidate.relative_to(source_root).as_posix()
        if source_root != self.root:
            destination_relative = self._final_relative_path_for_hash(
                provider, version, build, artifact_kind, checksum
            )
            destination = self._contained_path(self.root, destination_relative)
            if destination is None:
                return unresolved("UNSAFE_DESTINATION", 1)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if destination.is_symlink() or destination.stat().st_size != size or self._sha256_file(destination) != checksum:
                    return unresolved("DESTINATION_CONFLICT", 1)
            else:
                part = destination.with_name(destination.name + f".{op_id}.part")
                shutil.copyfile(candidate, part)
                if part.stat().st_size != size or self._sha256_file(part) != checksum:
                    part.unlink(missing_ok=True)
                    return unresolved("COPY_HASH_MISMATCH", 1)
                os.replace(part, destination)
            relative = destination_relative
        artifact = {
            "provider": provider,
            "mc_version": version,
            "build": build,
            "artifact_kind": artifact_kind,
            "source_url": source_url,
            "relative_path": relative,
            "size_bytes": size,
            "sha256": checksum.lower(),
            "upstream_checksums": upstream,
            "source_relative_path": candidate.relative_to(source_root).as_posix(),
            "server_artifact_id": self._artifact_id(
                provider, version, build, artifact_kind, checksum.lower()
            ),
        }
        return (
            {
                "entry_kind": "manifest_entry",
                "source_index": index,
                "source_name": source_name,
                "relative_path": candidate.relative_to(source_root).as_posix(),
                "outcome": "imported",
                "reason_code": None,
                "candidate_count": 1,
                "size_bytes": size,
                "sha256": checksum.lower(),
                "server_artifact_id": artifact["server_artifact_id"],
            },
            artifact,
        )

    def _publish_migration(
        self,
        op_id: str,
        artifacts: list[dict[str, Any]],
        entries: list[dict[str, Any]],
        manifest_sha: str,
    ) -> None:
        connection = self._store.writer()
        now = int(self._clock.now())
        try:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                "SELECT source_manifest_sha256 FROM server_artifact_migration_runs WHERE operation_id = ?",
                (op_id,),
            ).fetchone()
            if run is None or run["source_manifest_sha256"] != manifest_sha:
                raise ServerArtifactError(
                    "SERVER_ARTIFACT_MIGRATION_FAILED", "Migration record does not match its manifest."
                )
            for artifact in artifacts:
                descriptor = artifact
                connection.execute(
                    """
                    INSERT OR IGNORE INTO server_artifacts (
                        server_artifact_id, provider, mc_version, build, artifact_kind,
                        source_url, relative_path, size_bytes, sha256, upstream_checksums,
                        verified_at, downloaded_at, status, deleted_at, deleted_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'available', NULL, NULL, ?)
                    """,
                    (
                        descriptor["server_artifact_id"],
                        descriptor["provider"],
                        descriptor["mc_version"],
                        descriptor["build"],
                        descriptor["artifact_kind"],
                        descriptor["source_url"],
                        descriptor["relative_path"],
                        descriptor["size_bytes"],
                        descriptor["sha256"],
                        json.dumps(descriptor["upstream_checksums"]),
                        now,
                        now,
                        now,
                    ),
                )
            for entry in entries:
                connection.execute(
                    """
                    INSERT INTO server_artifact_migration_entries (
                        entry_id, operation_id, entry_kind, source_index, source_name,
                        relative_path, outcome, reason_code, candidate_count, size_bytes,
                        sha256, server_artifact_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"sae_{uuid.uuid4().hex}",
                        op_id,
                        entry["entry_kind"],
                        entry["source_index"],
                        entry["source_name"],
                        entry["relative_path"],
                        entry["outcome"],
                        entry["reason_code"],
                        entry["candidate_count"],
                        entry["size_bytes"],
                        entry["sha256"],
                        entry["server_artifact_id"],
                        now,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def _reconcile_download(self, operation: dict[str, Any]) -> None:
        data = self._json_object(operation.get("data_json"))
        promotion = data.get("promotion")
        op_id = operation["op_id"]
        if isinstance(promotion, dict):
            relative = promotion.get("relative_path")
            path = self._contained_path(self.root, relative) if isinstance(relative, str) else None
            if (
                path is not None
                and path.is_file()
                and not path.is_symlink()
                and path.stat().st_size == promotion.get("size_bytes")
                and self._sha256_file(path) == promotion.get("sha256")
            ):
                try:
                    artifact_id = self._artifact_id(
                        data["provider"],
                        data["mc_version"],
                        data["build"],
                        data["artifact_kind"],
                        promotion["sha256"],
                    )
                    existing = self._store.reader().execute(
                        """
                        SELECT relative_path, size_bytes, sha256
                        FROM server_artifacts
                        WHERE server_artifact_id = ? AND status = 'available'
                          AND deleted_at IS NULL
                        """,
                        (artifact_id,),
                    ).fetchone()
                    if (
                        existing is None
                        or existing["relative_path"] != relative
                        or existing["size_bytes"] != promotion["size_bytes"]
                        or existing["sha256"] != promotion["sha256"]
                    ):
                        descriptor = self._resolve_descriptor(
                            data.get("descriptor_id"),
                            data.get("provider"),
                            data.get("mc_version"),
                            data.get("build"),
                            data.get("artifact_kind"),
                        )
                        artifact_id = self._publish_artifact(
                            descriptor,
                            relative,
                            promotion["size_bytes"],
                            promotion["sha256"],
                            descriptor.upstream_checksums or {},
                        )
                    self._operations.transition(
                        op_id,
                        OperationStatus.COMPLETED,
                        data={
                            "server_artifact_id": artifact_id,
                            "size_bytes": promotion["size_bytes"],
                            "sha256": promotion["sha256"],
                        },
                    )
                    return
                except Exception:
                    _logger.exception("Could not complete recovered artifact download %s", op_id)
            if path is not None and path.is_file() and not path.is_symlink():
                path.unlink(missing_ok=True)
        part = self.root / ".parts" / f"{op_id}.part"
        if part.is_file() and not part.is_symlink():
            part.unlink(missing_ok=True)
        self._operations.transition(
            op_id,
            OperationStatus.FAILED,
            error_code="SERVER_ARTIFACT_DOWNLOAD_INTERRUPTED",
            message="Download was interrupted by manager restart.",
        )

    def _reconcile_migration(self, operation: dict[str, Any]) -> None:
        op_id = operation["op_id"]
        run = self._store.reader().execute(
            "SELECT outcome FROM server_artifact_migration_runs WHERE operation_id = ?",
            (op_id,),
        ).fetchone()
        if run is not None and run["outcome"] == "succeeded":
            self._operations.transition(op_id, OperationStatus.COMPLETED, data={"outcome": "succeeded"})
            return
        self._mark_migration_failed(op_id, "Manager restarted before migration publication completed.")
        self._operations.transition(
            op_id,
            OperationStatus.FAILED,
            error_code="SERVER_ARTIFACT_MIGRATION_INTERRUPTED",
            message="Migration was interrupted by manager restart.",
        )

    def _mark_migration_failed(self, op_id: str, message: str) -> None:
        connection = self._store.writer()
        connection.execute(
            """
            UPDATE server_artifact_migration_runs
            SET outcome = 'failed', rollback_status = 'completed', updated_at = ?
            WHERE operation_id = ? AND outcome = 'running'
            """,
            (int(self._clock.now()), op_id),
        )
        connection.commit()
        if message:
            _logger.warning("Server artifact migration %s: %s", op_id, message)

    @staticmethod
    def _legacy_kind(provider: str, metadata: dict[str, Any]) -> str | None:
        kind = metadata.get("artifact_type")
        if kind == "server-launcher":
            return "launcher"
        if kind == "installer":
            return "installer"
        if kind == "runnable_server":
            return "runnable_server"
        if provider in _RUNNABLE_PROVIDERS:
            return "runnable_server"
        if provider == "fabric":
            return "launcher"
        if provider in {"forge", "neoforge"}:
            return "installer"
        return None

    @staticmethod
    def _legacy_build(provider: str, metadata: dict[str, Any], version: str) -> str:
        if provider == "vanilla":
            return str(metadata.get("version_type") or "release")
        for name in ("build", "forge_version", "neoforge_version"):
            if metadata.get(name) is not None:
                value = str(metadata[name])
                if name == "forge_version" and value.startswith(version + "-"):
                    return value[len(version) + 1 :]
                return value
        if provider == "fabric":
            return f"{metadata.get('loader_version', '')}|{metadata.get('installer_version', '')}"
        return "latest"

    @staticmethod
    def _artifact_id(
        provider: str, mc_version: str, build: str, kind: str, digest: str
    ) -> str:
        identity = {
            "provider": provider,
            "mc_version": mc_version,
            "build": build,
            "artifact_kind": kind,
            "sha256": digest,
        }
        return "sa_" + hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    @classmethod
    def _final_relative_path(cls, descriptor: ArtifactDescriptor, digest: str) -> str:
        return cls._final_relative_path_for_hash(
            descriptor.provider,
            descriptor.mc_version,
            descriptor.build,
            descriptor.artifact_kind,
            digest,
        )

    @classmethod
    def _final_relative_path_for_hash(
        cls, provider: str, version: str, build: str, kind: str, digest: str
    ) -> str:
        safe_version = cls._safe_name(version)
        safe_build = cls._safe_name(build)
        filename = f"{safe_build}-{kind}-{digest[:16]}.jar"
        return Path(provider, safe_version, filename).as_posix()

    @staticmethod
    def _safe_name(value: str) -> str:
        return _SAFE_SEGMENT.sub("_", value)[:120] or "unknown"

    @staticmethod
    def _contained_path(root: Path, relative: str) -> Path | None:
        candidate_relative = Path(relative)
        if candidate_relative.is_absolute() or any(
            part in {"", ".", ".."} for part in candidate_relative.parts
        ):
            return None
        resolved_root = root.resolve()
        current = resolved_root
        try:
            for part in candidate_relative.parts:
                current = current / part
                if current.is_symlink():
                    return None
            resolved = (resolved_root / candidate_relative).resolve()
            resolved.relative_to(resolved_root)
        except (OSError, RuntimeError, ValueError):
            return None
        return resolved

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(_CHUNK_BYTES), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _public_artifact(row: dict[str, Any]) -> dict[str, Any]:
        checksums = row.get("upstream_checksums")
        if isinstance(checksums, str):
            try:
                checksums = json.loads(checksums)
            except json.JSONDecodeError:
                checksums = {}
        return {
            key: row.get(key)
            for key in (
                "server_artifact_id",
                "provider",
                "mc_version",
                "build",
                "artifact_kind",
                "size_bytes",
                "sha256",
                "verified_at",
                "downloaded_at",
                "status",
            )
        } | {"upstream_checksums": checksums or {}}

    @staticmethod
    def _json_object(value: Any) -> dict[str, Any]:
        try:
            data = json.loads(value or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _encode_cursor(provider: str, scope: str, offset: int) -> str:
        raw = f"{provider}\n{scope}\n{offset}".encode()
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str, provider: str, scope: str) -> int:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            parsed_provider, parsed_scope, raw_offset = base64.urlsafe_b64decode(
                padded.encode("ascii")
            ).decode("utf-8").split("\n")
            offset = int(raw_offset)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ServerArtifactError(
                "VALIDATION_ERROR", "Pagination cursor is invalid.", status=400
            ) from exc
        if parsed_provider != provider or parsed_scope != scope or offset < 0:
            raise ServerArtifactError(
                "VALIDATION_ERROR", "Pagination cursor does not match the query.", status=400
            )
        return offset

    @staticmethod
    def _encode_migration_cursor(op_id: str, offset: int) -> str:
        raw = f"{op_id}\n{offset}".encode()
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_migration_cursor(cursor: str, op_id: str) -> int:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            parsed_op_id, raw_offset = base64.urlsafe_b64decode(
                padded.encode("ascii")
            ).decode("utf-8").split("\n")
            offset = int(raw_offset)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ServerArtifactError("VALIDATION_ERROR", "Pagination cursor is invalid.", status=400) from exc
        if parsed_op_id != op_id or offset < 0:
            raise ServerArtifactError("VALIDATION_ERROR", "Pagination cursor does not match the query.", status=400)
        return offset
