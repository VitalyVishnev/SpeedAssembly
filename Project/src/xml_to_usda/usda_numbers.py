"""USDA numerical arrays, with interchangeable Python and native formatting.

Scene semantics and file publication belong to authoring/writer. Native calls
borrow packed buffers and return at most 4096 formatted values per chunk.
"""
from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import dataclass
import importlib
from itertools import islice
import sys

from .models import GeometryBuffer, MeshData

_FORMAT_CACHE_MIN_VALUES = 1024
_FORMAT_CACHE_SAMPLE_VALUES = 2048
_FORMAT_CACHE_MAX_UNIQUE_RATIO = 0.75
_NATIVE_CHUNK_VALUES = 4096


def _native_module():
    try:
        native = importlib.import_module("xml_to_usda._usda_numbers")
    except ModuleNotFoundError as error:
        if error.name != "xml_to_usda._usda_numbers":
            raise
        if getattr(sys, "frozen", False):
            raise RuntimeError("Packaged USDA numerical formatter is missing.") from error
        return None
    if getattr(native, "API_VERSION", None) != 1:
        raise RuntimeError("Unsupported USDA numerical formatter API; rebuild the native extensions.")
    return native


@dataclass(frozen=True)
class _NativeValues:
    chunks: Callable[[int], Generator[str, None, None]]


def _vectors(native, coords, width, cache_identity):
    return _NativeValues(lambda size: (
        native.format_vectors(coords[start:start + size], width, cache_identity)
        for start in range(0, len(coords), size)
    ))


def _components(native, values, width, cache_uvs=False):
    def chunks(size):
        # Acquire the lease during consumption, so a discarded array never pins a buffer.
        formatter = native.float_buffer_formatter(values, width, cache_uvs)
        for start in range(0, len(values), size * width):
            yield formatter.chunk(start, min(len(values), start + size * width))
    return _NativeValues(chunks)


def point_values(mesh: MeshData | GeometryBuffer):
    native = _native_module()
    if native is not None:
        if not isinstance(mesh, GeometryBuffer):
            return _vectors(native, mesh.points, 3, False)
        if mesh.point_components.typecode == "f":
            return _components(native, mesh.point_components, 3)
    return _python_point_values(mesh)


def normal_values(mesh: MeshData | GeometryBuffer):
    native = _native_module()
    if native is not None:
        if not isinstance(mesh, GeometryBuffer):
            return _vectors(native, mesh.normals, 3, _vector_coords_reuse_objects(mesh.normals))
        if mesh.normal_components.typecode == "f":
            return _components(native, mesh.normal_components, 3)
    return _python_normal_values(mesh)


def uv_values(mesh: MeshData | GeometryBuffer, *, uv_set="primary"):
    native = _native_module()
    if native is not None:
        if not isinstance(mesh, GeometryBuffer):
            coords = mesh.secondary_uv_coords if uv_set == "secondary" else mesh.uv_coords
            return _vectors(native, coords, 2, _uv_coords_should_cache_format(coords))
        values = mesh.secondary_uv_components if uv_set == "secondary" else mesh.uv_components
        if values.typecode == "f":
            return _components(native, values, 2, _uv_components_should_cache_format(values))
    return _python_uv_values(mesh, uv_set=uv_set)


def integer_values(values):
    native = _native_module()
    if native is None:
        return _python_integer_values(values)
    if getattr(values, "typecode", None) == "i" and values.itemsize == 4:
        return _NativeValues(lambda size: (
            native.format_int_buffer(values, start, min(len(values), start + size))
            for start in range(0, len(values), size)
        ))
    return _NativeValues(lambda size: (
        native.format_ints(tuple(values[start:start + size]))
        for start in range(0, len(values), size)
    ))


def write_values(sink, values, *, chunk_size=4096):
    if chunk_size <= 0:
        raise ValueError("USDA chunk size must be positive.")
    if isinstance(values, _NativeValues):
        chunks = values.chunks(min(chunk_size, _NATIVE_CHUNK_VALUES))
    else:
        def formatted_chunks():
            iterator = iter(values)
            while pending := list(islice(iterator, chunk_size)):
                yield ", ".join(pending)
        chunks = formatted_chunks()
    try:
        first = True
        for text in chunks:
            if not first:
                sink.write(", ")
            sink.write(text)
            first = False
    finally:
        # In particular release a native PyBuffer on cancellation or an I/O error.
        chunks.close()


