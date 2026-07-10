"""File-based Wind Preview worker protocol."""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .runtime_error_mode import suppress_windows_native_error_dialogs
from .wind_preview_service import WindPreviewRequest, WindPreviewResult, generate_wind_preview_from_request
from .worker_commands import WIND_PREVIEW_WORKER_COMMAND
from .worker_file_protocol import (
    cleanup_file,
    read_error_payload,
    read_worker_payload,
    validate_worker_token,
    write_error_payload,
    write_worker_payload_atomic,
)

if TYPE_CHECKING:
    from .wind_external_skeleton import (
        ExternalSkeletonChoicesRequest,
        ExternalSkeletonChoicesResult,
        ExternalSkeletonPreviewRequest,
    )


@dataclass(frozen=True)
class WindPreviewWorkerRequest:
    request: WindPreviewRequest | ExternalSkeletonPreviewRequest | ExternalSkeletonChoicesRequest
    result_path: str
    error_path: str
    worker_token: str


def write_wind_preview_worker_request(path: str | Path, request: WindPreviewWorkerRequest) -> None:
    write_worker_payload_atomic(path, request)


def read_wind_preview_worker_request(path: str | Path) -> WindPreviewWorkerRequest:
    payload = read_worker_payload(path)
    if not isinstance(payload, WindPreviewWorkerRequest):
        raise TypeError("Invalid Wind Preview worker request payload.")
    return payload


def read_wind_preview_worker_result(path: str | Path) -> WindPreviewResult | ExternalSkeletonChoicesResult:
    from .wind_external_skeleton import ExternalSkeletonChoicesResult

    payload = read_worker_payload(path)
    if not isinstance(payload, (WindPreviewResult, ExternalSkeletonChoicesResult)):
        raise TypeError("Invalid Wind Preview worker result payload.")
    return payload


def read_wind_preview_worker_error(path: str | Path) -> tuple[str, str] | None:
    return read_error_payload(path)


def run_wind_preview_worker_request_file(path: str | Path) -> int:
    suppress_windows_native_error_dialogs()
    request = read_wind_preview_worker_request(path)
    try:
        validate_worker_token(request.worker_token)
        if isinstance(request.request, WindPreviewRequest):
            result = generate_wind_preview_from_request(request.request)
        else:
            from .wind_external_skeleton import (
                ExternalSkeletonChoicesRequest,
                ExternalSkeletonPreviewRequest,
                list_external_usd_skeletons,
                load_external_skeleton_preview,
            )

            if isinstance(request.request, ExternalSkeletonChoicesRequest):
                result = list_external_usd_skeletons(request.request.input_path)
            elif isinstance(request.request, ExternalSkeletonPreviewRequest):
                result = load_external_skeleton_preview(request.request)
            else:
                raise TypeError(f"Unsupported Wind Preview worker request: {type(request.request).__name__}")
        write_worker_payload_atomic(request.result_path, result)
        cleanup_file(request.error_path)
        return 0
    except Exception as exc:
        write_error_payload(request.error_path, message=str(exc), formatted_traceback=traceback.format_exc())
        return 1
