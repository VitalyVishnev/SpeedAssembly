from __future__ import annotations

from array import array

import numpy as np
import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

pytestmark = pytest.mark.qt

from xml_to_usda.models import Color4, GeometryBuffer, Vector3
from xml_to_usda.qt_ui.viewport import MATCAP_VERTEX_STRIDE, MatcapViewport, _build_scene_vertices, _upload_matcap_vertices
from xml_to_usda.viewport_scene import (
    ViewportBoneSegment,
    ViewportBounds,
    ViewportDrawCall,
    ViewportMeshBatch,
    ViewportScene,
    ViewportStats,
)


class _FakeVao:
    def __init__(self) -> None:
        self.events: list[str] = []

    def bind(self) -> None:
        self.events.append("bind")

    def release(self) -> None:
        self.events.append("release")


class _FakeVertexBuffer:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.allocated_size = 0

    def bind(self) -> None:
        self.events.append("bind")

    def allocate(self, _data: bytes, size: int) -> None:
        self.events.append("allocate")
        self.allocated_size = size

    def release(self) -> None:
        self.events.append("release")


class _FakeProgram:
    def __init__(self, *, bind_result: bool = True) -> None:
        self.bind_result = bind_result
        self.events: list[str] = []
        self.enabled_locations: list[int] = []
        self.attribute_buffers: list[tuple[int, int, int, int, int]] = []
        self._locations = {
            "position": 1,
            "normal": 2,
            "pieceTint": 3,
            "explodeOffset": 4,
            "scaleOrigin": 5,
            "lengthScale": 6,
        }

    def bind(self) -> bool:
        self.events.append("bind")
        return self.bind_result

    def attributeLocation(self, name: str) -> int:
        return self._locations.get(name, -1)

    def enableAttributeArray(self, location: int) -> None:
        self.enabled_locations.append(location)

    def setAttributeBuffer(
        self, location: int, value_type: int, offset: int, tuple_size: int, stride: int
    ) -> None:
        self.attribute_buffers.append((location, value_type, offset, tuple_size, stride))

    def release(self) -> None:
        self.events.append("release")


def _triangle_mesh() -> GeometryBuffer:
    return GeometryBuffer(
        name="Triangle",
        point_components=array("f", (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)),
        face_vertex_counts=array("i", (3,)),
        face_vertex_indices=array("i", (0, 1, 2)),
    )


def test_matcap_vertex_upload_binds_the_shared_mesh_layout() -> None:
    vertices = np.zeros(MATCAP_VERTEX_STRIDE * 2, dtype=np.float32)
    vao = _FakeVao()
    vertex_buffer = _FakeVertexBuffer()
    program = _FakeProgram()

    uploaded = _upload_matcap_vertices(program=program, vertex_buffer=vertex_buffer, vao=vao, vertices=vertices)

    assert uploaded is True
    assert vao.events == ["bind", "release"]
    assert vertex_buffer.events == ["bind", "allocate", "release"]
    assert vertex_buffer.allocated_size == vertices.nbytes
    assert program.events == ["bind", "release"]
    assert program.enabled_locations == [1, 2, 3, 4, 5, 6]
    assert program.attribute_buffers == [
        (1, 0x1406, 0, 3, MATCAP_VERTEX_STRIDE * 4),
        (2, 0x1406, 12, 3, MATCAP_VERTEX_STRIDE * 4),
        (3, 0x1406, 24, 4, MATCAP_VERTEX_STRIDE * 4),
        (4, 0x1406, 40, 3, MATCAP_VERTEX_STRIDE * 4),
        (5, 0x1406, 52, 3, MATCAP_VERTEX_STRIDE * 4),
        (6, 0x1406, 64, 1, MATCAP_VERTEX_STRIDE * 4),
    ]


def test_matcap_vertex_upload_releases_resources_when_program_cannot_bind() -> None:
    vertices = np.zeros(MATCAP_VERTEX_STRIDE, dtype=np.float32)
    vao = _FakeVao()
    vertex_buffer = _FakeVertexBuffer()
    program = _FakeProgram(bind_result=False)

    uploaded = _upload_matcap_vertices(program=program, vertex_buffer=vertex_buffer, vao=vao, vertices=vertices)

    assert uploaded is False
    assert vao.events == ["bind", "release"]
    assert vertex_buffer.events == ["bind", "allocate", "release"]
    assert program.events == ["bind"]
    assert program.enabled_locations == []
    assert program.attribute_buffers == []


