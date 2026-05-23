"""Local diagnostics bundle export.

Layer: application/infrastructure edge.

The exporter gathers already-local artifacts into a zip file. It intentionally
does not inspect converter internals or contact any external service.
"""

from __future__ import annotations

import json
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .runtime_paths import capture_runtime_context


@dataclass(frozen=True)
class DiagnosticsBundleRequest:
    bundle_path: Path
    settings_path: Path
    runtime_log_path: Path | None = None
    build_info_path: Path | None = None
    jobs_root: Path | None = None
    active_preset_name: str = ""
    selected_input_path: str = ""
    selected_output_path: str = ""
    in_app_log_text: str = ""
    runtime_summary: dict[str, Any] = field(default_factory=dict)


def export_diagnostics_bundle(request: DiagnosticsBundleRequest) -> Path:
    bundle_path = Path(request.bundle_path)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(bundle_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        _write_file_or_note(
            archive,
            source_path=request.settings_path,
            archive_name="settings/gui_settings.json",
            missing_name="settings/gui_settings_missing.txt",
        )
        _write_file_or_note(
            archive,
            source_path=request.runtime_log_path,
            archive_name="logs/gui_runtime.log",
            missing_name="logs/gui_runtime_missing.txt",
        )
        _write_text(archive, "logs/in_app_log.txt", request.in_app_log_text.strip() or "No in-app log entries.")
        _write_file_or_note(
            archive,
            source_path=request.build_info_path,
            archive_name="build/build_info.json",
            missing_name="build/build_info_missing.txt",
        )
        latest_manifest = _latest_job_manifest(request.jobs_root)
        _write_file_or_note(
            archive,
            source_path=latest_manifest,
            archive_name="runtime/latest_job_manifest.json",
            missing_name="runtime/latest_job_manifest_missing.txt",
        )
        _write_json(archive, "runtime/runtime_summary.json", _build_runtime_summary(request))

    return bundle_path


def default_build_info_path() -> Path | None:
    candidates: list[Path] = []
    for raw_path in (sys.argv[0] if sys.argv else "", sys.executable):
        if raw_path:
            try:
                candidates.append(Path(raw_path).resolve().with_name("build_info.json"))
            except OSError:
                pass
    candidates.append(Path(__file__).resolve().parents[2] / "dist-next" / "build_info.json")
    candidates.append(Path(__file__).resolve().parents[2] / "dist" / "build_info.json")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _build_runtime_summary(request: DiagnosticsBundleRequest) -> dict[str, object]:
    return {
        "active_preset_name": request.active_preset_name,
        "selected_input_path": request.selected_input_path,
        "selected_output_path": request.selected_output_path,
        "settings_path": str(request.settings_path),
        "runtime_log_path": str(request.runtime_log_path) if request.runtime_log_path else "",
        "build_info_path": str(request.build_info_path) if request.build_info_path else "",
        "jobs_root": str(request.jobs_root) if request.jobs_root else "",
        "runtime_context": capture_runtime_context(),
        "runtime_summary": dict(request.runtime_summary),
    }


def _latest_job_manifest(jobs_root: Path | None) -> Path | None:
    if jobs_root is None:
        return None
    try:
        manifests = [path for path in Path(jobs_root).glob("*/job_manifest.json") if path.is_file()]
    except OSError:
        return None
    if not manifests:
        return None
    return max(manifests, key=lambda path: (_safe_mtime(path), path.parent.name))


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _write_file_or_note(
    archive: zipfile.ZipFile,
    *,
    source_path: Path | None,
    archive_name: str,
    missing_name: str,
) -> None:
    if source_path is not None and Path(source_path).exists():
        archive.write(Path(source_path), archive_name)
        return
    _write_text(archive, missing_name, f"Missing local artifact: {source_path or '<not configured>'}")


def _write_json(archive: zipfile.ZipFile, archive_name: str, payload: dict[str, object]) -> None:
    _write_text(archive, archive_name, json.dumps(payload, indent=2, sort_keys=True))


def _write_text(archive: zipfile.ZipFile, archive_name: str, text: str) -> None:
    archive.writestr(archive_name, text)
