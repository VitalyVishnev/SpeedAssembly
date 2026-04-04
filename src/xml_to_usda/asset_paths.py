from __future__ import annotations


def is_valid_unreal_asset_path(path: str) -> bool:
    return path.startswith("/Game/")


def normalize_unreal_asset_path(path: str) -> str:
    normalized = path.strip()
    if not normalized.startswith("/Game/"):
        return normalized
    package_path = normalized.rsplit("/", 1)[-1]
    if "." in package_path:
        return normalized
    return f"{normalized}.{package_path}"
