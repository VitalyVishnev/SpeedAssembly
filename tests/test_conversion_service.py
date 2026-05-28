from __future__ import annotations

from pathlib import Path

import pytest

from xml_to_usda.asset_paths import is_valid_unreal_asset_path, normalize_unreal_asset_path
from xml_to_usda.conversion_service import prepare_conversion_plan
from xml_to_usda.models import (
    BaseMaterialOverride,
    CleanupPolicy,
    ConversionMode,
    CpuProfile,
    FbxMaterialMode,
    FbxMaterialSlotOverride,
    MaterialPolicy,
    PrototypeSourceConfig,
    PrototypeSourceMode,
    UdimMaterialSetting,
    UdimMode,
)
from xml_to_usda.prototype_keys import normalize_prototype_source_key
from xml_to_usda.skeleton_rules import joint_name_from_bone_id, parse_generator_label


SIMPLE_TREE_01 = Path(__file__).resolve().parents[1] / "samples" / "speedtree" / "simple_tree" / "variants" / "SimpleTree_01.xml"


def test_normalize_unreal_asset_path_trims_and_appends_package_name() -> None:
    assert normalize_unreal_asset_path("  /Game/Foo/Bar  ") == "/Game/Foo/Bar.Bar"
    assert normalize_unreal_asset_path("/Game/Foo/Bar.Bar") == "/Game/Foo/Bar.Bar"
    assert normalize_unreal_asset_path("Not/Game/Path") == "Not/Game/Path"


def test_is_valid_unreal_asset_path_requires_game_prefix() -> None:
    assert is_valid_unreal_asset_path("/Game/Foo/Bar.Bar") is True
    assert is_valid_unreal_asset_path("/Engine/Foo/Bar.Bar") is False
    assert is_valid_unreal_asset_path("Game/Foo/Bar.Bar") is False


def test_normalize_prototype_source_key_preserves_current_mesh_alias_rules() -> None:
    assert normalize_prototype_source_key("Mesh_7") == "Mesh_7"
    assert normalize_prototype_source_key("meshid:7") == "Mesh_7"
    assert normalize_prototype_source_key("mesh_id: 7") == "Mesh_7"
    assert normalize_prototype_source_key("7") == "Mesh_7"
    assert normalize_prototype_source_key("Twig_01") == "Twig_01"
    assert normalize_prototype_source_key("   ") == ""


def test_skeleton_rules_preserve_generator_label_and_joint_naming_behavior() -> None:
    assert parse_generator_label("Trunk", 1) == ("Trunk", 0)
    assert parse_generator_label("root", 1) == ("root", 0)
    assert parse_generator_label("Group_4", 1) == ("Group_4", 4)
    assert parse_generator_label("Branch 7", 1) == ("Branch 7", 7)
    assert parse_generator_label("Lateral", 1) == ("Lateral", None)
    assert parse_generator_label(None, 1) == (None, None)
    assert joint_name_from_bone_id(None) == "root"
    assert joint_name_from_bone_id(0) == "root"
    assert joint_name_from_bone_id(12) == "bone_012"


def test_prepare_conversion_plan_builds_default_material_request() -> None:
    plan = prepare_conversion_plan(
        input_path=str(SIMPLE_TREE_01),
        output_path="out.usda",
        cpu_profile=CpuProfile.BALANCED,
        cleanup_policy=CleanupPolicy.EPHEMERAL,
        material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
        bark_material_path="/Game/TestMaterials/M_Bark_Test",
        leaves_material_path="/Game/TestMaterials/M_Leaves_Test",
        single_material_path=None,
        base_material_overrides=(),
        prototype_source_configs=(),
        async_threshold_bytes=1_000_000_000,
    )

    assert plan.run_async is False
    assert plan.request.input_paths == (str(SIMPLE_TREE_01),)
    assert plan.request.output_path == "out.usda"
    assert plan.request.material_policy == MaterialPolicy.SOURCE_MATERIAL_ROLES
    assert plan.request.bark_material_path == "/Game/TestMaterials/M_Bark_Test"
    assert plan.request.leaves_material_path == "/Game/TestMaterials/M_Leaves_Test"
    assert plan.request.single_material_path is None
    assert plan.request.use_explicit_material_contract is False
    assert plan.request.conversion_mode == ConversionMode.SKELETAL_ASSEMBLY