def test_sphere_collision_visual_scale_uses_center_origin() -> None:
    mesh = GeometryBuffer(
        name="USP_Sphere",
        point_components=array("f", (-1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 2.0, 0.0)),
        face_vertex_counts=array("i", (3,)),
        face_vertex_indices=array("i", (0, 1, 2)),
    )
    batch = ViewportMeshBatch(batch_id="collision", name="collision", mesh=mesh, color=Color4(0.0, 1.0, 1.0, 0.25))
    scene = ViewportScene(
        scene_id="sphere_collision",
        mesh_batches=(batch,),
        draw_calls=(ViewportDrawCall(draw_id="collision:0", batch_id=batch.batch_id, visibility_group="collision"),),
        bounds=ViewportBounds(min_point=Vector3(-1.0, 0.0, 0.0), max_point=Vector3(1.0, 2.0, 0.0)),
        stats=ViewportStats(uploaded_triangles=1, logical_triangles=1, batch_count=1, draw_call_count=1),
    )

    vertices = _build_scene_vertices(scene, collision=True)
    origins = [tuple(vertices[index + 13:index + 16]) for index in range(0, len(vertices), MATCAP_VERTEX_STRIDE)]

    assert origins == [(0.0, 1.0, 0.0)] * 3


def test_matcap_viewport_accepts_viewport_scene_without_mode_specific_dialog(qtbot) -> None:
    batch = ViewportMeshBatch(
        batch_id="triangle",
        name="Triangle",
        mesh=_triangle_mesh(),
        color=Color4(0.25, 0.5, 0.75, 1.0),
    )
    scene = ViewportScene(
        scene_id="synthetic",
        mesh_batches=(batch,),
        draw_calls=(ViewportDrawCall(draw_id="triangle:0", batch_id=batch.batch_id),),
        bounds=ViewportBounds(min_point=Vector3(0.0, 0.0, 0.0), max_point=Vector3(1.0, 1.0, 0.0)),
        stats=ViewportStats(uploaded_triangles=1, logical_triangles=1, batch_count=1, draw_call_count=1),
    )
    viewport = MatcapViewport()
    qtbot.addWidget(viewport)

    viewport.set_scene(scene)

    assert viewport.has_mesh() is True
    assert viewport.vertex_count == 3
    assert viewport.camera_radius == pytest.approx(2**0.5 * 0.5)
    assert viewport.camera_distance == pytest.approx(viewport.camera_radius * 3.0)


def test_matcap_viewport_reports_set_scene_trace_event(qtbot) -> None:
    batch = ViewportMeshBatch(
        batch_id="triangle",
        name="Triangle",
        mesh=_triangle_mesh(),
        color=Color4(0.25, 0.5, 0.75, 1.0),
    )
    scene = ViewportScene(
        scene_id="synthetic_trace",
        mesh_batches=(batch,),
        draw_calls=(ViewportDrawCall(draw_id="triangle:0", batch_id=batch.batch_id),),
        bounds=ViewportBounds(min_point=Vector3(0.0, 0.0, 0.0), max_point=Vector3(1.0, 1.0, 0.0)),
        stats=ViewportStats(uploaded_triangles=1, logical_triangles=1, batch_count=1, draw_call_count=1),
        bone_segments=(
            ViewportBoneSegment(
                segment_id="bone:root->branch",
                parent_token="root",
                child_token="branch",
                start=Vector3(0.0, 0.0, 0.0),
                end=Vector3(0.0, 1.0, 0.0),
                color=Color4(0.2, 0.8, 1.0, 1.0),
            ),
        ),
    )
    events: list[tuple[str, dict[str, object]]] = []
    viewport = MatcapViewport()
    viewport.set_trace_callback(lambda kind, data: events.append((kind, data)))
    qtbot.addWidget(viewport)

    viewport.set_scene(scene)

    assert events == [
        (
            "viewport.set_scene",
            {
                "scene_id": "synthetic_trace",
                "batch_count": 1,
                "draw_call_count": 1,
                "bone_segment_count": 1,
                "vertex_count": 3,
            },
        )
    ]


