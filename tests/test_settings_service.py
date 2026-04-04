from __future__ import annotations

import json
from pathlib import Path

from xml_to_usda.models import CpuProfile, FbxMaterialMode, MaterialPolicy, PrototypeSourceMode
from xml_to_usda.settings_service import (
    BaseMaterialSettingRecord,
    FbxMaterialSlotSettingRecord,
    GuiSettingsSnapshot,
    PartSourceSettingRecord,
    WindGroupSettingRecord,
    load_gui_settings,
    resolve_input_settings_key,
    save_gui_settings,
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
    input_key = resolve_input_settings_key(str(tmp_path / "tree.xml"))
    snapshot = GuiSettingsSnapshot(
        last_input_path="tree.xml",
        last_output_path="tree.usda",
        cpu_profile=CpuProfile.QUIET,
        preserve_temp_files=True,
        material_policy=MaterialPolicy.SINGLE_MATERIAL,
        bark_material_path="",
        leaves_material_path="",
        single_material_path="/Game/Assembly/Fern/M_Fern.M_Fern",
        gust_attenuation=0.6,
        is_ground_cover=True,
        wind_group_settings={
            "0": WindGroupSettingRecord(
                use_dual_influence=False,
                influence=0.7,
                min_influence=0.2,
                max_influence=0.4,
                shift_top=0.1,
            )
        },
        wind_group_settings_by_input_path={
            input_key: {
                "0": WindGroupSettingRecord(influence=0.35, shift_top=0.1),
            }
        },
        base_material_settings_by_input_path={
            input_key: (
                BaseMaterialSettingRecord(
                    source_id=1,
                    source_name="Bark_Mat",
                    ue_asset_path="/Game/TestMaterials/M_Bark_Test",
                ),
            )
        },
        part_mesh_settings_by_input_path={
            input_key: (
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
            )
        },
    )

    save_gui_settings(settings_path, snapshot)

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert payload["cpu_profile"] == CpuProfile.QUIET.value
    assert payload["preserve_temp_files"] is True
    assert payload["material_policy"] == MaterialPolicy.SINGLE_MATERIAL.value
    assert payload["part_mesh_settings_by_input_path"][input_key][0]["fbx_material_mode"] == "material_slots"
    assert payload["part_mesh_settings_by_input_path"][input_key][0]["fbx_material_slot_overrides"] == [
        {"slot_name": "Bark", "ue_asset_path": "/Game/TreeParts/M_Bark.M_Bark"},
        {"slot_name": "Needles", "ue_asset_path": ""},
    ]

    restored = load_gui_settings(settings_path)
    assert restored == snapshot
