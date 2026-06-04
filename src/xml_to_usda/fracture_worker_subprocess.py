"""File-based Fracture export worker protocol.

Layer: infrastructure.

Fracture export resolves full Operator Intent and may touch large XML and FBX
payloads. The GUI uses this worker protocol so native crashes stay outside the
UI process and multi-file export results do not travel through multiprocessing
queues.
"""

from __future__ import annotations

import json
import pickle
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .fracture_preview_service import FracturePreviewSettings
from .fracture_service import FractureSettings
from .job_control import apply_process_profile
from .models import ConversionRequest
from .runtime_error_mode import suppress_windows_native_error_dialogs
from .worker_commands import FRACTURE_WORKER_COMMAND

if TYPE_CHECKING:
    from .fracture_export_service import FractureExportResult
    from .fracture_preview_service import FracturePreviewResult


FRACTURE_WORKER_ACTION_EXPORT = "export"
FRACTURE_WORKER_ACTION_PREVIEW = "preview"


@dataclass(frozen=True)
class FractureWorkerRequest:
    request: ConversionRequest
    settings: FractureSettings | FracturePreviewSettings
    action: str
    result_path: str
    error_path: str


def write_fracture_worker_request(path: str | Path, request: FractureWorkerRequest) -> None:
    request_path = Path(path)
    temp_path = request_path.with_name(f"{request_path.name}.tmp")
    try:
        with temp_path.open("wb") as handle:
            pickle.dump(request, handle, protocol=pickle.HIGHEST_PROTOCOL)
        temp_path.replace(request_path)
    except Exception:
        _cleanup_file(temp_path)
        _cleanup_file(request_path)
        raise


def read_fracture_worker_request(path: str | Path) -> FractureWorkerRequest:
    with Path(path).open("rb") as handle:
        payload = pickle.load(handle)
    if not isinstance(payload, FractureWorkerRequest):
        raise TypeError("Invalid Fracture worker request payload.")
    return payload


def read_fracture_worker_error(path: str | Path) -> tuple[str, str] | None:
    error_path = Path(path)
    if not error_path.exists():
        return None
    payload = json.loads(error_path.read_text(encoding="utf-8"))
    return str(payload.get("message", "")), str(payload.get("traceback", ""))


def run_fracture_worker_request_file(path: str | Path) -> int:
    suppress_windows_native_error_dialogs()
    request = read_fracture_worker_request(path)
    try:
        apply_process_profile(request.request.cpu_profile)
        if request.action == FRACTURE_WORKER_ACTION_EXPORT:
            if not isinstance(request.settings, FractureSettings):
                raise TypeError("Fracture export worker requires FractureSettings.")
            from .fracture_export_service import export_fracture_usda_from_conversion_request

            result = export_fracture_usda_from_conversion_request(request.request, request.settings)
        elif request.action == FRACTURE_WORKER_ACTION_PREVIEW:
            if not isinstance(request.settings, FracturePreviewSettings):
                raise TypeError("Fracture preview worker requires FracturePreviewSettings.")
            from .fracture_preview_service import generate_fracture_preview_from_conversion_request

            result = generate_fracture_preview_from_conversion_request(request.request, request.settings)
        else:
            raise ValueError(f"Unsupported fracture worker action: {request.action}")
        write_fracture_worker_result(request.result_path, result)
        _cleanup_file(Path(request.error_path))
        return 0
    except Exception as exc:
        Path(request.error_path).write_text(
            json.dumps(
                {
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                }
            ),
            encoding="utf-8",
        )
        return 1


def read_fracture_worker_result(path: str | Path) -> "FractureExportResult | FracturePreviewResult | None":
    result_path = Path(path)
    if not result_path.exists():
        return None
    with result_path.open("rb") as handle:
        payload = pickle.load(handle)
    payload_type = type(payload)
    if payload_type.__module__ == "xml_to_usda.fracture_preview_service" and payload_type.__name__ == "FracturePreviewResult":
        return payload
    if payload_type.__module__ == "xml_to_usda.fracture_export_service" and payload_type.__name__ == "FractureExportResult":
        from .fracture_export_service import FractureExportResult

        if isinstance(payload, FractureExportResult):
            return payload
    raise TypeError("Invalid Fracture worker result payload.")


def write_fracture_worker_result(path: str | Path, result: object) -> None:
    result_path = Path(path)
    temp_path = result_path.with_name(f"{result_path.name}.tmp")
    try:
        with temp_path.open("wb") as handle:
            pickle.dump(result, handle, protocol=pickle.HIGHEST_PROTOCOL)
        temp_path.replace(result_path)
    except Exception:
        _cleanup_file(temp_path)
        _cleanup_file(result_path)
        raise


def _cleanup_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass
