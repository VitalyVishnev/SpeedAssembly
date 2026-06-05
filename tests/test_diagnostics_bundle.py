from __future__ import annotations

import json
import zipfile

from xml_to_usda.diagnostics_bundle import (
    DiagnosticsBundleRequest,
    build_diagnostics_bundle_request,
    export_diagnostics_bundle,
)
from xml_to_usda.runtime_paths import RuntimeCleanupSummary, RuntimePaths


def test_diagnostics_bundle_exports_local_reproduction_artifacts(tmp_path) -> None:
    settings_dir = tmp_path / "settings"
    cache_root = tmp_path / "cache"
    jobs_root = cache_root / "jobs"
    settings_dir.mkdir()
    jobs_root.mkdir(parents=True)
    settings_path = settings_dir / "gui_settings.json"
    runtime_log_path = settings_dir / "gui_runtime.log"
    build_info_path = tmp_path / "dist-next" / "build_info.json"
    output_path = tmp_path / "exports" / "oak.usda"
    bundle_path = tmp_path / "support" / "diagnostics.zip"

    settings_path.write_text('{"active_preset_name": "Artist Preset"}', encoding="utf-8")
    runtime_log_path.write_text("Traceback line 1\nTraceback line 2", encoding="utf-8")
    build_info_path.parent.mkdir()
    build_info_path.write_text('{"build_mode": "package", "git_head": "abc123"}', encoding="utf-8")
    output_path.parent.mkdir()
    output_path.write_text("#usda 1.0", encoding="utf-8")

    old_job = jobs_root / "20260522-110000-old"
    new_job = jobs_root / "20260522-120000-new"
    old_job.mkdir()
    new_job.mkdir()
    (old_job / "job_manifest.json").write_text('{"job_id": "old"}', encoding="utf-8")
    (new_job / "job_manifest.json").write_text('{"job_id": "new"}', encoding="utf-8")

    exported_path = export_diagnostics_bundle(
        DiagnosticsBundleRequest(
            bundle_path=bundle_path,
            settings_path=settings_path,
            runtime_log_path=runtime_log_path,
            build_info_path=build_info_path,
            jobs_root=jobs_root,
            active_preset_name="Artist Preset",
            selected_input_path=str(tmp_path / "oak.xml"),
            selected_output_path=str(output_path),
            in_app_log_text="Conversion failed after USDA writing.",
            runtime_summary={"cache_root": str(cache_root)},
        )
    )

    assert exported_path == bundle_path
    with zipfile.ZipFile(exported_path) as archive:
        names = set(archive.namelist())
        assert {
            "settings/gui_settings.json",
            "logs/gui_runtime.log",
            "logs/in_app_log.txt",
            "build/build_info.json",
            "runtime/runtime_summary.json",
            "runtime/latest_job_manifest.json",
        }.issubset(names)
        summary = json.loads(archive.read("runtime/runtime_summary.json"))
        assert summary["active_preset_name"] == "Artist Preset"
        assert summary["selected_output_path"] == str(output_path)
        assert summary["runtime_summary"]["cache_root"] == str(cache_root)
        assert archive.read("runtime/latest_job_manifest.json") == b'{"job_id": "new"}'
        assert b"Traceback line 2" in archive.read("logs/gui_runtime.log")


def test_diagnostics_bundle_request_builder_projects_runtime_context(tmp_path) -> None:
    runtime_paths = RuntimePaths(
        settings_dir=tmp_path / "settings",
        settings_path=tmp_path / "settings" / "gui_settings.json",
        cache_root=tmp_path / "cache",
        jobs_root=tmp_path / "cache" / "jobs",
    )
    cleanup_summary = RuntimeCleanupSummary(
        removed_jobs=2,
        removed_partial_outputs=1,
        failed_jobs=3,
    )
    bundle_path = tmp_path / "support" / "bundle.zip"

    request = build_diagnostics_bundle_request(
        bundle_path=bundle_path,
        settings_path=runtime_paths.settings_path,
        runtime_paths=runtime_paths,
        runtime_cleanup_summary=cleanup_summary,
        active_preset_name="Production",
        selected_input_path="oak.xml",
        selected_output_path="oak.usda",
        in_app_log_text="last error",
        build_info_path=tmp_path / "build_info.json",
    )

    assert request.bundle_path == bundle_path
    assert request.settings_path == runtime_paths.settings_path
    assert request.runtime_log_path == runtime_paths.settings_dir / "gui_runtime.log"
    assert request.jobs_root == runtime_paths.jobs_root
    assert request.active_preset_name == "Production"
    assert request.selected_input_path == "oak.xml"
    assert request.selected_output_path == "oak.usda"
    assert request.in_app_log_text == "last error"
    assert request.runtime_summary == {
        "settings_dir": str(runtime_paths.settings_dir),
        "cache_root": str(runtime_paths.cache_root),
        "jobs_root": str(runtime_paths.jobs_root),
        "removed_stale_jobs": 2,
        "removed_stale_partial_outputs": 1,
        "failed_cleanup_jobs": 3,
    }
