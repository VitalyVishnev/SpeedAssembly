"""Resolved Prototype projection from source facts plus operator intent.

Layer: application/domain seam.

This module owns Prototype Source matching and Resolved Prototype projection.
FBX payload loading is supplied through an adapter so runtime-specific FBX
Helper behavior stays in infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from .asset_paths import is_valid_unreal_asset_path, normalize_unreal_asset_path
from .job_control import emit_telemetry, throw_if_cancelled
from .models import (
    CanonicalTreeModel,
    ConversionPhase,
    CpuProfile,
    FbxMaterialMode,
    FbxMaterialSlotOverride,
    Prototype,
    PrototypeIdentity,
    PrototypeResolutionMode,
    PrototypeSourceConfig,
    PrototypeSourceMode,
)
from .naming import make_stable_prim_name
from .prototype_keys import normalize_prototype_source_key


@dataclass(frozen=True)
class _PreparedFbxImport:
    prototype_index: int
    original_prototype: Prototype
    config: PrototypeSourceConfig
    resolved_identity: PrototypeIdentity
    resolved_source_name: str


class PrototypePayloadLoader(Protocol):
    def __call__(
        self,
        prepared_imports: tuple[_PreparedFbxImport, ...],
        *,
        cpu_profile: CpuProfile,
        telemetry_callback=None,
        cancel_event=None,
        started_at: float | None = None,
    ) -> dict[int, object]:
        ...


def merge_legacy_part_mesh_configs(
    prototype_source_configs: tuple[PrototypeSourceConfig, ...],
    use_existing_part_meshes: bool,
    part_mesh_asset_paths: tuple[tuple[str, str], ...],
) -> tuple[PrototypeSourceConfig, ...]:
    """Translate legacy PartMesh mappings into Prototype Source configs."""
    if not use_existing_part_meshes or not part_mesh_asset_paths:
        return prototype_source_configs

    legacy_configs = tuple(
        PrototypeSourceConfig(
            source_key=source_key,
            mode=PrototypeSourceMode.UNREAL_ASSET,
            asset_path=asset_path,
        )
        for source_key, asset_path in part_mesh_asset_paths
    )
    return prototype_source_configs + legacy_configs


def resolve_prototype_sources(
    model: CanonicalTreeModel,
    prototype_source_configs: tuple[PrototypeSourceConfig, ...],
    *,
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
    telemetry_callback=None,
    cancel_event=None,
    started_at: float | None = None,
    payload_loader: PrototypePayloadLoader | None = None,
) -> CanonicalTreeModel:
    """Resolve Source Prototypes into Resolved Prototypes."""
    if not prototype_source_configs:
        return model

    normalized_configs = _normalize_prototype_source_configs(prototype_source_configs)
    metadata = model.metadata
    used_keys: set[str] = set()
    matched_configs: list[PrototypeSourceConfig | None] = []
    prototypes: list[Prototype] = []

    for prototype in model.prototypes:
        matching_configs = [
            (lookup_key, normalized_configs[lookup_key])
            for lookup_key in (prototype.source_name, prototype.source_key)
            if lookup_key and lookup_key in normalized_configs
        ]
        distinct_configs = {
            (
                config.mode,
                config.fbx_material_mode,
                config.asset_path,
                config.fbx_path,
                config.single_material_path,
                config.single_material_udim_mode,
                config.single_material_udim_id,
                config.black_material_path,
                config.black_material_udim_mode,
                config.black_material_udim_id,
                config.white_material_path,
                config.white_material_udim_mode,
                config.white_material_udim_id,
                config.fbx_material_slot_overrides,
            )
            for _lookup_key, config in matching_configs
        }
        if len(distinct_configs) > 1:
            raise ValueError(
                "Conflicting source configurations found for prototype "
                f"{prototype.source_name or prototype.source_key}."
            )
        matched_configs.append(matching_configs[0][1] if matching_configs else None)

    used_prim_names = {
        prototype.identity.prim_name
        for prototype, config in zip(model.prototypes, matched_configs, strict=True)
        if config is None or config.mode != PrototypeSourceMode.FBX_FILE
    }
    prepared_fbx_imports: dict[int, _PreparedFbxImport] = {}
    for prototype_index, (prototype, config) in enumerate(zip(model.prototypes, matched_configs, strict=True)):
        if config is None or config.mode != PrototypeSourceMode.FBX_FILE:
            continue
        if not config.fbx_path:
            raise ValueError(
                f"Prototype {prototype.identity.prim_name} uses FBX mode but does not provide an fbx_path."
            )
        fbx_source_name = Path(config.fbx_path).stem
        fbx_prim_name = _allocate_unique_fbx_prim_name(fbx_source_name, used_prim_names)
        prepared_fbx_imports[prototype_index] = _PreparedFbxImport(
            prototype_index=prototype_index,
            original_prototype=prototype,
            config=config,
            resolved_identity=PrototypeIdentity(
                source_key=prototype.identity.source_key,
                prim_name=fbx_prim_name,
                prototype_type=prototype.identity.prototype_type,
            ),
            resolved_source_name=fbx_source_name,
        )

    emit_telemetry(
        telemetry_callback,
        ConversionPhase.PROTOTYPE_RESOLUTION,
        completed_units=0,
        total_units=len(model.prototypes),
        message="Resolving prototype source modes.",
        started_at=started_at,
    )
    load_payloads = payload_loader or _default_payload_loader
    fbx_payloads_by_index = load_payloads(
        tuple(prepared_fbx_imports.values()),
        cpu_profile=cpu_profile,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
        started_at=started_at,
    )

    for index, (prototype, config) in enumerate(zip(model.prototypes, matched_configs, strict=True), start=1):
        throw_if_cancelled(cancel_event)
        if config is None:
            prototypes.append(replace(prototype, source_mode=PrototypeSourceMode.XML_MESH))
            emit_telemetry(
                telemetry_callback,
                ConversionPhase.PROTOTYPE_RESOLUTION,
                completed_units=index,
                total_units=len(model.prototypes),
                message=f"Resolved prototype {prototype.identity.prim_name}.",
                started_at=started_at,
            )
            continue

        used_keys.update(
            lookup_key
            for lookup_key in (prototype.source_name, prototype.source_key)
            if lookup_key and lookup_key in normalized_configs
        )
        if config.mode == PrototypeSourceMode.XML_MESH:
            prototypes.append(
                replace(
                    prototype,
                    source_mode=PrototypeSourceMode.XML_MESH,
                    resolution_mode=PrototypeResolutionMode.INLINE_MESH,
                    mesh_asset_path=None,
                    fbx_source_path=None,
                    fbx_material_mode=config.fbx_material_mode,
                    single_material_path=config.single_material_path,
                    single_material_udim_mode=config.single_material_udim_mode,
                    single_material_udim_id=config.single_material_udim_id,
                    black_material_path=config.black_material_path,
                    black_material_udim_mode=config.black_material_udim_mode,
                    black_material_udim_id=config.black_material_udim_id,
                    white_material_path=config.white_material_path,
                    white_material_udim_mode=config.white_material_udim_mode,
                    white_material_udim_id=config.white_material_udim_id,
                    fbx_material_slot_overrides=config.fbx_material_slot_overrides,
                    geometry_payload=None,
                )
            )
        elif config.mode == PrototypeSourceMode.UNREAL_ASSET:
            prototypes.append(
                replace(
                    prototype,
                    mesh=None,
                    geometry_payload=None,
                    resolution_mode=PrototypeResolutionMode.EXTERNAL_ASSET,
                    source_mode=PrototypeSourceMode.UNREAL_ASSET,
                    fbx_material_mode=FbxMaterialMode.AUTO,
                    mesh_asset_path=config.asset_path,
                    fbx_source_path=None,
                    single_material_path=None,
                    single_material_udim_mode=config.single_material_udim_mode,
                    single_material_udim_id=config.single_material_udim_id,
                    black_material_path=None,
                    black_material_udim_mode=config.black_material_udim_mode,
                    black_material_udim_id=config.black_material_udim_id,
                    white_material_path=None,
                    white_material_udim_mode=config.white_material_udim_mode,
                    white_material_udim_id=config.white_material_udim_id,
                    fbx_material_slot_overrides=(),
                )
            )
        else:
            prepared_import = prepared_fbx_imports[index - 1]
            geometry_payload = fbx_payloads_by_index[index - 1]
            prototypes.append(
                replace(
                    prototype,
                    identity=prepared_import.resolved_identity,
                    mesh=None,
                    geometry_payload=geometry_payload,
                    resolution_mode=PrototypeResolutionMode.INLINE_MESH,
                    source_mode=PrototypeSourceMode.FBX_FILE,
                    source_name=prepared_import.resolved_source_name,
                    fbx_material_mode=config.fbx_material_mode,
                    mesh_asset_path=None,
                    fbx_source_path=config.fbx_path,
                    single_material_path=config.single_material_path,
                    single_material_udim_mode=config.single_material_udim_mode,
                    single_material_udim_id=config.single_material_udim_id,
                    black_material_path=config.black_material_path,
                    black_material_udim_mode=config.black_material_udim_mode,
                    black_material_udim_id=config.black_material_udim_id,
                    white_material_path=config.white_material_path,
                    white_material_udim_mode=config.white_material_udim_mode,
                    white_material_udim_id=config.white_material_udim_id,
                    fbx_material_slot_overrides=config.fbx_material_slot_overrides,
                )
            )

        emit_telemetry(
            telemetry_callback,
            ConversionPhase.PROTOTYPE_RESOLUTION,
            completed_units=index,
            total_units=len(model.prototypes),
            message=f"Resolved prototype {prototype.identity.prim_name}.",
            started_at=started_at,
        )

    unused_keys = sorted(set(normalized_configs) - used_keys)
    model = replace(model, prototypes=tuple(prototypes), metadata=metadata)

    if unused_keys:
        metadata = model.metadata
        metadata = replace(
            metadata,
            warnings=metadata.warnings + tuple(
                f"Unused prototype source config ignored: {source_key}" for source_key in unused_keys
            ),
        )
        model = replace(model, metadata=metadata)
    return model


def _default_payload_loader(
    prepared_imports: tuple[_PreparedFbxImport, ...],
    *,
    cpu_profile: CpuProfile,
    telemetry_callback=None,
    cancel_event=None,
    started_at: float | None = None,
) -> dict[int, object]:
    from .prototype_sources import load_fbx_payloads_for_prototype_resolution

    return load_fbx_payloads_for_prototype_resolution(
        prepared_imports,
        cpu_profile=cpu_profile,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
        started_at=started_at,
    )


def _normalize_prototype_source_configs(
    prototype_source_configs: tuple[PrototypeSourceConfig, ...],
) -> dict[str, PrototypeSourceConfig]:
    overrides: dict[str, PrototypeSourceConfig] = {}
    for config in prototype_source_configs:
        source_key = normalize_prototype_source_key(config.source_name or config.source_key)
        if not source_key:
            raise ValueError("Prototype source config keys must not be empty.")

        normalized = replace(
            config,
            single_material_path=normalize_unreal_asset_path(config.single_material_path)
            if config.single_material_path
            else None,
            black_material_path=normalize_unreal_asset_path(config.black_material_path)
            if config.black_material_path
            else None,
            white_material_path=normalize_unreal_asset_path(config.white_material_path)
            if config.white_material_path
            else None,
            fbx_material_slot_overrides=tuple(
                FbxMaterialSlotOverride(
                    slot_name=override.slot_name,
                    ue_asset_path=normalize_unreal_asset_path(override.ue_asset_path)
                    if override.ue_asset_path
                    else None,
                )
                for override in config.fbx_material_slot_overrides
            ),
        )
        if config.mode == PrototypeSourceMode.UNREAL_ASSET:
            asset_path = normalize_unreal_asset_path(config.asset_path or "")
            if not is_valid_unreal_asset_path(asset_path):
                raise ValueError(f"PartMesh asset path for {source_key} must start with /Game/.")
            normalized = replace(normalized, asset_path=asset_path)
        elif config.mode == PrototypeSourceMode.FBX_FILE:
            if not config.fbx_path:
                raise ValueError(f"Prototype source config for {source_key} is missing fbx_path.")
            fbx_path = str(Path(config.fbx_path).expanduser().resolve())
            if not Path(fbx_path).exists():
                raise ValueError(f"FBX file for {source_key} does not exist: {fbx_path}")
            normalized = replace(normalized, fbx_path=fbx_path)

        existing = overrides.get(source_key)
        if existing is not None and existing != normalized:
            raise ValueError(f"Duplicate prototype source config for {source_key} uses conflicting values.")
        overrides[source_key] = normalized
    return overrides


def _allocate_unique_fbx_prim_name(source_name: str, used_prim_names: set[str]) -> str:
    base_name = make_stable_prim_name(source_name, fallback="Prototype")
    candidate = base_name
    suffix = 2
    while candidate in used_prim_names:
        candidate = f"{base_name}_{suffix}"
        suffix += 1
    used_prim_names.add(candidate)
    return candidate
