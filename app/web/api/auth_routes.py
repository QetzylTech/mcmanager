"""Authentication and current-session endpoints."""

from __future__ import annotations

from typing import Any

from flask import Blueprint, Response, current_app, g, request

from app.bootstrap import Container
from app.services.auth import (
    AuthenticationError,
    InvalidCredentialsError,
    SessionError,
    UserDisabledError,
    UserLockedError,
)
from app.web.errors import error, ok
from app.web.middleware import session_csrf_token

auth_bp = Blueprint("api_auth", __name__, url_prefix="/api")


def _container() -> Container:
    return current_app.extensions["mcmanager_container"]


def _request_device(body: dict[str, Any]) -> tuple[str | None, str | None]:
    device_id = body.get("device_id")
    device_name = body.get("device_name")
    return (
        device_id if isinstance(device_id, str) and device_id else None,
        device_name if isinstance(device_name, str) and device_name else None,
    )


def _set_session_cookies(response: Response, *, token: str) -> None:
    secure = request.is_secure
    response.set_cookie(
        "mcmanager_session",
        token,
        httponly=True,
        secure=secure,
        samesite="Lax",
        path="/",
    )
    response.set_cookie(
        "csrf_token",
        session_csrf_token(token),
        httponly=False,
        secure=secure,
        samesite="Lax",
        path="/",
    )


def _session_identity(user_id: str) -> dict[str, Any]:
    row = (
        _container()
        .store.reader()
        .execute(
            "SELECT u.username, u.display_name, GROUP_CONCAT(r.name) AS roles "
            "FROM users u LEFT JOIN role_assignments ra "
            "ON ra.user_id = u.user_id AND ra.deleted_at IS NULL "
            "LEFT JOIN roles r ON r.role_id = ra.role_id AND r.deleted_at IS NULL "
            "WHERE u.user_id = ? AND u.deleted_at IS NULL GROUP BY u.user_id",
            (user_id,),
        )
        .fetchone()
    )
    if row is None:
        raise SessionError("session user no longer exists")
    return {
        "user_id": user_id,
        "username": row["username"],
        "display_name": row["display_name"],
        "roles": (row["roles"] or "").split(",") if row["roles"] else [],
    }


@auth_bp.post("/auth/login")
def login() -> Any:
    body = request.get_json(silent=True) or {}
    username = body.get("username")
    password = body.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        return error("VALIDATION_ERROR", "Username and password are required.", status=400)

    device_id, device_name = _request_device(body)
    container = _container()
    try:
        session = container.auth.authenticate(
            username=username,
            password=password,
            device_id=device_id,
            device_name=device_name,
            ip=request.remote_addr or "",
        )
    except UserLockedError:
        return error("AUTH_LOCKED", "Account is temporarily locked.", status=429)
    except UserDisabledError:
        return error("AUTH_DISABLED", "Account is disabled.", status=403)
    except InvalidCredentialsError:
        return error("AUTH_INVALID_CREDENTIALS", "Invalid username or password.", status=401)

    response = ok({"session": _session_identity(session.user_id)}, status=201)
    _set_session_cookies(response[0], token=session.token)
    return response


@auth_bp.post("/auth/logout")
def logout() -> Any:
    container = _container()
    container.auth.revoke_session_id(g.current_session.session_id_hash)
    response = ok({"logged_out": True})
    response[0].delete_cookie(
        "mcmanager_session",
        path="/",
        secure=request.is_secure,
        httponly=True,
        samesite="Lax",
    )
    response[0].delete_cookie("csrf_token", path="/", secure=request.is_secure, samesite="Lax")
    return response


@auth_bp.post("/auth/step-up")
def step_up() -> Any:
    body = request.get_json(silent=True) or {}
    password = body.get("password")
    if not isinstance(password, str) or not password:
        return error("VALIDATION_ERROR", "Password is required.", status=400)

    device_id, device_name = _request_device(body)
    try:
        session = _container().auth.confirm_step_up(
            raw_token=g.current_session.token,
            password=password,
            device_id=device_id,
            device_name=device_name,
            ip=request.remote_addr or "",
        )
    except InvalidCredentialsError:
        return error("AUTH_INVALID_CREDENTIALS", "Invalid password.", status=401)
    except AuthenticationError:
        return error("AUTH_SESSION_INVALID", "A valid session is required.", status=401)

    response = ok(
        {
            "session": _session_identity(session.user_id),
            "step_up_expires_at": session.step_up_confirmed_at + 600,
        }
    )
    _set_session_cookies(response[0], token=session.token)
    return response


@auth_bp.get("/session")
def current_session() -> Any:
    session = g.current_session
    confirmed_at = session.step_up_confirmed_at
    expires_at = confirmed_at + 600 if confirmed_at is not None else None
    if expires_at is not None and expires_at < _container().clock.now():
        expires_at = None
    return ok(
        {
            **_session_identity(session.user_id),
            "expires_at": session.expires_at,
            "step_up_expires_at": expires_at,
        }
    )
