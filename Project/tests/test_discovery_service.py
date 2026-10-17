from __future__ import annotations

from pathlib import Path
from dataclasses import replace

import pytest

from xml_to_usda.discovery_service import (
    discover_base_material_rows,
    discover_part_prototype_rows,
    inspect_fbx_material_slot_rows,
)
from xml_to_usda.source_analysis import discover_missing_bone_generator_groups
from xml_to_usda.models import CpuProfile, FbxMaterialMode, FbxMaterialSlotSpec, PrototypeSourceMode
from xml_to_usda.settings_service import (
    BaseMaterialSettingRecord,
    FbxMaterialSlotSettingRecord,
    PartSourceSettingRecord,
)


SIMPLE_TREE_01 = Path(__file__).resolve().parents[1] / "samples" / "speedtree" / "simple_tree" / "variants" / "SimpleTree_01.xml"


@pytest.mark.parametrize("source", ("tree", "leaf_only", "clusters", "invalid_bone", "y_up"))
def test_opening_projects_canonical_facts_with_one_safe_read_and_no_model_cache(
    source, monkeypatch, tmp_path,
) -> None:
    from xml_to_usda import discovery_service as service, source_analysis
    from xml_to_usda.normalizer import normalize_to_canonical
    from xml_to_usda.scattered_parts import analyze_scattered_parts
    from xml_to_usda.skeleton_processing import strictly_vertical_joint_names
    from xml_to_usda.xml_reader import analyze_xml, read_source_xml

    if source in {"tree", "y_up"}:
        path = SIMPLE_TREE_01
        if source == "y_up":
            path = tmp_path / "y_up.xml"
            text = SIMPLE_TREE_01.read_text(encoding="utf-8")
            text = text.replace("<SpeedTreeRaw ", '<SpeedTreeRaw upAxis="Y" ', 1)
            path.write_text(text, encoding="utf-8")
    elif source == "invalid_bone":
        path = Path(__file__).parent / "data/invalid_leaf_bone.xml"
    elif source == "leaf_only":
        path = Path(__file__).parent / "data/missing_skeleton.xml"
    else:
        path = tmp_path / "clusters.xml"
        objects = ['<Object ID="0" />', '<Object ID="1" ParentID="0" />',
                   '<Object ID="2" ParentID="0" />']
        for index, parent in enumerate((1, 1, 2, 2), 3):
            objects.append(f'<Object ID="{index}" ParentID="{parent}"><LeafReferences>'
                           '<X>0</X><Y>1</Y><Z>2</Z><MeshID>1</MeshID>'
                           '</LeafReferences></Object>')
        path.write_text('<SpeedTreeRaw><Objects>' + ''.join(objects) +
                        '</Objects><Meshes><Mesh ID="1" Name="Blade" /></Meshes></SpeedTreeRaw>',
                        encoding="utf-8")
    document = read_source_xml(path)
    analysis = analyze_xml(document)
    if source == "y_up":
        assert analysis.report.up_axis_hint == "Y"
    model = normalize_to_canonical(document, analysis.report, source_nodes=analysis.source_nodes)
    expected_base = service.discover_base_material_rows(str(path))
    expected_prototypes = service.discover_part_prototype_rows(str(path))
    expected_gaps = source_analysis.discover_missing_bone_generator_groups(str(path))
    expected_scattered = analyze_scattered_parts(model)
    if model.skeleton:
        expected_scattered = replace(expected_scattered, reason="skeleton is present")
    if source == "clusters":
        assert expected_scattered.eligible and expected_scattered.cluster_count == 2

    reads = []
    def tracked_read(input_path):
        reads.append(input_path)
        return read_source_xml(input_path)
    def forbidden(*args, **kwargs):
        raise AssertionError("opening repeated XML parsing, cache IO, or unnecessary normalization")
    monkeypatch.setattr(service, "read_source_xml", tracked_read)
    monkeypatch.setattr(service, "load_source_tree_model", forbidden)
    monkeypatch.setattr(source_analysis, "iterparse_source_xml", forbidden)
    if model.skeleton:
        monkeypatch.setattr(service, "normalize_to_canonical", forbidden)
    result = service.discover_source_rows(service.SourceDiscoveryRequest(str(path)))
    assert reads == [str(path)]
    assert result.base == expected_base
    assert result.prototypes == expected_prototypes
    assert result.missing_bone_generator_groups == expected_gaps
    assert result.scattered_parts == expected_scattered
    assert result.strictly_vertical_joints == strictly_vertical_joint_names(model.skeleton)
    assert result.skeleton_joint_count == len(model.skeleton)


