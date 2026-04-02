from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from xml_to_usda.models import CleanupPolicy, CpuProfile, PrototypeSourceConfig, PrototypeSourceMode
from xml_to_usda.pipeline import convert_file
from xml_to_usda.runtime_paths import (
    JobWorkspace,
    resolve_runtime_paths,
    sweep_stale_job_workspaces,
)


SIMPLE_TREE_01 = Path(__file__).resolve().parents[1] / "samples" / "speedtree" / "simple_tree" / "variants" / "SimpleTree_01.xml"


def _write_fbx_json_payload(tmp_path: Path) -> Path:
    payload = {
        "point_components": [
            0.0, 0.0, 0.0,
            1.0, 0.0, 0.0,
            0.0, 1.0, 0.0,
        ],
        "face_vertex_counts": [3],
        "face_vertex_indices": [0, 1, 2],
        "uv_components": [
            0.0, 0.0,
            1.0, 0.0,
            0.0, 1.0,
        ],
    }
    payload_path = tmp_path / "prototype_payload.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    return payload_path


def test_runtime_path_resolution_keeps_settings_separate_from_cache(tmp_path: Path) -> None:
    runtime_paths = resolve_runtime_paths(
        settings_dir=tmp_path / "settings",
        settings_path=tmp_path / "settings" / "gui_settings.json",
        cache_root=tmp_path / "runtime_cache",
    )

    assert runtime_paths.settings_dir == tmp_path / "settings"
    assert runtime_paths.settings_path == tmp_path / "settings" / "gui_settings.json"
    assert runtime_paths.cache_root == tmp_path / "runtime_cache"
    assert runtime_paths.jobs_root == tmp_path / "runtime_cache" / "jobs"
    assert not str(runtime_paths.settings_path).startswith(str(runtime_paths.cache_root))


def test_runtime_path_resolution_accepts_string_inputs(tmp_path: Path) -> None:
    runtime_paths = resolve_runtime_paths(
        settings_dir=str(tmp_path / "settings"),
        settings_path=str(tmp_path / "settings" / "gui_settings.json"),
        cache_root=str(tmp_path / "runtime_cache"),
    )

    assert runtime_paths.settings_dir == tmp_path / "settings"
    assert runtime_paths.settings_path == tmp_path / "settings" / "gui_settings.json"
    assert runtime_paths.cache_root == tmp_path / "runtime_cache"


def test_job_workspace_is_created_inside_runtime_cache_root(tmp_path: Path) -> None:
    runtime_paths = resolve_runtime_paths(
        settings_dir=tmp_path / "settings",
        settings_path=tmp_path / "settings" / "gui_settings.json",
        cache_root=tmp_path / "runtime_cache",
    )

    workspace = JobWorkspace.create(
        runtime_paths,
        input_path=str(SIMPLE_TREE_01),
        output_path=str(tmp_path / "tree.usda"),
        cleanup_policy=CleanupPolicy.EPHEMERAL,
    )

    try:
        assert workspace.job_dir.parent == runtime_paths.jobs_root
        assert workspace.manifest_path.exists()
    finally:
        workspace.finalize(status="cancelled")


def test_startup_sweep_removes_only_stale_job_workspaces(tmp_path: Path) -> None:
    runtime_paths = resolve_runtime_paths(
        settings_dir=tmp_path / "settings",
        settings_path=tmp_path / "settings" / "gui_settings.json",
        cache_root=tmp_path / "runtime_cache",
    )
    runtime_paths.jobs_root.mkdir(parents=True, exist_ok=True)
    stale_dir = runtime_paths.jobs_root / "stale-job"
    fresh_dir = runtime_paths.jobs_root / "fresh-job"
    stale_dir.mkdir()
    fresh_dir.mkdir()
    stale_output = tmp_path / "stale.usda"
    stale_partial = stale_output.with_name("stale.usda.partial")
    stale_partial.write_text("partial", encoding="utf-8")
    old_timestamp = time.time() - (25 * 60 * 60)
    (stale_dir / "job_manifest.json").write_text(json.dumps({"output_path": str(stale_output)}), encoding="utf-8")
    (fresh_dir / "job_manifest.json").write_text("{}", encoding="utf-8")
    os_targets = (stale_dir, stale_dir / "job_manifest.json")
    for target in os_targets:
        target.touch()
        os.utime(target, (old_timestamp, old_timestamp))

    summary = sweep_stale_job_workspaces(runtime_paths, stale_after_seconds=24 * 60 * 60)

    assert summary.removed_jobs == 1
    assert summary.removed_partial_outputs == 1
    assert summary.failed_jobs == 0
    assert not stale_dir.exists()
    assert not stale_partial.exists()
    assert fresh_dir.exists()