def test_matcap_viewport_accepts_precomputed_matcap_scene_payload(qtbot) -> None:
    scene = ViewportScene(
        scene_id="precomputed_trace",
        mesh_batches=(),
        draw_calls=(),
        bounds=ViewportBounds(min_point=Vector3(-2.0, -1.0, 0.0), max_point=Vector3(2.0, 3.0, 4.0)),
        stats=ViewportStats(uploaded_triangles=2, logical_triangles=2, batch_count=0, draw_call_count=0),
        bone_segments=(
            ViewportBoneSegment(
                segment_id="bone:root->branch",
                parent_token="root",
                child_token="branch",
                start=Vector3(0.0, 0.0, 0.0),
                end=Vector3(0.0, 1.0, 0.0),
                color=Color4(0.2, 0.8, 1.0, 1.0),
            ),
        ),
    )
    vertices = np.zeros(MATCAP_VERTEX_STRIDE * 6, dtype=np.float32)
    events: list[tuple[str, dict[str, object]]] = []
    viewport = MatcapViewport()
    viewport.set_trace_callback(lambda kind, data: events.append((kind, data)))
    qtbot.addWidget(viewport)

    viewport.set_precomputed_matcap_scene(
        scene,
        vertices=vertices,
        min_point=scene.bounds.min_point,
        max_point=scene.bounds.max_point,
    )

    assert viewport.has_mesh() is True
    assert viewport.vertex_count == 6
    assert viewport.camera_radius == pytest.approx(12**0.5)
    assert viewport.camera_distance == pytest.approx(viewport.camera_radius * 3.0)
    assert events == [
        (
            "viewport.set_scene",
            {
                "scene_id": "precomputed_trace",
                "batch_count": 0,
                "draw_call_count": 0,
                "bone_segment_count": 1,
                "vertex_count": 6,
            },
        )
    ]


def test_matcap_viewport_reports_context_lost_when_gl_resources_are_released(qtbot) -> None:
    class _Resource:
        def destroy(self) -> None:
            return None

    class _Program:
        def release(self) -> None:
            return None

        def removeAllShaders(self) -> None:
            return None

    events: list[tuple[str, dict[str, object]]] = []
    viewport = MatcapViewport()
    viewport.set_trace_callback(lambda kind, data: events.append((kind, data)))
    qtbot.addWidget(viewport)
    viewport._mesh = _triangle_mesh()
    viewport._vertex_count = 3
    viewport._program = _Program()
    viewport._vertex_buffer = _Resource()
    viewport._vao = _Resource()
    viewport._grid_program = _Program()
    viewport._grid_buffer = _Resource()
    viewport._grid_vao = _Resource()

    viewport._release_gl_resources()

    assert events[0] == ("viewport.context_lost", {"had_mesh": True, "vertex_count": 3})
    assert viewport.vertex_count == 0


def test_matcap_viewport_scene_update_can_preserve_camera(qtbot) -> None:
    batch = ViewportMeshBatch(batch_id="triangle", name="Triangle", mesh=_triangle_mesh())
    scene = ViewportScene(
        scene_id="synthetic",
        mesh_batches=(batch,),
        draw_calls=(ViewportDrawCall(draw_id="triangle:0", batch_id=batch.batch_id),),
        bounds=ViewportBounds(min_point=Vector3(0.0, 0.0, 0.0), max_point=Vector3(1.0, 1.0, 0.0)),
        stats=ViewportStats(uploaded_triangles=1, logical_triangles=1, batch_count=1, draw_call_count=1),
    )
    viewport = MatcapViewport()
    qtbot.addWidget(viewport)
    viewport.set_scene(scene)
    viewport._distance = 42.0

    viewport.set_scene(scene, frame_camera=False)

    assert viewport.vertex_count == 3
    assert viewport.camera_distance == pytest.approx(42.0)


def test_matcap_viewport_picks_bone_segment_from_viewport_scene(qtbot) -> None:
    batch = ViewportMeshBatch(batch_id="triangle", name="Triangle", mesh=_triangle_mesh())
    scene = ViewportScene(
        scene_id="synthetic_bones",
        mesh_batches=(batch,),
        draw_calls=(ViewportDrawCall(draw_id="triangle:0", batch_id=batch.batch_id),),
        bounds=ViewportBounds(min_point=Vector3(-1.0, 0.0, 0.0), max_point=Vector3(1.0, 1.0, 0.0)),
        stats=ViewportStats(uploaded_triangles=1, logical_triangles=1, batch_count=1, draw_call_count=1),
        bone_segments=(
            ViewportBoneSegment(
                segment_id="bone:root->branch",
                parent_token="root",
                child_token="branch",
                start=Vector3(0.25, 0.0, 0.0),
                end=Vector3(0.25, 1.0, 0.0),
                color=Color4(0.2, 0.8, 1.0, 1.0),
                selectable_id="bone:root->branch",
            ),
        ),
    )
    viewport = MatcapViewport()
    qtbot.addWidget(viewport)
    viewport.resize(500, 400)
    viewport.set_scene(scene)
    viewport.set_show_bones(True)
    screen = viewport._project_point_to_screen(Vector3(0.25, 0.5, 0.0))

    assert screen is not None
    cut_token = viewport.pick_bone_segment_child_token(screen[0], screen[1])

    assert viewport.bone_vertex_count == 2
    assert cut_token is not None
    assert cut_token.startswith("root->branch@")
    assert 0.45 < float(cut_token.rsplit("@", 1)[1]) < 0.55


