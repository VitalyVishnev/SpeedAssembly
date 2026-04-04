from __future__ import annotations

from pathlib import Path

from xml_to_usda.source_analysis import discover_part_prototypes, discover_source_materials, inspect_source


SIMPLE_TREE_01 = Path(__file__).resolve().parents[1] / "samples" / "speedtree" / "simple_tree" / "variants" / "SimpleTree_01.xml"


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


def test_source_analysis_discovers_only_base_mesh_material_slots() -> None:
    materials = discover_source_materials(str(SIMPLE_TREE_01))

    assert materials == (
        materials[0].__class__(source_id=1, source_name="Bark_Mat"),
    )


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
