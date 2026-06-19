from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from xml_to_usda.canonical_loader import load_canonical_model
from xml_to_usda.models import (
    ConversionMode,
    ExportMetadata,
    MeshData,
    MeshSection,
    PrototypeResolutionMode,
    PrototypeSourceConfig,
    PrototypeSourceMode,
    PrototypeStrategy,
    Vector3,
)
from xml_to_usda.normalizer import normalize_to_canonical
from xml_to_usda.pipeline import convert_file
from xml_to_usda.validator import validate_model
from xml_to_usda.xml_reader import inspect_xml, read_source_xml
from usda_test_inventory import UsdaInventory


SIMPLE_TREE_01 = (
    Path(__file__).resolve().parents[1]
    / "samples"
    / "speedtree"
    / "simple_tree"
    / "variants"
    / "SimpleTree_01.xml"
)
DATA_DIR = Path(__file__).parent / "data"
LEAFREFS_ON_TRUNK = DATA_DIR / "leafrefs_on_trunk.xml"
LEAFREFS_ON_BRANCH_LEVELS = DATA_DIR / "leafrefs_on_branch_levels.xml"
INVALID_LEAF_BONE = DATA_DIR / "invalid_leaf_bone.xml"


def _write_fbx_json_payload(tmp_path: Path, *, file_name: str = "prototype_payload.json") -> Path:
    payload = {
        "point_components": [0.0, 0.0, 0.0, 1.0, 0.0, 0.0],
        "face_vertex_counts": [3, 3],
        "face_vertex_indices": [0, 1, 2, 3, 4, 5],
        "uv_components": [0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0],
        "vertex_color_components": [
            0.0, 0.0, 0.0, 1.0,
            0.0, 0.0, 0.0, 1.0,
            0.0, 0.0, 0.0, 1.0,
            1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 1.0,
        ],
    }
    payload_path = tmp_path / file_name
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    return payload_path


def test_missing_skeleton_is_error() -> None:
    document = read_source_xml(DATA_DIR / "missing_skeleton.xml")
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)

    assert any(issue.code == "missing_skeleton" and issue.severity == "error" for issue in diagnostics)
    with pytest.raises(ValueError, match="missing_skeleton"):
        from xml_to_usda.usda_writer import render_usda

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
    from xml_to_usda.usda_writer import render_usda

    usda = render_usda(model, diagnostics)
    inventory = UsdaInventory.from_text(usda.text)

    assert inventory.has_attribute("/Tree", "kind")
    assert inventory.has_api_schema("/Tree", "NaniteAssemblyRootAPI")
    assert inventory.has_prim("/Tree/BaseTreeSkelRoot", "SkelRoot")
    assert inventory.has_prim("/Tree/BaseTreeSkelRoot/BaseTreeMesh", "Mesh")
    assert inventory.has_attribute("/Tree/BaseTreeSkelRoot/BaseTreeMesh", "primvars:skel:skinningMethod")
    assert inventory.has_relationship("/Tree/BaseTreeSkelRoot/BaseTreeMesh", "skel:skeleton")
    assert inventory.has_attribute("/Tree/BaseTreeSkelRoot/MainSkeleton", "bindTransforms")
    assert inventory.has_attribute("/Tree/BaseTreeSkelRoot/MainSkeleton", "restTransforms")
    assert inventory.has_attribute("/Tree/AssemblyPartsInstancer", "primvars:unreal:naniteAssembly:bindJoints")
    assert inventory.has_attribute("/Tree/AssemblyPartsInstancer", "primvars:unreal:naniteAssembly:bindJointWeights")
    assert inventory.has_attribute("/Tree/AssemblyPartsInstancer", "elementSize")
    assert inventory.contains("/Tree/AssemblyPartsInstancer", "translations = [")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot", "SkelRoot")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/Twig_01", "Mesh")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/PartSkeleton", "Skeleton")
    assert inventory.has_relationship("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/Twig_01", "skel:skeleton")
    assert inventory.has_relationship("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/PartSkeleton", "skel:animationSource")
    assert not inventory.contains("/Tree", "NaniteAssemblyExternalRefAPI")
    assert not inventory.contains("/Tree", "primvars:pCaptFrame")
    assert not inventory.contains("/Tree", "string primvars:pCaptSkelRoot")


