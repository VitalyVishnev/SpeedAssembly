from __future__ import annotations

import json
from pathlib import Path

import pytest

from xml_to_usda.fracture_collision import FractureCollisionMode, FractureCollisionSettings
from xml_to_usda.fracture_preview_service import FracturePreviewSettings
from xml_to_usda.fracture_service import FractureSettings
from xml_to_usda.models import ConversionMode, CpuProfile, FbxMaterialMode, MaterialPolicy, PrototypeSourceMode, UdimMode
from xml_to_usda.proxy_collision import ProxyCollisionMode, ProxyCollisionSettings
from xml_to_usda.proxy_mesh_service import ProxyMeshSettings
from xml_to_usda.settings_service import (
    BaseMaterialSettingRecord,
    GUI_SETTINGS_SCHEMA_VERSION,
    FACTORY_DEFAULT_PRESET_NAME,
    FbxMaterialSlotSettingRecord,
    GuiPresetRecord,
    GuiSettingsSnapshot,
    PartSourceSettingRecord,
    WindGroupSettingRecord,
    factory_default_preset,
    load_gui_settings,
    load_gui_preset,
    save_gui_settings,
    save_gui_preset,
    sorted_gui_presets,
)


def test_load_gui_settings_returns_defaults_for_missing_file(tmp_path: Path) -> None:
    snapshot = load_gui_settings(tmp_path / "missing.json")

    assert snapshot == GuiSettingsSnapshot()
    assert snapshot.dual_skinning is True


def test_load_gui_settings_discards_legacy_fracture_preview_face_budget(tmp_path: Path) -> None:
    settings_path = tmp_path / "gui_settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "schema_version": GUI_SETTINGS_SCHEMA_VERSION,
                "fracture_preview_settings": {"max_base_faces_per_piece": 50_000},
            }
        ),
        encoding="utf-8",
    )

    snapshot = load_gui_settings(settings_path)

    assert snapshot.fracture_preview_settings.max_base_faces_per_piece == 10_000_000


def test_load_gui_settings_rejects_payload_without_schema_version(tmp_path: Path) -> None:
    settings_path = tmp_path / "gui_settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "last_input_path": "tree.xml",
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

    with pytest.raises(ValueError, match="unsupported schema version"):
        load_gui_settings(settings_path)


