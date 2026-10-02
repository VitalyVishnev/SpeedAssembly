"""UDIM operator intent resolution for authored mesh UV payloads."""

from __future__ import annotations

from array import array
from dataclasses import dataclass, replace

from .models import (
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


def apply_udim_settings_to_mesh_data(
    mesh: MeshData | None,
    settings: tuple[UdimMaterialSetting, ...],
    *,
    label: str = "Mesh",
) -> MeshData | None:
    active_settings = _resolve_active_udim_settings(settings)
    if mesh is None:
        if active_settings:
            raise ValueError(f"{label} has no geometry to receive UDIM settings.")
        return None
    if not active_settings:
        return mesh
    return _apply_settings_to_mesh(mesh, active_settings, label=label)


def apply_udim_settings_to_geometry_buffer(
    geometry_buffer: GeometryBuffer | None,
    settings: tuple[UdimMaterialSetting, ...],
    *,
    label: str = "Mesh",
) -> GeometryBuffer | None:
    active_settings = _resolve_active_udim_settings(settings)
    if geometry_buffer is None:
        if active_settings:
            raise ValueError(f"{label} has no geometry to receive UDIM settings.")
        return None
    if not active_settings:
        return geometry_buffer
    return _apply_settings_to_geometry_buffer(geometry_buffer, active_settings, label=label)


def apply_udim_settings_to_prototype(
    prototype: Prototype,
    settings: tuple[UdimMaterialSetting, ...],
) -> Prototype:
    active_settings = _resolve_active_udim_settings(settings)
    if not active_settings:
        return prototype
    label = f"Prototype {prototype.identity.prim_name}"
    if prototype.geometry_payload is not None:
        geometry_payload = _apply_settings_to_geometry_buffer(prototype.geometry_payload, active_settings, label=label)
        return replace(prototype, geometry_payload=geometry_payload)
    if prototype.mesh is not None:
        mesh = _apply_settings_to_mesh(prototype.mesh, active_settings, label=label)
        return replace(prototype, mesh=mesh)
    raise ValueError(f"{label} has no authored geometry to receive UDIM settings.")


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


def _apply_settings_to_mesh(
    mesh: MeshData | None,
    settings: tuple[_ResolvedUdimSetting, ...],
    *,
    label: str = "Mesh",
) -> MeshData | None:
    if mesh is None or not mesh.uv_coords:
        return mesh

    face_ranges = _face_vertex_ranges(mesh.face_vertex_counts)
    sections_by_material = _group_sections_by_material_id(mesh.sections)
    _validate_piece_udim_targets(sections_by_material, settings, label)
    shift_primary = any(setting.mode == UdimMode.SHIFT_PRIMARY_UV for setting in settings)
    write_secondary = any(setting.mode == UdimMode.WRITE_SECONDARY_UV_OFFSET for setting in settings)
    if not shift_primary and not write_secondary:
        return mesh

    primary_uvs = list(mesh.uv_coords) if shift_primary else None
    secondary_uvs = [DEFAULT_SECONDARY_OFFSET] * len(mesh.uv_coords) if write_secondary else None
    for setting in settings:
        for section in sections_by_material.get(setting.material_id, ()):
            if setting.mode == UdimMode.SHIFT_PRIMARY_UV and primary_uvs is not None:
                _shift_primary_uvs(primary_uvs, face_ranges, section.face_indices, setting.offset)
            elif setting.mode == UdimMode.WRITE_SECONDARY_UV_OFFSET and secondary_uvs is not None:
                _write_secondary_uvs(secondary_uvs, face_ranges, section.face_indices, setting.offset)

    if primary_uvs is None:
        resolved_secondary_uvs = tuple(secondary_uvs) if secondary_uvs is not None else mesh.secondary_uv_coords
        return replace(mesh, secondary_uv_coords=resolved_secondary_uvs)
    if secondary_uvs is None:
        return replace(mesh, uv_coords=tuple(primary_uvs))
    return replace(mesh, uv_coords=tuple(primary_uvs), secondary_uv_coords=tuple(secondary_uvs))


def _apply_settings_to_geometry_buffer(
    mesh: GeometryBuffer | None,
    settings: tuple[_ResolvedUdimSetting, ...],
    *,
    label: str = "Mesh",
) -> GeometryBuffer | None:
    if mesh is None or not mesh.uv_components:
        return mesh

    face_ranges = _face_vertex_ranges(mesh.face_vertex_counts)
    sections_by_material = _group_sections_by_material_id(mesh.sections)
    _validate_piece_udim_targets(sections_by_material, settings, label)
    shift_primary = any(setting.mode == UdimMode.SHIFT_PRIMARY_UV for setting in settings)
    write_secondary = any(setting.mode == UdimMode.WRITE_SECONDARY_UV_OFFSET for setting in settings)
    if not shift_primary and not write_secondary:
        return mesh

    primary_uvs = array("f", mesh.uv_components) if shift_primary else None
    secondary_uvs = _default_secondary_uv_components(len(mesh.uv_components)) if write_secondary else None
    for setting in settings:
        for section in sections_by_material.get(setting.material_id, ()):
            if setting.mode == UdimMode.SHIFT_PRIMARY_UV and primary_uvs is not None:
                _shift_primary_uv_components(primary_uvs, face_ranges, section.face_indices, setting.offset)
            elif setting.mode == UdimMode.WRITE_SECONDARY_UV_OFFSET and secondary_uvs is not None:
                _write_secondary_uv_components(secondary_uvs, face_ranges, section.face_indices, setting.offset)

    if primary_uvs is None:
        resolved_secondary_uvs = secondary_uvs if secondary_uvs is not None else mesh.secondary_uv_components
        return replace(mesh, secondary_uv_components=resolved_secondary_uvs)
    if secondary_uvs is None:
        return replace(mesh, uv_components=primary_uvs)
    return replace(mesh, uv_components=primary_uvs, secondary_uv_components=secondary_uvs)


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


def _validate_piece_udim_targets(
    sections_by_material: dict[int, tuple[MeshSection | CompactMeshSection, ...]],
    settings: tuple[_ResolvedUdimSetting, ...],
    label: str,
) -> None:
    seen_material_ids: set[int] = set()
    missing_material_ids: list[int] = []
    for setting in settings:
        if setting.material_id in seen_material_ids:
            raise ValueError(
                f"{label} has multiple active UDIM settings for material id {setting.material_id}."
            )
        seen_material_ids.add(setting.material_id)
        if setting.material_id not in sections_by_material:
            missing_material_ids.append(setting.material_id)
    if missing_material_ids:
        missing_payload = ", ".join(str(material_id) for material_id in missing_material_ids)
        raise ValueError(f"{label} has no material sections for UDIM material id(s): {missing_payload}.")


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
