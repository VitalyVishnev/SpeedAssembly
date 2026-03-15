from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

import pytest

from xml_to_usda.dynamic_wind import build_dynamic_wind_data
from xml_to_usda.normalizer import normalize_to_canonical
from xml_to_usda.models import (
    Color4,
    DynamicWindSimulationGroup,
    Joint,
    MaterialSpec,
    Matrix4d,
    MeshData,
    MeshSection,
    SourceObject,
    Vector3,
)
from xml_to_usda.normalizer import _rebalance_assembly_part_prototype_scales, _vertex_color_material_sections
from xml_to_usda.pipeline import convert_file, generate_wind_json, inspect_source, inspect_wind_data, load_canonical_model
from xml_to_usda.source_transform import build_source_transform
from xml_to_usda.ue_schema import DEFAULT_UE_SCHEMA_CONTRACT
from xml_to_usda.usda_writer import render_usda
from xml_to_usda.validator import validate_model
from xml_to_usda.xml_reader import inspect_xml, read_source_xml, render_inspect_report


DATA_DIR = Path(__file__).parent / "data"
SIMPLE_TREE_01 = Path(__file__).resolve().parents[1] / "samples" / "speedtree" / "simple_tree" / "variants" / "SimpleTree_01.xml"
LEAFREFS_ON_TRUNK = DATA_DIR / "leafrefs_on_trunk.xml"
LEAFREFS_ON_BRANCH_LEVELS = DATA_DIR / "leafrefs_on_branch_levels.xml"
INVALID_LEAF_BONE = DATA_DIR / "invalid_leaf_bone.xml"
EXPECTED_BRANCH_1_FIRST_POINT = (6.012271, 527.466196, -18.755458)
EXPECTED_FIRST_CHILD_JOINT_POSITION = (-0.409338, 58.5628, -1.30253)


def test_inspect_report_tracks_structure_without_sample_specific_contracts() -> None:
    report = inspect_source(SIMPLE_TREE_01)
    payload = json.loads(render_inspect_report(report))

    assert payload["root_tag"] == "SpeedTreeRaw"
    assert payload["hierarchy_depth"] >= 1
    assert payload["object_class_counts"]["trunk"] >= 1
    assert payload["object_class_counts"]["branch"] >= 1
    assert payload["object_class_counts"]["twig"] >= 1
    assert payload["spine_object_count"] >= 1
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
    assert model.dynamic_wind is not None
    assert model.binding_mode == "single_joint"
    assert model.binding_element_size == 1
    assert model.base_mesh.skel_joint_indices
    assert model.base_mesh.skel_joint_weights
    assert model.base_mesh.uv_coords
    assert (model.skeleton[0].bind_translate.x, model.skeleton[0].bind_translate.y, model.skeleton[0].bind_translate.z) == pytest.approx((0.0, 0.0, 0.0))
    assert (model.skeleton[0].rest_translate.x, model.skeleton[0].rest_translate.y, model.skeleton[0].rest_translate.z) == pytest.approx((0.0, 0.0, 0.0))
    assert (model.skeleton[1].bind_translate.x, model.skeleton[1].bind_translate.y, model.skeleton[1].bind_translate.z) == pytest.approx(EXPECTED_FIRST_CHILD_JOINT_POSITION)
    assert (model.skeleton[1].rest_translate.x, model.skeleton[1].rest_translate.y, model.skeleton[1].rest_translate.z) == pytest.approx(EXPECTED_FIRST_CHILD_JOINT_POSITION)
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


