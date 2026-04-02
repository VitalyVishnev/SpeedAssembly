from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from .fbx_adapter import load_fbx_geometry
from .job_control import emit_telemetry, throw_if_cancelled
from .naming import make_stable_prim_name
from .models import (
    CanonicalTreeModel,
    ConversionPhase,
    CpuProfile,
    FbxMaterialMode,
    Prototype,
    PrototypeIdentity,
    PrototypeResolutionMode,
    PrototypeSourceConfig,
    PrototypeSourceMode,
)


def load_prototype_source_configs_from_json(path: str) -> tuple[PrototypeSourceConfig, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Part source config JSON must be an object keyed by prototype name or Mesh_<id>.")

    configs: list[PrototypeSourceConfig] = []
    for raw_key, raw_value in payload.items():
        if not isinstance(raw_value, dict):
            raise ValueError(f"Part source config for {raw_key!r} must be an object.")
        mode = PrototypeSourceMode(str(raw_value.get("mode", PrototypeSourceMode.XML_MESH.value)))
        configs.append(
            PrototypeSourceConfig(
                source_key=str(raw_key),
                source_name=str(raw_value.get("source_name", "")),
                mode=mode,
                fbx_material_mode=FbxMaterialMode(
                    str(raw_value.get("fbx_material_mode", FbxMaterialMode.AUTO.value))
                ),
                asset_path=_coerce_optional_string(raw_value.get("asset_path")),
                fbx_path=_coerce_optional_string(raw_value.get("fbx_path")),
            )
        )
    return tuple(configs)


def merge_legacy_part_mesh_configs(
    prototype_source_configs: tuple[PrototypeSourceConfig, ...],
    use_existing_part_meshes: bool,
    part_mesh_asset_paths: tuple[tuple[str, str], ...],
) -> tuple[PrototypeSourceConfig, ...]:
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


def apply_prototype_source_configs(
    model: CanonicalTreeModel,
    prototype_source_configs: tuple[PrototypeSourceConfig, ...],
    *,
    normalize_asset_path,
    is_valid_unreal_asset_path,
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
    telemetry_callback=None,
    cancel_event=None,
    started_at: float | None = None,
) -> CanonicalTreeModel:
    if not prototype_source_configs:
        return model

    normalized_configs = _normalize_prototype_source_configs(prototype_source_configs, normalize_asset_path, is_valid_unreal_asset_path)
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
            (config.mode, config.fbx_material_mode, config.asset_path, config.fbx_path)
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

    emit_telemetry(
        telemetry_callback,
        ConversionPhase.PROTOTYPE_RESOLUTION,
        completed_units=0,
        total_units=len(model.prototypes),
        message="Resolving prototype source modes.",
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
                    fbx_material_mode=FbxMaterialMode.AUTO,
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
                )
            )
        else:
            if not config.fbx_path:
                raise ValueError(
                    f"Prototype {prototype.identity.prim_name} uses FBX mode but does not provide an fbx_path."
                )
            emit_telemetry(
                telemetry_callback,
                ConversionPhase.FBX_IMPORT,
                completed_units=index - 1,
                total_units=len(model.prototypes),
                message=f"Importing FBX for {Path(config.fbx_path).stem}.",
                started_at=started_at,
            )
            fbx_source_name = Path(config.fbx_path).stem
            fbx_prim_name = _allocate_unique_fbx_prim_name(fbx_source_name, used_prim_names)
            resolved_identity = PrototypeIdentity(
                source_key=prototype.identity.source_key,
                prim_name=fbx_prim_name,
                prototype_type=prototype.identity.prototype_type,
            )
            geometry_payload = load_fbx_geometry(
                config.fbx_path,
                fbx_prim_name,
                cpu_profile=cpu_profile,
                telemetry_callback=telemetry_callback,
                cancel_event=cancel_event,
            )
            prototypes.append(
                replace(
                    prototype,
                    identity=resolved_identity,
                    mesh=None,
                    geometry_payload=geometry_payload,
                    resolution_mode=PrototypeResolutionMode.INLINE_MESH,
                    source_mode=PrototypeSourceMode.FBX_FILE,
                    source_name=fbx_source_name,
                    fbx_material_mode=config.fbx_material_mode,
                    mesh_asset_path=None,
                    fbx_source_path=config.fbx_path,
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


def _normalize_prototype_source_configs(
    prototype_source_configs: tuple[PrototypeSourceConfig, ...],
    normalize_asset_path,
    is_valid_unreal_asset_path,
) -> dict[str, PrototypeSourceConfig]:
    overrides: dict[str, PrototypeSourceConfig] = {}
    for config in prototype_source_configs:
        source_key = normalize_prototype_override_key(config.source_name or config.source_key)
        if not source_key:
            raise ValueError("Prototype source config keys must not be empty.")

        normalized = config
        if config.mode == PrototypeSourceMode.UNREAL_ASSET:
            asset_path = normalize_asset_path(config.asset_path or "")
            if not is_valid_unreal_asset_path(asset_path):
                raise ValueError(f"PartMesh asset path for {source_key} must start with /Game/.")
            normalized = replace(config, asset_path=asset_path)
        elif config.mode == PrototypeSourceMode.FBX_FILE:
            if not config.fbx_path:
                raise ValueError(f"Prototype source config for {source_key} is missing fbx_path.")
            fbx_path = str(Path(config.fbx_path).expanduser().resolve())
            if not Path(fbx_path).exists():
                raise ValueError(f"FBX file for {source_key} does not exist: {fbx_path}")
            normalized = replace(config, fbx_path=fbx_path)

        existing = overrides.get(source_key)
        if existing is not None and existing != normalized:
            raise ValueError(f"Duplicate prototype source config for {source_key} uses conflicting values.")
        overrides[source_key] = normalized
    return overrides


def normalize_prototype_override_key(raw_key: str) -> str:
    key = raw_key.strip()
    if not key:
        return ""
    lower_key = key.lower()
    for prefix in ("mesh_", "meshid:", "mesh_id:"):
        if lower_key.startswith(prefix) and key[len(prefix):].strip().isdigit():
            return f"Mesh_{int(key[len(prefix):].strip())}"
    if key.isdigit():
        return f"Mesh_{int(key)}"
    return key


def _coerce_optional_string(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _allocate_unique_fbx_prim_name(source_name: str, used_prim_names: set[str]) -> str:
    base_name = make_stable_prim_name(source_name, fallback="Prototype")
    candidate = base_name
    suffix = 2
    while candidate in used_prim_names:
        candidate = f"{base_name}_{suffix}"
        suffix += 1
    used_prim_names.add(candidate)
    return candidate
