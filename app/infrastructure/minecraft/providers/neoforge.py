"""NeoForge installer discovery with validated Minecraft-version mapping."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from app.infrastructure.minecraft.providers.base import ProviderAdapter, quote_segment
from app.ports.server_artifacts import ArtifactDescriptor

_METADATA = "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
_MAVEN = "https://maven.neoforged.net/releases/net/neoforged/neoforge"
_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def minecraft_version(neoforge_version: str) -> str | None:
    match = _VERSION.fullmatch(neoforge_version)
    if match is None:
        return None
    major, minor = int(match.group(1)), int(match.group(2))
    if major < 20 or major > 99 or minor > 99:
        return None
    return f"1.{major}.{minor}"


class NeoForgeProvider(ProviderAdapter):
    provider = "neoforge"

    def discover(self, *, scope: str) -> list[ArtifactDescriptor]:
        root = ET.fromstring(self.http.get_bytes(_METADATA, max_bytes=16 * 1024 * 1024))
        by_mc: dict[str, list[str]] = {}
        for element in root.findall(".//version"):
            version = element.text
            if not version:
                continue
            mc_version = minecraft_version(version)
            if mc_version is not None:
                by_mc.setdefault(mc_version, []).append(version)
        result: list[ArtifactDescriptor] = []
        for mc_version, versions in sorted(by_mc.items()):
            ordered = sorted(
                versions,
                key=lambda value: tuple(int(part) for part in _VERSION.fullmatch(value).groups()),
            )
            selected = ordered if scope == "all" else ordered[-1:]
            result.extend(self._descriptor(mc_version, version) for version in selected)
        return result

    def resolve(
        self, *, mc_version: str, build: str, artifact_kind: str
    ) -> ArtifactDescriptor | None:
        if artifact_kind != "installer" or minecraft_version(build) != mc_version:
            return None
        root = ET.fromstring(self.http.get_bytes(_METADATA, max_bytes=16 * 1024 * 1024))
        if not any(item.text == build for item in root.findall(".//version")):
            return None
        return self._descriptor(mc_version, build)

    def _descriptor(self, mc_version: str, version: str) -> ArtifactDescriptor:
        return self.descriptor(
            provider=self.provider,
            mc_version=mc_version,
            build=version,
            artifact_kind="installer",
            source_url=f"{_MAVEN}/{quote_segment(version)}/neoforge-{quote_segment(version)}-installer.jar",
        )
