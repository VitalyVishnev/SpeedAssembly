from __future__ import annotations

import multiprocessing
import sys
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
import json
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path

from .fbx_adapter import load_fbx_geometry
from .job_control import cpu_worker_count, emit_telemetry, throw_if_cancelled
from .naming import make_stable_prim_name
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


@dataclass(frozen=True)
class _PreparedFbxImport:
    prototype_index: int
    original_prototype: Prototype
    config: PrototypeSourceConfig
    resolved_identity: PrototypeIdentity
    resolved_source_name: str


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
                single_material_path=_coerce_optional_string(raw_value.get("single_material_path")),
                black_material_path=_coerce_optional_string(raw_value.get("black_material_path")),
                white_material_path=_coerce_optional_string(raw_value.get("white_material_path")),
                fbx_material_slot_overrides=_load_fbx_material_slot_overrides(
                    raw_value.get("fbx_material_slot_overrides")
                ),
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
            (
                config.mode,
                config.fbx_material_mode,
                config.asset_path,
                config.fbx_path,
                config.single_material_path,
                config.black_material_path,
                config.white_material_path,
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
    fbx_payloads_by_index = _load_fbx_payloads(
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
                    black_material_path=config.black_material_path,
                    white_material_path=config.white_material_path,
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
                    black_material_path=None,
                    white_material_path=None,
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
                    black_material_path=config.black_material_path,
                    white_material_path=config.white_material_path,
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

        normalized = replace(
            config,
            single_material_path=normalize_asset_path(config.single_material_path) if config.single_material_path else None,
            black_material_path=normalize_asset_path(config.black_material_path) if config.black_material_path else None,
            white_material_path=normalize_asset_path(config.white_material_path) if config.white_material_path else None,
            fbx_material_slot_overrides=tuple(
                FbxMaterialSlotOverride(
                    slot_name=override.slot_name,
                    ue_asset_path=normalize_asset_path(override.ue_asset_path)
                    if override.ue_asset_path
                    else None,
                )
                for override in config.fbx_material_slot_overrides
            ),
        )
        if config.mode == PrototypeSourceMode.UNREAL_ASSET:
            asset_path = normalize_asset_path(config.asset_path or "")
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


def _load_fbx_material_slot_overrides(raw_value) -> tuple[FbxMaterialSlotOverride, ...]:
    if raw_value is None or raw_value == "":
        return ()
    if not isinstance(raw_value, list):
        raise ValueError("fbx_material_slot_overrides must be a list of objects.")
    overrides: list[FbxMaterialSlotOverride] = []
    seen_names: set[str] = set()
    for raw_override in raw_value:
        if not isinstance(raw_override, dict):
            raise ValueError("Each FBX material slot override must be an object.")
        slot_name = _coerce_optional_string(raw_override.get("slot_name"))
        if not slot_name:
            raise ValueError("FBX material slot override is missing slot_name.")
        if slot_name in seen_names:
            raise ValueError(f"Duplicate FBX material slot override for {slot_name}.")
        seen_names.add(slot_name)
        overrides.append(
            FbxMaterialSlotOverride(
                slot_name=slot_name,
                ue_asset_path=_coerce_optional_string(raw_override.get("ue_asset_path")),
            )
        )
    return tuple(overrides)


def _allocate_unique_fbx_prim_name(source_name: str, used_prim_names: set[str]) -> str:
    base_name = make_stable_prim_name(source_name, fallback="Prototype")
    candidate = base_name
    suffix = 2
    while candidate in used_prim_names:
        candidate = f"{base_name}_{suffix}"
        suffix += 1
    used_prim_names.add(candidate)
    return candidate


def _load_fbx_payloads(
    prepared_imports: tuple[_PreparedFbxImport, ...],
    *,
    cpu_profile: CpuProfile,
    telemetry_callback=None,
    cancel_event=None,
    started_at: float | None = None,
):
    if not prepared_imports:
        return {}

    # Parallelism here is intentionally coarse-grained: separate prototype imports
    # can overlap, but one Autodesk FBX scene import still largely runs as a
    # single worker. Low total CPU on a huge one- or two-prototype job is
    # therefore expected and not, by itself, a defect.
    if _frozen_runtime_requires_sequential_fbx_import() and len(prepared_imports) > 1:
        emit_telemetry(
            telemetry_callback,
            ConversionPhase.FBX_IMPORT,
            completed_units=0,
            total_units=len(prepared_imports),
            message=(
                "Frozen package mode uses sequential FBX prototype import for stability. "
                "Launcher/dev runs may still import multiple prototypes in parallel."
            ),
            started_at=started_at,
        )
        return _load_fbx_payloads_sequential(
            prepared_imports,
            cpu_profile=cpu_profile,
            telemetry_callback=telemetry_callback,
            cancel_event=cancel_event,
            started_at=started_at,
        )
    worker_count = min(len(prepared_imports), max(1, cpu_worker_count(cpu_profile)))
    if worker_count <= 1 or len(prepared_imports) <= 1:
        return _load_fbx_payloads_sequential(
            prepared_imports,
            cpu_profile=cpu_profile,
            telemetry_callback=telemetry_callback,
            cancel_event=cancel_event,
            started_at=started_at,
        )
    emit_telemetry(
        telemetry_callback,
        ConversionPhase.FBX_IMPORT,
        completed_units=0,
        total_units=len(prepared_imports),
        message=(
            f"Importing {len(prepared_imports)} FBX prototype(s) "
            f"using {worker_count} worker process(es)."
        ),
        started_at=started_at,
    )
    try:
        executor = ProcessPoolExecutor(
            max_workers=worker_count,
            mp_context=multiprocessing.get_context("spawn"),
        )
    except (OSError, PermissionError):
        emit_telemetry(
            telemetry_callback,
            ConversionPhase.FBX_IMPORT,
            completed_units=0,
            total_units=len(prepared_imports),
            message=(
                "FBX worker pool is unavailable in this environment. "
                "Falling back to sequential prototype import."
            ),
            started_at=started_at,
        )
        return _load_fbx_payloads_sequential(
            prepared_imports,
            cpu_profile=cpu_profile,
            telemetry_callback=telemetry_callback,
            cancel_event=cancel_event,
            started_at=started_at,
        )
    futures = {
        executor.submit(
            _load_fbx_payload_worker,
            prepared_import.config.fbx_path or "",
            prepared_import.resolved_identity.prim_name,
            cpu_profile.value,
            prepared_import.config.fbx_material_mode == FbxMaterialMode.VERTEX_COLOR_SPLIT,
        ): prepared_import
        for prepared_import in prepared_imports
    }
    resolved_payloads: dict[int, object] = {}
    completed = 0
    try:
        pending = set(futures)
        while pending:
            throw_if_cancelled(cancel_event)
            done, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
            if not done:
                continue
            for future in done:
                prepared_import = futures[future]
                try:
                    resolved_payloads[prepared_import.prototype_index] = future.result()
                except BrokenProcessPool as exc:
                    raise RuntimeError(
                        "FBX import worker process crashed while importing "
                        f"{prepared_import.resolved_source_name} from {prepared_import.config.fbx_path}."
                    ) from exc
                except Exception as exc:
                    if _should_retry_vertex_color_import(prepared_import, exc):
                        emit_telemetry(
                            telemetry_callback,
                            ConversionPhase.FBX_IMPORT,
                            completed_units=completed,
                            total_units=len(prepared_imports),
                            message=(
                                f"Retrying FBX {prepared_import.resolved_source_name} in a fresh worker "
                                "after Autodesk vertex-color access failure."
                            ),
                            started_at=started_at,
                        )
                        try:
                            resolved_payloads[prepared_import.prototype_index] = _retry_fbx_payload_in_fresh_process(
                                prepared_import,
                                cpu_profile=cpu_profile,
                            )
                            completed += 1
                            emit_telemetry(
                                telemetry_callback,
                                ConversionPhase.FBX_IMPORT,
                                completed_units=completed,
                                total_units=len(prepared_imports),
                                message=f"Imported FBX {prepared_import.resolved_source_name}.",
                                started_at=started_at,
                            )
                            continue
                        except Exception as retry_exc:
                            raise RuntimeError(
                                f"FBX import failed for {prepared_import.resolved_source_name} after vertex-color retry: {retry_exc}"
                            ) from retry_exc
                    raise RuntimeError(
                        f"FBX import failed for {prepared_import.resolved_source_name}: {exc}"
                    ) from exc
                completed += 1
                emit_telemetry(
                    telemetry_callback,
                    ConversionPhase.FBX_IMPORT,
                    completed_units=completed,
                    total_units=len(prepared_imports),
                    message=f"Imported FBX {prepared_import.resolved_source_name}.",
                    started_at=started_at,
                )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return resolved_payloads


def _frozen_runtime_requires_sequential_fbx_import() -> bool:
    return bool(getattr(sys, "frozen", False))


def _load_fbx_payloads_sequential(
    prepared_imports: tuple[_PreparedFbxImport, ...],
    *,
    cpu_profile: CpuProfile,
    telemetry_callback=None,
    cancel_event=None,
    started_at: float | None = None,
):
    emit_telemetry(
        telemetry_callback,
        ConversionPhase.FBX_IMPORT,
        completed_units=0,
        total_units=len(prepared_imports),
        message=f"Importing {len(prepared_imports)} FBX prototype(s) sequentially.",
        started_at=started_at,
    )
    resolved_payloads: dict[int, object] = {}
    for completed, prepared_import in enumerate(prepared_imports, start=1):
        throw_if_cancelled(cancel_event)
        try:
            resolved_payloads[prepared_import.prototype_index] = _load_fbx_payload_worker(
                prepared_import.config.fbx_path or "",
                prepared_import.resolved_identity.prim_name,
                cpu_profile.value,
                prepared_import.config.fbx_material_mode == FbxMaterialMode.VERTEX_COLOR_SPLIT,
            )
        except Exception as exc:
            if _should_retry_vertex_color_import(prepared_import, exc):
                emit_telemetry(
                    telemetry_callback,
                    ConversionPhase.FBX_IMPORT,
                    completed_units=completed - 1,
                    total_units=len(prepared_imports),
                    message=(
                        f"Retrying FBX {prepared_import.resolved_source_name} in a fresh worker "
                        "after Autodesk vertex-color access failure."
                    ),
                    started_at=started_at,
                )
                try:
                    resolved_payloads[prepared_import.prototype_index] = _retry_fbx_payload_in_fresh_process(
                        prepared_import,
                        cpu_profile=cpu_profile,
                    )
                except Exception as retry_exc:
                    raise RuntimeError(
                        f"FBX import failed for {prepared_import.resolved_source_name} after vertex-color retry: {retry_exc}"
                    ) from retry_exc
            else:
                raise RuntimeError(
                    f"FBX import failed for {prepared_import.resolved_source_name}: {exc}"
                ) from exc
        emit_telemetry(
            telemetry_callback,
            ConversionPhase.FBX_IMPORT,
            completed_units=completed,
            total_units=len(prepared_imports),
            message=f"Imported FBX {prepared_import.resolved_source_name}.",
            started_at=started_at,
        )
    return resolved_payloads


def _load_fbx_payload_worker(
    fbx_path: str,
    prototype_name: str,
    cpu_profile_value: str,
    strict_vertex_colors: bool = False,
):
    return load_fbx_geometry(
        fbx_path,
        prototype_name,
        cpu_profile=CpuProfile(cpu_profile_value),
        strict_vertex_colors=strict_vertex_colors,
    )


def _should_retry_vertex_color_import(prepared_import: _PreparedFbxImport, exc: Exception) -> bool:
    if prepared_import.config.fbx_material_mode != FbxMaterialMode.VERTEX_COLOR_SPLIT:
        return False
    return "Autodesk FBX SDK vertex-color access failed" in str(exc)


def _retry_fbx_payload_in_fresh_process(
    prepared_import: _PreparedFbxImport,
    *,
    cpu_profile: CpuProfile,
):
    with ProcessPoolExecutor(
        max_workers=1,
        mp_context=multiprocessing.get_context("spawn"),
    ) as executor:
        future = executor.submit(
            _load_fbx_payload_worker,
            prepared_import.config.fbx_path or "",
            prepared_import.resolved_identity.prim_name,
            cpu_profile.value,
            True,
        )
        try:
            return future.result()
        except BrokenProcessPool as exc:
            raise RuntimeError(
                "Fresh FBX retry worker crashed while importing "
                f"{prepared_import.resolved_source_name} from {prepared_import.config.fbx_path}."
            ) from exc
