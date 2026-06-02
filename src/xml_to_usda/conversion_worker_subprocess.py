"""File-based Conversion worker protocol.

Layer: infrastructure.

Packaged GUI conversions use this helper protocol instead of
`multiprocessing` queues. The worker exchange is file-based so frozen one-file
builds can launch a minimal helper command, native crashes stay outside the UI
process, and telemetry/result payloads do not travel through multiprocessing
pipes.
"""

from __future__ import annotations

import json
import pickle
import traceback
from dataclasses import dataclass
from pathlib import Path

from .job_control import apply_process_profile
from .models import ConversionJobResult, ConversionRequest
from .pipeline import convert_request
from .runtime_error_mode import suppress_windows_native_error_dialogs
from .runtime_paths import RuntimePaths


CONVERSION_WORKER_COMMAND = "conversion-worker"


@dataclass(frozen=True)
class ConversionWorkerRequest:
    request: ConversionRequest
    runtime_paths: RuntimePaths
    result_path: str
    error_path: str
    event_dir: str


def write_conversion_worker_request(path: str | Path, request: ConversionWorkerRequest) -> None:
    with Path(path).open("wb") as handle:
        pickle.dump(request, handle, protocol=pickle.HIGHEST_PROTOCOL)


def read_conversion_worker_request(path: str | Path) -> ConversionWorkerRequest:
    with Path(path).open("rb") as handle:
        payload = pickle.load(handle)
    if not isinstance(payload, ConversionWorkerRequest):
        raise TypeError("Invalid Conversion worker request payload.")
    return payload


def read_conversion_worker_error(path: str | Path) -> tuple[str, str] | None:
    error_path = Path(path)
    if not error_path.exists():
        return None
    payload = json.loads(error_path.read_text(encoding="utf-8"))
    return str(payload.get("message", "")), str(payload.get("traceback", ""))


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
        with Path(request.result_path).open("wb") as handle:
            pickle.dump(ConversionJobResult(result=result), handle, protocol=pickle.HIGHEST_PROTOCOL)
        _cleanup_file(Path(request.error_path))
        return 0
    except Exception as exc:
        formatted_traceback = traceback.format_exc()
        Path(request.error_path).write_text(
            json.dumps(
                {
                    "message": str(exc),
                    "traceback": formatted_traceback,
                }
            ),
            encoding="utf-8",
        )
        with Path(request.result_path).open("wb") as handle:
            pickle.dump(
                ConversionJobResult(error_message=str(exc)),
                handle,
                protocol=pickle.HIGHEST_PROTOCOL,
            )
        return 1


class _TelemetryEventWriter:
    def __init__(self, event_dir: Path) -> None:
        self.event_dir = event_dir
        self.sequence = 0
        self.event_dir.mkdir(parents=True, exist_ok=True)

    def write(self, telemetry) -> None:
        event_path = self.event_dir / f"{self.sequence:06d}.event.pkl"
        temp_path = self.event_dir / f"{self.sequence:06d}.event.tmp"
        self.sequence += 1
        with temp_path.open("wb") as handle:
            pickle.dump(("telemetry", telemetry), handle, protocol=pickle.HIGHEST_PROTOCOL)
        temp_path.replace(event_path)


def _cleanup_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass
