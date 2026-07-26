"""Crash-isolated source-row discovery worker protocol."""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from pathlib import Path

from .discovery_service import SourceDiscoveryRequest, SourceDiscoveryResult, discover_source_rows
from .runtime_error_mode import suppress_windows_native_error_dialogs
from .worker_commands import SOURCE_DISCOVERY_WORKER_COMMAND
from .worker_file_protocol import (
    cleanup_file,
    read_error_payload,
    read_worker_payload,
    validate_worker_token,
    write_error_payload,
    write_worker_payload_atomic,
)


@dataclass(frozen=True)
class SourceDiscoveryWorkerRequest:
    request: SourceDiscoveryRequest
    result_path: str
    error_path: str
    worker_token: str


def write_source_discovery_worker_request(path: str | Path, request: SourceDiscoveryWorkerRequest) -> None:
    write_worker_payload_atomic(path, request)


def read_source_discovery_worker_request(path: str | Path) -> SourceDiscoveryWorkerRequest:
    payload = read_worker_payload(path)
    if not isinstance(payload, SourceDiscoveryWorkerRequest):
        raise TypeError("Invalid source discovery worker request payload.")
    return payload


def read_source_discovery_worker_error(path: str | Path) -> tuple[str, str] | None:
    return read_error_payload(path)


def read_source_discovery_worker_result(path: str | Path) -> SourceDiscoveryResult:
    payload = read_worker_payload(path)
    if not isinstance(payload, SourceDiscoveryResult):
        raise TypeError("Invalid source discovery worker result payload.")
    return payload


def run_source_discovery_worker_request_file(path: str | Path) -> int:
    suppress_windows_native_error_dialogs()
    request = read_source_discovery_worker_request(path)
    try:
        validate_worker_token(request.worker_token)
        result = discover_source_rows(request.request)
        write_worker_payload_atomic(request.result_path, result)
        cleanup_file(request.error_path)
        return 0
    except Exception as exc:
        write_error_payload(request.error_path, message=str(exc), formatted_traceback=traceback.format_exc())
        return 1
