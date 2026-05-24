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

from .models import ConversionMode, CpuProfile, FbxMaterialMode, MaterialPolicy, PrototypeSourceMode, UdimMode


FACTORY_DEFAULT_PRESET_NAME = "Factory Defaults"


@dataclass(frozen=True)
class BaseMaterialSettingRecord:
    source_id: int
    source_name: str = ""
    ue_asset_path: str = ""
    udim_mode: UdimMode = UdimMode.OFF
    udim_id: int = 1001


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
    min_influence: float = 0.5
    max_influence: float = 1.0
    shift_top: float = 0.5


@dataclass(frozen=True)
class GuiPresetRecord:
    name: str
    cpu_profile: CpuProfile = CpuProfile.BALANCED
    preserve_temp_files: bool = False
    conversion_mode: ConversionMode = ConversionMode.SKELETAL_ASSEMBLY
    material_policy: MaterialPolicy = MaterialPolicy.SOURCE_MATERIAL_ROLES
    bark_material_path: str = ""
    leaves_material_path: str = ""
    single_material_path: str = ""
    gust_attenuation: float = 0.0
    is_ground_cover: bool = False
    wind_group_settings: dict[str, WindGroupSettingRecord] = field(default_factory=dict)
    base_material_settings: tuple[BaseMaterialSettingRecord, ...] = ()
    part_mesh_settings: tuple[PartSourceSettingRecord, ...] = ()


@dataclass(frozen=True)
class GuiSettingsSnapshot:
    last_input_path: str = ""
    last_output_path: str = ""
    cpu_profile: CpuProfile = CpuProfile.BALANCED
    preserve_temp_files: bool = False
    conversion_mode: ConversionMode = ConversionMode.SKELETAL_ASSEMBLY
    material_policy: MaterialPolicy = MaterialPolicy.SOURCE_MATERIAL_ROLES
    bark_material_path: str = ""
    leaves_material_path: str = ""
    single_material_path: str = ""
    gust_attenuation: float = 0.0
    is_ground_cover: bool = False
    wind_group_settings: dict[str, WindGroupSettingRecord] = field(default_factory=dict)
    base_material_settings: tuple[BaseMaterialSettingRecord, ...] = ()
    part_mesh_settings: tuple[PartSourceSettingRecord, ...] = ()
    active_preset_name: str = FACTORY_DEFAULT_PRESET_NAME
    presets: dict[str, GuiPresetRecord] = field(default_factory=dict)


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

    presets = _parse_presets(payload.get("presets"))
    active_preset_name = _coerce_preset_name(payload.get("active_preset_name"), FACTORY_DEFAULT_PRESET_NAME)
    if active_preset_name != FACTORY_DEFAULT_PRESET_NAME and active_preset_name not in presets:
        active_preset_name = FACTORY_DEFAULT_PRESET_NAME

    last_input_path = str(payload.get("last_input_path", ""))
    legacy_wind_by_input = _parse_wind_group_settings_by_input_path(payload.get("wind_group_settings_by_input_path"))
    legacy_base_by_input = _parse_base_material_settings_by_input_path(payload.get("base_material_settings_by_input_path"))
    legacy_part_by_input = _parse_part_mesh_settings_by_input_path(payload.get("part_mesh_settings_by_input_path"))

    wind_group_settings = _parse_wind_group_settings(payload.get("wind_group_settings"))
    if not wind_group_settings:
        wind_group_settings = _select_legacy_input_settings(legacy_wind_by_input, last_input_path, default={})
    base_material_settings = _parse_base_material_settings(payload.get("base_material_settings"))
    if not base_material_settings:
        base_material_settings = _select_legacy_input_settings(legacy_base_by_input, last_input_path, default=())
    part_mesh_settings = _parse_part_mesh_settings(payload.get("part_mesh_settings"))
    if not part_mesh_settings:
        part_mesh_settings = _select_legacy_input_settings(legacy_part_by_input, last_input_path, default=())

    return GuiSettingsSnapshot(
        last_input_path=last_input_path,
        last_output_path=str(payload.get("last_output_path", "")),
        cpu_profile=_parse_cpu_profile(payload.get("cpu_profile")),
        preserve_temp_files=bool(payload.get("preserve_temp_files", False)),
        conversion_mode=_parse_conversion_mode(payload.get("conversion_mode")),
        material_policy=_parse_gui_material_policy(
            payload.get("material_policy", MaterialPolicy.SOURCE_MATERIAL_ROLES.value)
        ),
        bark_material_path=str(payload.get("bark_material_path", "")),
        leaves_material_path=str(payload.get("leaves_material_path", "")),
        single_material_path=str(payload.get("single_material_path", "")),
        gust_attenuation=_coerce_float(payload.get("gust_attenuation", 0.0), 0.0),
        is_ground_cover=bool(payload.get("is_ground_cover", False)),
        wind_group_settings=wind_group_settings,
        base_material_settings=base_material_settings,
        part_mesh_settings=part_mesh_settings,
        active_preset_name=active_preset_name,
        presets=presets,
    )


