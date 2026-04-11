"""Typed GUI settings persistence and legacy-settings compatibility parsing.

Layer: application/infrastructure boundary.

The current GUI persists one typed settings snapshot, but this module also
retains compatibility with earlier payload shapes so existing operator settings
continue to load after packaged or launcher upgrades.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .models import CpuProfile, FbxMaterialMode, MaterialPolicy, PrototypeSourceMode


@dataclass(frozen=True)
class BaseMaterialSettingRecord:
    source_id: int
    source_name: str = ""
    ue_asset_path: str = ""


@dataclass(frozen=True)
class FbxMaterialSlotSettingRecord:
    slot_name: str
    ue_asset_path: str = ""


@dataclass(frozen=True)
class PartSourceSettingRecord:
    source_name: str = ""
    source_key: str = ""
    source_mode: PrototypeSourceMode = PrototypeSourceMode.XML_MESH
    unreal_asset_path: str = ""
    fbx_path: str = ""
    fbx_material_mode: FbxMaterialMode = FbxMaterialMode.VERTEX_COLOR_SPLIT
    single_material_path: str = ""
    black_material_path: str = ""
    white_material_path: str = ""
    fbx_material_slot_overrides: tuple[FbxMaterialSlotSettingRecord, ...] = ()


@dataclass(frozen=True)
class WindGroupSettingRecord:
    is_trunk_group: bool = False
    use_dual_influence: bool = True
    influence: float = 1.0
    min_influence: float = 0.0
    max_influence: float = 0.0
    shift_top: float = 0.0


@dataclass(frozen=True)
class GuiSettingsSnapshot:
    last_input_path: str = ""
    last_output_path: str = ""
    cpu_profile: CpuProfile = CpuProfile.BALANCED
    preserve_temp_files: bool = False
    material_policy: MaterialPolicy = MaterialPolicy.SOURCE_MATERIAL_ROLES
    bark_material_path: str = ""
    leaves_material_path: str = ""
    single_material_path: str = ""
    gust_attenuation: float = 0.0
    is_ground_cover: bool = False
    wind_group_settings: dict[str, WindGroupSettingRecord] = field(default_factory=dict)
    wind_group_settings_by_input_path: dict[str, dict[str, WindGroupSettingRecord]] = field(default_factory=dict)
    base_material_settings_by_input_path: dict[str, tuple[BaseMaterialSettingRecord, ...]] = field(default_factory=dict)
    part_mesh_settings_by_input_path: dict[str, tuple[PartSourceSettingRecord, ...]] = field(default_factory=dict)


def resolve_input_settings_key(input_path: str) -> str:
    """Return the normalized per-input key used for persisted GUI state."""
    return str(Path(input_path).expanduser().resolve())


def load_gui_settings(settings_path: str | Path) -> GuiSettingsSnapshot:
    """Load GUI settings, accepting retained legacy payload fields when present."""
    path = Path(settings_path)
    if not path.exists():
        return GuiSettingsSnapshot()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return GuiSettingsSnapshot()
    if not isinstance(payload, dict):
        return GuiSettingsSnapshot()

    return GuiSettingsSnapshot(
        last_input_path=str(payload.get("last_input_path", "")),
        last_output_path=str(payload.get("last_output_path", "")),
        cpu_profile=_parse_cpu_profile(payload.get("cpu_profile")),
        preserve_temp_files=bool(payload.get("preserve_temp_files", False)),
        material_policy=_parse_gui_material_policy(
            payload.get("material_policy", MaterialPolicy.SOURCE_MATERIAL_ROLES.value)
        ),
        bark_material_path=str(payload.get("bark_material_path", "")),
        leaves_material_path=str(payload.get("leaves_material_path", "")),
        single_material_path=str(payload.get("single_material_path", "")),
        gust_attenuation=_coerce_float(payload.get("gust_attenuation", 0.0), 0.0),
        is_ground_cover=bool(payload.get("is_ground_cover", False)),
        wind_group_settings=_parse_wind_group_settings(payload.get("wind_group_settings")),
        wind_group_settings_by_input_path=_parse_wind_group_settings_by_input_path(
            payload.get("wind_group_settings_by_input_path")
        ),
        base_material_settings_by_input_path=_parse_base_material_settings_by_input_path(
            payload.get("base_material_settings_by_input_path")
        ),
        part_mesh_settings_by_input_path=_parse_part_mesh_settings_by_input_path(
            payload.get("part_mesh_settings_by_input_path")
        ),
    )


def save_gui_settings(settings_path: str | Path, snapshot: GuiSettingsSnapshot) -> None:
    """Write the current canonical GUI settings payload."""
    path = Path(settings_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, object] = {
        "last_input_path": snapshot.last_input_path,
        "last_output_path": snapshot.last_output_path,
        "material_policy": snapshot.material_policy.value,
        "bark_material_path": snapshot.bark_material_path,
        "leaves_material_path": snapshot.leaves_material_path,
        "single_material_path": snapshot.single_material_path,
        "gust_attenuation": round(float(snapshot.gust_attenuation), 4),
        "is_ground_cover": bool(snapshot.is_ground_cover),
        "wind_group_settings": _serialize_wind_group_settings(snapshot.wind_group_settings),
    }
    if snapshot.cpu_profile != CpuProfile.BALANCED:
        payload["cpu_profile"] = snapshot.cpu_profile.value
    if snapshot.preserve_temp_files:
        payload["preserve_temp_files"] = True
    if snapshot.part_mesh_settings_by_input_path:
        payload["part_mesh_settings_by_input_path"] = _serialize_part_mesh_settings_by_input_path(
            snapshot.part_mesh_settings_by_input_path
        )
    if snapshot.base_material_settings_by_input_path:
        payload["base_material_settings_by_input_path"] = _serialize_base_material_settings_by_input_path(
            snapshot.base_material_settings_by_input_path
        )
    if snapshot.wind_group_settings_by_input_path:
        payload["wind_group_settings_by_input_path"] = _serialize_wind_group_settings_by_input_path(
            snapshot.wind_group_settings_by_input_path
        )
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _parse_cpu_profile(raw_value) -> CpuProfile:
    try:
        return CpuProfile(str(raw_value))
    except (TypeError, ValueError):
        return CpuProfile.BALANCED


def _parse_gui_material_policy(raw_value) -> MaterialPolicy:
    """Parse persisted GUI material policy values, including retired aliases."""
    normalized = str(raw_value).strip() if raw_value is not None else ""
    if normalized == "legacy_role_ids":
        return MaterialPolicy.SOURCE_MATERIAL_ROLES
    try:
        return MaterialPolicy.parse(normalized or MaterialPolicy.SOURCE_MATERIAL_ROLES.value)
    except ValueError:
        return MaterialPolicy.SOURCE_MATERIAL_ROLES


def _parse_prototype_source_mode(raw_value, *, use_unreal_reference: bool = False) -> PrototypeSourceMode:
    # Retained for older settings payloads that stored Unreal mode as a boolean
    # instead of the newer explicit `source_mode` enum string.
    if use_unreal_reference:
        return PrototypeSourceMode.UNREAL_ASSET
    try:
        return PrototypeSourceMode(str(raw_value))
    except (TypeError, ValueError):
        return PrototypeSourceMode.XML_MESH


def _parse_fbx_material_mode(raw_value) -> FbxMaterialMode:
    try:
        return FbxMaterialMode(str(raw_value))
    except (TypeError, ValueError):
        return FbxMaterialMode.VERTEX_COLOR_SPLIT


def _coerce_float(raw_value, default: float) -> float:
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return default


def _parse_wind_group_settings(raw_value) -> dict[str, WindGroupSettingRecord]:
    if not isinstance(raw_value, dict):
        return {}
    settings: dict[str, WindGroupSettingRecord] = {}
    for key, value in raw_value.items():
        if not isinstance(value, dict):
            continue
        settings[str(key)] = WindGroupSettingRecord(
            is_trunk_group=_coerce_bool(value.get("is_trunk_group"), False),
            use_dual_influence=_coerce_bool(value.get("use_dual_influence"), True),
            influence=_coerce_float(value.get("influence", 1.0), 1.0),
            min_influence=_coerce_float(value.get("min_influence", 0.0), 0.0),
            max_influence=_coerce_float(value.get("max_influence", 0.0), 0.0),
            shift_top=_coerce_float(value.get("shift_top", 0.0), 0.0),
        )
    return settings


def _parse_wind_group_settings_by_input_path(raw_value) -> dict[str, dict[str, WindGroupSettingRecord]]:
    if not isinstance(raw_value, dict):
        return {}
    settings: dict[str, dict[str, WindGroupSettingRecord]] = {}
    for key, value in raw_value.items():
        parsed = _parse_wind_group_settings(value)
        if parsed:
            settings[str(key)] = parsed
    return settings


def _parse_base_material_settings_by_input_path(raw_value) -> dict[str, tuple[BaseMaterialSettingRecord, ...]]:
    if not isinstance(raw_value, dict):
        return {}
    settings: dict[str, tuple[BaseMaterialSettingRecord, ...]] = {}
    for key, value in raw_value.items():
        if not isinstance(value, list):
            continue
        records: list[BaseMaterialSettingRecord] = []
        for record in value:
            if not isinstance(record, dict):
                continue
            source_id = record.get("source_id")
            if not str(source_id).lstrip("-").isdigit():
                continue
            records.append(
                BaseMaterialSettingRecord(
                    source_id=int(source_id),
                    source_name=str(record.get("source_name", "")),
                    ue_asset_path=str(record.get("ue_asset_path", "")),
                )
            )
        settings[str(key)] = tuple(records)
    return settings


def _parse_part_mesh_settings_by_input_path(raw_value) -> dict[str, tuple[PartSourceSettingRecord, ...]]:
    if not isinstance(raw_value, dict):
        return {}
    settings: dict[str, tuple[PartSourceSettingRecord, ...]] = {}
    for key, value in raw_value.items():
        if not isinstance(value, list):
            continue
        records: list[PartSourceSettingRecord] = []
        for record in value:
            if not isinstance(record, dict):
                continue
            records.append(
                PartSourceSettingRecord(
                    source_name=str(record.get("source_name", "")),
                    source_key=str(record.get("source_key", "")),
                    source_mode=_parse_prototype_source_mode(
                        record.get("source_mode"),
                        use_unreal_reference=bool(record.get("use_unreal_reference", False)),
                    ),
                    unreal_asset_path=str(record.get("unreal_asset_path", "")),
                    fbx_path=str(record.get("fbx_path", "")),
                    fbx_material_mode=_parse_fbx_material_mode(record.get("fbx_material_mode")),
                    single_material_path=str(record.get("single_material_path", "")),
                    black_material_path=str(record.get("black_material_path", "")),
                    white_material_path=str(record.get("white_material_path", "")),
                    fbx_material_slot_overrides=_parse_fbx_material_slot_overrides(
                        record.get("fbx_material_slot_overrides")
                    ),
                )
            )
        settings[str(key)] = tuple(records)
    return settings


def _parse_fbx_material_slot_overrides(raw_value) -> tuple[FbxMaterialSlotSettingRecord, ...]:
    if not isinstance(raw_value, list):
        return ()
    records: list[FbxMaterialSlotSettingRecord] = []
    for record in raw_value:
        if not isinstance(record, dict):
            continue
        slot_name = str(record.get("slot_name", "")).strip()
        if not slot_name:
            continue
        records.append(
            FbxMaterialSlotSettingRecord(
                slot_name=slot_name,
                ue_asset_path=str(record.get("ue_asset_path", "")),
            )
        )
    return tuple(records)


def _serialize_base_material_settings_by_input_path(
    settings: dict[str, tuple[BaseMaterialSettingRecord, ...]]
) -> dict[str, list[dict[str, object]]]:
    return {
        str(key): [
            {
                "source_id": record.source_id,
                "source_name": record.source_name,
                "ue_asset_path": record.ue_asset_path,
            }
            for record in records
        ]
        for key, records in settings.items()
    }


def _serialize_part_mesh_settings_by_input_path(
    settings: dict[str, tuple[PartSourceSettingRecord, ...]]
) -> dict[str, list[dict[str, object]]]:
    serialized: dict[str, list[dict[str, object]]] = {}
    for key, records in settings.items():
        rows: list[dict[str, object]] = []
        for record in records:
            payload: dict[str, object] = {
                "source_name": record.source_name,
                "source_key": record.source_key,
            }
            if record.source_mode == PrototypeSourceMode.UNREAL_ASSET:
                payload["use_unreal_reference"] = True
                payload["unreal_asset_path"] = record.unreal_asset_path
            elif record.source_mode == PrototypeSourceMode.FBX_FILE:
                payload["source_mode"] = PrototypeSourceMode.FBX_FILE.value
                payload["fbx_path"] = record.fbx_path
                payload["fbx_material_mode"] = record.fbx_material_mode.value
            else:
                payload["source_mode"] = PrototypeSourceMode.XML_MESH.value
                payload["fbx_material_mode"] = record.fbx_material_mode.value
            if record.single_material_path:
                payload["single_material_path"] = record.single_material_path
            if record.black_material_path:
                payload["black_material_path"] = record.black_material_path
            if record.white_material_path:
                payload["white_material_path"] = record.white_material_path
            if record.fbx_material_slot_overrides:
                payload["fbx_material_slot_overrides"] = [
                    {
                        "slot_name": override.slot_name,
                        "ue_asset_path": override.ue_asset_path,
                    }
                    for override in record.fbx_material_slot_overrides
                ]
            rows.append(payload)
        serialized[str(key)] = rows
    return serialized


def _serialize_wind_group_settings(
    settings: dict[str, WindGroupSettingRecord]
) -> dict[str, dict[str, object]]:
    return {
        str(key): {
            "is_trunk_group": bool(record.is_trunk_group),
            "use_dual_influence": record.use_dual_influence,
            "influence": round(float(record.influence), 4),
            "min_influence": round(float(record.min_influence), 4),
            "max_influence": round(float(record.max_influence), 4),
            "shift_top": round(float(record.shift_top), 4),
        }
        for key, record in settings.items()
    }


def _serialize_wind_group_settings_by_input_path(
    settings: dict[str, dict[str, WindGroupSettingRecord]]
) -> dict[str, dict[str, dict[str, object]]]:
    return {
        str(key): _serialize_wind_group_settings(group_settings)
        for key, group_settings in settings.items()
    }


def _coerce_bool(raw_value, default: bool) -> bool:
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    if raw_value is None:
        return default
    return bool(raw_value)
