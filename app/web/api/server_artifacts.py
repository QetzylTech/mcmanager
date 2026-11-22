"""Server artifact catalog and acquisition routes."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from flask import Blueprint, current_app, g, request

from app.domain.value_objects import OperationStatus
from app.services.server_artifacts import ServerArtifactError
from app.web.errors import error, ok

server_artifacts_bp = Blueprint(
    "api_server_artifacts", __name__, url_prefix="/api"
)


def _container() -> Any:
    return current_app.extensions["mcmanager_container"]


def _key() -> str | None:
    value = request.headers.get("Idempotency-Key")
    if value is None:
        return uuid4().hex
    value = value.strip()
    return value or None


def _body() -> dict[str, Any] | None:
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else None


def _page_size(default: int = 50, maximum: int = 50) -> int:
    raw = request.args.get("limit")
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ServerArtifactError(
            "VALIDATION_ERROR", "limit must be an integer.", status=400
        ) from exc


def _operation_response(operation: dict[str, Any], *, replayed: bool) -> Any:
    payload = dict(operation)
    if payload.get("data_json"):
        try:
            payload["data"] = json.loads(payload["data_json"])
        except (TypeError, json.JSONDecodeError):
            payload["data"] = None
    terminal = payload.get("status") in {
        OperationStatus.COMPLETED.value,
        OperationStatus.FAILED.value,
        OperationStatus.CANCELLED.value,
        OperationStatus.TIMED_OUT.value,
    }
    return ok(
        {"operation": payload},
        status=200 if replayed or terminal else 202,
        meta={"op_id": payload["op_id"]},
    )


def _handle_error(exc: ServerArtifactError) -> Any:
    return error(exc.code, str(exc), status=exc.status)


@server_artifacts_bp.get("/server-artifacts/providers")
def list_providers() -> Any:
    try:
        return ok({"providers": _container().server_artifacts.provider_catalog()})
    except ServerArtifactError as exc:
        return _handle_error(exc)


@server_artifacts_bp.get("/server-artifacts/discover")
def discover_artifacts() -> Any:
    try:
        items, pagination = _container().server_artifacts.discover(
            provider=request.args.get("provider", ""),
            scope=request.args.get("scope", "latest"),
            limit=_page_size(),
            cursor=request.args.get("cursor"),
        )
        return ok({"items": items}, meta={"pagination": pagination})
    except ServerArtifactError as exc:
        return _handle_error(exc)


@server_artifacts_bp.get("/server-artifacts")
def list_artifacts() -> Any:
    try:
        limit = _page_size(default=50, maximum=100)
        try:
            offset = int(request.args.get("offset", "0"))
        except ValueError as exc:
            raise ServerArtifactError(
                "VALIDATION_ERROR", "offset must be an integer.", status=400
            ) from exc
        items, pagination = _container().server_artifacts.list_catalog(
            provider=request.args.get("provider"),
            mc_version=request.args.get("mc_version"),
            limit=limit,
            offset=offset,
        )
        return ok({"items": items}, meta={"pagination": pagination})
    except ServerArtifactError as exc:
        return _handle_error(exc)


@server_artifacts_bp.get("/server-artifacts/<server_artifact_id>")
def get_artifact(server_artifact_id: str) -> Any:
    try:
        return ok(
            {
                "artifact": _container().server_artifacts.get_artifact(
                    server_artifact_id
                )
            }
        )
    except ServerArtifactError as exc:
        return _handle_error(exc)


@server_artifacts_bp.post("/server-artifacts/downloads")
def request_download() -> Any:
    key = _key()
    if key is None:
        return error("VALIDATION_ERROR", "Idempotency-Key must not be empty.")
    body = _body()
    expected = {
        "descriptor_id",
        "provider",
        "mc_version",
        "build",
        "artifact_kind",
    }
    if (
        body is None
        or not expected.issubset(body)
        or set(body).difference(expected | {"force"})
        or ("force" in body and type(body["force"]) is not bool)
    ):
        return error("VALIDATION_ERROR", "Download request fields are invalid.")
    try:
        artifact, operation, replayed = _container().server_artifacts.queue_download(
            descriptor_id=body["descriptor_id"],
            provider=body["provider"],
            mc_version=body["mc_version"],
            build=body["build"],
            artifact_kind=body["artifact_kind"],
            force=body.get("force", False),
            actor_user_id=g.current_user_id,
            idempotency_key=key,
        )
        if artifact is not None:
            return ok({"artifact": artifact}, status=200)
        if operation is None:
            return error("INTERNAL_ERROR", "Download operation was not created.")
        return _operation_response(operation, replayed=replayed)
    except ServerArtifactError as exc:
        return _handle_error(exc)


@server_artifacts_bp.post("/server-artifact-migrations")
def request_migration() -> Any:
    key = _key()
    if key is None:
        return error("VALIDATION_ERROR", "Idempotency-Key must not be empty.")
    if _body() not in ({}, None):
        return error("VALIDATION_ERROR", "Migration request body must be empty.")
    try:
        operation, replayed = _container().server_artifacts.request_migration(
            actor_user_id=g.current_user_id,
            idempotency_key=key,
        )
        return _operation_response(operation, replayed=replayed)
    except ServerArtifactError as exc:
        return _handle_error(exc)


@server_artifacts_bp.get("/server-artifact-migrations/<op_id>")
def migration_detail(op_id: str) -> Any:
    try:
        run, entries, pagination = _container().server_artifacts.migration_detail(
            op_id,
            limit=_page_size(),
            cursor=request.args.get("cursor"),
        )
        return ok(
            {"run": run, "entries": entries},
            meta={"pagination": pagination},
        )
    except ServerArtifactError as exc:
        return _handle_error(exc)
