"""Purpur build discovery."""

from __future__ import annotations

from app.infrastructure.minecraft.providers.base import ProviderAdapter, quote_segment
from app.ports.server_artifacts import ArtifactDescriptor

_BASE = "https://api.purpurmc.org/v2/purpur"


class PurpurProvider(ProviderAdapter):
    provider = "purpur"

    def discover(self, *, scope: str) -> list[ArtifactDescriptor]:
        catalog = self.http.get_json(_BASE)
        versions = catalog.get("versions", []) if isinstance(catalog, dict) else []
        if not isinstance(versions, list):
            return []
        results: list[ArtifactDescriptor] = []
        for version in versions:
            if not isinstance(version, str):
                continue
            builds = self.http.get_json(f"{_BASE}/{quote_segment(version)}")
            values = builds.get("builds", {}) if isinstance(builds, dict) else {}
            all_builds = values.get("all", []) if isinstance(values, dict) else []
            latest = values.get("latest") if isinstance(values, dict) else None
            selected = all_builds if scope == "all" else [latest]
            for build in selected:
                if build is None:
                    continue
                build_text = str(build)
                results.append(
                    self.descriptor(
                        provider=self.provider,
                        mc_version=version,
                        build=build_text,
                        artifact_kind="runnable_server",
                        source_url=f"{_BASE}/{quote_segment(version)}/{quote_segment(build_text)}/download",
                    )
                )
        return results

    def resolve(
        self, *, mc_version: str, build: str, artifact_kind: str
    ) -> ArtifactDescriptor | None:
        if artifact_kind != "runnable_server":
            return None
        builds = self.http.get_json(f"{_BASE}/{quote_segment(mc_version)}")
        build_info = builds.get("builds", {}) if isinstance(builds, dict) else {}
        choices = build_info.get("all", []) if isinstance(build_info, dict) else []
        if build not in {str(value) for value in choices}:
            return None
        return self.descriptor(
            provider=self.provider,
            mc_version=mc_version,
            build=build,
            artifact_kind=artifact_kind,
            source_url=f"{_BASE}/{quote_segment(mc_version)}/{quote_segment(build)}/download",
        )
