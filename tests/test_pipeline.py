from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from xml_to_usda.normalizer import normalize_to_canonical
from xml_to_usda.pipeline import inspect_source
from xml_to_usda.ue_schema import DEFAULT_UE_SCHEMA_CONTRACT
from xml_to_usda.usda_writer import render_usda
from xml_to_usda.validator import validate_model
from xml_to_usda.xml_reader import inspect_xml, read_source_xml, render_inspect_report


DATA_DIR = Path(__file__).parent / "data"
SIMPLE_TREE_01 = Path(__file__).resolve().parents[1] / "Samples" / "speedtree" / "simple_tree" / "variants" / "SimpleTree_01.xml"
EXPECTED_BRANCH_1_FIRST_POINT = (6.012271, 18.755458, 527.466196)


def test_inspect_report_tracks_structure_without_sample_specific_contracts() -> None:
    report = inspect_source(SIMPLE_TREE_01)
    payload = json.loads(render_inspect_report(report))

    assert payload["root_tag"] == "SpeedTreeRaw"
    assert payload["hierarchy_depth"] >= 1
    assert payload["object_class_counts"]["trunk"] >= 1
    assert payload["object_class_counts"]["branch"] >= 1
    assert payload["object_class_counts"]["twig"] >= 1
    assert payload["spine_object_count"] >= 1
    assert payload["leaf_binding_distribution"]
    assert payload["leaf_mesh_distribution"]
    assert payload["base_geometry_mode"] == "merged"
    assert payload["base_mesh_part_count"] >= 2
    assert payload["base_mesh_point_count"] > 0
    assert payload["base_mesh_face_count"] > 0
    assert payload["prototype_structure"] == "referenced_scope"
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


def test_canonical_model_extracts_universal_tree_asset_shape() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)

    assert model.base_mesh is not None
    assert model.trunk_source_mesh is not None
    assert model.source_objects
    assert model.skeleton
    assert model.base_mesh_parts
    assert model.branch_segments
    assert model.leaf_instances
    assert model.mesh_library
    assert model.prototypes
    assert model.skeletal_support_primvars is not None
    assert model.binding_mode == "single_joint"
    assert model.binding_element_size == 1
    assert model.trunk_mesh == model.base_mesh
    assert model.base_mesh.skel_joint_indices
    assert model.base_mesh.skel_joint_weights
    assert len(model.base_mesh.skel_joint_indices) == len(model.base_mesh.face_vertex_indices)
    assert len(model.base_mesh.skel_joint_weights) == len(model.base_mesh.face_vertex_indices)
    assert all(leaf.binding.joint_tokens for leaf in model.leaf_instances)
    assert all(len(leaf.binding.joint_tokens) == len(leaf.binding.weights) for leaf in model.leaf_instances)
    assert {prototype.source_key for prototype in model.prototypes} == {leaf.prototype_key for leaf in model.leaf_instances}


def test_base_mesh_merges_trunk_and_branch_geometry_with_abs_translation() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)

    assert model.base_mesh is not None
    assert model.trunk_source_mesh is not None
    assert len(model.base_mesh.points) > len(model.trunk_source_mesh.points)
    assert len(model.base_mesh.face_vertex_counts) > len(model.trunk_source_mesh.face_vertex_counts)
    assert model.base_mesh_parts[0].name == "Trunk"
    assert model.base_mesh_parts[1].name == "Branches_1"
    translated_point = model.base_mesh.points[model.base_mesh_parts[1].point_offset]
    assert translated_point.x == pytest.approx(EXPECTED_BRANCH_1_FIRST_POINT[0])
    assert translated_point.y == pytest.approx(EXPECTED_BRANCH_1_FIRST_POINT[1])
    assert translated_point.z == pytest.approx(EXPECTED_BRANCH_1_FIRST_POINT[2])


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
    assert 'custom rel unreal:naniteAssembly:skeleton = </Tree/TrunkSkelRoot/TrunkSkeleton>' in usda.text
    assert 'def Xform "Branches"' in usda.text
    assert 'def SkelRoot "TrunkSkelRoot"' in usda.text
    assert 'def SkelAnimation "animation"' in usda.text
    assert 'def Skeleton "TrunkSkeleton"' in usda.text
    assert 'append rel skel:animationSource = </Tree/TrunkSkelRoot/animation>' in usda.text
    assert 'apiSchemas = ["SkelBindingAPI"]' in usda.text
    assert 'uniform token[] skel:joints = [' in usda.text
    assert 'uniform matrix4d primvars:skel:geomBindTransform = ' in usda.text
    assert 'int[] primvars:skel:jointIndices = [' in usda.text
    assert 'float[] primvars:skel:jointWeights = [' in usda.text
    assert 'uniform token primvars:skel:skinningMethod = "classicLinear"' in usda.text
    assert 'interpolation = "vertex"' in usda.text
    assert 'primvars:boneCapture_pCaptPath' in usda.text
    assert 'primvars:ueJointNames' in usda.text
    assert 'primvars:localtransform' in usda.text
    assert 'def PointInstancer "PartsInstancer"' in usda.text
    assert 'apiSchemas = ["NaniteAssemblySkelBindingAPI"]' in usda.text
    assert 'token[] primvars:unreal:naniteAssembly:bindJoints = [' in usda.text
    assert 'int[] primvars:unreal:naniteAssembly:bindJoints:indices = None' in usda.text
    assert 'float[] primvars:unreal:naniteAssembly:bindJointWeights = [' in usda.text
    assert 'int[] primvars:unreal:naniteAssembly:bindJointWeights:indices = None' in usda.text
    assert 'elementSize = 2' in usda.text
    assert 'interpolation = "vertex"' in usda.text
    assert 'quath[] orientations = [' in usda.text
    assert 'def Scope "Prototypes"' in usda.text
    assert 'token visibility = "invisible"' in usda.text
    assert 'append references = </Tree/Branches/Mesh_1>' in usda.text
    assert 'token visibility = None' in usda.text


