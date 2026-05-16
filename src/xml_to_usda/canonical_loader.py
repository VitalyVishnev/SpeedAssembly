"""Source and resolved assembly model loading for conversion workflows.

Layer: application/domain boundary.

This module keeps the source-normalized CanonicalTreeModel separate from the
ResolvedAssemblyModel that applies operator intent for authoring.
"""

from __future__ import annotations

import time
from dataclasses import replace

from .asset_paths import normalize_unreal_asset_path
from .job_control import emit_telemetry, throw_if_cancelled
from .material_resolver import apply_material_policy as resolve_material_policy, resolve_prototype_materials
from .models import (
    BaseMaterialOverride,
    CanonicalTreeModel,
    ConversionPhase,
    ConversionMode,
    CpuProfile,
    MaterialPolicy,
    ObservedXmlSchemaReport,
    OutputMode,
    PrototypeSourceConfig,
    PrototypeStrategy,
    ResolvedAssemblyModel,
    ValidationIssue,
)
from .normalizer import normalize_to_canonical
from .prototype_sources import apply_prototype_source_configs, merge_legacy_part_mesh_configs
from .validator import validate_authoring_model, validate_resolution, validate_source_model
from .xml_reader import inspect_xml, read_source_xml


def load_source_tree_model(
    input_path: str,
    *,
    telemetry_callback=None,
    cancel_event=None,
) -> tuple[ObservedXmlSchemaReport, CanonicalTreeModel, tuple[ValidationIssue, ...]]:
    """Load one XML source into the source-normalized CanonicalTreeModel."""
    started_at = time.perf_counter()
    emit_telemetry(
        telemetry_callback,
        ConversionPhase.XML_NORMALIZATION,
        message="Reading and normalizing XML source.",
        started_at=started_at,
    )
    throw_if_cancelled(cancel_event)
    document = read_source_xml(input_path)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_source_model(model)
    return report, model, diagnostics


def resolve_assembly_model(
    source_model: CanonicalTreeModel,
    *,
    output_mode: OutputMode = OutputMode.SELF_CONTAINED,
    material_policy: MaterialPolicy = MaterialPolicy.SOURCE_MATERIAL_ROLES,
    bark_material_path: str | None = None,
    leaves_material_path: str | None = None,
    single_material_path: str | None = None,
    base_material_overrides: tuple[BaseMaterialOverride, ...] = (),
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
    use_explicit_material_contract: bool = False,
    prototype_source_configs: tuple[PrototypeSourceConfig, ...] = (),
    use_existing_part_meshes: bool = False,
    part_mesh_asset_paths: tuple[tuple[str, str], ...] = (),
    conversion_mode: ConversionMode | str = ConversionMode.SKELETAL_ASSEMBLY,
    output_stem: str | None = None,
    source_diagnostics: tuple[ValidationIssue, ...] | None = None,
    telemetry_callback=None,
    cancel_event=None,
) -> ResolvedAssemblyModel:
    """Apply operator intent to a source model and return authoring-ready state."""
    started_at = time.perf_counter()
    resolved_conversion_mode = ConversionMode.parse(conversion_mode)
    model = source_model
    source_configs = merge_legacy_part_mesh_configs(
        prototype_source_configs,
        use_existing_part_meshes,
        part_mesh_asset_paths,
    )
    model = apply_prototype_source_configs(
        model,
        source_configs,
        cpu_profile=cpu_profile,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
        started_at=started_at,
    )
    emit_telemetry(
        telemetry_callback,
        ConversionPhase.MATERIAL_RESOLUTION,
        message="Applying material policy.",
        started_at=started_at,
    )
    throw_if_cancelled(cancel_event)
    if use_explicit_material_contract:
        model = resolve_material_policy(
            model,
            material_policy=material_policy,
            bark_material_path=bark_material_path,
            leaves_material_path=leaves_material_path,
            single_material_path=single_material_path,
            normalize_asset_path=normalize_unreal_asset_path,
            base_material_overrides=base_material_overrides,
            explicit_part_material_contract=True,
            cpu_profile=cpu_profile,
            cancel_event=cancel_event,
        )
    else:
        model = resolve_prototype_materials(
            model,
            cpu_profile=cpu_profile,
            cancel_event=cancel_event,
        )
        model = _apply_material_policy(
            model,
            material_policy=material_policy,
            bark_material_path=bark_material_path,
            leaves_material_path=leaves_material_path,
            single_material_path=single_material_path,
        )
    if resolved_conversion_mode == ConversionMode.STATIC_ASSEMBLY:
        model = replace(model, prototype_strategy=PrototypeStrategy.INLINE_STATIC_PART)
    model = replace(
        model,
        metadata=replace(
            model.metadata,
            output_mode=output_mode,
            material_policy=material_policy,
            conversion_mode=resolved_conversion_mode,
        ),
    )
    resolved = ResolvedAssemblyModel(
        source_model=source_model,
        authoring_model=model,
        conversion_mode=resolved_conversion_mode,
        output_stem=output_stem,
        source_diagnostics=source_diagnostics if source_diagnostics is not None else validate_source_model(source_model),
    )
    resolution_diagnostics = validate_resolution(resolved)
    authoring_diagnostics = validate_authoring_model(model, conversion_mode=resolved_conversion_mode)
    return replace(
        resolved,
        resolution_diagnostics=resolution_diagnostics,
        authoring_diagnostics=authoring_diagnostics,
    )