def test_prepare_conversion_plan_preserves_udim_operator_intent() -> None:
    udim_settings = (
        UdimMaterialSetting(
            material_id=1,
            mode=UdimMode.WRITE_SECONDARY_UV_OFFSET,
            udim_id=1003,
        ),
    )

    plan = prepare_conversion_plan(
        input_path=str(SIMPLE_TREE_01),
        output_path="out.usda",
        cpu_profile=CpuProfile.BALANCED,
        cleanup_policy=CleanupPolicy.EPHEMERAL,
        material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
        bark_material_path=None,
        leaves_material_path=None,
        single_material_path=None,
        base_material_overrides=(),
        prototype_source_configs=(),
        async_threshold_bytes=1_000_000_000,
        udim_material_settings=udim_settings,
    )

    assert plan.request.udim_material_settings == udim_settings


def test_prepare_conversion_plan_preserves_global_fbx_cache_policy() -> None:
    plan = prepare_conversion_plan(
        input_path=str(SIMPLE_TREE_01),
        output_path="out.usda",
        cpu_profile=CpuProfile.BALANCED,
        cleanup_policy=CleanupPolicy.EPHEMERAL,
        material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
        bark_material_path=None,
        leaves_material_path=None,
        single_material_path=None,
        base_material_overrides=(),
        prototype_source_configs=(),
        async_threshold_bytes=1_000_000_000,
        fbx_cache_max_bytes=1234,
        fbx_cache_max_age_seconds=5678,
    )

    assert plan.request.fbx_cache_max_bytes == 1234
    assert plan.request.fbx_cache_max_age_seconds == 5678


def test_prepare_conversion_plan_builds_single_material_request() -> None:
    plan = prepare_conversion_plan(
        input_path=str(SIMPLE_TREE_01),
        output_path="out.usda",
        cpu_profile=CpuProfile.BALANCED,
        cleanup_policy=CleanupPolicy.EPHEMERAL,
        material_policy=MaterialPolicy.SINGLE_MATERIAL,
        bark_material_path="/Game/TestMaterials/M_Bark_Test",
        leaves_material_path="/Game/TestMaterials/M_Leaves_Test",
        single_material_path="/Game/Assembly/Fern/M_Fern.M_Fern",
        base_material_overrides=(),
        prototype_source_configs=(),
        async_threshold_bytes=1_000_000_000,
    )

    assert plan.request.material_policy == MaterialPolicy.SINGLE_MATERIAL
    assert plan.request.bark_material_path is None
    assert plan.request.leaves_material_path is None
    assert plan.request.single_material_path == "/Game/Assembly/Fern/M_Fern.M_Fern"
    assert plan.request.use_explicit_material_contract is False
    assert plan.request.conversion_mode == ConversionMode.SKELETAL_ASSEMBLY


def test_prepare_conversion_plan_marks_explicit_base_material_contract() -> None:
    plan = prepare_conversion_plan(
        input_path=str(SIMPLE_TREE_01),
        output_path="out.usda",
        cpu_profile=CpuProfile.QUIET,
        cleanup_policy=CleanupPolicy.PRESERVE_FOR_DEBUGGING,
        material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
        bark_material_path=None,
        leaves_material_path=None,
        single_material_path=None,
        base_material_overrides=(
            BaseMaterialOverride(
                source_id=1,
                source_name="Bark_Mat",
                ue_asset_path="/Game/TestMaterials/M_Bark_Test",
            ),
        ),
        prototype_source_configs=(),
        async_threshold_bytes=1_000_000_000,
    )

    assert plan.request.use_explicit_material_contract is True
    assert plan.request.base_material_overrides[0].ue_asset_path == "/Game/TestMaterials/M_Bark_Test"
    assert plan.request.cpu_profile == CpuProfile.QUIET
    assert plan.request.cleanup_policy == CleanupPolicy.PRESERVE_FOR_DEBUGGING


