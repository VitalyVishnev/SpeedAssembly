from __future__ import annotations

import gc
import os
from array import array
from time import perf_counter

import pytest

pytestmark = pytest.mark.stress

from xml_to_usda.models import (
    CompactMeshSection,
    GeometryBuffer,
    MeshData,
    MeshSection,
    UdimMaterialSetting,
    UdimMode,
    Vector2,
    Vector3,
)
from xml_to_usda.udim_resolver import apply_udim_settings_to_geometry_buffer, apply_udim_settings_to_mesh_data


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


def _build_mesh_payload(face_count: int) -> MeshData:
    return _build_mesh_data(face_count)


def _build_geometry_payload(face_count: int, *, existing_secondary: bool = False) -> GeometryBuffer:
    geometry_payload = _build_geometry_buffer(face_count)
    if existing_secondary:
        geometry_payload = GeometryBuffer(
            name=geometry_payload.name,
            point_components=geometry_payload.point_components,
            face_vertex_counts=geometry_payload.face_vertex_counts,
            face_vertex_indices=geometry_payload.face_vertex_indices,
            uv_components=geometry_payload.uv_components,
            secondary_uv_components=array("f", (9.0, 9.0, 8.0, 8.0, 7.0, 7.0)) * face_count,
            sections=geometry_payload.sections,
        )
    return geometry_payload


def _time_average_seconds(work, *, iterations: int = 5) -> float:
    gc_was_enabled = gc.isenabled()
    if gc_was_enabled:
        gc.disable()
    try:
        for _ in range(2):
            work()
        started_at = perf_counter()
        for _ in range(iterations):
            work()
        return (perf_counter() - started_at) / iterations
    finally:
        if gc_was_enabled:
            gc.enable()


@pytest.mark.skipif(os.getenv("XMLTOUSDA_RUN_PERF") != "1", reason="optional perf benchmark")
@pytest.mark.parametrize(
    ("payload_kind", "model_factory"),
    (
        ("mesh", _build_mesh_payload),
        ("geometry", _build_geometry_payload),
    ),
)
def test_udim_secondary_uv_authoring_stays_close_to_primary_shift_for_hot_payloads(
    payload_kind: str,
    model_factory,
) -> None:
    face_count = 24000
    payload = model_factory(face_count)
    shift_setting = (UdimMaterialSetting(material_id=1, mode=UdimMode.SHIFT_PRIMARY_UV, udim_id=1003),)
    secondary_setting = (
        UdimMaterialSetting(material_id=1, mode=UdimMode.WRITE_SECONDARY_UV_OFFSET, udim_id=1003),
    )

    if payload_kind == "mesh":
        apply = apply_udim_settings_to_mesh_data
        label = "HotMesh"
    else:
        apply = apply_udim_settings_to_geometry_buffer
        label = "HotGeometry"

    shift_seconds = _time_average_seconds(lambda: apply(payload, shift_setting, label=label))
    secondary_seconds = _time_average_seconds(lambda: apply(payload, secondary_setting, label=label))

    assert secondary_seconds <= shift_seconds * 1.5
    assert secondary_seconds < 0.05

    resolved = apply(payload, secondary_setting, label=label)
    if payload_kind == "mesh":
        assert resolved is not None
        assert resolved.secondary_uv_coords
        assert resolved.secondary_uv_coords[0] == Vector2(2.5, 0.5)
    else:
        assert resolved is not None
        assert resolved.secondary_uv_components
        assert resolved.secondary_uv_components[:2] == array("f", (2.5, 0.5))
