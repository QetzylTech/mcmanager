"""HTTP session, CSRF, step-up, and response-header middleware."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
from typing import Any

from flask import Flask, Response, g, request

from app.services.auth import SessionError, StepUpRequiredError
from app.web.errors import error

_STATE_CHANGING_METHODS = frozenset({"POST", "PATCH", "DELETE"})
_ADMIN_ROLES = frozenset({"Admin", "Superadmin"})


def session_csrf_token(session_token: str) -> str:
    """Derive a CSRF token whose validity is limited to one opaque session."""
    return hmac.new(
        session_token.encode("utf-8"),
        b"mcmanager-csrf-v1",
        hashlib.sha256,
    ).hexdigest()


def _is_public_request() -> bool:
    path: str = request.path
    method: str = request.method
    return (
        path == "/"
        or path.startswith("/pages/")
        or path.startswith("/static/")
        or path == "/api/health"
        or path == "/api/auth/login"
        or (path == "/api/setup" and method == "GET")
        or method == "OPTIONS"
    )


def _is_loopback_request() -> bool:
    try:
        return ipaddress.ip_address(request.remote_addr or "").is_loopback
    except ValueError:
        return False


def _requires_step_up() -> bool:
    method: str = request.method
    if method not in _STATE_CHANGING_METHODS:
        return False
    path: str = request.path
    segments = path.strip("/").split("/")
    return (
        path.endswith("/stop")
        or path.endswith("/kill")
        or path.endswith("/eula/accept")
        or path.endswith("/runtime-config")
        or path.endswith("/cleanup-policy")
        or path == "/api/supervisor/tick"
        or path == "/api/cleanup/policy"
        or path == "/api/cleanup/execute"
        or (method == "DELETE" and path.startswith("/api/backups/") and path.count("/") == 3)
        or (
            method == "POST"
            and path.startswith("/api/worlds/")
            and (path.endswith("/restores") or path.endswith("/restores/rollback"))
        )
        or (method == "DELETE" and path.startswith("/api/worlds/") and len(segments) == 3)
        or (
            method == "DELETE"
            and path.startswith("/api/worlds/")
            and len(segments) == 4
            and segments[3] == "files"
        )
        or path == "/api/manager/restore"
        or path
        in {
            "/api/manager/restart",
            "/api/manager/update",
            "/api/manager/rollback",
        }
        or (
            method == "PATCH"
            and path.startswith("/api/users/")
            and isinstance(payload := request.get_json(silent=True), dict)
            and "username" in payload
        )
    )


def _requires_admin() -> bool:
    path: str = request.path
    method: str = request.method
    segments = path.strip("/").split("/")
    protected_world_files = (
        path.startswith("/api/worlds/") and len(segments) >= 4 and segments[3] == "files"
    )
    protected_world_logs = (
        path.startswith("/api/worlds/") and len(segments) >= 5 and segments[3] == "logs"
    )
    admin_catalog_reads = method == "GET" and path in {
        "/api/backups",
        "/api/cleanup/runs",
        "/api/sync/records",
        "/api/sync/targets",
    }
    return (
        path == "/api/documentation"
        or path.startswith("/api/documentation/")
        or path == "/api/pages"
        or path.startswith("/api/pages/")
        or path == "/api/manager/logs"
        or path.startswith("/api/manager/logs/")
        or path == "/api/diagnostics"
        or path == "/api/cleanup/policy"
        or path == "/api/settings"
        or (path.startswith("/api/worlds/") and path.endswith("/cleanup-policy"))
        or path.endswith("/server-properties")
        or (
            method == "POST"
            and path.startswith("/api/operations/")
            and len(segments) == 4
            and segments[3] == "cancel"
        )
        or (path.startswith("/api/worlds/") and path.endswith("/settings"))
        or path.startswith("/api/supervisor/")
        or path.endswith("/stop")
        or path.endswith("/kill")
        or path.endswith("/eula/accept")
        or path.endswith("/runtime-config")
        or protected_world_files
        or protected_world_logs
        or admin_catalog_reads
        or path.endswith("/delete-preview")
        or path.endswith("/cleanup-preview")
        or path == "/api/cleanup/dry-run"
        or path == "/api/cleanup/execute"
        or path == "/api/sync/retry"
        or (method == "DELETE" and path.startswith("/api/backups/") and path.count("/") == 3)
        or (
            method in _STATE_CHANGING_METHODS
            and (
                path == "/api/worlds"
                or path.startswith("/api/schedules")
                or path.startswith("/api/templates")
                or path.startswith("/api/java-runtimes")
                or path.startswith("/api/sync/targets")
                or path
                in {
                    "/api/manager/backup",
                    "/api/manager/restore",
                    "/api/manager/restart",
                    "/api/manager/update",
                    "/api/manager/rollback",
                }
            )
        )
        or method in _STATE_CHANGING_METHODS
        and path.startswith("/api/worlds/")
        and not path.endswith("/start")
    )


def _requires_superadmin() -> bool:
    path: str = request.path
    return (
        (path == "/api/setup" and request.method == "POST")
        or path.startswith(("/api/users", "/api/roles", "/api/permissions", "/api/devices"))
        or (path in {"/api/manager/update", "/api/manager/rollback"})
        or (
            request.method == "DELETE"
            and path.startswith("/api/backups/")
            and request.args.get("force", "").lower() in {"true", "1"}
        )
    )


def _permission_requirement(container: Any) -> tuple[str, str | None] | None:
    """Return the exact permission category and scope required by this route."""
    path = request.path
    method = request.method
    args = request.view_args or {}
    world_id = args.get("world_id")

    def related_world(table: str, column: str, value: str | None) -> str | None:
        if not isinstance(value, str) or not value:
            return None
        row = (
            container.store.reader()
            .execute(
                f"SELECT world_id FROM {table} WHERE {column} = ?",
                (value,),
            )
            .fetchone()
        )
        return row["world_id"] if row is not None else None

    if path == "/api/worlds":
        if method == "GET":
            return "world.view", None
        if method == "POST":
            return "world.create", None

    if path.startswith("/api/worlds/") and world_id is not None:
        suffix = path[len(f"/api/worlds/{world_id}") :].rstrip("/")
        if suffix in {"", "/"}:
            if method == "GET":
                return "world.view", world_id
            if method == "PATCH":
                return "world.edit", world_id
            if method == "DELETE":
                return "world.delete", world_id
            return None
        if suffix == "/server-properties":
            if method == "GET":
                return "world.properties.view", world_id
            if method == "POST":
                return "world.properties.edit", world_id
            return None
        if suffix == "/start" and method == "POST":
            return "world.start", world_id
        if suffix == "/stop" and method == "POST":
            return "world.stop", world_id
        if suffix == "/kill" and method == "POST":
            return "world.kill", world_id
        if suffix == "/delete-preview" and method == "POST":
            return "world.delete", world_id
        if suffix == "/runtime-config":
            return ("world.runtime.view" if method == "GET" else "world.runtime.edit", world_id)
        if suffix == "/settings":
            return ("world.settings.view" if method == "GET" else "world.settings.edit", world_id)
        if suffix == "/cleanup-policy":
            return ("world.cleanup" if method == "GET" else "world.cleanup.manage", world_id)
        if suffix == "/eula":
            return ("world.view", world_id) if method == "GET" else None
        if suffix == "/eula/accept" and method == "POST":
            return "world.eula.accept", world_id
        if suffix == "/files":
            return ("world.files.view" if method == "GET" else "world.files.edit", world_id)
        if suffix.startswith("/files/"):
            return ("world.files.view" if method == "GET" else "world.files.edit", world_id)
        if suffix == "/logs" or suffix.startswith("/logs/"):
            return "world.logs.view", world_id
        if suffix == "/operations" and method == "GET":
            return "world.view", world_id
        if suffix == "/backups":
            return ("world.backup.view" if method == "GET" else "world.backup.create", world_id)
        if suffix == "/restores":
            return ("world.restore.view" if method == "GET" else "world.restore", world_id)
        if suffix in {"/restores/rollback", "/cleanup-preview"}:
            return ("world.restore" if suffix.endswith("rollback") else "world.cleanup", world_id)

    if path.startswith("/stream/worlds/") and world_id is not None:
        suffix = path[len(f"/stream/worlds/{world_id}") :].rstrip("/")
        if suffix == "/events":
            return "world.view", world_id
        if suffix == "/logs":
            return "world.logs.view", world_id
    if path == "/stream/events":
        return "world.view", None
    if path == "/stream/restore_logs":
        return "world.restore.view", request.args.get("world_id")
    if path == "/stream/metrics":
        return "system.view", None

    if path == "/api/operations" and method == "GET":
        return "world.view", request.args.get("world_id")
    if path == "/api/operations" and method in _STATE_CHANGING_METHODS:
        return None
    if path.startswith("/api/operations/"):
        operation_world = related_world("operations", "op_id", args.get("op_id"))
        if path.endswith("/cancel"):
            return "world.operation.cancel", operation_world
        if method == "GET":
            return "world.view", operation_world

    if path == "/api/backups":
        if method == "GET":
            requested_world = request.args.get("world_id")
            return "backup.view", requested_world if requested_world != "null" else None
        return None
    if path.startswith("/api/backups/"):
        artifact_id = args.get("artifact_id")
        artifact_world = related_world("backup_artifacts", "artifact_id", artifact_id)
        if path.endswith("/sync"):
            return "backup.sync.view", artifact_world
        if method == "DELETE":
            return "backup.delete", artifact_world
        if method == "GET":
            return "backup.view", artifact_world

    if path.startswith("/api/cleanup/"):
        if path == "/api/cleanup/policy":
            return ("cleanup.view" if method == "GET" else "cleanup.manage", None)
        if path in {"/api/cleanup/dry-run", "/api/cleanup/execute"}:
            body = request.get_json(silent=True)
            requested_world = body.get("world_id") if isinstance(body, dict) else None
            if not isinstance(requested_world, str):
                requested_world = None
            if requested_world is None and path.endswith("/execute") and isinstance(body, dict):
                requested_world = related_world(
                    "operations", "op_id", body.get("dry_run_operation_id")
                )
            return "cleanup.manage", requested_world
        if path == "/api/cleanup/runs" and method == "GET":
            return "cleanup.view", None
    if path in {"/api/sync/records", "/api/sync/targets"} and method == "GET":
        return "sync.view", request.args.get("world_id")
    if path == "/api/sync/retry" and method == "POST":
        body = request.get_json(silent=True)
        world_id = None
        if isinstance(body, dict):
            artifact_id = body.get("artifact_id")
            world_id = related_world("backup_artifacts", "artifact_id", artifact_id)
        return "sync.retry", world_id
    if path == "/api/sync/targets" and method == "POST":
        body = request.get_json(silent=True)
        requested_world = body.get("world_id") if isinstance(body, dict) else None
        if (
            isinstance(body, dict)
            and body.get("scope") == "world"
            and isinstance(requested_world, str)
        ):
            return "sync.manage", requested_world
        return "sync.manage", None
    if path.startswith("/api/sync/targets/"):
        target_id = args.get("target_id")
        if method in {"PATCH", "DELETE"}:
            body = request.get_json(silent=True)
            if (
                method == "PATCH"
                and isinstance(body, dict)
                and ("scope" in body or "world_id" in body)
            ):
                return "sync.manage", None
            target_world = related_world("sync_targets", "sync_target_id", target_id)
            return "sync.manage", target_world

    if path.startswith("/api/schedules"):
        if path == "/api/schedules" and method == "GET":
            return "schedule.view", request.args.get("world_id")
        schedule_id = args.get("schedule_id")
        schedule_world = related_world("schedules", "schedule_id", schedule_id)
        return ("schedule.view" if method == "GET" else "schedule.edit", schedule_world)
    if path.startswith("/api/missed-runs"):
        if method == "GET":
            return "schedule.view", None
        return "schedule.edit", None

    if path == "/api/settings":
        return ("settings.view" if method == "GET" else "settings.edit", None)
    if path.startswith("/api/templates"):
        return ("template.view" if method == "GET" else "template.edit", None)
    if path.startswith("/api/java-runtimes"):
        return ("runtime.view" if method == "GET" else "runtime.edit", None)
    if path.startswith("/api/manager/"):
        suffix = path.rsplit("/", 1)[-1]
        if suffix in {"backup", "restore", "restart"}:
            return f"manager.{suffix}", None
    if path in {"/api/diagnostics", "/api/system/stats"}:
        return "system.view", None
    return None


def _has_permission(
    container: Any,
    *,
    user_id: str,
    action_category: str,
    world_id: str | None,
) -> bool:
    scope_clause = (
        "p.world_id IS NULL" if world_id is None else "(p.world_id IS NULL OR p.world_id = ?)"
    )
    row = (
        container.store.reader()
        .execute(
            "SELECT 1 FROM permissions p "
            "WHERE p.deleted_at IS NULL AND p.action_category = ? AND "
            + scope_clause
            + " AND (p.user_id = ? OR EXISTS ("
            "SELECT 1 FROM role_assignments ra JOIN roles r ON r.role_id = ra.role_id "
            "WHERE ra.user_id = ? AND ra.role_id = p.role_id "
            "AND ra.deleted_at IS NULL AND r.deleted_at IS NULL)) LIMIT 1",
            [action_category, *([world_id] if world_id is not None else []), user_id, user_id],
        )
        .fetchone()
    )
    return row is not None


def register_middleware(app: Flask) -> None:
    """Install request authentication and safe defaults without owning DI."""

    @app.before_request
    def authenticate_and_validate_csrf() -> Any:
        if not request.is_secure and not _is_loopback_request():
            return error(
                "HTTPS_REQUIRED",
                "HTTPS is required for non-loopback connections.",
                status=403,
            )
        if request.path == "/api/setup" and request.method == "POST":
            container = app.extensions.get("mcmanager_container")
            if container is not None:
                active_users = (
                    container.store.reader()
                    .execute("SELECT count(*) FROM users WHERE deleted_at IS NULL")
                    .fetchone()[0]
                )
                if active_users == 0:
                    cookie_token = request.cookies.get("csrf_token", "")
                    header_token = request.headers.get("X-CSRF-Token", "")
                    if (
                        cookie_token
                        and header_token
                        and hmac.compare_digest(cookie_token, header_token)
                    ):
                        return None
                    return error(
                        "CSRF_INVALID",
                        "CSRF token validation failed.",
                        status=403,
                    )
        if _is_public_request():
            if request.path == "/api/auth/login" and request.method in _STATE_CHANGING_METHODS:
                cookie_token = request.cookies.get("csrf_token", "")
                header_token = request.headers.get("X-CSRF-Token", "")
                if (
                    not cookie_token
                    or not header_token
                    or not hmac.compare_digest(cookie_token, header_token)
                ):
                    return error("CSRF_INVALID", "CSRF token validation failed.", status=403)
            return None

        container = app.extensions.get("mcmanager_container")
        if container is None:
            return error("AUTH_SESSION_INVALID", "A valid session is required.", status=401)

        raw_token = request.cookies.get("mcmanager_session")
        if not raw_token:
            return error("AUTH_SESSION_INVALID", "A valid session is required.", status=401)
        try:
            session = container.auth.validate_session(raw_token, ip=request.remote_addr or "")
        except SessionError:
            return error("AUTH_SESSION_INVALID", "A valid session is required.", status=401)

        g.current_session = session
        g.current_user_id = session.user_id

        if request.method in _STATE_CHANGING_METHODS:
            cookie_token = request.cookies.get("csrf_token", "")
            header_token = request.headers.get("X-CSRF-Token", "")
            if (
                not cookie_token
                or not header_token
                or not hmac.compare_digest(cookie_token, header_token)
            ):
                return error("CSRF_INVALID", "CSRF token validation failed.", status=403)

            expected_token = session_csrf_token(session.token)
            if not hmac.compare_digest(cookie_token, expected_token):
                return error("CSRF_INVALID", "CSRF token validation failed.", status=403)

        if _requires_superadmin():
            role = (
                container.store.reader()
                .execute(
                    "SELECT 1 FROM role_assignments ra "
                    "JOIN roles r ON r.role_id = ra.role_id "
                    "WHERE ra.user_id = ? AND ra.deleted_at IS NULL "
                    "AND r.deleted_at IS NULL AND r.name = ? LIMIT 1",
                    (session.user_id, "Superadmin"),
                )
                .fetchone()
            )
            if role is None:
                return error("AUTH_FORBIDDEN", "A Superadmin role is required.", status=403)
        else:
            admin_role = (
                container.store.reader()
                .execute(
                    "SELECT 1 FROM role_assignments ra "
                    "JOIN roles r ON r.role_id = ra.role_id "
                    "WHERE ra.user_id = ? AND ra.deleted_at IS NULL "
                    "AND r.deleted_at IS NULL AND r.name IN (?, ?) LIMIT 1",
                    (session.user_id, *_ADMIN_ROLES),
                )
                .fetchone()
            )
            requirement = _permission_requirement(container)
            route_permission_granted = False
            if requirement is not None and admin_role is None:
                route_permission_granted = _has_permission(
                    container,
                    user_id=session.user_id,
                    action_category=requirement[0],
                    world_id=requirement[1],
                )
            if requirement is not None and admin_role is None and not route_permission_granted:
                return error(
                    "AUTH_FORBIDDEN",
                    f"The {requirement[0]} permission is required.",
                    status=403,
                )
        if (
            not _requires_superadmin()
            and _requires_admin()
            and admin_role is None
            and not route_permission_granted
        ):
            role = (
                container.store.reader()
                .execute(
                    "SELECT 1 FROM role_assignments ra "
                    "JOIN roles r ON r.role_id = ra.role_id "
                    "WHERE ra.user_id = ? AND ra.deleted_at IS NULL "
                    "AND r.deleted_at IS NULL AND r.name IN (?, ?) LIMIT 1",
                    (session.user_id, *_ADMIN_ROLES),
                )
                .fetchone()
            )
            if role is None:
                return error("AUTH_FORBIDDEN", "An administrator role is required.", status=403)

        if _requires_step_up():
            try:
                container.auth.require_step_up(session)
            except StepUpRequiredError:
                return error("STEP_UP_REQUIRED", "A fresh step-up is required.", status=403)
        return None

    @app.after_request
    def add_security_headers(response: Response) -> Response:
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'",
        )
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-XSS-Protection", "0")
        if request.path.startswith(("/api/", "/stream/")):
            response.headers.setdefault("Cache-Control", "no-store")

        response_sets_csrf = any(
            value.startswith("csrf_token=") for value in response.headers.getlist("Set-Cookie")
        )
        cookie_context_is_secure = request.is_secure or _is_loopback_request()
        if cookie_context_is_secure and not response_sets_csrf and hasattr(g, "current_session"):
            csrf_token = session_csrf_token(g.current_session.token)
            if request.cookies.get("csrf_token") != csrf_token:
                response.set_cookie(
                    "csrf_token",
                    csrf_token,
                    secure=request.is_secure,
                    httponly=False,
                    samesite="Lax",
                    path="/",
                )
        elif (
            cookie_context_is_secure
            and not response_sets_csrf
            and not request.cookies.get("csrf_token")
        ):
            response.set_cookie(
                "csrf_token",
                secrets.token_urlsafe(32),
                secure=request.is_secure,
                httponly=False,
                samesite="Lax",
                path="/",
            )
        return response