def load_resolved_assembly_model(
    input_path: str,
    output_mode: OutputMode = OutputMode.SELF_CONTAINED,
    material_policy: MaterialPolicy = MaterialPolicy.SOURCE_MATERIAL_ROLES,
    bark_material_path: str | None = None,
    leaves_material_path: str | None = None,
    single_material_path: str | None = None,
    base_material_overrides: tuple[BaseMaterialOverride, ...] = (),
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
    use_explicit_material_contract: bool = False,
    prototype_source_configs: tuple[PrototypeSourceConfig, ...] = (),
    use_existing_part_meshes: bool = False,
    part_mesh_asset_paths: tuple[tuple[str, str], ...] = (),
    conversion_mode: ConversionMode | str = ConversionMode.SKELETAL_ASSEMBLY,
    output_stem: str | None = None,
    telemetry_callback=None,
    cancel_event=None,
) -> tuple[ObservedXmlSchemaReport, ResolvedAssemblyModel]:
    """Load XML source facts and resolve them into authoring-ready state."""
    report, source_model, source_diagnostics = load_source_tree_model(
        input_path,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
    )
    resolved = resolve_assembly_model(
        source_model,
        output_mode=output_mode,
        material_policy=material_policy,
        bark_material_path=bark_material_path,
        leaves_material_path=leaves_material_path,
        single_material_path=single_material_path,
        base_material_overrides=base_material_overrides,
        cpu_profile=cpu_profile,
        use_explicit_material_contract=use_explicit_material_contract,
        prototype_source_configs=prototype_source_configs,
        use_existing_part_meshes=use_existing_part_meshes,
        part_mesh_asset_paths=part_mesh_asset_paths,
        conversion_mode=conversion_mode,
        output_stem=output_stem,
        source_diagnostics=source_diagnostics,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
    )
    return report, resolved


def load_canonical_model(
    input_path: str,
    output_mode: OutputMode = OutputMode.SELF_CONTAINED,
    material_policy: MaterialPolicy = MaterialPolicy.SOURCE_MATERIAL_ROLES,
    bark_material_path: str | None = None,
    leaves_material_path: str | None = None,
    single_material_path: str | None = None,
    base_material_overrides: tuple[BaseMaterialOverride, ...] = (),
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
    use_explicit_material_contract: bool = False,
    prototype_source_configs: tuple[PrototypeSourceConfig, ...] = (),
    use_existing_part_meshes: bool = False,
    part_mesh_asset_paths: tuple[tuple[str, str], ...] = (),
    conversion_mode: ConversionMode | str = ConversionMode.SKELETAL_ASSEMBLY,
    telemetry_callback=None,
    cancel_event=None,
) -> tuple[ObservedXmlSchemaReport, CanonicalTreeModel, tuple[ValidationIssue, ...]]:
    """Compatibility wrapper returning the resolved authoring model."""
    report, resolved = load_resolved_assembly_model(
        input_path,
        output_mode=output_mode,
        material_policy=material_policy,
        bark_material_path=bark_material_path,
        leaves_material_path=leaves_material_path,
        single_material_path=single_material_path,
        base_material_overrides=base_material_overrides,
        cpu_profile=cpu_profile,
        use_explicit_material_contract=use_explicit_material_contract,
        prototype_source_configs=prototype_source_configs,
        use_existing_part_meshes=use_existing_part_meshes,
        part_mesh_asset_paths=part_mesh_asset_paths,
        conversion_mode=conversion_mode,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
    )
    return report, resolved.authoring_model, resolved.diagnostics


def _apply_material_policy(
    model: CanonicalTreeModel,
    material_policy: MaterialPolicy,
    bark_material_path: str | None,
    leaves_material_path: str | None,
    single_material_path: str | None,
) -> CanonicalTreeModel:
    """Compatibility helper retained for callers that still import it via `pipeline`."""
    return resolve_material_policy(
        model,
        material_policy=material_policy,
        bark_material_path=bark_material_path,
        leaves_material_path=leaves_material_path,
        single_material_path=single_material_path,
        normalize_asset_path=normalize_unreal_asset_path,
    )
