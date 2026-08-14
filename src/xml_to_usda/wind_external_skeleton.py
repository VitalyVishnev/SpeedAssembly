"""External skeleton loading for Wind Preview."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .fbx_adapter import FbxImportError, load_fbx_skeleton
from .models import ExportMetadata, Joint, Matrix4d, TreeAsset, Vector3
from .wind_preview_service import WindPreviewError, WindPreviewResult
from .wind_viewport_scene import build_auto_wind_viewport_data, build_wind_viewport_groups, build_wind_viewport_scene


SUPPORTED_USD_SKELETON_SUFFIXES = {".usd", ".usda", ".usdc"}
TEXT_USD_SKELETON_SUFFIXES = {".usd", ".usda"}
_USD_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


@dataclass(frozen=True, slots=True)
class ExternalSkeletonPreviewRequest:
    input_path: str
    group_count: int = 3
    skeleton_index: int | None = None


@dataclass(frozen=True, slots=True)
class ExternalSkeletonChoicesRequest:
    input_path: str


@dataclass(frozen=True, slots=True)
class ExternalSkeletonChoice:
    index: int
    prim_path: str
    name: str
    joint_count: int


@dataclass(frozen=True, slots=True)
class ExternalSkeletonChoicesResult:
    input_path: str
    choices: tuple[ExternalSkeletonChoice, ...]


@dataclass(frozen=True, slots=True)
class _UsdSkeletonCandidate:
    choice: ExternalSkeletonChoice
    joints: tuple[Joint, ...]


def load_external_skeleton_preview(request: ExternalSkeletonPreviewRequest) -> WindPreviewResult:
    input_path = request.input_path.strip()
    if not input_path:
        raise WindPreviewError("external_skeleton_missing_path: Select an FBX or USD skeleton file.")
    path = Path(input_path)
    suffix = path.suffix.lower()
    if suffix == ".fbx":
        skeleton = _load_fbx_skeleton_for_preview(path)
    elif suffix in SUPPORTED_USD_SKELETON_SUFFIXES:
        skeleton = _load_usd_skeleton_for_preview(path, skeleton_index=request.skeleton_index)
    else:
        raise WindPreviewError(f"external_skeleton_unsupported_format: {suffix or '<none>'}")
    if not skeleton:
        raise WindPreviewError(f"external_skeleton_not_found: {path}")

    _validate_unique_joint_names(skeleton)
    model = TreeAsset(
        metadata=ExportMetadata(source_path=str(path), source_version=None),
        materials=(),
        source_objects=(),
        base_mesh=None,
        skeleton=skeleton,
        assembly_parts=(),
        prototypes=(),
    )
    dynamic_wind = build_auto_wind_viewport_data(model.skeleton, group_count=max(1, min(10, int(request.group_count))))
    groups = build_wind_viewport_groups(dynamic_wind, label_kind="Hierarchy level")
    return WindPreviewResult(
        input_path=str(path),
        source_model=model,
        dynamic_wind=dynamic_wind,
        groups=groups,
        diagnostics=(),
        viewport_scene=build_wind_viewport_scene(model, dynamic_wind),
        xml_groups_available=False,
        preferred_grouping_mode="auto",
    )


def list_external_usd_skeletons(input_path: str) -> ExternalSkeletonChoicesResult:
    path = Path(input_path.strip())
    if path.suffix.lower() not in SUPPORTED_USD_SKELETON_SUFFIXES:
        raise WindPreviewError(f"external_skeleton_unsupported_format: {path.suffix or '<none>'}")
    candidates = _load_usd_skeleton_candidates(path)
    return ExternalSkeletonChoicesResult(str(path), tuple(candidate.choice for candidate in candidates))


def external_skeleton_backend_available(suffix: str) -> tuple[bool, str]:
    suffix = suffix.lower()
    if suffix == ".fbx":
        try:
            from . import _ufbx  # noqa: F401
        except ImportError:
            return False, "Bundled ufbx FBX backend is not available."
        return True, ""
    if suffix in SUPPORTED_USD_SKELETON_SUFFIXES:
        if suffix in TEXT_USD_SKELETON_SUFFIXES:
            return True, ""
        try:
            import pxr  # noqa: F401
        except ImportError:
            return False, "OpenUSD Python module 'pxr' is not available."
        return True, ""
    return False, "Unsupported skeleton format."


def _load_fbx_skeleton_for_preview(path: Path):
    try:
        return load_fbx_skeleton(str(path))
    except FbxImportError as exc:
        raise WindPreviewError(str(exc)) from exc


def _load_usd_skeleton_for_preview(path: Path, *, skeleton_index: int | None):
    candidates = _load_usd_skeleton_candidates(path)
    if not candidates:
        raise WindPreviewError(f"external_skeleton_not_found: {path}")
    if skeleton_index is None:
        if len(candidates) == 1:
            return candidates[0].joints
        raise WindPreviewError(
            "external_skeleton_multiple_skeletons: choose a Skeleton prim before loading."
        )
    for candidate in candidates:
        if candidate.choice.index == skeleton_index:
            return candidate.joints
    raise WindPreviewError(f"external_skeleton_not_found: Skeleton index {skeleton_index} was not found in {path}.")


def _load_usd_skeleton_candidates(path: Path) -> tuple[_UsdSkeletonCandidate, ...]:
    try:
        from pxr import Usd, UsdSkel
    except ImportError as exc:
        if path.suffix.lower() in TEXT_USD_SKELETON_SUFFIXES:
            return _load_text_usda_skeleton_candidates(path)
        raise WindPreviewError("external_skeleton_backend_unavailable: OpenUSD Python module 'pxr' is not available.") from exc
    stage = Usd.Stage.Open(str(path))
    if stage is None:
        raise WindPreviewError(f"external_skeleton_usd_open_failed: {path}")
    skeleton_prims = [prim for prim in stage.Traverse() if prim.IsA(UsdSkel.Skeleton)]
    candidates: list[_UsdSkeletonCandidate] = []
    for prim in skeleton_prims:
        joints = _joints_from_usd_skeleton(UsdSkel.Skeleton(prim))
        if not joints:
            continue
        index = len(candidates)
        prim_path = _usd_prim_path(prim, index)
        candidates.append(
            _UsdSkeletonCandidate(
                choice=ExternalSkeletonChoice(
                    index=index,
                    prim_path=prim_path,
                    name=_usd_prim_name(prim, prim_path),
                    joint_count=len(joints),
                ),
                joints=joints,
            )
        )
    if not candidates:
        raise WindPreviewError(f"external_skeleton_not_found: {path}")
    return tuple(candidates)


def _load_text_usda_skeleton_candidates(path: Path) -> tuple[_UsdSkeletonCandidate, ...]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise WindPreviewError(
            "external_skeleton_backend_unavailable: OpenUSD Python module 'pxr' is required for binary USD files."
        ) from exc
    if not text.lstrip().startswith("#usda"):
        raise WindPreviewError(
            "external_skeleton_backend_unavailable: OpenUSD Python module 'pxr' is required for binary USD files."
        )
    candidates: list[_UsdSkeletonCandidate] = []
    for name, block in _text_usda_skeleton_blocks(text):
        joints = _parse_text_usda_skeleton_block(block)
        if not joints:
            continue
        index = len(candidates)
        prim_path = f"/{name}"
        candidates.append(
            _UsdSkeletonCandidate(
                choice=ExternalSkeletonChoice(index=index, prim_path=prim_path, name=name, joint_count=len(joints)),
                joints=joints,
            )
        )
    if not candidates:
        raise WindPreviewError(f"external_skeleton_not_found: {path}")
    return tuple(candidates)


def _text_usda_skeleton_blocks(text: str) -> tuple[tuple[str, str], ...]:
    blocks: list[tuple[str, str]] = []
    for match in re.finditer(r'\bdef\s+Skeleton\s+"([^"]+)"', text):
        opening = text.find("{", match.end())
        if opening < 0:
            continue
        closing = _find_matching_brace(text, opening)
        if closing > opening:
            blocks.append((match.group(1), text[opening + 1 : closing]))
    return tuple(blocks)


def _parse_text_usda_skeleton_block(block: str) -> tuple[Joint, ...]:
    joint_paths = tuple(_parse_usda_string_array(_extract_usda_array(block, "joints")))
    if not joint_paths:
        return ()
    transforms_payload = _extract_usda_array(block, "bindTransforms") or _extract_usda_array(block, "restTransforms")
    positions = _parse_usda_matrix_translations(transforms_payload)
    if len(positions) != len(joint_paths):
        positions = tuple(Vector3(0.0, 0.0, 0.0) for _joint in joint_paths)
    all_paths = set(joint_paths)
    return tuple(
        Joint(
            name=joint_path,
            source_id=index,
            parent=_usd_joint_parent(joint_path, all_paths),
            bind_transform=Matrix4d.from_translation(positions[index]),
            rest_transform=Matrix4d.from_translation(positions[index]),
        )
        for index, joint_path in enumerate(joint_paths)
    )


def _extract_usda_array(block: str, attr_name: str) -> str:
    match = re.search(rf"\b(?:uniform\s+)?(?:token|matrix4d)\[\]\s+{re.escape(attr_name)}\s*=", block)
    if match is None:
        return ""
    opening = block.find("[", match.end())
    if opening < 0:
        return ""
    closing = _find_matching_square_bracket(block, opening)
    return block[opening + 1 : closing] if closing > opening else ""


def _find_matching_square_bracket(text: str, opening: int) -> int:
    return _find_matching_delimiter(text, opening, "[", "]")


def _find_matching_brace(text: str, opening: int) -> int:
    return _find_matching_delimiter(text, opening, "{", "}")


def _find_matching_delimiter(text: str, opening: int, open_char: str, close_char: str) -> int:
    depth = 0
    in_string = False
    escaped = False
    for index in range(opening, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return index
    return -1


def _parse_usda_string_array(payload: str) -> tuple[str, ...]:
    values = []
    for match in re.finditer(r'"((?:[^"\\]|\\.)*)"', payload):
        values.append(match.group(1).replace(r"\"", '"').replace(r"\\", "\\"))
    return tuple(values)


def _parse_usda_matrix_translations(payload: str) -> tuple[Vector3, ...]:
    if not payload:
        return ()
    pattern = re.compile(
        rf"\(\s*\(([^()]*)\)\s*,\s*\(([^()]*)\)\s*,\s*\(([^()]*)\)\s*,\s*\(([^()]*)\)\s*\)"
    )
    translations: list[Vector3] = []
    for match in pattern.finditer(payload):
        row = _parse_usda_number_row(match.group(4))
        if len(row) >= 3:
            translations.append(Vector3(row[0], row[1], row[2]))
    return tuple(translations)


def _parse_usda_number_row(payload: str) -> tuple[float, ...]:
    return tuple(float(value) for value in re.findall(_USD_NUMBER, payload))


def _usd_prim_path(prim, fallback_index: int) -> str:
    try:
        return str(prim.GetPath())
    except Exception:
        return f"/Skeleton_{fallback_index}"


def _usd_prim_name(prim, prim_path: str) -> str:
    try:
        name = str(prim.GetName())
        if name:
            return name
    except Exception:
        pass
    return prim_path.rsplit("/", 1)[-1] or prim_path


def _joints_from_usd_skeleton(skeleton) -> tuple[Joint, ...]:
    joint_paths = tuple(str(joint) for joint in (skeleton.GetJointsAttr().Get() or ()))
    if not joint_paths:
        return ()
    transforms = tuple(skeleton.GetBindTransformsAttr().Get() or ())
    accumulate_parent = False
    if len(transforms) != len(joint_paths):
        transforms = tuple(skeleton.GetRestTransformsAttr().Get() or ())
        accumulate_parent = True
    if len(transforms) != len(joint_paths):
        raise WindPreviewError(
            "external_skeleton_missing_joint_transforms: "
            f"expected {len(joint_paths)} bind or rest transforms, found {len(transforms)}"
        )
    positions = _usd_joint_positions(joint_paths, transforms, accumulate_parent=accumulate_parent)
    return tuple(
        Joint(
            name=joint_path,
            source_id=index,
            parent=_usd_joint_parent(joint_path, set(joint_paths)),
            bind_transform=Matrix4d.from_translation(positions[index]),
            rest_transform=Matrix4d.from_translation(positions[index]),
        )
        for index, joint_path in enumerate(joint_paths)
    )


def _usd_joint_positions(
    joint_paths: tuple[str, ...],
    transforms: tuple[object, ...],
    *,
    accumulate_parent: bool,
) -> tuple[Vector3, ...]:
    positions_by_path: dict[str, Vector3] = {}
    all_paths = set(joint_paths)
    positions: list[Vector3] = []
    for joint_path, transform in zip(joint_paths, transforms):
        local = _usd_transform_translation(transform)
        parent_path = _usd_joint_parent(joint_path, all_paths)
        parent = positions_by_path.get(parent_path) if accumulate_parent and parent_path is not None else None
        position = Vector3(
            local.x + (parent.x if parent is not None else 0.0),
            local.y + (parent.y if parent is not None else 0.0),
            local.z + (parent.z if parent is not None else 0.0),
        )
        positions_by_path[joint_path] = position
        positions.append(position)
    return tuple(positions)


def _usd_joint_parent(joint_path: str, all_paths: set[str]) -> str | None:
    parts = joint_path.rsplit("/", 1)
    if len(parts) != 2:
        return None
    parent = parts[0]
    return parent if parent in all_paths else None


def _usd_transform_translation(transform: object) -> Vector3:
    if isinstance(transform, Matrix4d):
        return transform.translation
    try:
        translation = transform.ExtractTranslation()
        return Vector3(float(translation[0]), float(translation[1]), float(translation[2]))
    except Exception:
        pass
    try:
        row = transform[3]
        return Vector3(float(row[0]), float(row[1]), float(row[2]))
    except Exception as exc:
        raise WindPreviewError(
            f"external_skeleton_invalid_joint_transform: unsupported transform value {type(transform).__name__}"
        ) from exc


def _validate_unique_joint_names(skeleton) -> None:
    names = [joint.name for joint in skeleton]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise WindPreviewError("external_skeleton_duplicate_joint_name: " + ", ".join(duplicates))
