"""Shared constrained HTTP and descriptor helpers for provider adapters."""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.ports.server_artifacts import ArtifactDescriptor

ALLOWED_HOSTS = frozenset(
    {
        "piston-meta.mojang.com",
        "piston-data.mojang.com",
        "launcher.mojang.com",
        "api.purpurmc.org",
        "fill.papermc.io",
        "api.papermc.io",
        "meta.fabricmc.net",
        "files.minecraftforge.net",
        "maven.minecraftforge.net",
        "maven.neoforged.net",
    }
)
_USER_AGENT = "MCManager/1.0 server-artifact-catalog"
_METADATA_LIMIT = 16 * 1024 * 1024


class ArtifactProviderError(RuntimeError):
    """A provider returned invalid metadata or an unsafe/unavailable response."""


class _ValidatedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        validate_provider_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def validate_provider_url(url: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.fragment
    ):
        raise ArtifactProviderError("Provider returned a disallowed HTTPS URL.")
    return parsed


class SafeHttpClient:
    """HTTPS-only client with strict provider host and redirect validation."""

    def __init__(self, *, timeout: float = 45) -> None:
        self._timeout = timeout
        self._opener = urllib.request.build_opener(_ValidatedRedirectHandler())

    def get_json(self, url: str) -> Any:
        raw = self.get_bytes(url, max_bytes=_METADATA_LIMIT)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArtifactProviderError("Provider returned invalid JSON.") from exc

    def get_bytes(self, url: str, *, max_bytes: int) -> bytes:
        with self.open(url) as response:
            payload = response.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise ArtifactProviderError("Provider metadata exceeded the response limit.")
        return payload

    @contextmanager
    def open(self, url: str) -> Iterator[Any]:
        validate_provider_url(url)
        request = urllib.request.Request(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json, */*"},
        )
        try:
            response = self._opener.open(request, timeout=self._timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ArtifactProviderError(f"Provider request failed: {exc}") from exc
        try:
            validate_provider_url(response.geturl())
            yield response
        finally:
            response.close()


class ProviderAdapter:
    provider: str

    def __init__(self, http: SafeHttpClient | None = None) -> None:
        self.http = http or SafeHttpClient()

    @staticmethod
    def descriptor(
        *,
        provider: str,
        mc_version: str,
        build: str,
        artifact_kind: str,
        source_url: str,
        advertised_size_bytes: int | None = None,
        upstream_checksums: dict[str, str] | None = None,
    ) -> ArtifactDescriptor:
        identity = {
            "provider": provider,
            "mc_version": mc_version,
            "build": build,
            "artifact_kind": artifact_kind,
            "source_url": source_url,
            "upstream_checksums": upstream_checksums or {},
        }
        descriptor_id = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return ArtifactDescriptor(
            provider=provider,
            mc_version=mc_version,
            build=build,
            artifact_kind=artifact_kind,
            descriptor_id=descriptor_id,
            source_url=source_url,
            advertised_size_bytes=advertised_size_bytes,
            upstream_checksums=upstream_checksums or {},
        )

    def discover(self, *, scope: str) -> list[ArtifactDescriptor]:
        raise NotImplementedError

    def resolve(
        self, *, mc_version: str, build: str, artifact_kind: str
    ) -> ArtifactDescriptor | None:
        return next(
            (
                item
                for item in self.discover(scope="all")
                if item.mc_version == mc_version
                and item.build == build
                and item.artifact_kind == artifact_kind
            ),
            None,
        )


def require_mapping(value: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ArtifactProviderError(f"{context} response must be an object.")
    return value


def require_list(value: Any, *, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise ArtifactProviderError(f"{context} response must be a list.")
    return value


def quote_segment(value: str) -> str:
    return urllib.parse.quote(value, safe="")
