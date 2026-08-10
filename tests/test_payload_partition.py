from __future__ import annotations

from array import array
from dataclasses import replace
from threading import Event

import pytest

from xml_to_usda.job_control import ConversionCancelledError
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


def test_numpy_partition_preserves_mixed_face_buckets_across_chunks(monkeypatch) -> None:
    payload = replace(
        _payload(face_vertex_indices=[0, 1, 2]),
        point_components=array("f", [0.0] * 18),
        face_vertex_counts=array("i", [3, 3]),
        face_vertex_indices=array("i", [0, 1, 2, 3, 4, 5]),
        vertex_color_components=array(
            "f",
            [0.0, 0.0, 0.0, 1.0] * 3 + [1.0, 1.0, 1.0, 1.0] * 3,
        ),
    )
    monkeypatch.setattr("xml_to_usda.payload_partition._MIN_NUMPY_FACE_COUNT", 1)
    monkeypatch.setattr("xml_to_usda.payload_partition._NUMPY_FACE_CHUNK_SIZE", 1)

    sections = partition_fbx_material_faces(payload, cpu_profile=CpuProfile.BALANCED)

    assert sections is not None
    assert tuple(section.material_id for section in sections) == (1, 2)
    assert tuple(sections[0].face_indices) == (1,)
    assert tuple(sections[1].face_indices) == (0,)


def test_numpy_partition_honors_cancellation(monkeypatch) -> None:
    monkeypatch.setattr("xml_to_usda.payload_partition._MIN_NUMPY_FACE_COUNT", 1)
    cancel_event = Event()
    cancel_event.set()

    with pytest.raises(ConversionCancelledError):
        partition_fbx_material_faces(
            _payload(face_vertex_indices=[0, 1, 2]),
            cpu_profile=CpuProfile.BALANCED,
            cancel_event=cancel_event,
        )
