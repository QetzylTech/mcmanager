"""Fabric server-launcher discovery."""

from __future__ import annotations

from app.infrastructure.minecraft.providers.base import ProviderAdapter, quote_segment
from app.ports.server_artifacts import ArtifactDescriptor

_BASE = "https://meta.fabricmc.net/v2"


class FabricProvider(ProviderAdapter):
    provider = "fabric"

    def discover(self, *, scope: str) -> list[ArtifactDescriptor]:
        games = self.http.get_json(f"{_BASE}/versions/game")
        loaders = self.http.get_json(f"{_BASE}/versions/loader")
        installers = self.http.get_json(f"{_BASE}/versions/installer")
        if not all(isinstance(value, list) for value in (games, loaders, installers)):
            return []
        stable_loaders = [item for item in loaders if item.get("stable")]
        stable_installers = [item for item in installers if item.get("stable")]
        loader_values = stable_loaders or loaders
        installer_values = stable_installers or installers
        if scope == "latest":
            loader_values = loader_values[:1]
        if not installer_values:
            return []
        installer = installer_values[0].get("version")
        if not isinstance(installer, str):
            return []
        results: list[ArtifactDescriptor] = []
        for game in games:
            version = game.get("version") if isinstance(game, dict) else None
            if not isinstance(version, str):
                continue
            for loader in loader_values:
                loader_version = loader.get("version") if isinstance(loader, dict) else None
                if not isinstance(loader_version, str):
                    continue
                results.append(
                    self._descriptor(version, loader_version, installer)
                )
        return results

    def resolve(
        self, *, mc_version: str, build: str, artifact_kind: str
    ) -> ArtifactDescriptor | None:
        if artifact_kind != "launcher":
            return None
        pieces = build.split("|")
        if len(pieces) != 2:
            return None
        loader, installer = pieces
        games = self.http.get_json(f"{_BASE}/versions/game")
        loaders = self.http.get_json(f"{_BASE}/versions/loader")
        installers = self.http.get_json(f"{_BASE}/versions/installer")
        if (
            not isinstance(games, list)
            or not any(
                isinstance(item, dict) and item.get("version") == mc_version
                for item in games
            )
            or not isinstance(loaders, list)
            or not any(
                isinstance(item, dict) and item.get("version") == loader
                for item in loaders
            )
            or not isinstance(installers, list)
            or not any(
                isinstance(item, dict) and item.get("version") == installer
                for item in installers
            )
        ):
            return None
        return self._descriptor(mc_version, loader, installer)

    def _descriptor(self, version: str, loader: str, installer: str) -> ArtifactDescriptor:
        url = (
            f"{_BASE}/versions/loader/{quote_segment(version)}/"
            f"{quote_segment(loader)}/{quote_segment(installer)}/server/jar"
        )
        return self.descriptor(
            provider=self.provider,
            mc_version=version,
            build=f"{loader}|{installer}",
            artifact_kind="launcher",
            source_url=url,
        )
