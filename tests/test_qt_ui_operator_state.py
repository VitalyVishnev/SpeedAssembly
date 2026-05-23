from __future__ import annotations

from types import SimpleNamespace

from xml_to_usda.models import ConversionMode, CpuProfile, MaterialPolicy
from xml_to_usda.qt_ui.operator_state import (
    OperatorState,
    apply_preset_to_operator_state,
    load_base_material_records,
    load_operator_state,
    load_part_source_records,
    load_wind_group_records,
    preset_from_operator_state,
    save_nested_input_settings,
    save_operator_state,
)
from xml_to_usda.settings_service import (
    BaseMaterialSettingRecord,
    GuiPresetRecord,
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
            conversion_mode=ConversionMode.SKELETAL_PARTS,
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
    assert operator_state.cpu_profile == CpuProfile.BALANCED
    assert operator_state.preserve_temp_files is True
    assert operator_state.conversion_mode == ConversionMode.SKELETAL_PARTS
    assert operator_state.material_policy == MaterialPolicy.SINGLE_MATERIAL
    assert operator_state.single_material_path == "/Game/Assembly/SimpleTree/Bark1.Bark1"
    assert operator_state.gust_attenuation == 0.35
    assert operator_state.is_ground_cover is True
    assert snapshot.last_input_path == "D:/trees/tree.xml"
    assert snapshot.cpu_profile == CpuProfile.MAX_SPEED


def test_qt_operator_state_keeps_cpu_tuning_internal_for_operator_ui(tmp_path) -> None:
    settings_path = tmp_path / "gui_settings.json"
    save_gui_settings(
        settings_path,
        GuiSettingsSnapshot(
            last_input_path="D:/trees/tree.xml",
            last_output_path="D:/trees/tree.usda",
            cpu_profile=CpuProfile.MAX_SPEED,
        ),
    )
    deps = SimpleNamespace(load_gui_settings=load_gui_settings, save_gui_settings=save_gui_settings)

    operator_state, _snapshot = load_operator_state(deps, settings_path=settings_path)

    assert operator_state.cpu_profile == CpuProfile.BALANCED


def test_qt_operator_state_save_preserves_nested_records(tmp_path) -> None:
    settings_path = tmp_path / "gui_settings.json"
    deps = SimpleNamespace(load_gui_settings=load_gui_settings, save_gui_settings=save_gui_settings)
    original_snapshot = GuiSettingsSnapshot(
        last_input_path="old.xml",
        last_output_path="old.usda",
        conversion_mode=ConversionMode.SKELETAL_PARTS,
        wind_group_settings={"0": WindGroupSettingRecord(influence=0.8)},
        base_material_settings=(
            BaseMaterialSettingRecord(source_id=7, source_name="Bark", ue_asset_path="/Game/Bark.Bark"),
        ),
        part_mesh_settings=(PartSourceSettingRecord(source_name="Twig"),),
    )
    save_gui_settings(settings_path, original_snapshot)

    saved_snapshot = save_operator_state(
        deps,
        OperatorState(
            input_path="new.xml",
            output_path="new.usda",
            cpu_profile=CpuProfile.QUIET,
            conversion_mode=ConversionMode.SKELETAL_ASSEMBLY,
            material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
            bark_material_path="/Game/Bark.Bark",
            leaves_material_path="/Game/Leaves.Leaves",
        ),
        previous_snapshot=original_snapshot,
        settings_path=settings_path,
    )
    reloaded = load_gui_settings(settings_path)

    assert saved_snapshot.last_input_path == "new.xml"
    assert reloaded.last_output_path == "new.usda"
    assert reloaded.cpu_profile == CpuProfile.QUIET
    assert reloaded.conversion_mode == ConversionMode.SKELETAL_ASSEMBLY
    assert reloaded.base_material_settings == original_snapshot.base_material_settings
    assert reloaded.part_mesh_settings == original_snapshot.part_mesh_settings
    assert reloaded.wind_group_settings == original_snapshot.wind_group_settings


def test_qt_operator_state_loads_global_tab_records_without_input_key() -> None:
    snapshot = GuiSettingsSnapshot(
        wind_group_settings={"0": WindGroupSettingRecord(influence=0.4)},
        base_material_settings=(BaseMaterialSettingRecord(source_id=1, source_name="Bark"),),
        part_mesh_settings=(PartSourceSettingRecord(source_name="Twig"),),
    )

    assert load_base_material_records(snapshot) == snapshot.base_material_settings
    assert load_part_source_records(snapshot) == snapshot.part_mesh_settings
    assert load_wind_group_records(snapshot) == snapshot.wind_group_settings


def test_qt_operator_state_saves_tab_records_as_global_state(tmp_path) -> None:
    settings_path = tmp_path / "gui_settings.json"
    deps = SimpleNamespace(load_gui_settings=load_gui_settings, save_gui_settings=save_gui_settings)
    previous_snapshot = GuiSettingsSnapshot(last_input_path="old.xml", last_output_path="old.usda")

    snapshot = save_nested_input_settings(
        deps,
        OperatorState(conversion_mode=ConversionMode.STATIC_ASSEMBLY),
        previous_snapshot=previous_snapshot,
        base_material_records=(BaseMaterialSettingRecord(source_id=2, source_name="Leaf"),),
        part_source_records=(PartSourceSettingRecord(source_name="Branch"),),
        wind_group_records={"1": WindGroupSettingRecord(shift_top=0.2)},
        settings_path=settings_path,
    )
    reloaded = load_gui_settings(settings_path)

    assert snapshot.base_material_settings == (BaseMaterialSettingRecord(source_id=2, source_name="Leaf"),)
    assert snapshot.part_mesh_settings == (PartSourceSettingRecord(source_name="Branch"),)
    assert snapshot.wind_group_settings == {"1": WindGroupSettingRecord(shift_top=0.2)}
    assert reloaded == snapshot


def test_qt_operator_state_applies_preset_without_replacing_paths() -> None:
    state = OperatorState(input_path="tree.xml", output_path="tree.usda")
    preset = GuiPresetRecord(
        name="Static",
        conversion_mode=ConversionMode.STATIC_ASSEMBLY,
        material_policy=MaterialPolicy.SINGLE_MATERIAL,
        single_material_path="/Game/M_All.M_All",
        gust_attenuation=0.2,
        is_ground_cover=True,
    )

    applied = apply_preset_to_operator_state(state, preset)

    assert applied.input_path == "tree.xml"
    assert applied.output_path == "tree.usda"
    assert applied.conversion_mode == ConversionMode.STATIC_ASSEMBLY
    assert applied.material_policy == MaterialPolicy.SINGLE_MATERIAL
    assert applied.single_material_path == "/Game/M_All.M_All"
    assert applied.gust_attenuation == 0.2
    assert applied.is_ground_cover is True


def test_qt_operator_state_does_not_apply_cpu_profile_from_preset() -> None:
    state = OperatorState(cpu_profile=CpuProfile.BALANCED)
    preset = GuiPresetRecord(name="Legacy fast preset", cpu_profile=CpuProfile.MAX_SPEED)

    applied = apply_preset_to_operator_state(state, preset)

    assert applied.cpu_profile == CpuProfile.BALANCED


def test_qt_operator_state_captures_current_rows_as_preset() -> None:
    preset = preset_from_operator_state(
        "Branches",
        OperatorState(
            conversion_mode=ConversionMode.SKELETAL_PARTS,
            material_policy=MaterialPolicy.SINGLE_MATERIAL,
            single_material_path="/Game/M_All.M_All",
        ),
        base_material_records=(BaseMaterialSettingRecord(source_id=1, source_name="Bark"),),
        part_source_records=(PartSourceSettingRecord(source_name="Twig"),),
        wind_group_records={"0": WindGroupSettingRecord(influence=0.4)},
    )

    assert preset.name == "Branches"
    assert preset.conversion_mode == ConversionMode.SKELETAL_PARTS
    assert preset.base_material_settings[0].source_name == "Bark"
    assert preset.part_mesh_settings[0].source_name == "Twig"
    assert preset.wind_group_settings["0"].influence == 0.4
