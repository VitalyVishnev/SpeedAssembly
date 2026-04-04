from __future__ import annotations

import json
import threading
import xml.etree.ElementTree as ET
from dataclasses import replace
from enum import Enum
from pathlib import Path

import pytest

from xml_to_usda.dynamic_wind import build_dynamic_wind_data
from xml_to_usda.fbx_adapter import FbxVertexColorReadError, _read_vertex_color
from xml_to_usda.normalizer import (
    _build_base_mesh,
    _extract_assembly_parts_from_leaf_references,
    _extract_bounds,
    _mesh_with_original_scale,
    _read_float_list,
    _read_positive_float,
    normalize_to_canonical,
)
from xml_to_usda.models import (
    BaseMaterialOverride,
    Color4,
    CpuProfile,
    DynamicWindSimulationGroup,
    FbxMaterialMode,
    FbxMaterialSlotOverride,
    Joint,
    MaterialPolicy,
    MaterialSpec,
    Matrix4d,
    MeshData,
    MeshLibraryEntry,
    MeshSection,
    PrototypeSourceConfig,
    PrototypeSourceMode,
    SourceObject,
    PrototypeResolutionMode,
    Vector3,
)
from xml_to_usda.job_control import ConversionCancelledError, cpu_worker_count, reserved_cpu_count
from xml_to_usda.normalizer import _vertex_color_material_sections
from xml_to_usda.pipeline import (
    _apply_material_policy,
    convert_file,
    discover_source_materials,
    discover_part_prototypes,
    generate_wind_json,
    inspect_source,
    inspect_wind_data,
    load_canonical_model,
)
from xml_to_usda.prototype_sources import load_prototype_source_configs_from_json
from xml_to_usda.runtime_paths import resolve_runtime_paths
from xml_to_usda.source_transform import build_source_transform
from xml_to_usda.ue_schema import DEFAULT_UE_SCHEMA_CONTRACT
from xml_to_usda.usda_writer import render_usda, write_usda_document
from xml_to_usda.validator import validate_model
from xml_to_usda.xml_reader import inspect_xml, read_source_xml, render_inspect_report


DATA_DIR = Path(__file__).parent / "data"
SIMPLE_TREE_01 = Path(__file__).resolve().parents[1] / "samples" / "speedtree" / "simple_tree" / "variants" / "SimpleTree_01.xml"
LEAFREFS_ON_TRUNK = DATA_DIR / "leafrefs_on_trunk.xml"
LEAFREFS_ON_BRANCH_LEVELS = DATA_DIR / "leafrefs_on_branch_levels.xml"
INVALID_LEAF_BONE = DATA_DIR / "invalid_leaf_bone.xml"


def _test_runtime_paths(tmp_path: Path):
    return resolve_runtime_paths(
        settings_dir=tmp_path / "settings",
        settings_path=tmp_path / "settings" / "gui_settings.json",
        cache_root=tmp_path / "runtime_cache",
    )


def _write_fbx_json_payload(
    tmp_path: Path,
    *,
    include_vertex_colors: bool = True,
    color_components: list[float] | None = None,
    fbx_material_slots: list[dict[str, object]] | None = None,
    sections: list[dict[str, object]] | None = None,
    file_name: str = "prototype_payload.json",
) -> Path:
    payload = {
        "point_components": [
            0.0, 0.0, 0.0,
            1.0, 0.0, 0.0,
            0.0, 1.0, 0.0,
            0.0, 0.0, 1.0,
            1.0, 0.0, 1.0,
            0.0, 1.0, 1.0,
        ],
        "face_vertex_counts": [3, 3],
        "face_vertex_indices": [0, 1, 2, 3, 4, 5],
        "uv_components": [
            0.0, 0.0,
            1.0, 0.0,
            0.0, 1.0,
            0.0, 0.0,
            1.0, 0.0,
            0.0, 1.0,
        ],
    }
    if color_components is not None:
        payload["vertex_color_components"] = color_components
    elif include_vertex_colors:
        payload["vertex_color_components"] = [
            0.0, 0.0, 0.0, 1.0,
            0.0, 0.0, 0.0, 1.0,
            0.0, 0.0, 0.0, 1.0,
            1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 1.0,
        ]
    if fbx_material_slots is not None:
        payload["fbx_material_slots"] = fbx_material_slots
    if sections is not None:
        payload["sections"] = sections
    payload_path = tmp_path / file_name
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    return payload_path


def _write_generator_level_sample(tmp_path: Path, generator_labels: tuple[str | None, ...]) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    bone_lines: list[str] = ["<SpeedTreeRaw>", "  <Bones>"]
    for bone_id, generator_label in enumerate(generator_labels):
        parent_id = bone_id - 1 if bone_id > 0 else -1
        generator_attribute = f' Generator="{generator_label}"' if generator_label is not None else ""
        bone_lines.append(
            f'    <Bone ID="{bone_id}" ParentID="{parent_id}" StartX="0" StartY="0" StartZ="{bone_id}" '
            f'EndX="0" EndY="0" EndZ="{bone_id + 1}"{generator_attribute} />'
        )
    bone_lines.extend(["  </Bones>", "</SpeedTreeRaw>"])
    sample_path = tmp_path / "wind_generator_levels.xml"
    sample_path.write_text("\n".join(bone_lines), encoding="utf-8")
    return sample_path


def _write_shifted_material_sample(tmp_path: Path, material_id_map: dict[int, int]) -> Path:
    tree = ET.parse(SIMPLE_TREE_01)
    root = tree.getroot()

    for material_node in root.findall(".//Materials/Material"):
        raw_id = material_node.attrib.get("ID")
        if raw_id is None or not raw_id.isdigit():
            continue
        mapped_id = material_id_map.get(int(raw_id))
        if mapped_id is not None:
            material_node.set("ID", str(mapped_id))

    for node in root.iter():
        raw_id = node.attrib.get("Material")
        if raw_id is None or not raw_id.lstrip("-").isdigit():
            continue
        mapped_id = material_id_map.get(int(raw_id))
        if mapped_id is not None:
            node.set("Material", str(mapped_id))

    sample_path = tmp_path / "shifted_material_ids.xml"
    tree.write(sample_path, encoding="utf-8", xml_declaration=True)
    return sample_path


def test_load_prototype_source_configs_from_json_reads_fbx_and_unreal_modes(tmp_path: Path) -> None:
    payload_path = _write_fbx_json_payload(tmp_path)
    config_path = tmp_path / "part_sources.json"
    config_path.write_text(
        json.dumps(
            {
                "Twig_01": {
                    "mode": "fbx_file",
                    "fbx_path": str(payload_path),
                    "fbx_material_mode": "single_material",
                },
                "Mesh_2": {"mode": "unreal_asset", "asset_path": "/Game/TreeParts/SK_Twig02.SK_Twig02"},
            }
        ),
        encoding="utf-8",
    )

    configs = load_prototype_source_configs_from_json(str(config_path))

    assert configs == (
        PrototypeSourceConfig(
            source_key="Twig_01",
            source_name="",
            mode=PrototypeSourceMode.FBX_FILE,
            fbx_material_mode=FbxMaterialMode.SINGLE_MATERIAL,
            asset_path=None,
            fbx_path=str(payload_path),
        ),
        PrototypeSourceConfig(
            source_key="Mesh_2",
            source_name="",
            mode=PrototypeSourceMode.UNREAL_ASSET,
            fbx_material_mode=FbxMaterialMode.AUTO,
            asset_path="/Game/TreeParts/SK_Twig02.SK_Twig02",
            fbx_path=None,
        ),
    )


def test_cpu_profile_worker_count_math() -> None:
    assert reserved_cpu_count(CpuProfile.BALANCED, cpu_count=8) == 2
    assert cpu_worker_count(CpuProfile.BALANCED, cpu_count=8) == 6
    assert reserved_cpu_count(CpuProfile.MAX_SPEED, cpu_count=8) == 1
    assert cpu_worker_count(CpuProfile.MAX_SPEED, cpu_count=8) == 7
    assert reserved_cpu_count(CpuProfile.QUIET, cpu_count=8) == 4
    assert cpu_worker_count(CpuProfile.QUIET, cpu_count=8) == 4


def test_inspect_report_tracks_structure_without_sample_specific_contracts() -> None:
    report = inspect_source(SIMPLE_TREE_01)
    payload = json.loads(render_inspect_report(report))

    assert payload["root_tag"] == "SpeedTreeRaw"
    assert payload["hierarchy_depth"] >= 1
    assert payload["object_class_counts"]["root"] >= 1
    assert payload["object_class_counts"]["mesh_object"] >= 1
    assert payload["object_class_counts"]["leaf_reference_host"] >= 1
    assert "Spine" not in payload["unknown_sections"]
    assert payload["leaf_binding_distribution"]
    assert payload["leaf_mesh_distribution"]
    assert payload["leaf_source_object_distribution"]
    assert payload["material_count"] == 2
    assert payload["base_material_distribution"] == {"1": payload["base_mesh_face_count"]}
    assert payload["prototype_material_distribution"]["1"] > 0
    assert payload["base_geometry_mode"] == "merged"
    assert payload["base_mesh_part_count"] >= 2
    assert payload["base_mesh_point_count"] > 0
    assert payload["base_mesh_face_count"] > 0
    assert payload["prototype_structure"] == "inline_skeletal_part"
    assert payload["binding_mode"] == "single_joint"
    assert payload["binding_element_size"] == 1
    assert set(payload["support_primvars"]) == {
        "boneCapture_pCaptPath",
        "hierarchicalDepth",
        "localtransform",
        "logicalDepth",
        "ueJointNames",
    }
    assert len(payload["orientation_sample"]) == 3


def test_discover_part_prototypes_matches_canonical_prototype_identity_for_gui_loading() -> None:
    discovered = discover_part_prototypes(str(SIMPLE_TREE_01))
    _, model, _ = load_canonical_model(str(SIMPLE_TREE_01))
    instance_counts_by_key: dict[str, int] = {}
    for part in model.assembly_parts:
        instance_counts_by_key[part.prototype_key] = instance_counts_by_key.get(part.prototype_key, 0) + 1

    assert [
        (prototype.source_key, prototype.source_name, prototype.source_mesh_id, prototype.instance_count)
        for prototype in discovered
    ] == [
        (prototype.source_key, prototype.source_name, prototype.source_mesh_id, instance_counts_by_key[prototype.source_key])
        for prototype in model.prototypes
    ]