def test_startup_sweep_reports_inaccessible_jobs_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_paths = resolve_runtime_paths(
        settings_dir=tmp_path / "settings",
        settings_path=tmp_path / "settings" / "gui_settings.json",
        cache_root=tmp_path / "runtime_cache",
    )

    def raise_permission_error(*_args, **_kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(type(runtime_paths.jobs_root), "exists", raise_permission_error)

    summary = sweep_stale_job_workspaces(runtime_paths, stale_after_seconds=24 * 60 * 60)

    assert summary.removed_jobs == 0
    assert summary.removed_partial_outputs == 0
    assert summary.failed_jobs == 1
    assert summary.failed_paths == (str(runtime_paths.jobs_root),)


def test_success_cleanup_removes_runtime_job_workspace(tmp_path: Path) -> None:
    runtime_paths = resolve_runtime_paths(
        settings_dir=tmp_path / "settings",
        settings_path=tmp_path / "settings" / "gui_settings.json",
        cache_root=tmp_path / "runtime_cache",
    )
    output_path = tmp_path / "tree.usda"

    result = convert_file(
        str(SIMPLE_TREE_01),
        str(output_path),
        cleanup_policy=CleanupPolicy.EPHEMERAL,
        runtime_paths=runtime_paths,
    )

    assert result.usda_document is not None
    assert output_path.exists()
    assert result.runtime_job_dir is None
    assert not runtime_paths.jobs_root.exists() or not any(runtime_paths.jobs_root.iterdir())


def test_cancel_cleanup_removes_job_workspace_and_partial_output(tmp_path: Path) -> None:
    runtime_paths = resolve_runtime_paths(
        settings_dir=tmp_path / "settings",
        settings_path=tmp_path / "settings" / "gui_settings.json",
        cache_root=tmp_path / "runtime_cache",
    )
    output_path = tmp_path / "cancelled.usda"
    payload_path = _write_fbx_json_payload(tmp_path)
    cancel_event = threading.Event()

    def cancel_on_first_telemetry(_telemetry) -> None:
        cancel_event.set()

    result = convert_file(
        str(SIMPLE_TREE_01),
        str(output_path),
        cpu_profile=CpuProfile.QUIET,
        cleanup_policy=CleanupPolicy.EPHEMERAL,
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path=str(payload_path),
            ),
        ),
        cancel_event=cancel_event,
        telemetry_callback=cancel_on_first_telemetry,
        runtime_paths=runtime_paths,
    )

    assert result.usda_document is None
    assert not output_path.exists()
    assert not output_path.with_name("cancelled.usda.partial").exists()
    assert not runtime_paths.jobs_root.exists() or not any(runtime_paths.jobs_root.iterdir())


def test_preserve_temp_mode_keeps_job_workspace_but_not_partial_output(tmp_path: Path) -> None:
    runtime_paths = resolve_runtime_paths(
        settings_dir=tmp_path / "settings",
        settings_path=tmp_path / "settings" / "gui_settings.json",
        cache_root=tmp_path / "runtime_cache",
    )
    output_path = tmp_path / "preserved.usda"

    result = convert_file(
        str(SIMPLE_TREE_01),
        str(output_path),
        cleanup_policy=CleanupPolicy.PRESERVE_FOR_DEBUGGING,
        runtime_paths=runtime_paths,
    )

    assert result.usda_document is not None
    assert result.runtime_job_dir is not None
    assert Path(result.runtime_job_dir).exists()
    assert (Path(result.runtime_job_dir) / "job_manifest.json").exists()
    assert not output_path.with_name("preserved.usda.partial").exists()
