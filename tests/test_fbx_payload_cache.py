from __future__ import annotations

import os
from array import array
from pathlib import Path

import pytest

from xml_to_usda.fbx_adapter import load_fbx_geometry
from xml_to_usda.fbx_payload_cache import (
    FbxPayloadCacheOptions,
    clear_fbx_payload_cache,
    load_fbx_payload_from_cache,
    store_fbx_payload_in_cache,
    summarize_fbx_payload_cache,
    sweep_fbx_payload_cache,
)
from xml_to_usda.models import CpuProfile, GeometryBuffer


def _payload(name: str = "CachedBranch") -> GeometryBuffer:
    return GeometryBuffer(
        name=name,
        point_components=array("f", [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0]),
        face_vertex_counts=array("i", [3]),
        face_vertex_indices=array("i", [0, 1, 2]),
    )


def _options(*, read_vertex_colors: bool = True, read_material_slots: bool = False) -> FbxPayloadCacheOptions:
    return FbxPayloadCacheOptions(
        read_vertex_colors=read_vertex_colors,
        read_material_slots=read_material_slots,
        strict_vertex_colors=read_vertex_colors,
    )


def test_fbx_payload_cache_hit_avoids_reimporting_stable_payload(tmp_path: Path) -> None:
    fbx_path = tmp_path / "branch.fbx"
    fbx_path.write_bytes(b"fbx")
    cache_root = tmp_path / "cache"

    store_fbx_payload_in_cache(str(fbx_path), _options(), _payload(), cache_root=cache_root)

    cached = load_fbx_payload_from_cache(str(fbx_path), _options(), cache_root=cache_root)

    assert cached.hit is True
    assert cached.payload == _payload()


def test_fbx_payload_cache_invalidates_when_source_timestamp_changes(tmp_path: Path) -> None:
    fbx_path = tmp_path / "branch.fbx"
    fbx_path.write_bytes(b"fbx")
    cache_root = tmp_path / "cache"

    store_fbx_payload_in_cache(str(fbx_path), _options(), _payload(), cache_root=cache_root)
    stat = fbx_path.stat()
    os.utime(fbx_path, ns=(stat.st_atime_ns + 10_000_000, stat.st_mtime_ns + 10_000_000))

    cached = load_fbx_payload_from_cache(str(fbx_path), _options(), cache_root=cache_root)

    assert cached.hit is False
    assert cached.payload is None


def test_fbx_payload_cache_uses_read_options_in_key(tmp_path: Path) -> None:
    fbx_path = tmp_path / "branch.fbx"
    fbx_path.write_bytes(b"fbx")
    cache_root = tmp_path / "cache"

    store_fbx_payload_in_cache(
        str(fbx_path),
        _options(read_vertex_colors=False, read_material_slots=False),
        _payload("SingleMaterialPayload"),
        cache_root=cache_root,
    )

    cached = load_fbx_payload_from_cache(
        str(fbx_path),
        _options(read_vertex_colors=True, read_material_slots=False),
        cache_root=cache_root,
    )

    assert cached.hit is False
    assert cached.payload is None


def test_fbx_payload_cache_corrupt_entry_falls_back_to_import(tmp_path: Path) -> None:
    fbx_path = tmp_path / "branch.fbx"
    fbx_path.write_bytes(b"fbx")
    cache_root = tmp_path / "cache"
    stored = store_fbx_payload_in_cache(str(fbx_path), _options(), _payload(), cache_root=cache_root)
    assert stored.cache_path is not None
    stored.cache_path.write_bytes(b"not a pickle")

    cached = load_fbx_payload_from_cache(str(fbx_path), _options(), cache_root=cache_root)

    assert cached.hit is False
    assert cached.payload is None
    assert "cache_read_failed" in cached.message


def test_fbx_payload_cache_summary_and_clear_report_payload_entries(tmp_path: Path) -> None:
    fbx_path = tmp_path / "branch.fbx"
    fbx_path.write_bytes(b"fbx")
    cache_root = tmp_path / "cache"

    stored = store_fbx_payload_in_cache(str(fbx_path), _options(), _payload(), cache_root=cache_root)
    assert stored.cache_path is not None
    payload_bytes = stored.cache_path.stat().st_size

    before_clear = summarize_fbx_payload_cache(cache_root=cache_root)
    cleared = clear_fbx_payload_cache(cache_root=cache_root)
    after_clear = summarize_fbx_payload_cache(cache_root=cache_root)

    assert before_clear.entry_count == 1
    assert before_clear.total_bytes == payload_bytes
    assert before_clear.removed_entries == 0
    assert cleared.entry_count == 0
    assert cleared.total_bytes == 0
    assert cleared.removed_entries == 1
    assert cleared.removed_bytes == payload_bytes
    assert cleared.failed_paths == ()
    assert after_clear.entry_count == 0
    assert stored.cache_path.exists() is False
    assert stored.cache_path.with_suffix(".json").exists() is False