def test_prepare_conversion_plan_preserves_unreal_asset_part_override_request() -> None:
    config = PrototypeSourceConfig(
        source_key="Mesh_1",
        source_name="Twig_01",
        mode=PrototypeSourceMode.UNREAL_ASSET,
        asset_path="/Game/TreeParts/SK_Twig01.SK_Twig01",
    )
    plan = prepare_conversion_plan(
        input_path=str(SIMPLE_TREE_01),
        output_path="out.usda",
        cpu_profile=CpuProfile.BALANCED,
        cleanup_policy=CleanupPolicy.EPHEMERAL,
        material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
        bark_material_path=None,
        leaves_material_path=None,
        single_material_path=None,
        base_material_overrides=(),
        prototype_source_configs=(config,),
        async_threshold_bytes=1_000_000_000,
    )

    assert plan.run_async is False
    assert plan.request.use_explicit_material_contract is False
    assert plan.request.prototype_source_configs == (config,)


def test_prepare_conversion_plan_keeps_explicit_conversion_mode() -> None:
    plan = prepare_conversion_plan(
        input_path=str(SIMPLE_TREE_01),
        output_path="out.usda",
        cpu_profile=CpuProfile.BALANCED,
        cleanup_policy=CleanupPolicy.EPHEMERAL,
        material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
        bark_material_path=None,
        leaves_material_path=None,
        single_material_path=None,
        base_material_overrides=(),
        prototype_source_configs=(),
        conversion_mode=ConversionMode.SKELETAL_PARTS,
        async_threshold_bytes=1_000_000_000,
    )

    assert plan.request.conversion_mode == ConversionMode.SKELETAL_PARTS


def test_prepare_conversion_plan_forces_async_for_fbx_override(tmp_path: Path) -> None:
    fake_fbx_path = tmp_path / "fake_runtime_branch.fbx"
    fake_fbx_path.write_text("", encoding="utf-8")
    config = PrototypeSourceConfig(
        source_key="Mesh_1",
        source_name="Twig_01",
        mode=PrototypeSourceMode.FBX_FILE,
        fbx_path=str(fake_fbx_path),
        fbx_material_mode=FbxMaterialMode.SINGLE_MATERIAL,
        single_material_path="/Game/TreeParts/M_Twig.M_Twig",
    )
    plan = prepare_conversion_plan(
        input_path=str(SIMPLE_TREE_01),
        output_path="out.usda",
        cpu_profile=CpuProfile.QUIET,
        cleanup_policy=CleanupPolicy.PRESERVE_FOR_DEBUGGING,
        material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
        bark_material_path=None,
        leaves_material_path=None,
        single_material_path=None,
        base_material_overrides=(),
        prototype_source_configs=(config,),
        async_threshold_bytes=1_000_000_000,
    )

    assert plan.run_async is True
    assert plan.request.use_explicit_material_contract is True
    assert plan.request.prototype_source_configs == (config,)
    assert plan.request.cpu_profile == CpuProfile.QUIET
    assert plan.request.cleanup_policy == CleanupPolicy.PRESERVE_FOR_DEBUGGING


def test_prepare_conversion_plan_forces_async_when_threshold_is_reached() -> None:
    plan = prepare_conversion_plan(
        input_path=str(SIMPLE_TREE_01),
        output_path="out.usda",
        cpu_profile=CpuProfile.BALANCED,
        cleanup_policy=CleanupPolicy.EPHEMERAL,
        material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
        bark_material_path=None,
        leaves_material_path=None,
        single_material_path=None,
        base_material_overrides=(),
        prototype_source_configs=(),
        async_threshold_bytes=0,
    )

    assert plan.run_async is True


