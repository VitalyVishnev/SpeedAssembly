"""Qt-free viewport scene contract.

Layer: application/interface model.

`ViewportScene` is the payload seam between preview generation/mode adapters
and Qt/OpenGL rendering. It describes what to draw, not how to draw it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Color4, GeometryBuffer, Quaternion, Vector3


IDENTITY_ORIENTATION = Quaternion(1.0, 0.0, 0.0, 0.0)
UNIT_SCALE = Vector3(1.0, 1.0, 1.0)
ZERO_VECTOR = Vector3(0.0, 0.0, 0.0)


@dataclass(frozen=True)
class ViewportBounds:
    min_point: Vector3
    max_point: Vector3

    @property
    def center(self) -> Vector3:
        return Vector3(
            (self.min_point.x + self.max_point.x) * 0.5,
            (self.min_point.y + self.max_point.y) * 0.5,
            (self.min_point.z + self.max_point.z) * 0.5,
        )


@dataclass(frozen=True)
class ViewportMeshBatch:
    batch_id: str
    name: str
    mesh: GeometryBuffer
    color: Color4 | None = None
    selectable_id: str | None = None


@dataclass(frozen=True)
class ViewportDrawCall:
    draw_id: str
    batch_id: str
    translate: Vector3 = ZERO_VECTOR
    orientation: Quaternion = IDENTITY_ORIENTATION
    scale: Vector3 = UNIT_SCALE
    tint: Color4 | None = None
    explode_direction: Vector3 = ZERO_VECTOR
    selectable_id: str | None = None
    visibility_group: str = "mesh"


@dataclass(frozen=True)
class ViewportBoneSegment:
    segment_id: str
    parent_token: str
    child_token: str
    start: Vector3
    end: Vector3
    color: Color4
    selected: bool = False
    selectable_id: str | None = None
    explode_direction: Vector3 = ZERO_VECTOR


@dataclass(frozen=True)
class ViewportMarker:
    marker_id: str
    position: Vector3
    color: Color4
    radius: float = 1.0
    selectable_id: str | None = None
    label: str = ""


@dataclass(frozen=True)
class ViewportLabel:
    label_id: str
    text: str
    position: Vector3
    color: Color4 = Color4(1.0, 1.0, 1.0, 1.0)


@dataclass(frozen=True)
class ViewportStats:
    uploaded_triangles: int
    logical_triangles: int
    instance_count: int = 0
    batch_count: int = 0
    draw_call_count: int = 0


@dataclass(frozen=True)
class ViewportScene:
    scene_id: str
    mesh_batches: tuple[ViewportMeshBatch, ...]
    draw_calls: tuple[ViewportDrawCall, ...]
    bounds: ViewportBounds
    stats: ViewportStats
    bone_segments: tuple[ViewportBoneSegment, ...] = ()
    markers: tuple[ViewportMarker, ...] = ()
    labels: tuple[ViewportLabel, ...] = ()


def geometry_triangle_count(mesh: GeometryBuffer) -> int:
    return sum(max(0, int(count) - 2) for count in mesh.face_vertex_counts)


def geometry_bounds(meshes: tuple[GeometryBuffer, ...]) -> ViewportBounds:
    min_x = min_y = min_z = float("inf")
    max_x = max_y = max_z = float("-inf")
    found_point = False
    for mesh in meshes:
        components = mesh.point_components
        for index in range(0, len(components), 3):
            found_point = True
            x = float(components[index])
            y = float(components[index + 1])
            z = float(components[index + 2])
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            min_z = min(min_z, z)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
            max_z = max(max_z, z)
    if not found_point:
        return ViewportBounds(min_point=ZERO_VECTOR, max_point=ZERO_VECTOR)
    return ViewportBounds(
        min_point=Vector3(min_x, min_y, min_z),
        max_point=Vector3(max_x, max_y, max_z),
    )


def transformed_draw_bounds(
    mesh_batches: tuple[ViewportMeshBatch, ...],
    draw_calls: tuple[ViewportDrawCall, ...],
) -> ViewportBounds:
    batch_by_id = {batch.batch_id: batch for batch in mesh_batches}
    batch_bounds_by_id = {
        batch.batch_id: geometry_bounds((batch.mesh,))
        for batch in mesh_batches
    }
    min_x = min_y = min_z = float("inf")
    max_x = max_y = max_z = float("-inf")
    found_point = False
    for draw_call in draw_calls:
        batch = batch_by_id.get(draw_call.batch_id)
        if batch is None:
            continue
        local_bounds = batch_bounds_by_id[batch.batch_id]
        for corner in _bounds_corners(local_bounds):
            found_point = True
            point = _transform_point(corner, draw_call)
            min_x = min(min_x, point.x)
            min_y = min(min_y, point.y)
            min_z = min(min_z, point.z)
            max_x = max(max_x, point.x)
            max_y = max(max_y, point.y)
            max_z = max(max_z, point.z)
    if not found_point:
        return ViewportBounds(min_point=ZERO_VECTOR, max_point=ZERO_VECTOR)
    return ViewportBounds(
        min_point=Vector3(min_x, min_y, min_z),
        max_point=Vector3(max_x, max_y, max_z),
    )


def _bounds_corners(bounds: ViewportBounds) -> tuple[Vector3, ...]:
    min_point = bounds.min_point
    max_point = bounds.max_point
    return (
        Vector3(min_point.x, min_point.y, min_point.z),
        Vector3(min_point.x, min_point.y, max_point.z),
        Vector3(min_point.x, max_point.y, min_point.z),
        Vector3(min_point.x, max_point.y, max_point.z),
        Vector3(max_point.x, min_point.y, min_point.z),
        Vector3(max_point.x, min_point.y, max_point.z),
        Vector3(max_point.x, max_point.y, min_point.z),
        Vector3(max_point.x, max_point.y, max_point.z),
    )


def _transform_point(point: Vector3, draw_call: ViewportDrawCall) -> Vector3:
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
    # Equivalent to q * point * conjugate(q) for normalized quaternions.
    tx = 2.0 * (q.j * point.z - q.k * point.y)
    ty = 2.0 * (q.k * point.x - q.i * point.z)
    tz = 2.0 * (q.i * point.y - q.j * point.x)
    return Vector3(
        point.x + q.real * tx + (q.j * tz - q.k * ty),
        point.y + q.real * ty + (q.k * tx - q.i * tz),
        point.z + q.real * tz + (q.i * ty - q.j * tx),
    )
