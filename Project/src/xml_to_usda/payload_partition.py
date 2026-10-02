from __future__ import annotations

from array import array

from .job_control import throw_if_cancelled
from .models import CompactMeshSection, CpuProfile, GeometryBuffer


_MIN_NUMPY_FACE_COUNT = 50_000
_NUMPY_FACE_CHUNK_SIZE = 262_144


def partition_fbx_material_faces(
    payload: GeometryBuffer,
    *,
    cpu_profile: CpuProfile,
    cancel_event=None,
) -> tuple[CompactMeshSection, ...] | None:
    if payload.vertex_color_count == 0 or payload.face_count == 0 or not payload.face_vertex_indices:
        return None
    if payload.face_count < _MIN_NUMPY_FACE_COUNT:
        return _partition_fbx_material_faces_sequential(payload)
    return _partition_fbx_material_faces_numpy(payload, cancel_event=cancel_event)


def _partition_fbx_material_faces_sequential(payload: GeometryBuffer) -> tuple[CompactMeshSection, ...] | None:
    bark_faces = array("i")
    leaves_faces = array("i")
    offset = 0
    index_count = len(payload.face_vertex_indices)
    color_count = len(payload.vertex_color_components)
    for face_index, face_count in enumerate(payload.face_vertex_counts):
        end_offset = offset + face_count
        if end_offset > index_count:
            return None
        material_id = 2
        for face_offset in range(offset, end_offset):
            point_index = payload.face_vertex_indices[face_offset]
            color_offset = point_index * 4
            if point_index < 0 or color_offset + 2 >= color_count:
                return None
            if not (
                payload.vertex_color_components[color_offset] == 0.0
                and payload.vertex_color_components[color_offset + 1] == 0.0
                and payload.vertex_color_components[color_offset + 2] == 0.0
            ):
                material_id = 1
                break
        offset = end_offset
        if material_id == 1:
            bark_faces.append(face_index)
        else:
            leaves_faces.append(face_index)
    sections: list[CompactMeshSection] = []
    if bark_faces:
        sections.append(CompactMeshSection(material_id=1, face_indices=bark_faces))
    if leaves_faces:
        sections.append(CompactMeshSection(material_id=2, face_indices=leaves_faces))
    return tuple(sections)


def _partition_fbx_material_faces_numpy(
    payload: GeometryBuffer,
    *,
    cancel_event=None,
) -> tuple[CompactMeshSection, ...] | None:
    import numpy as np

    throw_if_cancelled(cancel_event)
    face_counts = np.frombuffer(payload.face_vertex_counts, dtype=np.int32)
    face_indices = np.frombuffer(payload.face_vertex_indices, dtype=np.int32)
    color_count = payload.vertex_color_count
    colors = np.frombuffer(
        payload.vertex_color_components,
        dtype=np.float32,
        count=color_count * 4,
    ).reshape((color_count, 4))
    bark_faces = array("i")
    leaves_faces = array("i")
    corner_offset = 0

    for face_start in range(0, len(face_counts), _NUMPY_FACE_CHUNK_SIZE):
        throw_if_cancelled(cancel_event)
        face_end = min(len(face_counts), face_start + _NUMPY_FACE_CHUNK_SIZE)
        chunk_counts = face_counts[face_start:face_end]
        if np.any(chunk_counts <= 0):
            return None
        chunk_corner_count = int(np.sum(chunk_counts, dtype=np.int64))
        end_corner_offset = corner_offset + chunk_corner_count
        if end_corner_offset > len(face_indices):
            return None
        chunk_indices = face_indices[corner_offset:end_corner_offset]
        if np.any(chunk_indices < 0) or np.any(chunk_indices >= color_count):
            return None

        face_offsets = np.empty(len(chunk_counts), dtype=np.int64)
        face_offsets[0] = 0
        np.cumsum(chunk_counts[:-1], dtype=np.int64, out=face_offsets[1:])
        black_corners = np.all(colors[chunk_indices, :3] == 0.0, axis=1)
        leaf_mask = np.logical_and.reduceat(black_corners, face_offsets)
        bark_chunk = (np.flatnonzero(~leaf_mask) + face_start).astype(np.int32, copy=False)
        leaves_chunk = (np.flatnonzero(leaf_mask) + face_start).astype(np.int32, copy=False)
        bark_faces.frombytes(bark_chunk.tobytes())
        leaves_faces.frombytes(leaves_chunk.tobytes())
        corner_offset = end_corner_offset

    sections: list[CompactMeshSection] = []
    if bark_faces:
        sections.append(CompactMeshSection(material_id=1, face_indices=bark_faces))
    if leaves_faces:
        sections.append(CompactMeshSection(material_id=2, face_indices=leaves_faces))
    throw_if_cancelled(cancel_event)
    return tuple(sections)