def test_assembly_part_prototypes_are_authored_as_single_joint_skeletal_meshes() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)
    from xml_to_usda.usda_writer import render_usda

    usda = render_usda(model, diagnostics)
    inventory = UsdaInventory.from_text(usda.text)

    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01", "Xform")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot", "SkelRoot")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/Twig_01", "Mesh")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/PartSkeleton", "Skeleton")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/PartAnimation", "SkelAnimation")
    assert inventory.has_relationship("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/Twig_01", "skel:skeleton")
    assert inventory.has_relationship("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/PartSkeleton", "skel:animationSource")
    assert inventory.has_attribute("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/Twig_01", "primvars:skel:skinningMethod")
    assert inventory.has_attribute("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/Twig_01", "elementSize")
    assert inventory.contains(
        "/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/PartSkeleton",
        'uniform token[] joints = ["Twig_01"]',
    )
    assert inventory.contains(
        "/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/PartSkeleton",
        'uniform token[] jointNames = ["Twig_01"]',
    )


def test_skeletal_parts_mode_authors_library_without_base_tree_or_instancer() -> None:
    _, model, _ = load_canonical_model(str(SIMPLE_TREE_01), conversion_mode=ConversionMode.SKELETAL_PARTS)
    parts_only_model = replace(model, base_mesh=None, skeleton=None, assembly_parts=())
    diagnostics = validate_model(parts_only_model, conversion_mode=ConversionMode.SKELETAL_PARTS)
    from xml_to_usda.usda_writer import render_usda

    usda = render_usda(parts_only_model, diagnostics, conversion_mode=ConversionMode.SKELETAL_PARTS)
    inventory = UsdaInventory.from_text(usda.text)

    assert not any(issue.severity == "error" for issue in diagnostics)
    assert inventory.has_prim("/Tree", "Xform")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer", "Xform")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes", "Scope")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01", "Xform")
    assert inventory.has_prim("/Tree/Materials", "Scope")
    assert not inventory.has_api_schema("/Tree", "NaniteAssemblyRootAPI")
    assert not inventory.contains("/Tree", "unreal:naniteAssembly:meshType")
    assert not inventory.contains("/Tree", "rel unreal:naniteAssembly:skeleton")
    assert not inventory.has_prim("/Tree/BaseTreeSkelRoot")
    assert not inventory.has_prim("/Tree/AssemblyPartsInstancer", "PointInstancer")
    assert not inventory.has_prim("/Tree/AssemblyPartsInstancer", "Skeleton")
    assert inventory.contains("/Tree/AssemblyPartsInstancer", 'def SkelRoot "PartSkelRoot"')
    assert inventory.contains("/Tree/AssemblyPartsInstancer", 'def Mesh "Twig_01"')
    assert inventory.contains(
        "/Tree/AssemblyPartsInstancer",
        'append rel skel:skeleton = </Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/PartSkeleton>',
    )
    assert inventory.contains(
        "/Tree/AssemblyPartsInstancer",
        'append rel skel:animationSource = </Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/PartAnimation>',
    )
    assert inventory.contains("/Tree/AssemblyPartsInstancer", 'rel material:binding = </Tree/Materials/Material_0_0>')


def test_skeletal_parts_mode_preserves_external_part_reuse() -> None:
    _, model, _ = load_canonical_model(
        str(SIMPLE_TREE_01),
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                mode=PrototypeSourceMode.UNREAL_ASSET,
                asset_path="/Game/TreeParts/SK_Twig01.SK_Twig01",
            ),
        ),
        conversion_mode=ConversionMode.SKELETAL_PARTS,
    )
    parts_only_model = replace(model, base_mesh=None, skeleton=None, assembly_parts=())
    diagnostics = validate_model(parts_only_model, conversion_mode=ConversionMode.SKELETAL_PARTS)
    from xml_to_usda.usda_writer import render_usda

    usda = render_usda(parts_only_model, diagnostics, conversion_mode=ConversionMode.SKELETAL_PARTS)
    inventory = UsdaInventory.from_text(usda.text)

    assert not any(issue.severity == "error" for issue in diagnostics)
    assert inventory.has_prim("/Tree", "Xform")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer", "Xform")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes", "Scope")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01", "Xform")
    assert inventory.has_api_schema("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01", "NaniteAssemblyExternalRefAPI")
    assert inventory.has_attribute("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01", "unreal:naniteAssembly:meshAssetPath")
    assert not inventory.has_prim("/Tree/BaseTreeSkelRoot")
    assert not inventory.has_prim("/Tree/AssemblyPartsInstancer", "PointInstancer")
    assert not inventory.contains("/Tree/AssemblyPartsInstancer", 'def Mesh "Twig_01"')


