from __future__ import annotations

from dataclasses import replace
import json
from enum import Enum
from pathlib import Path

import pytest

from xml_to_usda.canonical_loader import load_canonical_model, load_resolved_assembly_model, load_source_tree_model
from xml_to_usda.asset_paths import normalize_unreal_asset_path
from xml_to_usda.fbx_adapter import FbxVertexColorReadError, _read_vertex_color
from xml_to_usda.models import (
    BaseMaterialOverride,
    Color4,
    ExportMetadata,
    FbxMaterialMode,
    FbxMaterialSlotOverride,
    MaterialPolicy,
    MaterialSpec,
    MeshData,
    MeshSection,
    PrototypeSourceConfig,
    PrototypeSourceMode,
    TreeAsset,
    UdimMaterialSetting,
    UdimMode,
    Vector2,
    Vector3,
)
from xml_to_usda.normalizer import _resolve_prototype_material_sections, _vertex_color_material_sections, normalize_to_canonical
from xml_to_usda.material_resolver import apply_material_policy
from xml_to_usda.pipeline import _apply_material_policy, convert_file, discover_source_materials
from xml_to_usda.validator import validate_model
from xml_to_usda.udim_resolver import apply_udim_settings_to_mesh_data
from xml_to_usda.xml_reader import inspect_xml, read_source_xml
from xml_to_usda.udim_settings import load_udim_material_settings_from_json


SIMPLE_TREE_01 = (
    Path(__file__).resolve().parents[1]
    / "samples"
    / "speedtree"
    / "simple_tree"
    / "variants"
    / "SimpleTree_01.xml"
)


def _test_runtime_paths(tmp_path: Path):
    from xml_to_usda.runtime_paths import resolve_runtime_paths

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
    import json

    payload = {
        "point_components": [
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
        ],
        "face_vertex_counts": [3, 3],
        "face_vertex_indices": [0, 1, 2, 3, 4, 5],
        "uv_components": [
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            1.0,
        ],
    }
    if color_components is not None:
        payload["vertex_color_components"] = color_components
    elif include_vertex_colors:
        payload["vertex_color_components"] = [
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            0.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
        ]
    if fbx_material_slots is not None:
        payload["fbx_material_slots"] = fbx_material_slots
    if sections is not None:
        payload["sections"] = sections
    payload_path = tmp_path / file_name
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    return payload_path


def _write_shifted_material_sample(tmp_path: Path, material_id_map: dict[int, int]) -> Path:
    import xml.etree.ElementTree as ET

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


def test_discover_source_materials_ignores_prototype_only_material_slots() -> None:
    materials = discover_source_materials(str(SIMPLE_TREE_01))

    assert materials == (
        BaseMaterialOverride(
            source_id=1,
            source_name="Bark_Mat",
            ue_asset_path=None,
        ),
        BaseMaterialOverride(
            source_id=0,
            source_name="Default_Mat",
            ue_asset_path=None,
        ),
    )


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


