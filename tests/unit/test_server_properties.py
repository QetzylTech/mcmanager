"""Focused server.properties value and file-safety behavior."""

from __future__ import annotations

import pytest

from app.ports.minecraft import parse_properties
from app.services.server_properties import (
    _atomic_write_properties,
    _escape_property,
    _property_string,
    _restore_file,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, "true"),
        (False, "false"),
        ("string", "string"),
        (42, "42"),
    ],
)
def test_property_string_preserves_supported_value_types(value, expected):
    assert _property_string(value) == expected


def test_property_string_rejects_unsupported_value_type():
    with pytest.raises(
        ValueError, match="property values must be strings, integers, or booleans"
    ):
        _property_string(1.5)


def test_server_properties_escape_and_atomic_write_round_trip_special_text(tmp_path):
    path = tmp_path / "server.properties"
    properties = {
        "test:key": "slash\\tab\tline\nreturn\rform\f",
    }

    _atomic_write_properties(path, properties)

    text = path.read_text(encoding="utf-8")
    assert _escape_property("test:key", key=True) == r"test\:key"
    assert r"test\:key=" in text
    assert parse_properties(text) == properties


def test_restore_file_replaces_existing_content_and_removes_new_file(tmp_path):
    path = tmp_path / "server.properties"
    path.write_bytes(b"original")
    _restore_file(path, b"restored")
    assert path.read_bytes() == b"restored"

    _restore_file(path, None)
    assert not path.exists()
