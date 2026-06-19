"""Geometry helpers shared by fracture export and preview.

Layer: domain/application boundary.
"""

from __future__ import annotations

from dataclasses import dataclass

from .fracture_service import FractureError
from .geometry_buffers import iter_face_ranges
from .models import Color4, MeshData, MeshSection, Vector2, Vector3


@dataclass(frozen=True)
class CapSourceContext:
    face_ranges: tuple[tuple[int, int, int], ...]
    source_edge_faces: dict[tuple[int, int], tuple[int, ...]]
    material_by_source_face: dict[int, int]


def build_cap_source_context(mesh: MeshData) -> CapSourceContext:
    face_ranges = tuple(iter_face_ranges(mesh.face_vertex_counts))
    return CapSourceContext(
        face_ranges=face_ranges,
        source_edge_faces=_source_edge_faces(mesh, face_ranges),
        material_by_source_face=_material_by_source_face(mesh),
    )


def slice_mesh_faces(
    mesh: MeshData,
    face_indices: tuple[int, ...],
    *,
    name: str,
    generate_caps: bool = False,
    cap_context: CapSourceContext | None = None,
) -> MeshData:
    """Return a compact mesh containing only the requested source face indices."""
    if not face_indices:
        raise FractureError(f"Fracture piece {name} has no base mesh faces.")
    _validate_slice_mesh_shape(mesh)

    face_ranges = cap_context.face_ranges if cap_context is not None else tuple(iter_face_ranges(mesh.face_vertex_counts))
    selected = set(face_indices)
    if len(selected) != len(face_indices):
        raise FractureError(f"Fracture piece {name} contains duplicate base mesh face indices.")
    if any(face_index < 0 or face_index >= len(face_ranges) for face_index in face_indices):
        raise FractureError(f"Fracture piece {name} references a base mesh face outside the source mesh.")

    original_to_new_point: dict[int, int] = {}
    new_point_source: list[int | None] = []
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
                new_point_source.append(original_point_index)
                points.append(mesh.points[original_point_index])
            face_vertex_indices.append(new_point_index)
            if len(mesh.uv_coords) == len(mesh.face_vertex_indices):
                uv_coords.append(mesh.uv_coords[face_vertex_slot])
            if len(mesh.secondary_uv_coords) == len(mesh.face_vertex_indices):
                secondary_uv_coords.append(mesh.secondary_uv_coords[face_vertex_slot])
            if len(mesh.vertex_colors) == len(mesh.face_vertex_indices):
                vertex_colors.append(mesh.vertex_colors[face_vertex_slot])

    sections = _slice_mesh_sections(mesh.sections, original_to_new_face)
    if generate_caps:
        resolved_cap_context = cap_context or build_cap_source_context(mesh)
        sections = _append_boundary_fan_caps(
            mesh,
            resolved_cap_context,
            selected,
            original_to_new_face,
            original_to_new_point,
            new_point_source,
            points,
            face_vertex_counts,
            face_vertex_indices,
            uv_coords,
            secondary_uv_coords,
            vertex_colors,
            sections,
        )

    skel_joint_indices, skel_joint_weights = _slice_mesh_skinning(mesh, new_point_source)
    return MeshData(
        name=name,
        points=tuple(points),
        face_vertex_counts=tuple(face_vertex_counts),
        face_vertex_indices=tuple(face_vertex_indices),
        uv_coords=tuple(uv_coords),
        secondary_uv_coords=tuple(secondary_uv_coords),
        vertex_colors=tuple(vertex_colors),
        sections=sections,
        skel_joint_indices=skel_joint_indices,
        skel_joint_weights=skel_joint_weights,
        skel_element_size=mesh.skel_element_size if skel_joint_indices else 0,
    )


def _validate_slice_mesh_shape(mesh: MeshData) -> None:
    mesh_name = getattr(mesh, "name", "<unnamed>")
    for field_name in ("points", "face_vertex_counts", "face_vertex_indices"):
        _require_sequence_field(mesh, mesh_name, field_name)


def _require_sequence_field(mesh: MeshData, mesh_name: str, field_name: str) -> None:
    value = getattr(mesh, field_name, None)
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__") or not hasattr(value, "__getitem__"):
        raise FractureError(
            f"Fracture mesh {mesh_name} {field_name} must be a sequence, got {type(value).__name__}."
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
    new_point_source: list[int | None],
) -> tuple[tuple[int, ...], tuple[float, ...]]:
    if mesh.skel_element_size <= 0 or not mesh.skel_joint_indices:
        return (), ()

    expected_slots = len(mesh.points) * mesh.skel_element_size
    if len(mesh.skel_joint_indices) < expected_slots:
        raise FractureError("Base mesh skinning index count is smaller than point count.")
    if mesh.skel_joint_weights and len(mesh.skel_joint_weights) < expected_slots:
        raise FractureError("Base mesh skinning weight count is smaller than point count.")

    joint_indices: list[int] = []
    joint_weights: list[float] = []
    fallback_source = next((source for source in new_point_source if source is not None), None)
    for source_point_index in new_point_source:
        original_point_index = source_point_index if source_point_index is not None else fallback_source
        if original_point_index is None:
            continue
        start = original_point_index * mesh.skel_element_size
        end = start + mesh.skel_element_size
        joint_indices.extend(mesh.skel_joint_indices[start:end])
        if mesh.skel_joint_weights:
            joint_weights.extend(mesh.skel_joint_weights[start:end])
    return tuple(joint_indices), tuple(joint_weights)


