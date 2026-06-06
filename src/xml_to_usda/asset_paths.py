from __future__ import annotations

import re


_UE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


def is_valid_unreal_asset_path(path: str) -> bool:
    if not path.startswith("/Game/"):
        return False
    if any(character.isspace() for character in path):
        return False
    if any(character in path for character in ('\\', '"', "'", "@", "{", "}", "[", "]", "(", ")")):
        return False

    tail = path.removeprefix("/Game/")
    segments = tail.split("/")
    if not segments or any(not segment or segment in {".", ".."} for segment in segments):
        return False
    if not all(_is_valid_unreal_package_segment(segment) for segment in segments[:-1]):
        return False

    package_object = segments[-1].split(".")
    if len(package_object) != 2:
        return False
    package_name, object_name = package_object
    return _is_valid_unreal_package_segment(package_name) and _UE_NAME_RE.fullmatch(object_name) is not None


def normalize_unreal_asset_path(path: str) -> str:
    normalized = path.strip()
    if not normalized.startswith("/Game/"):
        return normalized
    package_path = normalized.rsplit("/", 1)[-1]
    if "." in package_path:
        return normalized
    return f"{normalized}.{package_path}"


def _is_valid_unreal_package_segment(segment: str) -> bool:
    return _UE_NAME_RE.fullmatch(segment) is not None
