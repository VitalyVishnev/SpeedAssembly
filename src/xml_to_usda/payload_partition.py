from __future__ import annotations

from array import array
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from multiprocessing import shared_memory

from .job_control import apply_process_profile, cpu_worker_count, throw_if_cancelled
from .models import CompactMeshSection, CpuProfile, GeometryBuffer


_MIN_PARALLEL_FACE_COUNT = 50_000
_MAX_PARALLEL_SHARED_BYTES = 384 * 1024 * 1024


@dataclass(frozen=True)
class _FaceChunk:
    start_face: int
    end_face: int
    start_offset: int


def partition_fbx_material_faces(
    payload: GeometryBuffer,
    *,
    cpu_profile: CpuProfile,
    cancel_event=None,
) -> tuple[CompactMeshSection, ...] | None:
    if payload.vertex_color_count == 0 or payload.face_count == 0 or not payload.face_vertex_indices:
        return None

    worker_count = cpu_worker_count(cpu_profile)
    shared_bytes = (
        len(payload.face_vertex_counts) * payload.face_vertex_counts.itemsize
        + len(payload.face_vertex_indices) * payload.face_vertex_indices.itemsize
        + len(payload.vertex_color_components) * payload.vertex_color_components.itemsize
    )
    if (
        worker_count <= 1
        or payload.face_count < _MIN_PARALLEL_FACE_COUNT
        or shared_bytes > _MAX_PARALLEL_SHARED_BYTES
    ):
        return _partition_fbx_material_faces_sequential(payload)

    try:
        return _partition_fbx_material_faces_parallel(
            payload,
            worker_count=worker_count,
            cpu_profile=cpu_profile,
            cancel_event=cancel_event,
        )
    except Exception:
        # Stability wins over speed for huge jobs.
        return _partition_fbx_material_faces_sequential(payload)


def _partition_fbx_material_faces_sequential(payload: GeometryBuffer) -> tuple[CompactMeshSection, ...] | None:
    bark_faces = array("i")
    leaves_faces = array("i")
    offset = 0
    for face_index, face_count in enumerate(payload.face_vertex_counts):
        face_indices = payload.face_vertex_indices[offset:offset + face_count]
        offset += face_count
        if len(face_indices) != face_count:
            return None
        material_id = 2
        for point_index in face_indices:
            color_offset = point_index * 4
            if color_offset + 2 >= len(payload.vertex_color_components):
                return None
            if not (
                payload.vertex_color_components[color_offset] == 0.0
                and payload.vertex_color_components[color_offset + 1] == 0.0
                and payload.vertex_color_components[color_offset + 2] == 0.0
            ):
                material_id = 1
                break
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


def _partition_fbx_material_faces_parallel(
    payload: GeometryBuffer,
    *,
    worker_count: int,
    cpu_profile: CpuProfile,
    cancel_event=None,
) -> tuple[CompactMeshSection, ...] | None:
    chunks = _build_face_chunks(payload.face_vertex_counts, worker_count)
    if len(chunks) <= 1:
        return _partition_fbx_material_faces_sequential(payload)

    counts_memory = shared_memory.SharedMemory(create=True, size=len(payload.face_vertex_counts) * payload.face_vertex_counts.itemsize)
    indices_memory = shared_memory.SharedMemory(create=True, size=len(payload.face_vertex_indices) * payload.face_vertex_indices.itemsize)
    colors_memory = shared_memory.SharedMemory(create=True, size=len(payload.vertex_color_components) * payload.vertex_color_components.itemsize)
    try:
        counts_memory.buf[: len(payload.face_vertex_counts) * payload.face_vertex_counts.itemsize] = payload.face_vertex_counts.tobytes()
        indices_memory.buf[: len(payload.face_vertex_indices) * payload.face_vertex_indices.itemsize] = payload.face_vertex_indices.tobytes()
        colors_memory.buf[: len(payload.vertex_color_components) * payload.vertex_color_components.itemsize] = payload.vertex_color_components.tobytes()

        bark_faces = array("i")
        leaves_faces = array("i")
        with ProcessPoolExecutor(max_workers=min(worker_count, len(chunks))) as executor:
            futures = [
                executor.submit(
                    _partition_face_chunk_worker,
                    counts_memory.name,
                    len(payload.face_vertex_counts),
                    indices_memory.name,
                    len(payload.face_vertex_indices),
                    colors_memory.name,
                    len(payload.vertex_color_components),
                    chunk.start_face,
                    chunk.end_face,
                    chunk.start_offset,
                    cpu_profile.value,
                )
                for chunk in chunks
            ]
            for future in futures:
                throw_if_cancelled(cancel_event)
                bark_chunk, leaves_chunk = future.result()
                bark_faces.extend(bark_chunk)
                leaves_faces.extend(leaves_chunk)
    finally:
        counts_memory.close()
        counts_memory.unlink()
        indices_memory.close()
        indices_memory.unlink()
        colors_memory.close()
        colors_memory.unlink()

    sections: list[CompactMeshSection] = []
    if bark_faces:
        sections.append(CompactMeshSection(material_id=1, face_indices=bark_faces))
    if leaves_faces:
        sections.append(CompactMeshSection(material_id=2, face_indices=leaves_faces))
    return tuple(sections)


