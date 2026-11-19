"""Guarded, versioned server.properties API."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from flask import Blueprint, current_app, g, request

from app.domain.value_objects import OperationType
from app.services.configuration import ConfigurationConflictError
from app.services.server_properties import (
    ManagedPropertyError,
    ServerPropertiesValidationError,
)
from app.web.errors import error, ok

server_properties_bp = Blueprint("api_server_properties", __name__, url_prefix="/api")


def _container() -> Any:
    return current_app.extensions["mcmanager_container"]


def _operation_data(operation: dict[str, Any]) -> dict[str, Any]:
    result = dict(operation)
    if result.get("data_json"):
        try:
            result["data"] = json.loads(result["data_json"])
        except (TypeError, json.JSONDecodeError):
            result["data"] = None
    return result


def _response(
    properties: dict[str, Any],
    operation: dict[str, Any],
    *,
    idempotency_key: str,
) -> Any:
    operation_data = _operation_data(operation)
    return ok(
        {**properties, "operation": operation_data},
        meta={
            "op_id": operation_data["op_id"],
            "idempotency_key": idempotency_key,
        },
    )


@server_properties_bp.get("/worlds/<world_id>/server-properties")
def get_server_properties(world_id: str) -> Any:
    try:
        properties = _container().server_properties.read(world_id)
    except KeyError:
        return error("WORLD_NOT_FOUND", "World not found.")
    except OSError:
        return error("INTERNAL_ERROR", "Could not read server.properties.", status=500)
    except ValueError:
        return error(
            "FILE_PATH_UNAUTHORIZED",
            "server.properties cannot be read through a symbolic link.",
        )
    return ok(properties)


@server_properties_bp.post("/worlds/<world_id>/server-properties")
def update_server_properties(world_id: str) -> Any:
    idempotency_key = request.headers.get("Idempotency-Key")
    if idempotency_key is None:
        idempotency_key = uuid4().hex
    else:
        idempotency_key = idempotency_key.strip()
        if not idempotency_key:
            return error("VALIDATION_ERROR", "Idempotency-Key must not be empty.")

    operations = _container().operations
    existing = operations.get_by_idempotency_key(
        OperationType.CONFIG_EDIT, idempotency_key
    )
    if existing is not None:
        try:
            properties = _container().server_properties.read(world_id)
        except KeyError:
            return error("WORLD_NOT_FOUND", "World not found.")
        return _response(properties, existing, idempotency_key=idempotency_key)

    body = request.get_json(silent=True)
    if (
        not isinstance(body, dict)
        or set(body) != {"version", "properties"}
        or type(body.get("version")) is not int
        or body["version"] < 0
        or not isinstance(body.get("properties"), dict)
        or any(not isinstance(key, str) or not key for key in body["properties"])
    ):
        return error(
            "VALIDATION_ERROR",
            "A non-negative version and properties object are required.",
        )
    try:
        result, operation, _ = _container().server_properties.update(
            world_id=world_id,
            expected_version=body["version"],
            properties=body["properties"],
            actor_user_id=g.current_user_id,
            idempotency_key=idempotency_key,
        )
    except KeyError:
        return error("WORLD_NOT_FOUND", "World not found.")
    except ConfigurationConflictError:
        return error(
            "CONFIG_VERSION_CONFLICT",
            "Configuration changed; reload and retry.",
            status=409,
        )
    except ManagedPropertyError as exc:
        return error(
            "VALIDATION_ERROR",
            str(exc),
            details={"managed_keys": exc.keys},
        )
    except ServerPropertiesValidationError as exc:
        codes = {entry.rsplit(": ", 1)[-1] for entry in exc.validation.errors}
        code = (
            "CONFIG_INVALID_KEY"
            if "CONFIG_INVALID_KEY" in codes
            else "CONFIG_INVALID_VALUE"
        )
        return error(code, str(exc), details={"errors": exc.validation.errors})
    except ValueError as exc:
        return error("VALIDATION_ERROR", str(exc))
    except OSError:
        return error("INTERNAL_ERROR", "Could not update server.properties.", status=500)

    return _response(result, operation, idempotency_key=idempotency_key)
