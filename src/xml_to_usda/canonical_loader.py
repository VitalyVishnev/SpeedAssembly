"""Canonical model loading from source XML through validated tree assets.

Layer: application/domain boundary.

This module coordinates reading, schema inspection, normalization, prototype
source resolution, material resolution, and final model validation to produce
the canonical tree model consumed by downstream exporters.
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
)
from .normalizer import normalize_to_canonical
from .prototype_sources import apply_prototype_source_configs, merge_legacy_part_mesh_configs
from .validator import validate_model
from .xml_reader import inspect_xml, read_source_xml


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
    conversion_mode: ConversionMode = ConversionMode.SKELETAL_ASSEMBLY,
    telemetry_callback=None,
    cancel_event=None,
) -> tuple[ObservedXmlSchemaReport, CanonicalTreeModel, tuple]:
    """Load one XML source into the canonical tree model plus diagnostics."""
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
    model = replace(
        model,
        metadata=replace(
            model.metadata,
            output_mode=output_mode,
            material_policy=material_policy,
            conversion_mode=conversion_mode,
        ),
    )
    diagnostics = validate_model(model, conversion_mode=conversion_mode)
    return report, model, diagnostics


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