def test_canonical_model_extracts_base_tree_and_assembly_parts() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)

    assert model.base_mesh is not None
    assert len(model.materials) == 2
    assert model.source_objects
    assert model.skeleton
    assert model.base_tree_parts
    assert model.branch_segments
    assert model.assembly_parts
    assert model.mesh_library
    assert model.prototypes
    assert model.skeletal_support_primvars is not None
    assert model.dynamic_wind is None
    assert model.binding_mode == "single_joint"
    assert model.binding_element_size == 1
    assert model.base_mesh.skel_joint_indices
    assert model.base_mesh.skel_joint_weights
    assert model.base_mesh.uv_coords
    assert (model.skeleton[0].bind_translate.x, model.skeleton[0].bind_translate.y, model.skeleton[0].bind_translate.z) == pytest.approx((0.0, 0.0, 0.0))
    assert (model.skeleton[0].rest_translate.x, model.skeleton[0].rest_translate.y, model.skeleton[0].rest_translate.z) == pytest.approx((0.0, 0.0, 0.0))
    assert model.skeleton[1].bind_translate == pytest.approx(model.skeleton[1].rest_translate)
    assert abs(model.skeleton[1].bind_translate.y) > 0
    assert len(model.base_mesh.skel_joint_indices) == len(model.base_mesh.points)
    assert len(model.base_mesh.skel_joint_weights) == len(model.base_mesh.points)
    assert len(model.base_mesh.uv_coords) == len(model.base_mesh.face_vertex_indices)
    assert {material.source_id for material in model.materials} == {1, 2}
    assert {section.material_id for section in model.base_mesh.sections} == {1}
    assert all(
        prototype.mesh is not None and {section.material_id for section in prototype.mesh.sections} == {1}
        for prototype in model.prototypes
    )
    assert all(part.binding.joint_tokens for part in model.assembly_parts)
    assert all(len(part.binding.joint_tokens) == len(part.binding.weights) for part in model.assembly_parts)
    assert all(token.startswith("bone_") or token == "root" for part in model.assembly_parts for token in part.binding.joint_tokens)
    assert {prototype.source_key for prototype in model.prototypes} == {part.prototype_key for part in model.assembly_parts}


def test_dynamic_wind_groups_follow_vertical_levels_without_horizontal_bias() -> None:
    skeleton = (
        Joint(
            name="root",
            parent=None,
            generator_label="Group_0 2",
            generator_level=0,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="trunk_1",
            parent="root",
            generator_label="Group_0 2",
            generator_level=0,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="branch_1",
            parent="root",
            generator_label="Group_0",
            generator_level=0,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="branch_1_main",
            parent="branch_1",
            generator_label="Group_1",
            generator_level=1,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="branch_2",
            parent="branch_1",
            generator_label="Group_1",
            generator_level=1,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="branch_2_main",
            parent="branch_2",
            generator_label="Group_2",
            generator_level=2,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="branch_3",
            parent="branch_2",
            generator_label="Group_2",
            generator_level=2,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="branch_4",
            parent="branch_3",
            generator_label="Group_2",
            generator_level=2,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
    )
    source_objects = (
        SourceObject(
            object_id="1",
            parent_id=None,
            name="Trunk",
            abs_translate=Vector3(0.0, 0.0, 0.0),
            rel_translate=Vector3(0.0, 0.0, 0.0),
            mesh=MeshData(
                name="Trunk",
                points=(Vector3(0.0, 0.0, 0.0),),
                face_vertex_counts=(),
                face_vertex_indices=(),
                skel_joint_indices=(0, 1),
                skel_joint_weights=(1.0, 1.0),
                skel_element_size=1,
            ),
        ),
        SourceObject(
            object_id="2",
            parent_id="1",
            name="Branches_1",
            abs_translate=Vector3(0.0, 0.0, 0.0),
            rel_translate=Vector3(0.0, 0.0, 0.0),
            mesh=MeshData(
                name="Branches_1",
                points=(Vector3(0.0, 0.0, 0.0),),
                face_vertex_counts=(),
                face_vertex_indices=(),
                skel_joint_indices=(2, 3),
                skel_joint_weights=(1.0, 1.0),
                skel_element_size=1,
            ),
        ),
        SourceObject(
            object_id="3",
            parent_id="2",
            name="Branches_2",
            abs_translate=Vector3(0.0, 0.0, 0.0),
            rel_translate=Vector3(0.0, 0.0, 0.0),
            mesh=MeshData(
                name="Branches_2",
                points=(Vector3(0.0, 0.0, 0.0),),
                face_vertex_counts=(),
                face_vertex_indices=(),
                skel_joint_indices=(4, 5),
                skel_joint_weights=(1.0, 1.0),
                skel_element_size=1,
            ),
        ),
        SourceObject(
            object_id="4",
            parent_id="3",
            name="Branches_3",
            abs_translate=Vector3(0.0, 0.0, 0.0),
            rel_translate=Vector3(0.0, 0.0, 0.0),
            mesh=MeshData(
                name="Branches_3",
                points=(Vector3(0.0, 0.0, 0.0),),
                face_vertex_counts=(),
                face_vertex_indices=(),
                skel_joint_indices=(6,),
                skel_joint_weights=(1.0,),
                skel_element_size=1,
            ),
        ),
        SourceObject(
            object_id="5",
            parent_id="4",
            name="Branches_4",
            abs_translate=Vector3(0.0, 0.0, 0.0),
            rel_translate=Vector3(0.0, 0.0, 0.0),
            mesh=MeshData(
                name="Branches_4",
                points=(Vector3(0.0, 0.0, 0.0),),
                face_vertex_counts=(),
                face_vertex_indices=(),
                skel_joint_indices=(7,),
                skel_joint_weights=(1.0,),
                skel_element_size=1,
            ),
        ),
    )

    dynamic_wind = build_dynamic_wind_data(skeleton, source_objects=source_objects)
    assignments = {assignment.joint_name: assignment.simulation_group_index for assignment in dynamic_wind.joint_assignments}

    assert len(dynamic_wind.simulation_groups) == 3
    assert dynamic_wind.simulation_groups[0].is_trunk_group is True
    assert [group.branch_order for group in dynamic_wind.simulation_groups] == [0, 1, 2]
    assert assignments["root"] == 0
    assert assignments["trunk_1"] == 0
    assert assignments["branch_1"] == 0
    assert assignments["branch_1_main"] == 1
    assert assignments["branch_2"] == 1
    assert assignments["branch_2_main"] == 2
    assert assignments["branch_3"] == 2
    assert assignments["branch_4"] == 2


def test_dynamic_wind_grouping_ignores_source_object_depth_hints() -> None:
    skeleton = (
        Joint(
            name="root",
            parent=None,
            generator_label="Group_0",
            generator_level=0,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="stem_a",
            parent="root",
            generator_label="Group_0",
            generator_level=0,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="stem_b",
            parent="root",
            generator_label="Group_0",
            generator_level=0,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="stem_a_tip",
            parent="stem_a",
            generator_label="Group_1",
            generator_level=1,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="stem_b_tip",
            parent="stem_b",
            generator_label="Group_1",
            generator_level=1,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="branch_a_1",
            parent="stem_a_tip",
            generator_label="Group_2",
            generator_level=2,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="branch_a_2",
            parent="stem_a_tip",
            generator_label="Group_2",
            generator_level=2,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
    )
    source_object = SourceObject(
        object_id="1",
        parent_id=None,
        name="Trunk",
        abs_translate=Vector3(0.0, 0.0, 0.0),
        rel_translate=Vector3(0.0, 0.0, 0.0),
        mesh=MeshData(
            name="Trunk",
            points=(Vector3(0.0, 0.0, 0.0),),
            face_vertex_counts=(),
            face_vertex_indices=(),
            skel_joint_indices=(5, 5, 6, 6),
            skel_joint_weights=(1.0, 1.0, 1.0, 1.0),
            skel_element_size=1,
        ),
    )

    without_hints = build_dynamic_wind_data(skeleton)
    with_hints = build_dynamic_wind_data(skeleton, source_objects=(source_object,))

    assert with_hints == without_hints
    assignments = {assignment.joint_name: assignment.simulation_group_index for assignment in with_hints.joint_assignments}
    assert assignments["root"] == 0
    assert assignments["stem_a"] == 0
    assert assignments["stem_b"] == 0
    assert assignments["stem_a_tip"] == 1
    assert assignments["stem_b_tip"] == 1
    assert assignments["branch_a_1"] == 2
    assert assignments["branch_a_2"] == 2


def test_dynamic_wind_json_generation_writes_groups_and_respects_slider_values(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(
        tmp_path,
        ("Group_0 2", "Group_0", "Group_1", "Group_1", "Group_2"),
    )
    output_path = tmp_path / "generator_levels_DynamicWind.json"
    result = generate_wind_json(
        str(input_path),
        str(output_path),
        group_settings=(
            DynamicWindSimulationGroup(
                group_index=0,
                branch_order=0,
                influence=1.8,
                shift_top=0.15,
                is_trunk_group=True,
                use_dual_influence=False,
            ),
            DynamicWindSimulationGroup(
                group_index=1,
                branch_order=1,
                influence=1.2,
                shift_top=0.05,
                use_dual_influence=False,
            ),
            DynamicWindSimulationGroup(
                group_index=2,
                branch_order=2,
                influence=1.05,
                shift_top=0.01,
                use_dual_influence=False,
            ),
        ),
        gust_attenuation=0.6,
        is_ground_cover=True,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert result.output_path == str(output_path)
    assert payload["Joints"]
    assert payload["SimulationGroups"]
    assert payload["SimulationGroups"][0]["bIsTrunkGroup"] is False
    assert payload["SimulationGroups"][0]["bUseDualInfluence"] is False
    assert payload["SimulationGroups"][0]["Influence"] == pytest.approx(1.8)
    assert payload["SimulationGroups"][0]["MinInfluence"] == pytest.approx(0.0)
    assert payload["SimulationGroups"][0]["MaxInfluence"] == pytest.approx(0.0)
    assert payload["SimulationGroups"][0]["ShiftTop"] == pytest.approx(0.0)
    assert payload["SimulationGroups"][1]["bUseDualInfluence"] is False
    assert payload["SimulationGroups"][1]["Influence"] == pytest.approx(1.2)
    assert payload["SimulationGroups"][2]["bUseDualInfluence"] is False
    assert payload["SimulationGroups"][2]["Influence"] == pytest.approx(1.05)
    assert payload["SimulationGroups"][2]["ShiftTop"] == pytest.approx(0.0)
    assert payload["bIsGroundCover"] is True
    assert all(group["bIsTrunkGroup"] is False for group in payload["SimulationGroups"])
    assert payload["GustAttenuation"] == pytest.approx(0.6)


def test_dynamic_wind_json_generation_serializes_dual_influence_groups(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(
        tmp_path,
        ("Group_0 2", "Group_0", "Group_1", "Group_1"),
    )
    output_path = tmp_path / "generator_levels_dual_DynamicWind.json"
    generate_wind_json(
        str(input_path),
        str(output_path),
        group_settings=(
            DynamicWindSimulationGroup(
                group_index=0,
                branch_order=0,
                influence=1.8,
                shift_top=0.15,
                is_trunk_group=True,
                use_dual_influence=True,
                min_influence=0.2,
                max_influence=0.9,
            ),
            DynamicWindSimulationGroup(
                group_index=1,
                branch_order=1,
                influence=1.2,
                shift_top=0.05,
                use_dual_influence=True,
                min_influence=0.15,
                max_influence=0.75,
            ),
        ),
        gust_attenuation=0.6,
        is_ground_cover=False,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["SimulationGroups"][0]["bUseDualInfluence"] is True
    assert payload["SimulationGroups"][0]["Influence"] == pytest.approx(0.0)
    assert payload["SimulationGroups"][0]["MinInfluence"] == pytest.approx(0.2)
    assert payload["SimulationGroups"][0]["MaxInfluence"] == pytest.approx(0.9)
    assert payload["SimulationGroups"][1]["bUseDualInfluence"] is True
    assert payload["SimulationGroups"][1]["Influence"] == pytest.approx(0.0)
    assert payload["SimulationGroups"][1]["MinInfluence"] == pytest.approx(0.15)
    assert payload["SimulationGroups"][1]["MaxInfluence"] == pytest.approx(0.75)


def test_inspect_wind_data_uses_generator_levels(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(
        tmp_path,
        ("Group_0 2", "Group_0", "Group_1", "Group_1", "Group_2"),
    )
    dynamic_wind = inspect_wind_data(str(input_path))

    assert len(dynamic_wind.simulation_groups) == 3
    assert dynamic_wind.simulation_groups[0].is_trunk_group is True
    assert [group.branch_order for group in dynamic_wind.simulation_groups] == [0, 1, 2]


def test_inspect_wind_data_clears_trunk_groups_when_ground_cover_is_enabled(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(
        tmp_path,
        ("Group_0 2", "Group_0", "Group_1", "Group_1", "Group_2"),
    )
    dynamic_wind = inspect_wind_data(str(input_path), is_ground_cover=True)

    assert dynamic_wind.is_ground_cover is True
    assert dynamic_wind.simulation_groups
    assert all(group.is_trunk_group is False for group in dynamic_wind.simulation_groups)


def test_inspect_wind_data_rejects_missing_generator_levels(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(tmp_path, (None, None))

    with pytest.raises(ValueError, match="missing_generator_level"):
        inspect_wind_data(str(input_path))


def test_generate_wind_json_rejects_malformed_generator_levels(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(tmp_path, ("Branches", "Branches"))

    with pytest.raises(ValueError, match="missing_generator_level"):
        generate_wind_json(str(input_path), str(tmp_path / "invalid_DynamicWind.json"))


def test_inspect_wind_data_accepts_legacy_speedtree_generator_labels(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(tmp_path, ("Trunk", "Trunk", "Branches_1", "Branches_2"))

    dynamic_wind = inspect_wind_data(str(input_path))

    assert [group.branch_order for group in dynamic_wind.simulation_groups] == [0, 1, 2]
    assert dynamic_wind.simulation_groups[0].is_trunk_group is True


def test_inspect_wind_data_infers_missing_upper_generator_levels_from_children(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(tmp_path, (None, None, None, "Branches_1", "Branches_2"))

    dynamic_wind = inspect_wind_data(str(input_path))

    assert [group.branch_order for group in dynamic_wind.simulation_groups] == [0, 1, 2]
    assignments = {assignment.joint_name: assignment.branch_order for assignment in dynamic_wind.joint_assignments}
    assert assignments["root"] == 0
    assert assignments["bone_001"] == 0
    assert assignments["bone_002"] == 0
    assert assignments["bone_003"] == 1
    assert assignments["bone_004"] == 2


def test_legacy_wind_samples_without_generator_labels_fail_strictly() -> None:
    with pytest.raises(ValueError, match="missing_generator_level"):
        inspect_wind_data(str(LEAFREFS_ON_BRANCH_LEVELS))


def test_base_tree_mesh_merges_trunk_and_branch_geometry_in_stage_space() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)

    assert model.base_mesh is not None
    primary_source_object = next(
        source_object
        for source_object in model.source_objects
        if source_object.mesh is not None and source_object.parent_id in {"0", None, "-1"}
    )
    assert primary_source_object.mesh is not None
    assert len(model.base_mesh.points) > len(primary_source_object.mesh.points)
    assert len(model.base_mesh.face_vertex_counts) > len(primary_source_object.mesh.face_vertex_counts)
    assert model.base_tree_parts[0].point_offset == 0
    assert model.base_tree_parts[1].point_offset > model.base_tree_parts[0].point_offset
    translated_point = model.base_mesh.points[model.base_tree_parts[1].point_offset]
    assert translated_point != primary_source_object.mesh.points[0]
    assert translated_point.y > primary_source_object.mesh.points[0].y


def test_base_tree_mesh_includes_all_mesh_bearing_objects_in_regular_hierarchy() -> None:
    trunk = SourceObject(
        object_id="1",
        parent_id=None,
        name="Trunk",
        abs_translate=Vector3(0.0, 0.0, 0.0),
        rel_translate=Vector3(0.0, 0.0, 0.0),
        mesh=MeshData(
            name="TrunkMesh",
            points=(Vector3(0.0, 0.0, 0.0), Vector3(1.0, 0.0, 0.0), Vector3(0.0, 1.0, 0.0)),
            face_vertex_counts=(3,),
            face_vertex_indices=(0, 1, 2),
            sections=(),
        ),
    )
    branch = SourceObject(
        object_id="2",
        parent_id="1",
        name="Branch",
        abs_translate=Vector3(0.0, 2.0, 0.0),
        rel_translate=Vector3(0.0, 2.0, 0.0),
        mesh=MeshData(
            name="BranchMesh",
            points=(Vector3(0.0, 0.0, 0.0), Vector3(0.0, 1.0, 0.0), Vector3(0.0, 0.0, 1.0)),
            face_vertex_counts=(3,),
            face_vertex_indices=(0, 1, 2),
            sections=(),
        ),
    )
    tubes = SourceObject(
        object_id="3",
        parent_id="2",
        name="Tubes_2",
        abs_translate=Vector3(0.0, 4.0, 0.0),
        rel_translate=Vector3(0.0, 2.0, 0.0),
        mesh=MeshData(
            name="TubesMesh",
            points=(Vector3(0.0, 0.0, 0.0), Vector3(1.0, 1.0, 0.0), Vector3(0.0, 1.0, 1.0)),
            face_vertex_counts=(3,),
            face_vertex_indices=(0, 1, 2),
            sections=(),
        ),
    )

    base_mesh, base_parts = _build_base_mesh((trunk, branch, tubes))

    assert base_mesh is not None
    assert [part.name for part in base_parts] == ["Trunk", "Branch", "Tubes_2"]
    assert len(base_mesh.points) == 9
    assert len(base_mesh.face_vertex_counts) == 3


def test_mesh_uvs_follow_vertex_indices_for_face_varying_authoring() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)

    assert model.base_mesh is not None
    assert len(model.base_mesh.uv_coords) == len(model.base_mesh.face_vertex_indices)
    first_uv = model.base_mesh.uv_coords[0]
    assert (first_uv.x, first_uv.y) == pytest.approx((-0.591758, 0.5572639))

    prototype = next(prototype for prototype in model.prototypes if prototype.source_key == "Mesh_1")
    assert prototype.mesh is not None
    assert len(prototype.mesh.uv_coords) == len(prototype.mesh.face_vertex_indices)
    prototype_first_uv = prototype.mesh.uv_coords[0]
    assert prototype_first_uv.x >= 0.8
    assert prototype_first_uv.y >= 0.8


def test_face_varying_uvs_fall_back_to_point_indices_when_vertex_indices_are_missing() -> None:
    from xml_to_usda.normalizer import _extract_face_varying_uvs

    vertices_node = ET.fromstring(
        """
        <Vertices>
            <TexcoordU>0 1 0</TexcoordU>
            <TexcoordV>0 0 1</TexcoordV>
        </Vertices>
        """
    )
    messages: list[str] = []

    uv_coords = _extract_face_varying_uvs(
        vertices_node=vertices_node,
        vertex_indices=[],
        face_indices=[0, 1, 2, 0, 2, 1],
        context="SyntheticMesh.vertices",
        messages=messages,
        allow_point_index_fallback=True,
    )

    assert messages == []
    assert len(uv_coords) == 6
    assert [(uv.x, uv.y) for uv in uv_coords] == pytest.approx(
        [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (0.0, 0.0), (0.0, 1.0), (1.0, 0.0)]
    )


def test_vertex_color_black_faces_become_leaves_sections_for_prototypes() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    model = normalize_to_canonical(document, inspect_xml(document))
    prototype = next(prototype for prototype in model.prototypes if prototype.source_key == "Mesh_1")
    assert prototype.mesh is not None

    synthetic_mesh = replace(
        prototype.mesh,
        face_vertex_counts=(3, 3),
        face_vertex_indices=(0, 1, 2, 3, 4, 5),
        vertex_colors=(
            Color4(0.0, 0.0, 0.0),
            Color4(0.0, 0.0, 0.0),
            Color4(0.0, 0.0, 0.0),
            Color4(1.0, 1.0, 1.0),
            Color4(1.0, 1.0, 1.0),
            Color4(1.0, 1.0, 1.0),
        ),
        sections=(MeshSection(material_id=1, face_indices=(0, 1)),),
    )

    sections = _vertex_color_material_sections(synthetic_mesh)

    assert sections == (
        MeshSection(material_id=1, face_indices=(1,)),
        MeshSection(material_id=2, face_indices=(0,)),
    )


def test_vertex_colors_override_authored_prototype_sections_when_present() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    model = normalize_to_canonical(document, inspect_xml(document))
    prototype = next(prototype for prototype in model.prototypes if prototype.source_key == "Mesh_1")
    assert prototype.mesh is not None

    synthetic_mesh = replace(
        prototype.mesh,
        face_vertex_counts=(3, 3),
        face_vertex_indices=(0, 1, 2, 3, 4, 5),
        vertex_colors=(
            Color4(0.0, 0.0, 0.0),
            Color4(0.0, 0.0, 0.0),
            Color4(0.0, 0.0, 0.0),
            Color4(1.0, 1.0, 1.0),
            Color4(1.0, 1.0, 1.0),
            Color4(1.0, 1.0, 1.0),
        ),
        sections=(
            MeshSection(material_id=1, face_indices=(0,)),
            MeshSection(material_id=2, face_indices=(1,)),
        ),
    )

    from xml_to_usda.normalizer import _resolve_prototype_material_sections

    resolved = _resolve_prototype_material_sections(synthetic_mesh, "Mesh_1", {2: 1}, {1, 2}, [])

    assert resolved.sections == (
        MeshSection(material_id=1, face_indices=(1,)),
        MeshSection(material_id=2, face_indices=(0,)),
    )


def test_source_role_policy_does_not_require_fixed_material_ids() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    broken_model = replace(
        model,
        materials=(MaterialSpec(source_id=1, name="Default_Mat", source_material_ids=(1,)),),
        metadata=replace(model.metadata, material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES),
    )

    diagnostics = validate_model(broken_model)

    assert not any(issue.code == "missing_required_material_role" for issue in diagnostics)


def test_single_material_policy_succeeds_on_shifted_source_material_ids(tmp_path: Path) -> None:
    shifted_sample = _write_shifted_material_sample(tmp_path, {1: 3, 2: 4})
    runtime_paths = _test_runtime_paths(tmp_path)

    result = convert_file(
        str(shifted_sample),
        str(tmp_path / "single_material.usda"),
        material_policy=MaterialPolicy.SINGLE_MATERIAL,
        single_material_path="/Game/Assembly/SimpleTree/Leaves1.Leaves1",
        runtime_paths=runtime_paths,
    )
    _, model, diagnostics = load_canonical_model(
        str(shifted_sample),
        material_policy=MaterialPolicy.SINGLE_MATERIAL,
        single_material_path="/Game/Assembly/SimpleTree/Leaves1.Leaves1",
    )

    assert result.usda_document is not None
    assert len(model.materials) == 1
    assert model.materials[0].source_id == 1
    assert model.materials[0].ue_asset_path == "/Game/Assembly/SimpleTree/Leaves1.Leaves1"
    assert model.base_mesh is not None
    assert {section.material_id for section in model.base_mesh.sections} == {1}
    assert all(
        prototype.mesh is None or {section.material_id for section in prototype.mesh.sections} == {1}
        for prototype in model.prototypes
    )
    assert not any(
        issue.severity == "error" and issue.code in {"missing_required_material_role", "missing_material_definition"}
        for issue in diagnostics
    )
    assert 'uniform asset info:unreal:sourceAsset = @/Game/Assembly/SimpleTree/Leaves1.Leaves1@' in result.usda_document.text


def test_source_role_policy_remaps_shifted_source_material_ids_to_role_materials(tmp_path: Path) -> None:
    shifted_sample = _write_shifted_material_sample(tmp_path, {1: 5, 2: 6})
    runtime_paths = _test_runtime_paths(tmp_path)

    result = convert_file(str(shifted_sample), str(tmp_path / "legacy_shifted.usda"), runtime_paths=runtime_paths)
    _, model, diagnostics = load_canonical_model(str(shifted_sample))

    assert result.usda_document is not None
    assert {material.source_id for material in model.materials} == {1, 2}
    assert {material.source_material_ids for material in model.materials} == {(5,), (6,)}
    assert model.base_mesh is not None
    assert {section.material_id for section in model.base_mesh.sections} == {1}
    assert all(
        prototype.mesh is None or {section.material_id for section in prototype.mesh.sections} <= {1, 2}
        for prototype in model.prototypes
    )
    assert not any(
        issue.severity == "error" and issue.code == "missing_material_definition"
        for issue in diagnostics
    )


def test_source_role_policy_succeeds_with_fbx_single_material_on_shifted_source_material_ids(tmp_path: Path) -> None:
    shifted_sample = _write_shifted_material_sample(tmp_path, {1: 5, 2: 6})
    payload_path = _write_fbx_json_payload(tmp_path, include_vertex_colors=False)

    _, model, diagnostics = load_canonical_model(
        str(shifted_sample),
        material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_material_mode=FbxMaterialMode.SINGLE_MATERIAL,
                fbx_path=str(payload_path),
            ),
        ),
    )

    prototype = next(prototype for prototype in model.prototypes if prototype.source_key == "Mesh_1")

    assert {material.source_id for material in model.materials} == {1, 2}
    assert {material.source_material_ids for material in model.materials} == {(5,), (6,)}
    assert prototype.geometry_payload is not None
    assert {section.material_id for section in prototype.geometry_payload.sections} == {1}
    assert not any(
        issue.severity == "error" and issue.code == "missing_material_definition"
        for issue in diagnostics
    )


def test_vertex_color_split_policy_maps_white_and_nonwhite_for_base_and_prototypes() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    synthetic_mesh = MeshData(
        name="SyntheticMaterialSplit",
        points=(
            Vector3(0.0, 0.0, 0.0),
            Vector3(1.0, 0.0, 0.0),
            Vector3(0.0, 1.0, 0.0),
            Vector3(1.0, 1.0, 0.0),
            Vector3(2.0, 1.0, 0.0),
            Vector3(1.0, 2.0, 0.0),
        ),
        face_vertex_counts=(3, 3),
        face_vertex_indices=(0, 1, 2, 3, 4, 5),
        vertex_colors=(
            Color4(1.0, 1.0, 1.0),
            Color4(1.0, 1.0, 1.0),
            Color4(1.0, 1.0, 1.0),
            Color4(0.5, 0.5, 0.5),
            Color4(0.5, 0.5, 0.5),
            Color4(0.5, 0.5, 0.5),
        ),
        sections=(MeshSection(material_id=9, face_indices=(0, 1)),),
        skel_joint_indices=(0, 0, 0, 0, 0, 0),
        skel_joint_weights=(1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
        skel_element_size=1,
    )
    prototype_mesh = replace(
        synthetic_mesh,
        name="SyntheticPrototypeSplit",
        skel_joint_indices=(),
        skel_joint_weights=(),
        skel_element_size=0,
    )
    first_prototype = model.prototypes[0]
    remapped_model = _apply_material_policy(
        replace(
            model,
            base_mesh=synthetic_mesh,
            prototypes=(
                replace(first_prototype, mesh=prototype_mesh),
                *model.prototypes[1:],
            ),
        ),
        material_policy=MaterialPolicy.VERTEX_COLOR_SPLIT,
        bark_material_path=None,
        leaves_material_path=None,
        single_material_path=None,
    )

    assert remapped_model.base_mesh is not None
    assert remapped_model.base_mesh.sections == (
        MeshSection(material_id=1, face_indices=(0,)),
        MeshSection(material_id=2, face_indices=(1,)),
    )
    assert remapped_model.prototypes[0].mesh is not None
    assert remapped_model.prototypes[0].mesh.sections == (
        MeshSection(material_id=1, face_indices=(0,)),
        MeshSection(material_id=2, face_indices=(1,)),
    )


def test_vertex_color_split_policy_warns_and_falls_back_to_primary_without_vertex_colors() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    base_mesh_without_colors = replace(model.base_mesh, vertex_colors=()) if model.base_mesh is not None else None
    first_prototype = model.prototypes[0]
    prototype_mesh_without_colors = replace(first_prototype.mesh, vertex_colors=()) if first_prototype.mesh is not None else None
    remapped_model = _apply_material_policy(
        replace(
            model,
            base_mesh=base_mesh_without_colors,
            prototypes=(
                replace(first_prototype, mesh=prototype_mesh_without_colors),
                *model.prototypes[1:],
            ),
        ),
        material_policy=MaterialPolicy.VERTEX_COLOR_SPLIT,
        bark_material_path=None,
        leaves_material_path=None,
        single_material_path=None,
    )
    diagnostics = validate_model(remapped_model)

    assert remapped_model.base_mesh is not None
    assert {section.material_id for section in remapped_model.base_mesh.sections} == {1}
    assert remapped_model.prototypes[0].mesh is not None
    assert {section.material_id for section in remapped_model.prototypes[0].mesh.sections} == {1}
    assert any(issue.code == "material_policy_warning" and issue.severity == "warning" for issue in diagnostics)


def test_speedtree_xml_without_units_uses_meter_source_scale() -> None:
    root = ET.fromstring(
        """
        <SpeedTreeRaw>
            <Objects>
                <Object>
                    <LeafReferences>
                        <Scale>100 100 100</Scale>
                    </LeafReferences>
                </Object>
            </Objects>
        </SpeedTreeRaw>
        """
    )

    transform = build_source_transform(root, units_hint=None, up_axis_hint=None)

    assert transform.source_units == "m"
    assert transform.linear_scale == pytest.approx(1.0)


def test_speedtree_xml_ignores_non_meter_units_hint_and_uses_meter_source_scale() -> None:
    root = ET.fromstring(
        """
        <SpeedTreeRaw units="cm">
            <Objects>
                <Object>
                    <LeafReferences>
                        <Scale>0.72 0.81 1.05</Scale>
                    </LeafReferences>
                </Object>
            </Objects>
        </SpeedTreeRaw>
        """
    )

    transform = build_source_transform(root, units_hint="cm", up_axis_hint=None)

    assert transform.source_units == "m"
    assert transform.linear_scale == pytest.approx(1.0)


def test_leaf_reference_orientation_preserves_rotation_sense_after_axis_remap() -> None:
    root = ET.fromstring(
        """
        <SpeedTreeRaw>
            <Objects>
                <Object Name="Leaf">
                    <LeafReferences Material="2" Count="1">
                        <X>0</X>
                        <Y>0</Y>
                        <Z>0</Z>
                        <Scale>100</Scale>
                        <RotAxisX>0</RotAxisX>
                        <RotAxisY>0</RotAxisY>
                        <RotAxisZ>1</RotAxisZ>
                        <RotAngle>90</RotAngle>
                        <MeshID>1</MeshID>
                        <MeshLOD>0</MeshLOD>
                        <BoneID>0</BoneID>
                    </LeafReferences>
                </Object>
            </Objects>
        </SpeedTreeRaw>
        """
    )

    transform = build_source_transform(root, units_hint=None, up_axis_hint=None)
    parts = _extract_assembly_parts_from_leaf_references(root, [], transform, {2})

    assert len(parts) == 1
    orientation = parts[0].orientation
    assert orientation.real == pytest.approx(0.70710678)
    assert orientation.i == pytest.approx(0.0)
    assert orientation.j == pytest.approx(0.70710678)
    assert orientation.k == pytest.approx(0.0)


def test_normalize_to_canonical_keeps_leaf_reference_scale_as_instance_multiplier() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    assert model.mesh_library
    assert model.assembly_parts

    mesh_1_parts = [part for part in model.assembly_parts if part.prototype_key == "Mesh_1"]
    mesh_2_parts = [part for part in model.assembly_parts if part.prototype_key == "Mesh_2"]

    assert mesh_1_parts
    assert mesh_2_parts
    assert all(part.scale == Vector3(1.0, 1.0, 1.0) for part in mesh_1_parts)
    assert all(part.scale == Vector3(1.0, 1.0, 1.0) for part in mesh_2_parts)


def test_locale_decimal_parsing_accepts_comma_floats_for_lists_and_bounds() -> None:
    source_transform = build_source_transform(ET.fromstring("<SpeedTreeRaw><Meshes><Mesh Orient='xyzZ' /></Meshes></SpeedTreeRaw>"), None, None)
    obj = ET.fromstring(
        "<Object BoundsMinX='-0,490294' BoundsMinY='-0,125' BoundsMinZ='0,25' "
        "BoundsMaxX='1,5' BoundsMaxY='2,75' BoundsMaxZ='3,125' />"
    )

    assert _read_float_list("0,3048 -0,490294 1,25") == pytest.approx([0.3048, -0.490294, 1.25])
    assert _read_positive_float("15,8194") == pytest.approx(15.8194)

    bounds = _extract_bounds(obj, source_transform)

    assert bounds is not None
    assert bounds.minimum.x == pytest.approx(-0.490294)
    assert bounds.maximum.y == pytest.approx(3.125)
    assert bounds.maximum.z == pytest.approx(0.125)


def test_load_canonical_model_bakes_shared_prototype_scale_into_inline_meshes() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    raw_model = normalize_to_canonical(document, inspect_xml(document))
    _, loaded_model, _ = load_canonical_model(str(SIMPLE_TREE_01))

    raw_prototype = next(prototype for prototype in raw_model.prototypes if prototype.source_key == "Mesh_1")
    loaded_prototype = next(prototype for prototype in loaded_model.prototypes if prototype.source_key == "Mesh_1")

    assert raw_prototype.mesh is not None
    assert loaded_prototype.mesh is not None
    assert all(part.scale == Vector3(1.0, 1.0, 1.0) for part in loaded_model.assembly_parts if part.prototype_key == "Mesh_1")
    assert loaded_prototype.mesh.points == raw_prototype.mesh.points


def test_usda_output_contains_ue_first_structure() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)
    usda = render_usda(model, diagnostics)

    assert 'metersPerUnit = 1' in usda.text
    assert 'upAxis = "Y"' in usda.text
    assert 'apiSchemas = ["NaniteAssemblyRootAPI"]' in usda.text
    assert 'uniform token unreal:naniteAssembly:meshType = "skeletalMesh"' in usda.text
    assert 'rel unreal:naniteAssembly:skeleton = </Tree/BaseTreeSkelRoot/MainSkeleton>' in usda.text
    assert 'def Scope "Materials"' in usda.text
    assert 'def Material "Material_1_1"' in usda.text
    assert 'def Material "Material_2_2"' in usda.text
    assert 'token outputs:surface.connect = </Tree/Materials/Material_1_1/Material_1_1_shader.outputs:surface>' in usda.text
    assert 'token outputs:surface.connect = </Tree/Materials/Material_2_2/Material_2_2_shader.outputs:surface>' in usda.text
    assert 'uniform token info:id = "UsdPreviewSurface"' in usda.text
    assert 'color3f inputs:diffuseColor = (' in usda.text
    assert 'def SkelRoot "BaseTreeSkelRoot"' in usda.text
    assert 'def SkelAnimation "BaseTreeAnimation"' in usda.text
    assert 'def Skeleton "MainSkeleton"' in usda.text
    assert 'def Mesh "BaseTreeMesh"' in usda.text
    assert 'append rel skel:animationSource = </Tree/BaseTreeSkelRoot/BaseTreeAnimation>' in usda.text
    assert 'prepend apiSchemas = ["SkelBindingAPI"]' in usda.text
    assert 'uniform token purpose = "guide"' in usda.text
    assert 'uniform token visibility = "invisible"' in usda.text
    assert 'uniform token[] skel:joints = [' in usda.text
    assert 'uniform matrix4d primvars:skel:geomBindTransform = ' in usda.text
    assert 'uniform int[] primvars:skel:jointIndices = [' in usda.text
    assert 'uniform float[] primvars:skel:jointWeights = [' in usda.text
    assert 'uniform token primvars:skel:skinningMethod = "classicLinear"' in usda.text
    assert 'uniform matrix4d[] bindTransforms = [' in usda.text
    assert 'uniform matrix4d[] restTransforms = [' in usda.text
    assert 'float3[] restTransforms:translations = [' not in usda.text
    assert 'rel material:binding = </Tree/Materials/Material_1_1>' in usda.text
    assert 'uniform token orientation = "rightHanded"' in usda.text
    assert 'interpolation = "vertex"' in usda.text
    assert 'texCoord2f[] primvars:st = [' in usda.text
    assert 'interpolation = "faceVarying"' in usda.text
    assert 'primvars:boneCapture_pCaptPath' in usda.text
    assert 'primvars:ueJointNames' in usda.text
    assert 'primvars:localtransform' in usda.text
    assert 'def PointInstancer "AssemblyPartsInstancer"' in usda.text
    assert 'apiSchemas = ["NaniteAssemblySkelBindingAPI"]' in usda.text
    assert 'token[] primvars:unreal:naniteAssembly:bindJoints = [' in usda.text
    assert 'int[] primvars:unreal:naniteAssembly:bindJoints:indices = None' in usda.text
    assert 'float[] primvars:unreal:naniteAssembly:bindJointWeights = [' in usda.text
    assert 'int[] primvars:unreal:naniteAssembly:bindJointWeights:indices = None' in usda.text
    assert 'elementSize = 2' in usda.text
    assert 'quath[] orientations = [' in usda.text
    assert 'def Scope "Prototypes"' in usda.text
    assert 'def Xform "Twig_01"' in usda.text
    assert 'def Xform "Twig_02"' in usda.text
    assert 'def SkelRoot "PartSkelRoot"' in usda.text
    assert 'def Mesh "Twig_01"' in usda.text
    assert 'def Mesh "Twig_02"' in usda.text
    assert 'def Skeleton "PartSkeleton"' in usda.text
    bind_joints_payload = _slice_between(
        usda.text,
        'token[] primvars:unreal:naniteAssembly:bindJoints = [',
        'int[] primvars:unreal:naniteAssembly:bindJoints:indices = None',
    )
    assert '"Tree_point_' not in bind_joints_payload


def test_material_bindings_stay_on_mesh_prims_only() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)
    usda = render_usda(model, diagnostics)

    root_slice = _slice_between(
        usda.text,
        'def Xform "Tree"',
        'def SkelRoot "BaseTreeSkelRoot"',
    )
    instancer_slice = _slice_between(
        usda.text,
        'def PointInstancer "AssemblyPartsInstancer"',
        'def Scope "Prototypes"',
    )

    assert 'material:binding' not in root_slice
    assert 'material:binding' not in instancer_slice


def test_inline_prototypes_are_authored_under_instancer_scope() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)
    usda = render_usda(model, diagnostics)

    assert 'def Xform "PrototypeLibrary"' not in usda.text
    assert 'append references = </Tree/PrototypeLibrary/Mesh_1>' not in usda.text
    assert 'append references = </Tree/PrototypeLibrary/Mesh_2>' not in usda.text
    assert 'rel prototypes = [</Tree/AssemblyPartsInstancer/Prototypes/Twig_01>, </Tree/AssemblyPartsInstancer/Prototypes/Twig_02>]' in usda.text
    assert usda.text.index('def Scope "Prototypes"') < usda.text.index('def Xform "Twig_01"')
    assert usda.text.index('def Xform "Twig_01"') < usda.text.index('def SkelRoot "PartSkelRoot"')


def test_ue_schema_contract_matches_current_writer_contract() -> None:
    contract = DEFAULT_UE_SCHEMA_CONTRACT

    assert contract.stage_meters_per_unit == 1.0
    assert contract.stage_up_axis == "Y"
    assert contract.root_api == "NaniteAssemblyRootAPI"
    assert contract.external_ref_api == "NaniteAssemblyExternalRefAPI"
    assert contract.binding_api == "NaniteAssemblySkelBindingAPI"
    assert contract.mesh_type_attr == "unreal:naniteAssembly:meshType"
    assert contract.root_kind == "component"
    assert contract.base_skel_root_name == "BaseTreeSkelRoot"
    assert contract.base_mesh_name == "BaseTreeMesh"
    assert contract.base_animation_name == "BaseTreeAnimation"
    assert contract.skeleton_name == "MainSkeleton"
    assert contract.assembly_parts_instancer_name == "AssemblyPartsInstancer"
    assert contract.skeleton_relationship_attr == "rel unreal:naniteAssembly:skeleton = </Tree/BaseTreeSkelRoot/MainSkeleton>"
    assert contract.bind_joints_attr == "token[] primvars:unreal:naniteAssembly:bindJoints"
    assert contract.bind_weights_attr == "float[] primvars:unreal:naniteAssembly:bindJointWeights"
    assert contract.skinning_method_attr == "uniform token primvars:skel:skinningMethod"
    assert contract.skinning_method_value == "classicLinear"
    assert contract.point_instancer_joint_element_size == 2
    assert contract.mesh_orientation == "rightHanded"
    assert contract.root_api_allowed_prims == ("Xform",)
    assert contract.external_ref_api_allowed_prims == ("Xform",)
    assert contract.binding_api_allowed_prims == ("Xform", "Mesh", "SkelRoot", "PointInstancer")


def test_point_instancer_binding_attrs_use_joint_tokens_from_main_skeleton() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)
    usda = render_usda(model, diagnostics)

    assert 'token[] primvars:unreal:naniteAssembly:bindJoints = [' in usda.text
    assert 'float[] primvars:unreal:naniteAssembly:bindJointWeights = [' in usda.text
    assert 'elementSize = 2' in usda.text
    bind_joints_payload = _slice_between(
        usda.text,
        'token[] primvars:unreal:naniteAssembly:bindJoints = [',
        'int[] primvars:unreal:naniteAssembly:bindJoints:indices = None',
    )
    bind_weights_payload = _slice_between(
        usda.text,
        'float[] primvars:unreal:naniteAssembly:bindJointWeights = [',
        'int[] primvars:unreal:naniteAssembly:bindJointWeights:indices = None',
    )
    assert '"bone_017"' in bind_joints_payload
    assert '"bone_104"' in bind_joints_payload
    assert '"Tree_point_17"' not in bind_joints_payload
    assert '0]' in bind_weights_payload or ', 0,' in bind_weights_payload


def test_assembly_part_orientations_remain_non_uniform_and_deterministic() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model_a = normalize_to_canonical(document, report)
    model_b = normalize_to_canonical(document, report)

    observed_a = tuple(part.orientation.to_usda() for part in model_a.assembly_parts[:3])
    observed_b = tuple(part.orientation.to_usda() for part in model_b.assembly_parts[:3])
    assert observed_a == observed_b
    assert len(set(part.orientation.to_usda() for part in model_a.assembly_parts)) > 3


def test_assembly_part_prototypes_preserve_authored_original_scale_and_orientation() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)
    usda = render_usda(model, diagnostics)

    mesh_entries = {entry.mesh_id: entry for entry in model.mesh_library}
    assert mesh_entries[1].original_scale is not None
    assert mesh_entries[2].original_scale is not None
    assert all(
        part.scale.x == pytest.approx(part.scale.y) and part.scale.y == pytest.approx(part.scale.z)
        for part in model.assembly_parts
    )
    scale_by_mesh_id = {
        entry.mesh_id: entry.original_scale for entry in model.mesh_library if entry.original_scale is not None
    }
    for part in model.assembly_parts:
        assert part.scale.x == pytest.approx(1.0)
        assert part.scale.y == pytest.approx(1.0)
        assert part.scale.z == pytest.approx(1.0)

    prototype_mesh = next(prototype.mesh for prototype in model.prototypes if prototype.source_key == "Mesh_1")
    assert prototype_mesh is not None
    raw_library_mesh = mesh_entries[1].mesh
    assert prototype_mesh.points[1].x == pytest.approx(raw_library_mesh.points[1].x * scale_by_mesh_id[1])
    assert prototype_mesh.points[1].y == pytest.approx(raw_library_mesh.points[1].y * scale_by_mesh_id[1])
    assert prototype_mesh.points[1].z == pytest.approx(raw_library_mesh.points[1].z * scale_by_mesh_id[1])
    max_extent = max(
        max(point.x for point in prototype_mesh.points) - min(point.x for point in prototype_mesh.points),
        max(point.y for point in prototype_mesh.points) - min(point.y for point in prototype_mesh.points),
        max(point.z for point in prototype_mesh.points) - min(point.z for point in prototype_mesh.points),
    )
    assert max_extent > 0.9

    instancer_scales_payload = _slice_between(
        usda.text,
        'float3[] scales = [',
        'string[] primvars:name = [',
    )
    assert instancer_scales_payload.strip()
    assert "1.02466" not in instancer_scales_payload
    assert "0.975898" not in instancer_scales_payload
    assert "(1, 1, 1)" in instancer_scales_payload


def test_missing_skeleton_is_error() -> None:
    document = read_source_xml(DATA_DIR / "missing_skeleton.xml")
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)

    assert any(issue.code == "missing_skeleton" and issue.severity == "error" for issue in diagnostics)
    with pytest.raises(ValueError, match="missing_skeleton"):
        render_usda(model, diagnostics)


def test_missing_leaf_refs_is_warning() -> None:
    document = read_source_xml(DATA_DIR / "missing_leaf_refs.xml")
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)

    assert any(issue.code == "missing_leaf_references" and issue.severity == "warning" for issue in diagnostics)


def test_non_default_metadata_becomes_warning() -> None:
    document = read_source_xml(DATA_DIR / "non_default_metadata.xml")
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)

    assert not any("units hint" in issue.message for issue in diagnostics)
    assert not any("up-axis hint" in issue.message for issue in diagnostics)


def test_generated_usda_tracks_reference_contract_without_houdini_only_fields() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)
    usda = render_usda(model, diagnostics)

    assert 'kind = "component"' in usda.text
    assert 'uniform token primvars:skel:skinningMethod = "classicLinear"' in usda.text
    assert 'uniform matrix4d[] restTransforms = [' in usda.text
    assert 'float3[] translations = [' in usda.text
    assert 'int[] primvars:unreal:naniteAssembly:bindJoints:indices = None' in usda.text
    assert 'int[] primvars:unreal:naniteAssembly:bindJointWeights:indices = None' in usda.text
    assert 'float primvars:pCaptFrame' not in usda.text
    assert 'string primvars:pCaptSkelRoot' not in usda.text
    assert 'NaniteAssemblyExternalRefAPI' not in usda.text
    assert 'def SkelRoot "PartSkelRoot"' in usda.text
    assert 'def Mesh "Twig_01"' in usda.text
    assert 'def Skeleton "PartSkeleton"' in usda.text


