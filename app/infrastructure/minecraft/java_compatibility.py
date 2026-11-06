"""Java runtime detection + Doc 14 section 7 compatibility matrix."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from app.domain.value_objects import ServerType
from app.ports.minecraft import JavaCompatibility, java_compatibility_for
from app.ports.minecraft import JAVA_COMPATIBILITY  # noqa: F401  (reference data)

_JAVA_VERSION_RE = re.compile(r'version "(?P<version>[^"]+)"')
_OLD_RUNTIME_RE = re.compile(r'^(?:1\.)?(?P<major>\d+)')


@dataclass(frozen=True)
class JavaDetection:
    """Resolved Java runtime info for a path."""

    path: str
    major: int
    full_version: str


def detect_java(path: str) -> JavaDetection | None:
    """Run ``<path> -version`` and parse the major version.

    Returns None when the path is not a runnable java (missing, exec error,
    or unparseable version). A major of 0 means unknown-but-runnable.
    """
    try:
        result = subprocess.run(
            [path, '-version'],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    output = result.stdout + result.stderr
    match = _JAVA_VERSION_RE.search(output)
    if not match:
        return None
    raw = match.group('version')
    return JavaDetection(path=path, major=parse_java_major(raw), full_version=raw)


def parse_java_major(raw_version: str) -> int:
    """Normalize a ``java -version`` string to its major version.

    ``1.8.0_411`` -> 8 (pre-9 naming), ``17.0.9`` -> 17, ``21`` -> 21.
    """
    if raw_version.startswith('1.'):
        old = _OLD_RUNTIME_RE.match(raw_version)
        return int(old.group('major')) if old else 0
    first = raw_version.split('.')[0]
    return int(first) if first.isdigit() else 0


def java_compatible(
    *, server_type: ServerType, mc_version: str, java_major: int
) -> bool:
    """Curated reference data check (Doc 14 section 7)."""
    record = java_compatibility_for(server_type, mc_version)
    if record is None:
        return False
    return java_major in record.supported_major


def compatibility_record(server_type: ServerType, mc_version: str) -> JavaCompatibility | None:
    return java_compatibility_for(server_type, mc_version)


def recommended_java(server_type: ServerType, mc_version: str) -> int | None:
    record = java_compatibility_for(server_type, mc_version)
    return record.recommended_major if record else None
