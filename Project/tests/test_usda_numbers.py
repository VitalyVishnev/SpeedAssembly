"""Native formatting must preserve Python USDA text and buffer lifetimes."""
from array import array
from dataclasses import replace
import importlib
import io
import random
import struct
import sys
from unittest.mock import patch

import numpy as np
import pytest

from xml_to_usda import usda_numbers as numbers
from xml_to_usda.models import GeometryBuffer, MeshData, Vector2, Vector3


def _text(values):
    sink = io.StringIO()
    numbers.write_values(sink, values)
    return sink.getvalue()


def test_native_arrays_preserve_python_rounding_caches_and_precision():
    pytest.importorskip("xml_to_usda._usda_numbers")
    rng = random.Random(147)
    floats = [0.0, -0.0, 1.234565, 1.234575, 1e-308, 1e308, float("inf"), -float("inf"), float("nan")]
    floats += [struct.unpack("d", rng.randbytes(8))[0] for _ in range(12000)]
    vectors = tuple(Vector3(v, -v, v) for v in floats)
    shared = Vector3(0, -0.0, 1)
    coords = (Vector2(0, -0.0), Vector2(1, 0)) * 3000
    meshes = [MeshData("exact", vectors, (3,) * 5000, (0, 1, 2) * 5000,
                       normals=(shared,) * 6000, uv_coords=coords, secondary_uv_coords=coords[::-1])]
    uv = array("f", [-0.0, 0.0] * 4100 + [0.0, -0.0, -0.0, float("nan"), 0.0, float("nan")])
    meshes.append(GeometryBuffer("packed", array("f", [1.234565, -0.0, 1e-38] * 6000),
                                array("i", [3] * 6000), array("i", [-2147483648, 0, 2147483647] * 6000),
                                normal_components=array("f", [0, 0, 1] * 6000), uv_components=uv,
                                secondary_uv_components=array("f", uv[::-1])))
    meshes.append(replace(meshes[-1], point_components=array("d", [1e308, -1e-308, -0.0]),
                          uv_components=array("d", [-0.0, 0.0] * 4100 + [0.0, -0.0])))
    for mesh in meshes:
        for factory in (numbers.point_values, numbers.normal_values, numbers.uv_values,
                        lambda mesh: numbers.uv_values(mesh, uv_set="secondary"),
                        lambda mesh: numbers.integer_values(mesh.face_vertex_indices),
                        lambda mesh: numbers.integer_values(mesh.face_vertex_counts)):
            with patch.object(numbers, "_native_module", return_value=None):
                expected = _text(factory(mesh))
            assert _text(factory(mesh)) == expected
    huge = (-(2**150), 2**180, -1, 0, 2**63) * 1000
    assert _text(numbers.integer_values(huge)) == ", ".join(map(str, huge))


def test_native_buffer_shape_is_validated_and_borrows_are_released():
    native = pytest.importorskip("xml_to_usda._usda_numbers")
    values = array("f", [0, 1, 2] * 5000)
    with pytest.raises(ValueError, match="aligned"):
        native.float_buffer_formatter(array("f", [1, 2]), 3, False)
    for malformed in (np.zeros((2, 3), dtype="f"), np.zeros(6, dtype="f")[::2]):
        with pytest.raises(ValueError):
            native.float_buffer_formatter(malformed, 3, False)
    with pytest.raises(BufferError):
        native.float_buffer_formatter(array("d", [1, 2, 3]), 3, False)
    formatter = native.float_buffer_formatter(values, 3, False)
    for bounds in ((1, 4), (0, len(values) + 3), (3, 0), (0, 4097 * 3)):
        with pytest.raises(ValueError, match="shape"):
            formatter.chunk(*bounds)
    del formatter
    values.append(4)
    with pytest.raises(ValueError):
        native.format_int_buffer(np.zeros((2, 3), dtype="i"), 0, 3)


def test_sink_failure_releases_native_buffer_even_with_retained_exception():
    pytest.importorskip("xml_to_usda._usda_numbers")
    mesh = GeometryBuffer("failure", array("f", [0, 1, 2] * 5000), array("i"), array("i"))
    class FailingSink:
        def write(self, text):
            raise OSError("disk full")
    with pytest.raises(OSError, match="disk full") as error:
        numbers.write_values(FailingSink(), numbers.point_values(mesh))
    assert error.value.__traceback__ is not None
    mesh.point_components.append(0)


def test_missing_native_is_source_only_fallback_and_incompatible_api_is_loud(monkeypatch):
    error = ModuleNotFoundError("missing native", name="xml_to_usda._usda_numbers")
    with patch.object(importlib, "import_module", side_effect=error):
        assert numbers._native_module() is None
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        with pytest.raises(RuntimeError, match="missing"):
            numbers._native_module()
    with patch.object(importlib, "import_module", return_value=object()):
        with pytest.raises(RuntimeError, match="API"):
            numbers._native_module()