def test_assembly_part_prototypes_are_authored_as_single_joint_skeletal_meshes() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)
    usda = render_usda(model, diagnostics)

    assert 'append rel skel:skeleton = </Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/PartSkeleton>' in usda.text
    assert 'append rel skel:animationSource = </Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/PartAnimation>' in usda.text
    assert 'uniform token[] joints = ["Twig_01"]' in usda.text
    assert 'uniform token[] jointNames = ["Twig_01"]' in usda.text
    assert 'uniform matrix4d[] bindTransforms = [( (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1) )]' in usda.text
    assert 'uniform matrix4d[] restTransforms = [( (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1) )]' in usda.text
    assert 'elementSize = 1' in usda.text
    assert 'uniform token primvars:skel:skinningMethod = "classicLinear"' in usda.text


def test_referenced_prototype_strategy_is_blocked_for_skeletal_assembly_part_export() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    broken_model = replace(model, prototype_strategy=model.prototype_strategy.REFERENCED_SCOPE)
    diagnostics = validate_model(broken_model)

    assert any(issue.code == "unsupported_prototype_strategy" and issue.severity == "error" for issue in diagnostics)
    with pytest.raises(ValueError, match="unsupported_prototype_strategy"):
        render_usda(broken_model, diagnostics)


def test_leaf_references_on_trunk_normalize_without_breaking_part_binding() -> None:
    document = read_source_xml(LEAFREFS_ON_TRUNK)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)

    assert model.base_mesh is not None
    assert model.base_tree_parts[0].point_offset == 0
    assert len(model.assembly_parts) == 1
    assert model.assembly_parts[0].source_object_id == "1"
    assert model.assembly_parts[0].bind_joint == "bone_001"
    assert not any(issue.severity == "error" for issue in diagnostics)