def test_matcap_viewport_scene_vertices_include_explode_direction() -> None:
    batch = ViewportMeshBatch(batch_id="triangle", name="Triangle", mesh=_triangle_mesh())
    scene = ViewportScene(
        scene_id="synthetic_explode",
        mesh_batches=(batch,),
        draw_calls=(
            ViewportDrawCall(
                draw_id="triangle:0",
                batch_id=batch.batch_id,
                explode_direction=Vector3(2.0, 3.0, 4.0),
            ),
        ),
        bounds=ViewportBounds(min_point=Vector3(0.0, 0.0, 0.0), max_point=Vector3(1.0, 1.0, 0.0)),
        stats=ViewportStats(uploaded_triangles=1, logical_triangles=1, batch_count=1, draw_call_count=1),
    )

    vertices = _build_scene_vertices(scene)

    assert len(vertices) == 3 * MATCAP_VERTEX_STRIDE
    assert tuple(vertices[10:13]) == pytest.approx((2.0, 3.0, 4.0))
    assert tuple(vertices[13:16]) == pytest.approx((0.0, 0.0, 0.0))
    assert vertices[16] == pytest.approx(0.0)


def test_matcap_collision_scale_origin_projects_vertices_to_capsule_axis() -> None:
    mesh = GeometryBuffer(
        name="UCP_CapsuleLike",
        point_components=array("f", (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 2.0, 0.0)),
        face_vertex_counts=array("i", (3,)),
        face_vertex_indices=array("i", (0, 1, 2)),
    )
    batch = ViewportMeshBatch(batch_id="collision", name="Collision", mesh=mesh)
    scene = ViewportScene(
        scene_id="collision_scale_origin",
        mesh_batches=(batch,),
        draw_calls=(
            ViewportDrawCall(
                draw_id="collision:0",
                batch_id=batch.batch_id,
                visibility_group="collision",
            ),
        ),
        bounds=ViewportBounds(min_point=Vector3(0.0, 0.0, 0.0), max_point=Vector3(1.0, 2.0, 0.0)),
        stats=ViewportStats(uploaded_triangles=1, logical_triangles=1, batch_count=1, draw_call_count=1),
    )

    vertices = _build_scene_vertices(scene, collision=True)
    side_vertex = vertices[MATCAP_VERTEX_STRIDE:MATCAP_VERTEX_STRIDE * 2]

    assert tuple(side_vertex[0:3]) == pytest.approx((1.0, 0.0, 0.0))
    assert tuple(side_vertex[13:16]) == pytest.approx((0.0, 0.0, 0.0))


def test_matcap_collision_vertices_include_length_scale_relative_to_longest_call() -> None:
    mesh = GeometryBuffer(
        name="CapsuleLike",
        point_components=array("f", (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)),
        face_vertex_counts=array("i", (3,)),
        face_vertex_indices=array("i", (0, 1, 2)),
    )
    batch = ViewportMeshBatch(batch_id="collision", name="Collision", mesh=mesh)
    scene = ViewportScene(
        scene_id="collision_length_scale",
        mesh_batches=(batch,),
        draw_calls=(
            ViewportDrawCall(draw_id="short", batch_id=batch.batch_id, visibility_group="collision"),
            ViewportDrawCall(
                draw_id="long",
                batch_id=batch.batch_id,
                visibility_group="collision",
                scale=Vector3(1.0, 3.0, 1.0),
            ),
        ),
        bounds=ViewportBounds(min_point=Vector3(0.0, 0.0, 0.0), max_point=Vector3(1.0, 3.0, 0.0)),
        stats=ViewportStats(uploaded_triangles=1, logical_triangles=2, batch_count=1, draw_call_count=2),
    )

    vertices = _build_scene_vertices(scene, collision=True)

    assert vertices[16] == pytest.approx(1.0 / 3.0)
    assert vertices[3 * MATCAP_VERTEX_STRIDE + 16] == pytest.approx(1.0)
