"""File-based Conversion worker protocol.

Layer: infrastructure.

Packaged GUI conversions use this helper protocol instead of
`multiprocessing` queues. The worker exchange is file-based so frozen one-file
builds can launch a minimal helper command, native crashes stay outside the UI
process, and telemetry/result payloads do not travel through multiprocessing
pipes.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from pathlib import Path

from .job_control import apply_process_profile
from .models import ConversionJobResult, ConversionRequest
from .pipeline import convert_request
from .runtime_error_mode import suppress_windows_native_error_dialogs
from .runtime_paths import RuntimePaths
from .worker_commands import CONVERSION_WORKER_COMMAND
from .worker_file_protocol import (
    cleanup_file,
    read_error_payload,
    read_worker_payload,
    write_error_payload,
    write_worker_payload_atomic,
)


@dataclass(frozen=True)
class ConversionWorkerRequest:
    request: ConversionRequest
    runtime_paths: RuntimePaths
    result_path: str
    error_path: str
    event_dir: str


def write_conversion_worker_request(path: str | Path, request: ConversionWorkerRequest) -> None:
    write_worker_payload_atomic(path, request)


def read_conversion_worker_request(path: str | Path) -> ConversionWorkerRequest:
    payload = read_worker_payload(path)
    if not isinstance(payload, ConversionWorkerRequest):
        raise TypeError("Invalid Conversion worker request payload.")
    return payload


def read_conversion_worker_error(path: str | Path) -> tuple[str, str] | None:
    return read_error_payload(path)


def run_conversion_worker_request_file(path: str | Path) -> int:
    suppress_windows_native_error_dialogs()
    request = read_conversion_worker_request(path)
    event_writer = _TelemetryEventWriter(Path(request.event_dir))
    try:
        apply_process_profile(request.request.cpu_profile)
        result = convert_request(
            request.request,
            telemetry_callback=event_writer.write,
            runtime_paths=request.runtime_paths,
        )[0]
        write_worker_payload_atomic(request.result_path, ConversionJobResult(result=result))
        cleanup_file(request.error_path)
        return 0
    except Exception as exc:
        formatted_traceback = traceback.format_exc()
        write_error_payload(request.error_path, message=str(exc), formatted_traceback=formatted_traceback)
        write_worker_payload_atomic(request.result_path, ConversionJobResult(error_message=str(exc)))
        return 1


class _TelemetryEventWriter:
    def __init__(self, event_dir: Path) -> None:
        self.event_dir = event_dir
        self.sequence = 0
        self.event_dir.mkdir(parents=True, exist_ok=True)

    def write(self, telemetry) -> None:
        event_path = self.event_dir / f"{self.sequence:06d}.event.json"
        self.sequence += 1
        write_worker_payload_atomic(event_path, ("telemetry", telemetry))