def save_gui_settings(settings_path: str | Path, snapshot: GuiSettingsSnapshot) -> None:
    """Write the current canonical GUI settings payload."""
    path = Path(settings_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, object] = {
        "last_input_path": snapshot.last_input_path,
        "last_output_path": snapshot.last_output_path,
        "conversion_mode": ConversionMode.parse(snapshot.conversion_mode).value,
        "material_policy": snapshot.material_policy.value,
        "bark_material_path": snapshot.bark_material_path,
        "leaves_material_path": snapshot.leaves_material_path,
        "single_material_path": snapshot.single_material_path,
        "gust_attenuation": round(float(snapshot.gust_attenuation), 4),
        "is_ground_cover": bool(snapshot.is_ground_cover),
        "wind_group_settings": _serialize_wind_group_settings(snapshot.wind_group_settings),
        "base_material_settings": _serialize_base_material_settings(snapshot.base_material_settings),
        "part_mesh_settings": _serialize_part_mesh_settings(snapshot.part_mesh_settings),
    }
    if snapshot.cpu_profile != CpuProfile.BALANCED:
        payload["cpu_profile"] = snapshot.cpu_profile.value
    if snapshot.preserve_temp_files:
        payload["preserve_temp_files"] = True
    payload["active_preset_name"] = _coerce_preset_name(snapshot.active_preset_name, FACTORY_DEFAULT_PRESET_NAME)
    if snapshot.presets:
        payload["presets"] = _serialize_presets(snapshot.presets)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def factory_default_preset() -> GuiPresetRecord:
    """Return the built-in preset that is always available in the selector."""
    return GuiPresetRecord(name=FACTORY_DEFAULT_PRESET_NAME)


def sorted_gui_presets(snapshot: GuiSettingsSnapshot) -> tuple[GuiPresetRecord, ...]:
    """Return factory defaults followed by user presets in deterministic order."""
    user_presets = sorted(snapshot.presets.values(), key=lambda preset: preset.name.casefold())
    return (factory_default_preset(), *user_presets)


