"""Source and resolved assembly model loading for conversion workflows.

Layer: application/domain boundary.

This module keeps the source-normalized CanonicalTreeModel separate from the
ResolvedAssemblyModel that applies operator intent for authoring.
"""

from __future__ import annotations

import time

from .assembly_resolution import (
    AssemblyResolutionOptions,
    ResolutionRuntime,
    resolve_assembly_model as resolve_assembly_model_from_options,
)
from .asset_paths import normalize_unreal_asset_path
from .job_control import emit_telemetry, throw_if_cancelled
from .material_resolver import apply_material_policy as resolve_material_policy
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
    ResolvedAssemblyModel,
    UdimMaterialSetting,
    ValidationIssue,
)
from .normalizer import normalize_to_canonical
from .source_validation import validate_source_model
from .xml_reader import analyze_xml, read_source_xml


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
    analysis = analyze_xml(document)
    report = analysis.report
    model = normalize_to_canonical(document, report, source_nodes=analysis.source_nodes)
    diagnostics = validate_source_model(model)
    return report, model, diagnostics


def resolve_assembly_model(
    source_model: CanonicalTreeModel,
    *,
    output_mode: OutputMode = OutputMode.SELF_CONTAINED,
    material_policy: MaterialPolicy = MaterialPolicy.SOURCE_MATERIALS,
    bark_material_path: str | None = None,
    leaves_material_path: str | None = None,
    single_material_path: str | None = None,
    base_material_overrides: tuple[BaseMaterialOverride, ...] = (),
    udim_material_settings: tuple[UdimMaterialSetting, ...] = (),
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
    use_explicit_material_contract: bool = False,
    prototype_source_configs: tuple[PrototypeSourceConfig, ...] = (),
    conversion_mode: ConversionMode | str = ConversionMode.SKELETAL_ASSEMBLY,
    output_stem: str | None = None,
    fbx_cache_max_bytes: int = 20 * 1024 * 1024 * 1024,
    fbx_cache_max_age_seconds: int = 14 * 24 * 60 * 60,
    source_diagnostics: tuple[ValidationIssue, ...] | None = None,
    telemetry_callback=None,
    cancel_event=None,
) -> ResolvedAssemblyModel:
    """Compatibility wrapper over the Assembly Resolution Module."""
    return resolve_assembly_model_from_options(
        source_model,
        AssemblyResolutionOptions(
            output_mode=output_mode,
            material_policy=material_policy,
            bark_material_path=bark_material_path,
            leaves_material_path=leaves_material_path,
            single_material_path=single_material_path,
            base_material_overrides=base_material_overrides,
            udim_material_settings=udim_material_settings,
            cpu_profile=cpu_profile,
            use_explicit_material_contract=use_explicit_material_contract,
            prototype_source_configs=prototype_source_configs,
            conversion_mode=conversion_mode,
            output_stem=output_stem,
            fbx_cache_max_bytes=fbx_cache_max_bytes,
            fbx_cache_max_age_seconds=fbx_cache_max_age_seconds,
        ),
        source_diagnostics=source_diagnostics,
        runtime=ResolutionRuntime(
            telemetry_callback=telemetry_callback,
            cancel_event=cancel_event,
        ),
    )


def load_resolved_assembly_model(
    input_path: str,
    output_mode: OutputMode = OutputMode.SELF_CONTAINED,
    material_policy: MaterialPolicy = MaterialPolicy.SOURCE_MATERIALS,
    bark_material_path: str | None = None,
    leaves_material_path: str | None = None,
    single_material_path: str | None = None,
    base_material_overrides: tuple[BaseMaterialOverride, ...] = (),
    udim_material_settings: tuple[UdimMaterialSetting, ...] = (),
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
    use_explicit_material_contract: bool = False,
    prototype_source_configs: tuple[PrototypeSourceConfig, ...] = (),
    conversion_mode: ConversionMode | str = ConversionMode.SKELETAL_ASSEMBLY,
    output_stem: str | None = None,
    fbx_cache_max_bytes: int = 20 * 1024 * 1024 * 1024,
    fbx_cache_max_age_seconds: int = 14 * 24 * 60 * 60,
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
        udim_material_settings=udim_material_settings,
        cpu_profile=cpu_profile,
        use_explicit_material_contract=use_explicit_material_contract,
        prototype_source_configs=prototype_source_configs,
        conversion_mode=conversion_mode,
        output_stem=output_stem,
        fbx_cache_max_bytes=fbx_cache_max_bytes,
        fbx_cache_max_age_seconds=fbx_cache_max_age_seconds,
        source_diagnostics=source_diagnostics,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
    )
    return report, resolved


def load_canonical_model(
    input_path: str,
    output_mode: OutputMode = OutputMode.SELF_CONTAINED,
    material_policy: MaterialPolicy = MaterialPolicy.SOURCE_MATERIALS,
    bark_material_path: str | None = None,
    leaves_material_path: str | None = None,
    single_material_path: str | None = None,
    base_material_overrides: tuple[BaseMaterialOverride, ...] = (),
    udim_material_settings: tuple[UdimMaterialSetting, ...] = (),
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
    use_explicit_material_contract: bool = False,
    prototype_source_configs: tuple[PrototypeSourceConfig, ...] = (),
    conversion_mode: ConversionMode | str = ConversionMode.SKELETAL_ASSEMBLY,
    fbx_cache_max_bytes: int = 20 * 1024 * 1024 * 1024,
    fbx_cache_max_age_seconds: int = 14 * 24 * 60 * 60,
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
        udim_material_settings=udim_material_settings,
        cpu_profile=cpu_profile,
        use_explicit_material_contract=use_explicit_material_contract,
        prototype_source_configs=prototype_source_configs,
        conversion_mode=conversion_mode,
        fbx_cache_max_bytes=fbx_cache_max_bytes,
        fbx_cache_max_age_seconds=fbx_cache_max_age_seconds,
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
