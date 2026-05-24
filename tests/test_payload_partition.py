from __future__ import annotations

from array import array

from xml_to_usda.models import CpuProfile, GeometryBuffer
from xml_to_usda.payload_partition import partition_fbx_material_faces


def _payload(*, face_vertex_indices: list[int]) -> GeometryBuffer:
    return GeometryBuffer(
        name="FBXPayload",
        point_components=array("f", [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0]),
        face_vertex_counts=array("i", [3]),
        face_vertex_indices=array("i", face_vertex_indices),
        vertex_color_components=array(
            "f",
            [
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
            ],
        ),
    )


def test_fbx_material_partition_rejects_negative_point_indices() -> None:
    sections = partition_fbx_material_faces(
        _payload(face_vertex_indices=[0, -1, 2]),
        cpu_profile=CpuProfile.BALANCED,
    )

    assert sections is None