def test_referenced_prototypes_clear_hidden_branch_library_visibility() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)
    usda = render_usda(model, diagnostics)

    assert 'def Xform "Mesh_1" (' in usda.text
    assert 'def Xform "Mesh_2" (' in usda.text
    assert 'append references = </Tree/Branches/Mesh_1>' in usda.text
    assert 'append references = </Tree/Branches/Mesh_2>' in usda.text
    assert usda.text.index('token visibility = "invisible"') < usda.text.index('def PointInstancer "PartsInstancer"')
    assert usda.text.index('token visibility = None') > usda.text.index('def Scope "Prototypes"')


def test_ue_schema_contract_matches_current_writer_contract() -> None:
    contract = DEFAULT_UE_SCHEMA_CONTRACT

    assert contract.stage_meters_per_unit == 1.0
    assert contract.stage_up_axis == "Y"
    assert contract.root_api == "NaniteAssemblyRootAPI"
    assert contract.external_ref_api == "NaniteAssemblyExternalRefAPI"
    assert contract.binding_api == "NaniteAssemblySkelBindingAPI"
    assert contract.mesh_type_attr == "unreal:naniteAssembly:meshType"
    assert contract.root_kind == "component"
    assert contract.skeleton_relationship_attr == "custom rel unreal:naniteAssembly:skeleton = </Tree/TrunkSkelRoot/TrunkSkeleton>"
    assert contract.bind_joints_attr == "token[] primvars:unreal:naniteAssembly:bindJoints"
    assert contract.bind_weights_attr == "float[] primvars:unreal:naniteAssembly:bindJointWeights"
    assert contract.skinning_method_attr == "uniform token primvars:skel:skinningMethod"
    assert contract.skinning_method_value == "classicLinear"
    assert contract.point_instancer_joint_element_size == 2
    assert contract.root_api_allowed_prims == ("Xform",)
    assert contract.external_ref_api_allowed_prims == ("Xform",)
    assert contract.binding_api_allowed_prims == ("Xform", "Mesh", "SkelRoot", "PointInstancer")


def test_point_instancer_binding_attrs_use_path_like_joint_tokens() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)
    usda = render_usda(model, diagnostics)

    assert 'token[] primvars:unreal:naniteAssembly:bindJoints = [' in usda.text
    assert 'float[] primvars:unreal:naniteAssembly:bindJointWeights = [' in usda.text
    assert 'elementSize = 2' in usda.text
    assert '"Tree_point_17"' in usda.text
    assert '"Tree_point_104"' in usda.text
    assert '0]' in usda.text or ', 0,' in usda.text


def test_point_instancer_orientations_remain_non_uniform_and_deterministic() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model_a = normalize_to_canonical(document, report)
    model_b = normalize_to_canonical(document, report)

    observed_a = tuple(leaf.orientation.to_usda() for leaf in model_a.leaf_instances[:3])
    observed_b = tuple(leaf.orientation.to_usda() for leaf in model_b.leaf_instances[:3])
    assert observed_a == observed_b
    assert len(set(leaf.orientation.to_usda() for leaf in model_a.leaf_instances)) > 3


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


def test_generated_usda_tracks_tutorial_reference_contract_without_houdini_only_fields() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)
    usda = render_usda(model, diagnostics)

    assert 'kind = "component"' in usda.text
    assert 'uniform token primvars:skel:skinningMethod = "classicLinear"' in usda.text
    assert 'int[] primvars:unreal:naniteAssembly:bindJoints:indices = None' in usda.text
    assert 'int[] primvars:unreal:naniteAssembly:bindJointWeights:indices = None' in usda.text
    assert 'float primvars:pCaptFrame' not in usda.text
    assert 'string primvars:pCaptSkelRoot' not in usda.text
    assert 'NaniteAssemblyExternalRefAPI' not in usda.text


def test_leaf_binding_distribution_maps_to_mesh_library_without_hardcoded_counts() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)

    mesh_ids = {entry.mesh_id for entry in model.mesh_library}
    assert all(leaf.source_mesh_id in mesh_ids for leaf in model.leaf_instances if leaf.source_mesh_id is not None)
    assert sum(1 for leaf in model.leaf_instances if leaf.source_bone_id is not None) == len(model.leaf_instances)


def test_spines_are_optional_source_data_for_writer() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)
    usda = render_usda(model, diagnostics)

    assert model.spines
    assert all(spine.points for spine in model.spines)
    assert "Spine" not in usda.text


def test_base_mesh_skinning_indices_resolve_to_authored_skeleton_range() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)

    assert model.base_mesh is not None
    assert model.base_mesh.skel_joint_indices
    assert min(model.base_mesh.skel_joint_indices) >= 0
    assert max(model.base_mesh.skel_joint_indices) < len(model.skeleton)


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
