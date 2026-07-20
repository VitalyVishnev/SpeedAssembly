from __future__ import annotations

from array import array
from unittest.mock import Mock

import pytest

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


def test_parallel_partition_does_not_mask_programming_errors(monkeypatch) -> None:
    monkeypatch.setattr("xml_to_usda.payload_partition.cpu_worker_count", lambda _profile: 2)
    monkeypatch.setattr("xml_to_usda.payload_partition._MIN_PARALLEL_FACE_COUNT", 1)
    monkeypatch.setattr(
        "xml_to_usda.payload_partition._partition_fbx_material_faces_parallel",
        Mock(side_effect=ValueError("invalid partition state")),
    )

    with pytest.raises(ValueError, match="invalid partition state"):
        partition_fbx_material_faces(_payload(face_vertex_indices=[0, 1, 2]), cpu_profile=CpuProfile.BALANCED)


def test_parallel_partition_reports_infrastructure_fallback(monkeypatch) -> None:
    monkeypatch.setattr("xml_to_usda.payload_partition.cpu_worker_count", lambda _profile: 2)
    monkeypatch.setattr("xml_to_usda.payload_partition._MIN_PARALLEL_FACE_COUNT", 1)
    monkeypatch.setattr(
        "xml_to_usda.payload_partition._partition_fbx_material_faces_parallel",
        Mock(side_effect=OSError("shared memory unavailable")),
    )

    with pytest.warns(RuntimeWarning, match="retrying sequentially: shared memory unavailable"):
        sections = partition_fbx_material_faces(
            _payload(face_vertex_indices=[0, 1, 2]),
            cpu_profile=CpuProfile.BALANCED,
        )

    assert sections is not None