def test_dynamic_wind_groups_follow_skeleton_branch_orders_without_fixed_cap() -> None:
    skeleton = (
        Joint(name="root", parent=None, bind_transform=Matrix4d.identity(), rest_transform=Matrix4d.identity()),
        Joint(name="trunk_1", parent="root", bind_transform=Matrix4d.identity(), rest_transform=Matrix4d.identity()),
        Joint(name="branch_1", parent="root", bind_transform=Matrix4d.identity(), rest_transform=Matrix4d.identity()),
        Joint(name="branch_1_main", parent="branch_1", bind_transform=Matrix4d.identity(), rest_transform=Matrix4d.identity()),
        Joint(name="branch_2", parent="branch_1", bind_transform=Matrix4d.identity(), rest_transform=Matrix4d.identity()),
        Joint(name="branch_2_main", parent="branch_2", bind_transform=Matrix4d.identity(), rest_transform=Matrix4d.identity()),
        Joint(name="branch_3", parent="branch_2", bind_transform=Matrix4d.identity(), rest_transform=Matrix4d.identity()),
        Joint(name="branch_4", parent="branch_3", bind_transform=Matrix4d.identity(), rest_transform=Matrix4d.identity()),
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

    assert len(dynamic_wind.simulation_groups) == 5
    assert dynamic_wind.simulation_groups[0].is_trunk_group is True
    assert [group.branch_order for group in dynamic_wind.simulation_groups] == [0, 1, 2, 3, 4]


def test_dynamic_wind_logical_depth_hints_use_object_anchor_joint_only() -> None:
    skeleton = (
        Joint(name="root", parent=None, bind_transform=Matrix4d.identity(), rest_transform=Matrix4d.identity()),
        Joint(name="trunk_mid", parent="root", bind_transform=Matrix4d.identity(), rest_transform=Matrix4d.identity()),
        Joint(name="branch_start", parent="trunk_mid", bind_transform=Matrix4d.identity(), rest_transform=Matrix4d.identity()),
        Joint(name="branch_tip", parent="branch_start", bind_transform=Matrix4d.identity(), rest_transform=Matrix4d.identity()),
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
                skel_joint_indices=(0, 1, 1),
                skel_joint_weights=(1.0, 1.0, 1.0),
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
                skel_joint_indices=(1, 1, 2, 2, 2, 3),
                skel_joint_weights=(1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
                skel_element_size=1,
            ),
        ),
    )

    dynamic_wind = build_dynamic_wind_data(skeleton, source_objects=source_objects)
    assignments = {assignment.joint_name: assignment.simulation_group_index for assignment in dynamic_wind.joint_assignments}

    assert assignments["root"] == 0
    assert assignments["trunk_mid"] == 0
    assert assignments["branch_start"] == 1
    assert assignments["branch_tip"] == 0


def test_dynamic_wind_json_generation_writes_groups_and_respects_slider_values(tmp_path: Path) -> None:
    output_path = tmp_path / "SimpleTree_01_DynamicWind.json"
    result = generate_wind_json(
        str(SIMPLE_TREE_01),
        str(output_path),
        group_settings=(
            DynamicWindSimulationGroup(group_index=0, branch_order=0, influence=1.8, shift_top=0.15, is_trunk_group=True),
            DynamicWindSimulationGroup(group_index=1, branch_order=1, influence=1.2, shift_top=0.05),
        ),
        gust_attenuation=0.6,
        is_ground_cover=True,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert result.output_path == str(output_path)
    assert payload["Joints"]
    assert payload["SimulationGroups"]
    assert payload["SimulationGroups"][0]["bIsTrunkGroup"] is True
    assert payload["SimulationGroups"][0]["Influence"] == pytest.approx(1.8)
    assert payload["SimulationGroups"][0]["ShiftTop"] == pytest.approx(0.15)
    assert payload["SimulationGroups"][1]["Influence"] == pytest.approx(1.2)
    if len(payload["SimulationGroups"]) > 2:
        assert payload["SimulationGroups"][2]["Influence"] == pytest.approx(1.2)
        assert payload["SimulationGroups"][2]["ShiftTop"] == pytest.approx(0.05)
    assert payload["bIsGroundCover"] is True
    assert payload["GustAttenuation"] == pytest.approx(0.6)


def test_inspect_wind_data_uses_normalized_skeleton_hierarchy() -> None:
    dynamic_wind = inspect_wind_data(str(LEAFREFS_ON_BRANCH_LEVELS))

    assert len(dynamic_wind.simulation_groups) == 4
    assert dynamic_wind.simulation_groups[0].is_trunk_group is True
    assert [group.branch_order for group in dynamic_wind.simulation_groups] == [0, 1, 2, 3]


def test_base_tree_mesh_merges_trunk_and_branch_geometry_in_stage_space() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)

    assert model.base_mesh is not None
    trunk_source_object = next(source_object for source_object in model.source_objects if source_object.name == "Trunk")
    assert trunk_source_object.mesh is not None
    assert len(model.base_mesh.points) > len(trunk_source_object.mesh.points)
    assert len(model.base_mesh.face_vertex_counts) > len(trunk_source_object.mesh.face_vertex_counts)
    assert model.base_tree_parts[0].name == "Trunk"
    assert model.base_tree_parts[1].name == "Branches_1"
    translated_point = model.base_mesh.points[model.base_tree_parts[1].point_offset]
    assert translated_point.x == pytest.approx(EXPECTED_BRANCH_1_FIRST_POINT[0])
    assert translated_point.y == pytest.approx(EXPECTED_BRANCH_1_FIRST_POINT[1])
    assert translated_point.z == pytest.approx(EXPECTED_BRANCH_1_FIRST_POINT[2])


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
    assert (prototype_first_uv.x, prototype_first_uv.y) == pytest.approx((0.8333333, 0.3333333))


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

    resolved = _resolve_prototype_material_sections(synthetic_mesh, "Mesh_1", {2}, [])

    assert resolved.sections == (
        MeshSection(material_id=1, face_indices=(1,)),
        MeshSection(material_id=2, face_indices=(0,)),
    )


def test_missing_primary_or_leaves_material_is_validation_error() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    broken_model = replace(model, materials=(MaterialSpec(source_id=1, name="Default_Mat"),))

    diagnostics = validate_model(broken_model)

    assert any(issue.code == "missing_required_material_role" and issue.severity == "error" for issue in diagnostics)


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


def test_original_scale_does_not_upscale_prototypes_when_instance_scales_are_near_one() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    assert model.mesh_library
    assert model.assembly_parts

    near_one_parts = tuple(
        replace(part, scale=Vector3(1.0, 1.0, 1.0))
        for part in model.assembly_parts
        if part.prototype_key == "Mesh_1"
    )
    untouched_parts = tuple(part for part in model.assembly_parts if part.prototype_key != "Mesh_1")
    assembly_parts = near_one_parts + untouched_parts

    entry = next(entry for entry in model.mesh_library if entry.mesh_id == 1)
    original_first_point = entry.mesh.points[0]

    rebalanced_parts, rebalanced_library = _rebalance_assembly_part_prototype_scales(assembly_parts, model.mesh_library)
    rebalanced_entry = next(entry for entry in rebalanced_library if entry.mesh_id == 1)

    assert rebalanced_entry.mesh.points[0] == original_first_point
    assert next(part for part in rebalanced_parts if part.prototype_key == "Mesh_1").scale == Vector3(1.0, 1.0, 1.0)


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
    assert 'color3f inputs:diffuseColor = (0.8, 0.8, 0.8)' in usda.text
    assert 'color3f inputs:diffuseColor = (0.280385, 0.431373, 0)' in usda.text
    assert 'def SkelRoot "BaseTreeSkelRoot"' in usda.text
    assert 'def SkelAnimation "BaseTreeAnimation"' in usda.text
    assert 'def Skeleton "MainSkeleton"' in usda.text
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
    assert 'def Xform "Mesh_1"' in usda.text
    assert 'def SkelRoot "PartSkelRoot"' in usda.text
    assert 'def Mesh "PartMesh"' in usda.text
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
    assert 'rel prototypes = [</Tree/AssemblyPartsInstancer/Prototypes/Mesh_1>, </Tree/AssemblyPartsInstancer/Prototypes/Mesh_2>]' in usda.text
    assert usda.text.index('def Scope "Prototypes"') < usda.text.index('def Xform "Mesh_1"')
    assert usda.text.index('def Xform "Mesh_1"') < usda.text.index('def SkelRoot "PartSkelRoot"')


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


def test_assembly_part_prototypes_bake_original_scale_into_standalone_meshes() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)
    usda = render_usda(model, diagnostics)

    mesh_entries = {entry.mesh_id: entry for entry in model.mesh_library}
    assert mesh_entries[1].original_scale == pytest.approx(102.466)
    assert mesh_entries[2].original_scale == pytest.approx(97.5899)
    assert max(part.scale.x for part in model.assembly_parts) < 2.0
    assert min(part.scale.x for part in model.assembly_parts) > 0.9

    prototype_mesh = next(prototype.mesh for prototype in model.prototypes if prototype.source_key == "Mesh_1")
    assert prototype_mesh is not None
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
    assert '(100, 100, 100)' not in instancer_scales_payload


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
    assert 'def Mesh "PartMesh"' in usda.text
    assert 'def Skeleton "PartSkeleton"' in usda.text


def test_assembly_part_prototypes_are_authored_as_single_joint_skeletal_meshes() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)
    usda = render_usda(model, diagnostics)

    assert 'append rel skel:skeleton = </Tree/AssemblyPartsInstancer/Prototypes/Mesh_1/PartSkelRoot/PartSkeleton>' in usda.text
    assert 'append rel skel:animationSource = </Tree/AssemblyPartsInstancer/Prototypes/Mesh_1/PartSkelRoot/PartAnimation>' in usda.text
    assert 'uniform token[] joints = ["root"]' in usda.text
    assert 'uniform token[] jointNames = ["root"]' in usda.text
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
    assert model.base_tree_parts[0].name == "Trunk"
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
    assert report.leaf_source_object_distribution == {"Branches_2": 1, "Branches_3": 1, "Trunk": 1}
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

    assert result.usda_document is not None
    assert 'prepend apiSchemas = ["NaniteAssemblyExternalRefAPI"]' in result.usda_document.text
    assert 'uniform token unreal:naniteAssembly:meshAssetPath = "/Game/TreeParts/SK_Twig01.SK_Twig01"' in result.usda_document.text
    assert 'def Xform "Mesh_1" (' in result.usda_document.text
    assert 'append rel skel:skeleton = </Tree/AssemblyPartsInstancer/Prototypes/Mesh_2/PartSkelRoot/PartSkeleton>' in result.usda_document.text


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

    assert model.spines
    assert all(spine.points for spine in model.spines)
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

