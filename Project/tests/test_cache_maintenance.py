from __future__ import annotations

import os
from array import array
from pathlib import Path

import pytest

from xml_to_usda.cache_maintenance import clear_application_cache, sweep_application_cache
from xml_to_usda.fbx_payload_cache import FbxPayloadCacheOptions, store_fbx_payload_in_cache
from xml_to_usda.models import GeometryBuffer
from xml_to_usda.runtime_paths import resolve_runtime_paths


def _runtime_paths(tmp_path: Path):
    return resolve_runtime_paths(
        settings_dir=tmp_path / "settings",
        settings_path=tmp_path / "settings" / "gui_settings.json",
        cache_root=tmp_path / "cache",
    )


def _isolate_runtime_temp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    monkeypatch.setattr("xml_to_usda.runtime_paths._system_temp_root", lambda: temp_root)


def _write(path: Path, size: int = 4, *, mtime: float = 1.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    os.utime(path, (mtime, mtime))
    return path


def test_application_cache_sweep_removes_stale_source_fact_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_paths = _runtime_paths(tmp_path)
    _isolate_runtime_temp(monkeypatch, tmp_path)
    stale_source = _write(runtime_paths.cache_root / "source_models" / "old.json", mtime=1.0)
    stale_proxy = _write(runtime_paths.cache_root / "proxy_source_projections" / "old.npz", mtime=1.0)
    fresh_fracture = _write(runtime_paths.cache_root / "fracture_preview_source_models" / "fresh.npz", mtime=99.0)
    unrelated = _write(runtime_paths.cache_root / "source_models" / "note.txt", mtime=1.0)

    summary = sweep_application_cache(
        runtime_paths,
        source_facts_max_age_seconds=50,
        source_facts_max_bytes=1024,
        now=100.0,
    )

    assert not stale_source.exists()
    assert not stale_proxy.exists()
    assert fresh_fracture.exists()
    assert unrelated.exists()
    assert sum(bucket.removed_entries for bucket in summary.source_facts) == 2


def test_application_cache_sweep_enforces_shared_source_fact_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_paths = _runtime_paths(tmp_path)
    _isolate_runtime_temp(monkeypatch, tmp_path)
    oldest = _write(runtime_paths.cache_root / "source_models" / "oldest.json", 10, mtime=1.0)
    proxy = _write(runtime_paths.cache_root / "proxy_source_projections" / "proxy.npz", 20, mtime=2.0)
    fracture = _write(runtime_paths.cache_root / "fracture_preview_source_models" / "fracture.npz", 30, mtime=3.0)

    summary = sweep_application_cache(
        runtime_paths,
        source_facts_max_age_seconds=1000,
        source_facts_max_bytes=50,
        now=10.0,
    )

    assert not oldest.exists()
    assert proxy.exists()
    assert fracture.exists()
    assert sum(bucket.total_bytes for bucket in summary.source_facts) == 50
    assert sum(bucket.removed_entries for bucket in summary.source_facts) == 1


def test_application_cache_sweep_removes_only_stale_cache_temp_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_paths = _runtime_paths(tmp_path)
    _isolate_runtime_temp(monkeypatch, tmp_path)
    stale_partial = _write(runtime_paths.cache_root / "fbx-payloads" / "old.payload.json.partial", mtime=1.0)
    fresh_partial = _write(runtime_paths.cache_root / "fbx-payloads" / "fresh.payload.json.partial", mtime=99.0)

    summary = sweep_application_cache(runtime_paths, runtime_stale_after_seconds=50, now=100.0)

    assert not stale_partial.exists()
    assert fresh_partial.exists()
    assert summary.temp_files is not None
    assert summary.temp_files.removed_entries == 1


def test_clear_application_cache_removes_fbx_and_source_fact_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_paths = _runtime_paths(tmp_path)
    _isolate_runtime_temp(monkeypatch, tmp_path)
    source_entry = _write(runtime_paths.cache_root / "source_models" / "source.json")
    temp_entry = _write(runtime_paths.cache_root / "fracture_preview_source_models" / "entry.npz.tmp")
    fbx_path = tmp_path / "branch.fbx"
    fbx_path.write_bytes(b"fbx")
    stored = store_fbx_payload_in_cache(
        str(fbx_path),
        FbxPayloadCacheOptions(read_vertex_colors=False, read_material_slots=False, strict_vertex_colors=False),
        GeometryBuffer(
            name="Branch",
            point_components=array("f"),
            face_vertex_counts=array("i"),
            face_vertex_indices=array("i"),
        ),
        cache_root=runtime_paths.cache_root / "fbx-payloads",
    )
    assert stored.cache_path is not None

    summary = clear_application_cache(runtime_paths)

    assert not source_entry.exists()
    assert not temp_entry.exists()
    assert not stored.cache_path.exists()
    assert summary.removed_entries >= 3
