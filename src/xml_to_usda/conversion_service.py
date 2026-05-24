"""Application-facing request planning for conversion launches.

Layer: application.

This service translates UI/CLI semantic inputs into one stable
`ConversionRequest` contract and decides the runtime launch strategy. It should
not depend on widget trees, runtime workspaces, or USDA authoring details.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .asset_paths import is_valid_unreal_asset_path, normalize_unreal_asset_path
from .models import (
    BaseMaterialOverride,
    CleanupPolicy,
    ConversionMode,
    ConversionRequest,
    CpuProfile,
    FbxMaterialMode,
    MaterialPolicy,
    OutputMode,
    PrototypeSourceConfig,
    PrototypeSourceMode,
    UdimMaterialSetting,
)


@dataclass(frozen=True)
class ConversionLaunchPlan:
    """A fully prepared conversion request plus the chosen execution mode."""
    request: ConversionRequest
    run_async: bool


def prepare_conversion_plan(
    *,
    input_path: str,
    output_path: str,
    cpu_profile: CpuProfile,
    cleanup_policy: CleanupPolicy,
    material_policy: MaterialPolicy,
    bark_material_path: str | None,
    leaves_material_path: str | None,
    single_material_path: str | None,
    base_material_overrides: tuple[BaseMaterialOverride, ...],
    prototype_source_configs: tuple[PrototypeSourceConfig, ...],
    use_existing_part_meshes: bool,
    part_mesh_asset_paths: tuple[tuple[str, str], ...],
    async_threshold_bytes: int,
    conversion_mode: ConversionMode | str = ConversionMode.SKELETAL_ASSEMBLY,
    udim_material_settings: tuple[UdimMaterialSetting, ...] = (),
) -> ConversionLaunchPlan:
    """Build one stable conversion plan from operator-facing semantic inputs."""
    resolved_input_path = input_path.strip()
    resolved_output_path = output_path.strip()
    if not resolved_input_path:
        raise ValueError("Select a source XML file.")
    if not resolved_output_path:
        raise ValueError("Select an output USDA path.")

    effective_bark_material_path = bark_material_path.strip() if bark_material_path else None
    effective_leaves_material_path = leaves_material_path.strip() if leaves_material_path else None
    effective_single_material_path = single_material_path.strip() if single_material_path else None

    if material_policy == MaterialPolicy.SINGLE_MATERIAL:
        effective_bark_material_path = None
        effective_leaves_material_path = None
    else:
        effective_single_material_path = None
    resolved_conversion_mode = ConversionMode.parse(conversion_mode)

    use_explicit_material_contract = _should_use_explicit_material_contract(
        base_material_overrides,
        prototype_source_configs,
    )
    if use_explicit_material_contract:
        _validate_explicit_material_contract(
            base_material_overrides=base_material_overrides,
            prototype_source_configs=prototype_source_configs,
        )
    else:
        _validate_material_policy_paths(
            material_policy=material_policy,
            bark_material_path=effective_bark_material_path,
            leaves_material_path=effective_leaves_material_path,
            single_material_path=effective_single_material_path,
        )

    request = ConversionRequest(
        input_paths=(resolved_input_path,),
        output_path=resolved_output_path,
        output_mode=OutputMode.SELF_CONTAINED,
        material_policy=material_policy,
        bark_material_path=effective_bark_material_path,
        leaves_material_path=effective_leaves_material_path,
        single_material_path=effective_single_material_path,
        base_material_overrides=base_material_overrides,
        udim_material_settings=udim_material_settings,
        cpu_profile=cpu_profile,
        cleanup_policy=cleanup_policy,
        use_explicit_material_contract=use_explicit_material_contract,
        prototype_source_configs=prototype_source_configs,
        use_existing_part_meshes=use_existing_part_meshes,
        part_mesh_asset_paths=part_mesh_asset_paths,
        conversion_mode=resolved_conversion_mode,
    )
    return ConversionLaunchPlan(
        request=request,
        run_async=_should_run_async(
            input_path=resolved_input_path,
            prototype_source_configs=prototype_source_configs,
            async_threshold_bytes=async_threshold_bytes,
        ),
    )


def _should_use_explicit_material_contract(
    base_material_overrides: tuple[BaseMaterialOverride, ...],
    prototype_source_configs: tuple[PrototypeSourceConfig, ...],
) -> bool:
    if any(override.ue_asset_path for override in base_material_overrides):
        return True
    for config in prototype_source_configs:
        if config.mode == PrototypeSourceMode.UNREAL_ASSET:
            continue
        if config.fbx_material_mode != FbxMaterialMode.VERTEX_COLOR_SPLIT:
            return True
        if config.single_material_path or config.black_material_path or config.white_material_path:
            return True
        if config.mode == PrototypeSourceMode.FBX_FILE:
            return True
    return False


def _validate_material_policy_paths(
    *,
    material_policy: MaterialPolicy,
    bark_material_path: str | None,
    leaves_material_path: str | None,
    single_material_path: str | None,
) -> None:
    checks: list[tuple[str, str | None]]
    if material_policy == MaterialPolicy.SINGLE_MATERIAL:
        checks = [("Single", single_material_path)]
    else:
        checks = [("Bark", bark_material_path), ("Leaves", leaves_material_path)]
    for label, path in checks:
        if not path:
            continue
        if not is_valid_unreal_asset_path(normalize_unreal_asset_path(path)):
            raise ValueError(f"{label} material path must start with /Game/.")


def _validate_explicit_material_contract(
    *,
    base_material_overrides: tuple[BaseMaterialOverride, ...],
    prototype_source_configs: tuple[PrototypeSourceConfig, ...],
) -> None:
    for override in base_material_overrides:
        if not override.ue_asset_path:
            continue
        if not is_valid_unreal_asset_path(normalize_unreal_asset_path(override.ue_asset_path)):
            raise ValueError(
                f"Base XML material path for {override.source_name} (ID {override.source_id}) must start with /Game/."
            )
    for config in prototype_source_configs:
        source_name = config.source_name or config.source_key
        if config.mode == PrototypeSourceMode.UNREAL_ASSET:
            if config.asset_path and not is_valid_unreal_asset_path(normalize_unreal_asset_path(config.asset_path)):
                raise ValueError(f"PartMesh asset path for {source_name} must start with /Game/.")
            continue
        if config.fbx_material_mode == FbxMaterialMode.SINGLE_MATERIAL:
            if config.single_material_path and not is_valid_unreal_asset_path(
                normalize_unreal_asset_path(config.single_material_path)
            ):
                raise ValueError(f"Single material path for {source_name} must start with /Game/.")
            continue
        if config.fbx_material_mode == FbxMaterialMode.MATERIAL_SLOTS:
            if config.mode == PrototypeSourceMode.FBX_FILE and not any(
                override.ue_asset_path for override in config.fbx_material_slot_overrides
            ):
                raise ValueError(
                    f"Material Slots mode for {source_name} requires at least one Unreal material path "
                    "in the discovered FBX material slots."
                )
            for override in config.fbx_material_slot_overrides:
                if override.ue_asset_path and not is_valid_unreal_asset_path(
                    normalize_unreal_asset_path(override.ue_asset_path)
                ):
                    raise ValueError(
                        f"FBX material slot path for {source_name} slot {override.slot_name} "
                        "must start with /Game/."
                    )
            continue
        for label, value in (("Black", config.black_material_path), ("White", config.white_material_path)):
            if value and not is_valid_unreal_asset_path(normalize_unreal_asset_path(value)):
                raise ValueError(f"{label} material path for {source_name} must start with /Game/.")


def _should_run_async(
    *,
    input_path: str,
    prototype_source_configs: tuple[PrototypeSourceConfig, ...],
    async_threshold_bytes: int,
) -> bool:
    if any(config.mode == PrototypeSourceMode.FBX_FILE for config in prototype_source_configs):
        return True
    try:
        return Path(input_path).stat().st_size >= async_threshold_bytes
    except OSError:
        return False
