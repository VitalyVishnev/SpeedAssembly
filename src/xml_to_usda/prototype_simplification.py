"""Resolved Prototype simplification.

Layer: domain.

This module owns export-affecting simplification for inline Resolved
Prototypes. It preserves final material sections by simplifying each resolved
material section independently; callers do not need to know the QEM backend,
attribute wedges, or section rebasing details.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass, replace
from typing import Iterable

from .geometry_buffers import geometry_buffer_from_mesh, geometry_buffer_to_mesh
from .models import (
    CanonicalTreeModel,
    Color4,
    CompactMeshSection,
    GeometryBuffer,
    MeshData,
    MeshSection,
    Prototype,
    PrototypeResolutionMode,
    Vector2,
    Vector3,
)


class PrototypeSimplificationError(ValueError):
    pass


@dataclass(frozen=True)
class _SectionTriangles:
    material_id: int | None
    triangles: tuple[tuple[int, int, int], ...]
    corners: tuple[tuple[int, int, int], ...]


@dataclass(frozen=True)
class _SectionSimplificationResult:
    point_components: array
    face_vertex_counts: array
    face_vertex_indices: array
    uv_components: array
    secondary_uv_components: array
    vertex_color_components: array
    skel_joint_indices: array
    skel_joint_weights: array
    face_count: int


@dataclass(frozen=True)
class _WedgeAttributes:
    source_point: int
    uv: Vector2 | None
    secondary_uv: Vector2 | None
    color: Color4 | None
    skel_indices: tuple[int, ...]
    skel_weights: tuple[float, ...]


def simplify_resolved_prototypes(model: CanonicalTreeModel, *, cancel_event=None) -> CanonicalTreeModel:
    prototypes = tuple(
        _simplify_prototype(prototype, cancel_event=cancel_event)
        for prototype in model.prototypes
    )
    if prototypes == model.prototypes:
        return model
    return replace(model, prototypes=prototypes)


def simplify_prototype_payload(
    prototype: Prototype,
    *,
    percent: int | None = None,
    cancel_event=None,
) -> MeshData | GeometryBuffer | None:
    resolved_percent = _coerce_percent(prototype.simplification_percent if percent is None else percent)
    if resolved_percent >= 100:
        return prototype.geometry_payload or prototype.mesh
    if prototype.resolution_mode == PrototypeResolutionMode.EXTERNAL_ASSET:
        return prototype.geometry_payload or prototype.mesh
    if prototype.geometry_payload is not None:
        return simplify_geometry_buffer(prototype.geometry_payload, resolved_percent, cancel_event=cancel_event)
    if prototype.mesh is not None:
        return simplify_mesh_data(prototype.mesh, resolved_percent, cancel_event=cancel_event)
    return None


def simplify_mesh_data(mesh: MeshData, percent: int, *, cancel_event=None) -> MeshData:
    simplified = simplify_geometry_buffer(geometry_buffer_from_mesh(mesh), percent, cancel_event=cancel_event)
    return geometry_buffer_to_mesh(simplified)


def simplify_geometry_buffer(mesh: GeometryBuffer, percent: int, *, cancel_event=None) -> GeometryBuffer:
    percent = _coerce_percent(percent)
    if percent >= 100 or mesh.face_count == 0:
        return mesh
    sections = _section_triangles(mesh)
    if not sections:
        return mesh

    point_components = array("f")
    face_vertex_counts = array("i")
    face_vertex_indices = array("i")
    uv_components = array("f")
    secondary_uv_components = array("f")
    vertex_color_components = array("f")
    skel_joint_indices = array("i")
    skel_joint_weights = array("f")
    output_sections: list[CompactMeshSection] = []
    point_offset = 0
    face_offset = 0
    target_counts = _target_counts(sections, percent)

    for section, target_count in zip(sections, target_counts, strict=True):
        _throw_if_cancelled(cancel_event)
        if not section.triangles:
            continue
        result = _simplify_section(mesh, section, target_count=target_count)
        point_components.extend(result.point_components)
        face_vertex_counts.extend(result.face_vertex_counts)
        face_vertex_indices.extend(index + point_offset for index in result.face_vertex_indices)
        uv_components.extend(result.uv_components)
        secondary_uv_components.extend(result.secondary_uv_components)
        vertex_color_components.extend(result.vertex_color_components)
        skel_joint_indices.extend(result.skel_joint_indices)
        skel_joint_weights.extend(result.skel_joint_weights)
        if section.material_id is not None and result.face_count:
            output_sections.append(
                CompactMeshSection(
                    material_id=section.material_id,
                    face_indices=array("i", range(face_offset, face_offset + result.face_count)),
                )
            )
        point_offset += len(result.point_components) // 3
        face_offset += result.face_count

    if not face_vertex_counts:
        raise PrototypeSimplificationError(f"Prototype simplification produced no faces for {mesh.name}.")
    return GeometryBuffer(
        name=mesh.name,
        point_components=point_components,
        face_vertex_counts=face_vertex_counts,
        face_vertex_indices=face_vertex_indices,
        uv_components=uv_components,
        secondary_uv_components=secondary_uv_components,
        vertex_color_components=vertex_color_components,
        vertex_color_warning=mesh.vertex_color_warning,
        fbx_material_slots=mesh.fbx_material_slots,
        sections=tuple(output_sections) if mesh.sections else (),
        skel_joint_indices=skel_joint_indices,
        skel_joint_weights=skel_joint_weights,
        skel_element_size=mesh.skel_element_size if skel_joint_indices else 0,
    )


def predicted_simplified_triangle_count(mesh: GeometryBuffer | MeshData, percent: int) -> int:
    buffer = geometry_buffer_from_mesh(mesh) if isinstance(mesh, MeshData) else mesh
    percent = _coerce_percent(percent)
    if percent >= 100:
        return _triangle_count(buffer)
    return sum(_target_counts(_section_triangles(buffer), percent))


def _simplify_prototype(prototype: Prototype, *, cancel_event=None) -> Prototype:
    percent = _coerce_percent(prototype.simplification_percent)
    if percent >= 100 or prototype.resolution_mode == PrototypeResolutionMode.EXTERNAL_ASSET:
        return prototype
    if prototype.geometry_payload is not None:
        return replace(
            prototype,
            geometry_payload=simplify_geometry_buffer(prototype.geometry_payload, percent, cancel_event=cancel_event),
        )
    if prototype.mesh is not None:
        return replace(
            prototype,
            mesh=simplify_mesh_data(prototype.mesh, percent, cancel_event=cancel_event),
        )
    return prototype


def _simplify_section(
    mesh: GeometryBuffer,
    section: _SectionTriangles,
    *,
    target_count: int,
) -> _SectionSimplificationResult:
    import numpy as np

    input_points, input_triangles, attributes = _build_section_wedge_mesh(mesh, section)
    if len(input_triangles) <= target_count:
        output_points = input_points
        output_triangles = input_triangles
        mapping = np.arange(len(input_points), dtype=np.int64)
    else:
        try:
            import fast_simplification
            from fast_simplification.replay import replay_simplification
        except ImportError as exc:
            raise PrototypeSimplificationError(
                "Prototype simplification requires the fast-simplification package."
            ) from exc
        try:
            _points, _triangles, collapses = fast_simplification.simplify(
                input_points,
                input_triangles,
                target_count=max(1, int(target_count)),
                return_collapses=True,
            )
            output_points, output_triangles, mapping = replay_simplification(
                input_points.astype(np.float32),
                input_triangles,
                collapses,
            )
        except Exception as exc:
            raise PrototypeSimplificationError(f"Prototype QEM simplification failed for {mesh.name}: {exc}") from exc

    point_attributes = _attributes_by_output_point(attributes, mapping, len(output_points))
    return _build_result_from_triangles(
        output_points,
        output_triangles,
        point_attributes,
        skel_element_size=mesh.skel_element_size,
    )


def _build_section_wedge_mesh(
    mesh: GeometryBuffer,
    section: _SectionTriangles,
):
    import numpy as np

    points = _points(mesh)
    uv_by_corner = _uvs(mesh.uv_components)
    secondary_uv_by_corner = _uvs(mesh.secondary_uv_components)
    color_by_point = _colors(mesh.vertex_color_components)
    vertex_map: dict[tuple[object, ...], int] = {}
    wedge_points: list[tuple[float, float, float]] = []
    wedge_attributes: list[_WedgeAttributes] = []
    triangles: list[tuple[int, int, int]] = []
    for triangle, corners in zip(section.triangles, section.corners, strict=True):
        wedge_triangle: list[int] = []
        for source_point, corner in zip(triangle, corners, strict=True):
            attribute = _wedge_attributes(mesh, source_point, corner, uv_by_corner, secondary_uv_by_corner, color_by_point)
            key = _wedge_key(attribute)
            wedge_index = vertex_map.get(key)
            if wedge_index is None:
                wedge_index = len(wedge_points)
                vertex_map[key] = wedge_index
                source_position = points[source_point]
                wedge_points.append((source_position.x, source_position.y, source_position.z))
                wedge_attributes.append(attribute)
            wedge_triangle.append(wedge_index)
        triangles.append((wedge_triangle[0], wedge_triangle[1], wedge_triangle[2]))
    return (
        np.asarray(wedge_points, dtype=np.float64),
        np.asarray(triangles, dtype=np.int32),
        tuple(wedge_attributes),
    )


def _build_result_from_triangles(
    points,
    triangles,
    point_attributes: tuple[_WedgeAttributes, ...],
    *,
    skel_element_size: int,
) -> _SectionSimplificationResult:
    point_components = array("f")
    for point in points:
        point_components.extend((float(point[0]), float(point[1]), float(point[2])))

    face_vertex_counts = array("i")
    face_vertex_indices = array("i")
    uv_components = array("f")
    secondary_uv_components = array("f")
    for triangle in triangles:
        face_vertex_counts.append(3)
        for raw_index in triangle:
            point_index = int(raw_index)
            face_vertex_indices.append(point_index)
            attribute = point_attributes[point_index]
            if attribute.uv is not None:
                uv_components.extend((attribute.uv.x, attribute.uv.y))
            if attribute.secondary_uv is not None:
                secondary_uv_components.extend((attribute.secondary_uv.x, attribute.secondary_uv.y))

    vertex_color_components = array("f")
    if any(attribute.color is not None for attribute in point_attributes):
        for attribute in point_attributes:
            color = attribute.color or Color4(1.0, 1.0, 1.0, 1.0)
            vertex_color_components.extend((color.r, color.g, color.b, color.a))

    skel_joint_indices = array("i")
    skel_joint_weights = array("f")
    if skel_element_size > 0 and any(attribute.skel_indices for attribute in point_attributes):
        for attribute in point_attributes:
            indices = _padded_ints(attribute.skel_indices, skel_element_size)
            weights = _padded_floats(attribute.skel_weights, skel_element_size)
            skel_joint_indices.extend(indices)
            skel_joint_weights.extend(weights)

    return _SectionSimplificationResult(
        point_components=point_components,
        face_vertex_counts=face_vertex_counts,
        face_vertex_indices=face_vertex_indices,
        uv_components=uv_components,
        secondary_uv_components=secondary_uv_components,
        vertex_color_components=vertex_color_components,
        skel_joint_indices=skel_joint_indices,
        skel_joint_weights=skel_joint_weights,
        face_count=len(face_vertex_counts),
    )


def _attributes_by_output_point(
    attributes: tuple[_WedgeAttributes, ...],
    mapping,
    output_point_count: int,
) -> tuple[_WedgeAttributes, ...]:
    grouped: list[list[_WedgeAttributes]] = [[] for _ in range(output_point_count)]
    for source_index, output_index in enumerate(mapping):
        if 0 <= int(output_index) < output_point_count:
            grouped[int(output_index)].append(attributes[source_index])
    resolved = []
    for group in grouped:
        if not group:
            resolved.append(_WedgeAttributes(0, None, None, None, (), ()))
            continue
        resolved.append(_merge_attributes(group))
    return tuple(resolved)


def _merge_attributes(group: list[_WedgeAttributes]) -> _WedgeAttributes:
    first = group[0]
    return _WedgeAttributes(
        source_point=first.source_point,
        uv=_average_uv(attribute.uv for attribute in group),
        secondary_uv=_average_uv(attribute.secondary_uv for attribute in group),
        color=_average_color(attribute.color for attribute in group),
        skel_indices=first.skel_indices,
        skel_weights=first.skel_weights,
    )


def _section_triangles(mesh: GeometryBuffer) -> tuple[_SectionTriangles, ...]:
    face_triangles, face_corners = _triangles_by_face(mesh.face_vertex_counts, mesh.face_vertex_indices)
    if not mesh.sections:
        triangles = tuple(triangle for face in face_triangles for triangle in face)
        corners = tuple(corner for face in face_corners for corner in face)
        return (_SectionTriangles(material_id=None, triangles=triangles, corners=corners),) if triangles else ()
    sections: list[_SectionTriangles] = []
    for section in mesh.sections:
        triangles: list[tuple[int, int, int]] = []
        corners: list[tuple[int, int, int]] = []
        for face_index in section.face_indices:
            if 0 <= int(face_index) < len(face_triangles):
                triangles.extend(face_triangles[int(face_index)])
                corners.extend(face_corners[int(face_index)])
        if triangles:
            sections.append(
                _SectionTriangles(
                    material_id=section.material_id,
                    triangles=tuple(triangles),
                    corners=tuple(corners),
                )
            )
    return tuple(sections)


def _triangles_by_face(face_counts: Iterable[int], face_indices: Iterable[int]):
    indices = list(face_indices)
    face_triangles: list[list[tuple[int, int, int]]] = []
    face_corners: list[list[tuple[int, int, int]]] = []
    offset = 0
    for count in face_counts:
        count = int(count)
        polygon = indices[offset:offset + count]
        corner_indices = list(range(offset, offset + count))
        offset += count
        triangles: list[tuple[int, int, int]] = []
        corners: list[tuple[int, int, int]] = []
        if count >= 3:
            for index in range(1, count - 1):
                triangles.append((polygon[0], polygon[index], polygon[index + 1]))
                corners.append((corner_indices[0], corner_indices[index], corner_indices[index + 1]))
        face_triangles.append(triangles)
        face_corners.append(corners)
    return face_triangles, face_corners


def _target_counts(sections: tuple[_SectionTriangles, ...], percent: int) -> tuple[int, ...]:
    percent = _coerce_percent(percent)
    if percent <= 0:
        return tuple(1 for section in sections if section.triangles)
    return tuple(
        max(1, min(len(section.triangles), int(round(len(section.triangles) * percent / 100.0))))
        for section in sections
        if section.triangles
    )


def _wedge_attributes(
    mesh: GeometryBuffer,
    point_index: int,
    corner_index: int,
    uv_by_corner: tuple[Vector2, ...],
    secondary_uv_by_corner: tuple[Vector2, ...],
    color_by_point: tuple[Color4, ...],
) -> _WedgeAttributes:
    return _WedgeAttributes(
        source_point=point_index,
        uv=uv_by_corner[corner_index] if corner_index < len(uv_by_corner) else None,
        secondary_uv=secondary_uv_by_corner[corner_index] if corner_index < len(secondary_uv_by_corner) else None,
        color=color_by_point[point_index] if point_index < len(color_by_point) else None,
        skel_indices=_skel_indices(mesh, point_index),
        skel_weights=_skel_weights(mesh, point_index),
    )


def _wedge_key(attribute: _WedgeAttributes) -> tuple[object, ...]:
    return (
        attribute.source_point,
        _uv_key(attribute.uv),
        _uv_key(attribute.secondary_uv),
        _color_key(attribute.color),
        attribute.skel_indices,
        tuple(round(value, 8) for value in attribute.skel_weights),
    )


def _points(mesh: GeometryBuffer) -> tuple[Vector3, ...]:
    return tuple(
        Vector3(mesh.point_components[index], mesh.point_components[index + 1], mesh.point_components[index + 2])
        for index in range(0, len(mesh.point_components), 3)
    )


def _uvs(components: array) -> tuple[Vector2, ...]:
    return tuple(Vector2(components[index], components[index + 1]) for index in range(0, len(components), 2))


def _colors(components: array) -> tuple[Color4, ...]:
    return tuple(
        Color4(components[index], components[index + 1], components[index + 2], components[index + 3])
        for index in range(0, len(components), 4)
        if index + 3 < len(components)
    )


def _skel_indices(mesh: GeometryBuffer, point_index: int) -> tuple[int, ...]:
    if mesh.skel_element_size <= 0:
        return ()
    start = point_index * mesh.skel_element_size
    end = start + mesh.skel_element_size
    if end > len(mesh.skel_joint_indices):
        return ()
    return tuple(int(value) for value in mesh.skel_joint_indices[start:end])


def _skel_weights(mesh: GeometryBuffer, point_index: int) -> tuple[float, ...]:
    if mesh.skel_element_size <= 0:
        return ()
    start = point_index * mesh.skel_element_size
    end = start + mesh.skel_element_size
    if end > len(mesh.skel_joint_weights):
        return ()
    return tuple(float(value) for value in mesh.skel_joint_weights[start:end])


def _average_uv(values: Iterable[Vector2 | None]) -> Vector2 | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return Vector2(
        sum(value.x for value in present) / len(present),
        sum(value.y for value in present) / len(present),
    )


def _average_color(values: Iterable[Color4 | None]) -> Color4 | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return Color4(
        sum(value.r for value in present) / len(present),
        sum(value.g for value in present) / len(present),
        sum(value.b for value in present) / len(present),
        sum(value.a for value in present) / len(present),
    )


def _padded_ints(values: tuple[int, ...], width: int) -> tuple[int, ...]:
    if len(values) >= width:
        return values[:width]
    return values + (0,) * (width - len(values))


def _padded_floats(values: tuple[float, ...], width: int) -> tuple[float, ...]:
    if len(values) >= width:
        return values[:width]
    return values + (0.0,) * (width - len(values))


def _uv_key(value: Vector2 | None) -> tuple[float, float] | None:
    if value is None:
        return None
    return (round(value.x, 8), round(value.y, 8))


def _color_key(value: Color4 | None) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    return (round(value.r, 8), round(value.g, 8), round(value.b, 8), round(value.a, 8))


def _triangle_count(mesh: GeometryBuffer) -> int:
    return sum(max(0, int(count) - 2) for count in mesh.face_vertex_counts)


def _coerce_percent(value: int) -> int:
    return max(0, min(100, int(value)))


def _throw_if_cancelled(cancel_event) -> None:
    if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
        raise PrototypeSimplificationError("Prototype simplification was cancelled.")
