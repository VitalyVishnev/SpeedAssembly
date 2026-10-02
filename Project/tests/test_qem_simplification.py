from collections import Counter

from xml_to_usda.models import GeometryBuffer
from xml_to_usda.qem_simplification import simplify_geometry_buffer_qem


def _closed_cube() -> GeometryBuffer:
    return GeometryBuffer(
        name="ClosedCube",
        point_components=[
            -1.0, -1.0, -1.0,
            1.0, -1.0, -1.0,
            1.0, 1.0, -1.0,
            -1.0, 1.0, -1.0,
            -1.0, -1.0, 1.0,
            1.0, -1.0, 1.0,
            1.0, 1.0, 1.0,
            -1.0, 1.0, 1.0,
        ],
        face_vertex_counts=[3] * 12,
        face_vertex_indices=[
            0, 2, 1, 0, 3, 2,
            4, 5, 6, 4, 6, 7,
            0, 1, 5, 0, 5, 4,
            1, 2, 6, 1, 6, 5,
            2, 3, 7, 2, 7, 6,
            3, 0, 4, 3, 4, 7,
        ],
    )


def test_qem_simplification_keeps_a_closed_surface_closed() -> None:
    simplified = simplify_geometry_buffer_qem(_closed_cube(), target_triangle_count=6)

    edges = Counter()
    indices = list(simplified.face_vertex_indices)
    for offset in range(0, len(indices), 3):
        triangle = indices[offset : offset + 3]
        for start, end in zip(triangle, triangle[1:] + triangle[:1], strict=True):
            edges[tuple(sorted((start, end)))] += 1

    assert simplified.face_count <= 6
    assert simplified.face_count >= 4
    assert set(edges.values()) == {2}
