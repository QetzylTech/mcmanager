"""Manager setup and Superadmin identity, role, permission, and device APIs."""

from __future__ import annotations

import uuid

from argon2 import PasswordHasher
from flask import Blueprint, current_app, g, request

from app.domain.value_objects import ActorType, ConfigEditEntity
from app.ports.secrets_store import SecretType
from app.services.configuration import ConfigurationConflictError, VersionedUpdate
from app.web.errors import error, ok

administration_bp = Blueprint("api_administration", __name__, url_prefix="/api")
_PASSWORD_HASHER = PasswordHasher()


def _container():
    return current_app.extensions["mcmanager_container"]


def _body():
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else None


def _iso(value):
    if value is None:
        return None
    from datetime import UTC, datetime

    return datetime.fromtimestamp(value, tz=UTC).isoformat().replace("+00:00", "Z")


def _live_role(role_id: str) -> bool:
    return (
        _container()
        .store.reader()
        .execute("SELECT 1 FROM roles WHERE role_id = ? AND deleted_at IS NULL", (role_id,))
        .fetchone()
        is not None
    )


@administration_bp.get("/manager")
def get_manager():
    container = _container()
    row = (
        container.store.reader()
        .execute(
            "SELECT deployed_version, setup_completed, updated_at FROM manager "
            "ORDER BY created_at LIMIT 1"
        )
        .fetchone()
    )
    if row is None:
        return ok({"deployed_version": "unknown", "setup_completed": False, "state": "setup"})
    return ok(
        {
            "deployed_version": row["deployed_version"],
            "setup_completed": bool(row["setup_completed"]),
            "state": "ready" if row["setup_completed"] else "setup",
            "updated_at": _iso(row["updated_at"]),
        }
    )


@administration_bp.get("/setup")
def get_setup():
    container = _container()
    count = (
        container.store.reader()
        .execute("SELECT count(*) FROM users WHERE deleted_at IS NULL")
        .fetchone()[0]
    )
    return ok({"setup_completed": count > 0, "first_superadmin_required": count == 0})


@administration_bp.post("/setup")
def complete_setup():
    body = _body()
    if body is None or any(
        not isinstance(body.get(key), str) or not body[key].strip()
        for key in ("username", "password")
    ):
        return error("VALIDATION_ERROR", "Username and password are required.")
    container = _container()
    try:
        user_id = container.auth.provision_first_superadmin(
            username=body["username"].strip(),
            password=body["password"],
            device_id=None,
            device_name=None,
            ip=request.remote_addr or "",
        )
    except Exception as exc:
        return error("AUTH_FORBIDDEN", str(exc), status=409)
    writer = container.store.writer()
    now = int(container.clock.now())
    writer.execute(
        "INSERT INTO manager (manager_id, deployed_version, setup_completed, created_at, updated_at) "
        "VALUES ('manager', 'unknown', 1, ?, ?) "
        "ON CONFLICT(manager_id) DO UPDATE SET setup_completed = 1, updated_at = excluded.updated_at",
        (now, now),
    )
    writer.commit()
    return ok({"setup_completed": True, "user_id": user_id}, status=201)


def _unsupported_manager_action(action: str):
    # The current container has no manager lifecycle/update service to own these actions.
    return error(
        "NOT_IMPLEMENTED",
        f"Manager {action} requires the manager lifecycle service.",
        status=501,
    )


@administration_bp.post("/manager/backup")
def manager_backup():
    return _unsupported_manager_action("backup")


@administration_bp.post("/manager/restore")
def manager_restore():
    return _unsupported_manager_action("restore")


@administration_bp.post("/manager/restart")
def manager_restart():
    return _unsupported_manager_action("restart")


@administration_bp.post("/manager/update")
def manager_update():
    return _unsupported_manager_action("update")


@administration_bp.post("/manager/rollback")
def manager_rollback():
    return _unsupported_manager_action("rollback")


@administration_bp.get("/users")
def list_users():
    rows = (
        _container()
        .store.reader()
        .execute(
            "SELECT u.user_id, u.username, u.display_name, u.status, u.created_at, "
            "(SELECT max(last_activity_at) FROM client_sessions s "
            " WHERE s.user_id = u.user_id AND s.deleted_at IS NULL) AS last_activity_at, "
            "GROUP_CONCAT(r.name) AS roles FROM users u "
            "LEFT JOIN role_assignments ra ON ra.user_id = u.user_id AND ra.deleted_at IS NULL "
            "LEFT JOIN roles r ON r.role_id = ra.role_id AND r.deleted_at IS NULL "
            "WHERE u.deleted_at IS NULL GROUP BY u.user_id ORDER BY u.username"
        )
        .fetchall()
    )
    result = [dict(row) for row in rows]
    for row in result:
        row["roles"] = row["roles"].split(",") if row["roles"] else []
        row["created_at"] = _iso(row["created_at"])
        row["last_activity_at"] = _iso(row["last_activity_at"])
    return ok({"users": result})


@administration_bp.post("/users")
def create_user():
    body = _body()
    if (
        body is None
        or not isinstance(body.get("username"), str)
        or not body["username"].strip()
        or not isinstance(body.get("password"), str)
        or len(body["password"]) < 12
        or not isinstance(body.get("role_id"), str)
        or not _live_role(body["role_id"])
    ):
        return error(
            "VALIDATION_ERROR", "A username, 12-character password, and live role are required."
        )
    container = _container()
    now = int(container.clock.now())
    user_id = f"u_{uuid.uuid4().hex[:16]}"
    secret_id = container.secrets.store(
        secret_type=SecretType.USER_PASSWORD,
        associated_entity_type="user",
        associated_entity_id=user_id,
        plaintext=_PASSWORD_HASHER.hash(body["password"]),
    )
    writer = container.store.writer()
    try:
        writer.execute(
            "INSERT INTO users (user_id, username, display_name, secret_id, status, "
            "failed_login_count, locked_until, created_by, deleted_at, deleted_by, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'active', 0, NULL, ?, NULL, NULL, ?, ?)",
            (
                user_id,
                body["username"].strip(),
                body.get("display_name"),
                secret_id,
                g.current_user_id,
                now,
                now,
            ),
        )
        writer.execute(
            "INSERT INTO role_assignments (assignment_id, user_id, role_id, granted_at, "
            "granted_by, deleted_at, deleted_by) VALUES (?, ?, ?, ?, ?, NULL, NULL)",
            (f"ra_{uuid.uuid4().hex[:12]}", user_id, body["role_id"], now, g.current_user_id),
        )
        writer.commit()
    except Exception as exc:
        writer.rollback()
        return error("VALIDATION_ERROR", str(exc), status=409)
    container.audit.write(
        event_type="user_created",
        actor=container.audit.snapshot_for_user(
            user_id=g.current_user_id,
            device_id=None,
            device_name=None,
            ip=request.remote_addr,
        ),
        payload={"target_user_id": user_id, "username": body["username"].strip()},
    )
    return ok({"user_id": user_id, "username": body["username"].strip()}, status=201)


