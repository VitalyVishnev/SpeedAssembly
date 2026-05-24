from __future__ import annotations

import json
from pathlib import Path

from xml_to_usda.models import ConversionMode, CpuProfile, FbxMaterialMode, MaterialPolicy, PrototypeSourceMode, UdimMode
from xml_to_usda.settings_service import (
    BaseMaterialSettingRecord,
    FACTORY_DEFAULT_PRESET_NAME,
    FbxMaterialSlotSettingRecord,
    GuiPresetRecord,
    GuiSettingsSnapshot,
    PartSourceSettingRecord,
    WindGroupSettingRecord,
    factory_default_preset,
    load_gui_settings,
    load_gui_preset,
    resolve_input_settings_key,
    save_gui_settings,
    save_gui_preset,
    sorted_gui_presets,
)


def test_load_gui_settings_returns_defaults_for_missing_file(tmp_path: Path) -> None:
    snapshot = load_gui_settings(tmp_path / "missing.json")

    assert snapshot == GuiSettingsSnapshot()


def test_load_gui_settings_parses_legacy_payload_shape(tmp_path: Path) -> None:
    settings_path = tmp_path / "gui_settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "last_input_path": "tree.xml",
                "material_policy": "legacy_role_ids",
                "wind_group_settings": {
                    "0": {
                        "influence": 0.35,
                        "shift_top": 0.1,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    snapshot = load_gui_settings(settings_path)

    assert snapshot.last_input_path == "tree.xml"
    assert snapshot.material_policy == MaterialPolicy.SOURCE_MATERIAL_ROLES
    assert snapshot.wind_group_settings["0"].influence == 0.35
    assert snapshot.wind_group_settings["0"].shift_top == 0.1


def test_save_gui_settings_round_trips_current_snapshot_shape(tmp_path: Path) -> None:
    settings_path = tmp_path / "gui_settings.json"
    snapshot = GuiSettingsSnapshot(
        last_input_path="tree.xml",
        last_output_path="tree.usda",
        cpu_profile=CpuProfile.QUIET,
        preserve_temp_files=True,
        conversion_mode=ConversionMode.SKELETAL_PARTS,
        material_policy=MaterialPolicy.SINGLE_MATERIAL,
        bark_material_path="",
        leaves_material_path="",
        single_material_path="/Game/Assembly/Fern/M_Fern.M_Fern",
        gust_attenuation=0.6,
        is_ground_cover=True,
        wind_group_settings={
            "0": WindGroupSettingRecord(
                is_trunk_group=True,
                use_dual_influence=False,
                influence=0.7,
                min_influence=0.2,
                max_influence=0.4,
                shift_top=0.1,
            )
        },
        base_material_settings=(
            BaseMaterialSettingRecord(
                source_id=1,
                source_name="Bark_Mat",
                ue_asset_path="/Game/TestMaterials/M_Bark_Test",
            ),
        ),
        part_mesh_settings=(
            PartSourceSettingRecord(
                source_name="Twig_01",
                source_key="Mesh_1",
                source_mode=PrototypeSourceMode.FBX_FILE,
                fbx_path=str(tmp_path / "spruce_branch.fbx"),
                fbx_material_mode=FbxMaterialMode.MATERIAL_SLOTS,
                fbx_material_slot_overrides=(
                    FbxMaterialSlotSettingRecord(
                        slot_name="Bark",
                        ue_asset_path="/Game/TreeParts/M_Bark.M_Bark",
                    ),
                    FbxMaterialSlotSettingRecord(
                        slot_name="Needles",
                        ue_asset_path="",
                    ),
                ),
            ),
        ),
    )

    save_gui_settings(settings_path, snapshot)

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert payload["conversion_mode"] == ConversionMode.SKELETAL_PARTS.value
    assert payload["cpu_profile"] == CpuProfile.QUIET.value
    assert payload["preserve_temp_files"] is True
    assert payload["material_policy"] == MaterialPolicy.SINGLE_MATERIAL.value
    assert payload["wind_group_settings"]["0"]["is_trunk_group"] is True
    assert "base_material_settings_by_input_path" not in payload
    assert "part_mesh_settings_by_input_path" not in payload
    assert "wind_group_settings_by_input_path" not in payload
    assert payload["part_mesh_settings"][0]["fbx_material_mode"] == "material_slots"
    assert payload["part_mesh_settings"][0]["fbx_material_slot_overrides"] == [
        {"slot_name": "Bark", "ue_asset_path": "/Game/TreeParts/M_Bark.M_Bark"},
        {"slot_name": "Needles", "ue_asset_path": ""},
    ]

    restored = load_gui_settings(settings_path)
    assert restored == snapshot


def test_save_gui_settings_preserves_base_material_udim_settings(tmp_path: Path) -> None:
    settings_path = tmp_path / "gui_settings.json"
    snapshot = GuiSettingsSnapshot(
        base_material_settings=(
            BaseMaterialSettingRecord(
                source_id=1,
                source_name="Bark",
                udim_mode=UdimMode.WRITE_SECONDARY_UV_OFFSET,
                udim_id=1003,
            ),
        )
    )

    save_gui_settings(settings_path, snapshot)

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert payload["base_material_settings"][0]["udim_mode"] == UdimMode.WRITE_SECONDARY_UV_OFFSET.value
    assert payload["base_material_settings"][0]["udim_id"] == 1003
    assert load_gui_settings(settings_path).base_material_settings == snapshot.base_material_settings


def test_load_gui_settings_migrates_legacy_per_input_records_to_global_state(tmp_path: Path) -> None:
    settings_path = tmp_path / "gui_settings.json"
    tree_key = resolve_input_settings_key(str(tmp_path / "tree.xml"))
    settings_path.write_text(
        json.dumps(
            {
                "last_input_path": str(tmp_path / "tree.xml"),
                "wind_group_settings_by_input_path": {
                    tree_key: {"0": {"influence": 0.25}},
                },
                "base_material_settings_by_input_path": {
                    tree_key: [
                        {
                            "source_id": 1,
                            "source_name": "Bark",
                            "ue_asset_path": "/Game/M_Bark.M_Bark",
                        }
                    ],
                },
                "part_mesh_settings_by_input_path": {
                    tree_key: [
                        {
                            "source_name": "Branch",
                            "source_key": "Mesh_1",
                            "source_mode": "fbx_file",
                            "fbx_path": str(tmp_path / "branch.fbx"),
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    snapshot = load_gui_settings(settings_path)

    assert snapshot.wind_group_settings["0"].influence == 0.25
    assert snapshot.base_material_settings == (
        BaseMaterialSettingRecord(source_id=1, source_name="Bark", ue_asset_path="/Game/M_Bark.M_Bark"),
    )
    assert snapshot.part_mesh_settings[0].source_name == "Branch"
    assert snapshot.part_mesh_settings[0].source_mode == PrototypeSourceMode.FBX_FILE


def test_gui_settings_round_trips_named_presets(tmp_path: Path) -> None:
    settings_path = tmp_path / "gui_settings.json"
    preset = GuiPresetRecord(
        name="High Poly Branches",
        conversion_mode=ConversionMode.STATIC_ASSEMBLY,
        material_policy=MaterialPolicy.SINGLE_MATERIAL,
        single_material_path="/Game/Materials/M_All.M_All",
        gust_attenuation=0.25,
        is_ground_cover=True,
        wind_group_settings={"0": WindGroupSettingRecord(is_trunk_group=True, influence=0.45)},
        base_material_settings=(
            BaseMaterialSettingRecord(source_id=3, source_name="Bark", ue_asset_path="/Game/M_Bark.M_Bark"),
        ),
        part_mesh_settings=(
            PartSourceSettingRecord(
                source_name="Branch",
                source_key="Mesh_3",
                source_mode=PrototypeSourceMode.UNREAL_ASSET,
                unreal_asset_path="/Game/Branches/SK_Branch.SK_Branch",
            ),
        ),
    )
    snapshot = GuiSettingsSnapshot(
        active_preset_name=preset.name,
        presets={preset.name: preset},
    )

    save_gui_settings(settings_path, snapshot)
    restored = load_gui_settings(settings_path)

    assert restored.active_preset_name == "High Poly Branches"
    assert restored.presets["High Poly Branches"] == preset
    assert [item.name for item in sorted_gui_presets(restored)] == [
        FACTORY_DEFAULT_PRESET_NAME,
        "High Poly Branches",
    ]
    assert factory_default_preset().name == FACTORY_DEFAULT_PRESET_NAME


def test_gui_preset_import_export_round_trips_one_preset(tmp_path: Path) -> None:
    preset_path = tmp_path / "branches.json"
    preset = GuiPresetRecord(
        name="Branches",
        cpu_profile=CpuProfile.QUIET,
        preserve_temp_files=True,
        conversion_mode=ConversionMode.SKELETAL_PARTS,
        material_policy=MaterialPolicy.VERTEX_COLOR_SPLIT,
        bark_material_path="/Game/M_Bark.M_Bark",
        leaves_material_path="/Game/M_Leaves.M_Leaves",
        wind_group_settings={"1": WindGroupSettingRecord(shift_top=0.2)},
    )

    save_gui_preset(preset_path, preset)

    assert load_gui_preset(preset_path) == preset