def test_static_assembly_mode_authors_point_instancer_without_skeletal_fields() -> None:
    _, model, diagnostics = load_canonical_model(str(SIMPLE_TREE_01), conversion_mode=ConversionMode.STATIC_ASSEMBLY)
    assert model.prototype_strategy == PrototypeStrategy.INLINE_STATIC_PART
    assert not any(issue.severity == "error" for issue in diagnostics)

    from xml_to_usda.usda_writer import render_usda

    usda = render_usda(
        model,
        diagnostics,
        base_mesh_name="StaticAssembly",
        conversion_mode=ConversionMode.STATIC_ASSEMBLY,
    )
    inventory = UsdaInventory.from_text(usda.text)

    assert 'defaultPrim = "StaticAssembly"' not in usda.text
    assert inventory.has_prim("/StaticAssembly", "Xform")
    assert inventory.has_api_schema("/StaticAssembly", "NaniteAssemblyRootAPI")
    assert inventory.has_attribute("/StaticAssembly", "unreal:naniteAssembly:meshType")
    assert inventory.has_prim("/StaticAssembly/AssemblyPartsInstancer", "PointInstancer")
    assert inventory.has_prim("/StaticAssembly/AssemblyPartsInstancer/Prototypes", "Scope")
    assert inventory.has_prim("/StaticAssembly/AssemblyPartsInstancer/Prototypes/StaticAssembly_BaseMesh", "Xform")
    assert inventory.has_prim("/StaticAssembly/AssemblyPartsInstancer/Prototypes/StaticAssembly_BaseMesh/SM_StaticAssembly_BaseMesh", "Mesh")
    assert inventory.has_prim("/StaticAssembly/AssemblyPartsInstancer/Prototypes/Twig_01", "Xform")
    assert inventory.has_prim("/StaticAssembly/AssemblyPartsInstancer/Prototypes/Twig_01/SM_Twig_01", "Mesh")
    assert inventory.has_prim("/StaticAssembly/AssemblyPartsInstancer/Prototypes/Twig_02", "Xform")
    assert inventory.has_prim("/StaticAssembly/AssemblyPartsInstancer/Prototypes/Twig_02/SM_Twig_02", "Mesh")
    assert not inventory.contains("/StaticAssembly", "rel unreal:naniteAssembly:skeleton = ")
    assert not inventory.contains("/StaticAssembly", "primvars:skel:")
    assert not inventory.contains("/StaticAssembly", "primvars:unreal:naniteAssembly:bindJoints")
    assert not inventory.contains("/StaticAssembly", "primvars:unreal:naniteAssembly:bindJointWeights")


def test_static_assembly_conversion_writes_single_usda_file(tmp_path: Path) -> None:
    output_path = tmp_path / "StaticAssembly.usda"

    result = convert_file(
        str(SIMPLE_TREE_01),
        str(output_path),
        conversion_mode=ConversionMode.STATIC_ASSEMBLY,
    )

    assert result.usda_document is not None
    assert result.usda_document.text is not None
    assert result.output_path == str(output_path)
    assert output_path.exists()
    inventory = UsdaInventory.from_text(result.usda_document.text)

    assert inventory.has_prim("/StaticAssembly", "Xform")
    assert inventory.has_api_schema("/StaticAssembly", "NaniteAssemblyRootAPI")
    assert inventory.has_attribute("/StaticAssembly", "unreal:naniteAssembly:meshType")
    assert inventory.has_prim("/StaticAssembly/AssemblyPartsInstancer", "PointInstancer")
    assert inventory.has_prim("/StaticAssembly/AssemblyPartsInstancer/Prototypes", "Scope")
    assert inventory.has_prim("/StaticAssembly/AssemblyPartsInstancer/Prototypes/StaticAssembly_BaseMesh", "Xform")
    assert inventory.has_prim("/StaticAssembly/AssemblyPartsInstancer/Prototypes/Twig_01", "Xform")
    assert inventory.has_prim("/StaticAssembly/AssemblyPartsInstancer/Prototypes/Twig_02", "Xform")
    assert not inventory.contains("/StaticAssembly", "def SkelRoot")
    assert not inventory.contains("/StaticAssembly", "primvars:skel:")


