"""Resolved Material Assignment orchestration.

Layer: application/domain seam.

This module chooses the material-resolution path for operator intent. Low-level
material remapping and section algorithms remain in `material_resolver`.
"""

from __future__ import annotations

from dataclasses import dataclass

from .asset_paths import normalize_unreal_asset_path
from .job_control import emit_telemetry, throw_if_cancelled
from .material_resolver import apply_material_policy, resolve_prototype_materials
from .models import (
    BaseMaterialOverride,
    CanonicalTreeModel,
    ConversionPhase,
    CpuProfile,
    MaterialPolicy,
)


@dataclass(frozen=True)
class MaterialAssignmentOptions:
    material_policy: MaterialPolicy = MaterialPolicy.SOURCE_MATERIAL_ROLES
    bark_material_path: str | None = None
    leaves_material_path: str | None = None
    single_material_path: str | None = None
    base_material_overrides: tuple[BaseMaterialOverride, ...] = ()
    use_explicit_material_contract: bool = False


@dataclass(frozen=True)
class MaterialAssignmentRuntime:
    cpu_profile: CpuProfile = CpuProfile.BALANCED
    telemetry_callback: object = None
    cancel_event: object = None
    started_at: float | None = None


def resolve_material_assignments(
    model: CanonicalTreeModel,
    options: MaterialAssignmentOptions,
    *,
    runtime: MaterialAssignmentRuntime | None = None,
) -> CanonicalTreeModel:
    """Apply material operator intent to produce Resolved Material Assignments."""
    runtime = runtime or MaterialAssignmentRuntime()
    emit_telemetry(
        runtime.telemetry_callback,
        ConversionPhase.MATERIAL_RESOLUTION,
        message="Applying material policy.",
        started_at=runtime.started_at,
    )
    throw_if_cancelled(runtime.cancel_event)
    if options.use_explicit_material_contract:
        return apply_material_policy(
            model,
            material_policy=options.material_policy,
            bark_material_path=options.bark_material_path,
            leaves_material_path=options.leaves_material_path,
            single_material_path=options.single_material_path,
            normalize_asset_path=normalize_unreal_asset_path,
            base_material_overrides=options.base_material_overrides,
            explicit_part_material_contract=True,
            cpu_profile=runtime.cpu_profile,
            cancel_event=runtime.cancel_event,
        )

    model = resolve_prototype_materials(
        model,
        cpu_profile=runtime.cpu_profile,
        cancel_event=runtime.cancel_event,
    )
    return apply_material_policy(
        model,
        material_policy=options.material_policy,
        bark_material_path=options.bark_material_path,
        leaves_material_path=options.leaves_material_path,
        single_material_path=options.single_material_path,
        normalize_asset_path=normalize_unreal_asset_path,
    )
