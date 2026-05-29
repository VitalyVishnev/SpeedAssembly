"""Operator-facing settings bridge for the PySide6 shell.

Layer: UI/application boundary.

The PySide6 shell reuses the existing GUI settings payload so operator defaults,
material policy, and wind settings survive across sessions.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from ..models import ConversionMode, CpuProfile, MaterialPolicy
from ..settings_service import (
    BaseMaterialSettingRecord,
    GuiPresetRecord,
    GuiSettingsSnapshot,
    PartSourceSettingRecord,
    WindGroupSettingRecord,
)
from .dependencies import QtUiDependencies


SETTINGS_DIR = Path.home() / ".xml_to_usda"
SETTINGS_PATH = SETTINGS_DIR / "gui_settings.json"


@dataclass(frozen=True)
class OperatorState:
    input_path: str = ""
    output_path: str = ""
    cpu_profile: CpuProfile = CpuProfile.BALANCED
    preserve_temp_files: bool = False
    conversion_mode: ConversionMode = ConversionMode.SKELETAL_ASSEMBLY
    material_policy: MaterialPolicy = MaterialPolicy.SOURCE_MATERIAL_ROLES
    bark_material_path: str = ""
    leaves_material_path: str = ""
    single_material_path: str = ""
    gust_attenuation: float = 0.0
    is_ground_cover: bool = False


def load_operator_state(
    deps: QtUiDependencies,
    *,
    settings_path: str | Path | None = None,
) -> tuple[OperatorState, GuiSettingsSnapshot]:
    """Load shared operator defaults for the Qt shell."""
    resolved_settings_path = Path(settings_path) if settings_path is not None else SETTINGS_PATH
    try:
        snapshot = deps.load_gui_settings(resolved_settings_path)
    except ValueError:
        snapshot = GuiSettingsSnapshot()
    return (
        OperatorState(
            input_path=snapshot.last_input_path,
            output_path=snapshot.last_output_path,
            cpu_profile=CpuProfile.BALANCED,
            preserve_temp_files=snapshot.preserve_temp_files,
            conversion_mode=snapshot.conversion_mode,
            material_policy=snapshot.material_policy,
            bark_material_path=snapshot.bark_material_path,
            leaves_material_path=snapshot.leaves_material_path,
            single_material_path=snapshot.single_material_path,
            gust_attenuation=snapshot.gust_attenuation,
            is_ground_cover=snapshot.is_ground_cover,
        ),
        snapshot,
    )


def save_operator_state(
    deps: QtUiDependencies,
    state: OperatorState,
    *,
    previous_snapshot: GuiSettingsSnapshot,
    settings_path: str | Path | None = None,
) -> GuiSettingsSnapshot:
    """Persist shared operator defaults without overwriting GUI file-path history."""
    resolved_settings_path = Path(settings_path) if settings_path is not None else SETTINGS_PATH
    snapshot = GuiSettingsSnapshot(
        **_operator_snapshot_fields(state, previous_snapshot),
        wind_group_settings=previous_snapshot.wind_group_settings,
        base_material_settings=previous_snapshot.base_material_settings,
        part_mesh_settings=previous_snapshot.part_mesh_settings,
        active_preset_name=previous_snapshot.active_preset_name,
        presets=previous_snapshot.presets,
    )
    deps.save_gui_settings(resolved_settings_path, snapshot)
    return snapshot


def load_base_material_records(
    snapshot: GuiSettingsSnapshot,
) -> tuple[BaseMaterialSettingRecord, ...]:
    return snapshot.base_material_settings


def load_part_source_records(
    snapshot: GuiSettingsSnapshot,
) -> tuple[PartSourceSettingRecord, ...]:
    return snapshot.part_mesh_settings


def load_wind_group_records(
    snapshot: GuiSettingsSnapshot,
) -> dict[str, WindGroupSettingRecord]:
    return dict(snapshot.wind_group_settings)


def save_nested_input_settings(
    deps: QtUiDependencies,
    state: OperatorState,
    *,
    previous_snapshot: GuiSettingsSnapshot,
    base_material_records: tuple[BaseMaterialSettingRecord, ...],
    part_source_records: tuple[PartSourceSettingRecord, ...],
    wind_group_records: dict[str, WindGroupSettingRecord],
    settings_path: str | Path | None = None,
) -> GuiSettingsSnapshot:
    """Persist current operator defaults plus global tab settings without replacing shared file-path history."""
    resolved_settings_path = Path(settings_path) if settings_path is not None else SETTINGS_PATH

    snapshot = GuiSettingsSnapshot(
        **_operator_snapshot_fields(state, previous_snapshot),
        wind_group_settings=dict(wind_group_records),
        base_material_settings=base_material_records,
        part_mesh_settings=part_source_records,
        fbx_cache_max_size_gb=previous_snapshot.fbx_cache_max_size_gb,
        fbx_cache_max_age_days=previous_snapshot.fbx_cache_max_age_days,
        active_preset_name=previous_snapshot.active_preset_name,
        presets=previous_snapshot.presets,
    )
    deps.save_gui_settings(resolved_settings_path, snapshot)
    return snapshot


def _operator_snapshot_fields(state: OperatorState, previous_snapshot: GuiSettingsSnapshot) -> dict[str, object]:
    return {
        "last_input_path": state.input_path or previous_snapshot.last_input_path,
        "last_output_path": state.output_path or previous_snapshot.last_output_path,
        "cpu_profile": state.cpu_profile,
        "preserve_temp_files": bool(state.preserve_temp_files),
        "conversion_mode": state.conversion_mode,
        "material_policy": state.material_policy,
        "bark_material_path": state.bark_material_path,
        "leaves_material_path": state.leaves_material_path,
        "single_material_path": state.single_material_path,
        "gust_attenuation": float(state.gust_attenuation),
        "is_ground_cover": bool(state.is_ground_cover),
    }


def preset_from_operator_state(
    name: str,
    state: OperatorState,
    *,
    base_material_records: tuple[BaseMaterialSettingRecord, ...],
    part_source_records: tuple[PartSourceSettingRecord, ...],
    wind_group_records: dict[str, WindGroupSettingRecord],
) -> GuiPresetRecord:
    """Capture current operator values as a reusable named preset."""
    return GuiPresetRecord(
        name=name,
        cpu_profile=state.cpu_profile,
        preserve_temp_files=bool(state.preserve_temp_files),
        conversion_mode=state.conversion_mode,
        material_policy=state.material_policy,
        bark_material_path=state.bark_material_path,
        leaves_material_path=state.leaves_material_path,
        single_material_path=state.single_material_path,
        gust_attenuation=float(state.gust_attenuation),
        is_ground_cover=bool(state.is_ground_cover),
        wind_group_settings=dict(wind_group_records),
        base_material_settings=base_material_records,
        part_mesh_settings=part_source_records,
    )


def apply_preset_to_operator_state(state: OperatorState, preset: GuiPresetRecord) -> OperatorState:
    """Apply preset operator values while keeping the current input/output paths."""
    return replace(
        state,
        preserve_temp_files=bool(preset.preserve_temp_files),
        conversion_mode=preset.conversion_mode,
        material_policy=preset.material_policy,
        bark_material_path=preset.bark_material_path,
        leaves_material_path=preset.leaves_material_path,
        single_material_path=preset.single_material_path,
        gust_attenuation=float(preset.gust_attenuation),
        is_ground_cover=bool(preset.is_ground_cover),
    )