def _append_boundary_fan_caps(
    mesh: MeshData,
    cap_context: CapSourceContext,
    selected: set[int],
    original_to_new_face: dict[int, int],
    original_to_new_point: dict[int, int],
    new_point_source: list[int | None],
    points: list[Vector3],
    face_vertex_counts: list[int],
    face_vertex_indices: list[int],
    uv_coords: list[Vector2],
    secondary_uv_coords: list[Vector2],
    vertex_colors: list[Color4],
    sections: tuple[MeshSection, ...],
) -> tuple[MeshSection, ...]:
    selected_boundary_edges: list[tuple[int, int, int]] = []
    for original_face_index in sorted(selected):
        _face_index, start, end = cap_context.face_ranges[original_face_index]
        face_points = mesh.face_vertex_indices[start:end]
        for index, point_a in enumerate(face_points):
            point_b = face_points[(index + 1) % len(face_points)]
            edge_key = _edge_key(point_a, point_b)
            adjacent = cap_context.source_edge_faces.get(edge_key, ())
            if len(adjacent) < 2 or all(face in selected for face in adjacent):
                continue
            selected_boundary_edges.append((point_a, point_b, original_face_index))

    if not selected_boundary_edges:
        return sections

    cap_face_indices_by_material: dict[int, list[int]] = {}
    use_uvs = len(mesh.uv_coords) == len(mesh.face_vertex_indices)
    use_secondary_uvs = len(mesh.secondary_uv_coords) == len(mesh.face_vertex_indices)
    use_vertex_colors = len(mesh.vertex_colors) == len(mesh.face_vertex_indices)

    for boundary_loop in _boundary_loops(selected_boundary_edges):
        loop_point_indices = sorted({point for point_a, point_b, _face in boundary_loop for point in (point_a, point_b)})
        center = _average_points(tuple(points[original_to_new_point[point]] for point in loop_point_indices))
        center_index = len(points)
        points.append(center)
        new_point_source.append(loop_point_indices[0] if loop_point_indices else None)
        for point_a, point_b, original_face_index in boundary_loop:
            new_a = original_to_new_point[point_a]
            new_b = original_to_new_point[point_b]
            new_face_index = len(face_vertex_counts)
            face_vertex_counts.append(3)
            face_vertex_indices.extend((new_b, new_a, center_index))
            if use_uvs:
                uv_coords.extend((Vector2(0.0, 0.0), Vector2(0.0, 0.0), Vector2(0.0, 0.0)))
            if use_secondary_uvs:
                secondary_uv_coords.extend((Vector2(0.0, 0.0), Vector2(0.0, 0.0), Vector2(0.0, 0.0)))
            if use_vertex_colors:
                vertex_colors.extend(
                    (
                        Color4(1.0, 1.0, 1.0, 1.0),
                        Color4(1.0, 1.0, 1.0, 1.0),
                        Color4(1.0, 1.0, 1.0, 1.0),
                    )
                )
            material_id = cap_context.material_by_source_face.get(original_face_index, 0)
            cap_face_indices_by_material.setdefault(material_id, []).append(new_face_index)

    merged_sections = [MeshSection(material_id=section.material_id, face_indices=section.face_indices) for section in sections]
    for material_id in sorted(cap_face_indices_by_material):
        merged_sections.append(MeshSection(material_id=material_id, face_indices=tuple(cap_face_indices_by_material[material_id])))
    return tuple(merged_sections)


def _source_edge_faces(
    mesh: MeshData,
    face_ranges: tuple[tuple[int, int, int], ...] | None = None,
) -> dict[tuple[int, int], tuple[int, ...]]:
    edge_faces: dict[tuple[int, int], list[int]] = {}
    resolved_face_ranges = face_ranges or tuple(iter_face_ranges(mesh.face_vertex_counts))
    for face_index, start, end in resolved_face_ranges:
        face_points = mesh.face_vertex_indices[start:end]
        for index, point_a in enumerate(face_points):
            point_b = face_points[(index + 1) % len(face_points)]
            edge_faces.setdefault(_edge_key(point_a, point_b), []).append(face_index)
    return {edge: tuple(faces) for edge, faces in edge_faces.items()}


def _material_by_source_face(mesh: MeshData) -> dict[int, int]:
    material_by_face: dict[int, int] = {}
    for section in mesh.sections:
        for face_index in section.face_indices:
            material_by_face.setdefault(face_index, section.material_id)
    return material_by_face


def _edge_key(point_a: int, point_b: int) -> tuple[int, int]:
    return (point_a, point_b) if point_a <= point_b else (point_b, point_a)


def _boundary_loops(edges: list[tuple[int, int, int]]) -> tuple[tuple[tuple[int, int, int], ...], ...]:
    remaining = list(edges)
    loops: list[tuple[tuple[int, int, int], ...]] = []
    while remaining:
        seed = remaining.pop(0)
        component = [seed]
        component_points = {seed[0], seed[1]}
        changed = True
        while changed:
            changed = False
            for edge in tuple(remaining):
                if edge[0] in component_points or edge[1] in component_points:
                    remaining.remove(edge)
                    component.append(edge)
                    component_points.update((edge[0], edge[1]))
                    changed = True
        loops.append(tuple(sorted(component, key=lambda item: (item[2], item[0], item[1]))))
    return tuple(loops)


def _average_points(points: tuple[Vector3, ...]) -> Vector3:
    if not points:
        raise FractureError("Cannot generate a fracture cap for an empty boundary loop.")
    scale = 1.0 / len(points)
    return Vector3(
        sum(point.x for point in points) * scale,
        sum(point.y for point in points) * scale,
        sum(point.z for point in points) * scale,
    )
