from __future__ import annotations

from array import array
from dataclasses import replace
from types import SimpleNamespace

import xml_to_usda.part_preview_service as part_preview_service_module
from xml_to_usda.models import (
    CompactMeshSection,
    FbxMaterialMode,
    GeometryBuffer,
    Prototype,
    PrototypeIdentity,
    PrototypeSourceConfig,
    PrototypeSourceMode,
)
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


def test_part_preview_samples_oversized_geometry_without_changing_export_prediction(monkeypatch) -> None:
    source_mesh = replace(
        _preview_mesh(),
        vertex_color_components=array(
            "f",
            (
                0.0, 0.0, 0.0, 1.0,
                0.0, 0.0, 0.0, 1.0,
                0.0, 0.0, 0.0, 1.0,
                1.0, 1.0, 1.0, 1.0,
                1.0, 1.0, 1.0, 1.0,
                1.0, 1.0, 1.0, 1.0,
            ),
        ),
    )
    prototype = Prototype(
        identity=PrototypeIdentity(source_key="Mesh_1", prim_name="Twig"),
        mesh=None,
        geometry_payload=source_mesh,
        source_key="Mesh_1",
        source_mesh_id=1,
        source_name="Twig",
    )
    monkeypatch.setattr(part_preview_service_module, "MAX_PART_PREVIEW_DISPLAY_FACES", 1)
    monkeypatch.setattr(
        part_preview_service_module,
        "load_resolved_assembly_model",
        lambda *_args, **_kwargs: (None, SimpleNamespace(authoring_model=SimpleNamespace(prototypes=(prototype,), materials=()))),
    )

    result = build_part_prototype_preview(
        PartPrototypePreviewRequest(
            input_path="tree.xml",
            source_key="Mesh_1",
            source_name="Twig",
            prototype_source_config=PrototypeSourceConfig(source_key="Mesh_1", source_name="Twig"),
        ),
        PartPrototypePreviewSettings(display_mode=PartPreviewDisplayMode.VERTEX_COLORS),
    )

    assert result.preview_limited is True
    assert result.source_triangle_count == 2
    assert result.displayed_triangle_count == 1
    assert result.predicted_export_triangle_count == 2
    assert result.mesh.vertex_color_count == result.mesh.point_count == 3


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


def test_part_preview_fbx_mode_loads_payload_without_resolving_full_assembly(monkeypatch) -> None:
    calls: dict[str, object] = {}

    def fail_resolved_load(*_args, **_kwargs):
        raise AssertionError("FBX part preview should not resolve the full assembly model")

    def fake_load_fbx_geometry(*_args, **kwargs):
        calls["strict_vertex_colors"] = kwargs["strict_vertex_colors"]
        calls["read_vertex_colors"] = kwargs["read_vertex_colors"]
        calls["read_material_slots"] = kwargs["read_material_slots"]
        return _preview_mesh()

    monkeypatch.setattr("xml_to_usda.part_preview_service.load_resolved_assembly_model", fail_resolved_load)
    monkeypatch.setattr("xml_to_usda.part_preview_service.load_fbx_payload_from_cache", lambda *_args, **_kwargs: SimpleNamespace(payload=None))
    monkeypatch.setattr("xml_to_usda.part_preview_service.store_fbx_payload_in_cache", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("xml_to_usda.part_preview_service.load_fbx_geometry", fake_load_fbx_geometry)

    result = build_part_prototype_preview(
        PartPrototypePreviewRequest(
            input_path="tree.xml",
            source_key="Mesh_1",
            source_name="Twig",
            prototype_source_config=PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path="twig.fbx",
                fbx_material_mode=FbxMaterialMode.VERTEX_COLOR_SPLIT,
            ),
        ),
        PartPrototypePreviewSettings(display_mode=PartPreviewDisplayMode.MATERIAL_COLORS),
    )

    assert result.source_mode == PrototypeSourceMode.FBX_FILE
    assert result.source_triangle_count == 2
    assert result.source_section_triangle_counts == (1, 1)
    assert calls == {
        "strict_vertex_colors": True,
        "read_vertex_colors": True,
        "read_material_slots": False,
    }
