from __future__ import annotations

import pytest
from flask import Flask

from app.web.errors import ERROR_STATUS_CODES, error


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("AUTH_CSRF_INVALID", 403),
        ("AUTH_STEP_UP_REQUIRED", 403),
        ("WORLD_NOT_OFF", 409),
        ("OP_CONFLICT_IN_FLIGHT", 409),
        ("OP_NOT_CANCELLABLE", 409),
        ("CONFIG_VERSION_CONFLICT", 409),
        ("STORAGE_GUARD_TRIPPED", 409),
        ("AUTH_SESSION_INVALID", 401),
        ("CSRF_INVALID", 403),
        ("STEP_UP_REQUIRED", 403),
        ("WORLD_CONFLICT", 409),
        ("STORAGE_GUARD_FAILED", 409),
    ],
)
def test_documented_error_catalog_maps_codes_to_http_status(code: str, status: int) -> None:
    app = Flask(__name__)
    with app.app_context():
        response, actual_status = error(code, "request rejected", status=400)

    assert actual_status == status
    assert response.get_json() == {
        "ok": False,
        "error": {"code": code, "message": "request rejected", "details": {}},
        "meta": {},
    }


def test_catalog_contains_documented_http_errors() -> None:
    assert ERROR_STATUS_CODES["VALIDATION_STALE_VERSION"] == 409
    assert ERROR_STATUS_CODES["AUTH_ACCOUNT_LOCKED"] == 403
    assert ERROR_STATUS_CODES["WORLD_NAME_CONFLICT"] == 409
    assert ERROR_STATUS_CODES["OP_QUEUED"] == 202
    assert ERROR_STATUS_CODES["CONFIG_INVALID_VALUE"] == 400
    assert ERROR_STATUS_CODES["FILE_PATH_UNAUTHORIZED"] == 403
    assert ERROR_STATUS_CODES["NOT_IMPLEMENTED"] == 501


def test_uncatalogued_error_preserves_explicit_status_and_standard_envelope() -> None:
    app = Flask(__name__)
    with app.app_context():
        response, status = error(
            "SERVICE_BEHAVIOR_MISSING",
            "The operation is not implemented.",
            status=501,
            details={"capability": "operation cancellation"},
            meta={"op_id": "op_1"},
        )

    assert status == 501
    assert response.get_json() == {
        "ok": False,
        "error": {
            "code": "SERVICE_BEHAVIOR_MISSING",
            "message": "The operation is not implemented.",
            "details": {"capability": "operation cancellation"},
        },
        "meta": {"op_id": "op_1"},
    }


def test_uncatalogued_error_defaults_to_internal_server_error() -> None:
    app = Flask(__name__)
    with app.app_context():
        response, status = error("UNMAPPED_ERROR", "Unexpected failure.")

    assert status == 500
    assert response.get_json()["error"]["code"] == "UNMAPPED_ERROR"