@administration_bp.patch("/users/<user_id>")
def update_user(user_id: str):
    body = _body()
    allowed = {"display_name", "status", "password", "username"}
    if body is None or not body or set(body).difference(allowed):
        return error("VALIDATION_ERROR", "Editable user fields are required.")
    container = _container()
    target = (
        container.store.reader()
        .execute("SELECT user_id FROM users WHERE user_id = ? AND deleted_at IS NULL", (user_id,))
        .fetchone()
    )
    if target is None:
        return error("NOT_FOUND", "User not found.", status=404)
    if "username" in body and (
        not isinstance(body["username"], str) or not body["username"].strip()
    ):
        return error("VALIDATION_ERROR", "username must be a non-empty string.")
    if (
        "display_name" in body
        and body["display_name"] is not None
        and not isinstance(body["display_name"], str)
    ):
        return error("VALIDATION_ERROR", "display_name must be a string or null.")
    if "status" in body and body["status"] not in {"active", "disabled"}:
        return error("VALIDATION_ERROR", "status must be active or disabled.")
    if body.get("status") == "disabled":
        is_superadmin = (
            container.store.reader()
            .execute(
                "SELECT 1 FROM role_assignments ra JOIN roles r ON r.role_id = ra.role_id "
                "WHERE ra.user_id = ? AND ra.deleted_at IS NULL AND r.deleted_at IS NULL "
                "AND r.name = 'Superadmin' LIMIT 1",
                (user_id,),
            )
            .fetchone()
        )
        if is_superadmin:
            active_superadmins = (
                container.store.reader()
                .execute(
                    "SELECT count(DISTINCT u.user_id) FROM users u "
                    "JOIN role_assignments ra ON ra.user_id = u.user_id AND ra.deleted_at IS NULL "
                    "JOIN roles r ON r.role_id = ra.role_id AND r.deleted_at IS NULL "
                    "WHERE u.deleted_at IS NULL AND u.status = 'active' AND r.name = 'Superadmin'"
                )
                .fetchone()[0]
            )
            if active_superadmins <= 1:
                return error(
                    "FORBIDDEN_LAST_SUPERADMIN",
                    "Cannot disable the last active Superadmin.",
                    status=409,
                )
    if "password" in body:
        if not isinstance(body["password"], str) or len(body["password"]) < 12:
            return error("VALIDATION_ERROR", "password must contain at least 12 characters.")
        if user_id == g.current_user_id:
            return error("VALIDATION_ERROR", "Use password change for your own account.")
        container.auth.change_password(
            user_id=user_id, new_password=body["password"], by_user_id=g.current_user_id
        )
    fields = {key: value for key, value in body.items() if key != "password"}
    if "username" in fields:
        fields["username"] = fields["username"].strip()
    if fields:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        writer = container.store.writer()
        try:
            writer.execute(
                f"UPDATE users SET {assignments}, updated_at = ? WHERE user_id = ?",
                [*fields.values(), int(container.clock.now()), user_id],
            )
            writer.commit()
        except Exception as exc:
            writer.rollback()
            return error("VALIDATION_ERROR", str(exc), status=409)
        if fields.get("status") == "disabled":
            writer.execute(
                "UPDATE client_sessions SET deleted_at = ?, deleted_by = ? "
                "WHERE user_id = ? AND deleted_at IS NULL",
                (int(container.clock.now()), g.current_user_id, user_id),
            )
            writer.commit()
    return ok({"user_id": user_id, "updated": sorted(body)})


@administration_bp.delete("/users/<user_id>")
def delete_user(user_id: str):
    container = _container()
    target = (
        container.store.reader()
        .execute("SELECT 1 FROM users WHERE user_id = ? AND deleted_at IS NULL", (user_id,))
        .fetchone()
    )
    if target is None:
        return error("NOT_FOUND", "User not found.", status=404)
    active_superadmins = (
        container.store.reader()
        .execute(
            "SELECT count(DISTINCT u.user_id) FROM users u "
            "JOIN role_assignments ra ON ra.user_id = u.user_id AND ra.deleted_at IS NULL "
            "JOIN roles r ON r.role_id = ra.role_id AND r.deleted_at IS NULL "
            "WHERE u.deleted_at IS NULL AND u.status = 'active' AND r.name = 'Superadmin'"
        )
        .fetchone()[0]
    )
    is_superadmin = (
        container.store.reader()
        .execute(
            "SELECT 1 FROM role_assignments ra JOIN roles r ON r.role_id = ra.role_id "
            "WHERE ra.user_id = ? AND ra.deleted_at IS NULL AND r.name = 'Superadmin' "
            "AND r.deleted_at IS NULL",
            (user_id,),
        )
        .fetchone()
    )
    if is_superadmin and active_superadmins <= 1:
        return error(
            "FORBIDDEN_LAST_SUPERADMIN", "Cannot delete the last active Superadmin.", status=409
        )
    now = int(container.clock.now())
    writer = container.store.writer()
    writer.execute(
        "UPDATE users SET deleted_at = ?, deleted_by = ?, updated_at = ? WHERE user_id = ?",
        (now, g.current_user_id, now, user_id),
    )
    writer.execute(
        "UPDATE role_assignments SET deleted_at = ?, deleted_by = ? "
        "WHERE user_id = ? AND deleted_at IS NULL",
        (now, g.current_user_id, user_id),
    )
    writer.execute(
        "UPDATE client_sessions SET deleted_at = ?, deleted_by = ? "
        "WHERE user_id = ? AND deleted_at IS NULL",
        (now, g.current_user_id, user_id),
    )
    writer.commit()
    return ok({"user_id": user_id, "deleted": True})


