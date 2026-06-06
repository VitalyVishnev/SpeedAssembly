"""Diagnostic fracture preview data generation.

Layer: application/domain boundary.

Preview uses the same `FracturePlan` contract as export, but emits lightweight
geometry and stable colors for inspection instead of authoring USD.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from .canonical_loader import load_source_tree_model
from .fracture_geometry import sample_face_indices, slice_mesh_faces
from .fracture_service import FractureError, FracturePiece, FracturePlan, FractureSettings, plan_fracture
from .geometry_buffers import geometry_buffer_from_mesh, geometry_buffer_to_mesh
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


DEFAULT_FRACTURE_PREVIEW_POLYCOUNT = 1_000_000
DEFAULT_FRACTURE_PREVIEW_BASE_PRIORITY = 0.33
DEFAULT_FRACTURE_PREVIEW_BASE_FACE_BUDGET = 50_000
DEFAULT_FRACTURE_PREVIEW_PROTOTYPE_FACE_BUDGET = 2_000


@dataclass(frozen=True)
class FracturePreviewSettings:
    fracture: FractureSettings = field(default_factory=FractureSettings)
    final_polycount: int = DEFAULT_FRACTURE_PREVIEW_POLYCOUNT
    base_mesh_priority: float = DEFAULT_FRACTURE_PREVIEW_BASE_PRIORITY
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


@dataclass(frozen=True)
class FracturePreviewResult:
    plan: FracturePlan
    pieces: tuple[FracturePreviewPiece, ...]
    prototypes: dict[str, FracturePreviewPrototype]
    instances: tuple[FracturePreviewInstance, ...]
    diagnostics: tuple[ValidationIssue, ...]
    bone_segments: tuple[FracturePreviewBoneSegment, ...] = ()


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
) -> FracturePreviewResult:
    """Load source XML geometry and build a diagnostic fracture preview."""
    return generate_fracture_preview_from_source_request(
        FracturePreviewSourceRequest.from_conversion_request(request),
        settings,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
    )


def generate_fracture_preview_from_source_request(
    request: FracturePreviewSourceRequest,
    settings: FracturePreviewSettings | None = None,
    *,
    telemetry_callback=None,
    cancel_event=None,
) -> FracturePreviewResult:
    """Load source XML geometry and build a diagnostic fracture preview."""
    input_path = request.input_path.strip()
    if not input_path:
        raise FractureError("Fracture preview requires a source XML path.")
    preview_settings = _preview_settings(settings, _preview_output_stem(request, input_path))
    _report, source_model, source_diagnostics = load_source_tree_model(
        input_path,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
    )
    result = generate_fracture_preview(source_model, preview_settings)
    return replace(result, diagnostics=source_diagnostics + result.diagnostics)


def generate_fracture_preview(
    model: CanonicalTreeModel,
    settings: FracturePreviewSettings | None = None,
) -> FracturePreviewResult:
    """Build lightweight diagnostic preview payloads from one tree model."""
    resolved_settings = settings or FracturePreviewSettings()
    _validate_preview_settings(resolved_settings)
    plan = plan_fracture(model, resolved_settings.fracture)
    base_face_budgets = _base_face_budgets(model, plan, resolved_settings)
    prototype_budgets = _prototype_face_budgets(model, plan, resolved_settings, base_face_budgets)
    pieces = tuple(_preview_piece(model, piece, base_face_budgets[piece.index]) for piece in plan.pieces)
    prototypes = _preview_prototypes(model, plan, prototype_budgets)
    instances = _preview_instances(model, pieces)
    bone_segments = _preview_bone_segments(model, resolved_settings.fracture, pieces)
    return FracturePreviewResult(
        plan=plan,
        pieces=pieces,
        prototypes=prototypes,
        instances=instances,
        diagnostics=plan.diagnostics,
        bone_segments=bone_segments,
    )


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
    if settings.max_base_faces_per_piece <= 0:
        raise FractureError("Fracture preview base face budget must be greater than zero.")
    if settings.max_prototype_faces <= 0:
        raise FractureError("Fracture preview prototype face budget must be greater than zero.")


def _base_face_budgets(
    model: CanonicalTreeModel,
    plan: FracturePlan,
    settings: FracturePreviewSettings,
) -> dict[int, int]:
    if model.base_mesh is None:
        raise FractureError("Fracture preview requires a base mesh.")
    source_counts = {piece.index: len(piece.base_face_indices) for piece in plan.pieces}
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
    model: CanonicalTreeModel,
    piece: FracturePiece,
    face_budget: int,
) -> FracturePreviewPiece:
    if model.base_mesh is None:
        raise FractureError("Fracture preview requires a base mesh.")
    sampled_faces = sample_face_indices(piece.base_face_indices, face_budget)
    mesh = slice_mesh_faces(model.base_mesh, sampled_faces, name=f"{piece.name}_PreviewBase")
    return FracturePreviewPiece(
        piece=piece,
        color=_piece_color(piece.index),
        base_mesh=geometry_buffer_from_mesh(mesh),
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
        mesh=geometry_buffer_from_mesh(preview_mesh),
    )


def _simplify_preview_mesh(mesh: MeshData, target_face_count: int, *, name: str) -> MeshData:
    source_face_count = len(mesh.face_vertex_counts)
    if source_face_count <= target_face_count:
        return slice_mesh_faces(mesh, tuple(range(source_face_count)), name=name)
    sampled_faces = sample_face_indices(tuple(range(source_face_count)), target_face_count)
    return slice_mesh_faces(mesh, sampled_faces, name=name)


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
        if joint.parent is None:
            continue
        parent = joints_by_name.get(joint.parent)
        if parent is None:
            raise FractureError(f"Fracture preview skeleton joint {joint.name} references missing parent {joint.parent}.")
        segments.append(
            FracturePreviewBoneSegment(
                parent_joint_token=parent.name,
                child_joint_token=joint.name,
                parent_position=parent.bind_translate,
                child_position=joint.bind_translate,
                is_selected_cut=joint.name in selected_tokens,
                color=color_by_joint_token.get(joint.name, Color4(0.64, 0.82, 0.95, 1.0)),
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
