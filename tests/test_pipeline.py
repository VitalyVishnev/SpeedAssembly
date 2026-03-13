from __future__ import annotations

import json
from pathlib import Path

from xml_to_usda.normalizer import normalize_to_canonical
from xml_to_usda.ue_schema import DEFAULT_UE_SCHEMA_CONTRACT
from xml_to_usda.usda_writer import render_usda
from xml_to_usda.validator import validate_model
from xml_to_usda.xml_reader import inspect_xml, read_source_xml, render_inspect_report


DATA_DIR = Path(__file__).parent / "data"
REFERENCES_DIR = Path(__file__).resolve().parents[1] / "references"


def test_inspect_report_is_deterministic() -> None:
    document = read_source_xml(DATA_DIR / "sample_tree.xml")
    report = inspect_xml(document)
    rendered = render_inspect_report(report)
    payload = json.loads(rendered)

    assert payload["root_tag"] == "SpeedTreeRaw"
    assert payload["known_sections"]["leaf_references"] >= 1
    assert "CustomSection" in payload["unknown_sections"]


def test_canonical_model_extracts_trunk_skeleton_and_leaves() -> None:
    document = read_source_xml(DATA_DIR / "sample_tree.xml")
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)

    assert model.trunk_mesh is not None
    assert len(model.skeleton) == 2
    assert len(model.leaf_references) == 2
    assert model.leaf_references[0].bind_joint == "branch_01"


def test_usda_output_contains_expected_structure() -> None:
    document = read_source_xml(DATA_DIR / "sample_tree.xml")
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
    assert 'uniform token[] primvars:unreal:naniteAssembly:bindJoints' in usda.text
    assert 'uniform float[] primvars:unreal:naniteAssembly:bindJointWeights' in usda.text
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


def test_point_instancer_binding_attrs_include_element_size_metadata() -> None:
    document = read_source_xml(DATA_DIR / "sample_tree.xml")
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)
    usda = render_usda(model, diagnostics)

    assert 'uniform token[] primvars:unreal:naniteAssembly:bindJoints (' in usda.text
    assert 'uniform float[] primvars:unreal:naniteAssembly:bindJointWeights (' in usda.text
    assert 'elementSize = 1' in usda.text


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


def test_real_reference_sample_extracts_observed_sections() -> None:
    document = read_source_xml(REFERENCES_DIR / "speedtree" / "xml" / "SkeletyalAssemblyTest_01.xml")
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)

    assert report.version == "10.0"
    assert report.known_sections["skeleton"] >= 89
    assert report.known_sections["leaf_references"] >= 1
    assert model.trunk_mesh is not None
    assert len(model.skeleton) == 89
    assert len(model.leaf_references) == 273
