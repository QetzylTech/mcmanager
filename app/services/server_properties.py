"""Guarded, versioned server.properties edits."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.domain.value_objects import (
    ActorType,
    ConfigEditEntity,
    OperationStatus,
    OperationType,
    ServerType,
)
from app.ports.clock import Clock
from app.ports.minecraft import (
    CORE_MANAGER_PROPERTIES,
    PropertyValidation,
    allowed_keys,
    parse_properties,
    validate_properties,
    validate_properties_file,
)
from app.ports.persistence import PersistencePort
from app.services.configuration import ConfigurationConflictError, ConfigurationService
from app.services.operations import OperationInput, OperationService
from app.services.world_paths import resolve_world_directory


class ManagedPropertyError(ValueError):
    """Raised when an edit attempts to change a manager-owned property."""

    def __init__(self, keys: list[str]) -> None:
        self.keys = keys
        super().__init__(
            f"manager-owned properties cannot be edited here: {', '.join(keys)}"
        )


class ServerPropertiesValidationError(ValueError):
    """A submitted property set failed its capability-schema validation."""

    def __init__(self, validation: PropertyValidation) -> None:
        self.validation = validation
        super().__init__("server.properties failed schema validation")


class ServerPropertiesService:
    """Read and atomically update a world's server.properties file."""

    _write_lock = threading.RLock()

    def __init__(
        self,
        store: PersistencePort,
        clock: Clock,
        configuration: ConfigurationService,
        operations: OperationService,
    ) -> None:
        self._store = store
        self._clock = clock
        self._configuration = configuration
        self._operations = operations

    def read(self, world_id: str) -> dict[str, Any]:
        world = self._world(world_id)
        properties = self._read_file(self._properties_path(world))
        validation = validate_properties_file(
            properties=properties,
            server_type=ServerType(world["server_type"]),
            mc_version=world["mc_version"],
        )
        return {
            "properties": properties,
            "allowed_keys": allowed_keys(
                ServerType(world["server_type"]), world["mc_version"]
            ),
            "version": self._version(world_id),
            "validation": {
                "valid": validation.valid,
                "errors": validation.errors,
                "deprecated_hints": validation.deprecated_hints,
            },
        }

    def update(
        self,
        *,
        world_id: str,
        expected_version: int,
        properties: dict[str, object],
        actor_user_id: str,
        idempotency_key: str,
    ) -> tuple[dict[str, Any], dict[str, Any], bool]:
        world = self._world(world_id)
        if not properties:
            raise ValueError("at least one property is required")
        managed = sorted(set(properties).intersection(CORE_MANAGER_PROPERTIES))
        if managed:
            raise ManagedPropertyError(managed)
        validation = validate_properties(
            properties=properties,
            server_type=ServerType(world["server_type"]),
            mc_version=world["mc_version"],
        )
        if not validation.valid:
            raise ServerPropertiesValidationError(validation)

        if self._version(world_id) != expected_version:
            raise ConfigurationConflictError("CONFIG_VERSION_CONFLICT")

        operation, replayed = self._operations.create_with_replay(
            OperationInput(
                op_type=OperationType.CONFIG_EDIT,
                actor_type=ActorType.USER,
                actor_user_id=actor_user_id,
                world_id=world_id,
                idempotency_key=idempotency_key,
                data={
                    "entity": ConfigEditEntity.SERVER_PROPERTIES.value,
                    "row_id": world_id,
                    "expected_version": expected_version,
                    "before": {},
                    "after": properties,
                },
            ),
            initial_status=OperationStatus.QUEUED,
            allow_world_conflict=True,
        )
        if replayed:
            return self.read(world_id), operation, True

        operation = self._operations.transition(
            operation["op_id"], OperationStatus.RUNNING
        )
        try:
            result, before = self._apply(
                world=world,
                expected_version=expected_version,
                edits=properties,
                actor_user_id=actor_user_id,
            )
            operation = self._operations.transition(
                operation["op_id"],
                OperationStatus.COMPLETED,
                data={
                    "entity": ConfigEditEntity.SERVER_PROPERTIES.value,
                    "row_id": world_id,
                    "expected_version": expected_version,
                    "before": before,
                    "after": properties,
                    "version": result["version"],
                },
            )
            return result, operation, False
        except Exception as exc:
            self._operations.transition(
                operation["op_id"],
                OperationStatus.FAILED,
                error_code=(
                    "CONFIG_VERSION_CONFLICT"
                    if isinstance(exc, ConfigurationConflictError)
                    else "CONFIG_EDIT_FAILED"
                ),
                message=str(exc),
                data={
                    "entity": ConfigEditEntity.SERVER_PROPERTIES.value,
                    "row_id": world_id,
                    "expected_version": expected_version,
                    "after": properties,
                },
            )
            raise

    def _apply(
        self,
        *,
        world: dict[str, Any],
        expected_version: int,
        edits: dict[str, object],
        actor_user_id: str,
    ) -> tuple[dict[str, Any], dict[str, str | None]]:
        world_id = world["world_id"]
        path = self._properties_path(world)
        connection = self._store.writer()
        with self._write_lock:
            connection.execute("BEGIN IMMEDIATE")
            original: bytes | None = None
            replaced = False
            try:
                current_world = connection.execute(
                    "SELECT 1 FROM world_instances "
                    "WHERE world_id = ? AND deleted_at IS NULL",
                    (world_id,),
                ).fetchone()
                if current_world is None:
                    raise KeyError(world_id)
                version = connection.execute(
                    "SELECT version FROM server_properties_versions WHERE world_id = ?",
                    (world_id,),
                ).fetchone()
                current_version = int(version["version"]) if version else 0
                if current_version != expected_version:
                    raise ConfigurationConflictError("CONFIG_VERSION_CONFLICT")

                if path.is_symlink():
                    raise ValueError("server.properties cannot be a symbolic link")
                if path.exists():
                    original = path.read_bytes()
                current = parse_properties(
                    original.decode("utf-8", errors="replace") if original else ""
                )
                before = {key: current.get(key) for key in edits}
                updated = {
                    **current,
                    **{
                        key: _property_string(value)
                        for key, value in edits.items()
                    },
                }
                _atomic_write_properties(path, updated)
                replaced = True
                now = int(self._clock.now())
                if version is None:
                    connection.execute(
                        """
                        INSERT INTO server_properties_versions
                            (world_id, version, updated_at, updated_by)
                        VALUES (?, 1, ?, ?)
                        """,
                        (world_id, now, actor_user_id),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE server_properties_versions
                        SET version = version + 1, updated_at = ?, updated_by = ?
                        WHERE world_id = ? AND version = ?
                        """,
                        (now, actor_user_id, world_id, current_version),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                if replaced:
                    _restore_file(path, original)
                raise

        result = self.read(world_id)
        return result, before

    def _world(self, world_id: str) -> dict[str, Any]:
        row = self._store.reader().execute(
            "SELECT * FROM world_instances WHERE world_id = ? AND deleted_at IS NULL",
            (world_id,),
        ).fetchone()
        if row is None:
            raise KeyError(world_id)
        return dict(row)

    def _version(self, world_id: str) -> int:
        row = self._store.reader().execute(
            "SELECT version FROM server_properties_versions WHERE world_id = ?",
            (world_id,),
        ).fetchone()
        return int(row["version"]) if row is not None else 0

    def _properties_path(self, world: dict[str, Any]) -> Path:
        try:
            settings = self._configuration.resolve_effective(world["world_id"])
        except KeyError:
            settings = {"minecraft_root_path": "worlds"}
        root = settings["minecraft_root_path"] or "worlds"
        return resolve_world_directory(world, str(root)) / "server.properties"

    @staticmethod
    def _read_file(path: Path) -> dict[str, str]:
        if path.is_symlink():
            raise ValueError("server.properties cannot be a symbolic link")
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return {}
        return parse_properties(text)


def _property_string(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int)):
        return str(value)
    raise ValueError("property values must be strings, integers, or booleans")


def _escape_property(value: str, *, key: bool = False) -> str:
    escaped: list[str] = []
    for character in value:
        if character == "\\":
            escaped.append("\\\\")
        elif character == "\t":
            escaped.append("\\t")
        elif character == "\n":
            escaped.append("\\n")
        elif character == "\r":
            escaped.append("\\r")
        elif character == "\f":
            escaped.append("\\f")
        elif key and character in " =:#!":
            escaped.append("\\" + character)
        else:
            escaped.append(character)
    return "".join(escaped)


def _atomic_write_properties(path: Path, properties: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        lines = [
            f"{_escape_property(key, key=True)}={_escape_property(value)}"
            for key, value in properties.items()
        ]
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _restore_file(path: Path, original: bytes | None) -> None:
    if original is None:
        path.unlink(missing_ok=True)
        return
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.rollback")
    try:
        temporary.write_bytes(original)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
