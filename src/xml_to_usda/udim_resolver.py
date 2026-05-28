"""UDIM operator intent resolution for authored mesh UV payloads."""

from __future__ import annotations

from array import array
from dataclasses import dataclass, replace

from .models import (
    CanonicalTreeModel,
    CompactMeshSection,
    GeometryBuffer,
    MeshData,
    MeshSection,
    Prototype,
    UdimMaterialSetting,
    UdimMode,
    Vector2,
)

BASE_UDIM = 1001
DEFAULT_SECONDARY_OFFSET = Vector2(0.5, 0.5)


@dataclass(frozen=True, slots=True)
class _ResolvedUdimSetting:
    material_id: int
    mode: UdimMode
    offset: Vector2


def apply_udim_material_settings(
    model: CanonicalTreeModel,
    settings: tuple[UdimMaterialSetting, ...],
) -> CanonicalTreeModel:
    active_settings = _resolve_active_udim_settings(settings)
    if not active_settings:
        return model

    base_mesh = _apply_settings_to_mesh(model.base_mesh, active_settings) if model.base_mesh is not None else None
    prototypes = tuple(_apply_settings_to_prototype(prototype, active_settings) for prototype in model.prototypes)
    return replace(model, base_mesh=base_mesh, prototypes=prototypes)


def _resolve_active_udim_settings(settings: tuple[UdimMaterialSetting, ...]) -> tuple[_ResolvedUdimSetting, ...]:
    active_settings: list[_ResolvedUdimSetting] = []
    for setting in settings:
        mode = UdimMode.parse(setting.mode)
        if mode == UdimMode.OFF:
            continue
        active_settings.append(
            _ResolvedUdimSetting(
                material_id=setting.material_id,
                mode=mode,
                offset=_udim_offset(setting.udim_id),
            )
        )
    return tuple(active_settings)


def _apply_settings_to_prototype(
    prototype: Prototype,
    settings: tuple[_ResolvedUdimSetting, ...],
) -> Prototype:
    mesh = _apply_settings_to_mesh(prototype.mesh, settings) if prototype.mesh is not None else None
    geometry_payload = (
        _apply_settings_to_geometry_buffer(prototype.geometry_payload, settings)
        if prototype.geometry_payload is not None
        else None
    )
    return replace(prototype, mesh=mesh, geometry_payload=geometry_payload)


def _apply_settings_to_mesh(
    mesh: MeshData | None,
    settings: tuple[_ResolvedUdimSetting, ...],
) -> MeshData | None:
    if mesh is None or not mesh.uv_coords:
        return mesh

    primary_uvs = list(mesh.uv_coords)
    write_secondary = any(setting.mode == UdimMode.WRITE_SECONDARY_UV_OFFSET for setting in settings)
    secondary_uvs = [DEFAULT_SECONDARY_OFFSET] * len(mesh.uv_coords) if write_secondary else list(mesh.secondary_uv_coords)
    if secondary_uvs and len(secondary_uvs) != len(mesh.uv_coords):
        secondary_uvs = [DEFAULT_SECONDARY_OFFSET] * len(mesh.uv_coords) if write_secondary else []

    wrote_secondary = bool(secondary_uvs)
    face_ranges = _face_vertex_ranges(mesh.face_vertex_counts)
    sections_by_material = _group_sections_by_material_id(mesh.sections)
    for setting in settings:
        for section in sections_by_material.get(setting.material_id, ()):
            if setting.mode == UdimMode.SHIFT_PRIMARY_UV:
                _shift_primary_uvs(primary_uvs, face_ranges, section.face_indices, setting.offset)
            elif setting.mode == UdimMode.WRITE_SECONDARY_UV_OFFSET:
                _write_secondary_uvs(secondary_uvs, face_ranges, section.face_indices, setting.offset)
                wrote_secondary = True

    return replace(
        mesh,
        uv_coords=tuple(primary_uvs),
        secondary_uv_coords=tuple(secondary_uvs) if wrote_secondary else mesh.secondary_uv_coords,
    )