def _python_point_values(mesh: MeshData | GeometryBuffer):
    if isinstance(mesh, GeometryBuffer):
        for index in range(0, len(mesh.point_components), 3):
            yield "(%g, %g, %g)" % (
                mesh.point_components[index],
                mesh.point_components[index + 1],
                mesh.point_components[index + 2],
            )
        return
    for point in mesh.points:
        yield "(%g, %g, %g)" % (point.x, point.y, point.z)


def _python_normal_values(mesh: MeshData | GeometryBuffer):
    if isinstance(mesh, GeometryBuffer):
        return (
            "(%g, %g, %g)"
            % (
                mesh.normal_components[index],
                mesh.normal_components[index + 1],
                mesh.normal_components[index + 2],
            )
            for index in range(0, len(mesh.normal_components), 3)
        )
    if _vector_coords_reuse_objects(mesh.normals):
        cache: dict[int, str] = {}
        values: list[str] = []
        append = values.append
        for normal in mesh.normals:
            key = id(normal)
            value = cache.get(key)
            if value is None:
                value = "(%g, %g, %g)" % (normal.x, normal.y, normal.z)
                cache[key] = value
            append(value)
        return values
    return ("(%g, %g, %g)" % (normal.x, normal.y, normal.z) for normal in mesh.normals)


def _python_integer_values(values):
    count = len(values)
    if count >= _FORMAT_CACHE_MIN_VALUES:
        sample_count = min(count, _FORMAT_CACHE_SAMPLE_VALUES)
        if len(set(values[:sample_count])) / sample_count <= _FORMAT_CACHE_MAX_UNIQUE_RATIO:
            cache = {value: str(value) for value in set(values)}
            return map(cache.__getitem__, values)
    return map(str, values)


def _python_uv_values(mesh: MeshData | GeometryBuffer, *, uv_set: str = "primary"):
    if isinstance(mesh, GeometryBuffer):
        uv_components = mesh.secondary_uv_components if uv_set == "secondary" else mesh.uv_components
        if _uv_components_should_cache_format(uv_components):
            return _iter_cached_uv_component_strings(uv_components)
        return _iter_uv_component_strings(uv_components)
    uv_coords = mesh.secondary_uv_coords if uv_set == "secondary" else mesh.uv_coords
    if _uv_coords_should_cache_format(uv_coords):
        return _iter_cached_uv_coord_strings(uv_coords)
    return _iter_uv_coord_strings(uv_coords)


def _iter_uv_component_strings(uv_components):
    for index in range(0, len(uv_components), 2):
        yield "(%g, %g)" % (uv_components[index], uv_components[index + 1])


def _iter_cached_uv_component_strings(uv_components):
    cache: dict[tuple[float, float], str] = {}
    for index in range(0, len(uv_components), 2):
        key = (uv_components[index], uv_components[index + 1])
        value = cache.get(key)
        if value is None:
            value = "(%g, %g)" % key
            cache[key] = value
        yield value


def _iter_uv_coord_strings(uv_coords):
    for uv in uv_coords:
        yield "(%g, %g)" % (uv.x, uv.y)


def _iter_cached_uv_coord_strings(uv_coords):
    cache: dict[int, str] = {}
    values: list[str] = []
    append = values.append
    for uv in uv_coords:
        key = id(uv)
        value = cache.get(key)
        if value is None:
            value = "(%g, %g)" % (uv.x, uv.y)
            cache[key] = value
        append(value)
    return values


def _uv_components_should_cache_format(uv_components) -> bool:
    pair_count = len(uv_components) // 2
    if pair_count < _FORMAT_CACHE_MIN_VALUES:
        return False
    sample_pair_count = min(pair_count, _FORMAT_CACHE_SAMPLE_VALUES)
    sample_end = sample_pair_count * 2
    unique_pairs = {
        (uv_components[index], uv_components[index + 1])
        for index in range(0, sample_end, 2)
    }
    return len(unique_pairs) / sample_pair_count <= _FORMAT_CACHE_MAX_UNIQUE_RATIO


def _uv_coords_should_cache_format(uv_coords) -> bool:
    return _vector_coords_reuse_objects(uv_coords)


def _vector_coords_reuse_objects(coords) -> bool:
    value_count = len(coords)
    if value_count < _FORMAT_CACHE_MIN_VALUES:
        return False
    sample_value_count = min(value_count, _FORMAT_CACHE_SAMPLE_VALUES)
    unique_objects = {id(coords[index]) for index in range(sample_value_count)}
    return len(unique_objects) / sample_value_count <= _FORMAT_CACHE_MAX_UNIQUE_RATIO
