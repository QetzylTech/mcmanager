"""Authenticated documentation and manager log browsing APIs."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from flask import Blueprint, send_file

from app.web.errors import error, ok

documentation_bp = Blueprint(
    "api_documentation", __name__, url_prefix="/api/documentation"
)
manager_logs_bp = Blueprint("api_manager_logs", __name__, url_prefix="/api/manager/logs")

_LOG_CHANNELS = frozenset(
    {
        "minecraft",
        "crash_reports",
        "backup_restore",
        "panel_activity",
        "panel_errors",
        "debug",
        "sync",
        "manager_action",
    }
)


def _documentation_root() -> tuple[Path, Path]:
    repository_root = Path(__file__).resolve().parents[3]
    return repository_root / "docs", repository_root


def _manager_logs_root() -> tuple[Path, Path]:
    app_root = Path(__file__).resolve().parents[2]
    return app_root / "data" / "logs", app_root


def _safe_root(root: Path, boundary: Path) -> Path | None:
    try:
        resolved_boundary = boundary.resolve(strict=True)
        resolved_root = root.resolve(strict=False)
        resolved_root.relative_to(resolved_boundary)
        if resolved_root != root:
            return None
        return resolved_root
    except (OSError, RuntimeError, ValueError):
        return None


def _guarded_path(root: Path, boundary: Path, relative: str) -> Path | None:
    safe_root = _safe_root(root, boundary)
    if safe_root is None:
        return None
    parts = PurePosixPath(relative.replace("\\", "/")).parts
    if not parts or PurePosixPath(relative.replace("\\", "/")).is_absolute():
        return None
    if any(part in {"", ".", ".."} for part in parts):
        return None

    candidate = safe_root
    try:
        for part in parts:
            candidate = candidate / part
            if candidate.is_symlink():
                return None
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(safe_root)
        return resolved
    except (OSError, RuntimeError, ValueError):
        return None


def _markdown_title(path: Path) -> str:
    try:
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                stripped = line.strip()
                if stripped:
                    return (
                        stripped.lstrip("#").strip()
                        if stripped.startswith("#")
                        else path.stem
                    )
    except OSError:
        pass
    return path.stem


@documentation_bp.get("")
def list_documentation() -> Any:
    root, boundary = _documentation_root()
    safe_root = _safe_root(root, boundary)
    documents: list[dict[str, Any]] = []
    if safe_root is not None and safe_root.is_dir():
        for candidate in safe_root.rglob("*.md"):
            relative = candidate.relative_to(safe_root).as_posix()
            target = _guarded_path(root, boundary, relative)
            if target is None or not target.is_file():
                continue
            try:
                stat = target.stat()
            except OSError:
                continue
            documents.append(
                {
                    "path": relative,
                    "title": _markdown_title(target),
                    "size": stat.st_size,
                    "mtime": int(stat.st_mtime),
                }
            )
    documents.sort(key=lambda item: item["path"].casefold())
    return ok({"documents": documents})


@documentation_bp.get("/<path:document_path>")
def read_documentation(document_path: str) -> Any:
    root, boundary = _documentation_root()
    target = _guarded_path(root, boundary, document_path)
    if target is None:
        return error("FILE_PATH_UNAUTHORIZED", "Document path escapes the repository docs directory.")
    if target.suffix.lower() != ".md" or not target.is_file():
        return error("NOT_FOUND", "Markdown document not found.", status=404)
    try:
        content = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return error("INTERNAL_ERROR", "Markdown document cannot be read.", status=500)
    return ok(
        {
            "document": {
                "path": PurePosixPath(document_path.replace("\\", "/")).as_posix(),
                "source_format": "text/markdown",
                "rendering": "source",
                "rendered_html": None,
                "content": content,
            }
        }
    )


def _existing_channels(root: Path, boundary: Path) -> list[str]:
    safe_root = _safe_root(root, boundary)
    if safe_root is None or not safe_root.is_dir():
        return []
    channels = []
    for channel in sorted(_LOG_CHANNELS):
        directory = _guarded_path(root, boundary, channel)
        if directory is not None and directory.is_dir():
            channels.append(channel)
    return channels


@manager_logs_bp.get("")
def list_manager_log_channels() -> Any:
    root, boundary = _manager_logs_root()
    return ok({"channels": _existing_channels(root, boundary)})


@manager_logs_bp.get("/<channel>")
def list_manager_log_files(channel: str) -> Any:
    if channel not in _LOG_CHANNELS:
        return error("VALIDATION_ERROR", "Unsupported manager log channel.")
    root, boundary = _manager_logs_root()
    directory = _guarded_path(root, boundary, channel)
    if directory is None:
        return error("FILE_PATH_UNAUTHORIZED", "Log channel escapes the manager logs directory.")
    if not directory.is_dir():
        return error("FILE_NOT_FOUND", "Manager log channel not found.")

    files = []
    for candidate in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
        target = _guarded_path(root, boundary, f"{channel}/{candidate.name}")
        if target is None or not target.is_file() or candidate.name.startswith("."):
            continue
        try:
            stat = target.stat()
        except OSError:
            continue
        files.append(
            {"name": candidate.name, "size": stat.st_size, "mtime": int(stat.st_mtime)}
        )
    return ok({"channel": channel, "files": files})


@manager_logs_bp.get("/<channel>/<path:filename>")
def download_manager_log(channel: str, filename: str) -> Any:
    if channel not in _LOG_CHANNELS:
        return error("VALIDATION_ERROR", "Unsupported manager log channel.")
    relative_file = PurePosixPath(filename.replace("\\", "/"))
    if (
        len(relative_file.parts) != 1
        or relative_file.is_absolute()
        or relative_file.name.startswith(".")
    ):
        return error("FILE_PATH_UNAUTHORIZED", "Log file path is not a channel file.")
    root, boundary = _manager_logs_root()
    target = _guarded_path(root, boundary, f"{channel}/{relative_file.as_posix()}")
    if target is None:
        return error("FILE_PATH_UNAUTHORIZED", "Log file escapes the manager logs directory.")
    if not target.is_file():
        return error("FILE_NOT_FOUND", "Manager log file not found.")
    return send_file(target, as_attachment=True, download_name=target.name)
