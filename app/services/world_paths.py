from pathlib import Path
from typing import Any


def resolve_world_directory(world: dict[str, Any], minecraft_root: str) -> Path:
    directory = world.get("world_directory")
    if isinstance(directory, str) and directory:
        return Path(directory)
    if world["addressing_strategy"] == "path":
        candidate = Path(world["addressing_value"])
        if candidate.is_absolute():
            return candidate
    return Path(str(minecraft_root or "worlds")) / str(world["display_name"])


def allocate_world_directory(world: dict[str, Any], minecraft_root: str) -> Path:
    if world["addressing_strategy"] == "path":
        candidate = Path(world["addressing_value"])
        if candidate.is_absolute():
            return candidate.expanduser().resolve()
    return (Path(str(minecraft_root or "worlds")) / str(world["world_id"])).expanduser().resolve()
