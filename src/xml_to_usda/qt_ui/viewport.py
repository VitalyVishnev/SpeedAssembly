"""Shared Qt/OpenGL preview viewport.

Layer: UI infrastructure.

This module owns camera/orbit/grid behavior and OpenGL resource lifecycle for
preview rendering. It consumes UI-ready viewport payloads; it does not generate
Proxy Meshes, plan Fracture Pieces, or interpret source XML.
"""

from __future__ import annotations

from dataclasses import replace
import math
from typing import Callable

import numpy as np

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QMatrix4x4, QPainter, QPen, QSurfaceFormat, QVector3D
from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram, QOpenGLVertexArrayObject
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QSizePolicy

from ..models import Color4, GeometryBuffer, Quaternion, Vector3
from ..viewport_scene import ViewportBoneSegment, ViewportDrawCall, ViewportScene


GL_COLOR_BUFFER_BIT = 0x00004000
GL_DEPTH_BUFFER_BIT = 0x00000100
GL_DEPTH_TEST = 0x0B71
GL_BLEND = 0x0BE2
GL_BACK = 0x0405
GL_CULL_FACE = 0x0B44
GL_FLOAT = 0x1406
GL_LINES = 0x0001
GL_ONE_MINUS_SRC_ALPHA = 0x0303
GL_SRC_ALPHA = 0x0302
GL_TRIANGLES = 0x0004
DEFAULT_MATCAP_TINT_ALPHA = 0.0
MATCAP_VERTEX_STRIDE = 17
ViewportTraceCallback = Callable[[str, dict[str, object]], None]
_MATCAP_ATTRIBUTE_LAYOUT = (
    ("position", 0, 3),
    ("normal", 12, 3),
    ("pieceTint", 24, 4),
    ("explodeOffset", 40, 3),
    ("scaleOrigin", 52, 3),
    ("lengthScale", 64, 1),
)


def _upload_matcap_vertices(
    *,
    program: QOpenGLShaderProgram,
    vertex_buffer: QOpenGLBuffer,
    vao: QOpenGLVertexArrayObject,
    vertices: np.ndarray,
) -> bool:
    """Upload the shared matcap vertex layout and bind its shader attributes."""
    vao.bind()
    vertex_buffer.bind()
    vertex_buffer.allocate(vertices.tobytes(), vertices.nbytes)
    if not program.bind():
        vertex_buffer.release()
        vao.release()
        return False
    stride = MATCAP_VERTEX_STRIDE * 4
    for attribute_name, byte_offset, component_count in _MATCAP_ATTRIBUTE_LAYOUT:
        location = program.attributeLocation(attribute_name)
        if location >= 0:
            program.enableAttributeArray(location)
            program.setAttributeBuffer(location, GL_FLOAT, byte_offset, component_count, stride)
    program.release()
    vertex_buffer.release()
    vao.release()
    return True