def test_save_gui_settings_round_trips_current_snapshot_shape(tmp_path: Path) -> None:
    settings_path = tmp_path / "gui_settings.json"
    snapshot = GuiSettingsSnapshot(
        last_input_path="tree.xml",
        last_output_path="tree.usda",
        last_output_input_path="tree.xml",
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
                simplification_percent=45,
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
        proxy_mesh_settings=ProxyMeshSettings(
            final_polycount=12000,
            bounds_inflation=1.4,
            density_resolution=96,
            base_mesh_priority=0.22,
            fuse_base_mesh_vertices=True,
            branch_prune_aggression=0.61,
            collision=ProxyCollisionSettings(
                enabled=True,
                mode=ProxyCollisionMode.CAPSULE,
                height_multiplier=0.75,
                width_multiplier=1.5,
                one_per_stem=True,
            ),
        ),
        fracture_preview_settings=FracturePreviewSettings(
            fracture=FractureSettings(
                target_piece_count=0,
                generate_caps=True,
                preserve_trunk_bias=0.25,
                separate_stems=True,
                branch_height_bias=-0.5,
                auto_branch_cut_offset=0.43,
                detailed_cuts_enabled=True,
                detailed_cut_intensity=20.0,
                detailed_cut_scale=1.25,
                detailed_cut_density=12,
                detailed_cut_max_bend_angle=45.0,
            ),
            collision=FractureCollisionSettings(
                enabled=True,
                mode=FractureCollisionMode.SPHERE,
                include_instance_parts=False,
                sphere_radius_scale=0.75,
                capsule_scale_by_length=0.8,
                ghost_opacity=0.35,
            ),
            final_polycount=333000,
            base_mesh_priority=0.44,
            branch_prune_aggression=0.72,
        ),
        fbx_cache_max_size_gb=42,
        fbx_cache_max_age_days=7,
        debug_trace_enabled=True,
        wind_preview_session={
            "schema_version": 1,
            "fingerprint": [["root", None], ["branch", "root"]],
            "manual_groups": [{"layer_id": 0, "joint_tokens": ["branch"]}],
        },
    )

    save_gui_settings(settings_path, snapshot)

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == GUI_SETTINGS_SCHEMA_VERSION
    assert payload["conversion_mode"] == ConversionMode.SKELETAL_PARTS.value
    assert payload["cpu_profile"] == CpuProfile.QUIET.value
    assert payload["preserve_temp_files"] is True
    assert payload["material_policy"] == MaterialPolicy.SINGLE_MATERIAL.value
    assert payload["wind_group_settings"]["0"]["is_trunk_group"] is True
    assert "base_material_settings_by_input_path" not in payload
    assert "part_mesh_settings_by_input_path" not in payload
    assert "wind_group_settings_by_input_path" not in payload
    assert payload["part_mesh_settings"][0]["fbx_material_mode"] == "material_slots"
    assert payload["part_mesh_settings"][0]["simplification_percent"] == 45
    assert payload["proxy_mesh_settings"]["final_polycount"] == 12000
    assert payload["proxy_mesh_settings"]["bounds_inflation"] == 1.4
    assert payload["proxy_mesh_settings"]["density_resolution"] == 96
    assert payload["proxy_mesh_settings"]["base_mesh_priority"] == 0.22
    assert payload["proxy_mesh_settings"]["fuse_base_mesh_vertices"] is True
    assert payload["proxy_mesh_settings"]["branch_prune_aggression"] == 0.61
    assert payload["proxy_mesh_settings"]["collision"] == {
        "enabled": True,
        "mode": "capsule",
        "height_multiplier": 0.75,
        "width_multiplier": 1.5,
        "one_per_stem": True,
    }
    assert payload["fracture_preview_settings"]["fracture"]["target_piece_count"] == 0
    assert payload["fracture_preview_settings"]["fracture"]["separate_stems"] is True
    assert payload["fracture_preview_settings"]["fracture"]["branch_height_bias"] == -0.5
    assert payload["fracture_preview_settings"]["fracture"]["auto_branch_cut_offset"] == 0.43
    assert payload["fracture_preview_settings"]["fracture"]["detailed_cuts_enabled"] is True
    assert payload["fracture_preview_settings"]["fracture"]["detailed_cut_intensity"] == 20.0
    assert payload["fracture_preview_settings"]["fracture"]["detailed_cut_scale"] == 1.25
    assert payload["fracture_preview_settings"]["fracture"]["detailed_cut_density"] == 12
    assert payload["fracture_preview_settings"]["fracture"]["detailed_cut_max_bend_angle"] == 45.0
    assert payload["fracture_preview_settings"]["collision"]["mode"] == "sphere"
    assert payload["fracture_preview_settings"]["collision"]["enabled"] is True
    assert payload["fracture_preview_settings"]["collision"]["include_instance_parts"] is False
    assert payload["fracture_preview_settings"]["collision"]["capsule_scale_by_length"] == 0.8
    assert "branch_prune_aggression" not in payload["fracture_preview_settings"]
    assert "capsule_max_count" not in payload["fracture_preview_settings"]["collision"]
    assert "capsule_min_radius_ratio" not in payload["fracture_preview_settings"]["collision"]
    assert "capsule_radius_padding" not in payload["fracture_preview_settings"]["collision"]
    assert payload["fbx_cache_max_size_gb"] == 42
    assert payload["fbx_cache_max_age_days"] == 7
    assert payload["debug_trace_enabled"] is True
    assert payload["wind_preview_session"]["fingerprint"] == [["root", None], ["branch", "root"]]
    assert payload["part_mesh_settings"][0]["fbx_material_slot_overrides"] == [
        {
            "slot_name": "Bark",
            "ue_asset_path": "/Game/TreeParts/M_Bark.M_Bark",
            "udim_mode": UdimMode.OFF.value,
            "udim_id": 1001,
        },
        {
            "slot_name": "Needles",
            "ue_asset_path": "",
            "udim_mode": UdimMode.OFF.value,
            "udim_id": 1001,
        },
    ]

    restored = load_gui_settings(settings_path)
    assert restored.last_input_path == snapshot.last_input_path
    assert restored.last_output_path == snapshot.last_output_path
    assert restored.last_output_input_path == snapshot.last_output_input_path
    assert restored.cpu_profile == snapshot.cpu_profile
    assert restored.preserve_temp_files is True
    assert restored.conversion_mode == snapshot.conversion_mode
    assert restored.material_policy == snapshot.material_policy
    assert restored.fbx_cache_max_size_gb == 42
    assert restored.fbx_cache_max_age_days == 7
    assert restored.debug_trace_enabled is True
    assert restored.wind_preview_session == snapshot.wind_preview_session
    assert restored.single_material_path == snapshot.single_material_path
    assert restored.wind_group_settings == snapshot.wind_group_settings
    assert restored.base_material_settings == snapshot.base_material_settings
    assert restored.proxy_mesh_settings == snapshot.proxy_mesh_settings
    assert restored.fracture_preview_settings == FracturePreviewSettings(
        fracture=snapshot.fracture_preview_settings.fracture,
        collision=snapshot.fracture_preview_settings.collision,
        final_polycount=snapshot.fracture_preview_settings.final_polycount,
        base_mesh_priority=snapshot.fracture_preview_settings.base_mesh_priority,
    )
    assert len(restored.part_mesh_settings) == 1
    restored_part = restored.part_mesh_settings[0]
    assert restored_part.source_name == "Twig_01"
    assert restored_part.source_key == "Mesh_1"
    assert restored_part.source_mode == PrototypeSourceMode.FBX_FILE
    assert restored_part.fbx_path == str(tmp_path / "spruce_branch.fbx")
    assert restored_part.fbx_material_mode == FbxMaterialMode.MATERIAL_SLOTS
    assert restored_part.simplification_percent == 45
    assert len(restored_part.fbx_material_slot_overrides) == 2
    assert restored_part.fbx_material_slot_overrides[0].slot_name == "Bark"
    assert restored_part.fbx_material_slot_overrides[0].udim_mode == UdimMode.OFF
    assert restored_part.fbx_material_slot_overrides[0].udim_id == 1001


