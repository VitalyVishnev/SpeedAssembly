from __future__ import annotations

from array import array

from xml_to_usda.models import CompactMeshSection, Color4, GeometryBuffer, MeshData, MeshSection, Vector2, Vector3
from xml_to_usda.prototype_simplification import (
    predicted_simplified_triangle_count,
    simplify_geometry_buffer,
    simplify_mesh_data,
)


def _two_section_buffer() -> GeometryBuffer:
    return GeometryBuffer(
        name="Branch",
        point_components=array(
            "f",
            [
                0.0, 0.0, 0.0,
                1.0, 0.0, 0.0,
                0.0, 1.0, 0.0,
                1.0, 1.0, 0.0,
                2.0, 0.0, 0.0,
                3.0, 0.0, 0.0,
                2.0, 1.0, 0.0,
                3.0, 1.0, 0.0,
            ],
        ),
        face_vertex_counts=array("i", [3, 3, 3, 3]),
        face_vertex_indices=array("i", [0, 1, 2, 1, 3, 2, 4, 5, 6, 5, 7, 6]),
        uv_components=array(
            "f",
            [
                0.0, 0.0, 1.0, 0.0, 0.0, 1.0,
                1.0, 0.0, 1.0, 1.0, 0.0, 1.0,
                0.0, 0.0, 1.0, 0.0, 0.0, 1.0,
                1.0, 0.0, 1.0, 1.0, 0.0, 1.0,
            ],
        ),
        secondary_uv_components=array(
            "f",
            [
                0.1, 0.1, 1.1, 0.1, 0.1, 1.1,
                1.1, 0.1, 1.1, 1.1, 0.1, 1.1,
                0.2, 0.2, 1.2, 0.2, 0.2, 1.2,
                1.2, 0.2, 1.2, 1.2, 0.2, 1.2,
            ],
        ),
        vertex_color_components=array(
            "f",
            [
                1.0, 0.0, 0.0, 1.0,
                0.0, 1.0, 0.0, 1.0,
                0.0, 0.0, 1.0, 1.0,
                1.0, 1.0, 1.0, 1.0,
                1.0, 0.0, 0.0, 1.0,
                0.0, 1.0, 0.0, 1.0,
                0.0, 0.0, 1.0, 1.0,
                1.0, 1.0, 1.0, 1.0,
            ],
        ),
        sections=(
            CompactMeshSection(material_id=11, face_indices=array("i", [0, 1])),
            CompactMeshSection(material_id=22, face_indices=array("i", [2, 3])),
        ),
    )


def test_prototype_simplification_100_percent_is_exact_noop() -> None:
    mesh = _two_section_buffer()

    assert simplify_geometry_buffer(mesh, 100) is mesh
    assert predicted_simplified_triangle_count(mesh, 100) == 4


def test_prototype_simplification_zero_keeps_one_triangle_per_material_section() -> None:
    simplified = simplify_geometry_buffer(_two_section_buffer(), 0)

    assert simplified.face_count == 2
    assert [section.material_id for section in simplified.sections] == [11, 22]
    assert [len(section.face_indices) for section in simplified.sections] == [1, 1]
    assert len(simplified.uv_components) == len(simplified.face_vertex_indices) * 2
    assert len(simplified.secondary_uv_components) == len(simplified.face_vertex_indices) * 2
    assert simplified.vertex_color_count == simplified.point_count
    assert predicted_simplified_triangle_count(_two_section_buffer(), 0) == 2


def test_prototype_simplification_preserves_meshdata_material_boundaries() -> None:
    mesh = MeshData(
        name="Twig",
        points=(
            Vector3(0.0, 0.0, 0.0),
            Vector3(1.0, 0.0, 0.0),
            Vector3(0.0, 1.0, 0.0),
            Vector3(1.0, 1.0, 0.0),
        ),
        face_vertex_counts=(3, 3),
        face_vertex_indices=(0, 1, 2, 1, 3, 2),
        uv_coords=(
            Vector2(0.0, 0.0),
            Vector2(1.0, 0.0),
            Vector2(0.0, 1.0),
            Vector2(1.0, 0.0),
            Vector2(1.0, 1.0),
            Vector2(0.0, 1.0),
        ),
        vertex_colors=(
            Color4(1.0, 1.0, 1.0, 1.0),
            Color4(1.0, 1.0, 1.0, 1.0),
            Color4(1.0, 1.0, 1.0, 1.0),
            Color4(1.0, 1.0, 1.0, 1.0),
        ),
        sections=(
            MeshSection(material_id=5, face_indices=(0,)),
            MeshSection(material_id=6, face_indices=(1,)),
        ),
    )

    simplified = simplify_mesh_data(mesh, 0)

    assert len(simplified.face_vertex_counts) == 2
    assert [section.material_id for section in simplified.sections] == [5, 6]
    assert len(simplified.uv_coords) == len(simplified.face_vertex_indices)
    assert len(simplified.vertex_colors) == len(simplified.points)
