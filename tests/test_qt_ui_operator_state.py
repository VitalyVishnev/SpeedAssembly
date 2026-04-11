from __future__ import annotations

from types import SimpleNamespace

from xml_to_usda.models import CpuProfile, MaterialPolicy
from xml_to_usda.qt_ui.operator_state import OperatorState, load_operator_state, save_operator_state
from xml_to_usda.settings_service import (
    BaseMaterialSettingRecord,
    GuiSettingsSnapshot,
    PartSourceSettingRecord,
    WindGroupSettingRecord,
    load_gui_settings,
    save_gui_settings,
)


def test_qt_operator_state_loads_shared_gui_snapshot(tmp_path) -> None:
    settings_path = tmp_path / "gui_settings.json"
    save_gui_settings(
        settings_path,
        GuiSettingsSnapshot(
            last_input_path="D:/trees/tree.xml",
            last_output_path="D:/trees/tree.usda",
            cpu_profile=CpuProfile.MAX_SPEED,
            preserve_temp_files=True,
            material_policy=MaterialPolicy.SINGLE_MATERIAL,
            single_material_path="/Game/Assembly/SimpleTree/Bark1.Bark1",
            gust_attenuation=0.35,
            is_ground_cover=True,
        ),
    )
    deps = SimpleNamespace(load_gui_settings=load_gui_settings, save_gui_settings=save_gui_settings)

    operator_state, snapshot = load_operator_state(deps, settings_path=settings_path)

    assert operator_state.input_path == ""
    assert operator_state.output_path == ""
    assert operator_state.cpu_profile == CpuProfile.MAX_SPEED
    assert operator_state.preserve_temp_files is True
    assert operator_state.material_policy == MaterialPolicy.SINGLE_MATERIAL
    assert operator_state.single_material_path == "/Game/Assembly/SimpleTree/Bark1.Bark1"
    assert operator_state.gust_attenuation == 0.35
    assert operator_state.is_ground_cover is True
    assert snapshot.last_input_path == "D:/trees/tree.xml"


def test_qt_operator_state_save_preserves_nested_records(tmp_path) -> None:
    settings_path = tmp_path / "gui_settings.json"
    deps = SimpleNamespace(load_gui_settings=load_gui_settings, save_gui_settings=save_gui_settings)
    original_snapshot = GuiSettingsSnapshot(
        last_input_path="old.xml",
        last_output_path="old.usda",
        wind_group_settings={"0": WindGroupSettingRecord(influence=0.8)},
        wind_group_settings_by_input_path={"foo": {"1": WindGroupSettingRecord(shift_top=0.4)}},
        base_material_settings_by_input_path={
            "foo": (BaseMaterialSettingRecord(source_id=7, source_name="Bark", ue_asset_path="/Game/Bark.Bark"),)
        },
        part_mesh_settings_by_input_path={"foo": (PartSourceSettingRecord(source_name="Twig"),)},
    )
    save_gui_settings(settings_path, original_snapshot)

    saved_snapshot = save_operator_state(
        deps,
        OperatorState(
            input_path="new.xml",
            output_path="new.usda",
            cpu_profile=CpuProfile.QUIET,
            material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
            bark_material_path="/Game/Bark.Bark",
            leaves_material_path="/Game/Leaves.Leaves",
        ),
        previous_snapshot=original_snapshot,
        settings_path=settings_path,
    )
    reloaded = load_gui_settings(settings_path)

    assert saved_snapshot.last_input_path == "old.xml"
    assert reloaded.last_output_path == "old.usda"
    assert reloaded.cpu_profile == CpuProfile.QUIET
    assert reloaded.base_material_settings_by_input_path == original_snapshot.base_material_settings_by_input_path
    assert reloaded.part_mesh_settings_by_input_path == original_snapshot.part_mesh_settings_by_input_path
    assert reloaded.wind_group_settings_by_input_path == original_snapshot.wind_group_settings_by_input_path