def test_load_gui_settings_uses_fbx_cache_defaults_for_legacy_payload(tmp_path: Path) -> None:
    settings_path = tmp_path / "gui_settings.json"
    settings_path.write_text(json.dumps({"schema_version": GUI_SETTINGS_SCHEMA_VERSION}), encoding="utf-8")

    restored = load_gui_settings(settings_path)

    assert restored.fbx_cache_max_size_gb == 20
    assert restored.fbx_cache_max_age_days == 14


def test_load_gui_settings_clamps_imported_proxy_density_to_supported_cap(tmp_path: Path) -> None:
    settings_path = tmp_path / "gui_settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "schema_version": GUI_SETTINGS_SCHEMA_VERSION,
                "proxy_mesh_settings": {"density_resolution": 999999},
            }
        ),
        encoding="utf-8",
    )

    restored = load_gui_settings(settings_path)

    assert restored.proxy_mesh_settings.density_resolution == 512
    assert restored.proxy_mesh_settings.collision == ProxyCollisionSettings()


def test_load_gui_settings_clamps_imported_proxy_branch_prune_aggression(tmp_path: Path) -> None:
    settings_path = tmp_path / "gui_settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "schema_version": GUI_SETTINGS_SCHEMA_VERSION,
                "proxy_mesh_settings": {"branch_prune_aggression": 5.0},
            }
        ),
        encoding="utf-8",
    )

    restored = load_gui_settings(settings_path)

    assert restored.proxy_mesh_settings.branch_prune_aggression == 1.0


def test_load_gui_settings_ignores_imported_fracture_branch_prune_aggression(tmp_path: Path) -> None:
    settings_path = tmp_path / "gui_settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "schema_version": GUI_SETTINGS_SCHEMA_VERSION,
                "fracture_preview_settings": {"branch_prune_aggression": 0.97},
            }
        ),
        encoding="utf-8",
    )

    restored = load_gui_settings(settings_path)

    assert restored.fracture_preview_settings.branch_prune_aggression == 0.0


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

    payload = json.loads(preset_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == GUI_SETTINGS_SCHEMA_VERSION
    assert "fbx_cache_max_size_gb" not in payload
    assert "fbx_cache_max_age_days" not in payload
    assert load_gui_preset(preset_path) == preset
