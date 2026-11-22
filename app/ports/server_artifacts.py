"""Provider-facing server artifact contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ArtifactDescriptor:
    provider: str
    mc_version: str
    build: str
    artifact_kind: str
    descriptor_id: str
    source_url: str
    advertised_size_bytes: int | None = None
    upstream_checksums: dict[str, str] | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "descriptor_id": self.descriptor_id,
            "provider": self.provider,
            "mc_version": self.mc_version,
            "build": self.build,
            "artifact_kind": self.artifact_kind,
            "advertised_size_bytes": self.advertised_size_bytes,
            "upstream_checksums": self.upstream_checksums or {},
        }


class ServerArtifactProviderPort(Protocol):
    """Metadata and download contract implemented by each trusted provider."""

    provider: str

    def discover(self, *, scope: str) -> list[ArtifactDescriptor]: ...

    def resolve(
        self, *, mc_version: str, build: str, artifact_kind: str
    ) -> ArtifactDescriptor | None: ...


class ServerArtifactHttpPort(Protocol):
    def get_json(self, url: str) -> Any: ...

    def get_bytes(self, url: str, *, max_bytes: int) -> bytes: ...

    def open(self, url: str) -> Any: ...
