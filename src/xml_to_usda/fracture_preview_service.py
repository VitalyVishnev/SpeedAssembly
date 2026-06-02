"""Diagnostic fracture preview data generation.

Layer: application/domain boundary.

Preview uses the same `FracturePlan` contract as export, but emits lightweight
geometry and stable colors for inspection instead of authoring USD.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from .canonical_loader import load_source_tree_model
from .conversion_validation import validate_conversion_request
from .fracture_geometry import sample_face_indices, slice_mesh_faces
from .fracture_service import FractureError, FracturePiece, FracturePlan, FractureSettings, plan_fracture
from .geometry_buffers import geometry_buffer_from_mesh, geometry_buffer_to_mesh
from .models import (
    CanonicalTreeModel,
    Color4,
    ConversionRequest,
    GeometryBuffer,
    MeshData,
    Prototype,
    Quaternion,
    RepeatedPartInstance,
    ValidationIssue,
    Vector3,
)
from .output_resolution import resolve_output_path


DEFAULT_FRACTURE_PREVIEW_BASE_FACE_BUDGET = 50_000
DEFAULT_FRACTURE_PREVIEW_PROTOTYPE_FACE_BUDGET = 2_000


@dataclass(frozen=True)
class FracturePreviewSettings:
    fracture: FractureSettings = field(default_factory=FractureSettings)
    max_base_faces_per_piece: int = DEFAULT_FRACTURE_PREVIEW_BASE_FACE_BUDGET
    max_prototype_faces: int = DEFAULT_FRACTURE_PREVIEW_PROTOTYPE_FACE_BUDGET


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
class FracturePreviewResult:
    plan: FracturePlan
    pieces: tuple[FracturePreviewPiece, ...]
    prototypes: dict[str, FracturePreviewPrototype]
    instances: tuple[FracturePreviewInstance, ...]
    diagnostics: tuple[ValidationIssue, ...]


def generate_fracture_preview_from_conversion_request(
    request: ConversionRequest,
    settings: FracturePreviewSettings | None = None,
    *,
    telemetry_callback=None,
    cancel_event=None,
) -> FracturePreviewResult:
    """Load source XML geometry and build a diagnostic fracture preview."""
    validate_conversion_request(request)
    input_path = _single_input_path(request)
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
    pieces = tuple(_preview_piece(model, piece, resolved_settings) for piece in plan.pieces)
    prototypes = _preview_prototypes(model, plan, resolved_settings)
    instances = _preview_instances(model, pieces)
    return FracturePreviewResult(
        plan=plan,
        pieces=pieces,
        prototypes=prototypes,
        instances=instances,
        diagnostics=plan.diagnostics,
    )


def _single_input_path(request: ConversionRequest) -> str:
    if len(request.input_paths) != 1:
        raise FractureError("Fracture preview requires exactly one input XML.")
    return request.input_paths[0]


def _preview_output_stem(request: ConversionRequest, input_path: str) -> str:
    if request.output_path:
        return Path(request.output_path).stem
    if request.output_directory:
        resolved = resolve_output_path(request, input_path)
        if resolved is None:
            raise FractureError("Fracture preview requires a resolved output path.")
        return resolved.stem
    return Path(input_path).stem


def _preview_settings(settings: FracturePreviewSettings | None, output_stem: str) -> FracturePreviewSettings:
    resolved_settings = settings or FracturePreviewSettings()
    return replace(
        resolved_settings,
        fracture=replace(resolved_settings.fracture, output_stem=output_stem),
    )


def _validate_preview_settings(settings: FracturePreviewSettings) -> None:
    if settings.max_base_faces_per_piece <= 0:
        raise FractureError("Fracture preview base face budget must be greater than zero.")
    if settings.max_prototype_faces <= 0:
        raise FractureError("Fracture preview prototype face budget must be greater than zero.")


def _preview_piece(
    model: CanonicalTreeModel,
    piece: FracturePiece,
    settings: FracturePreviewSettings,
) -> FracturePreviewPiece:
    if model.base_mesh is None:
        raise FractureError("Fracture preview requires a base mesh.")
    sampled_faces = sample_face_indices(piece.base_face_indices, settings.max_base_faces_per_piece)
    mesh = slice_mesh_faces(model.base_mesh, sampled_faces, name=f"{piece.name}_PreviewBase")
    return FracturePreviewPiece(
        piece=piece,
        color=_piece_color(piece.index),
        base_mesh=geometry_buffer_from_mesh(mesh),
    )


def _preview_prototypes(
    model: CanonicalTreeModel,
    plan: FracturePlan,
    settings: FracturePreviewSettings,
) -> dict[str, FracturePreviewPrototype]:
    used_keys = {
        model.repeated_parts[index].prototype_key
        for piece in plan.pieces
        for index in piece.repeated_part_indices
    }
    prototypes_by_key = {prototype.source_key: prototype for prototype in model.prototypes}
    preview_prototypes: dict[str, FracturePreviewPrototype] = {}
    for source_key in sorted(used_keys):
        prototype = prototypes_by_key.get(source_key)
        if prototype is None:
            raise FractureError(f"Fracture preview repeated part references missing prototype {source_key}.")
        preview_prototypes[source_key] = _preview_prototype(prototype, settings)
    return preview_prototypes


def _preview_prototype(
    prototype: Prototype,
    settings: FracturePreviewSettings,
) -> FracturePreviewPrototype:
    mesh = _prototype_mesh(prototype)
    sampled_faces = sample_face_indices(tuple(range(len(mesh.face_vertex_counts))), settings.max_prototype_faces)
    preview_mesh = slice_mesh_faces(mesh, sampled_faces, name=f"{prototype.identity.prim_name}_Preview")
    return FracturePreviewPrototype(
        source_key=prototype.source_key,
        source_name=prototype.source_name,
        mesh=geometry_buffer_from_mesh(preview_mesh),
    )


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
