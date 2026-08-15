"""Resolved Assembly Model construction.

Layer: application/domain seam.

This module combines source facts with Operator Intent and produces the
authoring-stage ResolvedAssemblyModel.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace

from .material_assignment_resolution import (
    MaterialAssignmentOptions,
    MaterialAssignmentRuntime,
    resolve_material_assignments,
)
from .models import (
    BaseMaterialOverride,
    CanonicalTreeModel,
    ConversionMode,
    CpuProfile,
    MaterialPolicy,
    OutputMode,
    PrototypeSourceConfig,
    PrototypeStrategy,
    ResolvedAssemblyModel,
    ScatteredRigMode,
    SkinningQuality,
    UdimMaterialSetting,
    ValidationIssue,
)
from .prototype_resolution import (
    PrototypePayloadLoader,
    resolve_prototype_sources,
)
from .prototype_simplification import simplify_resolved_prototypes
from .authoring_validation import validate_authoring_model
from .resolution_validation import validate_resolution
from .source_validation import validate_source_model
from .scattered_parts import analyze_scattered_parts, apply_scattered_parts_rig
from .skeleton_processing import apply_skinning_quality
from .udim_resolver import apply_udim_settings_to_mesh_data


@dataclass(frozen=True)
class AssemblyResolutionOptions:
    output_mode: OutputMode = OutputMode.SELF_CONTAINED
    material_policy: MaterialPolicy = MaterialPolicy.SOURCE_MATERIALS
    bark_material_path: str | None = None
    leaves_material_path: str | None = None
    single_material_path: str | None = None
    base_material_overrides: tuple[BaseMaterialOverride, ...] = ()
    udim_material_settings: tuple[UdimMaterialSetting, ...] = ()
    cpu_profile: CpuProfile = CpuProfile.BALANCED
    use_explicit_material_contract: bool = False
    prototype_source_configs: tuple[PrototypeSourceConfig, ...] = ()
    conversion_mode: ConversionMode | str = ConversionMode.SKELETAL_ASSEMBLY
    skinning_quality: SkinningQuality | int = SkinningQuality.ONE_WEIGHT
    scattered_rig_mode: ScatteredRigMode | str = ScatteredRigMode.PER_CLUSTER_SKINNED
    orient_scattered_bones_from_instances: bool = False
    output_stem: str | None = None
    fbx_cache_max_bytes: int = 20 * 1024 * 1024 * 1024
    fbx_cache_max_age_seconds: int = 14 * 24 * 60 * 60

    def material_assignment_options(self) -> MaterialAssignmentOptions:
        return MaterialAssignmentOptions(
            material_policy=self.material_policy,
            bark_material_path=self.bark_material_path,
            leaves_material_path=self.leaves_material_path,
            single_material_path=self.single_material_path,
            base_material_overrides=self.base_material_overrides,
            use_explicit_material_contract=self.use_explicit_material_contract,
        )


@dataclass(frozen=True)
class ResolutionRuntime:
    telemetry_callback: object = None
    cancel_event: object = None
    started_at: float | None = None
    prototype_payload_loader: PrototypePayloadLoader | None = None


def resolve_assembly_model(
    source_model: CanonicalTreeModel,
    options: AssemblyResolutionOptions,
    *,
    source_diagnostics: tuple[ValidationIssue, ...] | None = None,
    runtime: ResolutionRuntime | None = None,
) -> ResolvedAssemblyModel:
    """Resolve source facts plus Operator Intent into authoring-ready state."""
    runtime = runtime or ResolutionRuntime()
    started_at = runtime.started_at if runtime.started_at is not None else time.perf_counter()
    runtime = replace(runtime, started_at=started_at)
    resolved_conversion_mode = ConversionMode.parse(options.conversion_mode)
    working_source_model = replace(
        source_model,
        base_mesh=apply_udim_settings_to_mesh_data(
            source_model.base_mesh,
            options.udim_material_settings,
            label="Base Skeletal Tree",
        ),
    )

    authoring_model = resolve_prototype_sources(
        working_source_model,
        options.prototype_source_configs,
        cpu_profile=options.cpu_profile,
        telemetry_callback=runtime.telemetry_callback,
        cancel_event=runtime.cancel_event,
        started_at=runtime.started_at,
        payload_loader=runtime.prototype_payload_loader,
        fbx_cache_max_bytes=options.fbx_cache_max_bytes,
        fbx_cache_max_age_seconds=options.fbx_cache_max_age_seconds,
    )
    authoring_model = resolve_material_assignments(
        authoring_model,
        options.material_assignment_options(),
        runtime=MaterialAssignmentRuntime(
            cpu_profile=options.cpu_profile,
            telemetry_callback=runtime.telemetry_callback,
            cancel_event=runtime.cancel_event,
            started_at=runtime.started_at,
        ),
    )
    authoring_model = simplify_resolved_prototypes(
        authoring_model,
        cancel_event=runtime.cancel_event,
    )
    if resolved_conversion_mode == ConversionMode.SKELETAL_ASSEMBLY:
        if analyze_scattered_parts(authoring_model).eligible:
            authoring_model = apply_scattered_parts_rig(
                authoring_model,
                options.scattered_rig_mode,
                orient_bones_from_instances=options.orient_scattered_bones_from_instances,
            )
        else:
            authoring_model = apply_skinning_quality(
                authoring_model,
                skinning_quality=options.skinning_quality,
            )
    if resolved_conversion_mode in {ConversionMode.STATIC_ASSEMBLY, ConversionMode.STATIC_PARTS}:
        authoring_model = replace(authoring_model, prototype_strategy=PrototypeStrategy.INLINE_STATIC_PART)
    authoring_model = replace(
        authoring_model,
        metadata=replace(
            authoring_model.metadata,
            output_mode=options.output_mode,
            material_policy=options.material_policy,
            conversion_mode=resolved_conversion_mode,
        ),
    )
    resolved = ResolvedAssemblyModel(
        source_model=source_model,
        authoring_model=authoring_model,
        conversion_mode=resolved_conversion_mode,
        output_stem=options.output_stem,
        udim_material_settings=options.udim_material_settings,
        source_diagnostics=source_diagnostics if source_diagnostics is not None else validate_source_model(source_model),
    )
    resolution_diagnostics = validate_resolution(resolved)
    authoring_diagnostics = validate_authoring_model(authoring_model, conversion_mode=resolved_conversion_mode)
    return replace(
        resolved,
        resolution_diagnostics=resolution_diagnostics,
        authoring_diagnostics=authoring_diagnostics,
    )