def test_leaf_references_on_multiple_branch_levels_preserve_deeper_hierarchy_and_sources() -> None:
    report = inspect_source(LEAFREFS_ON_BRANCH_LEVELS)
    document = read_source_xml(LEAFREFS_ON_BRANCH_LEVELS)
    model = normalize_to_canonical(document, inspect_xml(document))
    diagnostics = validate_model(model)

    assert report.hierarchy_depth == 3
    assert report.leaf_source_object_distribution
    assert all(source_id.isdigit() for source_id in report.leaf_source_object_distribution)
    assert report.leaf_mesh_distribution == {"1": 2, "2": 1}
    assert len(model.base_tree_parts) == 4
    assert [part.source_object_id for part in model.assembly_parts] == ["1", "3", "4"]
    assert [part.bind_joint for part in model.assembly_parts] == ["root", "bone_002", "bone_003"]
    assert not any(issue.severity == "error" for issue in diagnostics)


def test_invalid_leaf_bone_is_reported_as_binding_error() -> None:
    document = read_source_xml(INVALID_LEAF_BONE)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)

    assert any(issue.code == "invalid_binding_joint" and issue.severity == "error" for issue in diagnostics)


def test_existing_part_mesh_override_authors_external_refs_in_mixed_mode(tmp_path: Path) -> None:
    result = convert_file(
        str(SIMPLE_TREE_01),
        str(tmp_path / "external_parts.usda"),
        use_existing_part_meshes=True,
        part_mesh_asset_paths=(("Mesh_1", "/Game/TreeParts/SK_Twig01.SK_Twig01"),),
    )
    _, model, _diagnostics = load_canonical_model(
        str(SIMPLE_TREE_01),
        use_existing_part_meshes=True,
        part_mesh_asset_paths=(("Mesh_1", "/Game/TreeParts/SK_Twig01.SK_Twig01"),),
    )

    assert result.usda_document is not None
    prototype = next(prototype for prototype in model.prototypes if prototype.source_key == "Mesh_1")
    assert prototype.resolution_mode == PrototypeResolutionMode.EXTERNAL_ASSET
    assert prototype.mesh is None
    assert 'prepend apiSchemas = ["NaniteAssemblyExternalRefAPI"]' in result.usda_document.text
    assert 'uniform token unreal:naniteAssembly:meshAssetPath = "/Game/TreeParts/SK_Twig01.SK_Twig01"' in result.usda_document.text
    assert 'def Xform "Twig_01" (' in result.usda_document.text
    assert 'append rel skel:skeleton = </Tree/AssemblyPartsInstancer/Prototypes/Twig_02/PartSkelRoot/PartSkeleton>' in result.usda_document.text


def test_existing_part_mesh_override_accepts_xml_mesh_names_in_mixed_mode(tmp_path: Path) -> None:
    result = convert_file(
        str(SIMPLE_TREE_01),
        str(tmp_path / "external_parts_by_name.usda"),
        use_existing_part_meshes=True,
        part_mesh_asset_paths=(("Twig_01", "/Game/TreeParts/SK_Twig01.SK_Twig01"),),
    )
    _, model, _diagnostics = load_canonical_model(
        str(SIMPLE_TREE_01),
        use_existing_part_meshes=True,
        part_mesh_asset_paths=(("Twig_01", "/Game/TreeParts/SK_Twig01.SK_Twig01"),),
    )

    assert result.usda_document is not None
    prototype = next(prototype for prototype in model.prototypes if prototype.source_key == "Mesh_1")
    assert prototype.resolution_mode == PrototypeResolutionMode.EXTERNAL_ASSET
    assert prototype.mesh is None
    assert 'prepend apiSchemas = ["NaniteAssemblyExternalRefAPI"]' in result.usda_document.text
    assert 'uniform token unreal:naniteAssembly:meshAssetPath = "/Game/TreeParts/SK_Twig01.SK_Twig01"' in result.usda_document.text


def test_fbx_part_source_config_replaces_inline_prototype_with_geometry_payload(tmp_path: Path) -> None:
    payload_path = _write_fbx_json_payload(tmp_path, file_name="SM_BigBranch_01_HIGH.json")
    _, model, diagnostics = load_canonical_model(
        str(SIMPLE_TREE_01),
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path=str(payload_path),
            ),
        ),
    )

    prototype = next(prototype for prototype in model.prototypes if prototype.source_key == "Mesh_1")

    assert not any(issue.severity == "error" for issue in diagnostics)
    assert prototype.source_mode == PrototypeSourceMode.FBX_FILE
    assert prototype.fbx_material_mode == FbxMaterialMode.AUTO
    assert prototype.mesh is None
    assert prototype.geometry_payload is not None
    assert prototype.fbx_source_path == str(payload_path)
    assert prototype.source_name == "SM_BigBranch_01_HIGH"
    assert prototype.identity.prim_name == "SM_BigBranch_01_HIGH"
    assert {section.material_id: list(section.face_indices) for section in prototype.geometry_payload.sections} == {
        1: [1],
        2: [0],
    }


def test_frozen_runtime_uses_sequential_fbx_import_for_multiple_prototypes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import xml_to_usda.prototype_sources as prototype_sources_module

    payload_path = _write_fbx_json_payload(tmp_path, file_name="SM_BigBranch_01_HIGH.json")

    class _ForbiddenExecutor:
        def __init__(self, *args, **kwargs):
            raise AssertionError("ProcessPoolExecutor should not be created in frozen package mode.")

    monkeypatch.setattr(prototype_sources_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(prototype_sources_module, "ProcessPoolExecutor", _ForbiddenExecutor)

    _, model, diagnostics = load_canonical_model(
        str(SIMPLE_TREE_01),
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path=str(payload_path),
            ),
            PrototypeSourceConfig(
                source_key="Mesh_2",
                source_name="Twig_02",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path=str(payload_path),
            ),
        ),
    )

    assert not any(issue.severity == "error" for issue in diagnostics)
    assert all(prototype.geometry_payload is not None for prototype in model.prototypes)


def test_fbx_part_source_restores_authored_instance_scale_without_xml_original_scale_multiplier(tmp_path: Path) -> None:
    payload_path = _write_fbx_json_payload(tmp_path)
    _, baseline_model, _ = load_canonical_model(str(SIMPLE_TREE_01))
    _, fbx_model, _ = load_canonical_model(
        str(SIMPLE_TREE_01),
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path=str(payload_path),
            ),
        ),
    )

    baseline_mesh_1_parts = [part for part in baseline_model.assembly_parts if part.prototype_key == "Mesh_1"]
    fbx_mesh_1_parts = [part for part in fbx_model.assembly_parts if part.prototype_key == "Mesh_1"]
    baseline_mesh_2_parts = [part for part in baseline_model.assembly_parts if part.prototype_key == "Mesh_2"]
    fbx_mesh_2_parts = [part for part in fbx_model.assembly_parts if part.prototype_key == "Mesh_2"]

    assert baseline_mesh_1_parts
    assert len(baseline_mesh_1_parts) == len(fbx_mesh_1_parts)
    assert baseline_mesh_2_parts
    assert len(baseline_mesh_2_parts) == len(fbx_mesh_2_parts)

    assert all(part.scale == Vector3(1.0, 1.0, 1.0) for part in baseline_mesh_1_parts)
    assert all(part.scale == Vector3(1.0, 1.0, 1.0) for part in fbx_mesh_1_parts)

    for baseline_part, fbx_part in zip(baseline_mesh_2_parts, fbx_mesh_2_parts, strict=True):
        assert fbx_part.scale == baseline_part.scale


def test_fbx_part_source_without_vertex_colors_falls_back_to_single_material(tmp_path: Path) -> None:
    payload_path = _write_fbx_json_payload(tmp_path, include_vertex_colors=False)

    _, model, diagnostics = load_canonical_model(
        str(SIMPLE_TREE_01),
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path=str(payload_path),
            ),
        ),
    )

    prototype = next(prototype for prototype in model.prototypes if prototype.source_key == "Mesh_1")

    assert prototype.geometry_payload is not None
    assert {section.material_id: list(section.face_indices) for section in prototype.geometry_payload.sections} == {
        1: [0, 1],
    }
    assert any(
        issue.code == "material_policy_warning" and "uses single material because vertex colors are missing" in issue.message
        for issue in diagnostics
    )


