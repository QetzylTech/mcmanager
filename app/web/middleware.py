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
        or path == "/api/cleanup/execute"
        or (
            method == "DELETE"
            and path.startswith("/api/backups/")
            and path.count("/") == 3
        )
        or (
            method == "POST"
            and path.startswith("/api/worlds/")
            and (path.endswith("/restores") or path.endswith("/restores/rollback"))
        )
        or (
            method == "DELETE"
            and path.startswith("/api/worlds/")
            and len(segments) == 3
        )
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
            and isinstance(request.get_json(silent=True), dict)
            and "username" in request.get_json(silent=True)
        )
    )


def _requires_admin() -> bool:
    path: str = request.path
    method: str = request.method
    segments = path.strip("/").split("/")
    protected_world_files = (
        path.startswith("/api/worlds/")
        and len(segments) >= 4
        and segments[3] == "files"
    )
    protected_world_logs = (
        path.startswith("/api/worlds/")
        and len(segments) >= 5
        and segments[3] == "logs"
    )
    admin_catalog_reads = method == "GET" and path in {
        "/api/backups",
        "/api/cleanup/runs",
        "/api/sync/records",
        "/api/sync/targets",
    }
    return (
        path == "/api/diagnostics"
        or path == "/api/settings"
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
        or (
            method == "DELETE"
            and path.startswith("/api/backups/")
            and path.count("/") == 3
        )
        or (
            method in _STATE_CHANGING_METHODS
            and (
                path.startswith("/api/schedules")
                or path.startswith("/api/templates")
                or path.startswith("/api/java-runtimes")
                or path in {
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
        path == "/api/setup" and request.method == "POST"
    ) or path.startswith(("/api/users", "/api/roles", "/api/permissions", "/api/devices")) or (
        path in {"/api/manager/update", "/api/manager/rollback"}
    ) or (
        request.method == "DELETE"
        and path.startswith("/api/backups/")
        and request.args.get("force", "").lower() in {"true", "1"}
    )


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
                active_users = container.store.reader().execute(
                    "SELECT count(*) FROM users WHERE deleted_at IS NULL"
                ).fetchone()[0]
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
        elif _requires_admin():
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