def save_gui_preset(preset_path: str | Path, preset: GuiPresetRecord) -> None:
    """Write one preset to a portable JSON file."""
    path = Path(preset_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _serialize_preset(preset)
    payload["name"] = preset.name
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_gui_preset(preset_path: str | Path) -> GuiPresetRecord:
    """Load one preset from a portable JSON file."""
    path = Path(preset_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Preset file is not readable JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Preset file must contain one JSON object.")
    name = _coerce_preset_name(payload.get("name"), path.stem)
    if name == FACTORY_DEFAULT_PRESET_NAME:
        raise ValueError("Imported preset must use a user preset name.")
    return _parse_preset(name, payload)


def _parse_cpu_profile(raw_value) -> CpuProfile:
    try:
        return CpuProfile(str(raw_value))
    except (TypeError, ValueError):
        return CpuProfile.BALANCED


def _parse_conversion_mode(raw_value) -> ConversionMode:
    try:
        return ConversionMode.parse(raw_value)
    except ValueError:
        return ConversionMode.SKELETAL_ASSEMBLY


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


def _parse_udim_mode(raw_value) -> UdimMode:
    try:
        return UdimMode.parse(raw_value)
    except (TypeError, ValueError):
        return UdimMode.OFF


def _parse_udim_id(raw_value) -> int:
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return 1001
    return value if value >= 1001 else 1001


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
            min_influence=_coerce_float(value.get("min_influence", 0.5), 0.5),
            max_influence=_coerce_float(value.get("max_influence", 1.0), 1.0),
            shift_top=_coerce_float(value.get("shift_top", 0.5), 0.5),
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
                    udim_mode=_parse_udim_mode(record.get("udim_mode")),
                    udim_id=_parse_udim_id(record.get("udim_id")),
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


def _parse_presets(raw_value) -> dict[str, GuiPresetRecord]:
    if not isinstance(raw_value, dict):
        return {}
    presets: dict[str, GuiPresetRecord] = {}
    for raw_name, raw_preset in raw_value.items():
        name = _coerce_preset_name(raw_name, "")
        if not name or name == FACTORY_DEFAULT_PRESET_NAME or not isinstance(raw_preset, dict):
            continue
        presets[name] = _parse_preset(name, raw_preset)
    return presets


def _parse_preset(name: str, payload: dict) -> GuiPresetRecord:
    return GuiPresetRecord(
        name=name,
        cpu_profile=_parse_cpu_profile(payload.get("cpu_profile")),
        preserve_temp_files=bool(payload.get("preserve_temp_files", False)),
        conversion_mode=_parse_conversion_mode(payload.get("conversion_mode")),
        material_policy=_parse_gui_material_policy(
            payload.get("material_policy", MaterialPolicy.SOURCE_MATERIAL_ROLES.value)
        ),
        bark_material_path=str(payload.get("bark_material_path", "")),
        leaves_material_path=str(payload.get("leaves_material_path", "")),
        single_material_path=str(payload.get("single_material_path", "")),
        gust_attenuation=_coerce_float(payload.get("gust_attenuation", 0.0), 0.0),
        is_ground_cover=bool(payload.get("is_ground_cover", False)),
        wind_group_settings=_parse_wind_group_settings(payload.get("wind_group_settings")),
        base_material_settings=_parse_base_material_settings(payload.get("base_material_settings")),
        part_mesh_settings=_parse_part_mesh_settings(payload.get("part_mesh_settings")),
    )


def _parse_base_material_settings(raw_value) -> tuple[BaseMaterialSettingRecord, ...]:
    return _parse_base_material_settings_by_input_path({"preset": raw_value}).get("preset", ())


def _parse_part_mesh_settings(raw_value) -> tuple[PartSourceSettingRecord, ...]:
    return _parse_part_mesh_settings_by_input_path({"preset": raw_value}).get("preset", ())


def _select_legacy_input_settings(settings: dict, last_input_path: str, *, default):
    if not settings:
        return default
    if last_input_path:
        try:
            last_key = resolve_input_settings_key(last_input_path)
        except (OSError, RuntimeError, ValueError):
            last_key = str(Path(last_input_path).expanduser())
        if last_key in settings:
            return settings[last_key]
    first_key = sorted(settings)[0]
    return settings[first_key]


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
                "udim_mode": record.udim_mode.value,
                "udim_id": record.udim_id,
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


def _serialize_base_material_settings(records: tuple[BaseMaterialSettingRecord, ...]) -> list[dict[str, object]]:
    return _serialize_base_material_settings_by_input_path({"global": records})["global"]


def _serialize_part_mesh_settings(records: tuple[PartSourceSettingRecord, ...]) -> list[dict[str, object]]:
    return _serialize_part_mesh_settings_by_input_path({"global": records}).get("global", [])


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


def _serialize_presets(presets: dict[str, GuiPresetRecord]) -> dict[str, dict[str, object]]:
    return {
        preset.name: _serialize_preset(preset)
        for preset in sorted(presets.values(), key=lambda value: value.name.casefold())
        if preset.name != FACTORY_DEFAULT_PRESET_NAME
    }


def _serialize_preset(preset: GuiPresetRecord) -> dict[str, object]:
    payload: dict[str, object] = {
        "cpu_profile": preset.cpu_profile.value,
        "preserve_temp_files": bool(preset.preserve_temp_files),
        "conversion_mode": ConversionMode.parse(preset.conversion_mode).value,
        "material_policy": preset.material_policy.value,
        "bark_material_path": preset.bark_material_path,
        "leaves_material_path": preset.leaves_material_path,
        "single_material_path": preset.single_material_path,
        "gust_attenuation": round(float(preset.gust_attenuation), 4),
        "is_ground_cover": bool(preset.is_ground_cover),
        "wind_group_settings": _serialize_wind_group_settings(preset.wind_group_settings),
        "base_material_settings": _serialize_base_material_settings_by_input_path(
            {"preset": preset.base_material_settings}
        )["preset"],
        "part_mesh_settings": _serialize_part_mesh_settings_by_input_path({"preset": preset.part_mesh_settings}).get(
            "preset", []
        ),
    }
    return payload


def _coerce_preset_name(raw_value, default: str) -> str:
    name = str(raw_value).strip() if raw_value is not None else ""
    return name or default


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