def test_static_assembly_preserves_fbx_and_unreal_reference_prototypes(tmp_path: Path) -> None:
    payload_path = _write_fbx_json_payload(tmp_path, file_name="spruce_branch.json")
    _, fbx_model, fbx_diagnostics = load_canonical_model(
        str(SIMPLE_TREE_01),
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path=str(payload_path),
            ),
        ),
        conversion_mode=ConversionMode.STATIC_ASSEMBLY,
    )
    from xml_to_usda.usda_writer import render_usda

    fbx_usda = render_usda(
        fbx_model,
        fbx_diagnostics,
        base_mesh_name="StaticAssembly",
        conversion_mode=ConversionMode.STATIC_ASSEMBLY,
    )
    fbx_inventory = UsdaInventory.from_text(fbx_usda.text)

    assert fbx_inventory.has_prim("/StaticAssembly", "Xform")
    assert fbx_inventory.has_prim("/StaticAssembly/AssemblyPartsInstancer", "PointInstancer")
    assert fbx_inventory.has_prim("/StaticAssembly/AssemblyPartsInstancer/Prototypes", "Scope")
    assert fbx_inventory.has_prim("/StaticAssembly/AssemblyPartsInstancer/Prototypes/spruce_branch", "Xform")
    assert fbx_inventory.has_prim("/StaticAssembly/AssemblyPartsInstancer/Prototypes/spruce_branch/SM_spruce_branch", "Mesh")
    assert not fbx_inventory.has_prim("/StaticAssembly/AssemblyPartsInstancer/Prototypes/spruce_branch/PartSkelRoot")

    _, unreal_model, unreal_diagnostics = load_canonical_model(
        str(SIMPLE_TREE_01),
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                mode=PrototypeSourceMode.UNREAL_ASSET,
                asset_path="/Game/TreeParts/SK_Twig01.SK_Twig01",
            ),
        ),
        conversion_mode=ConversionMode.STATIC_ASSEMBLY,
    )
    unreal_usda = render_usda(
        unreal_model,
        unreal_diagnostics,
        base_mesh_name="StaticAssembly",
        conversion_mode=ConversionMode.STATIC_ASSEMBLY,
    )
    unreal_inventory = UsdaInventory.from_text(unreal_usda.text)

    assert unreal_inventory.has_prim("/StaticAssembly", "Xform")
    assert unreal_inventory.has_prim("/StaticAssembly/AssemblyPartsInstancer", "PointInstancer")
    assert unreal_inventory.has_prim("/StaticAssembly/AssemblyPartsInstancer/Prototypes", "Scope")
    assert unreal_inventory.has_prim("/StaticAssembly/AssemblyPartsInstancer/Prototypes/Twig_01", "Xform")
    assert unreal_inventory.has_api_schema("/StaticAssembly/AssemblyPartsInstancer/Prototypes/Twig_01", "NaniteAssemblyExternalRefAPI")
    assert unreal_inventory.has_attribute("/StaticAssembly/AssemblyPartsInstancer/Prototypes/Twig_01", "unreal:naniteAssembly:meshAssetPath")
    assert not unreal_inventory.has_prim("/StaticAssembly/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot")


def test_skeletal_parts_mode_rejects_zero_prototype_models() -> None:
    _, model, _ = load_canonical_model(str(SIMPLE_TREE_01), conversion_mode=ConversionMode.SKELETAL_PARTS)
    broken_model = replace(model, prototypes=(), assembly_parts=())
    diagnostics = validate_model(broken_model, conversion_mode=ConversionMode.SKELETAL_PARTS)

    assert any(issue.code == "missing_prototypes" and issue.severity == "error" for issue in diagnostics)
    from xml_to_usda.usda_writer import render_usda

    with pytest.raises(ValueError, match="missing_prototypes"):
        render_usda(broken_model, diagnostics, conversion_mode=ConversionMode.SKELETAL_PARTS)


