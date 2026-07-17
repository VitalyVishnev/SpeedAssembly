from __future__ import annotations

from array import array

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytestmark = pytest.mark.qt

from xml_to_usda.geometry_buffers import geometry_buffer_from_mesh
from xml_to_usda.models import Color4, GeometryBuffer, MeshData, Vector3
from xml_to_usda.qt_ui.fracture_preview import (
    FRACTURE_SOURCE_VERTEX_STRIDE,
    FRACTURE_VERTEX_STRIDE,
    FractureViewportMesh,
    _append_mesh_triangles,
    _build_fracture_instanced_render_payload,
    apply_fracture_viewport_mesh,
    build_fracture_viewport_mesh_from_scene,
)
from xml_to_usda.qt_ui.viewport import MatcapViewport, _build_matcap_instance_batches
from xml_to_usda.viewport_scene import (
    ViewportBounds,
    ViewportDrawCall,
    ViewportMeshBatch,
    ViewportScene,
    ViewportStats,
)


def test_matcap_viewport_defers_scene_upload_to_paint_gl(qtbot, monkeypatch) -> None:
    viewport = MatcapViewport()
    qtbot.addWidget(viewport)
    uploads: list[str] = []
    monkeypatch.setattr(viewport, "_upload_mesh", lambda: uploads.append("mesh"))
    monkeypatch.setattr(viewport, "_upload_grid", lambda: uploads.append("grid"))

    viewport.set_mesh(
        GeometryBuffer(
            name="Triangle",
            point_components=array("f", (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)),
            face_vertex_counts=array("i", (3,)),
            face_vertex_indices=array("i", (0, 1, 2)),
        )
    )

    assert uploads == []
    assert viewport._mesh_dirty is True
    assert viewport._grid_dirty is True


def test_fracture_viewport_rejects_oversized_unique_source_upload(qtbot, monkeypatch) -> None:
    monkeypatch.setattr("xml_to_usda.qt_ui.fracture_preview.MAX_FRACTURE_PREVIEW_UPLOAD_BYTES", 100)
    viewport = MatcapViewport()
    qtbot.addWidget(viewport)
    mesh = FractureViewportMesh(
        name="Oversized",
        vertex_components=array("f", (0.0,) * (3 * FRACTURE_SOURCE_VERTEX_STRIDE)),
        triangle_count=1,
        uploaded_triangle_count=0,
        piece_count=0,
        instance_count=0,
        draw_sources=(),
        draw_calls=(),
    )
    scene = ViewportScene(
        scene_id="oversized",
        mesh_batches=(),
        draw_calls=(),
        bounds=ViewportBounds(min_point=Vector3(0.0, 0.0, 0.0), max_point=Vector3(0.0, 0.0, 0.0)),
        stats=ViewportStats(uploaded_triangles=0, logical_triangles=0),
    )

    with pytest.raises(ValueError, match="Fracture Preview safely allows at most"):
        apply_fracture_viewport_mesh(viewport, mesh, scene=scene)


def test_fracture_viewport_keeps_repeated_parts_instanced_in_render_payload() -> None:
    triangle = GeometryBuffer(
        name="Triangle",
        point_components=array("f", (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)),
        face_vertex_counts=array("i", (3,)),
        face_vertex_indices=array("i", (0, 1, 2)),
    )
    repeated = tuple(
        ViewportDrawCall(
            draw_id=f"instance:{index}",
            batch_id="repeated",
            visibility_group="repeated_parts",
        )
        for index in range(9)
    )
    scene = ViewportScene(
        scene_id="sampled",
        mesh_batches=(
            ViewportMeshBatch(batch_id="base", name="Base", mesh=triangle),
            ViewportMeshBatch(batch_id="repeated", name="Repeated", mesh=triangle),
        ),
        draw_calls=(ViewportDrawCall(draw_id="base", batch_id="base", visibility_group="base_mesh"), *repeated),
        bounds=ViewportBounds(min_point=Vector3(0.0, 0.0, 0.0), max_point=Vector3(1.0, 1.0, 0.0)),
        stats=ViewportStats(uploaded_triangles=2, logical_triangles=10, instance_count=9),
    )

    mesh = build_fracture_viewport_mesh_from_scene(scene)
    payload, draws = _build_fracture_instanced_render_payload(mesh, scene)
    instance_rows, batches = _build_matcap_instance_batches(draws)

    assert mesh.triangle_count == 10
    assert mesh.uploaded_triangle_count == 2
    assert len(draws) == 10
    assert len(instance_rows) == 10
    assert len(batches) == 2
    assert sum(batch.instance_count for batch in batches) == 10
    assert len(payload.vertex_components) == 2 * 3 * FRACTURE_VERTEX_STRIDE


def test_fracture_viewport_smooths_shared_points_without_authored_normals() -> None:
    mesh = geometry_buffer_from_mesh(
        MeshData(
            name="Bent",
            points=(
                Vector3(0.0, 0.0, 0.0),
                Vector3(1.0, 0.0, 0.0),
                Vector3(0.0, 1.0, 0.0),
                Vector3(0.0, 0.0, 1.0),
            ),
            face_vertex_counts=(3, 3),
            face_vertex_indices=(0, 1, 2, 0, 3, 1),
        )
    )
    vertices = array("f")

    assert _append_mesh_triangles(vertices, mesh, color=Color4(1.0, 1.0, 1.0, 1.0)) == 2

    first_normal = tuple(vertices[3:6])
    second_face_same_point = tuple(
        vertices[3 * FRACTURE_SOURCE_VERTEX_STRIDE + 3 : 3 * FRACTURE_SOURCE_VERTEX_STRIDE + 6]
    )
    assert second_face_same_point == pytest.approx(first_normal)
    assert first_normal[1] > 0.0
    assert first_normal[2] > 0.0


def test_viewport_can_focus_on_mesh_and_zoom_to_cut_detail(qtbot) -> None:
    class _Delta:
        def y(self) -> int:
            return 120 * 100

    class _WheelEvent:
        def angleDelta(self) -> _Delta:
            return _Delta()

        def accept(self) -> None:
            return None

    viewport = MatcapViewport()
    qtbot.addWidget(viewport)
    viewport.resize(500, 400)
    viewport.set_mesh(
        GeometryBuffer(
            name="Triangle",
            point_components=array("f", (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)),
            face_vertex_counts=array("i", (3,)),
            face_vertex_indices=array("i", (0, 1, 2)),
        )
    )
    expected_focus = Vector3(0.2, 0.2, 0.0)
    screen = viewport._project_point_to_screen(expected_focus)

    assert screen is not None
    assert viewport.focus_at_screen_point(*screen) is True
    assert viewport.camera_target.x == pytest.approx(expected_focus.x, abs=1e-5)
    assert viewport.camera_target.y == pytest.approx(expected_focus.y, abs=1e-5)

    viewport._radius = 100.0
    viewport._distance = 300.0
    viewport.wheelEvent(_WheelEvent())
    assert viewport.camera_distance == pytest.approx(0.1)
