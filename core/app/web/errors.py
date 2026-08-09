"""API envelope helpers."""

from __future__ import annotations

from flask import jsonify


def ok(data: dict, *, status: int = 200, meta: dict | None = None):
    return jsonify({'ok': True, 'data': data, 'meta': meta or {}}), status


def error(code: str, message: str, *, status: int = 400, details: dict | None = None, meta: dict | None = None):
    return jsonify({'ok': False, 'error': {'code': code, 'message': message, 'details': details or {}}, 'meta': meta or {}}), status
