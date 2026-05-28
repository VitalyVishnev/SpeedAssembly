"""Prototype Source infrastructure adapters.

Layer: infrastructure with light application-facing helpers.

This module owns Prototype Source config loading and FBX payload loading.
Resolved Prototype matching lives in `prototype_resolution`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .fbx_import_supervisor import FbxImportTask, import_fbx_payloads
from .models import (
    CpuProfile,
    FbxMaterialMode,
    FbxMaterialSlotOverride,
    PrototypeSourceConfig,
    PrototypeSourceMode,
)
from .prototype_resolution import (
    _PreparedFbxImport,
)


@dataclass(frozen=True)
class FbxImportReadOptions:
    read_vertex_colors: bool
    read_material_slots: bool
    strict_vertex_colors: bool


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


def load_fbx_payloads_for_prototype_resolution(
    prepared_imports: tuple[_PreparedFbxImport, ...],
    *,
    cpu_profile: CpuProfile,
    telemetry_callback=None,
    cancel_event=None,
    started_at: float | None = None,
):
    """Infrastructure adapter for Prototype Source FBX payload loading."""
    return _load_fbx_payloads(
        prepared_imports,
        cpu_profile=cpu_profile,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
        started_at=started_at,
    )


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

    tasks: list[FbxImportTask] = []
    for prepared_import in prepared_imports:
        read_options = fbx_import_read_options_for_material_mode(prepared_import.config.fbx_material_mode)
        tasks.append(
            FbxImportTask(
                task_id=prepared_import.prototype_index,
                display_name=prepared_import.resolved_source_name,
                prototype_name=prepared_import.resolved_identity.prim_name,
                fbx_path=prepared_import.config.fbx_path or "",
                cpu_profile=cpu_profile,
                strict_vertex_colors=read_options.strict_vertex_colors,
                read_vertex_colors=read_options.read_vertex_colors,
                read_material_slots=read_options.read_material_slots,
            )
        )
    return import_fbx_payloads(
        tuple(tasks),
        cpu_profile=cpu_profile,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
        started_at=started_at,
    )


def fbx_import_read_options_for_material_mode(mode: FbxMaterialMode) -> FbxImportReadOptions:
    return FbxImportReadOptions(
        read_vertex_colors=mode in {FbxMaterialMode.AUTO, FbxMaterialMode.VERTEX_COLOR_SPLIT},
        read_material_slots=mode == FbxMaterialMode.MATERIAL_SLOTS,
        strict_vertex_colors=mode == FbxMaterialMode.VERTEX_COLOR_SPLIT,
    )