@administration_bp.get("/roles")
def list_roles():
    rows = (
        _container()
        .store.reader()
        .execute(
            "SELECT role_id, name, description, is_system_role, version, created_at, updated_at "
            "FROM roles WHERE deleted_at IS NULL ORDER BY is_system_role DESC, name"
        )
        .fetchall()
    )
    result = [dict(row) for row in rows]
    for row in result:
        row["is_system_role"] = bool(row["is_system_role"])
        row["created_at"] = _iso(row["created_at"])
        row["updated_at"] = _iso(row["updated_at"])
    return ok({"roles": result})


@administration_bp.post("/roles")
def create_role():
    body = _body()
    if body is None or not isinstance(body.get("name"), str) or not body["name"].strip():
        return error("VALIDATION_ERROR", "A role name is required.")
    container = _container()
    now = int(container.clock.now())
    role_id = f"r_{uuid.uuid4().hex[:12]}"
    try:
        container.store.writer().execute(
            "INSERT INTO roles (role_id, name, description, is_system_role, version, "
            "deleted_at, deleted_by, created_at, updated_at) "
            "VALUES (?, ?, ?, 0, 1, NULL, NULL, ?, ?)",
            (role_id, body["name"].strip(), body.get("description"), now, now),
        )
        container.store.writer().commit()
    except Exception as exc:
        return error("VALIDATION_ERROR", str(exc), status=409)
    return ok({"role_id": role_id, "name": body["name"].strip(), "version": 1}, status=201)


@administration_bp.patch("/roles/<role_id>")
def update_role(role_id: str):
    body = _body()
    if (
        body is None
        or type(body.get("version")) is not int
        or set(body).difference({"version", "name", "description"})
    ):
        return error("VALIDATION_ERROR", "A version and editable role fields are required.")
    row = (
        _container()
        .store.reader()
        .execute(
            "SELECT is_system_role FROM roles WHERE role_id = ? AND deleted_at IS NULL", (role_id,)
        )
        .fetchone()
    )
    if row is None:
        return error("NOT_FOUND", "Role not found.", status=404)
    if row["is_system_role"]:
        return error("CONFIG_VERSION_CONFLICT", "Baseline roles are immutable.", status=409)
    fields = {key: body[key] for key in ("name", "description") if key in body}
    try:
        updated, operation = _container().configuration.update_versioned_with_operation(
            VersionedUpdate(
                entity=ConfigEditEntity.ROLES,
                row_id=role_id,
                expected_version=body["version"],
                fields=fields,
                actor_type=ActorType.USER,
                actor_user_id=g.current_user_id,
            )
        )
    except ConfigurationConflictError:
        return error("CONFIG_VERSION_CONFLICT", "Role changed; reload and retry.", status=409)
    except KeyError:
        return error("NOT_FOUND", "Role not found.", status=404)
    except ValueError as exc:
        return error("VALIDATION_ERROR", str(exc))
    return ok({"role": updated, "operation": operation}, meta={"op_id": operation["op_id"]})


