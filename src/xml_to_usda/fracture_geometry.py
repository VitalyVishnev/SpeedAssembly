"""Geometry helpers shared by fracture export and preview.

Layer: domain/application boundary.
"""

from __future__ import annotations

from .fracture_service import FractureError
from .geometry_buffers import iter_face_ranges
from .models import MeshData, MeshSection


def slice_mesh_faces(mesh: MeshData, face_indices: tuple[int, ...], *, name: str) -> MeshData:
    """Return a compact mesh containing only the requested source face indices."""
    if not face_indices:
        raise FractureError(f"Fracture piece {name} has no base mesh faces.")

    face_ranges = tuple(iter_face_ranges(mesh.face_vertex_counts))
    selected = set(face_indices)
    if len(selected) != len(face_indices):
        raise FractureError(f"Fracture piece {name} contains duplicate base mesh face indices.")
    if any(face_index < 0 or face_index >= len(face_ranges) for face_index in face_indices):
        raise FractureError(f"Fracture piece {name} references a base mesh face outside the source mesh.")

    original_to_new_point: dict[int, int] = {}
    points = []
    face_vertex_counts: list[int] = []
    face_vertex_indices: list[int] = []
    uv_coords = []
    secondary_uv_coords = []
    vertex_colors = []
    original_to_new_face: dict[int, int] = {}

    for new_face_index, original_face_index in enumerate(face_indices):
        _face_index, start, end = face_ranges[original_face_index]
        original_to_new_face[original_face_index] = new_face_index
        face_vertex_counts.append(end - start)
        for face_vertex_slot in range(start, end):
            original_point_index = mesh.face_vertex_indices[face_vertex_slot]
            if original_point_index < 0 or original_point_index >= len(mesh.points):
                raise FractureError(
                    f"Base mesh face {original_face_index} references point {original_point_index} outside the mesh."
                )
            new_point_index = original_to_new_point.get(original_point_index)
            if new_point_index is None:
                new_point_index = len(points)
                original_to_new_point[original_point_index] = new_point_index
                points.append(mesh.points[original_point_index])
            face_vertex_indices.append(new_point_index)
            if len(mesh.uv_coords) == len(mesh.face_vertex_indices):
                uv_coords.append(mesh.uv_coords[face_vertex_slot])
            if len(mesh.secondary_uv_coords) == len(mesh.face_vertex_indices):
                secondary_uv_coords.append(mesh.secondary_uv_coords[face_vertex_slot])
            if len(mesh.vertex_colors) == len(mesh.face_vertex_indices):
                vertex_colors.append(mesh.vertex_colors[face_vertex_slot])

    skel_joint_indices, skel_joint_weights = _slice_mesh_skinning(mesh, original_to_new_point)
    return MeshData(
        name=name,
        points=tuple(points),
        face_vertex_counts=tuple(face_vertex_counts),
        face_vertex_indices=tuple(face_vertex_indices),
        uv_coords=tuple(uv_coords),
        secondary_uv_coords=tuple(secondary_uv_coords),
        vertex_colors=tuple(vertex_colors),
        sections=_slice_mesh_sections(mesh.sections, original_to_new_face),
        skel_joint_indices=skel_joint_indices,
        skel_joint_weights=skel_joint_weights,
        skel_element_size=mesh.skel_element_size if skel_joint_indices else 0,
    )


def sample_face_indices(face_indices: tuple[int, ...], max_face_count: int) -> tuple[int, ...]:
    """Deterministically downsample a face-index list while preserving order."""
    if max_face_count <= 0:
        raise FractureError("Fracture preview face budget must be greater than zero.")
    if len(face_indices) <= max_face_count:
        return face_indices
    if max_face_count == 1:
        return (face_indices[0],)
    last = len(face_indices) - 1
    return tuple(face_indices[round(index * last / (max_face_count - 1))] for index in range(max_face_count))


def _slice_mesh_sections(
    sections: tuple[MeshSection, ...],
    original_to_new_face: dict[int, int],
) -> tuple[MeshSection, ...]:
    sliced_sections: list[MeshSection] = []
    for section in sections:
        face_indices = tuple(
            original_to_new_face[face_index]
            for face_index in section.face_indices
            if face_index in original_to_new_face
        )
        if face_indices:
            sliced_sections.append(MeshSection(material_id=section.material_id, face_indices=face_indices))
    return tuple(sliced_sections)


def _slice_mesh_skinning(
    mesh: MeshData,
    original_to_new_point: dict[int, int],
) -> tuple[tuple[int, ...], tuple[float, ...]]:
    if mesh.skel_element_size <= 0 or not mesh.skel_joint_indices:
        return (), ()

    expected_slots = len(mesh.points) * mesh.skel_element_size
    if len(mesh.skel_joint_indices) < expected_slots:
        raise FractureError("Base mesh skinning index count is smaller than point count.")
    if mesh.skel_joint_weights and len(mesh.skel_joint_weights) < expected_slots:
        raise FractureError("Base mesh skinning weight count is smaller than point count.")

    points_by_new_index = sorted(original_to_new_point.items(), key=lambda item: item[1])
    joint_indices: list[int] = []
    joint_weights: list[float] = []
    for original_point_index, _new_point_index in points_by_new_index:
        start = original_point_index * mesh.skel_element_size
        end = start + mesh.skel_element_size
        joint_indices.extend(mesh.skel_joint_indices[start:end])
        if mesh.skel_joint_weights:
            joint_weights.extend(mesh.skel_joint_weights[start:end])
    return tuple(joint_indices), tuple(joint_weights)
