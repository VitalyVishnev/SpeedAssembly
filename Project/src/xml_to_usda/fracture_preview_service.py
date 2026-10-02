"""Diagnostic fracture preview data generation.

Layer: application/domain boundary.

Preview uses the same `FracturePlan` contract as export, but emits lightweight
geometry and stable colors for inspection instead of authoring USD.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

from .boolean_fracture_prototype import (
    BooleanMultiPrototypeSession,
    boolean_multi_settings_from_fracture,
    fracture_geometry_from_boolean_multi,
    prepare_boolean_fracture_source,
    prepare_boolean_multi_prototype,
)
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
    source_bone_segment_positions,
)
from .geometry_buffers import geometry_buffer_from_mesh, geometry_buffer_to_mesh
from .job_control import throw_if_cancelled
from .mesh_pruning import select_large_connected_face_indices
from .models import (
    CanonicalTreeModel,
    Color4,
    ConversionRequest,
    CpuProfile,
    GeometryBuffer,
    MeshData,
    Prototype,
    Quaternion,
    RepeatedPartInstance,
    ValidationIssue,
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
_PREVIEW_SOURCE_MEMORY_CACHE: tuple[
    tuple[Path, int | None, int | None],
    tuple[object, CanonicalTreeModel, tuple[ValidationIssue, ...], _FracturePlanCache],
] | None = None
_BOOLEAN_PREVIEW_SESSION_CACHE: tuple[CanonicalTreeModel, BooleanMultiPrototypeSession] | None = None


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
    source_cache_key = _preview_source_memory_cache_key(input_path)
    cached_source = (
        _PREVIEW_SOURCE_MEMORY_CACHE[1]
        if _PREVIEW_SOURCE_MEMORY_CACHE is not None and _PREVIEW_SOURCE_MEMORY_CACHE[0] == source_cache_key
        else None
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
    global _BOOLEAN_PREVIEW_SESSION_CACHE
    geometry = None
    if resolved_settings.fracture.detailed_cuts_enabled:
        boolean_settings = boolean_multi_settings_from_fracture(resolved_settings.fracture)
        previous_session = (
            _BOOLEAN_PREVIEW_SESSION_CACHE[1]
            if _BOOLEAN_PREVIEW_SESSION_CACHE is not None and _BOOLEAN_PREVIEW_SESSION_CACHE[0] is model
            else None
        )
        source_context = (
            None
            if previous_session is not None
            else prepare_boolean_fracture_source(model, analysis_cache=analysis_cache)
        )
        boolean_session = prepare_boolean_multi_prototype(
            model,
            boolean_settings,
            previous_session=previous_session,
            source_context=source_context,
        )
        geometry = fracture_geometry_from_boolean_multi(boolean_session.build(boolean_settings))
        _BOOLEAN_PREVIEW_SESSION_CACHE = (model, boolean_session)
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
        start, end = source_bone_segment_positions(joint, parent)
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


def _preview_source_memory_cache_key(input_path: str) -> tuple[Path, int | None, int | None]:
    path = Path(input_path).resolve(strict=False)
    try:
        stat = path.stat()
    except OSError:
        return path, None, None
    return path, stat.st_size, stat.st_mtime_ns
