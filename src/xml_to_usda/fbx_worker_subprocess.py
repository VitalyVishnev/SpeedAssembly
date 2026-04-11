"""Explicit FBX worker subprocess protocol for frozen/package runs.

Layer: infrastructure.

Frozen packaged builds use this helper protocol instead of nested
`multiprocessing` spawn for heavy FBX imports. The worker exchange is file-based
so large geometry payloads do not travel through multiprocessing pipes or
queues, and the packaged executable can be launched in a minimal helper mode.
"""

from __future__ import annotations

import json
import pickle
import traceback
from dataclasses import dataclass
from pathlib import Path

from .fbx_adapter import load_fbx_geometry
from .models import CpuProfile

FBX_WORKER_COMMAND = "fbx-worker"


@dataclass(frozen=True)
class FbxWorkerRequest:
    fbx_path: str
    prototype_name: str
    cpu_profile: CpuProfile
    strict_vertex_colors: bool
    result_path: str
    error_path: str


def write_fbx_worker_request(path: str | Path, request: FbxWorkerRequest) -> None:
    Path(path).write_text(
        json.dumps(
            {
                "fbx_path": request.fbx_path,
                "prototype_name": request.prototype_name,
                "cpu_profile": request.cpu_profile.value,
                "strict_vertex_colors": request.strict_vertex_colors,
                "result_path": request.result_path,
                "error_path": request.error_path,
            }
        ),
        encoding="utf-8",
    )


def read_fbx_worker_request(path: str | Path) -> FbxWorkerRequest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return FbxWorkerRequest(
        fbx_path=str(payload["fbx_path"]),
        prototype_name=str(payload["prototype_name"]),
        cpu_profile=CpuProfile(str(payload["cpu_profile"])),
        strict_vertex_colors=bool(payload.get("strict_vertex_colors", False)),
        result_path=str(payload["result_path"]),
        error_path=str(payload["error_path"]),
    )


def read_fbx_worker_error(path: str | Path) -> tuple[str, str] | None:
    error_path = Path(path)
    if not error_path.exists():
        return None
    payload = json.loads(error_path.read_text(encoding="utf-8"))
    return str(payload.get("message", "")), str(payload.get("traceback", ""))


def run_fbx_worker_request_file(path: str | Path) -> int:
    request = read_fbx_worker_request(path)
    try:
        payload = load_fbx_geometry(
            request.fbx_path,
            request.prototype_name,
            cpu_profile=request.cpu_profile,
            strict_vertex_colors=request.strict_vertex_colors,
        )
        with Path(request.result_path).open("wb") as handle:
            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
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
