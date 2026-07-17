from __future__ import annotations

import pytest

from xml_to_usda.models import MeshData, Vector3


def test_mesh_data_materializes_iterables_and_rejects_non_iterable_fields() -> None:
    mesh = MeshData(
        name="Base",
        points=(point for point in (Vector3(0.0, 0.0, 0.0), Vector3(1.0, 0.0, 0.0), Vector3(0.0, 1.0, 0.0))),
        face_vertex_counts=(count for count in (3,)),
        face_vertex_indices=(index for index in (0, 1, 2)),
    )

    assert mesh.points == (Vector3(0.0, 0.0, 0.0), Vector3(1.0, 0.0, 0.0), Vector3(0.0, 1.0, 0.0))
    assert mesh.face_vertex_counts == (3,)
    with pytest.raises(TypeError, match="MeshData.face_vertex_counts must be tuple-compatible"):
        MeshData(
            name="Invalid",
            points=(Vector3(0.0, 0.0, 0.0),),
            face_vertex_counts=lambda: (3,),  # type: ignore[arg-type]
            face_vertex_indices=(0, 1, 2),
        )
