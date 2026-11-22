"""Mojang server-version discovery."""

from __future__ import annotations

from app.infrastructure.minecraft.providers.base import (
    ProviderAdapter,
    require_list,
)
from app.ports.server_artifacts import ArtifactDescriptor

_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"


class VanillaProvider(ProviderAdapter):
    provider = "vanilla"

    def discover(self, *, scope: str) -> list[ArtifactDescriptor]:
        manifest = self.http.get_json(_MANIFEST_URL)
        versions = require_list(manifest.get("versions"), context="Vanilla manifest")
        descriptors: list[ArtifactDescriptor] = []
        for item in versions:
            if not isinstance(item, dict):
                continue
            version = item.get("id")
            version_type = item.get("type")
            metadata_url = item.get("url")
            if not all(isinstance(value, str) and value for value in (version, metadata_url)):
                continue
            if scope == "latest" and version_type != "release":
                continue
            metadata = self.http.get_json(metadata_url)
            downloads = metadata.get("downloads", {}) if isinstance(metadata, dict) else {}
            server = downloads.get("server") if isinstance(downloads, dict) else None
            if not isinstance(server, dict) or not isinstance(server.get("url"), str):
                continue
            checksums = {}
            if isinstance(server.get("sha1"), str) and server["sha1"]:
                checksums["sha1"] = server["sha1"].lower()
            descriptors.append(
                self.descriptor(
                    provider=self.provider,
                    mc_version=version,
                    build=str(version_type or "unknown"),
                    artifact_kind="runnable_server",
                    source_url=server["url"],
                    advertised_size_bytes=server.get("size")
                    if type(server.get("size")) is int
                    else None,
                    upstream_checksums=checksums,
                )
            )
        return descriptors

    def resolve(
        self, *, mc_version: str, build: str, artifact_kind: str
    ) -> ArtifactDescriptor | None:
        if artifact_kind != "runnable_server":
            return None
        manifest = self.http.get_json(_MANIFEST_URL)
        versions = require_list(manifest.get("versions"), context="Vanilla manifest")
        for item in versions:
            if not isinstance(item, dict) or item.get("id") != mc_version:
                continue
            if str(item.get("type") or "unknown") != build:
                return None
            metadata_url = item.get("url")
            if not isinstance(metadata_url, str):
                return None
            metadata = self.http.get_json(metadata_url)
            server = metadata.get("downloads", {}).get("server")
            if not isinstance(server, dict) or not isinstance(server.get("url"), str):
                return None
            checksums = {"sha1": str(server["sha1"]).lower()} if server.get("sha1") else {}
            return self.descriptor(
                provider=self.provider,
                mc_version=mc_version,
                build=build,
                artifact_kind=artifact_kind,
                source_url=server["url"],
                advertised_size_bytes=server.get("size")
                if type(server.get("size")) is int
                else None,
                upstream_checksums=checksums,
            )
        return None
