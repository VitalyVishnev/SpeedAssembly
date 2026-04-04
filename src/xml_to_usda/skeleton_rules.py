from __future__ import annotations

import re


_GENERATOR_LEVEL_PATTERN = re.compile(r"^Group_(?P<level>\d+)(?:[ _-]\d+)?$", re.IGNORECASE)
_GENERATOR_SUFFIX_LEVEL_PATTERN = re.compile(r"^(?P<label>.+?)[ _-](?P<level>\d+)$", re.IGNORECASE)


def parse_generator_label(generator_label: str | None, bone_id: int) -> tuple[str | None, int | None]:
    if generator_label is None or not generator_label.strip():
        return None, None

    normalized_label = " ".join(generator_label.strip().split())
    lower_label = normalized_label.lower()
    if lower_label in {"trunk", "root"}:
        return normalized_label, 0
    match = _GENERATOR_LEVEL_PATTERN.match(normalized_label)
    if match is not None:
        return normalized_label, int(match.group("level"))
    suffix_match = _GENERATOR_SUFFIX_LEVEL_PATTERN.match(normalized_label)
    if suffix_match is not None:
        return normalized_label, int(suffix_match.group("level"))
    return normalized_label, None


def joint_name_from_bone_id(bone_id: int | None) -> str:
    if bone_id is None:
        return "root"
    return "root" if bone_id == 0 else f"bone_{bone_id:03d}"
