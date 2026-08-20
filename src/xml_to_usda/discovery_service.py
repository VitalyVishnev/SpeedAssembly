"""Application-facing discovery services for XML and FBX-backed UI rows.

Layer: application.

These helpers expose typed discovery/view-model specs to the UI layer without
letting widget code depend directly on XML streaming details or raw FBX slot
inspection internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .models import CpuProfile, FbxMaterialMode, PrototypeSourceMode, UdimMode
from .settings_service import (
    BaseMaterialSettingRecord,
    FbxMaterialSlotSettingRecord,
    PartSourceSettingRecord,
)
from .source_analysis import (
    discover_missing_bone_generator_groups,
    discover_part_prototypes,
    discover_source_materials,
)
from .canonical_loader import load_source_tree_model
from .scattered_parts import ScatteredPartsAnalysis, analyze_scattered_parts
from .skeleton_processing import strictly_vertical_joint_names


@dataclass(frozen=True)
class BaseMaterialRowSpec:
    source_id: int
    source_name: str
    ue_asset_path: str = ""
    udim_mode: UdimMode = UdimMode.OFF
    udim_id: int = 1001


@dataclass(frozen=True)
class BaseMaterialDiscovery:
    summary: str
    rows: tuple[BaseMaterialRowSpec, ...]


@dataclass(frozen=True)
class PrototypeMaterialSlotRowSpec:
    slot_name: str
    face_count: int
    ue_asset_path: str = ""
    udim_mode: UdimMode = UdimMode.OFF
    udim_id: int = 1001


@dataclass(frozen=True)
class PrototypeRowSpec:
    source_key: str
    source_name: str
    source_mesh_id: int | None
    instance_count: int
    source_mode: PrototypeSourceMode = PrototypeSourceMode.XML_MESH
    unreal_asset_path: str = ""
    fbx_path: str = ""
    fbx_material_mode: FbxMaterialMode = FbxMaterialMode.VERTEX_COLOR_SPLIT
    single_material_path: str = ""
    single_material_udim_mode: UdimMode = UdimMode.OFF
    single_material_udim_id: int = 1001
    black_material_path: str = ""
    black_material_udim_mode: UdimMode = UdimMode.OFF
    black_material_udim_id: int = 1001
    white_material_path: str = ""
    white_material_udim_mode: UdimMode = UdimMode.OFF
    white_material_udim_id: int = 1001
    fbx_material_slot_overrides: tuple[FbxMaterialSlotSettingRecord, ...] = ()
    simplification_percent: int = 100


@dataclass(frozen=True)
class PrototypeDiscovery:
    summary: str
    rows: tuple[PrototypeRowSpec, ...]


@dataclass(frozen=True)
class SourceDiscoveryRequest:
    input_path: str
    base_persisted_records: tuple[BaseMaterialSettingRecord, ...] = ()
    part_persisted_records: tuple[PartSourceSettingRecord, ...] = ()


@dataclass(frozen=True)
class SourceDiscoveryResult:
    input_path: str
    base: BaseMaterialDiscovery
    prototypes: PrototypeDiscovery
    missing_bone_generator_groups: tuple[str, ...] = ()
    scattered_parts: ScatteredPartsAnalysis = ScatteredPartsAnalysis(False, False, 0)
    strictly_vertical_joints: tuple[str, ...] = ()
    skeleton_joint_count: int = 0


def discover_source_rows(request: SourceDiscoveryRequest) -> SourceDiscoveryResult:
    _report, source_model, _diagnostics = load_source_tree_model(request.input_path)
    return SourceDiscoveryResult(
        input_path=request.input_path,
        base=discover_base_material_rows(
            request.input_path,
            persisted_records=request.base_persisted_records,
        ),
        prototypes=discover_part_prototype_rows(
            request.input_path,
            persisted_records=request.part_persisted_records,
        ),
        missing_bone_generator_groups=discover_missing_bone_generator_groups(request.input_path),
        scattered_parts=analyze_scattered_parts(source_model),
        strictly_vertical_joints=strictly_vertical_joint_names(source_model.skeleton),
        skeleton_joint_count=len(source_model.skeleton),
    )


def discover_scattered_parts(input_path: str) -> ScatteredPartsAnalysis:
    _report, source_model, _diagnostics = load_source_tree_model(input_path)
    return analyze_scattered_parts(source_model)


def discover_strictly_vertical_joints(input_path: str) -> tuple[str, ...]:
    _report, source_model, _diagnostics = load_source_tree_model(input_path)
    return strictly_vertical_joint_names(source_model.skeleton)


def discover_base_material_rows(
    input_path: str,
    persisted_records: tuple[BaseMaterialSettingRecord, ...] = (),
) -> BaseMaterialDiscovery:
    """Discover base XML material rows and merge persisted UI assignments."""
    materials = discover_source_materials(input_path)
    if not materials:
        return BaseMaterialDiscovery(
            summary="No XML material slots were found in this file.",
            rows=(),
        )
    persisted_by_id = {record.source_id: record for record in persisted_records}
    rows = tuple(
        _base_material_row_spec(material, persisted_by_id.get(material.source_id))
        for material in materials
    )
    return BaseMaterialDiscovery(
        summary=f"Found {len(rows)} base XML material slot(s).",
        rows=rows,
    )


def _base_material_row_spec(material, persisted: BaseMaterialSettingRecord | None) -> BaseMaterialRowSpec:
    return BaseMaterialRowSpec(
        source_id=material.source_id,
        source_name=material.source_name,
        ue_asset_path=persisted.ue_asset_path if persisted is not None else "",
        udim_mode=persisted.udim_mode if persisted is not None else UdimMode.OFF,
        udim_id=persisted.udim_id if persisted is not None else 1001,
    )


def discover_part_prototype_rows(
    input_path: str,
    persisted_records: tuple[PartSourceSettingRecord, ...] = (),
) -> PrototypeDiscovery:
    """Discover repeated-part prototype rows and merge persisted source settings."""
    prototypes = discover_part_prototypes(input_path)
    if not prototypes:
        return PrototypeDiscovery(
            summary="No repeated branch instances were found in this XML.",
            rows=(),
        )

    total_instances = sum(prototype.instance_count for prototype in prototypes)
    persisted_by_name = {
        record.source_name: record
        for record in persisted_records
        if record.source_name
    }
    persisted_by_key = {
        record.source_key: record
        for record in persisted_records
        if record.source_key
    }
    rows: list[PrototypeRowSpec] = []
    for prototype in prototypes:
        display_name = prototype.source_name or prototype.source_key
        persisted = persisted_by_name.get(display_name) or persisted_by_key.get(str(prototype.source_key))
        source_mode = PrototypeSourceMode.XML_MESH
        fbx_material_mode = FbxMaterialMode.VERTEX_COLOR_SPLIT
        unreal_asset_path = ""
        fbx_path = ""
        single_material_path = ""
        single_material_udim_mode = UdimMode.OFF
        single_material_udim_id = 1001
        black_material_path = ""
        black_material_udim_mode = UdimMode.OFF
        black_material_udim_id = 1001
        white_material_path = ""
        white_material_udim_mode = UdimMode.OFF
        white_material_udim_id = 1001
        slot_overrides: tuple[FbxMaterialSlotSettingRecord, ...] = ()
        simplification_percent = 100
        if persisted is not None:
            source_mode = _normalize_source_mode(persisted.source_mode)
            fbx_material_mode = _normalize_row_fbx_material_mode(persisted.fbx_material_mode)
            unreal_asset_path = persisted.unreal_asset_path
            fbx_path = persisted.fbx_path
            single_material_path = persisted.single_material_path
            single_material_udim_mode = persisted.single_material_udim_mode
            single_material_udim_id = persisted.single_material_udim_id
            black_material_path = persisted.black_material_path
            black_material_udim_mode = persisted.black_material_udim_mode
            black_material_udim_id = persisted.black_material_udim_id
            white_material_path = persisted.white_material_path
            white_material_udim_mode = persisted.white_material_udim_mode
            white_material_udim_id = persisted.white_material_udim_id
            slot_overrides = persisted.fbx_material_slot_overrides
            simplification_percent = persisted.simplification_percent
        rows.append(
            PrototypeRowSpec(
                source_key=prototype.source_key,
                source_name=display_name,
                source_mesh_id=prototype.source_mesh_id,
                instance_count=prototype.instance_count,
                source_mode=source_mode,
                unreal_asset_path=unreal_asset_path,
                fbx_path=fbx_path,
                fbx_material_mode=fbx_material_mode,
                single_material_path=single_material_path,
                single_material_udim_mode=single_material_udim_mode,
                single_material_udim_id=single_material_udim_id,
                black_material_path=black_material_path,
                black_material_udim_mode=black_material_udim_mode,
                black_material_udim_id=black_material_udim_id,
                white_material_path=white_material_path,
                white_material_udim_mode=white_material_udim_mode,
                white_material_udim_id=white_material_udim_id,
                fbx_material_slot_overrides=slot_overrides,
                simplification_percent=simplification_percent,
            )
        )
    return PrototypeDiscovery(
        summary=f"Found {total_instances} repeated branch instances across {len(rows)} prototype(s).",
        rows=tuple(rows),
    )


def inspect_fbx_material_slot_rows(
    fbx_path: str,
    cpu_profile: CpuProfile,
    persisted_records: tuple[FbxMaterialSlotSettingRecord, ...] = (),
) -> tuple[PrototypeMaterialSlotRowSpec, ...]:
    """Inspect face-used FBX slots and apply any persisted Unreal material paths."""
    resolved_path = str(Path(fbx_path).expanduser().resolve())
    slots = _inspect_fbx_material_slots_cached(resolved_path, cpu_profile.value)
    persisted_by_name = {record.slot_name: record for record in persisted_records if record.slot_name}
    default_persisted = FbxMaterialSlotSettingRecord("", "", UdimMode.OFF, 1001)
    rows: list[PrototypeMaterialSlotRowSpec] = []
    for slot in slots:
        persisted = persisted_by_name.get(slot.name, default_persisted)
        rows.append(
            PrototypeMaterialSlotRowSpec(
                slot_name=slot.name,
                face_count=slot.face_count,
                ue_asset_path=persisted.ue_asset_path,
                udim_mode=persisted.udim_mode,
                udim_id=persisted.udim_id,
            )
        )
    return tuple(rows)


@lru_cache(maxsize=64)
def _inspect_fbx_material_slots_cached(
    resolved_fbx_path: str,
    cpu_profile_value: str,
):
    # FBX is native and expensive to import. Keep it out of normal GUI startup;
    # only Material Slots inspection needs this backend.
    from .fbx_adapter import inspect_fbx_material_slots

    return inspect_fbx_material_slots(
        resolved_fbx_path,
        cpu_profile=CpuProfile(cpu_profile_value),
    )


def _normalize_source_mode(mode: PrototypeSourceMode) -> PrototypeSourceMode:
    if mode not in set(PrototypeSourceMode):
        return PrototypeSourceMode.XML_MESH
    return mode


def _normalize_row_fbx_material_mode(mode: FbxMaterialMode) -> FbxMaterialMode:
    if mode == FbxMaterialMode.AUTO:
        return FbxMaterialMode.VERTEX_COLOR_SPLIT
    if mode not in {
        FbxMaterialMode.VERTEX_COLOR_SPLIT,
        FbxMaterialMode.SINGLE_MATERIAL,
        FbxMaterialMode.MATERIAL_SLOTS,
    }:
        return FbxMaterialMode.VERTEX_COLOR_SPLIT
    return mode
