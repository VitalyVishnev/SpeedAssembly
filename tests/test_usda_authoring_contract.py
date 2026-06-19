from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from xml_to_usda.canonical_loader import load_canonical_model, load_resolved_assembly_model
from xml_to_usda.models import (
    ConversionMode,
    ExportMetadata,
    Joint,
    MaterialSpec,
    Matrix4d,
    MeshData,
    MeshSection,
    TreeAsset,
    UdimMaterialSetting,
    UdimMode,
    Vector2,
    Vector3,
)
from xml_to_usda.normalizer import normalize_to_canonical
from xml_to_usda.pipeline import convert_file
from xml_to_usda.source_analysis import discover_source_materials
from xml_to_usda.udim_settings import load_udim_material_settings_from_json
from xml_to_usda.usda_authoring import author_usda_text
from xml_to_usda.usda_writer import render_usda
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
LEAFREFS_ON_BRANCH_LEVELS = DATA_DIR / "leafrefs_on_branch_levels.xml"


def _slice_between(text: str, start: str, end: str) -> str:
    start_index = text.index(start)
    end_index = text.index(end, start_index)
    return text[start_index:end_index]


def _test_runtime_paths(tmp_path: Path):
    from xml_to_usda.runtime_paths import resolve_runtime_paths

    return resolve_runtime_paths(
        settings_dir=tmp_path / "settings",
        settings_path=tmp_path / "settings" / "gui_settings.json",
        cache_root=tmp_path / "runtime_cache",
    )


def test_usda_output_contains_ue_first_structure() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)
    usda = render_usda(model, diagnostics)
    inventory = UsdaInventory.from_text(usda.text)

    assert inventory.has_prim("/Tree", "Xform")
    assert inventory.has_api_schema("/Tree", "NaniteAssemblyRootAPI")
    assert inventory.has_attribute("/Tree", "kind")
    assert inventory.has_relationship("/Tree", "unreal:naniteAssembly:skeleton")

    assert inventory.has_prim("/Tree/Materials", "Scope")
    assert inventory.has_prim("/Tree/Materials/Material_1_1", "Material")
    assert inventory.has_prim("/Tree/Materials/Material_2_2", "Material")
    assert inventory.has_attribute("/Tree/Materials/Material_1_1", "outputs:surface.connect")
    assert inventory.has_attribute("/Tree/Materials/Material_2_2", "outputs:surface.connect")
    assert inventory.has_attribute("/Tree/Materials/Material_1_1/Material_1_1_shader", "info:id")

    assert inventory.has_prim("/Tree/BaseTreeSkelRoot", "SkelRoot")
    assert inventory.has_prim("/Tree/BaseTreeSkelRoot/BaseTreeAnimation", "SkelAnimation")
    assert inventory.has_prim("/Tree/BaseTreeSkelRoot/MainSkeleton", "Skeleton")
    assert inventory.has_prim("/Tree/BaseTreeSkelRoot/BaseTreeMesh", "Mesh")
    assert inventory.has_api_schema("/Tree/BaseTreeSkelRoot/BaseTreeMesh", "SkelBindingAPI")
    assert inventory.has_attribute("/Tree/BaseTreeSkelRoot/BaseTreeMesh", "primvars:skel:geomBindTransform")
    assert inventory.has_attribute("/Tree/BaseTreeSkelRoot/BaseTreeMesh", "primvars:skel:jointIndices")
    assert inventory.has_attribute("/Tree/BaseTreeSkelRoot/BaseTreeMesh", "primvars:skel:jointWeights")
    assert inventory.has_attribute("/Tree/BaseTreeSkelRoot/BaseTreeMesh", "primvars:skel:skinningMethod")
    assert inventory.has_attribute("/Tree/BaseTreeSkelRoot/MainSkeleton", "bindTransforms")
    assert inventory.has_attribute("/Tree/BaseTreeSkelRoot/MainSkeleton", "restTransforms")
    assert inventory.has_attribute("/Tree/BaseTreeSkelRoot/MainSkeleton", "purpose")
    assert inventory.has_attribute("/Tree/BaseTreeSkelRoot/MainSkeleton", "visibility")
    assert inventory.has_attribute("/Tree/BaseTreeSkelRoot/BaseTreeMesh", "orientation")
    assert inventory.has_attribute("/Tree/BaseTreeSkelRoot/BaseTreeMesh", "interpolation")
    assert inventory.has_attribute("/Tree/BaseTreeSkelRoot/BaseTreeMesh", "primvars:st")
    assert inventory.contains("/Tree/BaseTreeSkelRoot", "primvars:boneCapture_pCaptPath")
    assert inventory.contains("/Tree/BaseTreeSkelRoot", "primvars:ueJointNames")
    assert inventory.contains("/Tree/BaseTreeSkelRoot", "primvars:localtransform")

    assert inventory.has_prim("/Tree/AssemblyPartsInstancer", "PointInstancer")
    assert inventory.has_api_schema("/Tree/AssemblyPartsInstancer", "NaniteAssemblySkelBindingAPI")
    assert inventory.has_attribute("/Tree/AssemblyPartsInstancer", "primvars:unreal:naniteAssembly:bindJoints")
    assert inventory.has_attribute("/Tree/AssemblyPartsInstancer", "primvars:unreal:naniteAssembly:bindJointWeights")
    assert inventory.has_attribute("/Tree/AssemblyPartsInstancer", "elementSize")
    assert inventory.has_attribute("/Tree/AssemblyPartsInstancer", "orientations")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes", "Scope")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01", "Xform")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_02", "Xform")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot", "SkelRoot")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_02/PartSkelRoot", "SkelRoot")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/PartSkeleton", "Skeleton")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_02/PartSkelRoot/PartSkeleton", "Skeleton")
    assert not inventory.contains("/Tree/AssemblyPartsInstancer", '"Tree_point_')


