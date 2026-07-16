"""Diagnostic fracture preview data generation.

Layer: application/domain boundary.

Preview uses the same `FracturePlan` contract as export, but emits lightweight
geometry and stable colors for inspection instead of authoring USD.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING

from .canonical_loader import load_source_tree_model
from .fracture_collision import (
    CollisionMeshSet,
    FractureCollisionSettings,
    build_fracture_collision_mesh_sets,
    build_fracture_collision_meshes,
    collision_render_mesh_name,
    validated_collision_settings,
)
from .fracture_geometry import build_cap_source_context, prepare_fracture_geometry, slice_mesh_faces
from .fracture_service import (
    FractureError,
    FracturePiece,
    FracturePlan,
    FractureSettings,
    _FracturePlanCache,
    _build_fracture_plan_cache,
    plan_fracture,
)
from .geometry_buffers import geometry_buffer_from_mesh, geometry_buffer_to_mesh
from .job_control import throw_if_cancelled
from .mesh_pruning import select_large_connected_face_indices
from .models import (
    CanonicalTreeModel,
    Color4,
    ConversionMode,
    ConversionRequest,
    CpuProfile,
    ExportMetadata,
    GeometryBuffer,
    InstanceBinding,
    Joint,
    MaterialPolicy,
    Matrix4d,
    MeshData,
    MeshSection,
    OutputMode,
    Prototype,
    PrototypeIdentity,
    Quaternion,
    RepeatedPartInstance,
    ValidationIssue,
    Vector2,
    Vector3,
)
from .output_resolution import render_output_file_name
from .qem_simplification import QemSimplificationError, simplify_geometry_buffer_qem

if TYPE_CHECKING:
    from .viewport_scene import ViewportScene


DEFAULT_FRACTURE_PREVIEW_POLYCOUNT = 1_000_000
DEFAULT_FRACTURE_PREVIEW_BASE_PRIORITY = 0.33
DEFAULT_FRACTURE_PREVIEW_BRANCH_PRUNE_AGGRESSION = 0.0
DEFAULT_FRACTURE_PREVIEW_BASE_FACE_BUDGET = 10_000_000
DEFAULT_FRACTURE_PREVIEW_PROTOTYPE_FACE_BUDGET = 2_000
FRACTURE_PREVIEW_SOURCE_CACHE_SCHEMA_VERSION = 8
_PREVIEW_SOURCE_MEMORY_CACHE: tuple[
    Path,
    tuple[object, CanonicalTreeModel, tuple[ValidationIssue, ...], _FracturePlanCache],
] | None = None


@dataclass(frozen=True)
class FracturePreviewSettings:
    fracture: FractureSettings = field(default_factory=FractureSettings)
    collision: FractureCollisionSettings = field(default_factory=FractureCollisionSettings)
    final_polycount: int = DEFAULT_FRACTURE_PREVIEW_POLYCOUNT
    base_mesh_priority: float = DEFAULT_FRACTURE_PREVIEW_BASE_PRIORITY
    branch_prune_aggression: float = DEFAULT_FRACTURE_PREVIEW_BRANCH_PRUNE_AGGRESSION
    max_base_faces_per_piece: int = DEFAULT_FRACTURE_PREVIEW_BASE_FACE_BUDGET
    max_prototype_faces: int = DEFAULT_FRACTURE_PREVIEW_PROTOTYPE_FACE_BUDGET


@dataclass(frozen=True)
class FracturePreviewSourceRequest:
    input_path: str
    output_path: str = ""
    output_directory: str = ""
    output_naming_template: str | None = None
    cpu_profile: CpuProfile = CpuProfile.BALANCED

    @classmethod
    def from_conversion_request(cls, request: ConversionRequest) -> "FracturePreviewSourceRequest":
        return cls(
            input_path=_single_conversion_input_path(request),
            output_path=request.output_path or "",
            output_directory=request.output_directory or "",
            output_naming_template=request.output_naming_template,
            cpu_profile=request.cpu_profile,
        )


@dataclass(frozen=True)
class FracturePreviewPiece:
    piece: FracturePiece
    color: Color4
    base_mesh: GeometryBuffer


@dataclass(frozen=True)
class FracturePreviewPrototype:
    source_key: str
    source_name: str
    mesh: GeometryBuffer


@dataclass(frozen=True)
class FracturePreviewInstance:
    name: str
    piece_index: int
    prototype_key: str
    position: Vector3
    orientation: Quaternion
    scale: Vector3
    color: Color4


@dataclass(frozen=True)
class FracturePreviewBoneSegment:
    parent_joint_token: str
    child_joint_token: str
    parent_position: Vector3
    child_position: Vector3
    is_selected_cut: bool = False
    color: Color4 = Color4(0.64, 0.82, 0.95, 1.0)
    selectable: bool = True


@dataclass(frozen=True)
class FracturePreviewResult:
    plan: FracturePlan
    pieces: tuple[FracturePreviewPiece, ...]
    prototypes: dict[str, FracturePreviewPrototype]
    instances: tuple[FracturePreviewInstance, ...]
    diagnostics: tuple[ValidationIssue, ...]
    bone_segments: tuple[FracturePreviewBoneSegment, ...] = ()
    collision_meshes: tuple[GeometryBuffer, ...] = ()
    collision_piece_indices: tuple[int, ...] = ()
    collision_opacity: float = 0.25
    viewport_scene: "ViewportScene | None" = None


def prepare_fracture_preview_source_request(
    *,
    input_path: str,
    output_path: str = "",
    output_directory: str = "",
    output_naming_template: str | None = None,
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
) -> FracturePreviewSourceRequest:
    if not input_path.strip():
        raise ValueError("Select a source XML file before previewing fracturing.")
    return FracturePreviewSourceRequest(
        input_path=input_path.strip(),
        output_path=output_path.strip(),
        output_directory=output_directory.strip(),
        output_naming_template=output_naming_template,
        cpu_profile=cpu_profile,
    )


def generate_fracture_preview_from_conversion_request(
    request: ConversionRequest,
    settings: FracturePreviewSettings | None = None,
    *,
    telemetry_callback=None,
    cancel_event=None,
    include_viewport_scene: bool = True,
) -> FracturePreviewResult:
    """Load source XML geometry and build a diagnostic fracture preview."""
    return generate_fracture_preview_from_source_request(
        FracturePreviewSourceRequest.from_conversion_request(request),
        settings,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
        include_viewport_scene=include_viewport_scene,
    )


def generate_fracture_preview_from_source_request(
    request: FracturePreviewSourceRequest,
    settings: FracturePreviewSettings | None = None,
    *,
    telemetry_callback=None,
    cancel_event=None,
    include_viewport_scene: bool = True,
) -> FracturePreviewResult:
    """Load source XML geometry and build a diagnostic fracture preview."""
    input_path = request.input_path.strip()
    if not input_path:
        raise FractureError("Fracture preview requires a source XML path.")
    preview_settings = _preview_settings(settings, _preview_output_stem(request, input_path))
    throw_if_cancelled(cancel_event)
    global _PREVIEW_SOURCE_MEMORY_CACHE
    source_cache_key = _preview_source_model_cache_path(input_path)
    cached_source = (
        _PREVIEW_SOURCE_MEMORY_CACHE[1]
        if _PREVIEW_SOURCE_MEMORY_CACHE is not None and _PREVIEW_SOURCE_MEMORY_CACHE[0] == source_cache_key
        else _read_preview_source_model_cache(input_path)
    )
    if cached_source is None:
        _report, source_model, source_diagnostics = load_source_tree_model(
            input_path,
            source_cache_enabled=False,
            telemetry_callback=telemetry_callback,
            cancel_event=cancel_event,
        )
        source_model = _slim_preview_source_model(source_model)
        analysis_cache = _build_fracture_plan_cache(source_model)
        _write_preview_source_model_cache(input_path, (_report, source_model, source_diagnostics, analysis_cache))
        cached_source = (_report, source_model, source_diagnostics, analysis_cache)
    else:
        _report, source_model, source_diagnostics, analysis_cache = cached_source
    _PREVIEW_SOURCE_MEMORY_CACHE = (source_cache_key, cached_source)
    result = generate_fracture_preview(
        source_model,
        preview_settings,
        include_viewport_scene=include_viewport_scene,
        analysis_cache=analysis_cache,
    )
    return replace(result, diagnostics=source_diagnostics + result.diagnostics)


def generate_fracture_preview(
    model: CanonicalTreeModel,
    settings: FracturePreviewSettings | None = None,
    *,
    include_viewport_scene: bool = True,
    analysis_cache: _FracturePlanCache | None = None,
) -> FracturePreviewResult:
    """Build lightweight diagnostic preview payloads from one tree model."""
    resolved_settings = settings or FracturePreviewSettings()
    _validate_preview_settings(resolved_settings)
    geometry = None
    if resolved_settings.fracture.noisy_cut_enabled:
        geometry = prepare_fracture_geometry(
            model,
            resolved_settings.fracture,
            analysis_cache=analysis_cache,
        )
        plan = geometry.plan
        geometry_pieces = geometry.pieces
    else:
        plan = plan_fracture(model, resolved_settings.fracture, analysis_cache=analysis_cache)
        geometry_pieces = None
    base_face_budgets = _base_face_budgets(model, plan, resolved_settings, geometry_pieces)
    prototype_budgets = _prototype_face_budgets(model, plan, resolved_settings, base_face_budgets)
    if geometry_pieces is None:
        cap_context = (
            build_cap_source_context(model.base_mesh)
            if resolved_settings.fracture.generate_caps and model.base_mesh is not None
            else None
        )
        pieces = tuple(
            _legacy_preview_piece(
                model,
                piece,
                base_face_budgets[piece.index],
                generate_caps=resolved_settings.fracture.generate_caps,
                branch_prune_aggression=resolved_settings.branch_prune_aggression,
                cap_context=cap_context,
            )
            for piece in plan.pieces
        )
    else:
        pieces = tuple(
            _preview_piece(
                geometry_piece,
                base_face_budgets[geometry_piece.piece.index],
                branch_prune_aggression=resolved_settings.branch_prune_aggression,
            )
            for geometry_piece in geometry_pieces
        )
    prototypes = _preview_prototypes(model, plan, prototype_budgets)
    instances = _preview_instances(model, pieces)
    bone_segments = _preview_bone_segments(model, resolved_settings.fracture, pieces)
    collision_settings = validated_collision_settings(resolved_settings.collision)
    collision_sets = tuple(
        CollisionMeshSet(
            piece_index=geometry_piece.piece.index,
            meshes=build_fracture_collision_meshes(
                replace(model, base_mesh=geometry_piece.base_mesh),
                replace(
                    geometry_piece.piece,
                    base_face_indices=tuple(range(len(geometry_piece.base_mesh.face_vertex_counts))),
                ),
                collision_settings,
                render_mesh_name=collision_render_mesh_name(geometry_piece.piece),
            ),
        )
        for geometry_piece in geometry_pieces
    ) if collision_settings.enabled and geometry_pieces is not None else (
        build_fracture_collision_mesh_sets(model, plan.pieces, collision_settings)
        if collision_settings.enabled
        else ()
    )
    collision_meshes = tuple(geometry_buffer_from_mesh(mesh) for mesh_set in collision_sets for mesh in mesh_set.meshes)
    collision_piece_indices = tuple(mesh_set.piece_index for mesh_set in collision_sets for _mesh in mesh_set.meshes)
    result = FracturePreviewResult(
        plan=plan,
        pieces=pieces,
        prototypes=prototypes,
        instances=instances,
        diagnostics=plan.diagnostics,
        bone_segments=bone_segments,
        collision_meshes=collision_meshes,
        collision_piece_indices=collision_piece_indices,
        collision_opacity=collision_settings.ghost_opacity,
    )
    if not include_viewport_scene:
        return result

    from .fracture_viewport_scene import build_fracture_viewport_scene

    return replace(result, viewport_scene=build_fracture_viewport_scene(result))


def _single_conversion_input_path(request: ConversionRequest) -> str:
    if len(request.input_paths) != 1:
        raise FractureError("Fracture preview requires exactly one input XML.")
    return request.input_paths[0]


def _preview_output_stem(request: FracturePreviewSourceRequest, input_path: str) -> str:
    if request.output_path:
        return Path(request.output_path).stem
    if request.output_directory:
        return Path(render_output_file_name(Path(input_path), request.output_naming_template)).stem
    return Path(input_path).stem


def _preview_settings(settings: FracturePreviewSettings | None, output_stem: str) -> FracturePreviewSettings:
    resolved_settings = settings or FracturePreviewSettings()
    return replace(
        resolved_settings,
        fracture=replace(resolved_settings.fracture, output_stem=output_stem),
    )


def _validate_preview_settings(settings: FracturePreviewSettings) -> None:
    if settings.final_polycount <= 0:
        raise FractureError("Fracture preview target polycount must be greater than zero.")
    if not 0.0 <= settings.base_mesh_priority <= 1.0:
        raise FractureError("Fracture preview base mesh priority must be between 0 and 1.")
    if not 0.0 <= settings.branch_prune_aggression <= 1.0:
        raise FractureError("Fracture preview branch prune aggression must be between 0 and 1.")
    if settings.max_base_faces_per_piece <= 0:
        raise FractureError("Fracture preview base face budget must be greater than zero.")
    if settings.max_prototype_faces <= 0:
        raise FractureError("Fracture preview prototype face budget must be greater than zero.")
    validated_collision_settings(settings.collision)


def _base_face_budgets(
    model: CanonicalTreeModel,
    plan: FracturePlan,
    settings: FracturePreviewSettings,
    geometry_pieces,
) -> dict[int, int]:
    if model.base_mesh is None:
        raise FractureError("Fracture preview requires a base mesh.")
    source_counts = (
        {
            geometry_piece.piece.index: len(geometry_piece.base_mesh.face_vertex_counts)
            for geometry_piece in geometry_pieces
        }
        if geometry_pieces is not None
        else {piece.index: len(piece.base_face_indices) for piece in plan.pieces}
    )
    if any(face_count <= 0 for face_count in source_counts.values()):
        raise FractureError("Fracture preview requires every fracture piece to keep base mesh faces.")
    has_repeated_parts = any(piece.repeated_part_indices for piece in plan.pieces)
    if has_repeated_parts:
        minimum_base_faces = len(source_counts)
        target_faces = max(minimum_base_faces, int(round(settings.final_polycount * settings.base_mesh_priority)))
    else:
        target_faces = settings.final_polycount
    return _proportional_face_budgets(
        source_counts,
        target_faces,
        max_faces_per_item=settings.max_base_faces_per_piece,
    )


def _preview_piece(
    geometry_piece,
    face_budget: int,
    *,
    branch_prune_aggression: float,
) -> FracturePreviewPiece:
    piece = geometry_piece.piece
    source_mesh = geometry_piece.base_mesh
    all_faces = tuple(range(len(source_mesh.face_vertex_counts)))
    pruned_faces = select_large_connected_face_indices(
        source_mesh,
        aggression=branch_prune_aggression,
        candidate_face_indices=all_faces,
    )
    mesh = slice_mesh_faces(
        source_mesh,
        pruned_faces or all_faces,
        name=f"{piece.name}_PreviewBase",
    )
    return FracturePreviewPiece(
        piece=piece,
        color=_piece_color(piece.index),
        base_mesh=_simplify_preview_mesh(mesh, face_budget, name=f"{piece.name}_PreviewBase"),
    )


def _legacy_preview_piece(
    model: CanonicalTreeModel,
    piece: FracturePiece,
    face_budget: int,
    *,
    generate_caps: bool,
    branch_prune_aggression: float,
    cap_context=None,
) -> FracturePreviewPiece:
    if model.base_mesh is None:
        raise FractureError("Fracture preview requires a base mesh.")
    pruned_faces = select_large_connected_face_indices(
        model.base_mesh,
        aggression=branch_prune_aggression,
        candidate_face_indices=piece.base_face_indices,
    )
    mesh = slice_mesh_faces(
        model.base_mesh,
        pruned_faces or piece.base_face_indices,
        name=f"{piece.name}_PreviewBase",
        generate_caps=generate_caps,
        cap_context=cap_context,
    )
    return FracturePreviewPiece(
        piece=piece,
        color=_piece_color(piece.index),
        base_mesh=_simplify_preview_mesh(mesh, face_budget, name=f"{piece.name}_PreviewBase"),
    )


def _preview_prototypes(
    model: CanonicalTreeModel,
    plan: FracturePlan,
    prototype_budgets: dict[str, int],
) -> dict[str, FracturePreviewPrototype]:
    prototypes_by_key = {prototype.source_key: prototype for prototype in model.prototypes}
    preview_prototypes: dict[str, FracturePreviewPrototype] = {}
    for source_key in sorted(prototype_budgets):
        prototype = prototypes_by_key.get(source_key)
        if prototype is None:
            raise FractureError(f"Fracture preview repeated part references missing prototype {source_key}.")
        preview_prototypes[source_key] = _preview_prototype(
            prototype,
            face_budget=prototype_budgets[source_key],
        )
    return preview_prototypes


def _preview_prototype(
    prototype: Prototype,
    *,
    face_budget: int,
) -> FracturePreviewPrototype:
    mesh = _prototype_mesh(prototype)
    preview_mesh = _simplify_preview_mesh(mesh, face_budget, name=f"{prototype.identity.prim_name}_Preview")
    return FracturePreviewPrototype(
        source_key=prototype.source_key,
        source_name=prototype.source_name,
        mesh=preview_mesh,
    )


def _simplify_preview_mesh(mesh: MeshData, target_triangle_count: int, *, name: str) -> GeometryBuffer:
    source = geometry_buffer_from_mesh(replace(mesh, name=name))
    try:
        return simplify_geometry_buffer_qem(source, target_triangle_count=target_triangle_count)
    except QemSimplificationError as exc:
        raise FractureError(f"Fracture Preview QEM simplification failed: {exc}") from exc


def _prototype_face_budgets(
    model: CanonicalTreeModel,
    plan: FracturePlan,
    settings: FracturePreviewSettings,
    base_budgets: dict[int, int],
) -> dict[str, int]:
    instance_counts = _prototype_instance_counts(model, plan)
    if not instance_counts:
        return {}

    prototype_meshes = _prototype_meshes_by_key(model, instance_counts)

    foliage_target = max(1, settings.final_polycount - sum(base_budgets.values()))
    logical_source_counts = {
        source_key: len(mesh.face_vertex_counts) * instance_counts[source_key]
        for source_key, mesh in prototype_meshes.items()
    }
    total_logical_source_faces = sum(logical_source_counts.values())
    if total_logical_source_faces <= foliage_target:
        return {
            source_key: min(len(mesh.face_vertex_counts), settings.max_prototype_faces)
            for source_key, mesh in prototype_meshes.items()
        }

    budgets: dict[str, int] = {}
    for source_key, mesh in prototype_meshes.items():
        source_face_count = len(mesh.face_vertex_counts)
        weighted_budget = round(source_face_count * foliage_target / total_logical_source_faces)
        budgets[source_key] = max(1, min(source_face_count, settings.max_prototype_faces, int(weighted_budget)))
    return budgets


def _prototype_instance_counts(
    model: CanonicalTreeModel,
    plan: FracturePlan,
) -> dict[str, int]:
    instance_counts: dict[str, int] = {}
    for piece in plan.pieces:
        for repeated_part_index in piece.repeated_part_indices:
            prototype_key = model.repeated_parts[repeated_part_index].prototype_key
            instance_counts[prototype_key] = instance_counts.get(prototype_key, 0) + 1
    return instance_counts


def _prototype_meshes_by_key(
    model: CanonicalTreeModel,
    instance_counts: dict[str, int],
) -> dict[str, MeshData]:
    prototypes_by_key = {prototype.source_key: prototype for prototype in model.prototypes}
    prototype_meshes: dict[str, MeshData] = {}
    for source_key in sorted(instance_counts):
        prototype = prototypes_by_key.get(source_key)
        if prototype is None:
            raise FractureError(f"Fracture preview repeated part references missing prototype {source_key}.")
        mesh = _prototype_mesh(prototype)
        if len(mesh.face_vertex_counts) <= 0:
            raise FractureError(f"Fracture preview prototype {prototype.identity.prim_name} has no faces.")
        prototype_meshes[source_key] = mesh
    return prototype_meshes


def _proportional_face_budgets(
    source_counts: dict[int, int],
    target_faces: int,
    *,
    max_faces_per_item: int,
) -> dict[int, int]:
    total_source_faces = sum(source_counts.values())
    if total_source_faces <= 0:
        return {key: 0 for key in source_counts}
    if total_source_faces <= target_faces:
        return {
            key: max(1, min(source_count, max_faces_per_item))
            for key, source_count in source_counts.items()
        }
    budgets: dict[int, int] = {}
    for key, source_count in source_counts.items():
        weighted_budget = round(source_count * target_faces / total_source_faces)
        budgets[key] = max(1, min(source_count, max_faces_per_item, int(weighted_budget)))
    return budgets


def _preview_instances(
    model: CanonicalTreeModel,
    pieces: tuple[FracturePreviewPiece, ...],
) -> tuple[FracturePreviewInstance, ...]:
    instances: list[FracturePreviewInstance] = []
    for preview_piece in pieces:
        for repeated_part_index in preview_piece.piece.repeated_part_indices:
            part = model.repeated_parts[repeated_part_index]
            instances.append(_preview_instance(part, preview_piece))
    return tuple(instances)


def _preview_instance(
    part: RepeatedPartInstance,
    preview_piece: FracturePreviewPiece,
) -> FracturePreviewInstance:
    return FracturePreviewInstance(
        name=part.name,
        piece_index=preview_piece.piece.index,
        prototype_key=part.prototype_key,
        position=part.position,
        orientation=part.orientation,
        scale=part.scale,
        color=preview_piece.color,
    )


def _preview_bone_segments(
    model: CanonicalTreeModel,
    settings: FractureSettings,
    pieces: tuple[FracturePreviewPiece, ...],
) -> tuple[FracturePreviewBoneSegment, ...]:
    joints_by_name = {joint.name: joint for joint in model.skeleton}
    selected_tokens = set(settings.pinned_cut_joint_tokens)
    color_by_joint_token: dict[str, Color4] = {}
    for piece in pieces:
        for joint_token in piece.piece.joint_tokens:
            color_by_joint_token[joint_token] = piece.color
    segments: list[FracturePreviewBoneSegment] = []
    for joint in model.skeleton:
        parent = joints_by_name.get(joint.parent or "")
        if joint.parent is not None and parent is None:
            raise FractureError(f"Fracture preview skeleton joint {joint.name} references missing parent {joint.parent}.")
        start, end = _source_bone_segment_positions(joint, parent)
        if start == end:
            continue
        segments.append(
            FracturePreviewBoneSegment(
                parent_joint_token=parent.name if parent is not None else joint.name,
                child_joint_token=joint.name,
                parent_position=start,
                child_position=end,
                is_selected_cut=joint.parent is not None and joint.name in selected_tokens,
                color=color_by_joint_token.get(parent.name if parent is not None else joint.name, Color4(0.64, 0.82, 0.95, 1.0)),
                selectable=joint.parent is not None,
            )
        )
    return tuple(segments)


def _source_bone_segment_positions(joint, parent) -> tuple[Vector3, Vector3]:
    end = joint.bind_end_translate
    if end is not None:
        return joint.bind_translate, end
    if parent is not None:
        return parent.bind_translate, joint.bind_translate
    return joint.bind_translate, joint.bind_translate


def _prototype_mesh(prototype: Prototype) -> MeshData:
    if prototype.mesh is not None:
        return prototype.mesh
    if prototype.geometry_payload is not None:
        return geometry_buffer_to_mesh(prototype.geometry_payload)
    raise FractureError(f"Fracture preview prototype {prototype.identity.prim_name} has no mesh payload.")


def _piece_color(index: int) -> Color4:
    palette = (
        Color4(0.88, 0.23, 0.18, 1.0),
        Color4(0.20, 0.53, 0.84, 1.0),
        Color4(0.24, 0.67, 0.36, 1.0),
        Color4(0.90, 0.64, 0.18, 1.0),
        Color4(0.56, 0.38, 0.78, 1.0),
        Color4(0.20, 0.70, 0.68, 1.0),
        Color4(0.82, 0.35, 0.58, 1.0),
        Color4(0.52, 0.56, 0.20, 1.0),
    )
    if index < len(palette):
        return palette[index]
    value = (index * 1103515245 + 12345) & 0xFFFFFF
    red = 0.25 + ((value >> 16) & 0xFF) / 510.0
    green = 0.25 + ((value >> 8) & 0xFF) / 510.0
    blue = 0.25 + (value & 0xFF) / 510.0
    return Color4(red, green, blue, 1.0)


def _slim_preview_source_model(model: CanonicalTreeModel) -> CanonicalTreeModel:
    return replace(
        model,
        materials=(),
        source_objects=(),
        base_tree_parts=(),
        branch_segments=(),
        mesh_library=(),
        skeletal_support_primvars=None,
        spines=(),
        dynamic_wind=None,
    )


def _read_preview_source_model_cache(
    input_path: str,
) -> tuple[object, CanonicalTreeModel, tuple[ValidationIssue, ...], _FracturePlanCache] | None:
    cache_path = _preview_source_model_cache_path(input_path)
    if not cache_path.exists():
        return None
    try:
        import numpy as np

        with np.load(cache_path, allow_pickle=False) as data:
            schema_version = int(data["schema_version"][0])
            if schema_version != FRACTURE_PREVIEW_SOURCE_CACHE_SCHEMA_VERSION:
                raise ValueError("Fracture Preview source cache schema mismatch.")
            model = _preview_source_model_from_arrays(data)
            diagnostics = _diagnostics_from_arrays(data)
        analysis_cache = _build_fracture_plan_cache(model)
        return None, model, diagnostics, analysis_cache
    except Exception:
        with contextlib.suppress(Exception):
            cache_path.unlink(missing_ok=True)
        return None


def _write_preview_source_model_cache(
    input_path: str,
    payload: tuple[object, CanonicalTreeModel, tuple[ValidationIssue, ...], _FracturePlanCache],
) -> None:
    cache_path = _preview_source_model_cache_path(input_path)
    temp_path = cache_path.with_name(f"{cache_path.name}.tmp")
    try:
        import numpy as np

        _report, model, diagnostics, _analysis_cache = payload
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        arrays = _preview_source_model_to_arrays(model, diagnostics, np)
        with temp_path.open("wb") as handle:
            np.savez(handle, **arrays)
        temp_path.replace(cache_path)
    except Exception:
        with contextlib.suppress(Exception):
            temp_path.unlink(missing_ok=True)
        with contextlib.suppress(Exception):
            cache_path.unlink(missing_ok=True)


def _preview_source_model_cache_path(input_path: str) -> Path:
    xml_path = Path(input_path)
    try:
        stat_result = xml_path.stat()
    except OSError:
        return _preview_source_model_cache_root() / "unavailable.npz"
    signature = "|".join(
        (
            str(FRACTURE_PREVIEW_SOURCE_CACHE_SCHEMA_VERSION),
            _preview_source_model_cache_parser_key(),
            os.path.normcase(str(xml_path.resolve(strict=False))),
            str(stat_result.st_size),
            str(stat_result.st_mtime_ns),
        )
    )
    cache_key = hashlib.sha256(signature.encode("utf-8")).hexdigest()
    return _preview_source_model_cache_root() / f"{cache_key}.npz"


def _preview_source_model_cache_parser_key() -> str:
    from .xml_reader import packaged_xml_parser_adapter_enabled

    return "packaged-et-explicit" if packaged_xml_parser_adapter_enabled() else "defused"


def _preview_source_model_cache_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    candidate = (
        Path(local_app_data) / "XMLtoUSDAConverter" / "cache" / "fracture_preview_source_models"
        if local_app_data
        else None
    )
    fallback = Path(tempfile.gettempdir()) / "XMLtoUSDAConverter" / "cache" / "fracture_preview_source_models"
    for root in (candidate, fallback):
        if root is None:
            continue
        try:
            root.mkdir(parents=True, exist_ok=True)
            return root
        except OSError:
            continue
    return fallback


def _preview_source_model_to_arrays(
    model: CanonicalTreeModel,
    diagnostics: tuple[ValidationIssue, ...],
    np,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": np.asarray([FRACTURE_PREVIEW_SOURCE_CACHE_SCHEMA_VERSION], dtype=np.int32),
        "metadata_source_path": np.asarray([model.metadata.source_path]),
        "metadata_source_version": np.asarray([model.metadata.source_version or ""]),
        "metadata_meters_per_unit": np.asarray([model.metadata.meters_per_unit], dtype=np.float64),
        "metadata_up_axis": np.asarray([model.metadata.up_axis]),
        "metadata_warnings": np.asarray(model.metadata.warnings, dtype=np.str_),
        "metadata_unknown_sections": np.asarray(model.metadata.unknown_sections, dtype=np.str_),
        "metadata_output_mode": np.asarray([model.metadata.output_mode.value]),
        "metadata_material_policy": np.asarray([model.metadata.material_policy.value]),
        "metadata_conversion_mode": np.asarray([model.metadata.conversion_mode.value]),
        "diagnostic_severities": np.asarray([issue.severity for issue in diagnostics], dtype=np.str_),
        "diagnostic_codes": np.asarray([issue.code for issue in diagnostics], dtype=np.str_),
        "diagnostic_messages": np.asarray([issue.message for issue in diagnostics], dtype=np.str_),
    }
    _add_mesh_arrays(payload, "base", model.base_mesh, np)
    _add_skeleton_arrays(payload, model.skeleton, np)
    _add_repeated_part_arrays(payload, model.assembly_parts, np)
    _add_prototype_arrays(payload, model.prototypes, np)
    return payload


def _preview_source_model_from_arrays(data) -> CanonicalTreeModel:
    metadata = ExportMetadata(
        source_path=_string_scalar(data, "metadata_source_path"),
        source_version=_none_if_empty(_string_scalar(data, "metadata_source_version")),
        meters_per_unit=float(data["metadata_meters_per_unit"][0]),
        up_axis=_string_scalar(data, "metadata_up_axis"),
        warnings=tuple(data["metadata_warnings"].astype(str).tolist()),
        unknown_sections=tuple(data["metadata_unknown_sections"].astype(str).tolist()),
        output_mode=OutputMode(_string_scalar(data, "metadata_output_mode")),
        material_policy=MaterialPolicy.parse(_string_scalar(data, "metadata_material_policy")),
        conversion_mode=ConversionMode.parse(_string_scalar(data, "metadata_conversion_mode")),
    )
    return CanonicalTreeModel(
        metadata=metadata,
        materials=(),
        source_objects=(),
        base_mesh=_mesh_from_arrays(data, "base"),
        skeleton=_skeleton_from_arrays(data),
        assembly_parts=_repeated_parts_from_arrays(data),
        prototypes=_prototypes_from_arrays(data),
    )


def _diagnostics_from_arrays(data) -> tuple[ValidationIssue, ...]:
    severities = data["diagnostic_severities"].astype(str).tolist()
    codes = data["diagnostic_codes"].astype(str).tolist()
    messages = data["diagnostic_messages"].astype(str).tolist()
    return tuple(
        ValidationIssue(
            severity=severities[index],
            code=codes[index],
            message=messages[index],
        )
        for index in range(len(severities))
    )


def _add_skeleton_arrays(payload: dict[str, object], skeleton: tuple[Joint, ...], np) -> None:
    payload["joint_names"] = np.asarray([joint.name for joint in skeleton], dtype=np.str_)
    payload["joint_source_ids"] = np.asarray([joint.source_id if joint.source_id is not None else -1 for joint in skeleton], dtype=np.int64)
    payload["joint_parents"] = np.asarray([joint.parent or "" for joint in skeleton], dtype=np.str_)
    payload["joint_generator_labels"] = np.asarray([joint.generator_label or "" for joint in skeleton], dtype=np.str_)
    payload["joint_generator_levels"] = np.asarray(
        [joint.generator_level if joint.generator_level is not None else -1 for joint in skeleton],
        dtype=np.int64,
    )
    payload["joint_bind_rows"] = _matrix_array(tuple(joint.bind_transform for joint in skeleton), np)
    payload["joint_rest_rows"] = _matrix_array(tuple(joint.rest_transform for joint in skeleton), np)
    payload["joint_bind_end_present"] = np.asarray([1 if joint.bind_end_transform is not None else 0 for joint in skeleton], dtype=np.int8)
    payload["joint_bind_end_rows"] = _matrix_array(
        tuple(joint.bind_end_transform or Matrix4d.identity() for joint in skeleton),
        np,
    )


def _skeleton_from_arrays(data) -> tuple[Joint, ...]:
    names = data["joint_names"].astype(str).tolist()
    source_ids = data["joint_source_ids"].astype(int).tolist()
    parents = data["joint_parents"].astype(str).tolist()
    generator_labels = data["joint_generator_labels"].astype(str).tolist()
    generator_levels = data["joint_generator_levels"].astype(int).tolist()
    bind_rows = data["joint_bind_rows"]
    rest_rows = data["joint_rest_rows"]
    bind_end_present = data["joint_bind_end_present"].astype(int).tolist()
    bind_end_rows = data["joint_bind_end_rows"]
    return tuple(
        Joint(
            name=names[index],
            source_id=source_ids[index] if source_ids[index] >= 0 else None,
            parent=parents[index] or None,
            generator_label=generator_labels[index] or None,
            generator_level=generator_levels[index] if generator_levels[index] >= 0 else None,
            bind_transform=_matrix_from_rows(bind_rows[index]),
            rest_transform=_matrix_from_rows(rest_rows[index]),
            bind_end_transform=_matrix_from_rows(bind_end_rows[index]) if bind_end_present[index] else None,
        )
        for index in range(len(names))
    )


def _add_repeated_part_arrays(payload: dict[str, object], repeated_parts: tuple[RepeatedPartInstance, ...], np) -> None:
    payload["repeated_names"] = np.asarray([part.name for part in repeated_parts], dtype=np.str_)
    payload["repeated_prototype_keys"] = np.asarray([part.prototype_key for part in repeated_parts], dtype=np.str_)
    payload["repeated_positions"] = np.asarray([(part.position.x, part.position.y, part.position.z) for part in repeated_parts], dtype=np.float64)
    payload["repeated_orientations"] = np.asarray(
        [(part.orientation.real, part.orientation.i, part.orientation.j, part.orientation.k) for part in repeated_parts],
        dtype=np.float64,
    )
    payload["repeated_scales"] = np.asarray([(part.scale.x, part.scale.y, part.scale.z) for part in repeated_parts], dtype=np.float64)
    payload["repeated_source_object_ids"] = np.asarray([part.source_object_id or "" for part in repeated_parts], dtype=np.str_)
    payload["repeated_source_mesh_ids"] = np.asarray(
        [part.source_mesh_id if part.source_mesh_id is not None else -1 for part in repeated_parts],
        dtype=np.int64,
    )
    payload["repeated_source_material_ids"] = np.asarray(
        [part.source_material_id if part.source_material_id is not None else -1 for part in repeated_parts],
        dtype=np.int64,
    )
    payload["repeated_mesh_lods"] = np.asarray([part.mesh_lod if part.mesh_lod is not None else -1 for part in repeated_parts], dtype=np.int64)
    _add_string_offsets(payload, "repeated_binding_tokens", tuple(part.binding.joint_tokens for part in repeated_parts), np)
    _add_float_offsets(payload, "repeated_binding_weights", tuple(part.binding.weights for part in repeated_parts), np)
    _add_int_offsets(payload, "repeated_source_bone_ids", tuple(part.source_bone_ids for part in repeated_parts), np)


def _repeated_parts_from_arrays(data) -> tuple[RepeatedPartInstance, ...]:
    names = data["repeated_names"].astype(str).tolist()
    prototype_keys = data["repeated_prototype_keys"].astype(str).tolist()
    positions = data["repeated_positions"]
    orientations = data["repeated_orientations"]
    scales = data["repeated_scales"]
    source_object_ids = data["repeated_source_object_ids"].astype(str).tolist()
    source_mesh_ids = data["repeated_source_mesh_ids"].astype(int).tolist()
    source_material_ids = data["repeated_source_material_ids"].astype(int).tolist()
    mesh_lods = data["repeated_mesh_lods"].astype(int).tolist()
    binding_tokens = _string_groups_from_offsets(data, "repeated_binding_tokens")
    binding_weights = _float_groups_from_offsets(data, "repeated_binding_weights")
    source_bone_ids = _int_groups_from_offsets(data, "repeated_source_bone_ids")
    return tuple(
        RepeatedPartInstance(
            name=names[index],
            prototype_key=prototype_keys[index],
            position=Vector3(float(positions[index][0]), float(positions[index][1]), float(positions[index][2])),
            orientation=Quaternion(
                float(orientations[index][0]),
                float(orientations[index][1]),
                float(orientations[index][2]),
                float(orientations[index][3]),
            ),
            scale=Vector3(float(scales[index][0]), float(scales[index][1]), float(scales[index][2])),
            binding=InstanceBinding(joint_tokens=binding_tokens[index], weights=binding_weights[index]),
            source_object_id=source_object_ids[index] or None,
            source_mesh_id=source_mesh_ids[index] if source_mesh_ids[index] >= 0 else None,
            source_material_id=source_material_ids[index] if source_material_ids[index] >= 0 else None,
            source_bone_ids=source_bone_ids[index],
            mesh_lod=mesh_lods[index] if mesh_lods[index] >= 0 else None,
        )
        for index in range(len(names))
    )


def _add_prototype_arrays(payload: dict[str, object], prototypes: tuple[Prototype, ...], np) -> None:
    payload["prototype_keys"] = np.asarray([prototype.source_key for prototype in prototypes], dtype=np.str_)
    payload["prototype_source_names"] = np.asarray([prototype.source_name for prototype in prototypes], dtype=np.str_)
    payload["prototype_prim_names"] = np.asarray([prototype.identity.prim_name for prototype in prototypes], dtype=np.str_)
    payload["prototype_types"] = np.asarray([prototype.identity.prototype_type for prototype in prototypes], dtype=np.str_)
    payload["prototype_mesh_ids"] = np.asarray(
        [prototype.source_mesh_id if prototype.source_mesh_id is not None else -1 for prototype in prototypes],
        dtype=np.int64,
    )
    for index, prototype in enumerate(prototypes):
        _add_mesh_arrays(payload, f"prototype_{index}", prototype.mesh, np)


def _prototypes_from_arrays(data) -> tuple[Prototype, ...]:
    keys = data["prototype_keys"].astype(str).tolist()
    source_names = data["prototype_source_names"].astype(str).tolist()
    prim_names = data["prototype_prim_names"].astype(str).tolist()
    prototype_types = data["prototype_types"].astype(str).tolist()
    mesh_ids = data["prototype_mesh_ids"].astype(int).tolist()
    return tuple(
        Prototype(
            identity=PrototypeIdentity(
                source_key=keys[index],
                prim_name=prim_names[index],
                prototype_type=prototype_types[index],
            ),
            mesh=_mesh_from_arrays(data, f"prototype_{index}"),
            source_key=keys[index],
            source_mesh_id=mesh_ids[index] if mesh_ids[index] >= 0 else None,
            source_name=source_names[index],
            prototype_type=prototype_types[index],
        )
        for index in range(len(keys))
    )


def _add_mesh_arrays(payload: dict[str, object], prefix: str, mesh: MeshData | None, np) -> None:
    payload[f"{prefix}_present"] = np.asarray([1 if mesh is not None else 0], dtype=np.int8)
    if mesh is None:
        payload[f"{prefix}_name"] = np.asarray([""], dtype=np.str_)
        payload[f"{prefix}_points"] = np.empty((0, 3), dtype=np.float64)
        payload[f"{prefix}_face_counts"] = np.empty((0,), dtype=np.int32)
        payload[f"{prefix}_face_indices"] = np.empty((0,), dtype=np.int32)
        payload[f"{prefix}_uv"] = np.empty((0, 2), dtype=np.float64)
        payload[f"{prefix}_secondary_uv"] = np.empty((0, 2), dtype=np.float64)
        payload[f"{prefix}_colors"] = np.empty((0, 4), dtype=np.float64)
        payload[f"{prefix}_section_material_ids"] = np.empty((0,), dtype=np.int64)
        payload[f"{prefix}_section_offsets"] = np.asarray([0], dtype=np.int64)
        payload[f"{prefix}_section_face_indices"] = np.empty((0,), dtype=np.int32)
        payload[f"{prefix}_skel_indices"] = np.empty((0,), dtype=np.int32)
        payload[f"{prefix}_skel_weights"] = np.empty((0,), dtype=np.float64)
        payload[f"{prefix}_skel_element_size"] = np.asarray([0], dtype=np.int32)
        return
    payload[f"{prefix}_name"] = np.asarray([mesh.name], dtype=np.str_)
    payload[f"{prefix}_points"] = np.asarray([(point.x, point.y, point.z) for point in mesh.points], dtype=np.float64)
    payload[f"{prefix}_face_counts"] = np.asarray(mesh.face_vertex_counts, dtype=np.int32)
    payload[f"{prefix}_face_indices"] = np.asarray(mesh.face_vertex_indices, dtype=np.int32)
    payload[f"{prefix}_uv"] = np.asarray([(uv.x, uv.y) for uv in mesh.uv_coords], dtype=np.float64)
    payload[f"{prefix}_secondary_uv"] = np.asarray([(uv.x, uv.y) for uv in mesh.secondary_uv_coords], dtype=np.float64)
    payload[f"{prefix}_colors"] = np.asarray([(color.r, color.g, color.b, color.a) for color in mesh.vertex_colors], dtype=np.float64)
    material_ids: list[int] = []
    offsets = [0]
    face_indices: list[int] = []
    for section in mesh.sections:
        material_ids.append(int(section.material_id))
        face_indices.extend(int(index) for index in section.face_indices)
        offsets.append(len(face_indices))
    payload[f"{prefix}_section_material_ids"] = np.asarray(material_ids, dtype=np.int64)
    payload[f"{prefix}_section_offsets"] = np.asarray(offsets, dtype=np.int64)
    payload[f"{prefix}_section_face_indices"] = np.asarray(face_indices, dtype=np.int32)
    payload[f"{prefix}_skel_indices"] = np.asarray(mesh.skel_joint_indices, dtype=np.int32)
    payload[f"{prefix}_skel_weights"] = np.asarray(mesh.skel_joint_weights, dtype=np.float64)
    payload[f"{prefix}_skel_element_size"] = np.asarray([mesh.skel_element_size], dtype=np.int32)


def _mesh_from_arrays(data, prefix: str) -> MeshData | None:
    if not int(data[f"{prefix}_present"][0]):
        return None
    points = data[f"{prefix}_points"]
    uv = data[f"{prefix}_uv"]
    secondary_uv = data[f"{prefix}_secondary_uv"]
    colors = data[f"{prefix}_colors"]
    material_ids = data[f"{prefix}_section_material_ids"].astype(int).tolist()
    offsets = data[f"{prefix}_section_offsets"].astype(int).tolist()
    section_face_indices = data[f"{prefix}_section_face_indices"].astype(int).tolist()
    sections = tuple(
        MeshSection(
            material_id=material_ids[index],
            face_indices=tuple(section_face_indices[offsets[index] : offsets[index + 1]]),
        )
        for index in range(len(material_ids))
    )
    return MeshData(
        name=_string_scalar(data, f"{prefix}_name"),
        points=tuple(Vector3(float(row[0]), float(row[1]), float(row[2])) for row in points),
        face_vertex_counts=tuple(int(value) for value in data[f"{prefix}_face_counts"]),
        face_vertex_indices=tuple(int(value) for value in data[f"{prefix}_face_indices"]),
        uv_coords=tuple(Vector2(float(row[0]), float(row[1])) for row in uv),
        secondary_uv_coords=tuple(Vector2(float(row[0]), float(row[1])) for row in secondary_uv),
        vertex_colors=tuple(Color4(float(row[0]), float(row[1]), float(row[2]), float(row[3])) for row in colors),
        sections=sections,
        skel_joint_indices=tuple(int(value) for value in data[f"{prefix}_skel_indices"]),
        skel_joint_weights=tuple(float(value) for value in data[f"{prefix}_skel_weights"]),
        skel_element_size=int(data[f"{prefix}_skel_element_size"][0]),
    )


def _matrix_array(matrices: tuple[Matrix4d, ...], np):
    if not matrices:
        return np.empty((0, 4, 4), dtype=np.float64)
    return np.asarray([matrix.rows for matrix in matrices], dtype=np.float64)


def _matrix_from_rows(rows) -> Matrix4d:
    return Matrix4d(rows=tuple(tuple(float(value) for value in row) for row in rows))


def _add_string_offsets(payload: dict[str, object], prefix: str, groups: tuple[tuple[str, ...], ...], np) -> None:
    offsets = [0]
    values: list[str] = []
    for group in groups:
        values.extend(group)
        offsets.append(len(values))
    payload[f"{prefix}_offsets"] = np.asarray(offsets, dtype=np.int64)
    payload[f"{prefix}_values"] = np.asarray(values, dtype=np.str_)


def _add_float_offsets(payload: dict[str, object], prefix: str, groups: tuple[tuple[float, ...], ...], np) -> None:
    offsets = [0]
    values: list[float] = []
    for group in groups:
        values.extend(float(value) for value in group)
        offsets.append(len(values))
    payload[f"{prefix}_offsets"] = np.asarray(offsets, dtype=np.int64)
    payload[f"{prefix}_values"] = np.asarray(values, dtype=np.float64)


def _add_int_offsets(payload: dict[str, object], prefix: str, groups: tuple[tuple[int, ...], ...], np) -> None:
    offsets = [0]
    values: list[int] = []
    for group in groups:
        values.extend(int(value) for value in group)
        offsets.append(len(values))
    payload[f"{prefix}_offsets"] = np.asarray(offsets, dtype=np.int64)
    payload[f"{prefix}_values"] = np.asarray(values, dtype=np.int64)


def _string_groups_from_offsets(data, prefix: str) -> tuple[tuple[str, ...], ...]:
    offsets = data[f"{prefix}_offsets"].astype(int).tolist()
    values = data[f"{prefix}_values"].astype(str).tolist()
    return tuple(tuple(values[offsets[index] : offsets[index + 1]]) for index in range(len(offsets) - 1))


def _float_groups_from_offsets(data, prefix: str) -> tuple[tuple[float, ...], ...]:
    offsets = data[f"{prefix}_offsets"].astype(int).tolist()
    values = data[f"{prefix}_values"].astype(float).tolist()
    return tuple(tuple(float(value) for value in values[offsets[index] : offsets[index + 1]]) for index in range(len(offsets) - 1))


def _int_groups_from_offsets(data, prefix: str) -> tuple[tuple[int, ...], ...]:
    offsets = data[f"{prefix}_offsets"].astype(int).tolist()
    values = data[f"{prefix}_values"].astype(int).tolist()
    return tuple(tuple(int(value) for value in values[offsets[index] : offsets[index + 1]]) for index in range(len(offsets) - 1))


def _string_scalar(data, key: str) -> str:
    return str(data[key].astype(str).tolist()[0])


def _none_if_empty(value: str) -> str | None:
    return value or None