@administration_bp.delete("/roles/<role_id>")
def delete_role(role_id: str):
    container = _container()
    row = (
        container.store.reader()
        .execute(
            "SELECT is_system_role, version FROM roles WHERE role_id = ? AND deleted_at IS NULL",
            (role_id,),
        )
        .fetchone()
    )
    if row is None:
        return error("NOT_FOUND", "Role not found.", status=404)
    if row["is_system_role"]:
        return error("CONFIG_VERSION_CONFLICT", "Baseline roles are immutable.", status=409)
    holders = (
        container.store.reader()
        .execute(
            "SELECT 1 FROM role_assignments WHERE role_id = ? AND deleted_at IS NULL LIMIT 1",
            (role_id,),
        )
        .fetchone()
    )
    if holders:
        return error("CONFIG_VERSION_CONFLICT", "Role still has active holders.", status=409)
    try:
        _, operation = container.configuration.update_versioned_with_operation(
            VersionedUpdate(
                entity=ConfigEditEntity.ROLES,
                row_id=role_id,
                expected_version=row["version"],
                fields={"deleted_at": int(container.clock.now()), "deleted_by": g.current_user_id},
                actor_type=ActorType.USER,
                actor_user_id=g.current_user_id,
            )
        )
    except (ConfigurationConflictError, KeyError):
        return error("CONFIG_VERSION_CONFLICT", "Role changed; reload and retry.", status=409)
    return ok({"role_id": role_id, "deleted": True, "operation": operation})


@administration_bp.get("/roles/<role_id>/permissions")
def list_role_permissions(role_id: str):
    if not _live_role(role_id):
        return error("NOT_FOUND", "Role not found.", status=404)
    rows = (
        _container()
        .store.reader()
        .execute(
            "SELECT permission_id, action_category, world_id, granted_at, granted_by "
            "FROM permissions WHERE role_id = ? AND deleted_at IS NULL ORDER BY action_category",
            (role_id,),
        )
        .fetchall()
    )
    return ok({"permissions": [dict(row) for row in rows]})


@administration_bp.post("/permissions")
def grant_permission():
    body = _body()
    if body is None:
        return error("VALIDATION_ERROR", "A JSON object is required.")
    role_id, user_id = body.get("role_id"), body.get("user_id")
    category, world_id = body.get("action_category"), body.get("world_id")
    if (role_id is None) == (user_id is None) or not isinstance(category, str) or not category:
        return error(
            "VALIDATION_ERROR", "Exactly one role or user and an action category are required."
        )
    if role_id is not None and not _live_role(role_id):
        return error("NOT_FOUND", "Role not found.", status=404)
    if (
        user_id is not None
        and _container()
        .store.reader()
        .execute("SELECT 1 FROM users WHERE user_id = ? AND deleted_at IS NULL", (user_id,))
        .fetchone()
        is None
    ):
        return error("NOT_FOUND", "User not found.", status=404)
    if (
        world_id is not None
        and _container()
        .store.reader()
        .execute(
            "SELECT 1 FROM world_instances WHERE world_id = ? AND deleted_at IS NULL", (world_id,)
        )
        .fetchone()
        is None
    ):
        return error("NOT_FOUND", "World not found.", status=404)
    permission_id = f"perm_{uuid.uuid4().hex[:16]}"
    now = int(_container().clock.now())
    try:
        writer = _container().store.writer()
        writer.execute(
            "INSERT INTO permissions (permission_id, role_id, user_id, action_category, "
            "world_id, granted_at, granted_by, deleted_at, deleted_by, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)",
            (permission_id, role_id, user_id, category, world_id, now, g.current_user_id, now, now),
        )
        writer.commit()
    except Exception as exc:
        return error("VALIDATION_ERROR", str(exc), status=409)
    return ok({"permission_id": permission_id}, status=201)


@administration_bp.delete("/permissions/<permission_id>")
def revoke_permission(permission_id: str):
    writer = _container().store.writer()
    writer.execute(
        "UPDATE permissions SET deleted_at = ?, deleted_by = ?, updated_at = ? "
        "WHERE permission_id = ? AND deleted_at IS NULL",
        (
            int(_container().clock.now()),
            g.current_user_id,
            int(_container().clock.now()),
            permission_id,
        ),
    )
    changed = writer.execute("SELECT changes()").fetchone()[0]
    writer.commit()
    if not changed:
        return error("NOT_FOUND", "Permission not found.", status=404)
    return ok({"permission_id": permission_id, "revoked": True})


@administration_bp.get("/devices")
def list_devices():
    rows = (
        _container()
        .store.reader()
        .execute(
            "SELECT device_id, device_name, ip_address, owner, status, last_seen_at, "
            "created_at, updated_at FROM devices WHERE deleted_at IS NULL ORDER BY last_seen_at DESC"
        )
        .fetchall()
    )
    result = [dict(row) for row in rows]
    for row in result:
        row["last_seen_at"] = _iso(row["last_seen_at"])
        row["created_at"] = _iso(row["created_at"])
        row["updated_at"] = _iso(row["updated_at"])
    return ok({"devices": result})


@administration_bp.patch("/devices/<device_id>")
def update_device(device_id: str):
    body = _body()
    allowed = {"device_name", "status"}
    if body is None or not body or set(body).difference(allowed):
        return error("VALIDATION_ERROR", "Editable device fields are required.")
    if "device_name" in body and (
        not isinstance(body["device_name"], str) or not body["device_name"].strip()
    ):
        return error("VALIDATION_ERROR", "device_name must be a non-empty string.")
    if "status" in body and body["status"] not in {"registered", "unrecognized", "revoked"}:
        return error("VALIDATION_ERROR", "status is invalid.")
    container = _container()
    row = (
        container.store.reader()
        .execute("SELECT 1 FROM devices WHERE device_id = ? AND deleted_at IS NULL", (device_id,))
        .fetchone()
    )
    if row is None:
        return error("NOT_FOUND", "Device not found.", status=404)
    now = int(container.clock.now())
    if body.get("status") == "revoked":
        container.store.writer().execute(
            "UPDATE devices SET deleted_at = ?, deleted_by = ?, updated_at = ? WHERE device_id = ?",
            (now, g.current_user_id, now, device_id),
        )
        container.store.writer().commit()
        container.store.writer().execute(
            "UPDATE client_sessions SET deleted_at = ?, deleted_by = ? "
            "WHERE device_id = ? AND deleted_at IS NULL",
            (now, g.current_user_id, device_id),
        )
        container.store.writer().commit()
        return ok({"device_id": device_id, "status": "revoked"})
    fields = {
        key: value.strip() if isinstance(value, str) else value for key, value in body.items()
    }
    assignments = ", ".join(f"{key} = ?" for key in fields)
    writer = container.store.writer()
    writer.execute(
        f"UPDATE devices SET {assignments}, updated_at = ? WHERE device_id = ?",
        [*fields.values(), now, device_id],
    )
    writer.commit()
    return ok({"device_id": device_id, **fields})


@administration_bp.get("/devices/<device_id>/sessions")
def device_sessions(device_id: str):
    if (
        _container()
        .store.reader()
        .execute("SELECT 1 FROM devices WHERE device_id = ?", (device_id,))
        .fetchone()
        is None
    ):
        return error("NOT_FOUND", "Device not found.", status=404)
    rows = (
        _container()
        .store.reader()
        .execute(
            "SELECT session_id, user_id, ip_address, expires_at, last_activity_at, "
            "deleted_at, created_at FROM client_sessions WHERE device_id = ? "
            "ORDER BY created_at DESC LIMIT 500",
            (device_id,),
        )
        .fetchall()
    )
    result = [dict(row) for row in rows]
    for row in result:
        for key in ("expires_at", "last_activity_at", "deleted_at", "created_at"):
            row[key] = _iso(row[key])
    return ok({"sessions": result})


@administration_bp.get("/session/activity")
def session_activity():
    session = g.current_session
    row = (
        _container()
        .store.reader()
        .execute(
            "SELECT session_id, device_id, ip_address, expires_at, step_up_confirmed_at, "
            "last_activity_at, created_at FROM client_sessions WHERE session_id = ?",
            (session.session_id_hash,),
        )
        .fetchone()
    )
    if row is None:
        return error("NOT_FOUND", "Session activity is unavailable.", status=404)
    activity = dict(row)
    for key in ("expires_at", "step_up_confirmed_at", "last_activity_at", "created_at"):
        activity[key] = _iso(activity[key])
    return ok({"activity": activity})