def test_material_bindings_stay_on_mesh_prims_only() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)
    usda = render_usda(model, diagnostics)
    inventory = UsdaInventory.from_text(usda.text)

    assert not inventory.direct_contains("/Tree", "material:binding")
    assert not inventory.direct_contains("/Tree/AssemblyPartsInstancer", "material:binding")


def test_inline_prototypes_are_authored_under_instancer_scope() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)
    usda = render_usda(model, diagnostics)
    inventory = UsdaInventory.from_text(usda.text)

    assert not inventory.contains("/Tree", 'def Xform "PrototypeLibrary"')
    assert not inventory.contains("/Tree", 'append references = </Tree/PrototypeLibrary/Mesh_1>')
    assert not inventory.contains("/Tree", 'append references = </Tree/PrototypeLibrary/Mesh_2>')
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes", "Scope")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01", "Xform")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_02", "Xform")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot", "SkelRoot")


def test_ue_schema_contract_matches_current_writer_contract() -> None:
    from xml_to_usda.ue_schema import DEFAULT_UE_SCHEMA_CONTRACT

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
    inventory = UsdaInventory.from_text(usda.text)

    assert inventory.has_prim("/Tree/AssemblyPartsInstancer", "PointInstancer")
    assert inventory.has_attribute("/Tree/AssemblyPartsInstancer", "primvars:unreal:naniteAssembly:bindJoints")
    assert inventory.has_attribute("/Tree/AssemblyPartsInstancer", "primvars:unreal:naniteAssembly:bindJointWeights")
    assert inventory.has_attribute("/Tree/AssemblyPartsInstancer", "elementSize")
    assert inventory.has_attribute("/Tree/AssemblyPartsInstancer", "orientations")
    assert inventory.direct_contains("/Tree/AssemblyPartsInstancer", "elementSize = 2")
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


def test_realistic_multi_material_part_mesh_authors_geom_subsets() -> None:
    document = read_source_xml(LEAFREFS_ON_BRANCH_LEVELS)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)
    usda = render_usda(model, diagnostics)
    inventory = UsdaInventory.from_text(usda.text)

    multi_material_prototype = next(prototype for prototype in model.prototypes if prototype.source_key == "Mesh_2")
    assert multi_material_prototype.mesh is not None
    assert {section.material_id for section in multi_material_prototype.mesh.sections} == {1, 2}
    assert inventory.has_prim(
        "/Tree/AssemblyPartsInstancer/Prototypes/TwigLeafCluster_B/PartSkelRoot/TwigLeafCluster_B/Material_1_1",
        "GeomSubset",
    )
    assert inventory.has_prim(
        "/Tree/AssemblyPartsInstancer/Prototypes/TwigLeafCluster_B/PartSkelRoot/TwigLeafCluster_B/Material_2_2",
        "GeomSubset",
    )
    assert inventory.has_attribute(
        "/Tree/AssemblyPartsInstancer/Prototypes/TwigLeafCluster_B/PartSkelRoot/TwigLeafCluster_B",
        "subsetFamily:materialBind:familyType",
    )