def test_referenced_prototype_strategy_is_blocked_for_skeletal_assembly_part_export() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    broken_model = replace(model, prototype_strategy=model.prototype_strategy.REFERENCED_SCOPE)
    diagnostics = validate_model(broken_model)

    assert any(issue.code == "unsupported_prototype_strategy" and issue.severity == "error" for issue in diagnostics)
    from xml_to_usda.usda_writer import render_usda

    with pytest.raises(ValueError, match="unsupported_prototype_strategy"):
        render_usda(broken_model, diagnostics)


def test_skeletal_parts_mode_preserves_fbx_part_names_and_material_bindings(tmp_path: Path) -> None:
    payload_path = _write_fbx_json_payload(tmp_path, file_name="SM_BigBranch_01_HIGH.json")
    _, model, _ = load_canonical_model(
        str(SIMPLE_TREE_01),
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path=str(payload_path),
            ),
        ),
        conversion_mode=ConversionMode.SKELETAL_PARTS,
    )
    parts_only_model = replace(model, base_mesh=None, skeleton=None, assembly_parts=())
    diagnostics = validate_model(parts_only_model, conversion_mode=ConversionMode.SKELETAL_PARTS)
    from xml_to_usda.usda_writer import render_usda

    usda = render_usda(parts_only_model, diagnostics, conversion_mode=ConversionMode.SKELETAL_PARTS)
    inventory = UsdaInventory.from_text(usda.text)

    assert not any(issue.severity == "error" for issue in diagnostics)
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer", "Xform")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes", "Scope")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/SM_BigBranch_01_HIGH", "Xform")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/SM_BigBranch_01_HIGH/PartSkelRoot/SM_BigBranch_01_HIGH", "Mesh")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/SM_BigBranch_01_HIGH/PartSkelRoot/SM_BigBranch_01_HIGH_Skeleton", "Skeleton")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/SM_BigBranch_01_HIGH/PartSkelRoot/SM_BigBranch_01_HIGH_Animation", "SkelAnimation")
    assert inventory.has_relationship("/Tree/AssemblyPartsInstancer/Prototypes/SM_BigBranch_01_HIGH/PartSkelRoot/SM_BigBranch_01_HIGH_Skeleton", "skel:animationSource")
    assert inventory.has_relationship("/Tree/AssemblyPartsInstancer/Prototypes/SM_BigBranch_01_HIGH/PartSkelRoot/SM_BigBranch_01_HIGH", "skel:skeleton")
    assert inventory.has_attribute("/Tree/AssemblyPartsInstancer/Prototypes/SM_BigBranch_01_HIGH/PartSkelRoot/SM_BigBranch_01_HIGH", "subsetFamily:materialBind:familyType")
    assert inventory.has_prim(
        "/Tree/AssemblyPartsInstancer/Prototypes/SM_BigBranch_01_HIGH/PartSkelRoot/SM_BigBranch_01_HIGH/Material_1_1",
        "GeomSubset",
    )
    assert inventory.has_prim(
        "/Tree/AssemblyPartsInstancer/Prototypes/SM_BigBranch_01_HIGH/PartSkelRoot/SM_BigBranch_01_HIGH/Material_2_2",
        "GeomSubset",
    )
    assert inventory.has_relationship(
        "/Tree/AssemblyPartsInstancer/Prototypes/SM_BigBranch_01_HIGH/PartSkelRoot/SM_BigBranch_01_HIGH/Material_1_1",
        "material:binding",
    )
    assert inventory.has_relationship(
        "/Tree/AssemblyPartsInstancer/Prototypes/SM_BigBranch_01_HIGH/PartSkelRoot/SM_BigBranch_01_HIGH/Material_2_2",
        "material:binding",
    )


