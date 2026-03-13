from __future__ import annotations

import json
from pathlib import Path

from xml_to_usda.normalizer import normalize_to_canonical
from xml_to_usda.ue_schema import DEFAULT_UE_SCHEMA_CONTRACT
from xml_to_usda.usda_writer import render_usda
from xml_to_usda.validator import validate_model
from xml_to_usda.xml_reader import inspect_xml, read_source_xml, render_inspect_report


DATA_DIR = Path(__file__).parent / "data"
SIMPLE_TREE_01 = Path(__file__).resolve().parents[1] / "Samples" / "speedtree" / "simple_tree" / "variants" / "SimpleTree_01.xml"
EXPECTED_LEAF_BONE_IDS = (
    17,
    19,
    20,
    22,
    24,
    30,
    32,
    34,
    35,
    36,
    44,
    46,
    49,
    51,
    56,
    57,
    59,
    61,
    63,
    64,
    66,
    67,
    68,
    70,
    71,
    77,
    78,
    80,
    84,
    90,
    92,
    94,
    96,
    98,
    99,
    100,
    101,
    102,
    104,
)
EXPECTED_LEAF_BINDING_DISTRIBUTION = {str(bone_id): 1 for bone_id in EXPECTED_LEAF_BONE_IDS}
EXPECTED_LEAF_MESH_DISTRIBUTION = {1: 13, 2: 26}


def test_inspect_report_tracks_simple_tree_01_structure() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    rendered = render_inspect_report(report)
    payload = json.loads(rendered)

    assert payload["root_tag"] == "SpeedTreeRaw"
    assert payload["hierarchy_depth"] == 4
    assert payload["object_class_counts"]["trunk"] == 1
    assert payload["object_class_counts"]["branch"] == 22
    assert payload["object_class_counts"]["twig"] == 39
    assert payload["spine_object_count"] == 23
    assert payload["leaf_binding_distribution"] == EXPECTED_LEAF_BINDING_DISTRIBUTION
    assert payload["leaf_mesh_distribution"] == {str(mesh_id): count for mesh_id, count in EXPECTED_LEAF_MESH_DISTRIBUTION.items()}


def test_canonical_model_extracts_simple_tree_01_graph() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)

    assert model.trunk_mesh is not None
    assert len(model.source_objects) == 63
    assert len(model.skeleton) == 105
    assert len(model.branch_segments) == 22
    assert len(model.leaf_instances) == 39
    assert len(model.mesh_library) == 2
    assert len(model.spines) == 23
    assert model.leaf_instances[0].bind_joint.startswith("bone_")
    assert model.leaf_instances[0].source_bone_id is not None


def test_usda_output_contains_expected_structure() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)
    usda = render_usda(model, diagnostics)

    assert 'apiSchemas = ["NaniteAssemblyRootAPI"]' in usda.text
    assert 'uniform token unreal:naniteAssembly:meshType = "skeletalMesh"' in usda.text
    assert 'rel unreal:naniteAssembly:skeleton = </Tree/TrunkSkelRoot/TrunkSkeleton>' in usda.text
    assert 'def SkelRoot "TrunkSkelRoot"' in usda.text
    assert 'def Skeleton "TrunkSkeleton"' in usda.text
    assert 'apiSchemas = ["SkelBindingAPI"]' in usda.text
    assert 'def PointInstancer "PartsInstancer"' in usda.text
    assert 'apiSchemas = ["NaniteAssemblySkelBindingAPI"]' in usda.text
    assert 'uniform token[] primvars:unreal:naniteAssembly:bindJoints = [' in usda.text
    assert 'uniform float[] primvars:unreal:naniteAssembly:bindJointWeights = [' in usda.text
    assert 'elementSize = 1' in usda.text
    assert 'quatf[] orientations = [' in usda.text
    assert 'def Scope "Prototypes"' in usda.text


def test_ue_schema_contract_matches_verified_ue_57_names() -> None:
    contract = DEFAULT_UE_SCHEMA_CONTRACT

    assert contract.root_api == "NaniteAssemblyRootAPI"
    assert contract.external_ref_api == "NaniteAssemblyExternalRefAPI"
    assert contract.binding_api == "NaniteAssemblySkelBindingAPI"
    assert contract.mesh_type_attr == "unreal:naniteAssembly:meshType"
    assert contract.skeleton_relationship_attr == "rel unreal:naniteAssembly:skeleton = </Tree/TrunkSkelRoot/TrunkSkeleton>"
    assert contract.bind_joints_attr == "uniform token[] primvars:unreal:naniteAssembly:bindJoints"
    assert contract.bind_weights_attr == "uniform float[] primvars:unreal:naniteAssembly:bindJointWeights"
    assert contract.root_api_allowed_prims == ("Xform",)
    assert contract.external_ref_api_allowed_prims == ("Xform",)
    assert contract.binding_api_allowed_prims == ("Xform", "Mesh", "SkelRoot", "PointInstancer")


def test_point_instancer_binding_attrs_use_explicit_leaf_bone_ids() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)
    usda = render_usda(model, diagnostics)

    assert 'uniform token[] primvars:unreal:naniteAssembly:bindJoints = [' in usda.text
    assert 'uniform float[] primvars:unreal:naniteAssembly:bindJointWeights = [' in usda.text
    assert 'elementSize = 1' in usda.text
    assert '"bone_017"' in usda.text
    assert '"bone_104"' in usda.text


def test_missing_skeleton_is_error() -> None:
    document = read_source_xml(DATA_DIR / "missing_skeleton.xml")
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)

    assert any(issue.code == "missing_skeleton" and issue.severity == "error" for issue in diagnostics)


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

    assert any("Non-default units hint" in issue.message for issue in diagnostics)
    assert any("Non-default up-axis hint" in issue.message for issue in diagnostics)


def test_simple_tree_01_leaf_binding_distribution_is_deterministic() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)

    bone_ids = sorted(leaf.source_bone_id for leaf in model.leaf_instances if leaf.source_bone_id is not None)
    mesh_distribution: dict[int, int] = {}
    for leaf in model.leaf_instances:
        assert leaf.source_bone_id is not None
        assert leaf.source_mesh_id is not None
        mesh_distribution[leaf.source_mesh_id] = mesh_distribution.get(leaf.source_mesh_id, 0) + 1

    assert tuple(bone_ids) == EXPECTED_LEAF_BONE_IDS
    assert mesh_distribution == EXPECTED_LEAF_MESH_DISTRIBUTION


def test_simple_tree_01_spines_are_optional_source_data() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)
    usda = render_usda(model, diagnostics)

    assert len(model.spines) == 23
    assert all(spine.points for spine in model.spines)
    assert "Spine" not in usda.text
