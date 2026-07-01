"""Deterministic mesh face pruning for preview/proxy workflows.

Layer: domain.

The module keeps large connected source geometry and drops tiny disconnected
islands before a caller runs its own simplification pass.
"""

from __future__ import annotations

import math

from .models import MeshData, Vector3


DEFAULT_BRANCH_PRUNE_AGGRESSION = 0.25


def select_large_connected_face_indices(
    mesh: MeshData,
    aggression: float = DEFAULT_BRANCH_PRUNE_AGGRESSION,
    candidate_face_indices: tuple[int, ...] | None = None,
) -> tuple[int, ...] | None:
    """Return source face indices to keep, or None when pruning should not run."""
    if aggression <= 0.0:
        return None

    face_ranges = _face_vertex_ranges(mesh)
    if face_ranges is None:
        return None
    face_points = _face_point_indices(mesh, face_ranges, candidate_face_indices)
    if face_points is None:
        return None
    components = _connected_face_components(face_points)
    if len(components) <= 1:
        return None
    component_scores = _ranked_component_scores(mesh, face_points, components)
    if not component_scores:
        return None
    remove_count = min(
        len(component_scores) - 1,
        _component_removal_count(len(component_scores), aggression),
    )
    if remove_count <= 0:
        return None
    kept_components = component_scores[remove_count:]
    return tuple(
        sorted(
            face_index
            for _score, _area, _first_face, face_indices in kept_components
            for face_index in face_indices
        )
    )


def _component_removal_count(component_count: int, aggression: float) -> int:
    return max(1, int(math.ceil(component_count * max(0.0, min(1.0, aggression)))))


def _face_vertex_ranges(mesh: MeshData) -> tuple[tuple[int, int], ...] | None:
    ranges: list[tuple[int, int]] = []
    offset = 0
    for count in mesh.face_vertex_counts:
        end = offset + int(count)
        if int(count) <= 0 or end > len(mesh.face_vertex_indices):
            return None
        ranges.append((offset, end))
        offset = end
    if offset != len(mesh.face_vertex_indices):
        return None
    return tuple(ranges)


def _face_point_indices(
    mesh: MeshData,
    face_ranges: tuple[tuple[int, int], ...],
    candidate_face_indices: tuple[int, ...] | None,
) -> tuple[tuple[int, ...], ...] | None:
    source_face_indices = (
        candidate_face_indices
        if candidate_face_indices is not None
        else tuple(range(len(face_ranges)))
    )
    faces: list[tuple[int, ...]] = []
    for face_index in source_face_indices:
        if face_index < 0 or face_index >= len(face_ranges):
            return None
        start, end = face_ranges[face_index]
        face = tuple(int(index) for index in mesh.face_vertex_indices[start:end])
        if any(index < 0 or index >= len(mesh.points) for index in face):
            return None
        faces.append((face_index, *face))
    return tuple(faces)


def _connected_face_components(face_points: tuple[tuple[int, ...], ...]) -> tuple[tuple[int, ...], ...]:
    faces_by_point: dict[int, list[int]] = {}
    for local_face_index, point_indices in enumerate(face_points):
        for point_index in point_indices[1:]:
            faces_by_point.setdefault(point_index, []).append(local_face_index)
    components: list[tuple[int, ...]] = []
    seen: set[int] = set()
    for face_index in range(len(face_points)):
        if face_index in seen:
            continue
        stack = [face_index]
        seen.add(face_index)
        component: list[int] = []
        while stack:
            current = stack.pop()
            component.append(current)
            for point_index in face_points[current][1:]:
                for neighbor in faces_by_point[point_index]:
                    if neighbor not in seen:
                        seen.add(neighbor)
                        stack.append(neighbor)
        components.append(tuple(sorted(component)))
    return tuple(components)


def _ranked_component_scores(
    mesh: MeshData,
    face_points: tuple[tuple[int, ...], ...],
    components: tuple[tuple[int, ...], ...],
) -> list[tuple[float, float, int, tuple[int, ...]]]:
    scores: list[tuple[float, float, int, tuple[int, ...]]] = []
    for component in components:
        area = sum(_face_area(mesh, face_points[face_index]) for face_index in component)
        if area <= 0.0:
            continue
        diagonal_squared = max(_component_bounds_diagonal_squared(mesh, face_points, component), 1e-12)
        source_faces = tuple(face_points[local_face_index][0] for local_face_index in component)
        scores.append((area * diagonal_squared, area, source_faces[0], source_faces))
    return sorted(scores, key=lambda item: (item[0], item[1], item[2]))


def _component_bounds_diagonal_squared(
    mesh: MeshData,
    face_points: tuple[tuple[int, ...], ...],
    component: tuple[int, ...],
) -> float:
    point_indices: set[int] = set()
    for local_face_index in component:
        point_indices.update(face_points[local_face_index][1:])
    if not point_indices:
        return 0.0
    points = tuple(mesh.points[index] for index in point_indices)
    min_x = min(point.x for point in points)
    min_y = min(point.y for point in points)
    min_z = min(point.z for point in points)
    max_x = max(point.x for point in points)
    max_y = max(point.y for point in points)
    max_z = max(point.z for point in points)
    return (max_x - min_x) ** 2 + (max_y - min_y) ** 2 + (max_z - min_z) ** 2


def _face_area(mesh: MeshData, face_point_indices: tuple[int, ...]) -> float:
    return _polygon_area(tuple(mesh.points[index] for index in face_point_indices[1:]))


def _polygon_area(points: tuple[Vector3, ...]) -> float:
    if len(points) < 3:
        return 0.0
    anchor = points[0]
    area = 0.0
    for index in range(1, len(points) - 1):
        area += _triangle_area(anchor, points[index], points[index + 1])
    return area


def _triangle_area(a: Vector3, b: Vector3, c: Vector3) -> float:
    ab_x = b.x - a.x
    ab_y = b.y - a.y
    ab_z = b.z - a.z
    ac_x = c.x - a.x
    ac_y = c.y - a.y
    ac_z = c.z - a.z
    cross_x = ab_y * ac_z - ab_z * ac_y
    cross_y = ab_z * ac_x - ab_x * ac_z
    cross_z = ab_x * ac_y - ab_y * ac_x
    return ((cross_x * cross_x + cross_y * cross_y + cross_z * cross_z) ** 0.5) * 0.5