def test_prepare_conversion_plan_rejects_invalid_material_paths_with_current_messages() -> None:
    with pytest.raises(ValueError, match="Bark material path must start with /Game/."):
        prepare_conversion_plan(
            input_path=str(SIMPLE_TREE_01),
            output_path="out.usda",
            cpu_profile=CpuProfile.BALANCED,
            cleanup_policy=CleanupPolicy.EPHEMERAL,
            material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
            bark_material_path="Not/Game/Path",
            leaves_material_path=None,
            single_material_path=None,
            base_material_overrides=(),
            prototype_source_configs=(),
            async_threshold_bytes=1_000_000_000,
        )

    with pytest.raises(ValueError, match="Single material path for Twig_01 must start with /Game/."):
        prepare_conversion_plan(
            input_path=str(SIMPLE_TREE_01),
            output_path="out.usda",
            cpu_profile=CpuProfile.BALANCED,
            cleanup_policy=CleanupPolicy.EPHEMERAL,
            material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
            bark_material_path=None,
            leaves_material_path=None,
            single_material_path=None,
            base_material_overrides=(),
            prototype_source_configs=(
                PrototypeSourceConfig(
                    source_key="Mesh_1",
                    source_name="Twig_01",
                    mode=PrototypeSourceMode.XML_MESH,
                    fbx_material_mode=FbxMaterialMode.SINGLE_MATERIAL,
                    single_material_path="Not/Game/Path",
                ),
            ),
            async_threshold_bytes=1_000_000_000,
        )

    with pytest.raises(
        ValueError,
        match="Material Slots mode for Twig_01 requires at least one Unreal material path in the discovered FBX material slots.",
    ):
        prepare_conversion_plan(
            input_path=str(SIMPLE_TREE_01),
            output_path="out.usda",
            cpu_profile=CpuProfile.BALANCED,
            cleanup_policy=CleanupPolicy.EPHEMERAL,
            material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
            bark_material_path=None,
            leaves_material_path=None,
            single_material_path=None,
            base_material_overrides=(),
            prototype_source_configs=(
                PrototypeSourceConfig(
                    source_key="Mesh_1",
                    source_name="Twig_01",
                    mode=PrototypeSourceMode.FBX_FILE,
                    fbx_path=str(SIMPLE_TREE_01),
                    fbx_material_mode=FbxMaterialMode.MATERIAL_SLOTS,
                    fbx_material_slot_overrides=(),
                ),
            ),
            async_threshold_bytes=1_000_000_000,
        )


def test_prepare_conversion_plan_rejects_missing_input_and_output_with_current_messages() -> None:
    with pytest.raises(ValueError, match="Select a source XML file."):
        prepare_conversion_plan(
            input_path="",
            output_path="out.usda",
            cpu_profile=CpuProfile.BALANCED,
            cleanup_policy=CleanupPolicy.EPHEMERAL,
            material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
            bark_material_path=None,
            leaves_material_path=None,
            single_material_path=None,
            base_material_overrides=(),
            prototype_source_configs=(),
            async_threshold_bytes=1_000_000_000,
        )

    with pytest.raises(ValueError, match="Select an output USDA path."):
        prepare_conversion_plan(
            input_path=str(SIMPLE_TREE_01),
            output_path="",
            cpu_profile=CpuProfile.BALANCED,
            cleanup_policy=CleanupPolicy.EPHEMERAL,
            material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
            bark_material_path=None,
            leaves_material_path=None,
            single_material_path=None,
            base_material_overrides=(),
            prototype_source_configs=(),
            async_threshold_bytes=1_000_000_000,
        )


def test_prepare_conversion_plan_validates_fbx_material_slot_override_paths() -> None:
    with pytest.raises(ValueError, match="FBX material slot path for Twig_01 slot Bark must start with /Game/."):
        prepare_conversion_plan(
            input_path=str(SIMPLE_TREE_01),
            output_path="out.usda",
            cpu_profile=CpuProfile.BALANCED,
            cleanup_policy=CleanupPolicy.EPHEMERAL,
            material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
            bark_material_path=None,
            leaves_material_path=None,
            single_material_path=None,
            base_material_overrides=(),
            prototype_source_configs=(
                PrototypeSourceConfig(
                    source_key="Mesh_1",
                    source_name="Twig_01",
                    mode=PrototypeSourceMode.XML_MESH,
                    fbx_material_mode=FbxMaterialMode.MATERIAL_SLOTS,
                    fbx_material_slot_overrides=(
                        FbxMaterialSlotOverride(slot_name="Bark", ue_asset_path="Not/Game/Path"),
                    ),
                ),
            ),
            async_threshold_bytes=1_000_000_000,
        )
