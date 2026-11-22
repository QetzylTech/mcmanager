"""Forge installer discovery from the official promotions feed."""

from __future__ import annotations

from app.infrastructure.minecraft.providers.base import ProviderAdapter, quote_segment
from app.ports.server_artifacts import ArtifactDescriptor

_PROMOTIONS = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions.json"
_MAVEN = "https://maven.minecraftforge.net/net/minecraftforge/forge"


class ForgeProvider(ProviderAdapter):
    provider = "forge"

    def discover(self, *, scope: str) -> list[ArtifactDescriptor]:
        payload = self.http.get_json(_PROMOTIONS)
        promotions = payload.get("promos", {}) if isinstance(payload, dict) else {}
        if not isinstance(promotions, dict):
            return []
        versions = sorted(
            {key.rsplit("-", 1)[0] for key in promotions if key.endswith(("-latest", "-recommended"))}
        )
        result: list[ArtifactDescriptor] = []
        for mc_version in versions:
            builds = []
            for suffix in ("recommended", "latest"):
                value = promotions.get(f"{mc_version}-{suffix}")
                if isinstance(value, str) and value not in builds:
                    builds.append(value)
            selected = builds if scope == "all" else builds[:1]
            for forge_build in selected:
                result.append(self._descriptor(mc_version, forge_build))
        return result

    def resolve(
        self, *, mc_version: str, build: str, artifact_kind: str
    ) -> ArtifactDescriptor | None:
        if artifact_kind != "installer":
            return None
        promotions = self.http.get_json(_PROMOTIONS).get("promos", {})
        if not isinstance(promotions, dict) or build not in {
            promotions.get(f"{mc_version}-latest"),
            promotions.get(f"{mc_version}-recommended"),
        }:
            return None
        return self._descriptor(mc_version, build)

    def _descriptor(self, mc_version: str, forge_build: str) -> ArtifactDescriptor:
        full = f"{mc_version}-{forge_build}"
        return self.descriptor(
            provider=self.provider,
            mc_version=mc_version,
            build=forge_build,
            artifact_kind="installer",
            source_url=f"{_MAVEN}/{quote_segment(full)}/forge-{quote_segment(full)}-installer.jar",
        )
