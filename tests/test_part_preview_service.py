from __future__ import annotations

from array import array
from types import SimpleNamespace

from xml_to_usda.models import CompactMeshSection, GeometryBuffer, Prototype, PrototypeIdentity, PrototypeSourceConfig
from xml_to_usda.part_preview_service import (
    PartPreviewDisplayMode,
    PartPrototypePreviewRequest,
    PartPrototypePreviewSettings,
    build_part_prototype_preview,
)


def _preview_mesh() -> GeometryBuffer:
    return GeometryBuffer(
        name="Twig",
        point_components=array("f", [0, 0, 0, 1, 0, 0, 0, 1, 0, 2, 0, 0, 3, 0, 0, 2, 1, 0]),
        face_vertex_counts=array("i", [3, 3]),
        face_vertex_indices=array("i", [0, 1, 2, 3, 4, 5]),
        sections=(
            CompactMeshSection(material_id=10, face_indices=array("i", [0])),
            CompactMeshSection(material_id=20, face_indices=array("i", [1])),
        ),
    )


def test_part_preview_material_colors_are_stable_per_material_section(monkeypatch) -> None:
    prototype = Prototype(
        identity=PrototypeIdentity(source_key="Mesh_1", prim_name="Twig"),
        mesh=None,
        geometry_payload=_preview_mesh(),
        source_key="Mesh_1",
        source_mesh_id=1,
        source_name="Twig",
    )

    monkeypatch.setattr(
        "xml_to_usda.part_preview_service.load_resolved_assembly_model",
        lambda *_args, **_kwargs: (None, SimpleNamespace(authoring_model=SimpleNamespace(prototypes=(prototype,)))),
    )

    result = build_part_prototype_preview(
        PartPrototypePreviewRequest(
            input_path="tree.xml",
            source_key="Mesh_1",
            source_name="Twig",
            prototype_source_config=PrototypeSourceConfig(source_key="Mesh_1", source_name="Twig"),
        ),
        PartPrototypePreviewSettings(display_mode=PartPreviewDisplayMode.MATERIAL_COLORS),
    )

    assert result.mesh is not None
    assert result.displayed_triangle_count == 2
    assert [entry.material_id for entry in result.material_colors] == [10, 20]
    assert result.mesh.vertex_color_count == result.mesh.point_count
    first_color = tuple(result.mesh.vertex_color_components[:4])
    second_face_color = tuple(result.mesh.vertex_color_components[12:16])
    assert first_color != second_face_color


def test_part_preview_loads_source_geometry_without_export_simplification(monkeypatch) -> None:
    prototype = Prototype(
        identity=PrototypeIdentity(source_key="Mesh_1", prim_name="Twig"),
        mesh=None,
        geometry_payload=_preview_mesh(),
        source_key="Mesh_1",
        source_mesh_id=1,
        source_name="Twig",
    )
    calls: dict[str, object] = {}

    def fake_load(*_args, **kwargs):
        calls["config"] = kwargs["prototype_source_configs"][0]
        return None, SimpleNamespace(authoring_model=SimpleNamespace(prototypes=(prototype,), materials=()))

    monkeypatch.setattr("xml_to_usda.part_preview_service.load_resolved_assembly_model", fake_load)

    result = build_part_prototype_preview(
        PartPrototypePreviewRequest(
            input_path="tree.xml",
            source_key="Mesh_1",
            source_name="Twig",
            prototype_source_config=PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig",
                simplification_percent=0,
            ),
        ),
        PartPrototypePreviewSettings(display_mode=PartPreviewDisplayMode.DEFAULT),
    )

    assert calls["config"].simplification_percent == 100
    assert result.source_triangle_count == 2
    assert result.source_section_triangle_counts == (1, 1)
    assert result.predicted_export_triangle_count == 2