def _apply_settings_to_geometry_buffer(
    mesh: GeometryBuffer | None,
    settings: tuple[_ResolvedUdimSetting, ...],
) -> GeometryBuffer | None:
    if mesh is None or not mesh.uv_components:
        return mesh

    primary_uvs = array("f", mesh.uv_components)
    write_secondary = any(setting.mode == UdimMode.WRITE_SECONDARY_UV_OFFSET for setting in settings)
    secondary_uvs = _default_secondary_uv_components(len(primary_uvs)) if write_secondary else array("f", mesh.secondary_uv_components)
    if secondary_uvs and len(secondary_uvs) != len(primary_uvs):
        secondary_uvs = _default_secondary_uv_components(len(primary_uvs)) if write_secondary else array("f")

    wrote_secondary = bool(secondary_uvs)
    face_ranges = _face_vertex_ranges(mesh.face_vertex_counts)
    sections_by_material = _group_sections_by_material_id(mesh.sections)
    for setting in settings:
        for section in sections_by_material.get(setting.material_id, ()):
            if setting.mode == UdimMode.SHIFT_PRIMARY_UV:
                _shift_primary_uv_components(primary_uvs, face_ranges, section.face_indices, setting.offset)
            elif setting.mode == UdimMode.WRITE_SECONDARY_UV_OFFSET:
                _write_secondary_uv_components(secondary_uvs, face_ranges, section.face_indices, setting.offset)
                wrote_secondary = True

    return replace(
        mesh,
        uv_components=primary_uvs,
        secondary_uv_components=secondary_uvs if wrote_secondary else mesh.secondary_uv_components,
    )


def _udim_offset(udim_id: int) -> Vector2:
    delta = udim_id - BASE_UDIM
    return Vector2(float(delta % 10), float(delta // 10))


def _face_vertex_ranges(face_vertex_counts) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    start = 0
    for count in face_vertex_counts:
        end = start + int(count)
        ranges.append((start, end))
        start = end
    return tuple(ranges)


def _group_sections_by_material_id(
    sections: tuple[MeshSection | CompactMeshSection, ...],
) -> dict[int, tuple[MeshSection | CompactMeshSection, ...]]:
    grouped_sections: dict[int, list[MeshSection | CompactMeshSection]] = {}
    for section in sections:
        grouped_sections.setdefault(section.material_id, []).append(section)
    return {material_id: tuple(section_group) for material_id, section_group in grouped_sections.items()}


def _shift_primary_uvs(
    uvs: list[Vector2],
    face_ranges: tuple[tuple[int, int], ...],
    face_indices,
    offset: Vector2,
) -> None:
    for face_vertex_index in _iter_section_face_vertices(face_ranges, face_indices):
        if 0 <= face_vertex_index < len(uvs):
            uv = uvs[face_vertex_index]
            uvs[face_vertex_index] = Vector2(uv.x + offset.x, uv.y + offset.y)


def _write_secondary_uvs(
    uvs: list[Vector2],
    face_ranges: tuple[tuple[int, int], ...],
    face_indices,
    offset: Vector2,
) -> None:
    value = Vector2(offset.x + 0.5, offset.y + 0.5)
    for face_vertex_index in _iter_section_face_vertices(face_ranges, face_indices):
        if 0 <= face_vertex_index < len(uvs):
            uvs[face_vertex_index] = value


def _shift_primary_uv_components(
    uv_components: array,
    face_ranges: tuple[tuple[int, int], ...],
    face_indices,
    offset: Vector2,
) -> None:
    for face_vertex_index in _iter_section_face_vertices(face_ranges, face_indices):
        component_index = face_vertex_index * 2
        if component_index + 1 < len(uv_components):
            uv_components[component_index] += offset.x
            uv_components[component_index + 1] += offset.y


def _write_secondary_uv_components(
    uv_components: array,
    face_ranges: tuple[tuple[int, int], ...],
    face_indices,
    offset: Vector2,
) -> None:
    for face_vertex_index in _iter_section_face_vertices(face_ranges, face_indices):
        component_index = face_vertex_index * 2
        if component_index + 1 < len(uv_components):
            uv_components[component_index] = offset.x + 0.5
            uv_components[component_index + 1] = offset.y + 0.5


def _iter_section_face_vertices(
    face_ranges: tuple[tuple[int, int], ...],
    face_indices,
):
    for face_index in face_indices:
        if face_index < 0 or face_index >= len(face_ranges):
            continue
        start, end = face_ranges[face_index]
        yield from range(start, end)


def _default_secondary_uv_components(primary_component_count: int) -> array:
    return array("f", (DEFAULT_SECONDARY_OFFSET.x, DEFAULT_SECONDARY_OFFSET.y)) * (primary_component_count // 2)