def test_skeletal_parts_single_prototype_authors_asset_info_name_hints() -> None:
    _, model, _ = load_canonical_model(str(SIMPLE_TREE_01), conversion_mode=ConversionMode.SKELETAL_PARTS)
    single_prototype_model = replace(
        model,
        base_mesh=None,
        skeleton=None,
        assembly_parts=(),
        prototypes=(model.prototypes[0],),
    )
    diagnostics = validate_model(single_prototype_model, conversion_mode=ConversionMode.SKELETAL_PARTS)
    from xml_to_usda.usda_writer import render_usda

    usda = render_usda(single_prototype_model, diagnostics, conversion_mode=ConversionMode.SKELETAL_PARTS)
    inventory = UsdaInventory.from_text(usda.text)

    assert not any(issue.severity == "error" for issue in diagnostics)
    assert inventory.has_prim("/Twig_01", "Xform")
    assert inventory.has_prim("/Twig_01/PartSkelRoot", "SkelRoot")
    assert inventory.has_prim("/Twig_01/PartSkelRoot/Twig_01", "Mesh")
    assert inventory.has_prim("/Twig_01/PartSkelRoot/PartSkeleton", "Skeleton")
    assert inventory.has_prim("/Twig_01/PartSkelRoot/PartAnimation", "SkelAnimation")
    assert inventory.has_attribute("/Twig_01", "assetInfo")
    assert inventory.has_attribute("/Twig_01/PartSkelRoot/Twig_01", "primvars:skel:skinningMethod")
    assert inventory.has_attribute("/Twig_01/PartSkelRoot/Twig_01", "skel:joints")
    assert inventory.has_relationship("/Twig_01/PartSkelRoot/Twig_01", "skel:skeleton")
    assert 'uniform token[] jointNames = ["Twig_01"]' in usda.text
    assert 'append rel skel:animationSource = </Twig_01/PartSkelRoot/PartAnimation>' in usda.text


def test_skeletal_parts_conversion_writes_one_usda_per_prototype(tmp_path: Path) -> None:
    output_path = tmp_path / "SimpleTree_01_Branches.usda"

    result = convert_file(
        str(SIMPLE_TREE_01),
        str(output_path),
        conversion_mode=ConversionMode.SKELETAL_PARTS,
    )

    output_directory = tmp_path / "SimpleTree_01_Branches"
    twig_one = output_directory / "Twig_01.usda"
    twig_two = output_directory / "Twig_02.usda"

    assert result.usda_document is not None
    assert result.usda_document.text is None
    assert result.output_path == str(output_directory)
    assert output_directory.is_dir()
    assert twig_one.exists()
    assert twig_two.exists()

    twig_one_text = twig_one.read_text(encoding="utf-8")
    twig_one_inventory = UsdaInventory.from_text(twig_one_text)

    assert twig_one_inventory.has_prim("/Twig_01", "Xform")
    assert twig_one_inventory.has_prim("/Twig_01/PartSkelRoot", "SkelRoot")
    assert twig_one_inventory.has_prim("/Twig_01/PartSkelRoot/Twig_01", "Mesh")
    assert twig_one_inventory.has_prim("/Twig_01/PartSkelRoot/PartSkeleton", "Skeleton")
    assert twig_one_inventory.has_prim("/Twig_01/PartSkelRoot/PartAnimation", "SkelAnimation")
    assert twig_one_inventory.has_attribute("/Twig_01", "assetInfo")
    assert twig_one_inventory.has_attribute("/Twig_01/PartSkelRoot/Twig_01", "primvars:skel:skinningMethod")
    assert twig_one_inventory.has_relationship("/Twig_01/PartSkelRoot/Twig_01", "skel:skeleton")
    assert 'append rel skel:animationSource = </Twig_01/PartSkelRoot/PartAnimation>' in twig_one_text