def test_source_role_policy_does_not_require_fixed_material_ids() -> None:
    _report, source_model, _diagnostics = load_source_tree_model(str(SIMPLE_TREE_01))
    broken_model = replace(
        source_model,
        materials=(MaterialSpec(source_id=1, name="Default_Mat", source_material_ids=(1,)),),
        metadata=replace(source_model.metadata, material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES),
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


def test_source_material_policy_preserves_shifted_source_material_ids(tmp_path: Path) -> None:
    shifted_sample = _write_shifted_material_sample(tmp_path, {1: 5, 2: 6})
    runtime_paths = _test_runtime_paths(tmp_path)

    result = convert_file(str(shifted_sample), str(tmp_path / "source_materials.usda"), runtime_paths=runtime_paths)
    _, model, diagnostics = load_canonical_model(str(shifted_sample))

    assert result.usda_document is not None
    assert {material.source_id for material in model.materials} == {0, 5, 6}
    assert {material.source_material_ids for material in model.materials} == {(0,), (5,), (6,)}
    assert model.base_mesh is not None
    assert {section.material_id for section in model.base_mesh.sections} == {0, 5}
    assert all(
        prototype.mesh is None or {section.material_id for section in prototype.mesh.sections} <= {0, 5, 6}
        for prototype in model.prototypes
    )
    assert not any(
        issue.severity == "error" and issue.code == "missing_material_definition"
        for issue in diagnostics
    )


def test_source_role_policy_remaps_shifted_source_material_ids_to_role_materials(tmp_path: Path) -> None:
    shifted_sample = _write_shifted_material_sample(tmp_path, {1: 5, 2: 6})
    runtime_paths = _test_runtime_paths(tmp_path)

    result = convert_file(
        str(shifted_sample),
        str(tmp_path / "legacy_shifted.usda"),
        material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
        runtime_paths=runtime_paths,
    )
    _, model, diagnostics = load_canonical_model(
        str(shifted_sample),
        material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
    )

    assert result.usda_document is not None
    assert {material.source_id for material in model.materials} == {1, 2}
    assert {material.source_material_ids for material in model.materials} == {(0, 5), (6,)}
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
    assert {material.source_material_ids for material in model.materials} == {(0, 5), (6,)}
    assert prototype.geometry_payload is not None
    assert {section.material_id for section in prototype.geometry_payload.sections} == {1}
    assert not any(
        issue.severity == "error" and issue.code == "missing_material_definition"
        for issue in diagnostics
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
    assert {section.material_id for section in prototype_two.mesh.sections} == {0}


def test_vertex_color_split_policy_maps_white_and_nonwhite_for_base_and_prototypes() -> None:
    model = load_canonical_model(str(SIMPLE_TREE_01))[1]
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
            Color4(0.0, 0.0, 0.0),
            Color4(0.0, 0.0, 0.0),
            Color4(0.0, 0.0, 0.0),
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
    model = load_canonical_model(str(SIMPLE_TREE_01))[1]
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

    resolved = _resolve_prototype_material_sections(synthetic_mesh, "Mesh_1", {2: 1}, {1, 2}, [])

    assert resolved.sections == (
        MeshSection(material_id=1, face_indices=(1,)),
        MeshSection(material_id=2, face_indices=(0,)),
    )


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


def test_explicit_part_material_contract_activates_for_udim_only_xml_mesh_rows() -> None:
    _, source_model, _ = load_canonical_model(str(SIMPLE_TREE_01))
    source_prototype = next(prototype for prototype in source_model.prototypes if prototype.source_key == "Mesh_1")
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
            Color4(0.0, 0.0, 0.0),
            Color4(0.0, 0.0, 0.0),
            Color4(0.0, 0.0, 0.0),
        ),
        sections=(MeshSection(material_id=9, face_indices=(0, 1)),),
        skel_joint_indices=(0, 0, 0, 0, 0, 0),
        skel_joint_weights=(1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
        skel_element_size=1,
    )
    udim_prototype = replace(
        source_prototype,
        mesh=synthetic_mesh,
        source_mode=PrototypeSourceMode.XML_MESH,
        fbx_material_mode=FbxMaterialMode.VERTEX_COLOR_SPLIT,
        single_material_path=None,
        single_material_udim_mode=UdimMode.OFF,
        black_material_path=None,
        black_material_udim_mode=UdimMode.WRITE_SECONDARY_UV_OFFSET,
        black_material_udim_id=1028,
        white_material_path=None,
        white_material_udim_mode=UdimMode.SHIFT_PRIMARY_UV,
        white_material_udim_id=1003,
        fbx_material_slot_overrides=(),
    )
    model = replace(source_model, prototypes=(udim_prototype, *source_model.prototypes[1:]))

    resolved_model = apply_material_policy(
        model,
        material_policy=MaterialPolicy.SOURCE_MATERIALS,
        bark_material_path=None,
        leaves_material_path=None,
        single_material_path=None,
        normalize_asset_path=normalize_unreal_asset_path,
        explicit_part_material_contract=True,
    )

    black_material = next(material for material in resolved_model.materials if material.name == f"{source_prototype.identity.prim_name}_Black")
    white_material = next(material for material in resolved_model.materials if material.name == f"{source_prototype.identity.prim_name}_White")
    resolved_prototype = next(prototype for prototype in resolved_model.prototypes if prototype.source_key == "Mesh_1")

    assert len(resolved_model.materials) == len(source_model.materials) + 2
    assert {black_material.source_id, white_material.source_id} == {
        section.material_id for section in resolved_prototype.mesh.sections
    }


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


def test_udim_settings_keep_input_order_for_the_same_material() -> None:
    mesh = MeshData(
        name="OrderSensitiveMesh",
        points=(Vector3(0.0, 0.0, 0.0), Vector3(1.0, 0.0, 0.0), Vector3(0.0, 1.0, 0.0)),
        face_vertex_counts=(3,),
        face_vertex_indices=(0, 1, 2),
        uv_coords=(Vector2(0.0, 0.0), Vector2(1.0, 0.0), Vector2(0.0, 1.0)),
        sections=(MeshSection(material_id=1, face_indices=(0,)),),
    )

    with pytest.raises(ValueError, match="multiple active UDIM settings for material id 1"):
        apply_udim_settings_to_mesh_data(
            mesh,
            (
                UdimMaterialSetting(material_id=1, mode=UdimMode.SHIFT_PRIMARY_UV, udim_id=1003),
                UdimMaterialSetting(material_id=1, mode=UdimMode.SHIFT_PRIMARY_UV, udim_id=1004),
            ),
        )


def test_udim_primary_shift_moves_only_selected_resolved_material_uvs() -> None:
    _, baseline = load_resolved_assembly_model(str(SIMPLE_TREE_01))
    _, resolved = load_resolved_assembly_model(
        str(SIMPLE_TREE_01),
        udim_material_settings=(
            UdimMaterialSetting(
                material_id=1,
                mode=UdimMode.SHIFT_PRIMARY_UV,
                udim_id=1003,
            ),
        ),
    )

    baseline_mesh = baseline.authoring_model.base_mesh
    resolved_mesh = resolved.authoring_model.base_mesh

    assert baseline_mesh is not None
    assert resolved_mesh is not None
    assert baseline_mesh.sections == resolved_mesh.sections
    assert len(baseline_mesh.uv_coords) == len(resolved_mesh.uv_coords)

    face_ranges = []
    cursor = 0
    for face_count in baseline_mesh.face_vertex_counts:
        face_ranges.append((cursor, cursor + face_count))
        cursor += face_count
    shifted_faces = {
        face_index
        for section in baseline_mesh.sections
        if section.material_id == 1
        for face_index in section.face_indices
    }
    shifted_slots = {
        slot_index
        for face_index in shifted_faces
        for slot_index in range(*face_ranges[face_index])
    }

    for slot_index, (before, after) in enumerate(zip(baseline_mesh.uv_coords, resolved_mesh.uv_coords, strict=True)):
        expected_x = before.x + 2.0 if slot_index in shifted_slots else before.x
        assert after.x == pytest.approx(expected_x)
        assert after.y == pytest.approx(before.y)


def test_udim_secondary_mode_writes_offset_without_changing_primary_uvs(tmp_path: Path) -> None:
    _, baseline = load_resolved_assembly_model(str(SIMPLE_TREE_01))
    result = convert_file(
        str(SIMPLE_TREE_01),
        str(tmp_path / "tree.usda"),
        udim_material_settings=(
            UdimMaterialSetting(
                material_id=1,
                mode=UdimMode.WRITE_SECONDARY_UV_OFFSET,
                udim_id=1003,
            ),
        ),
        runtime_paths=_test_runtime_paths(tmp_path),
    )
    _, resolved = load_resolved_assembly_model(
        str(SIMPLE_TREE_01),
        udim_material_settings=(
            UdimMaterialSetting(
                material_id=1,
                mode=UdimMode.WRITE_SECONDARY_UV_OFFSET,
                udim_id=1003,
            ),
        ),
    )

    assert result.usda_document is not None
    assert "texCoord2f[] primvars:st1 = [" in result.usda_document.text
    assert "(2.5, 0.5)" in result.usda_document.text
    assert baseline.authoring_model.base_mesh is not None
    assert resolved.authoring_model.base_mesh is not None
    assert resolved.authoring_model.base_mesh.uv_coords == baseline.authoring_model.base_mesh.uv_coords
    assert resolved.authoring_model.base_mesh.secondary_uv_coords
    assert resolved.authoring_model.base_mesh.secondary_uv_coords[0].x == pytest.approx(2.5)
    assert resolved.authoring_model.base_mesh.secondary_uv_coords[0].y == pytest.approx(0.5)


def test_udim_secondary_mode_defaults_untouched_material_faces_to_first_udim() -> None:
    mesh = MeshData(
        name="TwoMaterialMesh",
        points=(Vector3(0.0, 0.0, 0.0), Vector3(1.0, 0.0, 0.0), Vector3(0.0, 1.0, 0.0)),
        face_vertex_counts=(3, 3),
        face_vertex_indices=(0, 1, 2, 0, 2, 1),
        uv_coords=(
            Vector2(0.0, 0.0),
            Vector2(1.0, 0.0),
            Vector2(0.0, 1.0),
            Vector2(0.0, 0.0),
            Vector2(0.0, 1.0),
            Vector2(1.0, 0.0),
        ),
        sections=(
            MeshSection(material_id=1, face_indices=(0,)),
            MeshSection(material_id=2, face_indices=(1,)),
        ),
    )
    resolved = apply_udim_settings_to_mesh_data(
        mesh,
        (
            UdimMaterialSetting(
                material_id=1,
                mode=UdimMode.WRITE_SECONDARY_UV_OFFSET,
                udim_id=1003,
            ),
        ),
        label="Base Skeletal Tree",
    )

    assert resolved is not None
    assert len(resolved.secondary_uv_coords) == len(mesh.uv_coords)
    assert [(uv.x, uv.y) for uv in resolved.secondary_uv_coords[:3]] == pytest.approx(
        [(2.5, 0.5), (2.5, 0.5), (2.5, 0.5)]
    )
    assert [(uv.x, uv.y) for uv in resolved.secondary_uv_coords[3:]] == pytest.approx(
        [(0.5, 0.5), (0.5, 0.5), (0.5, 0.5)]
    )


def test_udim_secondary_mode_overwrites_existing_secondary_uvs_with_default_fill() -> None:
    mesh = MeshData(
        name="TwoMaterialMeshWithSecondaryUVs",
        points=(Vector3(0.0, 0.0, 0.0), Vector3(1.0, 0.0, 0.0), Vector3(0.0, 1.0, 0.0)),
        face_vertex_counts=(3, 3),
        face_vertex_indices=(0, 1, 2, 0, 2, 1),
        uv_coords=(
            Vector2(0.0, 0.0),
            Vector2(1.0, 0.0),
            Vector2(0.0, 1.0),
            Vector2(0.0, 0.0),
            Vector2(0.0, 1.0),
            Vector2(1.0, 0.0),
        ),
        secondary_uv_coords=(
            Vector2(9.0, 9.0),
            Vector2(9.0, 9.0),
            Vector2(9.0, 9.0),
            Vector2(8.0, 8.0),
            Vector2(8.0, 8.0),
            Vector2(8.0, 8.0),
        ),
        sections=(
            MeshSection(material_id=1, face_indices=(0,)),
            MeshSection(material_id=2, face_indices=(1,)),
        ),
    )
    resolved = apply_udim_settings_to_mesh_data(
        mesh,
        (
            UdimMaterialSetting(
                material_id=1,
                mode=UdimMode.WRITE_SECONDARY_UV_OFFSET,
                udim_id=1003,
            ),
        ),
        label="Base Skeletal Tree",
    )

    assert resolved is not None
    assert [(uv.x, uv.y) for uv in resolved.secondary_uv_coords[:3]] == pytest.approx(
        [(2.5, 0.5), (2.5, 0.5), (2.5, 0.5)]
    )
    assert [(uv.x, uv.y) for uv in resolved.secondary_uv_coords[3:]] == pytest.approx(
        [(0.5, 0.5), (0.5, 0.5), (0.5, 0.5)]
    )


def test_udim_setting_that_matches_no_inline_material_is_resolution_error() -> None:
    with pytest.raises(ValueError, match="Base Skeletal Tree has no material sections for UDIM material id\\(s\\): 999"):
        load_resolved_assembly_model(
            str(SIMPLE_TREE_01),
            udim_material_settings=(
                UdimMaterialSetting(
                    material_id=999,
                    mode=UdimMode.SHIFT_PRIMARY_UV,
                    udim_id=1003,
                ),
            ),
        )


def test_udim_settings_json_loads_material_targets(tmp_path: Path) -> None:
    path = tmp_path / "udim_settings.json"
    path.write_text(
        json.dumps(
            [
                {
                    "material_id": 1,
                    "mode": UdimMode.WRITE_SECONDARY_UV_OFFSET.value,
                    "udim_id": 1003,
                }
            ]
        ),
        encoding="utf-8",
    )

    assert load_udim_material_settings_from_json(path) == (
        UdimMaterialSetting(
            material_id=1,
            mode=UdimMode.WRITE_SECONDARY_UV_OFFSET,
            udim_id=1003,
        ),
    )
