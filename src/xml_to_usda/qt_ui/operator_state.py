"""Operator-facing settings bridge for the PySide6 shell.

Layer: UI/application boundary.

The PySide6 shell reuses the existing GUI settings payload so operator defaults,
material policy, and wind settings survive across Tk and Qt launches.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..models import ConversionMode, CpuProfile, MaterialPolicy
from ..settings_service import (
    BaseMaterialSettingRecord,
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
    """Load shared operator defaults while keeping the Qt shell visually blank on startup."""
    resolved_settings_path = Path(settings_path) if settings_path is not None else SETTINGS_PATH
    snapshot = deps.load_gui_settings(resolved_settings_path)
    return (
        OperatorState(
            input_path="",
            output_path="",
            cpu_profile=snapshot.cpu_profile,
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
        last_input_path=previous_snapshot.last_input_path,
        last_output_path=previous_snapshot.last_output_path,
        cpu_profile=state.cpu_profile,
        preserve_temp_files=bool(state.preserve_temp_files),
        conversion_mode=state.conversion_mode,
        material_policy=state.material_policy,
        bark_material_path=state.bark_material_path,
        leaves_material_path=state.leaves_material_path,
        single_material_path=state.single_material_path,
        gust_attenuation=float(state.gust_attenuation),
        is_ground_cover=bool(state.is_ground_cover),
        wind_group_settings=previous_snapshot.wind_group_settings,
        wind_group_settings_by_input_path=previous_snapshot.wind_group_settings_by_input_path,
        base_material_settings_by_input_path=previous_snapshot.base_material_settings_by_input_path,
        part_mesh_settings_by_input_path=previous_snapshot.part_mesh_settings_by_input_path,
    )
    deps.save_gui_settings(resolved_settings_path, snapshot)
    return snapshot


def resolve_settings_key(deps: QtUiDependencies, input_path: str) -> str | None:
    """Resolve the persisted per-input key when an XML path is available."""
    resolved = input_path.strip()
    if not resolved:
        return None
    return str(deps.resolve_input_settings_key(resolved))


def load_base_material_records(
    snapshot: GuiSettingsSnapshot,
    *,
    settings_key: str | None,
) -> tuple[BaseMaterialSettingRecord, ...]:
    if not settings_key:
        return ()
    return snapshot.base_material_settings_by_input_path.get(settings_key, ())


def load_part_source_records(
    snapshot: GuiSettingsSnapshot,
    *,
    settings_key: str | None,
) -> tuple[PartSourceSettingRecord, ...]:
    if not settings_key:
        return ()
    return snapshot.part_mesh_settings_by_input_path.get(settings_key, ())


def load_wind_group_records(
    snapshot: GuiSettingsSnapshot,
    *,
    settings_key: str | None,
) -> dict[str, WindGroupSettingRecord]:
    if settings_key and settings_key in snapshot.wind_group_settings_by_input_path:
        return dict(snapshot.wind_group_settings_by_input_path[settings_key])
    if not snapshot.wind_group_settings_by_input_path:
        return dict(snapshot.wind_group_settings)
    return {}


def save_nested_input_settings(
    deps: QtUiDependencies,
    state: OperatorState,
    *,
    previous_snapshot: GuiSettingsSnapshot,
    settings_key: str | None,
    base_material_records: tuple[BaseMaterialSettingRecord, ...],
    part_source_records: tuple[PartSourceSettingRecord, ...],
    wind_group_records: dict[str, WindGroupSettingRecord],
    settings_path: str | Path | None = None,
) -> GuiSettingsSnapshot:
    """Persist current operator defaults plus per-input tab settings without replacing shared file-path history."""
    resolved_settings_path = Path(settings_path) if settings_path is not None else SETTINGS_PATH

    base_material_settings_by_input_path = dict(previous_snapshot.base_material_settings_by_input_path)
    part_mesh_settings_by_input_path = dict(previous_snapshot.part_mesh_settings_by_input_path)
    wind_group_settings_by_input_path = dict(previous_snapshot.wind_group_settings_by_input_path)

    if settings_key:
        if base_material_records:
            base_material_settings_by_input_path[settings_key] = base_material_records
        else:
            base_material_settings_by_input_path.pop(settings_key, None)
        if part_source_records:
            part_mesh_settings_by_input_path[settings_key] = part_source_records
        else:
            part_mesh_settings_by_input_path.pop(settings_key, None)
        if wind_group_records:
            wind_group_settings_by_input_path[settings_key] = dict(wind_group_records)
        else:
            wind_group_settings_by_input_path.pop(settings_key, None)

    snapshot = GuiSettingsSnapshot(
        last_input_path=previous_snapshot.last_input_path,
        last_output_path=previous_snapshot.last_output_path,
        cpu_profile=state.cpu_profile,
        preserve_temp_files=bool(state.preserve_temp_files),
        conversion_mode=state.conversion_mode,
        material_policy=state.material_policy,
        bark_material_path=state.bark_material_path,
        leaves_material_path=state.leaves_material_path,
        single_material_path=state.single_material_path,
        gust_attenuation=float(state.gust_attenuation),
        is_ground_cover=bool(state.is_ground_cover),
        wind_group_settings=previous_snapshot.wind_group_settings,
        wind_group_settings_by_input_path=wind_group_settings_by_input_path,
        base_material_settings_by_input_path=base_material_settings_by_input_path,
        part_mesh_settings_by_input_path=part_mesh_settings_by_input_path,
    )
    deps.save_gui_settings(resolved_settings_path, snapshot)
    return snapshot
