"""Provider adapter construction."""

from __future__ import annotations

from app.infrastructure.minecraft.providers.base import SafeHttpClient
from app.infrastructure.minecraft.providers.fabric import FabricProvider
from app.infrastructure.minecraft.providers.forge import ForgeProvider
from app.infrastructure.minecraft.providers.neoforge import NeoForgeProvider
from app.infrastructure.minecraft.providers.paper import PaperProvider
from app.infrastructure.minecraft.providers.purpur import PurpurProvider
from app.infrastructure.minecraft.providers.vanilla import VanillaProvider
from app.ports.server_artifacts import ServerArtifactProviderPort


def build_provider_adapters(
    http: SafeHttpClient | None = None,
) -> dict[str, ServerArtifactProviderPort]:
    client = http or SafeHttpClient()
    providers = (
        VanillaProvider,
        PaperProvider,
        PurpurProvider,
        FabricProvider,
        ForgeProvider,
        NeoForgeProvider,
    )
    return {provider.provider: provider(client) for provider in providers}
