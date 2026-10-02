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
) -> list[tuple[int, ...]] | None:
    source_face_indices = (
        candidate_face_indices
        if candidate_face_indices is not None
        else range(len(face_ranges))
    )
    faces: list[tuple[int, ...]] = []
    point_count = len(mesh.points)
    face_vertex_indices = mesh.face_vertex_indices
    for face_index in source_face_indices:
        if face_index < 0 or face_index >= len(face_ranges):
            return None
        start, end = face_ranges[face_index]
        face = tuple(int(face_vertex_indices[index]) for index in range(start, end))
        for point_index in face:
            if point_index < 0 or point_index >= point_count:
                return None
        if not face:
            return None
        faces.append((face_index, *face))
    return faces


def _connected_face_components(face_points: list[tuple[int, ...]]) -> list[list[int]]:
    faces_by_point: dict[int, list[int]] = {}
    for local_face_index, point_indices in enumerate(face_points):
        for point_index in point_indices[1:]:
            faces_by_point.setdefault(point_index, []).append(local_face_index)
    components: list[list[int]] = []
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
        components.append(component)
    return components


def _ranked_component_scores(
    mesh: MeshData,
    face_points: list[tuple[int, ...]],
    components: list[list[int]],
) -> list[tuple[float, float, int, tuple[int, ...]]]:
    scores: list[tuple[float, float, int, tuple[int, ...]]] = []
    for component in components:
        area = 0.0
        source_faces: list[int] = []
        min_x = min_y = min_z = float("inf")
        max_x = max_y = max_z = float("-inf")
        for face_index in component:
            face = face_points[face_index]
            source_faces.append(face[0])
            area += _face_area(mesh, face)
            for point_index in face[1:]:
                point = mesh.points[point_index]
                if point.x < min_x:
                    min_x = point.x
                if point.y < min_y:
                    min_y = point.y
                if point.z < min_z:
                    min_z = point.z
                if point.x > max_x:
                    max_x = point.x
                if point.y > max_y:
                    max_y = point.y
                if point.z > max_z:
                    max_z = point.z
        if area <= 0.0:
            continue
        diagonal_squared = max((max_x - min_x) ** 2 + (max_y - min_y) ** 2 + (max_z - min_z) ** 2, 1e-12)
        scores.append((area * diagonal_squared, area, source_faces[0], tuple(source_faces)))
    return sorted(scores, key=lambda item: (item[0], item[1], item[2]))


def _face_area(mesh: MeshData, face_point_indices: tuple[int, ...]) -> float:
    if len(face_point_indices) < 4:
        return 0.0
    anchor = mesh.points[face_point_indices[1]]
    area = 0.0
    for index in range(2, len(face_point_indices) - 1):
        area += _triangle_area(anchor, mesh.points[face_point_indices[index]], mesh.points[face_point_indices[index + 1]])
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
