from __future__ import annotations

from array import array
from dataclasses import replace
from typing import Iterable, Iterator

from .models import (
    Color4,
    CompactMeshSection,
    GeometryBuffer,
    MeshData,
    MeshSection,
    Vector2,
    Vector3,
)


def geometry_buffer_from_mesh(mesh: MeshData) -> GeometryBuffer:
    point_components = array("f")
    for point in mesh.points:
        point_components.extend((point.x, point.y, point.z))

    face_vertex_counts = array("i", mesh.face_vertex_counts)
    face_vertex_indices = array("i", mesh.face_vertex_indices)

    uv_components = array("f")
    for uv in mesh.uv_coords:
        uv_components.extend((uv.x, uv.y))

    vertex_color_components = array("f")
    for color in mesh.vertex_colors:
        vertex_color_components.extend((color.r, color.g, color.b, color.a))

    sections = tuple(
        CompactMeshSection(material_id=section.material_id, face_indices=array("i", section.face_indices))
        for section in mesh.sections
    )
    skel_joint_indices = array("i", mesh.skel_joint_indices)
    skel_joint_weights = array("f", mesh.skel_joint_weights)
    return GeometryBuffer(
        name=mesh.name,
        point_components=point_components,
        face_vertex_counts=face_vertex_counts,
        face_vertex_indices=face_vertex_indices,
        uv_components=uv_components,
        vertex_color_components=vertex_color_components,
        sections=sections,
        skel_joint_indices=skel_joint_indices,
        skel_joint_weights=skel_joint_weights,
        skel_element_size=mesh.skel_element_size,
    )


def geometry_buffer_to_mesh(buffer: GeometryBuffer, max_points: int = 250_000) -> MeshData:
    if buffer.point_count > max_points:
        raise ValueError(
            f"GeometryBuffer {buffer.name} exceeds the in-memory render limit ({buffer.point_count} > {max_points})."
        )

    points = tuple(
        Vector3(
            buffer.point_components[index],
            buffer.point_components[index + 1],
            buffer.point_components[index + 2],
        )
        for index in range(0, len(buffer.point_components), 3)
    )
    uv_coords = tuple(
        Vector2(
            buffer.uv_components[index],
            buffer.uv_components[index + 1],
        )
        for index in range(0, len(buffer.uv_components), 2)
    )
    vertex_colors = tuple(
        Color4(
            buffer.vertex_color_components[index],
            buffer.vertex_color_components[index + 1],
            buffer.vertex_color_components[index + 2],
            buffer.vertex_color_components[index + 3] if index + 3 < len(buffer.vertex_color_components) else 1.0,
        )
        for index in range(0, len(buffer.vertex_color_components), 4)
    )
    sections = tuple(
        MeshSection(material_id=section.material_id, face_indices=tuple(section.face_indices))
        for section in buffer.sections
    )
    return MeshData(
        name=buffer.name,
        points=points,
        face_vertex_counts=tuple(buffer.face_vertex_counts),
        face_vertex_indices=tuple(buffer.face_vertex_indices),
        uv_coords=uv_coords,
        vertex_colors=vertex_colors,
        sections=sections,
        skel_joint_indices=tuple(buffer.skel_joint_indices),
        skel_joint_weights=tuple(buffer.skel_joint_weights),
        skel_element_size=buffer.skel_element_size,
    )


def payload_point_count(mesh: MeshData | None, geometry_payload: GeometryBuffer | None) -> int:
    if geometry_payload is not None:
        return geometry_payload.point_count
    return len(mesh.points) if mesh is not None else 0


def payload_face_count(mesh: MeshData | None, geometry_payload: GeometryBuffer | None) -> int:
    if geometry_payload is not None:
        return geometry_payload.face_count
    return len(mesh.face_vertex_counts) if mesh is not None else 0


def payload_sections(mesh: MeshData | None, geometry_payload: GeometryBuffer | None) -> tuple[MeshSection | CompactMeshSection, ...]:
    if geometry_payload is not None:
        return geometry_payload.sections
    if mesh is None:
        return ()
    return mesh.sections


def payload_has_face_topology(mesh: MeshData | None, geometry_payload: GeometryBuffer | None) -> bool:
    if geometry_payload is not None:
        return bool(geometry_payload.point_components and geometry_payload.face_vertex_counts and geometry_payload.face_vertex_indices)
    if mesh is None:
        return False
    return bool(mesh.points and mesh.face_vertex_counts and mesh.face_vertex_indices)


def replace_payload_sections(
    geometry_payload: GeometryBuffer,
    sections: tuple[CompactMeshSection, ...],
) -> GeometryBuffer:
    return replace(geometry_payload, sections=sections)


def single_material_sections(material_id: int, face_count: int) -> tuple[CompactMeshSection, ...]:
    if face_count <= 0:
        return ()
    return (CompactMeshSection(material_id=material_id, face_indices=array("i", range(face_count))),)


def payload_material_distribution(mesh: MeshData | None, geometry_payload: GeometryBuffer | None) -> dict[str, int]:
    distribution: dict[str, int] = {}
    for section in payload_sections(mesh, geometry_payload):
        distribution[str(section.material_id)] = len(section.face_indices)
    return distribution


def chunked_indexes(length: int, chunk_size: int) -> Iterator[range]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive.")
    for start in range(0, length, chunk_size):
        yield range(start, min(start + chunk_size, length))


def iter_face_ranges(face_vertex_counts: Iterable[int]) -> Iterator[tuple[int, int, int]]:
    offset = 0
    for face_index, face_count in enumerate(face_vertex_counts):
        yield face_index, offset, offset + face_count
        offset += face_count