class MatcapViewport(QOpenGLWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(480, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        format_ = QSurfaceFormat()
        format_.setDepthBufferSize(24)
        format_.setSamples(4)
        self.setFormat(format_)
        self._mesh: GeometryBuffer | None = None
        self._scene: ViewportScene | None = None
        self._precomputed_matcap_vertices: np.ndarray | None = None
        self._mesh_tint_alpha = DEFAULT_MATCAP_TINT_ALPHA
        self._target = Vector3(0.0, 0.0, 0.0)
        self._radius = 1.0
        self._distance = 3.0
        self._yaw = math.radians(38.0)
        self._pitch = math.radians(18.0)
        self._last_mouse: QPoint | None = None
        self._program: QOpenGLShaderProgram | None = None
        self._vertex_buffer: QOpenGLBuffer | None = None
        self._vao: QOpenGLVertexArrayObject | None = None
        self._collision_vertex_buffer: QOpenGLBuffer | None = None
        self._collision_vao: QOpenGLVertexArrayObject | None = None
        self._grid_program: QOpenGLShaderProgram | None = None
        self._grid_buffer: QOpenGLBuffer | None = None
        self._grid_vao: QOpenGLVertexArrayObject | None = None
        self._vertex_count = 0
        self._visible_vertex_count_override: int | None = None
        self._collision_vertex_count = 0
        self._grid_vertex_count = 0
        self._mesh_dirty = False
        self._grid_dirty = False
        self._ground_y = 0.0
        self._matcap_tint_strength = DEFAULT_MATCAP_TINT_ALPHA
        self._exploded_view_strength = 0.0
        self._collision_opacity = 0.25
        self._collision_base_opacity = 0.25
        self._collision_geometry_scale = 1.0
        self._collision_length_scale = 0.0
        self._collision_base_length_scale = 0.0
        self._gl_cleanup_context = None
        self._show_bones = False
        self._selected_cut_tokens: tuple[str, ...] = ()
        self._hover_cut_token: str | None = None
        self._trace_callback: ViewportTraceCallback | None = None
        self.on_bone_cut_toggled = lambda _joint_token: None
        self.on_bone_clicked = lambda _joint_token, _modifiers: None
        self._bone_pick_requires_control = True
        self._shortcut_hints: tuple[str, ...] = ()
        self.setMouseTracking(True)

    def has_mesh(self) -> bool:
        if self._precomputed_matcap_vertices is not None:
            return self._vertex_count > 0
        if self._scene is not None:
            return self._vertex_count > 0 or bool(self._scene.mesh_batches)
        return self._mesh is not None and self._mesh.point_count > 0

    @property
    def vertex_count(self) -> int:
        return self._vertex_count

    @property
    def grid_vertex_count(self) -> int:
        return self._grid_vertex_count

    @property
    def camera_radius(self) -> float:
        return self._radius

    @property
    def camera_distance(self) -> float:
        return self._distance

    @property
    def matcap_tint_strength(self) -> float:
        return self._matcap_tint_strength

    def set_matcap_tint_strength(self, value: float) -> None:
        self._matcap_tint_strength = max(0.0, min(1.0, float(value)))
        self.update()

    @property
    def exploded_view_strength(self) -> float:
        return self._exploded_view_strength

    def set_exploded_view_strength(self, value: float) -> None:
        self._exploded_view_strength = max(0.0, min(2.0, float(value)))
        self.update()

    @property
    def collision_opacity(self) -> float:
        return self._collision_opacity

    @property
    def collision_geometry_scale(self) -> float:
        return self._collision_geometry_scale

    @property
    def collision_length_scale(self) -> float:
        return self._collision_length_scale

    def set_collision_visuals(
        self,
        *,
        opacity: float,
        geometry_scale: float = 1.0,
        length_scale: float = 0.0,
        base_length_scale: float = 0.0,
    ) -> None:
        self._collision_opacity = max(0.0, min(1.0, float(opacity)))
        self._collision_geometry_scale = max(0.001, float(geometry_scale))
        self._collision_length_scale = max(0.0, float(length_scale))
        self._collision_base_length_scale = max(0.0, float(base_length_scale))
        self.update()

    def set_trace_callback(self, callback: ViewportTraceCallback | None) -> None:
        self._trace_callback = callback

    @property
    def show_bones(self) -> bool:
        return self._show_bones

    @property
    def bone_vertex_count(self) -> int:
        if not self._show_bones:
            return 0
        return len(self._bone_segments_for_overlay()) * 2

    @property
    def hover_cut_token(self) -> str | None:
        return self._hover_cut_token

    def set_show_bones(self, value: bool) -> None:
        self._show_bones = bool(value)
        if not self._show_bones:
            self._hover_cut_token = None
        self.update()

    def set_selected_cut_tokens(self, joint_tokens: tuple[str, ...]) -> None:
        self._selected_cut_tokens = tuple(joint_tokens)
        if self._hover_cut_token is not None and self._cut_marker_position(self._hover_cut_token) is None:
            self._hover_cut_token = None
        self.update()

    def set_bone_pick_requires_control(self, value: bool) -> None:
        self._bone_pick_requires_control = bool(value)
        if self._bone_pick_requires_control and self._hover_cut_token is not None:
            self._hover_cut_token = None
            self.update()

    def set_shortcut_hints(self, hints: tuple[str, ...]) -> None:
        self._shortcut_hints = tuple(str(hint).strip() for hint in hints if str(hint).strip())
        self.update()

    def set_bone_segments(self, bone_segments: tuple[ViewportBoneSegment, ...]) -> None:
        if self._scene is None:
            return
        self._scene = replace(self._scene, bone_segments=tuple(bone_segments))
        if self._hover_cut_token is not None and self._cut_marker_position(self._hover_cut_token) is None:
            self._hover_cut_token = None
        self.update()

    def set_scene(
        self,
        scene: ViewportScene | None,
        *,
        frame_camera: bool = True,
        precompute_static: bool = False,
    ) -> None:
        if precompute_static and scene is not None and not any(draw.visibility_group == "collision" for draw in scene.draw_calls):
            self.set_precomputed_matcap_scene(
                scene,
                vertices=_build_scene_vertices(scene),
                min_point=scene.bounds.min_point,
                max_point=scene.bounds.max_point,
                frame_camera=frame_camera,
            )
            return
        self._visible_vertex_count_override = None
        self._scene = scene
        self._mesh = None
        self._precomputed_matcap_vertices = None
        self._collision_base_opacity = _scene_collision_opacity(scene)
        if self._hover_cut_token is not None and self._cut_marker_position(self._hover_cut_token) is None:
            self._hover_cut_token = None
        if scene is None:
            self._update_empty_metrics(frame_camera=frame_camera)
        else:
            self._update_bounds_metrics(
                scene.bounds.min_point,
                scene.bounds.max_point,
                frame_camera=frame_camera,
            )
        self._vertex_count = int(len(_build_scene_vertices(scene)) // MATCAP_VERTEX_STRIDE)
        self._grid_vertex_count = int(len(_build_grid_vertices(self._target, self._radius, self._ground_y)) // 4)
        self._trace_set_scene_event(scene)
        self._mesh_dirty = True
        self._grid_dirty = True
        self._upload_if_valid()

    def set_mesh(
        self,
        mesh: GeometryBuffer | None,
        *,
        frame_camera: bool = True,
        tint_alpha: float = DEFAULT_MATCAP_TINT_ALPHA,
    ) -> None:
        self._visible_vertex_count_override = None
        self._scene = None
        self._mesh = mesh
        self._precomputed_matcap_vertices = None
        self._mesh_tint_alpha = max(0.0, min(1.0, float(tint_alpha)))
        self._update_mesh_metrics(frame_camera=frame_camera)
        self._vertex_count = int(len(_build_viewport_vertices(self._mesh, tint_alpha=self._mesh_tint_alpha)) // MATCAP_VERTEX_STRIDE)
        self._grid_vertex_count = int(len(_build_grid_vertices(self._target, self._radius, self._ground_y)) // 4)
        self._mesh_dirty = True
        self._grid_dirty = True
        self._upload_if_valid()

    def set_precomputed_matcap_scene(
        self,
        scene: ViewportScene | None,
        *,
        vertices: np.ndarray,
        min_point: Vector3,
        max_point: Vector3,
        frame_camera: bool = True,
    ) -> None:
        self._visible_vertex_count_override = None
        self._scene = scene
        self._mesh = None
        self._precomputed_matcap_vertices = (
            vertices
            if vertices.dtype == np.float32 and vertices.flags.c_contiguous
            else np.ascontiguousarray(vertices, dtype=np.float32)
        )
        if self._hover_cut_token is not None and self._cut_marker_position(self._hover_cut_token) is None:
            self._hover_cut_token = None
        self._update_bounds_metrics(min_point, max_point, frame_camera=frame_camera)
        self._vertex_count = int(len(self._precomputed_matcap_vertices) // MATCAP_VERTEX_STRIDE)
        self._collision_vertex_count = 0
        self._grid_vertex_count = int(len(_build_grid_vertices(self._target, self._radius, self._ground_y)) // 4)
        self._trace_set_scene_event(scene)
        self._mesh_dirty = True
        self._grid_dirty = True
        self._upload_if_valid()

    def set_visible_vertex_count_override(self, vertex_count: int | None) -> None:
        resolved = None if vertex_count is None else max(0, int(vertex_count))
        if resolved == self._visible_vertex_count_override:
            return
        self._visible_vertex_count_override = resolved
        self.update()

    def _upload_if_valid(self) -> None:
        if self.isValid():
            self.makeCurrent()
            try:
                self._upload_mesh()
                self._upload_grid()
            finally:
                self.doneCurrent()
        self.update()

    def initializeGL(self) -> None:  # type: ignore[override]
        context = self.context()
        if self._gl_cleanup_context is not context:
            context.aboutToBeDestroyed.connect(self._release_gl_resources)
            self._gl_cleanup_context = context
        functions = context.functions()
        functions.initializeOpenGLFunctions()
        functions.glClearColor(0.0, 0.0, 0.0, 1.0)
        functions.glEnable(GL_DEPTH_TEST)
        self._program = _build_matcap_program()
        self._grid_program = _build_grid_program()
        self._vao = QOpenGLVertexArrayObject(self)
        self._vao.create()
        self._vertex_buffer = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self._vertex_buffer.create()
        self._collision_vao = QOpenGLVertexArrayObject(self)
        self._collision_vao.create()
        self._collision_vertex_buffer = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self._collision_vertex_buffer.create()
        self._grid_vao = QOpenGLVertexArrayObject(self)
        self._grid_vao.create()
        self._grid_buffer = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self._grid_buffer.create()
        self._mesh_dirty = True
        self._grid_dirty = True
        self._upload_mesh()
        self._upload_grid()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._release_gl_resources()
        super().closeEvent(event)

    def resizeGL(self, width: int, height: int) -> None:  # type: ignore[override]
        self.context().functions().glViewport(0, 0, max(1, width), max(1, height))

    def paintGL(self) -> None:  # type: ignore[override]
        functions = self.context().functions()
        functions.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        if self._mesh_dirty:
            self._upload_mesh()
        if self._grid_dirty:
            self._upload_grid()
        view = self._view_matrix()
        projection = self._projection_matrix()
        self._draw_grid(functions, projection * view)
        visible_vertex_count = self._visible_vertex_count()
        if self._program is not None and self._vao is not None and visible_vertex_count > 0:
            _prepare_opaque_mesh_draw(functions)
            if self._program.bind():
                _set_matcap_program_uniforms(
                    self._program,
                    functions=functions,
                    mvp=projection * view,
                    normal_matrix=view.normalMatrix(),
                    piece_tint_strength=self._matcap_tint_strength,
                    exploded_view_strength=self._matcap_exploded_view_strength(),
                )
                self._vao.bind()
                functions.glDrawArrays(GL_TRIANGLES, 0, visible_vertex_count)
                self._vao.release()
                self._program.release()
        if self._program is not None and self._collision_vao is not None and self._collision_vertex_count > 0:
            _prepare_ghost_mesh_draw(functions)
            if self._program.bind():
                _set_matcap_program_uniforms(
                    self._program,
                    functions=functions,
                    mvp=projection * view,
                    normal_matrix=view.normalMatrix(),
                    piece_tint_strength=self._collision_opacity / max(self._collision_base_opacity, 0.001),
                    exploded_view_strength=self._matcap_exploded_view_strength(),
                    geometry_scale=self._collision_geometry_scale,
                    capsule_length_scale=self._collision_length_scale,
                    capsule_base_length_scale=self._collision_base_length_scale,
                )
                self._collision_vao.bind()
                functions.glDrawArrays(GL_TRIANGLES, 0, self._collision_vertex_count)
                self._collision_vao.release()
                self._program.release()
            _finish_ghost_mesh_draw(functions)
        if self._show_bones:
            self._paint_bone_overlay()
        self._paint_shortcut_hints()

    def _matcap_exploded_view_strength(self) -> float:
        return self._exploded_view_strength

    def _visible_vertex_count(self) -> int:
        if self._visible_vertex_count_override is None:
            return self._vertex_count
        return max(0, min(self._vertex_count, self._visible_vertex_count_override))

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._show_bones
            and (not self._bone_pick_requires_control or event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        ):
            token = self._hover_cut_token or self.pick_bone_segment_child_token(event.position().x(), event.position().y())
            if token:
                self.on_bone_clicked(token, event.modifiers())
                self.on_bone_cut_toggled(token)
                event.accept()
                return
        if event.button() == Qt.MouseButton.LeftButton:
            self._last_mouse = event.position().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if (
            self._show_bones
            and not event.buttons()
            and (not self._bone_pick_requires_control or event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        ):
            token = self.pick_bone_segment_child_token(event.position().x(), event.position().y())
            if token != self._hover_cut_token:
                self._hover_cut_token = token
                self.update()
            event.accept()
            return
        if (
            self._hover_cut_token is not None
            and self._bone_pick_requires_control
            and not (event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        ):
            self._hover_cut_token = None
            self.update()
        if self._last_mouse is not None and event.buttons() & Qt.MouseButton.LeftButton:
            current = event.position().toPoint()
            delta = current - self._last_mouse
            self._last_mouse = current
            self._yaw -= delta.x() * 0.01
            self._pitch = max(math.radians(-82.0), min(math.radians(82.0), self._pitch + delta.y() * 0.01))
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self._last_mouse = None
        super().mouseReleaseEvent(event)

    def keyReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Control and self._hover_cut_token is not None:
            self._hover_cut_token = None
            self.update()
        super().keyReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        if self._hover_cut_token is not None:
            self._hover_cut_token = None
            self.update()
        super().leaveEvent(event)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        steps = event.angleDelta().y() / 120.0
        self._distance = max(self._radius * 0.35, self._distance * (0.88 ** steps))
        self.update()
        event.accept()

    def pick_bone_segment_child_token(self, x: float, y: float, *, max_distance: float = 14.0) -> str | None:
        bone_segments = self._bone_segments_for_overlay()
        if not bone_segments:
            return None
        best: tuple[float, str, str] | None = None
        for segment in bone_segments:
            segment_start, segment_end = self._exploded_bone_segment_points(segment)
            parent = self._project_point_to_screen(segment_start)
            child = self._project_point_to_screen(segment_end)
            if parent is None or child is None:
                continue
            distance, segment_t = _distance_to_screen_segment(float(x), float(y), parent, child)
            token = _format_manual_segment_cut_token(
                segment.parent_token,
                segment.child_token,
                _clamp_manual_segment_t(segment_t),
            )
            candidate = (distance, segment.child_token, token)
            if best is None or candidate < best:
                best = candidate
        if best is None or best[0] > max_distance:
            return None
        return best[2]

    def _update_empty_metrics(self, *, frame_camera: bool) -> None:
        if frame_camera:
            self._target = Vector3(0.0, 0.0, 0.0)
            self._radius = 1.0
            self._distance = 3.0
        self._ground_y = 0.0

    def _trace_set_scene_event(self, scene: ViewportScene | None) -> None:
        self._trace_viewport_event(
            "viewport.set_scene",
            scene_id="" if scene is None else scene.scene_id,
            batch_count=0 if scene is None else len(scene.mesh_batches),
            draw_call_count=0 if scene is None else len(scene.draw_calls),
            bone_segment_count=len(self._bone_segments_for_overlay()),
            vertex_count=self._vertex_count,
        )

    def _update_bounds_metrics(self, min_point: Vector3, max_point: Vector3, *, frame_camera: bool) -> None:
        self._ground_y = float(min_point.y)
        self._radius = max(
            0.001,
            math.sqrt(
                (max_point.x - min_point.x) ** 2
                + (max_point.y - min_point.y) ** 2
                + (max_point.z - min_point.z) ** 2
            )
            * 0.5,
        )
        if frame_camera:
            self._target = Vector3(
                (min_point.x + max_point.x) * 0.5,
                (min_point.y + max_point.y) * 0.5,
                (min_point.z + max_point.z) * 0.5,
            )
            self._distance = self._radius * 3.0

    def _update_mesh_metrics(self, *, frame_camera: bool) -> None:
        if self._mesh is None or self._mesh.point_count == 0:
            self._update_empty_metrics(frame_camera=frame_camera)
            return
        points = list(_points(self._mesh))
        min_x = min(point.x for point in points)
        min_y = min(point.y for point in points)
        min_z = min(point.z for point in points)
        max_x = max(point.x for point in points)
        max_y = max(point.y for point in points)
        max_z = max(point.z for point in points)
        self._update_bounds_metrics(
            Vector3(min_x, min_y, min_z),
            Vector3(max_x, max_y, max_z),
            frame_camera=frame_camera,
        )

    def _current_matcap_vertices(self) -> np.ndarray:
        if self._precomputed_matcap_vertices is not None:
            return self._precomputed_matcap_vertices
        if self._scene is not None:
            return _build_scene_vertices(self._scene, collision=False)
        return _build_viewport_vertices(self._mesh, tint_alpha=self._mesh_tint_alpha)

    def _current_collision_vertices(self) -> np.ndarray:
        if self._precomputed_matcap_vertices is not None or self._scene is None:
            return np.asarray([], dtype=np.float32)
        return _build_scene_vertices(self._scene, collision=True)

    def _upload_mesh(self) -> None:
        if (
            self._program is None
            or self._vertex_buffer is None
            or self._vao is None
            or self._collision_vertex_buffer is None
            or self._collision_vao is None
        ):
            return
        vertices = self._current_matcap_vertices()
        collision_vertices = self._current_collision_vertices()
        self._vertex_count = int(len(vertices) // MATCAP_VERTEX_STRIDE)
        self._collision_vertex_count = int(len(collision_vertices) // MATCAP_VERTEX_STRIDE)
        self._trace_viewport_event(
            "viewport.upload_begin",
            vertex_count=self._vertex_count + self._collision_vertex_count,
            byte_count=int(vertices.nbytes + collision_vertices.nbytes),
            scene_id="" if self._scene is None else self._scene.scene_id,
        )
        program_bound = _upload_matcap_vertices(
            program=self._program,
            vertex_buffer=self._vertex_buffer,
            vao=self._vao,
            vertices=vertices,
        )
        if program_bound:
            program_bound = _upload_matcap_vertices(
                program=self._program,
                vertex_buffer=self._collision_vertex_buffer,
                vao=self._collision_vao,
                vertices=collision_vertices,
            )
        if not program_bound:
            self._trace_viewport_event(
                "viewport.upload_end",
                vertex_count=self._vertex_count + self._collision_vertex_count,
                byte_count=int(vertices.nbytes + collision_vertices.nbytes),
                program_bound=False,
            )
            return
        self._mesh_dirty = False
        self._trace_viewport_event(
            "viewport.upload_end",
            vertex_count=self._vertex_count + self._collision_vertex_count,
            byte_count=int(vertices.nbytes + collision_vertices.nbytes),
            program_bound=True,
        )

    def _upload_grid(self) -> None:
        if self._grid_program is None or self._grid_buffer is None or self._grid_vao is None:
            return
        vertices = _build_grid_vertices(self._target, self._radius, self._ground_y)
        self._grid_vertex_count = int(len(vertices) // 4)
        self._grid_vao.bind()
        self._grid_buffer.bind()
        self._grid_buffer.allocate(vertices.tobytes(), vertices.nbytes)
        if not self._grid_program.bind():
            self._grid_buffer.release()
            self._grid_vao.release()
            return
        stride = 4 * 4
        position_location = self._grid_program.attributeLocation("position")
        alpha_location = self._grid_program.attributeLocation("alpha")
        self._grid_program.enableAttributeArray(position_location)
        self._grid_program.setAttributeBuffer(position_location, GL_FLOAT, 0, 3, stride)
        self._grid_program.enableAttributeArray(alpha_location)
        self._grid_program.setAttributeBuffer(alpha_location, GL_FLOAT, 12, 1, stride)
        self._grid_program.release()
        self._grid_buffer.release()
        self._grid_vao.release()
        self._grid_dirty = False

    def _draw_grid(self, functions, mvp: QMatrix4x4) -> None:
        if self._grid_program is None or self._grid_vao is None or self._grid_vertex_count <= 0:
            return
        functions.glEnable(GL_BLEND)
        functions.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        functions.glLineWidth(1.35)
        if not self._grid_program.bind():
            functions.glDisable(GL_BLEND)
            return
        self._grid_program.setUniformValue("mvp", mvp)
        self._grid_vao.bind()
        functions.glDrawArrays(GL_LINES, 0, self._grid_vertex_count)
        self._grid_vao.release()
        self._grid_program.release()
        functions.glDisable(GL_BLEND)

    def _view_matrix(self) -> QMatrix4x4:
        eye = self._camera_eye()
        matrix = QMatrix4x4()
        matrix.lookAt(
            QVector3D(float(eye.x), float(eye.y), float(eye.z)),
            QVector3D(float(self._target.x), float(self._target.y), float(self._target.z)),
            QVector3D(0.0, 1.0, 0.0),
        )
        return matrix

    def _projection_matrix(self) -> QMatrix4x4:
        matrix = QMatrix4x4()
        aspect = max(0.001, self.width() / max(1, self.height()))
        matrix.perspective(42.0, aspect, max(0.001, self._radius * 0.01), max(10.0, self._radius * 20.0))
        return matrix

    def _project_point_to_screen(self, point: Vector3) -> tuple[float, float] | None:
        width = max(1, self.width())
        height = max(1, self.height())
        mapped = (self._projection_matrix() * self._view_matrix()).map(
            QVector3D(float(point.x), float(point.y), float(point.z))
        )
        ndc_x = float(mapped.x())
        ndc_y = float(mapped.y())
        if ndc_x < -1.5 or ndc_x > 1.5 or ndc_y < -1.5 or ndc_y > 1.5:
            return None
        return ((ndc_x + 1.0) * 0.5 * width, (1.0 - ndc_y) * 0.5 * height)

    def _camera_eye(self) -> Vector3:
        cos_pitch = math.cos(self._pitch)
        offset = Vector3(
            self._distance * math.sin(self._yaw) * cos_pitch,
            self._distance * math.sin(self._pitch),
            self._distance * math.cos(self._yaw) * cos_pitch,
        )
        return Vector3(self._target.x + offset.x, self._target.y + offset.y, self._target.z + offset.z)

    def _bone_segments_for_overlay(self) -> tuple[ViewportBoneSegment, ...]:
        if self._scene is None:
            return ()
        return self._scene.bone_segments

    def _bone_segment_by_child_token(self, joint_token: str) -> ViewportBoneSegment | None:
        for segment in self._bone_segments_for_overlay():
            if segment.child_token == joint_token:
                return segment
        return None

    def _bone_segment_by_edge(self, parent_token: str, child_token: str) -> ViewportBoneSegment | None:
        for segment in self._bone_segments_for_overlay():
            if segment.parent_token == parent_token and segment.child_token == child_token:
                return segment
        return None

    def _selected_cut_on_segment(self, segment: ViewportBoneSegment) -> bool:
        for cut_token in self._selected_cut_tokens:
            segment_cut = _manual_segment_cut_parts(cut_token)
            if segment_cut is None:
                if cut_token == segment.child_token:
                    return True
                continue
            parent_token, child_token, _segment_t = segment_cut
            if parent_token == segment.parent_token and child_token == segment.child_token:
                return True
        return False

    def _cut_marker_position(self, cut_token: str) -> tuple[float, float] | None:
        segment_cut = _manual_segment_cut_parts(cut_token)
        if segment_cut is not None:
            parent_token, child_token, segment_t = segment_cut
            segment = self._bone_segment_by_edge(parent_token, child_token)
            if segment is None:
                return None
            segment_start, segment_end = self._exploded_bone_segment_points(segment)
            return self._project_point_to_screen(_lerp_vector3(segment_start, segment_end, segment_t))
        segment = self._bone_segment_by_child_token(cut_token)
        if segment is None:
            return None
        segment_start, _segment_end = self._exploded_bone_segment_points(segment)
        return self._project_point_to_screen(segment_start)

    def _paint_bone_overlay(self) -> None:
        bone_segments = self._bone_segments_for_overlay()
        if not bone_segments:
            return
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            for segment in bone_segments:
                segment_start, segment_end = self._exploded_bone_segment_points(segment)
                parent = self._project_point_to_screen(segment_start)
                child = self._project_point_to_screen(segment_end)
                if parent is None or child is None:
                    continue
                selected = segment.selected or self._selected_cut_on_segment(segment)
                halo = QPen(QColor(6, 10, 12, 210), 7.0 if selected else 6.0)
                halo.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(halo)
                painter.drawLine(int(round(parent[0])), int(round(parent[1])), int(round(child[0])), int(round(child[1])))
                pen = QPen(_qcolor_from_color4(segment.color, alpha=255 if selected else 230), 4.5 if selected else 3.6)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawLine(int(round(parent[0])), int(round(parent[1])), int(round(child[0])), int(round(child[1])))
                if segment.selected:
                    painter.setPen(QPen(QColor(255, 245, 185, 245), 1.0))
                    painter.drawText(int(round(child[0])) + 5, int(round(child[1])) - 5, segment.child_token)
            for cut_token in self._selected_cut_tokens:
                marker_point = self._cut_marker_position(cut_token)
                if marker_point is not None:
                    _paint_cut_marker(painter, marker_point, QColor(255, 245, 185, 245), radius=6.5, width=2.0)
            if self._hover_cut_token is not None:
                hover_point = self._cut_marker_position(self._hover_cut_token)
                if hover_point is not None:
                    _paint_cut_marker(painter, hover_point, QColor(155, 235, 255, 245), radius=8.5, width=2.2)
        finally:
            painter.end()

    def _paint_shortcut_hints(self) -> None:
        if not self._shortcut_hints:
            return
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            text = "   ".join(self._shortcut_hints)
            font = painter.font()
            font.setPointSize(max(8, font.pointSize() - 1))
            painter.setFont(font)
            metrics = painter.fontMetrics()
            margin = 10
            width = metrics.horizontalAdvance(text)
            height = metrics.height()
            x = max(margin, self.width() - width - margin)
            y = max(margin + height, self.height() - margin)
            painter.setPen(QPen(QColor(235, 240, 235, 145), 1.0))
            painter.drawText(x, y, text)
        finally:
            painter.end()

    def _exploded_bone_segment_points(self, segment: ViewportBoneSegment) -> tuple[Vector3, Vector3]:
        offset = _scale_vector3(segment.explode_direction, self._exploded_view_strength)
        return _add_vector3(segment.start, offset), _add_vector3(segment.end, offset)

    def _release_gl_resources(self) -> None:
        has_resources = any(
            resource is not None
            for resource in (
                self._program,
                self._vertex_buffer,
                self._vao,
                self._collision_vertex_buffer,
                self._collision_vao,
                self._grid_program,
                self._grid_buffer,
                self._grid_vao,
            )
        )
        if not has_resources:
            return
        self._trace_viewport_event(
            "viewport.context_lost",
            had_mesh=bool(self._mesh or self._scene),
            vertex_count=self._vertex_count,
        )

        made_current = False
        if self.isValid():
            self.makeCurrent()
            made_current = True
        try:
            for buffer in (self._vertex_buffer, self._collision_vertex_buffer, self._grid_buffer):
                if buffer is not None:
                    buffer.destroy()
            for vao in (self._vao, self._collision_vao, self._grid_vao):
                if vao is not None:
                    vao.destroy()
            for program in (self._program, self._grid_program):
                if program is not None:
                    program.release()
                    program.removeAllShaders()
        finally:
            self._program = None
            self._vertex_buffer = None
            self._vao = None
            self._collision_vertex_buffer = None
            self._collision_vao = None
            self._grid_program = None
            self._grid_buffer = None
            self._grid_vao = None
            self._vertex_count = 0
            self._visible_vertex_count_override = None
            self._grid_vertex_count = 0
            self._mesh_dirty = bool(self._mesh or self._scene)
            self._grid_dirty = True
            if made_current:
                self.doneCurrent()

    def _trace_viewport_event(self, kind: str, **data: object) -> None:
        if self._trace_callback is None:
            return
        try:
            self._trace_callback(kind, dict(data))
        except Exception:
            pass


class ProxyViewport(MatcapViewport):
    pass


def _build_scene_vertices(scene: ViewportScene | None, *, collision: bool = False) -> np.ndarray:
    if scene is None:
        return np.asarray([], dtype=np.float32)
    batch_by_id = {batch.batch_id: batch for batch in scene.mesh_batches}
    length_scales = _collision_length_scales(scene, batch_by_id) if collision else {}
    vertices: list[float] = []
    for draw_call in scene.draw_calls:
        if (draw_call.visibility_group == "collision") != collision:
            continue
        batch = batch_by_id.get(draw_call.batch_id)
        if batch is None:
            continue
        _append_draw_call_vertices(
            vertices,
            batch.mesh,
            draw_call=draw_call,
            color=draw_call.tint or batch.color,
            length_scale=length_scales.get(draw_call.draw_id, 0.0),
        )
    return np.asarray(vertices, dtype=np.float32)


def _collision_length_scales(
    scene: ViewportScene,
    batch_by_id: dict[str, ViewportMeshBatch],
) -> dict[str, float]:
    lengths: list[tuple[str, float]] = []
    for draw_call in scene.draw_calls:
        if draw_call.visibility_group != "collision":
            continue
        batch = batch_by_id.get(draw_call.batch_id)
        if batch is None:
            continue
        points = tuple(_transform_scene_point(point, draw_call) for point in _points(batch.mesh))
        lengths.append((draw_call.draw_id, _collision_axis_length(points)))
    reference = max((length for _draw_id, length in lengths), default=0.0)
    if reference <= 1e-8:
        return {}
    return {draw_id: max(0.0, min(1.0, length / reference)) for draw_id, length in lengths}


def _scene_collision_opacity(scene: ViewportScene | None) -> float:
    if scene is None:
        return 0.25
    batch_by_id = {batch.batch_id: batch for batch in scene.mesh_batches}
    for draw_call in scene.draw_calls:
        if draw_call.visibility_group != "collision":
            continue
        batch = batch_by_id.get(draw_call.batch_id)
        color = draw_call.tint or (batch.color if batch is not None else None)
        if color is not None:
            return max(0.001, float(color.a))
    return 0.25


def _append_draw_call_vertices(
    vertices: list[float],
    mesh: GeometryBuffer,
    *,
    draw_call: ViewportDrawCall,
    color: Color4 | None,
    length_scale: float = 0.0,
) -> None:
    if mesh.point_count == 0:
        return
    points = list(_points(mesh))
    colors = _point_colors(mesh)
    transformed_points = tuple(_transform_scene_point(point, draw_call) for point in points)
    scale_origins = _draw_call_scale_origins(transformed_points, mesh, draw_call)
    offset = 0
    for count in mesh.face_vertex_counts:
        indices = [int(mesh.face_vertex_indices[offset + index]) for index in range(count)]
        offset += count
        if count < 3:
            continue
        for index in range(1, count - 1):
            triangle = tuple(
                transformed_points[point_index]
                for point_index in (indices[0], indices[index], indices[index + 1])
            )
            normal = _face_normal(triangle)  # type: ignore[arg-type]
            for point_index, point in zip((indices[0], indices[index], indices[index + 1]), triangle):
                source_color = color or _color4_from_tuple(colors[point_index])
                scale_origin = scale_origins[point_index]
                vertices.extend(
                    (
                        point.x,
                        point.y,
                        point.z,
                        normal.x,
                        normal.y,
                        normal.z,
                        float(source_color.r),
                        float(source_color.g),
                        float(source_color.b),
                        float(source_color.a),
                        float(draw_call.explode_direction.x),
                        float(draw_call.explode_direction.y),
                        float(draw_call.explode_direction.z),
                        scale_origin.x,
                        scale_origin.y,
                        scale_origin.z,
                        float(length_scale),
                    )
                )


def _draw_call_scale_origins(
    points: tuple[Vector3, ...],
    mesh: GeometryBuffer,
    draw_call: ViewportDrawCall,
) -> tuple[Vector3, ...]:
    if not points:
        return ()
    if draw_call.visibility_group == "collision" and _is_capsule_collision_mesh(mesh) and len(points) >= 2:
        start = points[0]
        end = points[-1]
        return tuple(_closest_point_on_segment(point, start, end) for point in points)
    if draw_call.visibility_group == "collision":
        center = _point_bounds_center(points)
        return tuple(center for _point in points)
    return points


def _is_capsule_collision_mesh(mesh: GeometryBuffer) -> bool:
    return str(mesh.name).startswith("UCP_")


def _point_bounds_center(points: tuple[Vector3, ...]) -> Vector3:
    return Vector3(
        (min(point.x for point in points) + max(point.x for point in points)) * 0.5,
        (min(point.y for point in points) + max(point.y for point in points)) * 0.5,
        (min(point.z for point in points) + max(point.z for point in points)) * 0.5,
    )


def _collision_axis_length(points: tuple[Vector3, ...]) -> float:
    if len(points) < 2:
        return 0.0
    return math.sqrt(
        (points[-1].x - points[0].x) ** 2
        + (points[-1].y - points[0].y) ** 2
        + (points[-1].z - points[0].z) ** 2
    )


def _closest_point_on_segment(point: Vector3, start: Vector3, end: Vector3) -> Vector3:
    ax, ay, az = point.x - start.x, point.y - start.y, point.z - start.z
    bx, by, bz = end.x - start.x, end.y - start.y, end.z - start.z
    denom = bx * bx + by * by + bz * bz
    if denom <= 1e-12:
        return start
    t = max(0.0, min(1.0, (ax * bx + ay * by + az * bz) / denom))
    return Vector3(start.x + bx * t, start.y + by * t, start.z + bz * t)


def _build_viewport_vertices(
    mesh: GeometryBuffer | None,
    *,
    tint_alpha: float = DEFAULT_MATCAP_TINT_ALPHA,
) -> np.ndarray:
    if mesh is None or mesh.point_count == 0:
        return np.asarray([], dtype=np.float32)
    points = list(_points(mesh))
    colors = _point_colors(mesh)
    vertices: list[float] = []
    offset = 0
    for count in mesh.face_vertex_counts:
        indices = [int(mesh.face_vertex_indices[offset + index]) for index in range(count)]
        offset += count
        if count < 3:
            continue
        for index in range(1, count - 1):
            triangle = (points[indices[0]], points[indices[index]], points[indices[index + 1]])
            normal = _face_normal(triangle)
            for point_index, point in zip((indices[0], indices[index], indices[index + 1]), triangle):
                color = colors[point_index]
                vertices.extend(
                    (
                        point.x,
                        point.y,
                        point.z,
                        normal.x,
                        normal.y,
                        normal.z,
                        color[0],
                        color[1],
                        color[2],
                        max(0.0, min(1.0, float(tint_alpha))),
                        0.0,
                        0.0,
                        0.0,
                        point.x,
                        point.y,
                        point.z,
                        0.0,
                    )
                )
    return np.asarray(vertices, dtype=np.float32)


def _point_colors(mesh: GeometryBuffer) -> tuple[tuple[float, float, float, float], ...]:
    if mesh.vertex_color_count >= mesh.point_count:
        return tuple(
            (
                float(mesh.vertex_color_components[index]),
                float(mesh.vertex_color_components[index + 1]),
                float(mesh.vertex_color_components[index + 2]),
                float(mesh.vertex_color_components[index + 3]),
            )
            for index in range(0, mesh.point_count * 4, 4)
        )
    return ((1.0, 1.0, 1.0, 1.0),) * mesh.point_count


def _build_grid_vertices(target: Vector3, radius: float, ground_y: float) -> np.ndarray:
    step = 1.0
    half_extent = int(max(8, min(80, math.ceil(radius * 5.0))))
    origin_x = math.floor(target.x)
    origin_z = math.floor(target.z)
    y = float(ground_y) - max(0.002, radius * 0.001)
    fade_radius = max(1.0, float(half_extent))
    vertices: list[float] = []

    def alpha_at(x: float, z: float) -> float:
        distance = math.sqrt((x - target.x) ** 2 + (z - target.z) ** 2)
        fade = max(0.0, 1.0 - distance / fade_radius)
        return 0.28 * fade * fade

    def add_vertex(x: float, z: float) -> None:
        vertices.extend((x, y, z, alpha_at(x, z)))

    for ix in range(-half_extent, half_extent + 1):
        x = origin_x + ix * step
        for iz in range(-half_extent, half_extent):
            z0 = origin_z + iz * step
            z1 = z0 + step
            add_vertex(x, z0)
            add_vertex(x, z1)

    for iz in range(-half_extent, half_extent + 1):
        z = origin_z + iz * step
        for ix in range(-half_extent, half_extent):
            x0 = origin_x + ix * step
            x1 = x0 + step
            add_vertex(x0, z)
            add_vertex(x1, z)

    return np.asarray(vertices, dtype=np.float32)


def _build_matcap_program() -> QOpenGLShaderProgram:
    program = QOpenGLShaderProgram()
    if not program.addShaderFromSourceCode(
        QOpenGLShader.ShaderTypeBit.Vertex,
        """
        attribute vec3 position;
        attribute vec3 normal;
        attribute vec4 pieceTint;
        attribute vec3 explodeOffset;
        attribute vec3 scaleOrigin;
        attribute float lengthScale;
        uniform mat4 mvp;
        uniform mat3 normalMatrix;
        uniform float explodeStrength;
        uniform float pieceTintStrength;
        uniform float geometryScale;
        uniform float capsuleLengthScale;
        uniform float capsuleBaseLengthScale;
        varying vec3 viewNormal;
        varying vec4 pieceColor;
        void main() {
            viewNormal = normalize(normalMatrix * normal);
            pieceColor = vec4(pieceTint.rgb, clamp(pieceTint.a * max(pieceTintStrength, 0.0), 0.0, 1.0));
            float baseLength = max(0.001, 1.0 + max(capsuleBaseLengthScale, 0.0) * lengthScale);
            float currentLength = 1.0 + max(capsuleLengthScale, 0.0) * lengthScale;
            vec3 scaledPosition = scaleOrigin + (position - scaleOrigin) * max(geometryScale, 0.001) * currentLength / baseLength;
            gl_Position = mvp * vec4(scaledPosition + explodeOffset * explodeStrength, 1.0);
        }
        """,
    ):
        raise RuntimeError(program.log())
    if not program.addShaderFromSourceCode(
        QOpenGLShader.ShaderTypeBit.Fragment,
        """
        varying vec3 viewNormal;
        varying vec4 pieceColor;
        void main() {
            vec3 n = normalize(viewNormal);
            vec2 uv = n.xy * 0.5 + 0.5;
            float facing = clamp(n.z * 0.5 + 0.5, 0.0, 1.0);
            float upper = smoothstep(0.15, 0.95, uv.y);
            float side = 1.0 - smoothstep(0.45, 1.0, abs(uv.x - 0.5) * 2.0);
            float rim = pow(1.0 - abs(n.z), 2.35);
            vec3 shadow = vec3(0.10, 0.105, 0.11);
            vec3 mid = vec3(0.55, 0.55, 0.51);
            vec3 high = vec3(0.96, 0.94, 0.82);
            vec3 color = mix(shadow, mid, facing);
            color = mix(color, high, upper * side * 0.74);
            color += rim * vec3(0.15, 0.16, 0.18);
            color = pow(color, vec3(0.88));
            float luma = dot(color, vec3(0.299, 0.587, 0.114));
            vec3 tintedMatcap = pieceColor.rgb * clamp(0.28 + luma * 1.22, 0.0, 1.35);
            color = mix(color, tintedMatcap, clamp(pieceColor.a, 0.0, 1.0));
            gl_FragColor = vec4(color + rim * pieceColor.rgb * 0.45, max(0.05, pieceColor.a));
        }
        """,
    ):
        raise RuntimeError(program.log())
    if not program.link():
        raise RuntimeError(program.log())
    return program


def _set_matcap_program_uniforms(
    program: QOpenGLShaderProgram,
    *,
    functions,
    mvp: QMatrix4x4,
    normal_matrix,
    piece_tint_strength: float,
    exploded_view_strength: float = 0.0,
    geometry_scale: float = 1.0,
    capsule_length_scale: float = 0.0,
    capsule_base_length_scale: float = 0.0,
) -> None:
    program.setUniformValue("mvp", mvp)
    program.setUniformValue("normalMatrix", normal_matrix)
    tint_strength_location = program.uniformLocation("pieceTintStrength")
    if tint_strength_location >= 0:
        functions.glUniform1f(tint_strength_location, float(max(0.0, piece_tint_strength)))
    explode_strength_location = program.uniformLocation("explodeStrength")
    if explode_strength_location >= 0:
        functions.glUniform1f(explode_strength_location, float(max(0.0, min(2.0, exploded_view_strength))))
    geometry_scale_location = program.uniformLocation("geometryScale")
    if geometry_scale_location >= 0:
        functions.glUniform1f(geometry_scale_location, float(max(0.001, geometry_scale)))
    capsule_length_scale_location = program.uniformLocation("capsuleLengthScale")
    if capsule_length_scale_location >= 0:
        functions.glUniform1f(capsule_length_scale_location, float(max(0.0, capsule_length_scale)))
    capsule_base_length_scale_location = program.uniformLocation("capsuleBaseLengthScale")
    if capsule_base_length_scale_location >= 0:
        functions.glUniform1f(capsule_base_length_scale_location, float(max(0.0, capsule_base_length_scale)))


def _prepare_opaque_mesh_draw(functions) -> None:
    functions.glDisable(GL_BLEND)
    functions.glEnable(GL_DEPTH_TEST)
    functions.glDepthMask(True)


def _prepare_ghost_mesh_draw(functions) -> None:
    functions.glEnable(GL_BLEND)
    functions.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
    functions.glEnable(GL_DEPTH_TEST)
    functions.glEnable(GL_CULL_FACE)
    functions.glCullFace(GL_BACK)
    functions.glDepthMask(False)


def _finish_ghost_mesh_draw(functions) -> None:
    functions.glDepthMask(True)
    functions.glDisable(GL_CULL_FACE)
    functions.glDisable(GL_BLEND)


def _build_grid_program() -> QOpenGLShaderProgram:
    program = QOpenGLShaderProgram()
    if not program.addShaderFromSourceCode(
        QOpenGLShader.ShaderTypeBit.Vertex,
        """
        attribute vec3 position;
        attribute float alpha;
        uniform mat4 mvp;
        varying float gridAlpha;
        void main() {
            gridAlpha = alpha;
            gl_Position = mvp * vec4(position, 1.0);
        }
        """,
    ):
        raise RuntimeError(program.log())
    if not program.addShaderFromSourceCode(
        QOpenGLShader.ShaderTypeBit.Fragment,
        """
        varying float gridAlpha;
        void main() {
            gl_FragColor = vec4(0.48, 0.56, 0.58, gridAlpha);
        }
        """,
    ):
        raise RuntimeError(program.log())
    if not program.link():
        raise RuntimeError(program.log())
    return program


def _points(mesh: GeometryBuffer):
    for index in range(0, len(mesh.point_components), 3):
        yield Vector3(mesh.point_components[index], mesh.point_components[index + 1], mesh.point_components[index + 2])


def _color4_from_tuple(color: tuple[float, float, float, float]) -> Color4:
    return Color4(color[0], color[1], color[2], color[3])


def _transform_scene_point(point: Vector3, draw_call: ViewportDrawCall) -> Vector3:
    scaled = Vector3(
        point.x * draw_call.scale.x,
        point.y * draw_call.scale.y,
        point.z * draw_call.scale.z,
    )
    rotated = _rotate_vector(draw_call.orientation, scaled)
    return Vector3(
        rotated.x + draw_call.translate.x,
        rotated.y + draw_call.translate.y,
        rotated.z + draw_call.translate.z,
    )


def _rotate_vector(q: Quaternion, point: Vector3) -> Vector3:
    tx = 2.0 * (q.j * point.z - q.k * point.y)
    ty = 2.0 * (q.k * point.x - q.i * point.z)
    tz = 2.0 * (q.i * point.y - q.j * point.x)
    return Vector3(
        point.x + q.real * tx + (q.j * tz - q.k * ty),
        point.y + q.real * ty + (q.k * tx - q.i * tz),
        point.z + q.real * tz + (q.i * ty - q.j * tx),
    )


def _face_normal(points: tuple[Vector3, Vector3, Vector3]) -> Vector3:
    a, b, c = points
    ux = b.x - a.x
    uy = b.y - a.y
    uz = b.z - a.z
    vx = c.x - a.x
    vy = c.y - a.y
    vz = c.z - a.z
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length <= 0.0:
        return Vector3(0.0, 0.0, 1.0)
    return Vector3(nx / length, ny / length, nz / length)


def _distance_to_screen_segment(
    x: float,
    y: float,
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[float, float]:
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-8:
        return math.sqrt((x - sx) ** 2 + (y - sy) ** 2), 0.5
    t = max(0.0, min(1.0, ((x - sx) * dx + (y - sy) * dy) / length_squared))
    px = sx + t * dx
    py = sy + t * dy
    return math.sqrt((x - px) ** 2 + (y - py) ** 2), t


def _clamp_manual_segment_t(segment_t: float) -> float:
    return max(0.02, min(0.98, float(segment_t)))


def _format_manual_segment_cut_token(parent_joint_token: str, child_joint_token: str, segment_t: float) -> str:
    return f"{parent_joint_token.strip()}->{child_joint_token.strip()}@{float(segment_t):.3f}"


def _manual_segment_cut_parts(cut_token: str) -> tuple[str, str, float] | None:
    if "->" not in cut_token or "@" not in cut_token:
        return None
    try:
        edge, raw_t = cut_token.rsplit("@", 1)
        parent, child = edge.split("->", 1)
        return parent.strip(), child.strip(), float(raw_t)
    except ValueError:
        return None


def _lerp_vector3(start: Vector3, end: Vector3, t: float) -> Vector3:
    return Vector3(
        start.x + (end.x - start.x) * t,
        start.y + (end.y - start.y) * t,
        start.z + (end.z - start.z) * t,
    )


def _add_vector3(left: Vector3, right: Vector3) -> Vector3:
    return Vector3(left.x + right.x, left.y + right.y, left.z + right.z)


def _scale_vector3(vector: Vector3, scale: float) -> Vector3:
    return Vector3(vector.x * scale, vector.y * scale, vector.z * scale)


def _qcolor_from_color4(color: Color4, *, alpha: int) -> QColor:
    return QColor(
        max(0, min(255, int(round(float(color.r) * 255)))),
        max(0, min(255, int(round(float(color.g) * 255)))),
        max(0, min(255, int(round(float(color.b) * 255)))),
        max(0, min(255, int(alpha))),
    )


def _paint_cut_marker(
    painter: QPainter,
    screen_point: tuple[float, float],
    color: QColor,
    *,
    radius: float,
    width: float,
) -> None:
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(4, 8, 10, 230), width + 2.0))
    x = float(screen_point[0])
    y = float(screen_point[1])
    painter.drawEllipse(int(round(x - radius)), int(round(y - radius)), int(round(radius * 2)), int(round(radius * 2)))
    painter.setPen(QPen(color, width))
    painter.drawEllipse(int(round(x - radius)), int(round(y - radius)), int(round(radius * 2)), int(round(radius * 2)))