def test_speedtree_cap_like_object_is_authored_as_base_mesh_material_sections(tmp_path: Path) -> None:
    source_path = tmp_path / "cap_like_object.xml"
    source_path.write_text(
        """
        <SpeedTreeRaw>
            <Materials>
                <Material ID="1" Name="Bark" />
                <Material ID="0" Name="CapCut" />
                <Material ID="2" Name="TwigOnly" />
            </Materials>
            <Bones>
                <Bone ID="20" ParentID="-1" StartX="0" StartY="0" StartZ="0" Generator="Group_0" />
            </Bones>
            <Objects>
                <Object ID="1" Name="CapLike" AbsX="0" AbsY="0" AbsZ="0" RelX="0" RelY="0" RelZ="0">
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
                    <Triangles Material="1" Count="1">
                        <PointIndices>0 1 2</PointIndices>
                        <VertexIndices>0 1 2</VertexIndices>
                    </Triangles>
                    <Triangles Material="0" Count="1">
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
    model = normalize_to_canonical(document, inspect_xml(document))
    diagnostics = validate_model(model)
    usda = render_usda(model, diagnostics)
    inventory = UsdaInventory.from_text(usda.text)

    assert model.base_mesh is not None
    assert model.base_mesh.sections == (
        MeshSection(material_id=0, face_indices=(1,)),
        MeshSection(material_id=1, face_indices=(0,)),
    )
    assert [material.source_id for material in discover_source_materials(str(source_path))] == [1, 0]
    assert not any(issue.severity == "error" for issue in diagnostics)
    assert inventory.has_attribute("/Tree/BaseTreeSkelRoot/BaseTreeMesh", "subsetFamily:materialBind:familyType")
    assert inventory.has_prim("/Tree/BaseTreeSkelRoot/BaseTreeMesh/Material_0_0", "GeomSubset")
    assert inventory.has_prim("/Tree/BaseTreeSkelRoot/BaseTreeMesh/Material_1_1", "GeomSubset")
    assert not inventory.has_prim("/Tree/BaseTreeSkelRoot/BaseTreeMesh/Material_2_2", "GeomSubset")


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
            MaterialSpec(source_id=0, name="Cap_Mat", source_material_ids=(0,)),
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
    inventory = UsdaInventory.from_text(usda.text)

    assert inventory.has_prim("/Tree/MultiRootFern_Geo", "SkelRoot")
    assert inventory.has_prim("/Tree/MultiRootFern_Geo/MultiRootFern_Skeleton", "Skeleton")
    assert inventory.has_prim("/Tree/MultiRootFern_Geo/animation", "SkelAnimation")
    assert inventory.has_attribute("/Tree/MultiRootFern_Geo/MultiRootFern_Skeleton", "joints")
    assert inventory.has_attribute("/Tree/MultiRootFern_Geo/MultiRootFern_Skeleton", "jointNames")
    assert inventory.has_relationship("/Tree/MultiRootFern_Geo/MultiRootFern", "skel:skeleton")
    assert inventory.has_relationship("/Tree/MultiRootFern_Geo/MultiRootFern_Skeleton", "skel:animationSource")


def test_inline_part_skeleton_uses_prototype_name_for_single_joint() -> None:
    result = convert_file(str(SIMPLE_TREE_01), output_path=None)
    inventory = UsdaInventory.from_text(result.usda_document.text)

    assert result.usda_document is not None
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01", "Xform")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot", "SkelRoot")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/Twig_01", "Mesh")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/PartSkeleton", "Skeleton")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/PartAnimation", "SkelAnimation")
    assert inventory.has_attribute("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/Twig_01", "primvars:skel:skinningMethod")
    assert inventory.has_relationship("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/Twig_01", "skel:skeleton")
    assert inventory.has_relationship("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/PartSkeleton", "skel:animationSource")
    assert inventory.contains(
        "/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/PartSkeleton",
        'uniform token[] joints = ["Twig_01"]',
    )
    assert inventory.contains(
        "/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/PartSkeleton",
        'uniform token[] jointNames = ["Twig_01"]',
    )


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
            MaterialSpec(source_id=0, name="Cap_Mat"),
            MaterialSpec(source_id=1, name="Default_Mat"),
            MaterialSpec(source_id=2, name="Twigs_Mat"),
        ),
        prototypes=(replace(prototype, mesh=synthetic_mesh),) + model.prototypes[1:],
    )

    diagnostics = validate_model(synthetic_model)
    usda = render_usda(synthetic_model, diagnostics)
    inventory = UsdaInventory.from_text(usda.text)

    assert inventory.has_attribute("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/Twig_01", "subsetFamily:materialBind:familyType")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/Twig_01/Material_1_1", "GeomSubset")
    assert inventory.has_prim("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/Twig_01/Material_2_2", "GeomSubset")
    assert inventory.has_attribute("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/Twig_01/Material_1_1", "familyName")
    assert inventory.has_attribute("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/Twig_01/Material_1_1", "elementType")
    assert inventory.has_relationship("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/Twig_01/Material_1_1", "material:binding")
    assert inventory.has_relationship("/Tree/AssemblyPartsInstancer/Prototypes/Twig_01/PartSkelRoot/Twig_01/Material_2_2", "material:binding")
