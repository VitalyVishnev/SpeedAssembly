"""Fracture static assembly export workflow.

Layer: application/infrastructure boundary.

Fracture planning owns piece membership. This module projects each planned
piece into a Static Mesh Assembly authoring model and delegates USDA output to
the existing writer.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from .authoring_validation import validate_authoring_model
from .canonical_loader import load_resolved_assembly_model
from .conversion_validation import validate_conversion_request
from .fracture_service import FractureError, FracturePiece, FracturePlan, FractureSettings, plan_fracture
from .fracture_geometry import slice_mesh_faces
from .job_control import throw_if_cancelled
from .models import (
    CanonicalTreeModel,
    ConversionMode,
    ConversionRequest,
    PrototypeStrategy,
    ResolvedAssemblyModel,
    UsdAssemblyDocument,
    ValidationIssue,
)
from .output_resolution import ensure_output_path_allowed, resolve_output_path
from .usda_writer import write_resolved_usda_document


@dataclass(frozen=True)
class FracturePieceExport:
    piece: FracturePiece
    output_path: str
    usda_document: UsdAssemblyDocument


@dataclass(frozen=True)
class FractureExportResult:
    plan: FracturePlan
    outputs: tuple[FracturePieceExport, ...]
    diagnostics: tuple[ValidationIssue, ...]


def export_fracture_usda_from_conversion_request(
    request: ConversionRequest,
    settings: FractureSettings | None = None,
    *,
    telemetry_callback=None,
    cancel_event=None,
) -> FractureExportResult:
    """Resolve one conversion request's Operator Intent and export fracture pieces."""
    validate_conversion_request(request)
    input_path = _single_input_path(request)
    output_path = _request_output_path(request, input_path)
    _, resolved = load_resolved_assembly_model(
        input_path,
        request.output_mode,
        material_policy=request.material_policy,
        bark_material_path=request.bark_material_path,
        leaves_material_path=request.leaves_material_path,
        single_material_path=request.single_material_path,
        base_material_overrides=request.base_material_overrides,
        udim_material_settings=request.udim_material_settings,
        cpu_profile=request.cpu_profile,
        use_explicit_material_contract=request.use_explicit_material_contract,
        prototype_source_configs=request.prototype_source_configs,
        conversion_mode=ConversionMode.STATIC_ASSEMBLY,
        output_stem=output_path.stem,
        fbx_cache_max_bytes=request.fbx_cache_max_bytes,
        fbx_cache_max_age_seconds=request.fbx_cache_max_age_seconds,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
    )
    return export_fracture_usda(
        resolved,
        output_path,
        settings,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
    )


def export_fracture_usda(
    resolved: ResolvedAssemblyModel,
    output_path: str | Path,
    settings: FractureSettings | None = None,
    *,
    telemetry_callback=None,
    cancel_event=None,
) -> FractureExportResult:
    """Export a flat sibling set of fracture Static Mesh Assembly USDA files."""
    base_output_path = Path(output_path)
    export_settings = _export_settings(settings, base_output_path)
    plan = plan_fracture(resolved.authoring_model, export_settings)
    outputs: list[FracturePieceExport] = []
    diagnostics = plan.diagnostics

    for piece in plan.pieces:
        throw_if_cancelled(cancel_event)
        piece_output_path = _piece_output_path(base_output_path, piece)
        ensure_output_path_allowed(piece_output_path)
        piece_resolved = _piece_resolved_model(resolved, piece)
        diagnostics += piece_resolved.authoring_diagnostics
        document = write_resolved_usda_document(
            piece_resolved,
            output_path=piece_output_path,
            telemetry_callback=telemetry_callback,
            cancel_event=cancel_event,
        )
        outputs.append(
            FracturePieceExport(
                piece=piece,
                output_path=str(piece_output_path),
                usda_document=document,
            )
        )

    return FractureExportResult(
        plan=plan,
        outputs=tuple(outputs),
        diagnostics=diagnostics,
    )


def derive_fracture_usda_output_paths(
    output_path: str | Path,
    plan: FracturePlan,
) -> tuple[Path, ...]:
    base_output_path = Path(output_path)
    return tuple(_piece_output_path(base_output_path, piece) for piece in plan.pieces)


def _single_input_path(request: ConversionRequest) -> str:
    if len(request.input_paths) != 1:
        raise FractureError("Fracture export requires exactly one input XML.")
    return request.input_paths[0]


def _request_output_path(request: ConversionRequest, input_path: str) -> Path:
    if request.output_path:
        return Path(request.output_path)
    if request.output_directory:
        resolved = resolve_output_path(request, input_path)
        if resolved is None:
            raise FractureError("Fracture export requires a resolved output path.")
        return resolved
    return Path(input_path).with_suffix(".usda")


def _export_settings(settings: FractureSettings | None, output_path: Path) -> FractureSettings:
    resolved_settings = settings or FractureSettings()
    return replace(resolved_settings, output_stem=output_path.stem)


def _piece_output_path(output_path: Path, piece: FracturePiece) -> Path:
    return output_path.with_name(f"{piece.name}.usda")


def _piece_resolved_model(resolved: ResolvedAssemblyModel, piece: FracturePiece) -> ResolvedAssemblyModel:
    piece_model = _piece_authoring_model(resolved.authoring_model, piece)
    authoring_diagnostics = validate_authoring_model(piece_model, conversion_mode=ConversionMode.STATIC_ASSEMBLY)
    return ResolvedAssemblyModel(
        source_model=resolved.source_model,
        authoring_model=piece_model,
        conversion_mode=ConversionMode.STATIC_ASSEMBLY,
        output_stem=piece.name,
        udim_material_settings=resolved.udim_material_settings,
        source_diagnostics=resolved.source_diagnostics,
        resolution_diagnostics=resolved.resolution_diagnostics,
        authoring_diagnostics=authoring_diagnostics,
    )


def _piece_authoring_model(model: CanonicalTreeModel, piece: FracturePiece) -> CanonicalTreeModel:
    if model.base_mesh is None:
        raise FractureError("Fracture export requires a base mesh.")

    repeated_parts = tuple(model.repeated_parts[index] for index in piece.repeated_part_indices)
    used_prototype_keys = {part.prototype_key for part in repeated_parts}
    prototypes = tuple(prototype for prototype in model.prototypes if prototype.source_key in used_prototype_keys)
    metadata = replace(model.metadata, conversion_mode=ConversionMode.STATIC_ASSEMBLY)
    return replace(
        model,
        metadata=metadata,
        base_mesh=slice_mesh_faces(model.base_mesh, piece.base_face_indices, name=f"{piece.name}_BaseMesh"),
        skeleton=(),
        assembly_parts=repeated_parts,
        prototypes=prototypes,
        prototype_strategy=PrototypeStrategy.INLINE_STATIC_PART,
        skeletal_support_primvars=None,
    )
