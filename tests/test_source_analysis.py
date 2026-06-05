from __future__ import annotations

from pathlib import Path

import pytest

from xml_to_usda.models import BaseMaterialOverride, PrototypeDiscoveryEntry
from xml_to_usda.normalizer import normalize_to_canonical
from xml_to_usda.source_analysis import discover_part_prototypes, discover_source_materials, inspect_source
from xml_to_usda.xml_reader import analyze_xml, read_source_xml


SIMPLE_TREE_01 = Path(__file__).resolve().parents[1] / "samples" / "speedtree" / "simple_tree" / "variants" / "SimpleTree_01.xml"
DATA_DIR = Path(__file__).resolve().parent / "data"


def test_source_analysis_inspect_source_smoke() -> None:
    report = inspect_source(str(SIMPLE_TREE_01))

    assert report.base_mesh_part_count > 0
    assert report.base_mesh_face_count > 0
    assert report.prototype_structure


def test_source_analysis_discovers_part_prototypes_for_simple_tree() -> None:
    discovered = discover_part_prototypes(str(SIMPLE_TREE_01))

    assert discovered == (
        discovered[0].__class__(source_key="Mesh_1", source_mesh_id=1, source_name="Twig_01", instance_count=13),
        discovered[1].__class__(source_key="Mesh_2", source_mesh_id=2, source_name="Twig_02", instance_count=26),
    )


def test_source_analysis_streamed_part_prototypes_match_canonical_simple_tree() -> None:
    assert discover_part_prototypes(str(SIMPLE_TREE_01)) == _canonical_part_prototypes(SIMPLE_TREE_01)


@pytest.mark.parametrize(
    "fixture_name",
    (
        "leafrefs_on_branch_levels.xml",
        "leafrefs_on_trunk.xml",
        "invalid_leaf_bone.xml",
        "missing_skeleton.xml",
    ),
)
def test_source_analysis_streamed_part_prototypes_match_canonical_leaf_reference_fixtures(
    fixture_name: str,
) -> None:
    xml_path = DATA_DIR / fixture_name

    assert discover_part_prototypes(str(xml_path)) == _canonical_part_prototypes(xml_path)


def test_source_analysis_discovers_only_base_mesh_material_slots() -> None:
    materials = discover_source_materials(str(SIMPLE_TREE_01))

    assert materials == (
        materials[0].__class__(source_id=1, source_name="Bark_Mat"),
    )


def test_source_analysis_streamed_base_materials_match_canonical_base_sections() -> None:
    assert discover_source_materials(str(SIMPLE_TREE_01)) == _canonical_base_materials(SIMPLE_TREE_01)


def test_source_analysis_falls_back_to_leaf_prototype_without_explicit_mesh_id(tmp_path: Path) -> None:
    xml_path = tmp_path / "leafrefs_only.xml"
    xml_path.write_text(
        "\n".join(
            (
                "<SpeedTreeRaw>",
                "  <LeafReferences>",
                "    <X>0</X>",
                "  </LeafReferences>",
                "</SpeedTreeRaw>",
            )
        ),
        encoding="utf-8",
    )

    discovered = discover_part_prototypes(str(xml_path))

    assert discovered == (
        discovered[0].__class__(
            source_key="LeafPrototype",
            source_mesh_id=None,
            source_name="LeafPrototype",
            instance_count=1,
        ),
    )


def _canonical_part_prototypes(input_path: Path) -> tuple[PrototypeDiscoveryEntry, ...]:
    model = _canonical_model(input_path)
    return tuple(
        PrototypeDiscoveryEntry(
            source_key=prototype.source_key,
            source_mesh_id=prototype.source_mesh_id,
            source_name=prototype.source_name,
            instance_count=sum(1 for part in model.repeated_parts if part.prototype_key == prototype.source_key),
        )
        for prototype in model.prototypes
    )


def _canonical_base_materials(input_path: Path) -> tuple[BaseMaterialOverride, ...]:
    model = _canonical_model(input_path)
    if model.base_mesh is None:
        return ()
    base_material_ids = {section.material_id for section in model.base_mesh.sections}
    return tuple(
        BaseMaterialOverride(source_id=material.source_id, source_name=material.name)
        for material in model.materials
        if material.source_id in base_material_ids
    )


def _canonical_model(input_path: Path):
    document = read_source_xml(str(input_path))
    analysis = analyze_xml(document)
    return normalize_to_canonical(document, analysis.report, source_nodes=analysis.source_nodes)
