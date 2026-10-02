"""External skeleton loading for Wind Preview."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from pathlib import Path

from .fbx_adapter import FbxImportError, FbxSkeletalPreview, load_fbx_skeletal_preview
from .models import DynamicWindData, ExportMetadata, Joint, Matrix4d, Quaternion, TreeAsset, Vector3
from .wind_preview_service import WindPreviewError, WindPreviewResult
from .wind_viewport_scene import build_auto_wind_viewport_data, build_wind_viewport_groups, build_wind_viewport_scene
from .viewport_scene import ViewportBoneSegment, ViewportBounds, ViewportScene, transformed_draw_bounds


SUPPORTED_USD_SKELETON_SUFFIXES = {".usd", ".usda", ".usdc"}
TEXT_USD_SKELETON_SUFFIXES = {".usd", ".usda"}
_USD_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_DISPLAY_UNIT_TO_METERS = {"mm": 0.001, "cm": 0.01, "m": 1.0}
_VERTICAL_EPSILON = 1.0e-4
_UE58_INVALID_OBJECT_NAME_CHARACTERS = "\"' ,/.:|&!~\n\r\t@#(){}[]=;^%$`"
_UE58_RESERVED_OBJECT_NAMES = frozenset({
    "none", "con", "prn", "aux", "nul", "com1", "com2", "com3", "com4", "com5",
    "com6", "com7", "com8", "com9", "lpt1", "lpt2", "lpt3", "lpt4", "lpt5",
    "lpt6", "lpt7", "lpt8", "lpt9",
})


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


def external_vertical_bone_names(skeleton: tuple[Joint, ...], source_up_axis: str) -> tuple[str, ...]:
    """Return joints whose bind-pose +X is parallel to the selected up axis."""
    up_axis = _display_up_axis(source_up_axis)
    names: list[str] = []
    for joint in skeleton:
        forward = _matrix_axis(joint.bind_transform, 0)
        length_squared = _dot_vector(forward, forward)
        if length_squared <= _VERTICAL_EPSILON * _VERTICAL_EPSILON:
            continue
        vertical = _axis_value(forward, up_axis)
        lateral_squared = length_squared - vertical * vertical
        if lateral_squared <= length_squared * _VERTICAL_EPSILON * _VERTICAL_EPSILON:
            names.append(joint.name)
    return tuple(names)


def transform_external_skeleton_scene(
    scene: ViewportScene,
    *,
    source_unit: str,
    preview_unit: str,
    source_up_axis: str,
    preview_up_axis: str,
) -> ViewportScene:
    """Return a display-only transformed external-skeleton scene."""
    scale = _display_unit_scale(source_unit, preview_unit)
    source_up = _display_up_axis(source_up_axis)
    preview_up = _display_up_axis(preview_up_axis)

    def transform(point: Vector3) -> Vector3:
        return _transform_display_point(point, scale, source_up, preview_up)

    axis_rotation = _display_axis_rotation(source_up, preview_up)
    draw_calls = tuple(
        replace(
            draw,
            translate=transform(draw.translate),
            orientation=_multiply_quaternions(axis_rotation, draw.orientation),
            scale=Vector3(draw.scale.x * scale, draw.scale.y * scale, draw.scale.z * scale),
            explode_direction=_transform_display_direction(draw.explode_direction, source_up, preview_up),
        )
        for draw in scene.draw_calls
    )

    bone_segments = tuple(
        ViewportBoneSegment(
            segment_id=segment.segment_id,
            parent_token=segment.parent_token,
            child_token=segment.child_token,
            start=transform(segment.start),
            end=transform(segment.end),
            color=segment.color,
            selected=segment.selected,
            selectable_id=segment.selectable_id,
            explode_direction=_transform_display_direction(segment.explode_direction, source_up, preview_up),
        )
        for segment in scene.bone_segments
    )
    transformed_bounds = transformed_draw_bounds(scene.mesh_batches, draw_calls) if draw_calls else None
    return ViewportScene(
        scene_id=scene.scene_id,
        mesh_batches=scene.mesh_batches,
        draw_calls=draw_calls,
        bounds=_transformed_external_bounds(scene.bounds, bone_segments, transform, transformed_bounds),
        stats=scene.stats,
        bone_segments=bone_segments,
        markers=tuple(replace(marker, position=transform(marker.position)) for marker in scene.markers),
        labels=tuple(replace(label, position=transform(label.position)) for label in scene.labels),
        grid_origin=transform(scene.grid_origin) if scene.grid_origin is not None else None,
    )


def prepare_external_dynamic_wind_export(
    preview: WindPreviewResult,
    dynamic_wind: DynamicWindData,
) -> DynamicWindData:
    """Validate JSON against the RefSkeleton-shaped external preview model."""
    from .dynamic_wind import validate_dynamic_wind_data

    try:
        validate_dynamic_wind_data(
            dynamic_wind,
            skeleton=preview.source_model.skeleton,
            require_linear_groups=True,
        )
    except ValueError as exc:
        raise WindPreviewError(str(exc)) from exc
    return dynamic_wind


def _display_unit_scale(source_unit: str, preview_unit: str) -> float:
    try:
        return _DISPLAY_UNIT_TO_METERS[source_unit] / _DISPLAY_UNIT_TO_METERS[preview_unit]
    except KeyError as exc:
        raise ValueError(f"Unsupported display unit: {exc.args[0]}") from exc


def _display_up_axis(value: str) -> str:
    axis = value.upper()
    if axis not in {"Y", "Z"}:
        raise ValueError(f"Unsupported display up axis: {value}")
    return axis


def _transform_display_point(point: Vector3, scale: float, source_up: str, preview_up: str) -> Vector3:
    if source_up == preview_up:
        return Vector3(point.x * scale, point.y * scale, point.z * scale)
    if source_up == "Y":
        return Vector3(point.x * scale, -point.z * scale, point.y * scale)
    return Vector3(point.x * scale, point.z * scale, -point.y * scale)


def _transform_display_direction(value: Vector3, source_up: str, preview_up: str) -> Vector3:
    return _transform_display_point(value, 1.0, source_up, preview_up)


def _display_axis_rotation(source_up: str, preview_up: str) -> Quaternion:
    if source_up == preview_up:
        return Quaternion(1.0, 0.0, 0.0, 0.0)
    half = math.sqrt(0.5)
    return Quaternion(half, half if source_up == "Y" else -half, 0.0, 0.0)


def _multiply_quaternions(left: Quaternion, right: Quaternion) -> Quaternion:
    return Quaternion(
        left.real * right.real - left.i * right.i - left.j * right.j - left.k * right.k,
        left.real * right.i + left.i * right.real + left.j * right.k - left.k * right.j,
        left.real * right.j - left.i * right.k + left.j * right.real + left.k * right.i,
        left.real * right.k + left.i * right.j - left.j * right.i + left.k * right.real,
    )


def _transformed_external_bounds(
    fallback: ViewportBounds,
    bone_segments: tuple[ViewportBoneSegment, ...],
    transform,
    mesh_bounds: ViewportBounds | None,
) -> ViewportBounds:
    points = tuple(
        point
        for segment in bone_segments
        for point in (segment.start, segment.end)
    )
    if mesh_bounds is not None:
        points += _bounds_corners(mesh_bounds)
    if not points:
        points = tuple(transform(point) for point in _bounds_corners(fallback))
    return ViewportBounds(
        min_point=Vector3(min(point.x for point in points), min(point.y for point in points), min(point.z for point in points)),
        max_point=Vector3(max(point.x for point in points), max(point.y for point in points), max(point.z for point in points)),
    )


def _bounds_corners(bounds: ViewportBounds) -> tuple[Vector3, ...]:
    low, high = bounds.min_point, bounds.max_point
    return tuple(
        Vector3(x, y, z)
        for x in (low.x, high.x)
        for y in (low.y, high.y)
        for z in (low.z, high.z)
    )


def _axis_value(value: Vector3, axis: str) -> float:
    return value.y if axis == "Y" else value.z


def load_external_skeleton_preview(request: ExternalSkeletonPreviewRequest) -> WindPreviewResult:
    input_path = request.input_path.strip()
    if not input_path:
        raise WindPreviewError("external_skeleton_missing_path: Select an FBX or USD skeleton file.")
    path = Path(input_path)
    suffix = path.suffix.lower()
    base_mesh = None
    diagnostics = ()
    display_source_unit = "m"
    display_source_up_axis = "Y"
    if suffix == ".fbx":
        fbx_preview = _load_fbx_skeleton_for_preview(path)
        skeleton = _unreal_fbx_ref_skeleton(fbx_preview.skeleton)
        base_mesh = fbx_preview.mesh
        diagnostics = fbx_preview.diagnostics
        # UE 5.8 Ufbx normalizes its reference skeleton to cm, left-handed Z-up.
        display_source_unit = "cm"
        display_source_up_axis = "Z"
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
        base_mesh=base_mesh,
        skeleton=skeleton,
        assembly_parts=(),
        prototypes=(),
    )
    dynamic_wind = build_auto_wind_viewport_data(model.skeleton, group_count=max(1, min(10, int(request.group_count))))
    groups = build_wind_viewport_groups(dynamic_wind, label_kind="Hierarchy level")
    viewport_scene = build_wind_viewport_scene(model, dynamic_wind)
    return WindPreviewResult(
        input_path=str(path),
        source_model=replace(model, base_mesh=None),
        dynamic_wind=dynamic_wind,
        groups=groups,
        diagnostics=diagnostics,
        viewport_scene=viewport_scene,
        xml_groups_available=False,
        preferred_grouping_mode="auto",
        display_source_unit=display_source_unit,
        display_source_up_axis=display_source_up_axis,
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


def _load_fbx_skeleton_for_preview(path: Path) -> FbxSkeletalPreview:
    try:
        return load_fbx_skeletal_preview(str(path))
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
    for index, (name, block) in enumerate(_text_usda_skeleton_blocks(text)):
        try:
            joints = _parse_text_usda_skeleton_block(block)
        except WindPreviewError:
            continue
        if not joints:
            continue
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
    bind_transforms = _parse_usda_matrix_array(_extract_usda_array(block, "bindTransforms"))
    rest_transforms = _parse_usda_matrix_array(_extract_usda_array(block, "restTransforms"))
    return _unreal_usd_ref_skeleton(joint_paths, bind_transforms, rest_transforms)


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


def _parse_usda_matrix_array(payload: str) -> tuple[Matrix4d, ...]:
    if not payload:
        return ()
    pattern = re.compile(
        rf"\(\s*\(([^()]*)\)\s*,\s*\(([^()]*)\)\s*,\s*\(([^()]*)\)\s*,\s*\(([^()]*)\)\s*\)"
    )
    transforms: list[Matrix4d] = []
    for match in pattern.finditer(payload):
        rows = tuple(_parse_usda_number_row(match.group(index)) for index in range(1, 5))
        if any(len(row) != 4 for row in rows):
            raise WindPreviewError("external_skeleton_invalid_joint_transform: USDA matrix must have four numeric rows.")
        transforms.append(Matrix4d(rows=rows))
    return tuple(transforms)


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
    bind_transforms = tuple(_matrix_from_usd_transform(value) for value in (skeleton.GetBindTransformsAttr().Get() or ()))
    rest_transforms = tuple(_matrix_from_usd_transform(value) for value in (skeleton.GetRestTransformsAttr().Get() or ()))
    return _unreal_usd_ref_skeleton(joint_paths, bind_transforms, rest_transforms)


def _usd_joint_parent(joint_path: str, all_paths: set[str]) -> str | None:
    parts = joint_path.rsplit("/", 1)
    if len(parts) != 2:
        return None
    parent = parts[0]
    return parent if parent in all_paths else None


def _matrix_from_usd_transform(transform: object) -> Matrix4d:
    if isinstance(transform, Matrix4d):
        return transform
    try:
        rows = tuple(
            tuple(float(transform[row][column]) for column in range(4))
            for row in range(4)
        )
        return Matrix4d(rows=rows)
    except Exception:
        pass
    try:
        translation = transform.ExtractTranslation()
        return Matrix4d.from_translation(Vector3(float(translation[0]), float(translation[1]), float(translation[2])))
    except Exception as exc:
        raise WindPreviewError(
            f"external_skeleton_invalid_joint_transform: unsupported transform value {type(transform).__name__}"
        ) from exc


def _validate_unique_joint_names(skeleton) -> None:
    names = [joint.name for joint in skeleton]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise WindPreviewError("external_skeleton_duplicate_joint_name: " + ", ".join(duplicates))


def _unreal_usd_ref_skeleton(
    joint_paths: tuple[str, ...],
    bind_transforms: tuple[Matrix4d, ...],
    rest_transforms: tuple[Matrix4d, ...],
) -> tuple[Joint, ...]:
    """Mirror UE 5.8 UsdSkel ref-skeleton naming, roots, and bind-pose choice."""
    if len(set(joint_paths)) != len(joint_paths):
        raise WindPreviewError("external_usd_duplicate_joint_path: USD Skeleton joints must be unique.")
    if bind_transforms and len(bind_transforms) != len(joint_paths):
        raise WindPreviewError(
            f"external_skeleton_missing_joint_transforms: expected {len(joint_paths)} bind transforms, found {len(bind_transforms)}"
        )
    if rest_transforms and len(rest_transforms) != len(joint_paths):
        raise WindPreviewError(
            f"external_skeleton_missing_joint_transforms: expected {len(joint_paths)} rest transforms, found {len(rest_transforms)}"
        )
    if not bind_transforms and not rest_transforms:
        raise WindPreviewError(f"external_skeleton_missing_joint_transforms: expected {len(joint_paths)} bind or rest transforms, found 0")

    paths = set(joint_paths)
    parent_by_path = {path: _usd_joint_parent(path, paths) for path in joint_paths}
    _require_parent_first_joint_paths(joint_paths, parent_by_path)
    if not bind_transforms:
        absolute_by_path: dict[str, Matrix4d] = {}
        for path, local in zip(joint_paths, rest_transforms):
            parent = parent_by_path[path]
            absolute_by_path[path] = local if parent is None else _multiply_matrices(local, absolute_by_path[parent])
        bind_transforms = tuple(absolute_by_path[path] for path in joint_paths)
    if not rest_transforms:
        bind_by_path = dict(zip(joint_paths, bind_transforms))
        rest_transforms = tuple(
            bind if parent_by_path[path] is None else _multiply_matrices(bind, _inverse_affine_matrix(bind_by_path[parent_by_path[path]]))
            for path, bind in zip(joint_paths, bind_transforms)
        )

    names_by_path = {path: _usd_joint_basename(path) for path in joint_paths}
    target_names = tuple(names_by_path[path] for path in joint_paths)
    duplicates = sorted({name for name in target_names if target_names.count(name) > 1})
    if duplicates:
        raise WindPreviewError("external_usd_unreal_joint_name_collision: " + ", ".join(duplicates))
    joints = [
        Joint(
            name=names_by_path[path],
            source_id=index,
            parent=names_by_path[parent_by_path[path]] if parent_by_path[path] is not None else None,
            bind_transform=bind,
            rest_transform=rest,
        )
        for index, (path, bind, rest) in enumerate(zip(joint_paths, bind_transforms, rest_transforms))
    ]
    roots = [joint for joint in joints if joint.parent is None]
    if len(roots) <= 1:
        return tuple(joints)

    root_name = _unreal_usd_unique_name("Root", set(target_names))
    synthetic_root = Joint(name=root_name, source_id=-1, bind_transform=Matrix4d.identity(), rest_transform=Matrix4d.identity())
    return (synthetic_root, *(replace(joint, parent=root_name) if joint.parent is None else joint for joint in joints))


def _require_parent_first_joint_paths(joint_paths: tuple[str, ...], parent_by_path: dict[str, str | None]) -> None:
    seen: set[str] = set()
    for path in joint_paths:
        parent = parent_by_path[path]
        if parent is not None and parent not in seen:
            raise WindPreviewError(f"external_usd_joint_order: parent {parent!r} must precede child {path!r}.")
        seen.add(path)


def _usd_joint_basename(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if not name:
        raise WindPreviewError(f"external_usd_invalid_joint_path: {path!r}")
    return name


def _unreal_usd_unique_name(name: str, used_names: set[str]) -> str:
    if name not in used_names:
        return name
    base = re.sub(r"_\d+$", "", name)
    if base not in used_names:
        return base
    suffix = 0
    while f"{base}_{suffix}" in used_names:
        suffix += 1
    return f"{base}_{suffix}"


def _unreal_fbx_ref_skeleton(skeleton: tuple[Joint, ...]) -> tuple[Joint, ...]:
    """Apply UE 5.8 default Interchange joint-name rules without changing transforms."""
    source_names = tuple(joint.name for joint in skeleton)
    target_names = _unreal_fbx_joint_names(source_names)
    name_by_source = dict(zip(source_names, target_names))
    return tuple(
        replace(joint, name=name_by_source[joint.name], parent=name_by_source.get(joint.parent) if joint.parent is not None else None)
        for joint in skeleton
    )


def _unreal_fbx_joint_names(source_names: tuple[str, ...]) -> tuple[str, ...]:
    if len(set(source_names)) != len(source_names):
        raise WindPreviewError("external_skeleton_duplicate_joint_name: FBX source joints must be unique.")
    used_names: set[str] = set()
    names: list[str] = []
    for source_name in source_names:
        base = _unreal_fbx_sanitize_joint_name(source_name)
        name = base
        suffix = 1
        while name in used_names:
            name = f"{base}{suffix}"
            suffix += 1
        used_names.add(name)
        names.append(name)
    casefolded = [name.casefold() for name in names]
    collisions = sorted({name for name in names if casefolded.count(name.casefold()) > 1})
    if collisions:
        raise WindPreviewError("external_fbx_unreal_joint_name_collision: " + ", ".join(collisions))
    return tuple(names)


def _unreal_fbx_sanitize_joint_name(value: str) -> str:
    name = value.rsplit(":", 1)[-1]
    name = name.replace(" ", "-").replace("+", "_")
    for character in _UE58_INVALID_OBJECT_NAME_CHARACTERS:
        name = name.replace(character, "_")
    if not name or name.casefold() in _UE58_RESERVED_OBJECT_NAMES:
        name = "Null"
    if re.fullmatch(r"_\d+", name):
        name = "Null" + name
    return name


def _matrix_axis(matrix: Matrix4d, index: int) -> Vector3:
    row = matrix.rows[index]
    return Vector3(row[0], row[1], row[2])


def _dot_vector(left: Vector3, right: Vector3) -> float:
    return left.x * right.x + left.y * right.y + left.z * right.z


def _multiply_matrices(left: Matrix4d, right: Matrix4d) -> Matrix4d:
    return Matrix4d(rows=tuple(
        tuple(sum(left.rows[row][index] * right.rows[index][column] for index in range(4)) for column in range(4))
        for row in range(4)
    ))


def _inverse_affine_matrix(matrix: Matrix4d) -> Matrix4d:
    rows = matrix.rows
    if any(abs(rows[row][3]) > 1.0e-8 for row in range(3)) or abs(rows[3][3] - 1.0) > 1.0e-8:
        raise WindPreviewError("external_skeleton_invalid_joint_transform: expected an affine joint transform.")
    a, b, c = rows[0][:3]
    d, e, f = rows[1][:3]
    g, h, i = rows[2][:3]
    determinant = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if not math.isfinite(determinant) or abs(determinant) <= 1.0e-12:
        raise WindPreviewError("external_skeleton_noninvertible_bind_transform: joint bind transform cannot be inverted.")
    inverse = (
        ((e * i - f * h) / determinant, (c * h - b * i) / determinant, (b * f - c * e) / determinant),
        ((f * g - d * i) / determinant, (a * i - c * g) / determinant, (c * d - a * f) / determinant),
        ((d * h - e * g) / determinant, (b * g - a * h) / determinant, (a * e - b * d) / determinant),
    )
    translate = rows[3][:3]
    inverse_translate = tuple(-sum(translate[index] * inverse[index][column] for index in range(3)) for column in range(3))
    return Matrix4d(rows=(
        (*inverse[0], 0.0),
        (*inverse[1], 0.0),
        (*inverse[2], 0.0),
        (*inverse_translate, 1.0),
    ))