def test_discover_missing_bone_generator_groups_reports_only_internal_gaps(tmp_path: Path) -> None:
    xml_path = tmp_path / "missing_group.xml"
    xml_path.write_text(
        '<SpeedTreeRaw><Bones Count="3">'
        '<Bone ID="0" Generator="Group_0" />'
        '<Bone ID="1" Generator="Group_1" />'
        '<Bone ID="2" Generator="Group_3" />'
        "</Bones></SpeedTreeRaw>",
        encoding="utf-8",
    )

    assert discover_missing_bone_generator_groups(str(xml_path)) == ("Group_2",)

    xml_path.write_text(
        '<SpeedTreeRaw><Bones Count="3">'
        '<Bone ID="0" Generator="Group_0" />'
        '<Bone ID="1" Generator="Group_1" />'
        '<Bone ID="2" Generator="Group_2" />'
        "</Bones></SpeedTreeRaw>",
        encoding="utf-8",
    )
    assert discover_missing_bone_generator_groups(str(xml_path)) == ()


def test_discover_base_material_rows_merges_persisted_paths() -> None:
    discovery = discover_base_material_rows(
        str(SIMPLE_TREE_01),
        persisted_records=(
            BaseMaterialSettingRecord(
                source_id=1,
                source_name="Bark_Mat",
                ue_asset_path="/Game/TestMaterials/M_Bark_Test",
            ),
        ),
    )

    assert discovery.summary == "Found 2 base XML material slot(s)."
    assert discovery.rows[0].source_name == "Bark_Mat"
    assert discovery.rows[0].ue_asset_path == "/Game/TestMaterials/M_Bark_Test"
    assert discovery.rows[1].source_id == 0
    assert discovery.rows[1].source_name == "Default_Mat"
    assert discovery.rows[1].ue_asset_path == ""


def test_discover_part_prototype_rows_restores_persisted_modes() -> None:
    discovery = discover_part_prototype_rows(
        str(SIMPLE_TREE_01),
        persisted_records=(
            PartSourceSettingRecord(
                source_name="Twig_01",
                source_key="Mesh_1",
                source_mode=PrototypeSourceMode.FBX_FILE,
                fbx_path=r"D:\XMLtoUSD_miscFiles\spruce_branch.fbx",
                fbx_material_mode=FbxMaterialMode.MATERIAL_SLOTS,
                simplification_percent=25,
                fbx_material_slot_overrides=(
                    FbxMaterialSlotSettingRecord(
                        slot_name="Bark",
                        ue_asset_path="/Game/TreeParts/M_Bark.M_Bark",
                    ),
                ),
            ),
        ),
    )

    assert discovery.summary == "Found 39 repeated branch instances across 2 prototype(s)."
    assert discovery.rows[0].source_name == "Twig_01"
    assert discovery.rows[0].source_mode == PrototypeSourceMode.FBX_FILE
    assert discovery.rows[0].fbx_material_mode == FbxMaterialMode.MATERIAL_SLOTS
    assert discovery.rows[0].simplification_percent == 25
    assert discovery.rows[0].fbx_material_slot_overrides == (
        FbxMaterialSlotSettingRecord(
            slot_name="Bark",
            ue_asset_path="/Game/TreeParts/M_Bark.M_Bark",
        ),
    )


def test_inspect_fbx_material_slot_rows_merges_persisted_overrides(monkeypatch, tmp_path: Path) -> None:
    fake_fbx_path = tmp_path / "spruce_branch.fbx"
    fake_fbx_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "xml_to_usda.discovery_service._inspect_fbx_material_slots_cached",
        lambda *_args, **_kwargs: (
            FbxMaterialSlotSpec(source_id=1, name="Bark", face_count=12),
            FbxMaterialSlotSpec(source_id=2, name="Needles", face_count=24),
        ),
    )

    rows = inspect_fbx_material_slot_rows(
        str(fake_fbx_path),
        cpu_profile=CpuProfile.BALANCED,
        persisted_records=(
            FbxMaterialSlotSettingRecord(
                slot_name="Bark",
                ue_asset_path="/Game/TreeParts/M_Bark.M_Bark",
            ),
        ),
    )

    assert rows == (
        rows[0].__class__(slot_name="Bark", face_count=12, ue_asset_path="/Game/TreeParts/M_Bark.M_Bark"),
        rows[1].__class__(slot_name="Needles", face_count=24, ue_asset_path=""),
    )
