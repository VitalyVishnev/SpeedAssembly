"""File-based Fracture export worker protocol.

Layer: infrastructure.

Fracture export resolves full Operator Intent and may touch large XML and FBX
payloads. The GUI uses this worker protocol so native crashes stay outside the
UI process and multi-file export results do not travel through multiprocessing
queues.
"""

from __future__ import annotations

import faulthandler
import time
import traceback
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from .fracture_preview_service import FracturePreviewSettings, FracturePreviewSourceRequest
from .fracture_service import FractureSettings
from .job_control import apply_process_profile
from .runtime_error_mode import suppress_windows_native_error_dialogs
from .worker_commands import FRACTURE_WORKER_COMMAND
from .worker_file_protocol import (
    cleanup_file,
    read_error_payload,
    read_worker_payload,
    validate_worker_token,
    write_error_payload,
    write_worker_payload_atomic,
)

if TYPE_CHECKING:
    from .fracture_export_service import FractureExportRequest
    from .fracture_export_service import FractureExportResult
    from .fracture_preview_service import FracturePreviewResult


FRACTURE_WORKER_ACTION_EXPORT = "export"
FRACTURE_WORKER_ACTION_PREVIEW = "preview"


@dataclass(frozen=True)
class FractureWorkerRequest:
    request: object
    settings: FractureSettings | FracturePreviewSettings
    action: str
    result_path: str
    error_path: str
    worker_token: str


def write_fracture_worker_request(path: str | Path, request: FractureWorkerRequest) -> None:
    write_worker_payload_atomic(path, request)


def read_fracture_worker_request(path: str | Path) -> FractureWorkerRequest:
    payload = read_worker_payload(path)
    if not isinstance(payload, FractureWorkerRequest):
        raise TypeError("Invalid Fracture worker request payload.")
    return payload


def read_fracture_worker_error(path: str | Path) -> tuple[str, str] | None:
    return read_error_payload(path)


def run_fracture_worker_request_file(path: str | Path) -> int:
    suppress_windows_native_error_dialogs()
    try:
        faulthandler.enable(file=sys.stderr, all_threads=True)
    except Exception:
        pass
    _worker_stage("request.read.start")
    request = read_fracture_worker_request(path)
    try:
        validate_worker_token(request.worker_token)
        _worker_stage(f"{request.action}.profile.start")
        apply_process_profile(request.request.cpu_profile)
        if request.action == FRACTURE_WORKER_ACTION_EXPORT:
            from .fracture_export_service import FractureExportRequest

            if not isinstance(request.request, FractureExportRequest):
                raise TypeError("Fracture export worker requires FractureExportRequest.")
            if not isinstance(request.settings, FractureSettings):
                raise TypeError("Fracture export worker requires FractureSettings.")
            from .fracture_export_service import export_fracture_usda_from_export_request

            _worker_stage("export.generate.start")
            result = export_fracture_usda_from_export_request(request.request, request.settings)
            _worker_stage("export.generate.end")
        elif request.action == FRACTURE_WORKER_ACTION_PREVIEW:
            if not isinstance(request.request, FracturePreviewSourceRequest):
                raise TypeError("Fracture preview worker requires FracturePreviewSourceRequest.")
            if not isinstance(request.settings, FracturePreviewSettings):
                raise TypeError("Fracture preview worker requires FracturePreviewSettings.")
            from .fracture_preview_service import generate_fracture_preview_from_source_request

            _worker_stage(
                "preview.generate.start",
                generate_caps=request.settings.fracture.generate_caps,
                target_branch_count=request.settings.fracture.target_piece_count,
                force_stump_piece=request.settings.fracture.force_stump_piece,
                separate_stems=request.settings.fracture.separate_stems,
                branch_height_bias=request.settings.fracture.branch_height_bias,
                noisy_cut_enabled=request.settings.fracture.noisy_cut_enabled,
                noisy_cut_intensity=request.settings.fracture.noisy_cut_intensity,
                noisy_cut_scale=request.settings.fracture.noisy_cut_scale,
            )
            result = generate_fracture_preview_from_source_request(
                request.request,
                request.settings,
                include_viewport_scene=False,
            )
            _worker_stage("preview.generate.end")
        else:
            raise ValueError(f"Unsupported fracture worker action: {request.action}")
        _worker_stage("result.write.start")
        write_fracture_worker_result(request.result_path, result)
        _worker_stage("result.write.end")
        cleanup_file(request.error_path)
        return 0
    except Exception as exc:
        _worker_stage("error.write.start", error_type=type(exc).__name__, message=str(exc))
        write_error_payload(request.error_path, message=str(exc), formatted_traceback=traceback.format_exc())
        return 1


def run_fracture_preview_worker_server(queue_directory: str | Path, *, idle_timeout_seconds: float = 300.0) -> int:
    """Serve sequential preview requests in one crash-isolated process."""
    suppress_windows_native_error_dialogs()
    queue_dir = Path(queue_directory)
    queue_dir.mkdir(parents=True, exist_ok=True)
    processed: set[str] = set()
    last_activity = time.monotonic()
    while time.monotonic() - last_activity < idle_timeout_seconds:
        requests = tuple(sorted(queue_dir.glob("*.request.json")))
        pending = tuple(path for path in requests if path.name not in processed)
        if not pending:
            time.sleep(0.02)
            continue
        for request_path in pending:
            processed.add(request_path.name)
            last_activity = time.monotonic()
            run_fracture_worker_request_file(request_path)
    return 0


def read_fracture_worker_result(path: str | Path) -> "FractureExportResult | FracturePreviewResult | None":
    result_path = Path(path)
    if not result_path.exists():
        return None
    payload = read_worker_payload(result_path)
    payload_type = type(payload)
    if payload_type.__module__ == "xml_to_usda.fracture_preview_service" and payload_type.__name__ == "FracturePreviewResult":
        return payload
    if payload_type.__module__ == "xml_to_usda.fracture_export_service" and payload_type.__name__ == "FractureExportResult":
        from .fracture_export_service import FractureExportResult

        if isinstance(payload, FractureExportResult):
            return payload
    raise TypeError("Invalid Fracture worker result payload.")


def write_fracture_worker_result(path: str | Path, result: object) -> None:
    write_worker_payload_atomic(path, _worker_result_payload(result))


def _worker_result_payload(result: object) -> object:
    payload_type = type(result)
    if payload_type.__module__ == "xml_to_usda.fracture_preview_service" and payload_type.__name__ == "FracturePreviewResult":
        return replace(result, viewport_scene=None)
    return result


def _worker_stage(stage: str, **fields: object) -> None:
    details = " ".join(f"{key}={value}" for key, value in sorted(fields.items()))
    suffix = f" {details}" if details else ""
    print(f"fracture-worker stage={stage}{suffix}", file=sys.stderr, flush=True)
