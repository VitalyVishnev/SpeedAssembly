"""File-based Proxy Mesh worker protocol.

Layer: infrastructure.

Proxy generation can touch large XML and geometry payloads. The GUI uses this
worker protocol so native crashes stay outside the UI process and mesh results
do not travel through multiprocessing queues.
"""

from __future__ import annotations

import json
import pickle
import traceback
from dataclasses import dataclass
from pathlib import Path

from .job_control import apply_process_profile
from .models import ConversionRequest
from .proxy_mesh_service import (
    ProxyMeshJobResult,
    ProxyMeshSettings,
    export_proxy_usda_from_request,
    generate_proxy_mesh_from_request,
)
from .runtime_error_mode import suppress_windows_native_error_dialogs


PROXY_MESH_WORKER_COMMAND = "proxy-mesh-worker"


@dataclass(frozen=True)
class ProxyMeshWorkerRequest:
    request: ConversionRequest
    settings: ProxyMeshSettings
    action: str
    result_path: str
    error_path: str


def write_proxy_mesh_worker_request(path: str | Path, request: ProxyMeshWorkerRequest) -> None:
    with Path(path).open("wb") as handle:
        pickle.dump(request, handle, protocol=pickle.HIGHEST_PROTOCOL)


def read_proxy_mesh_worker_request(path: str | Path) -> ProxyMeshWorkerRequest:
    with Path(path).open("rb") as handle:
        payload = pickle.load(handle)
    if not isinstance(payload, ProxyMeshWorkerRequest):
        raise TypeError("Invalid Proxy Mesh worker request payload.")
    return payload


def read_proxy_mesh_worker_error(path: str | Path) -> tuple[str, str] | None:
    error_path = Path(path)
    if not error_path.exists():
        return None
    payload = json.loads(error_path.read_text(encoding="utf-8"))
    return str(payload.get("message", "")), str(payload.get("traceback", ""))


def run_proxy_mesh_worker_request_file(path: str | Path) -> int:
    suppress_windows_native_error_dialogs()
    request = read_proxy_mesh_worker_request(path)
    try:
        apply_process_profile(request.request.cpu_profile)
        if request.action == "preview":
            result = ProxyMeshJobResult(
                proxy=generate_proxy_mesh_from_request(request.request, request.settings)
            )
        elif request.action == "export":
            result = ProxyMeshJobResult(
                export=export_proxy_usda_from_request(request.request, request.settings)
            )
        else:
            raise ValueError(f"Unsupported proxy mesh worker action: {request.action}")
        with Path(request.result_path).open("wb") as handle:
            pickle.dump(result, handle, protocol=pickle.HIGHEST_PROTOCOL)
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


def _cleanup_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass
