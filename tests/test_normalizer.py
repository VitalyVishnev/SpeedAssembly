from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from xml_to_usda.models import MeshData, MeshSection, SourceObject, Vector3
from xml_to_usda.normalizer import (
    _build_base_mesh,
    _extract_assembly_parts_from_leaf_references,
    _extract_bounds,
    _extract_face_varying_uvs,
    _read_float_list,
    _read_int_list,
    _read_positive_float,
    normalize_to_canonical,
)
from xml_to_usda.pipeline import inspect_source, load_canonical_model
from xml_to_usda.source_transform import build_source_transform
from xml_to_usda.xml_reader import analyze_xml, inspect_xml, read_source_xml, render_inspect_report


SIMPLE_TREE_01 = Path(__file__).resolve().parents[1] / "samples" / "speedtree" / "simple_tree" / "variants" / "SimpleTree_01.xml"


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
    assert payload["material_count"] == 3
    assert payload["base_material_distribution"] == {"0": 46, "1": payload["base_mesh_face_count"] - 46}
    assert payload["prototype_material_distribution"]["0"] > 0
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
    assert len(model.materials) == 3
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
    assert model.skeleton[0].bind_end_translate is not None
    assert model.skeleton[0].bind_end_translate.y > 0.5
    assert model.skeleton[1].bind_translate == pytest.approx(model.skeleton[1].rest_translate)
    assert abs(model.skeleton[1].bind_translate.y) > 0
    assert len(model.base_mesh.skel_joint_indices) == len(model.base_mesh.points)
    assert len(model.base_mesh.skel_joint_weights) == len(model.base_mesh.points)
    assert len(model.base_mesh.uv_coords) == len(model.base_mesh.face_vertex_indices)
    assert {material.source_id for material in model.materials} == {0, 1, 2}
    assert {section.material_id for section in model.base_mesh.sections} == {0, 1}
    assert all(
        prototype.mesh is not None and {section.material_id for section in prototype.mesh.sections} == {0}
        for prototype in model.prototypes
    )
    assert all(part.binding.joint_tokens for part in model.assembly_parts)
    assert all(len(part.binding.joint_tokens) == len(part.binding.weights) for part in model.assembly_parts)
    assert all(token.startswith("bone_") or token == "root" for part in model.assembly_parts for token in part.binding.joint_tokens)
    assert {prototype.source_key for prototype in model.prototypes} == {part.prototype_key for part in model.assembly_parts}


def test_canonical_model_matches_when_source_node_index_is_prebuilt() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    analysis = analyze_xml(document)
    model_from_analysis = normalize_to_canonical(document, analysis.report, source_nodes=analysis.source_nodes)
    model_without_shared_index = normalize_to_canonical(document, analysis.report)

    assert model_without_shared_index == model_from_analysis


def test_object_mesh_reads_all_sibling_triangle_material_blocks(tmp_path: Path) -> None:
    source_path = tmp_path / "multi_triangle_blocks.xml"
    source_path.write_text(
        """
        <SpeedTreeRaw>
            <Materials>
                <Material ID="10" Name="Bark" />
                <Material ID="11" Name="Cap" />
            </Materials>
            <Bones>
                <Bone ID="20" ParentID="-1" Name="Root" StartX="0" StartY="0" StartZ="0" Generator="Group_0" />
            </Bones>
            <Objects>
                <Object ID="1" Name="Group_cap" AbsX="0" AbsY="0" AbsZ="0" RelX="0" RelY="0" RelZ="0">
                    <Points Count="4">
                        <X>0 1 0 0</X>
                        <Y>0 0 1 0</Y>
                        <Z>0 0 0 1</Z>
                    </Points>
                    <Vertices Count="4">
                        <TexcoordU>0 1 0 0</TexcoordU>
                        <TexcoordV>0 0 1 1</TexcoordV>
                        <BoneID>20 20 20 20</BoneID>
                    </Vertices>
                    <Triangles Material="10" Count="1">
                        <PointIndices>0 1 2</PointIndices>
                        <VertexIndices>0 1 2</VertexIndices>
                    </Triangles>
                    <Triangles Material="11" Count="1">
                        <PointIndices>0 2 3</PointIndices>
                        <VertexIndices>0 2 3</VertexIndices>
                    </Triangles>
                </Object>
            </Objects>
        </SpeedTreeRaw>
        """,
        encoding="utf-8",
    )
    document = read_source_xml(source_path)
    report = inspect_xml(document)

    model = normalize_to_canonical(document, report)

    assert model.base_mesh is not None
    assert model.base_mesh.face_vertex_counts == (3, 3)
    assert model.base_mesh.face_vertex_indices == (0, 1, 2, 0, 2, 3)
    assert model.base_mesh.skel_joint_indices == (0, 0, 0, 0)
    assert model.base_mesh.sections == (
        MeshSection(material_id=10, face_indices=(0,)),
        MeshSection(material_id=11, face_indices=(1,)),
    )
    assert not any("did not resolve to any skeletal binding" in warning for warning in model.metadata.warnings)


def test_object_reads_all_sibling_leaf_reference_blocks(tmp_path: Path) -> None:
    source_path = tmp_path / "multi_leaf_reference_blocks.xml"
    source_path.write_text(
        """
        <SpeedTreeRaw>
            <Materials>
                <Material ID="10" Name="Needles" />
            </Materials>
            <Bones>
                <Bone ID="20" ParentID="-1" Name="Root" StartX="0" StartY="0" StartZ="0" Generator="Group_0" />
            </Bones>
            <Objects>
                <Object ID="1" Name="Branch" AbsX="0" AbsY="0" AbsZ="0" RelX="0" RelY="0" RelZ="0">
                    <LeafReferences Material="10" Count="1">
                        <X>0</X>
                        <Y>0</Y>
                        <Z>0</Z>
                        <Scale>1</Scale>
                        <RotAxisX>0</RotAxisX>
                        <RotAxisY>0</RotAxisY>
                        <RotAxisZ>1</RotAxisZ>
                        <RotAngle>0</RotAngle>
                        <MeshID>1</MeshID>
                        <MeshLOD>0</MeshLOD>
                        <BoneID>20</BoneID>
                    </LeafReferences>
                    <LeafReferences Material="10" Count="1">
                        <X>1</X>
                        <Y>0</Y>
                        <Z>0</Z>
                        <Scale>1</Scale>
                        <RotAxisX>0</RotAxisX>
                        <RotAxisY>0</RotAxisY>
                        <RotAxisZ>1</RotAxisZ>
                        <RotAngle>0</RotAngle>
                        <MeshID>2</MeshID>
                        <MeshLOD>0</MeshLOD>
                        <BoneID>20</BoneID>
                    </LeafReferences>
                </Object>
            </Objects>
        </SpeedTreeRaw>
        """,
        encoding="utf-8",
    )
    document = read_source_xml(source_path)
    analysis = analyze_xml(document)

    model = normalize_to_canonical(document, analysis.report, source_nodes=analysis.source_nodes)

    assert analysis.report.leaf_mesh_distribution == {"1": 1, "2": 1}
    assert analysis.report.leaf_binding_distribution == {"20": 2}
    assert analysis.report.leaf_source_object_distribution == {"1": 2}
    assert len(model.assembly_parts) == 2
    assert [part.prototype_key for part in model.assembly_parts] == ["Mesh_1", "Mesh_2"]
    assert [part.bind_joint for part in model.assembly_parts] == ["bone_020", "bone_020"]


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


def test_source_transform_batch_point_conversion_matches_single_point_conversion() -> None:
    root = ET.fromstring("<SpeedTreeRaw><Meshes><Mesh Orient='xyzZ' /></Meshes></SpeedTreeRaw>")
    transform = build_source_transform(root, units_hint=None, up_axis_hint=None)

    batch_points = transform.points_components_to_stage([1.0, 2.0], [3.0, 4.0], [5.0, 6.0])

    assert batch_points == [Vector3(1.0, 5.0, -3.0), Vector3(2.0, 6.0, -4.0)]


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
    parts = _extract_assembly_parts_from_leaf_references(tuple(root.findall(".//Object")), [], transform, {2})

    assert len(parts) == 1
    orientation = parts[0].orientation
    assert orientation.real == pytest.approx(0.70710678)
    assert orientation.i == pytest.approx(0.0)
    assert orientation.j == pytest.approx(0.70710678)
    assert orientation.k == pytest.approx(0.0)


def test_non_mesh_leaf_reference_host_with_nonzero_abs_transform_fails_loudly() -> None:
    root = ET.fromstring(
        """
        <SpeedTreeRaw>
            <Objects>
                <Object ID="1" Name="AmbiguousLeafHost" AbsX="1" AbsY="0" AbsZ="0">
                    <LeafReferences Material="2" Count="1">
                        <X>0</X>
                        <Y>0</Y>
                        <Z>0</Z>
                        <Scale>1</Scale>
                        <MeshID>1</MeshID>
                    </LeafReferences>
                </Object>
            </Objects>
        </SpeedTreeRaw>
        """
    )
    transform = build_source_transform(root, units_hint=None, up_axis_hint=None)

    with pytest.raises(ValueError, match="position space cannot be determined safely"):
        _extract_assembly_parts_from_leaf_references(tuple(root.findall(".//Object")), [], transform, {2})


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
    assert _read_float_list("1,2,3 invalid 4.5") == pytest.approx([1.0, 2.0, 3.0, 4.5])
    assert _read_int_list("1,2 invalid -3") == [1, 2, -3]
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
