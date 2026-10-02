"""Deterministic oriented collision mesh primitives shared by Proxy and Fracturing."""

from __future__ import annotations

import math

from .models import MeshData, Vector3
from .naming import make_stable_prim_name


def build_capsule_collision_mesh(name: str, start: Vector3, end: Vector3, radius: float) -> MeshData:
    axis = _normalize(Vector3(end.x - start.x, end.y - start.y, end.z - start.z))
    u, v = collision_axis_basis(axis)
    segments = 8
    hemisphere_steps = 3
    angles = tuple(2.0 * math.pi * index / segments for index in range(segments))
    rings: list[tuple[Vector3, ...]] = []
    for step in range(1, hemisphere_steps + 1):
        phi = -math.pi * 0.5 + step * (math.pi * 0.5 / hemisphere_steps)
        center = Vector3(
            start.x + axis.x * math.sin(phi) * radius,
            start.y + axis.y * math.sin(phi) * radius,
            start.z + axis.z * math.sin(phi) * radius,
        )
        rings.append(_ring(center, u, v, math.cos(phi) * radius, angles))
    for step in range(hemisphere_steps):
        phi = step * (math.pi * 0.5 / hemisphere_steps)
        center = Vector3(
            end.x + axis.x * math.sin(phi) * radius,
            end.y + axis.y * math.sin(phi) * radius,
            end.z + axis.z * math.sin(phi) * radius,
        )
        rings.append(_ring(center, u, v, math.cos(phi) * radius, angles))
    bottom = Vector3(start.x - axis.x * radius, start.y - axis.y * radius, start.z - axis.z * radius)
    top = Vector3(end.x + axis.x * radius, end.y + axis.y * radius, end.z + axis.z * radius)
    points = [bottom, *(point for ring in rings for point in ring), top]
    top_index = len(points) - 1
    faces: list[tuple[int, ...]] = []
    for segment in range(segments):
        nxt = (segment + 1) % segments
        faces.append((0, 1 + segment, 1 + nxt))
    for ring_index in range(len(rings) - 1):
        row = 1 + ring_index * segments
        next_row = row + segments
        for segment in range(segments):
            nxt = (segment + 1) % segments
            faces.append((row + segment, row + nxt, next_row + nxt, next_row + segment))
    last_row = 1 + (len(rings) - 1) * segments
    for segment in range(segments):
        nxt = (segment + 1) % segments
        faces.append((top_index, last_row + nxt, last_row + segment))
    return _mesh_from_faces(name, tuple(points), tuple(faces))


def build_box_collision_mesh(name: str, start: Vector3, end: Vector3, width: float) -> MeshData:
    axis = _normalize(Vector3(end.x - start.x, end.y - start.y, end.z - start.z))
    u, v = collision_axis_basis(axis)
    half = max(0.0, float(width)) * 0.5

    def corner(center: Vector3, u_sign: float, v_sign: float) -> Vector3:
        return Vector3(
            center.x + (u.x * u_sign + v.x * v_sign) * half,
            center.y + (u.y * u_sign + v.y * v_sign) * half,
            center.z + (u.z * u_sign + v.z * v_sign) * half,
        )

    points = (
        corner(start, -1.0, -1.0),
        corner(start, 1.0, -1.0),
        corner(start, 1.0, 1.0),
        corner(start, -1.0, 1.0),
        corner(end, -1.0, -1.0),
        corner(end, 1.0, -1.0),
        corner(end, 1.0, 1.0),
        corner(end, -1.0, 1.0),
    )
    faces = (
        (0, 3, 2, 1),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    )
    return _mesh_from_faces(name, points, faces)


def collision_axis_basis(axis: Vector3) -> tuple[Vector3, Vector3]:
    normalized = _normalize(axis)
    helper = Vector3(1.0, 0.0, 0.0) if abs(normalized.x) < 0.8 else Vector3(0.0, 1.0, 0.0)
    u = _normalize(_cross(normalized, helper))
    return u, _normalize(_cross(normalized, u))


def _ring(
    center: Vector3,
    u: Vector3,
    v: Vector3,
    radius: float,
    angles: tuple[float, ...],
) -> tuple[Vector3, ...]:
    return tuple(
        Vector3(
            center.x + (math.cos(theta) * u.x + math.sin(theta) * v.x) * radius,
            center.y + (math.cos(theta) * u.y + math.sin(theta) * v.y) * radius,
            center.z + (math.cos(theta) * u.z + math.sin(theta) * v.z) * radius,
        )
        for theta in angles
    )


def _mesh_from_faces(name: str, points: tuple[Vector3, ...], faces: tuple[tuple[int, ...], ...]) -> MeshData:
    return MeshData(
        name=make_stable_prim_name(name, fallback="Collision"),
        points=points,
        face_vertex_counts=tuple(len(face) for face in faces),
        face_vertex_indices=tuple(index for face in faces for index in face),
    )


def _normalize(vector: Vector3) -> Vector3:
    length = math.sqrt(vector.x * vector.x + vector.y * vector.y + vector.z * vector.z)
    if length <= 0.0:
        return Vector3(0.0, 1.0, 0.0)
    return Vector3(vector.x / length, vector.y / length, vector.z / length)


def _cross(a: Vector3, b: Vector3) -> Vector3:
    return Vector3(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x)
