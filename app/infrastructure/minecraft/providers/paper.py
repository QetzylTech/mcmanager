"""PaperMC v3 build discovery."""

from __future__ import annotations

from typing import Any

from app.infrastructure.minecraft.providers.base import ProviderAdapter, quote_segment
from app.ports.server_artifacts import ArtifactDescriptor

_BASE = "https://fill.papermc.io/v3"


class PaperProvider(ProviderAdapter):
    provider = "paper"

    def discover(self, *, scope: str) -> list[ArtifactDescriptor]:
        projects = self.http.get_json(f"{_BASE}/projects")
        if isinstance(projects, dict):
            projects = projects.get("projects", [])
        if not isinstance(projects, list) or "paper" not in projects:
            return []
        project = self.http.get_json(f"{_BASE}/projects/paper")
        versions_data = project.get("versions", {}) if isinstance(project, dict) else {}
        versions = (
            versions_data.get("versions", [])
            if isinstance(versions_data, dict)
            else versions_data
        )
        if isinstance(versions, dict):
            versions = list(versions)
        if not isinstance(versions, list):
            return []
        results: list[ArtifactDescriptor] = []
        for version in versions:
            if not isinstance(version, str):
                continue
            builds = self._builds(version)
            if scope == "latest":
                stable = [
                    build
                    for build in builds
                    if str(build.get("channel", "")).upper() == "STABLE"
                ]
                builds = stable[:1] or builds[:1]
            for build_info in builds:
                descriptor = self._descriptor(version, build_info)
                if descriptor is not None:
                    results.append(descriptor)
        return results

    def resolve(
        self, *, mc_version: str, build: str, artifact_kind: str
    ) -> ArtifactDescriptor | None:
        if artifact_kind != "runnable_server":
            return None
        for build_info in self._builds(mc_version):
            if str(build_info.get("build")) == build:
                return self._descriptor(mc_version, build_info)
        return None

    def _builds(self, version: str) -> list[dict[str, Any]]:
        payload = self.http.get_json(
            f"{_BASE}/projects/paper/versions/{quote_segment(version)}/builds"
        )
        values = payload.get("builds", []) if isinstance(payload, dict) else payload
        return [value for value in values if isinstance(value, dict)] if isinstance(values, list) else []

    def _descriptor(self, version: str, value: dict[str, Any]) -> ArtifactDescriptor | None:
        build = value.get("build")
        downloads = value.get("downloads", {})
        server = downloads.get("server:default") or downloads.get("server") if isinstance(downloads, dict) else None
        url = server.get("url") if isinstance(server, dict) else None
        if build is None or not isinstance(url, str):
            return None
        return self.descriptor(
            provider=self.provider,
            mc_version=version,
            build=str(build),
            artifact_kind="runnable_server",
            source_url=url,
            advertised_size_bytes=server.get("size")
            if type(server.get("size")) is int
            else None,
            upstream_checksums=server.get("checksums")
            if isinstance(server.get("checksums"), dict)
            else {},
        )
