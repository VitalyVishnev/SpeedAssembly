from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .fbx_adapter import inspect_fbx_material_slots
from .models import CpuProfile, FbxMaterialMode, PrototypeSourceMode
from .settings_service import (
    BaseMaterialSettingRecord,
    FbxMaterialSlotSettingRecord,
    PartSourceSettingRecord,
)
from .source_analysis import discover_part_prototypes, discover_source_materials


@dataclass(frozen=True)
class BaseMaterialRowSpec:
    source_id: int
    source_name: str
    ue_asset_path: str = ""


@dataclass(frozen=True)
class BaseMaterialDiscovery:
    summary: str
    rows: tuple[BaseMaterialRowSpec, ...]


@dataclass(frozen=True)
class PrototypeMaterialSlotRowSpec:
    slot_name: str
    face_count: int
    ue_asset_path: str = ""


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
    black_material_path: str = ""
    white_material_path: str = ""
    fbx_material_slot_overrides: tuple[FbxMaterialSlotSettingRecord, ...] = ()


@dataclass(frozen=True)
class PrototypeDiscovery:
    summary: str
    rows: tuple[PrototypeRowSpec, ...]


def discover_base_material_rows(
    input_path: str,
    persisted_records: tuple[BaseMaterialSettingRecord, ...] = (),
) -> BaseMaterialDiscovery:
    materials = discover_source_materials(input_path)
    if not materials:
        return BaseMaterialDiscovery(
            summary="No XML material slots were found in this file.",
            rows=(),
        )
    persisted_by_id = {record.source_id: record for record in persisted_records}
    rows = tuple(
        BaseMaterialRowSpec(
            source_id=material.source_id,
            source_name=material.source_name,
            ue_asset_path=persisted_by_id.get(material.source_id, BaseMaterialSettingRecord(material.source_id)).ue_asset_path,
        )
        for material in materials
    )
    return BaseMaterialDiscovery(
        summary=f"Found {len(rows)} base XML material slot(s).",
        rows=rows,
    )


def discover_part_prototype_rows(
    input_path: str,
    persisted_records: tuple[PartSourceSettingRecord, ...] = (),
) -> PrototypeDiscovery:
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
        black_material_path = ""
        white_material_path = ""
        slot_overrides: tuple[FbxMaterialSlotSettingRecord, ...] = ()
        if persisted is not None:
            source_mode = _normalize_source_mode(persisted.source_mode)
            fbx_material_mode = _normalize_row_fbx_material_mode(persisted.fbx_material_mode)
            unreal_asset_path = persisted.unreal_asset_path
            fbx_path = persisted.fbx_path
            single_material_path = persisted.single_material_path
            black_material_path = persisted.black_material_path
            white_material_path = persisted.white_material_path
            slot_overrides = persisted.fbx_material_slot_overrides
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
                black_material_path=black_material_path,
                white_material_path=white_material_path,
                fbx_material_slot_overrides=slot_overrides,
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
    resolved_path = str(Path(fbx_path).expanduser().resolve())
    slots = _inspect_fbx_material_slots_cached(resolved_path, cpu_profile.value)
    persisted_by_name = {record.slot_name: record.ue_asset_path for record in persisted_records if record.slot_name}
    return tuple(
        PrototypeMaterialSlotRowSpec(
            slot_name=slot.name,
            face_count=slot.face_count,
            ue_asset_path=persisted_by_name.get(slot.name, ""),
        )
        for slot in slots
    )


@lru_cache(maxsize=64)
def _inspect_fbx_material_slots_cached(
    resolved_fbx_path: str,
    cpu_profile_value: str,
):
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