def test_skeletal_parts_conversion_uses_fbx_stem_for_split_file_name_and_asset_name(tmp_path: Path) -> None:
    payload_path = _write_fbx_json_payload(tmp_path, file_name="spruce_branch.json")
    output_path = tmp_path / "SpruceParts.usda"

    result = convert_file(
        str(SIMPLE_TREE_01),
        str(output_path),
        conversion_mode=ConversionMode.SKELETAL_PARTS,
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path=str(payload_path),
            ),
        ),
    )

    output_directory = tmp_path / "SpruceParts"
    part_path = output_directory / "spruce_branch.usda"

    assert result.usda_document is not None
    assert part_path.exists()

    part_text = part_path.read_text(encoding="utf-8")
    part_inventory = UsdaInventory.from_text(part_text)

    assert part_inventory.has_prim("/spruce_branch", "Xform")
    assert part_inventory.has_prim("/spruce_branch/PartSkelRoot/spruce_branch", "Mesh")
    assert part_inventory.has_prim("/spruce_branch/PartSkelRoot/spruce_branch_Skeleton", "Skeleton")
    assert part_inventory.has_prim("/spruce_branch/PartSkelRoot/spruce_branch_Animation", "SkelAnimation")
    assert part_inventory.has_prim("/spruce_branch/PartSkelRoot/spruce_branch/Material_1_1", "GeomSubset")
    assert part_inventory.has_prim("/spruce_branch/PartSkelRoot/spruce_branch/Material_2_2", "GeomSubset")
    assert part_inventory.contains(
        "/spruce_branch/PartSkelRoot/spruce_branch",
        'append rel skel:skeleton = </spruce_branch/PartSkelRoot/spruce_branch_Skeleton>',
    )
    assert 'append rel skel:animationSource = </spruce_branch/PartSkelRoot/spruce_branch_Animation>' in part_text
    assert part_inventory.has_relationship("/spruce_branch/PartSkelRoot/spruce_branch/Material_1_1", "material:binding")
    assert part_inventory.has_relationship("/spruce_branch/PartSkelRoot/spruce_branch/Material_2_2", "material:binding")


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
    report = inspect_xml(read_source_xml(LEAFREFS_ON_BRANCH_LEVELS))
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
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                mode=PrototypeSourceMode.UNREAL_ASSET,
                asset_path="/Game/TreeParts/SK_Twig01.SK_Twig01",
            ),
        ),
    )
    _, model, _diagnostics = load_canonical_model(
        str(SIMPLE_TREE_01),
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                mode=PrototypeSourceMode.UNREAL_ASSET,
                asset_path="/Game/TreeParts/SK_Twig01.SK_Twig01",
            ),
        ),
    )

    assert result.usda_document is not None
    prototype = next(prototype for prototype in model.prototypes if prototype.source_key == "Mesh_1")
    assert prototype.resolution_mode == PrototypeResolutionMode.EXTERNAL_ASSET
    assert prototype.mesh is None
    inventory = UsdaInventory.from_text(result.usda_document.text)
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01", "Xform")
    assert inventory.has_api_schema("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01", "NaniteAssemblyExternalRefAPI")
    assert inventory.has_attribute("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01", "unreal:naniteAssembly:meshAssetPath")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_02", "Xform")
    assert inventory.has_relationship("/Tree/AssemblyPartsInstancer/Prototypes/Twig_02/PartSkelRoot/Twig_02", "skel:skeleton")


def test_existing_part_mesh_override_accepts_xml_mesh_names_in_mixed_mode(tmp_path: Path) -> None:
    result = convert_file(
        str(SIMPLE_TREE_01),
        str(tmp_path / "external_parts_by_name.usda"),
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Twig_01",
                mode=PrototypeSourceMode.UNREAL_ASSET,
                asset_path="/Game/TreeParts/SK_Twig01.SK_Twig01",
            ),
        ),
    )
    _, model, _diagnostics = load_canonical_model(
        str(SIMPLE_TREE_01),
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Twig_01",
                mode=PrototypeSourceMode.UNREAL_ASSET,
                asset_path="/Game/TreeParts/SK_Twig01.SK_Twig01",
            ),
        ),
    )

    assert result.usda_document is not None
    prototype = next(prototype for prototype in model.prototypes if prototype.source_key == "Mesh_1")
    assert prototype.resolution_mode == PrototypeResolutionMode.EXTERNAL_ASSET
    assert prototype.mesh is None
    inventory = UsdaInventory.from_text(result.usda_document.text)
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01", "Xform")
    assert inventory.has_api_schema("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01", "NaniteAssemblyExternalRefAPI")
    assert inventory.has_attribute("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01", "unreal:naniteAssembly:meshAssetPath")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_02", "Xform")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_02/PartSkelRoot", "SkelRoot")
    assert not inventory.has_attribute("/Tree/AssemblyPartsInstancer/Prototypes/Twig_02", "unreal:naniteAssembly:meshAssetPath")
