"""Shared topology-preserving QEM simplification for diagnostic geometry."""

from __future__ import annotations

from array import array

from .models import GeometryBuffer


class QemSimplificationError(ValueError):
    """Raised when QEM input or output geometry is unsafe."""


def simplify_geometry_buffer_qem(mesh: GeometryBuffer, *, target_triangle_count: int) -> GeometryBuffer:
    points, triangles = _triangulated_mesh_arrays(mesh)
    if len(triangles) == 0:
        raise QemSimplificationError(f"Mesh {mesh.name} contains no surface triangles.")
    target_triangle_count = max(1, int(target_triangle_count))
    if len(triangles) <= target_triangle_count:
        if all(int(count) == 3 for count in mesh.face_vertex_counts):
            return mesh
        return _geometry_buffer_from_triangles(points, triangles, name=mesh.name)
    try:
        import fast_simplification
    except ImportError as exc:
        raise QemSimplificationError("QEM simplification requires the fast-simplification package.") from exc
    try:
        simplified_points, simplified_triangles = fast_simplification.simplify(
            points,
            triangles,
            target_count=target_triangle_count,
        )
    except Exception as exc:
        raise QemSimplificationError(f"QEM simplification failed for {mesh.name}: {exc}") from exc
    if len(simplified_points) == 0 or len(simplified_triangles) == 0:
        return _geometry_buffer_from_triangles(points, triangles, name=mesh.name)
    _validate_triangle_arrays(simplified_points, simplified_triangles, name=mesh.name)
    return _geometry_buffer_from_triangles(simplified_points, simplified_triangles, name=mesh.name)


def triangle_count(mesh: GeometryBuffer) -> int:
    return len(_triangulated_mesh_arrays(mesh)[1])


def _triangulated_mesh_arrays(mesh: GeometryBuffer):
    import numpy as np

    if len(mesh.point_components) % 3 != 0:
        raise QemSimplificationError(f"Mesh {mesh.name} point component count must be divisible by 3.")
    points = np.asarray(mesh.point_components, dtype=np.float64).reshape((-1, 3))
    if len(points) == 0:
        raise QemSimplificationError(f"Mesh {mesh.name} has no points.")
    if not bool(np.isfinite(points).all()):
        raise QemSimplificationError(f"Mesh {mesh.name} contains non-finite point coordinates.")
    triangles: list[tuple[int, int, int]] = []
    offset = 0
    point_count = len(points)
    for face_index, count in enumerate(mesh.face_vertex_counts):
        count = int(count)
        if count < 0:
            raise QemSimplificationError(f"Mesh {mesh.name} face {face_index} has a negative vertex count.")
        if offset + count > len(mesh.face_vertex_indices):
            raise QemSimplificationError(f"Mesh {mesh.name} face {face_index} is missing vertex indices.")
        face_indices = [int(mesh.face_vertex_indices[offset + index]) for index in range(count)]
        offset += count
        for point_index in face_indices:
            if point_index < 0 or point_index >= point_count:
                raise QemSimplificationError(
                    f"Mesh {mesh.name} face {face_index} references point {point_index} outside the mesh."
                )
        if count < 3:
            continue
        anchor = face_indices[0]
        for index in range(1, count - 1):
            triangles.append((anchor, face_indices[index], face_indices[index + 1]))
    if offset != len(mesh.face_vertex_indices):
        raise QemSimplificationError(f"Mesh {mesh.name} has trailing face vertex indices.")
    triangle_array = np.asarray(triangles, dtype=np.int32)
    _validate_triangle_arrays(points, triangle_array, name=mesh.name)
    return points, triangle_array


def _validate_triangle_arrays(points, triangles, *, name: str) -> None:
    import numpy as np

    if len(points) == 0:
        raise QemSimplificationError(f"Mesh {name} has no points.")
    if not bool(np.isfinite(points).all()):
        raise QemSimplificationError(f"Mesh {name} contains non-finite point coordinates.")
    if len(triangles) == 0:
        return
    if triangles.ndim != 2 or triangles.shape[1] != 3:
        raise QemSimplificationError(f"Mesh {name} simplification produced invalid triangle topology.")
    if int(triangles.min()) < 0 or int(triangles.max()) >= len(points):
        raise QemSimplificationError(f"Mesh {name} simplification produced triangle indices outside the mesh.")


def _geometry_buffer_from_triangles(points, triangles, *, name: str) -> GeometryBuffer:
    point_components = array("f")
    for point in points:
        point_components.extend((float(point[0]), float(point[1]), float(point[2])))
    face_counts = array("i", [3 for _ in range(len(triangles))])
    face_indices = array("i")
    for triangle in triangles:
        face_indices.extend((int(triangle[0]), int(triangle[1]), int(triangle[2])))
    return GeometryBuffer(
        name=name,
        point_components=point_components,
        face_vertex_counts=face_counts,
        face_vertex_indices=face_indices,
    )
