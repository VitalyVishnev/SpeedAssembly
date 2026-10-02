from __future__ import annotations

from array import array

from xml_to_usda.geometry_buffers import (
    chunked_indexes,
    geometry_buffer_from_mesh,
    geometry_buffer_to_mesh,
    iter_face_ranges,
    payload_face_count,
    payload_has_face_topology,
    payload_material_distribution,
    payload_point_count,
    payload_sections,
    replace_payload_sections,
    single_material_sections,
)
from xml_to_usda.models import Color4, GeometryBuffer, MeshData, MeshSection, Vector2, Vector3


def _mesh_with_geometry_payload() -> MeshData:
    return MeshData(
        name="RoundTripMesh",
        points=(Vector3(0.0, 0.0, 0.0), Vector3(1.0, 0.0, 0.0)),
        face_vertex_counts=(3, 3),
        face_vertex_indices=(0, 1, 0, 1, 0, 1),
        uv_coords=(Vector2(0.0, 0.0), Vector2(1.0, 0.0)),
        secondary_uv_coords=(Vector2(0.5, 0.5), Vector2(0.5, 0.5)),
        vertex_colors=(Color4(1.0, 0.0, 0.0, 1.0), Color4(0.0, 1.0, 0.0, 1.0)),
        sections=(MeshSection(material_id=1, face_indices=(0,)), MeshSection(material_id=2, face_indices=(1,))),
        skel_joint_indices=(0, 1),
        skel_joint_weights=(1.0, 0.5),
        skel_element_size=1,
    )


def test_geometry_buffer_round_trips_mesh_payload() -> None:
    mesh = _mesh_with_geometry_payload()

    buffer = geometry_buffer_from_mesh(mesh)
    round_tripped = geometry_buffer_to_mesh(buffer)

    assert round_tripped == mesh


def test_payload_helpers_prefer_geometry_buffer_over_mesh() -> None:
    mesh = _mesh_with_geometry_payload()
    buffer = geometry_buffer_from_mesh(mesh)

    assert payload_point_count(mesh, buffer) == 2
    assert payload_face_count(mesh, buffer) == 2
    assert payload_has_face_topology(mesh, buffer)
    assert payload_sections(mesh, buffer) == buffer.sections
    assert payload_material_distribution(mesh, buffer) == {"1": 1, "2": 1}

    replaced = replace_payload_sections(buffer, single_material_sections(material_id=7, face_count=2))
    assert isinstance(replaced, GeometryBuffer)
    assert replaced.sections[0].material_id == 7


def test_index_helpers_are_deterministic_and_gap_aware() -> None:
    assert list(chunked_indexes(length=5, chunk_size=2)) == [range(0, 2), range(2, 4), range(4, 5)]
    assert list(iter_face_ranges((3, 0, 2))) == [(0, 0, 3), (1, 3, 3), (2, 3, 5)]
