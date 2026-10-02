"""File-based Instanced Geometry prototype preview worker protocol."""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from pathlib import Path

from .job_control import apply_process_profile
from .part_preview_service import (
    PartPrototypePreviewRequest,
    PartPrototypePreviewResult,
    PartPrototypePreviewSettings,
    build_part_prototype_preview,
)
from .runtime_error_mode import suppress_windows_native_error_dialogs
from .worker_commands import PART_PREVIEW_WORKER_COMMAND
from .worker_file_protocol import (
    cleanup_file,
    read_error_payload,
    read_worker_payload,
    validate_worker_token,
    write_error_payload,
    write_worker_payload_atomic,
)


@dataclass(frozen=True)
class PartPreviewWorkerRequest:
    request: PartPrototypePreviewRequest
    settings: PartPrototypePreviewSettings
    result_path: str
    error_path: str
    worker_token: str


def write_part_preview_worker_request(path: str | Path, request: PartPreviewWorkerRequest) -> None:
    write_worker_payload_atomic(path, request)


def read_part_preview_worker_request(path: str | Path) -> PartPreviewWorkerRequest:
    payload = read_worker_payload(path)
    if not isinstance(payload, PartPreviewWorkerRequest):
        raise TypeError("Invalid Part Preview worker request payload.")
    return payload


def read_part_preview_worker_error(path: str | Path) -> tuple[str, str] | None:
    return read_error_payload(path)


def read_part_preview_worker_result(path: str | Path) -> PartPrototypePreviewResult | None:
    result_path = Path(path)
    if not result_path.exists():
        return None
    payload = read_worker_payload(result_path)
    if isinstance(payload, PartPrototypePreviewResult):
        return payload
    raise TypeError("Invalid Part Preview worker result payload.")


def run_part_preview_worker_request_file(path: str | Path) -> int:
    suppress_windows_native_error_dialogs()
    request = read_part_preview_worker_request(path)
    try:
        validate_worker_token(request.worker_token)
        apply_process_profile(request.request.cpu_profile)
        result = build_part_prototype_preview(request.request, request.settings)
        write_worker_payload_atomic(request.result_path, result)
        cleanup_file(request.error_path)
        return 0
    except Exception as exc:
        write_error_payload(request.error_path, message=str(exc), formatted_traceback=traceback.format_exc())
        return 1
