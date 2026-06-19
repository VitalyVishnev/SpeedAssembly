from __future__ import annotations

from array import array

import pytest

from xml_to_usda.models import (
    CompactMeshSection,
    GeometryBuffer,
    Prototype,
    PrototypeIdentity,
    Vector3,
    UdimMaterialSetting,
    UdimMode,
    Vector2,
    MeshData,
    MeshSection,
)
from xml_to_usda.udim_resolver import (
    apply_udim_settings_to_geometry_buffer,
    apply_udim_settings_to_mesh_data,
    apply_udim_settings_to_prototype,
)


def _build_mesh_data(face_count: int) -> MeshData:
    face_counts = tuple(3 for _ in range(face_count))
    uv_pattern = (
        Vector2(0.0, 0.0),
        Vector2(1.0, 0.0),
        Vector2(0.0, 1.0),
    )
    sections = tuple(
        MeshSection(material_id=index + 1, face_indices=tuple(range(start, end)))
        for index, (start, end) in enumerate(_face_ranges(face_count, 10))
    )
    return MeshData(
        name="UDIMBenchMesh",
        points=(Vector3(0.0, 0.0, 0.0), Vector3(1.0, 0.0, 0.0), Vector3(0.0, 1.0, 0.0)),
        face_vertex_counts=face_counts,
        face_vertex_indices=tuple(vertex for _ in range(face_count) for vertex in (0, 1, 2)),
        uv_coords=uv_pattern * face_count,
        sections=sections,
    )


def _face_ranges(face_count: int, section_count: int) -> tuple[tuple[int, int], ...]:
    base_size = face_count // section_count
    remainder = face_count % section_count
    ranges: list[tuple[int, int]] = []
    start = 0
    for index in range(section_count):
        size = base_size + (1 if index < remainder else 0)
        end = start + size
        if size > 0:
            ranges.append((start, end))
        start = end
    return tuple(ranges)


def _build_geometry_buffer(face_count: int) -> GeometryBuffer:
    face_counts = array("i", (3 for _ in range(face_count)))
    face_indices = array("i", (vertex for _ in range(face_count) for vertex in (0, 1, 2)))
    uv_components = array("f", (0.0, 0.0, 1.0, 0.0, 0.0, 1.0)) * face_count
    sections = tuple(
        CompactMeshSection(material_id=index + 1, face_indices=array("i", range(start, end)))
        for index, (start, end) in enumerate(_face_ranges(face_count, 10))
    )
    return GeometryBuffer(
        name="UDIMBenchGeometry",
        point_components=array("f", (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)),
        face_vertex_counts=face_counts,
        face_vertex_indices=face_indices,
        uv_components=uv_components,
        sections=sections,
    )


def test_udim_secondary_uv_authoring_overwrites_existing_geometry_channel_with_default_fill() -> None:
    face_count = 12000
    geometry_payload = _build_geometry_buffer(face_count)
    geometry_payload = GeometryBuffer(
        name=geometry_payload.name,
        point_components=geometry_payload.point_components,
        face_vertex_counts=geometry_payload.face_vertex_counts,
        face_vertex_indices=geometry_payload.face_vertex_indices,
        uv_components=geometry_payload.uv_components,
        secondary_uv_components=array("f", (9.0, 9.0, 8.0, 8.0, 7.0, 7.0)) * face_count,
        sections=geometry_payload.sections,
    )
    setting = (UdimMaterialSetting(material_id=1, mode=UdimMode.WRITE_SECONDARY_UV_OFFSET, udim_id=1003),)

    resolved = apply_udim_settings_to_geometry_buffer(geometry_payload, setting, label="Prototype Proto")

    assert resolved is not None
    secondary_uvs = resolved.secondary_uv_components
    assert len(secondary_uvs) == len(resolved.uv_components)
    assert secondary_uvs[:2] == array("f", (2.5, 0.5))
    assert secondary_uvs[-2:] == array("f", (0.5, 0.5))


def test_piece_local_udim_helper_does_not_couple_separate_piece_payloads() -> None:
    base_mesh = _build_mesh_data(1)
    prototype = Prototype(
        identity=PrototypeIdentity(source_key="proto", prim_name="Proto"),
        mesh=_build_mesh_data(1),
        source_key="proto",
        source_mesh_id=None,
        source_name="Proto",
    )
    base_resolved = apply_udim_settings_to_mesh_data(
        base_mesh,
        (UdimMaterialSetting(material_id=1, mode=UdimMode.WRITE_SECONDARY_UV_OFFSET, udim_id=1003),),
        label="Base Skeletal Tree",
    )
    prototype_resolved = apply_udim_settings_to_prototype(
        prototype,
        (UdimMaterialSetting(material_id=1, mode=UdimMode.SHIFT_PRIMARY_UV, udim_id=1004),),
    )

    assert base_resolved is not None
    assert base_resolved.secondary_uv_coords == (
        Vector2(2.5, 0.5),
        Vector2(2.5, 0.5),
        Vector2(2.5, 0.5),
    )
    assert prototype_resolved.mesh is not None
    assert prototype_resolved.mesh.uv_coords[0] == Vector2(3.0, 0.0)


def test_piece_local_udim_helper_keeps_same_numeric_material_id_isolated_per_piece() -> None:
    mesh_a = _build_mesh_data(1)
    mesh_b = _build_mesh_data(1)

    resolved_a = apply_udim_settings_to_mesh_data(
        mesh_a,
        (UdimMaterialSetting(material_id=1, mode=UdimMode.SHIFT_PRIMARY_UV, udim_id=1003),),
        label="Piece A",
    )
    resolved_b = apply_udim_settings_to_mesh_data(
        mesh_b,
        (UdimMaterialSetting(material_id=1, mode=UdimMode.WRITE_SECONDARY_UV_OFFSET, udim_id=1004),),
        label="Piece B",
    )

    assert resolved_a is not None
    assert resolved_b is not None
    assert resolved_a.uv_coords[0] == Vector2(2.0, 0.0)
    assert resolved_b.secondary_uv_coords[0] == Vector2(3.5, 0.5)


def test_piece_local_udim_helper_rejects_duplicate_active_settings_on_one_piece() -> None:
    mesh = _build_mesh_data(1)

    with pytest.raises(ValueError, match="multiple active UDIM settings for material id 1"):
        apply_udim_settings_to_mesh_data(
            mesh,
            (
                UdimMaterialSetting(material_id=1, mode=UdimMode.SHIFT_PRIMARY_UV, udim_id=1003),
                UdimMaterialSetting(material_id=1, mode=UdimMode.SHIFT_PRIMARY_UV, udim_id=1004),
            ),
            label="Piece A",
        )


def test_piece_local_udim_helper_rejects_missing_and_duplicate_targets() -> None:
    mesh = _build_mesh_data(1)

    with pytest.raises(ValueError, match="Piece A has no material sections for UDIM material id\\(s\\): 2"):
        apply_udim_settings_to_mesh_data(
            mesh,
            (UdimMaterialSetting(material_id=2, mode=UdimMode.SHIFT_PRIMARY_UV, udim_id=1003),),
            label="Piece A",
        )

    with pytest.raises(ValueError, match="multiple active UDIM settings for material id 1"):
        apply_udim_settings_to_mesh_data(
            mesh,
            (
                UdimMaterialSetting(material_id=1, mode=UdimMode.SHIFT_PRIMARY_UV, udim_id=1003),
                UdimMaterialSetting(material_id=1, mode=UdimMode.WRITE_SECONDARY_UV_OFFSET, udim_id=1004),
            ),
            label="Piece A",
        )
