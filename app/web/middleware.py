"""HTTP session, CSRF, step-up, and response-header middleware."""

from __future__ import annotations

import hashlib
import hmac
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
        or method == "OPTIONS"
    )


def _requires_step_up() -> bool:
    method: str = request.method
    if method not in _STATE_CHANGING_METHODS:
        return False
    path: str = request.path
    return (
        path.endswith("/stop")
        or path.endswith("/kill")
        or path.endswith("/eula/accept")
        or path.endswith("/runtime-config")
    )


def _requires_admin() -> bool:
    path: str = request.path
    method: str = request.method
    return (
        path == "/api/diagnostics"
        or path.startswith("/api/supervisor/")
        or path.endswith("/stop")
        or path.endswith("/kill")
        or path.endswith("/eula/accept")
        or path.endswith("/runtime-config")
        or method in _STATE_CHANGING_METHODS
        and path.startswith("/api/worlds/")
        and not path.endswith("/start")
    )


def register_middleware(app: Flask) -> None:
    """Install request authentication and safe defaults without owning DI."""

    @app.before_request
    def authenticate_and_validate_csrf() -> Any:
        if request.method in _STATE_CHANGING_METHODS:
            cookie_token = request.cookies.get("csrf_token", "")
            header_token = request.headers.get("X-CSRF-Token", "")
            if (
                not cookie_token
                or not header_token
                or not hmac.compare_digest(cookie_token, header_token)
            ):
                return error("CSRF_INVALID", "CSRF token validation failed.", status=403)

        if _is_public_request():
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
            expected_token = session_csrf_token(session.token)
            if not hmac.compare_digest(cookie_token, expected_token):
                return error("CSRF_INVALID", "CSRF token validation failed.", status=403)

        if _requires_admin():
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
            "default-src 'self'; script-src 'self'; style-src 'self'",
        )
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-XSS-Protection", "0")

        response_sets_csrf = any(
            value.startswith("csrf_token=") for value in response.headers.getlist("Set-Cookie")
        )
        if not response_sets_csrf and hasattr(g, "current_session"):
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
        elif not response_sets_csrf and not request.cookies.get("csrf_token"):
            response.set_cookie(
                "csrf_token",
                secrets.token_urlsafe(32),
                secure=request.is_secure,
                httponly=False,
                samesite="Lax",
                path="/",
            )
        return response