def test_fbx_payload_cache_clear_missing_directory_is_empty_summary(tmp_path: Path) -> None:
    cleared = clear_fbx_payload_cache(cache_root=tmp_path / "missing-cache")

    assert cleared.entry_count == 0
    assert cleared.total_bytes == 0
    assert cleared.removed_entries == 0
    assert cleared.removed_bytes == 0
    assert cleared.failed_paths == ()


def test_fbx_payload_cache_sweep_removes_oldest_payload_over_size_limit(tmp_path: Path) -> None:
    first_fbx = tmp_path / "first.fbx"
    second_fbx = tmp_path / "second.fbx"
    first_fbx.write_bytes(b"first")
    second_fbx.write_bytes(b"second")
    cache_root = tmp_path / "cache"

    first = store_fbx_payload_in_cache(str(first_fbx), _options(), _payload("First"), cache_root=cache_root)
    second = store_fbx_payload_in_cache(str(second_fbx), _options(), _payload("Second"), cache_root=cache_root)
    assert first.cache_path is not None
    assert second.cache_path is not None
    os.utime(first.cache_path, (1.0, 1.0))
    os.utime(first.cache_path.with_suffix(".json"), (1.0, 1.0))

    summary = sweep_fbx_payload_cache(cache_root=cache_root, max_bytes=second.cache_path.stat().st_size)

    assert first.cache_path.exists() is False
    assert first.cache_path.with_suffix(".json").exists() is False
    assert second.cache_path.exists() is True
    assert summary.entry_count == 1
    assert summary.removed_entries == 1


def test_fbx_payload_cache_sweep_removes_stale_payload(tmp_path: Path) -> None:
    fbx_path = tmp_path / "branch.fbx"
    fbx_path.write_bytes(b"fbx")
    cache_root = tmp_path / "cache"
    stored = store_fbx_payload_in_cache(str(fbx_path), _options(), _payload(), cache_root=cache_root)
    assert stored.cache_path is not None
    os.utime(stored.cache_path, (1.0, 1.0))
    os.utime(stored.cache_path.with_suffix(".json"), (1.0, 1.0))

    summary = sweep_fbx_payload_cache(cache_root=cache_root, max_age_seconds=1, now=10.0)

    assert stored.cache_path.exists() is False
    assert stored.cache_path.with_suffix(".json").exists() is False
    assert summary.entry_count == 0
    assert summary.removed_entries == 1


def test_json_geometry_backend_honors_selective_read_options(tmp_path: Path) -> None:
    payload_path = tmp_path / "branch.json"
    payload_path.write_text(
        """{
  "point_components": [0, 0, 0, 1, 0, 0, 0, 1, 0],
  "face_vertex_counts": [3],
  "face_vertex_indices": [0, 1, 2],
  "vertex_color_components": [0, 0, 0, 1, 1, 1, 1, 1, 0, 0, 0, 1],
  "fbx_material_slots": [{"source_id": 1, "name": "Bark", "face_count": 1}],
  "sections": [{"material_id": 1, "face_indices": [0]}]
}""",
        encoding="utf-8",
    )

    loaded = load_fbx_geometry(
        str(payload_path),
        "Branch",
        cpu_profile=CpuProfile.BALANCED,
        read_vertex_colors=False,
        read_material_slots=False,
    )

    assert loaded.vertex_color_count == 0
    assert loaded.fbx_material_slots == ()
    assert loaded.sections == ()


@pytest.mark.skipif(
    not os.environ.get("XML_TO_USDA_HEAVY_FBX_STRESS_PATH"),
    reason="Set XML_TO_USDA_HEAVY_FBX_STRESS_PATH to run the local huge-FBX cache stress test.",
)
def test_optional_heavy_fbx_payload_cache_stress() -> None:
    fbx_path = os.environ["XML_TO_USDA_HEAVY_FBX_STRESS_PATH"]
    options = _options(read_vertex_colors=False, read_material_slots=False)

    first = load_fbx_payload_from_cache(fbx_path, options)
    if first.payload is None:
        payload = load_fbx_geometry(
            fbx_path,
            "StressBranch",
            cpu_profile=CpuProfile.BALANCED,
            read_vertex_colors=False,
            read_material_slots=False,
        )
        store_fbx_payload_in_cache(fbx_path, options, payload)

    second = load_fbx_payload_from_cache(fbx_path, options)

    assert second.hit is True
    assert second.payload is not None
    assert second.payload.face_count > 0
