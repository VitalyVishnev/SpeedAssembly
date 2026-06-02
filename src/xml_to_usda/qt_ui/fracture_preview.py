"""Qt-facing fracture preview payload preparation.

Layer: UI adapter.

This module converts `FracturePreviewResult` into a flat colored triangle
payload that an OpenGL widget can draw without knowing fracture planning rules.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass
from math import sqrt

from PySide6.QtWidgets import QDialog, QFrame, QGridLayout, QLabel, QVBoxLayout

from ..fracture_preview_service import FracturePreviewResult
from ..models import Color4, GeometryBuffer, Quaternion, Vector3
from .proxy_preview import MatcapViewport


FRACTURE_VERTEX_STRIDE = 10
FRACTURE_MATCAP_TINT_STRENGTH = 0.28


@dataclass(frozen=True)
class FractureViewportMesh:
    name: str
    vertex_components: array
    triangle_count: int
    piece_count: int
    instance_count: int


class FracturePreviewDialog(QDialog):
    def __init__(self, *, preview: FracturePreviewResult, parent=None) -> None:
        super().__init__(parent)
        self.current_preview = preview
        self.viewport_mesh = build_fracture_viewport_mesh(preview)
        self.setWindowTitle("Fracture Preview")
        self.resize(1040, 720)

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.viewport = FractureViewport(self)
        layout.addWidget(self.viewport, 0, 0)
        self.viewport.set_mesh(self.viewport_mesh)

        settings_panel = QFrame(self)
        settings_panel.setObjectName("PanelCard")
        settings_panel.setFixedWidth(260)
        settings_layout = QVBoxLayout(settings_panel)
        settings_layout.setContentsMargins(14, 14, 14, 14)
        settings_layout.setSpacing(8)

        title = QLabel("Fracturing", settings_panel)
        title.setStyleSheet("font-weight: 700;")
        settings_layout.addWidget(title)

        self.summary_label = QLabel(
            (
                f"{self.viewport_mesh.piece_count} pieces\n"
                f"{self.viewport_mesh.triangle_count} preview triangles\n"
                f"{self.viewport_mesh.instance_count} repeated instances"
            ),
            settings_panel,
        )
        self.summary_label.setWordWrap(True)
        settings_layout.addWidget(self.summary_label)
        settings_layout.addStretch(1)

        layout.addWidget(settings_panel, 0, 1)


class FractureViewport(MatcapViewport):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._fracture_mesh: FractureViewportMesh | None = None
        self._matcap_tint_strength = FRACTURE_MATCAP_TINT_STRENGTH

    def set_mesh(self, mesh: FractureViewportMesh) -> None:
        self._fracture_mesh = mesh
        super().set_mesh(_geometry_buffer_from_viewport_mesh(mesh))

    @property
    def mesh(self) -> FractureViewportMesh | None:
        return self._fracture_mesh


def build_fracture_viewport_mesh(preview: FracturePreviewResult) -> FractureViewportMesh:
    vertices = array("f")
    triangle_count = 0
    for piece in preview.pieces:
        triangle_count += _append_mesh_triangles(
            vertices,
            piece.base_mesh,
            color=piece.color,
        )
    for instance in preview.instances:
        prototype = preview.prototypes[instance.prototype_key]
        triangle_count += _append_mesh_triangles(
            vertices,
            prototype.mesh,
            color=instance.color,
            translate=instance.position,
            orientation=instance.orientation,
            scale=instance.scale,
        )
    return FractureViewportMesh(
        name=f"{preview.plan.output_stem}_fracture_preview",
        vertex_components=vertices,
        triangle_count=triangle_count,
        piece_count=len(preview.pieces),
        instance_count=len(preview.instances),
    )


def _append_mesh_triangles(
    vertices: array,
    mesh: GeometryBuffer,
    *,
    color: Color4,
    translate: Vector3 = Vector3(0.0, 0.0, 0.0),
    orientation: Quaternion = Quaternion(1.0, 0.0, 0.0, 0.0),
    scale: Vector3 = Vector3(1.0, 1.0, 1.0),
) -> int:
    points = tuple(_points(mesh))
    offset = 0
    triangle_count = 0
    for count in mesh.face_vertex_counts:
        indices = tuple(int(mesh.face_vertex_indices[offset + index]) for index in range(count))
        offset += count
        if count < 3:
            continue
        transformed = tuple(
            _transform_point(points[index], translate=translate, orientation=orientation, scale=scale)
            for index in indices
        )
        for index in range(1, count - 1):
            triangle = (transformed[0], transformed[index], transformed[index + 1])
            normal = _face_normal(triangle)
            for point in triangle:
                vertices.extend(
                    (
                        point.x,
                        point.y,
                        point.z,
                        normal.x,
                        normal.y,
                        normal.z,
                        color.r,
                        color.g,
                        color.b,
                        color.a,
                    )
                )
            triangle_count += 1
    return triangle_count


def _points(mesh: GeometryBuffer):
    for index in range(0, len(mesh.point_components), 3):
        yield Vector3(mesh.point_components[index], mesh.point_components[index + 1], mesh.point_components[index + 2])


def _transform_point(
    point: Vector3,
    *,
    translate: Vector3,
    orientation: Quaternion,
    scale: Vector3,
) -> Vector3:
    scaled = Vector3(point.x * scale.x, point.y * scale.y, point.z * scale.z)
    rotated = _rotate_vector(orientation, scaled)
    return Vector3(rotated.x + translate.x, rotated.y + translate.y, rotated.z + translate.z)


def _rotate_vector(q: Quaternion, value: Vector3) -> Vector3:
    x, y, z = _rotate_components(q, value.x, value.y, value.z)
    return Vector3(x, y, z)


def _rotate_components(q: Quaternion, x: float, y: float, z: float) -> tuple[float, float, float]:
    qw, qx, qy, qz = q.real, q.i, q.j, q.k
    tx = 2.0 * (qy * z - qz * y)
    ty = 2.0 * (qz * x - qx * z)
    tz = 2.0 * (qx * y - qy * x)
    return (
        x + qw * tx + (qy * tz - qz * ty),
        y + qw * ty + (qz * tx - qx * tz),
        z + qw * tz + (qx * ty - qy * tx),
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
    length = sqrt(nx * nx + ny * ny + nz * nz)
    if length <= 0.0:
        return Vector3(0.0, 0.0, 1.0)
    return Vector3(nx / length, ny / length, nz / length)


def _geometry_buffer_from_viewport_mesh(mesh: FractureViewportMesh) -> GeometryBuffer:
    points = array("f")
    colors = array("f")
    face_vertex_counts = array("i")
    face_vertex_indices = array("i")
    vertex_count = len(mesh.vertex_components) // FRACTURE_VERTEX_STRIDE
    for index in range(0, len(mesh.vertex_components), FRACTURE_VERTEX_STRIDE):
        points.extend(
            (
                mesh.vertex_components[index],
                mesh.vertex_components[index + 1],
                mesh.vertex_components[index + 2],
            )
        )
        colors.extend(
            (
                mesh.vertex_components[index + 6],
                mesh.vertex_components[index + 7],
                mesh.vertex_components[index + 8],
                mesh.vertex_components[index + 9],
            )
        )
    for index in range(0, vertex_count, 3):
        face_vertex_counts.append(3)
        face_vertex_indices.extend((index, index + 1, index + 2))
    return GeometryBuffer(
        name=mesh.name,
        point_components=points,
        face_vertex_counts=face_vertex_counts,
        face_vertex_indices=face_vertex_indices,
        vertex_color_components=colors,
    )