def test_fbx_part_source_with_uniform_vertex_colors_falls_back_to_single_material(tmp_path: Path) -> None:
    payload_path = _write_fbx_json_payload(
        tmp_path,
        color_components=[
            0.0, 0.0, 0.0, 1.0,
            0.0, 0.0, 0.0, 1.0,
            0.0, 0.0, 0.0, 1.0,
            0.0, 0.0, 0.0, 1.0,
            0.0, 0.0, 0.0, 1.0,
            0.0, 0.0, 0.0, 1.0,
        ],
    )

    _, model, diagnostics = load_canonical_model(
        str(SIMPLE_TREE_01),
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path=str(payload_path),
            ),
        ),
    )

    prototype = next(prototype for prototype in model.prototypes if prototype.source_key == "Mesh_1")

    assert prototype.geometry_payload is not None
    assert {section.material_id: list(section.face_indices) for section in prototype.geometry_payload.sections} == {
        1: [0, 1],
    }
    assert any(
        issue.code == "material_policy_warning"
        and "do not create more than one material bucket" in issue.message
        for issue in diagnostics
    )


def test_fbx_part_source_force_single_material_ignores_useful_vertex_color_split(tmp_path: Path) -> None:
    payload_path = _write_fbx_json_payload(tmp_path)

    _, model, diagnostics = load_canonical_model(
        str(SIMPLE_TREE_01),
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_material_mode=FbxMaterialMode.SINGLE_MATERIAL,
                fbx_path=str(payload_path),
            ),
        ),
    )

    prototype = next(prototype for prototype in model.prototypes if prototype.source_key == "Mesh_1")

    assert not any(issue.severity == "error" for issue in diagnostics)
    assert prototype.geometry_payload is not None
    assert {section.material_id: list(section.face_indices) for section in prototype.geometry_payload.sections} == {
        1: [0, 1],
    }


def test_fbx_part_source_with_vertex_color_warning_uses_specific_fallback_reason(tmp_path: Path) -> None:
    payload_path = _write_fbx_json_payload(tmp_path, include_vertex_colors=False)
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["vertex_color_warning"] = "Autodesk FBX SDK vertex-color access failed for prototype_payload.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")

    _, model, diagnostics = load_canonical_model(
        str(SIMPLE_TREE_01),
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path=str(payload_path),
            ),
        ),
    )

    prototype = next(prototype for prototype in model.prototypes if prototype.source_key == "Mesh_1")

    assert prototype.geometry_payload is not None
    assert prototype.geometry_payload.vertex_color_warning == payload["vertex_color_warning"]
    assert {section.material_id: list(section.face_indices) for section in prototype.geometry_payload.sections} == {
        1: [0, 1],
    }
    assert any(
        issue.code == "material_policy_warning" and payload["vertex_color_warning"] in issue.message
        for issue in diagnostics
    )


def test_fbx_part_source_explicit_vertex_color_split_requires_usable_colors(tmp_path: Path) -> None:
    payload_path = _write_fbx_json_payload(tmp_path, include_vertex_colors=False)

    with pytest.raises(ValueError, match="requested FBX vertex_color_split"):
        load_canonical_model(
            str(SIMPLE_TREE_01),
            prototype_source_configs=(
                PrototypeSourceConfig(
                    source_key="Mesh_1",
                    source_name="Twig_01",
                    mode=PrototypeSourceMode.FBX_FILE,
                    fbx_material_mode=FbxMaterialMode.VERTEX_COLOR_SPLIT,
                    fbx_path=str(payload_path),
                ),
            ),
        )


def test_fbx_part_source_explicit_vertex_color_split_reports_binding_warning_reason(tmp_path: Path) -> None:
    payload_path = _write_fbx_json_payload(tmp_path, include_vertex_colors=False)
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["vertex_color_warning"] = "Autodesk FBX SDK vertex-color access failed for prototype_payload.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="Autodesk FBX SDK vertex-color access failed"):
        load_canonical_model(
            str(SIMPLE_TREE_01),
            prototype_source_configs=(
                PrototypeSourceConfig(
                    source_key="Mesh_1",
                    source_name="Twig_01",
                    mode=PrototypeSourceMode.FBX_FILE,
                    fbx_material_mode=FbxMaterialMode.VERTEX_COLOR_SPLIT,
                    fbx_path=str(payload_path),
                ),
            ),
        )


def test_fbx_part_source_explicit_vertex_color_split_keeps_split_when_useful(tmp_path: Path) -> None:
    payload_path = _write_fbx_json_payload(tmp_path)

    _, model, diagnostics = load_canonical_model(
        str(SIMPLE_TREE_01),
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_material_mode=FbxMaterialMode.VERTEX_COLOR_SPLIT,
                fbx_path=str(payload_path),
            ),
        ),
    )

    prototype = next(prototype for prototype in model.prototypes if prototype.source_key == "Mesh_1")

    assert not any(issue.severity == "error" for issue in diagnostics)
    assert prototype.geometry_payload is not None
    assert {section.material_id: list(section.face_indices) for section in prototype.geometry_payload.sections} == {
        1: [1],
        2: [0],
    }


def test_fbx_part_source_material_slots_assigns_named_slots_and_warns_for_missing_paths(tmp_path: Path) -> None:
    payload_path = _write_fbx_json_payload(
        tmp_path,
        fbx_material_slots=[
            {"source_id": 1, "name": "Bark", "face_count": 1},
            {"source_id": 2, "name": "Needles", "face_count": 1},
        ],
        sections=[
            {"material_id": 1, "face_indices": [0]},
            {"material_id": 2, "face_indices": [1]},
        ],
    )

    _, model, diagnostics = load_canonical_model(
        str(SIMPLE_TREE_01),
        use_explicit_material_contract=True,
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_material_mode=FbxMaterialMode.MATERIAL_SLOTS,
                fbx_path=str(payload_path),
                fbx_material_slot_overrides=(
                    FbxMaterialSlotOverride(
                        slot_name="Bark",
                        ue_asset_path="/Game/TreeParts/M_Bark.M_Bark",
                    ),
                    FbxMaterialSlotOverride(
                        slot_name="Needles",
                        ue_asset_path=None,
                    ),
                ),
            ),
        ),
    )

    prototype = next(prototype for prototype in model.prototypes if prototype.source_key == "Mesh_1")
    bark_material = next(material for material in model.materials if material.name == "prototype_payload_Bark")
    needles_material = next(material for material in model.materials if material.name == "prototype_payload_Needles")

    assert bark_material.ue_asset_path == "/Game/TreeParts/M_Bark.M_Bark"
    assert needles_material.ue_asset_path == "/Game/TreeParts/M_Bark.M_Bark"
    assert prototype.geometry_payload is not None
    assert {section.material_id: list(section.face_indices) for section in prototype.geometry_payload.sections} == {
        bark_material.source_id: [0],
        needles_material.source_id: [1],
    }
    assert any(
        issue.code == "material_policy_warning"
        and "Needles" in issue.message
        and "/Game/TreeParts/M_Bark.M_Bark" in issue.message
        for issue in diagnostics
    )


def test_fbx_part_source_material_slots_requires_at_least_one_filled_path(tmp_path: Path) -> None:
    payload_path = _write_fbx_json_payload(
        tmp_path,
        fbx_material_slots=[
            {"source_id": 1, "name": "Bark", "face_count": 1},
        ],
        sections=[
            {"material_id": 1, "face_indices": [0, 1]},
        ],
    )

    with pytest.raises(ValueError, match="none of the FBX material slot overrides have an Unreal material path"):
        load_canonical_model(
            str(SIMPLE_TREE_01),
            use_explicit_material_contract=True,
            prototype_source_configs=(
                PrototypeSourceConfig(
                    source_key="Mesh_1",
                    source_name="Twig_01",
                    mode=PrototypeSourceMode.FBX_FILE,
                    fbx_material_mode=FbxMaterialMode.MATERIAL_SLOTS,
                    fbx_path=str(payload_path),
                    fbx_material_slot_overrides=(
                        FbxMaterialSlotOverride(slot_name="Bark", ue_asset_path=None),
                    ),
                ),
            ),
        )


def test_read_vertex_color_wraps_autodesk_binding_internal_error() -> None:
    class _BrokenColorElement:
        def GetDirectArray(self):
            raise SystemError(r"D:\_w\1\s\Objects\dictobject.c:1514: bad argument to internal function")

    class _BrokenMesh:
        def GetElementVertexColorCount(self):
            return 1

        def GetElementVertexColor(self, _index):
            return _BrokenColorElement()

    with pytest.raises(FbxVertexColorReadError, match="Autodesk FBX SDK failed while reading vertex colors"):
        _read_vertex_color(_BrokenMesh(), 0, 0)


def test_read_vertex_color_accepts_python_enum_mapping_and_reference_modes() -> None:
    class _MappingMode(Enum):
        eByControlPoint = 1
        eByPolygonVertex = 2
        eAllSame = 3

    class _ReferenceMode(Enum):
        eDirect = 0
        eIndex = 1
        eIndexToDirect = 2

    class _Color:
        def __init__(self, red: float, green: float, blue: float, alpha: float) -> None:
            self.mRed = red
            self.mGreen = green
            self.mBlue = blue
            self.mAlpha = alpha

    class _Array:
        def __init__(self, values) -> None:
            self._values = list(values)

        def GetCount(self):
            return len(self._values)

        def GetAt(self, index):
            return self._values[index]

    class _ColorElement:
        def GetDirectArray(self):
            return _Array((_Color(0.0, 0.0, 0.0, 1.0), _Color(1.0, 1.0, 1.0, 1.0)))

        def GetIndexArray(self):
            return _Array((1, 0, 1))

        def GetMappingMode(self):
            return _MappingMode.eByPolygonVertex

        def GetReferenceMode(self):
            return _ReferenceMode.eIndexToDirect

    class _Mesh:
        def GetElementVertexColorCount(self):
            return 1

        def GetElementVertexColor(self, _index):
            return _ColorElement()

        def GetPolygonVertexIndex(self, _polygon_index):
            return 0

        def GetPolygonVertex(self, _polygon_index, vertex_order):
            return vertex_order

    assert _read_vertex_color(_Mesh(), 0, 0) == (1.0, 1.0, 1.0, 1.0)
    assert _read_vertex_color(_Mesh(), 0, 1) == (0.0, 0.0, 0.0, 1.0)


def test_conflicting_fbx_material_modes_for_same_prototype_are_rejected(tmp_path: Path) -> None:
    payload_path = _write_fbx_json_payload(tmp_path)

    with pytest.raises(ValueError, match="Twig_01"):
        load_canonical_model(
            str(SIMPLE_TREE_01),
            prototype_source_configs=(
                PrototypeSourceConfig(
                    source_key="Mesh_1",
                    source_name="Twig_01",
                    mode=PrototypeSourceMode.FBX_FILE,
                    fbx_material_mode=FbxMaterialMode.SINGLE_MATERIAL,
                    fbx_path=str(payload_path),
                ),
                PrototypeSourceConfig(
                    source_key="Twig_01",
                    mode=PrototypeSourceMode.FBX_FILE,
                    fbx_material_mode=FbxMaterialMode.VERTEX_COLOR_SPLIT,
                    fbx_path=str(payload_path),
                ),
            ),
        )


def test_fbx_part_source_streams_usda_to_disk(tmp_path: Path) -> None:
    payload_path = _write_fbx_json_payload(tmp_path, file_name="SM_BigBranch_01_HIGH.json")
    output_path = tmp_path / "fbx_streamed.usda"

    result = convert_file(
        str(SIMPLE_TREE_01),
        str(output_path),
        cpu_profile=CpuProfile.QUIET,
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path=str(payload_path),
            ),
        ),
    )

    assert result.usda_document is not None
    assert result.usda_document.text is None
    assert result.usda_document.stats.streamed is True
    assert result.usda_document.stats.bytes_written > 0
    assert output_path.exists()
    assert not output_path.with_name("fbx_streamed.usda.partial").exists()
    usda_text = output_path.read_text(encoding="utf-8")
    assert 'def Xform "SM_BigBranch_01_HIGH"' in usda_text
    assert 'def Mesh "SM_BigBranch_01_HIGH"' in usda_text
    assert 'def Skeleton "SM_BigBranch_01_HIGH_Skeleton"' in usda_text
    assert (
        'append rel skel:skeleton = '
        '</Tree/AssemblyPartsInstancer/Prototypes/SM_BigBranch_01_HIGH/PartSkelRoot/SM_BigBranch_01_HIGH_Skeleton>'
        in usda_text
    )
    assert 'def GeomSubset "Material_1_1"' in usda_text
    assert 'def GeomSubset "Material_2_2"' in usda_text


def test_explicit_base_material_overrides_do_not_force_untouched_xml_prototypes_into_split() -> None:
    _, baseline_model, _ = load_canonical_model(str(SIMPLE_TREE_01))
    _, explicit_model, diagnostics = load_canonical_model(
        str(SIMPLE_TREE_01),
        base_material_overrides=(
            BaseMaterialOverride(
                source_id=1,
                source_name="Bark_Mat",
                ue_asset_path="/Game/TestMaterials/M_Bark_Test",
            ),
        ),
        use_explicit_material_contract=True,
    )

    assert not any(issue.severity == "error" for issue in diagnostics)
    assert next(material for material in explicit_model.materials if material.source_id == 1).ue_asset_path == (
        "/Game/TestMaterials/M_Bark_Test.M_Bark_Test"
    )
    assert [
        tuple((section.material_id, tuple(section.face_indices)) for section in prototype.mesh.sections)
        for prototype in baseline_model.prototypes
        if prototype.mesh is not None
    ] == [
        tuple((section.material_id, tuple(section.face_indices)) for section in prototype.mesh.sections)
        for prototype in explicit_model.prototypes
        if prototype.mesh is not None
    ]


def test_discover_source_materials_ignores_prototype_only_material_slots() -> None:
    materials = discover_source_materials(str(SIMPLE_TREE_01))

    assert materials == (
        BaseMaterialOverride(
            source_id=1,
            source_name="Bark_Mat",
            ue_asset_path=None,
        ),
    )


def test_explicit_xml_part_single_material_adds_prototype_local_material_override() -> None:
    _, model, diagnostics = load_canonical_model(
        str(SIMPLE_TREE_01),
        use_explicit_material_contract=True,
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.XML_MESH,
                fbx_material_mode=FbxMaterialMode.SINGLE_MATERIAL,
                single_material_path="/Game/TreeParts/M_Twig.M_Twig",
            ),
        ),
    )

    assert not any(issue.severity == "error" for issue in diagnostics)
    prototype_one = next(prototype for prototype in model.prototypes if prototype.source_key == "Mesh_1")
    prototype_two = next(prototype for prototype in model.prototypes if prototype.source_key == "Mesh_2")
    prototype_material = next(
        material for material in model.materials if material.name == "Twig_01_SingleMaterial"
    )

    assert prototype_material.ue_asset_path == "/Game/TreeParts/M_Twig.M_Twig"
    assert prototype_one.mesh is not None
    assert {section.material_id for section in prototype_one.mesh.sections} == {prototype_material.source_id}
    assert prototype_two.mesh is not None
    assert {section.material_id for section in prototype_two.mesh.sections} == {1}


def test_mesh_with_original_scale_reports_invalid_point_payloads() -> None:
    entry = replace(
        MeshLibraryEntry(
            mesh_id=7,
            name="BrokenPrototype",
            mesh=MeshData(
                name="BrokenPrototype",
                points=(Vector3,),
                face_vertex_counts=(),
                face_vertex_indices=(),
            ),
            original_scale=2.0,
        ),
    )

    with pytest.raises(TypeError, match="BrokenPrototype"):
        _mesh_with_original_scale(entry)


def test_streaming_writer_cleans_partial_file_on_cancel(tmp_path: Path) -> None:
    payload_path = _write_fbx_json_payload(tmp_path)
    output_path = tmp_path / "cancelled_stream.usda"
    _, model, diagnostics = load_canonical_model(
        str(SIMPLE_TREE_01),
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path=str(payload_path),
            ),
        ),
    )
    cancel_event = threading.Event()
    cancel_event.set()

    with pytest.raises(ConversionCancelledError, match="cancelled"):
        write_usda_document(
            model,
            diagnostics,
            output_path=output_path,
            cancel_event=cancel_event,
        )

    assert not output_path.exists()
    assert not output_path.with_name("cancelled_stream.usda.partial").exists()


def test_unused_existing_part_mesh_override_becomes_warning() -> None:
    _, model, diagnostics = load_canonical_model(
        str(SIMPLE_TREE_01),
        use_existing_part_meshes=True,
        part_mesh_asset_paths=(("Mesh_999", "/Game/TreeParts/SK_Missing.SK_Missing"),),
    )

    assert any(issue.code == "metadata_warning" and "Mesh_999" in issue.message for issue in diagnostics)


def test_part_mesh_override_requires_explicit_existing_parts_mode(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="use_existing_part_meshes=True"):
        convert_file(
            str(SIMPLE_TREE_01),
            str(tmp_path / "tree.usda"),
            part_mesh_asset_paths=(("Mesh_1", "/Game/TreeParts/SK_Twig01.SK_Twig01"),),
        )


def test_realistic_multi_material_part_mesh_authors_geom_subsets() -> None:
    document = read_source_xml(LEAFREFS_ON_BRANCH_LEVELS)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)
    usda = render_usda(model, diagnostics)

    multi_material_prototype = next(prototype for prototype in model.prototypes if prototype.source_key == "Mesh_2")
    assert multi_material_prototype.mesh is not None
    assert {section.material_id for section in multi_material_prototype.mesh.sections} == {1, 2}
    assert 'def GeomSubset "Material_1_1"' in usda.text
    assert 'def GeomSubset "Material_2_2"' in usda.text
    assert 'uniform token subsetFamily:materialBind:familyType = "nonOverlapping"' in usda.text


def test_multi_root_skeleton_keeps_unique_root_joint_names_in_usda() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    assert model.base_mesh is not None
    base_mesh = replace(
        model.base_mesh,
        skel_joint_indices=(0,) * len(model.base_mesh.points),
        skel_joint_weights=(1.0,) * len(model.base_mesh.points),
        skel_element_size=1,
    )
    multi_root_model = replace(
        model,
        materials=(
            MaterialSpec(source_id=1, name="Default_Mat", source_material_ids=(1,)),
            MaterialSpec(source_id=2, name="Secondary_Mat", source_material_ids=(2,)),
        ),
        base_mesh=base_mesh,
        skeleton=(
            Joint(name="root_a", parent=None, bind_transform=Matrix4d.identity(), rest_transform=Matrix4d.identity()),
            Joint(name="root_b", parent=None, bind_transform=Matrix4d.identity(), rest_transform=Matrix4d.identity()),
        ),
        skeletal_support_primvars=None,
        assembly_parts=(),
        prototypes=(),
    )
    diagnostics = validate_model(multi_root_model)
    usda = render_usda(multi_root_model, diagnostics, base_mesh_name="MultiRootFern")

    assert 'uniform token[] jointNames = ["root_a", "root_b"]' in usda.text
    assert 'uniform token[] joints = ["root_a", "root_b"]' in usda.text
    assert 'uniform token[] jointNames = ["MultiRootFern", "MultiRootFern"]' not in usda.text


def test_inline_part_skeleton_uses_prototype_name_for_single_joint() -> None:
    result = convert_file(str(SIMPLE_TREE_01), output_path=None)

    assert result.usda_document is not None
    assert 'def Xform "Twig_01"' in result.usda_document.text
    assert 'uniform token[] joints = ["Twig_01"]' in result.usda_document.text
    assert 'uniform token[] jointNames = ["Twig_01"]' in result.usda_document.text


def test_leaf_binding_distribution_maps_to_mesh_library_without_hardcoded_counts() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)

    mesh_ids = {entry.mesh_id for entry in model.mesh_library}
    assert all(part.source_mesh_id in mesh_ids for part in model.assembly_parts if part.source_mesh_id is not None)
    assert sum(1 for part in model.assembly_parts if part.source_bone_id is not None) == len(model.assembly_parts)
    assert all(part.source_material_id == 2 for part in model.assembly_parts)


def test_spines_are_optional_source_data_for_writer() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)
    usda = render_usda(model, diagnostics)

    assert not model.spines
    assert "Spine" not in usda.text


def test_base_tree_skinning_indices_resolve_to_authored_skeleton_range() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)

    assert model.base_mesh is not None
    assert model.base_mesh.skel_joint_indices
    assert min(model.base_mesh.skel_joint_indices) >= 0
    assert max(model.base_mesh.skel_joint_indices) < len(model.skeleton)
    assert len(model.base_mesh.skel_joint_indices) == len(model.base_mesh.points)


def test_missing_prototype_mesh_becomes_error_and_blocks_writer() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    broken_model = replace(
        model,
        prototypes=(replace(model.prototypes[0], mesh=None),) + model.prototypes[1:],
    )
    diagnostics = validate_model(broken_model)

    assert any(issue.code == "missing_prototype_mesh" and issue.severity == "error" for issue in diagnostics)
    with pytest.raises(ValueError, match="missing_prototype_mesh"):
        render_usda(broken_model, diagnostics)


def test_multi_material_prototype_authors_geom_subsets() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    prototype = model.prototypes[0]
    assert prototype.mesh is not None

    synthetic_mesh = replace(
        prototype.mesh,
        sections=(
            MeshSection(material_id=1, face_indices=(0,)),
            MeshSection(material_id=2, face_indices=tuple(range(1, len(prototype.mesh.face_vertex_counts)))),
        ),
    )
    synthetic_model = replace(
        model,
        materials=(
            MaterialSpec(source_id=1, name="Default_Mat"),
            MaterialSpec(source_id=2, name="Twigs_Mat"),
        ),
        prototypes=(replace(prototype, mesh=synthetic_mesh),) + model.prototypes[1:],
    )

    diagnostics = validate_model(synthetic_model)
    usda = render_usda(synthetic_model, diagnostics)

    assert 'uniform token subsetFamily:materialBind:familyType = "nonOverlapping"' in usda.text
    assert 'def GeomSubset "Material_1_1"' in usda.text
    assert 'def GeomSubset "Material_2_2"' in usda.text
    assert 'uniform token familyName = "materialBind"' in usda.text
    assert 'uniform token elementType = "face"' in usda.text


def _slice_between(text: str, start: str, end: str) -> str:
    start_index = text.index(start)
    end_index = text.index(end, start_index)
    return text[start_index:end_index]