def _partition_face_chunk_worker(
    counts_name: str,
    counts_length: int,
    indices_name: str,
    indices_length: int,
    colors_name: str,
    colors_length: int,
    start_face: int,
    end_face: int,
    start_offset: int,
    cpu_profile_value: str,
) -> tuple[array, array]:
    apply_process_profile(CpuProfile(cpu_profile_value))
    counts_memory = shared_memory.SharedMemory(name=counts_name)
    indices_memory = shared_memory.SharedMemory(name=indices_name)
    colors_memory = shared_memory.SharedMemory(name=colors_name)
    try:
        counts = counts_memory.buf.cast("i")[:counts_length]
        indices = indices_memory.buf.cast("i")[:indices_length]
        colors = colors_memory.buf.cast("f")[:colors_length]
        bark_faces = array("i")
        leaves_faces = array("i")
        offset = start_offset
        for face_index in range(start_face, end_face):
            face_count = counts[face_index]
            material_id = 2
            end_offset = offset + face_count
            if end_offset > indices_length:
                raise ValueError("Face topology exceeds available faceVertexIndices data.")
            for face_offset in range(offset, end_offset):
                point_index = indices[face_offset]
                color_offset = point_index * 4
                if color_offset + 2 >= colors_length:
                    raise ValueError("Vertex color payload is shorter than the indexed point range.")
                if not (
                    colors[color_offset] == 0.0
                    and colors[color_offset + 1] == 0.0
                    and colors[color_offset + 2] == 0.0
                ):
                    material_id = 1
                    break
            if material_id == 1:
                bark_faces.append(face_index)
            else:
                leaves_faces.append(face_index)
            offset = end_offset
        return bark_faces, leaves_faces
    finally:
        counts_memory.close()
        indices_memory.close()
        colors_memory.close()


def _build_face_chunks(face_vertex_counts: array, worker_count: int) -> tuple[_FaceChunk, ...]:
    total_faces = len(face_vertex_counts)
    if total_faces <= 0:
        return ()
    target_chunk_size = max(1, total_faces // max(1, worker_count))
    chunks: list[_FaceChunk] = []
    start_face = 0
    start_offset = 0
    accumulated = 0
    running_offset = 0
    for face_index, face_count in enumerate(face_vertex_counts, start=1):
        accumulated += 1
        running_offset += face_count
        if accumulated < target_chunk_size and face_index < total_faces:
            continue
        chunks.append(_FaceChunk(start_face=start_face, end_face=face_index, start_offset=start_offset))
        start_offset = running_offset
        start_face = face_index
        accumulated = 0
    if start_face < total_faces:
        chunks.append(_FaceChunk(start_face=start_face, end_face=total_faces, start_offset=start_offset))
    return tuple(chunks)
