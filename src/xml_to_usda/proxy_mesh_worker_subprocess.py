"""File-based Proxy Mesh worker protocol.

Layer: infrastructure.

Proxy generation can touch large XML and geometry payloads. The GUI uses this
worker protocol so native crashes stay outside the UI process and mesh results
do not travel through multiprocessing queues.
"""

from __future__ import annotations

import faulthandler
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

from .job_control import apply_process_profile
from .proxy_mesh_service import (
    ProxyMeshJobResult,
    ProxyMeshSettings,
    ProxyMeshSourceRequest,
    export_proxy_usda_from_source_request,
    generate_proxy_collision_meshes_from_source_request,
    generate_proxy_preview_from_source_request,
)
from .runtime_error_mode import suppress_windows_native_error_dialogs
from .worker_commands import PROXY_MESH_WORKER_COMMAND
from .worker_file_protocol import (
    cleanup_file,
    read_error_payload,
    read_worker_payload,
    validate_worker_token,
    write_error_payload,
    write_worker_payload_atomic,
)


@dataclass(frozen=True)
class ProxyMeshWorkerRequest:
    request: ProxyMeshSourceRequest
    settings: ProxyMeshSettings
    action: str
    result_path: str
    error_path: str
    worker_token: str


def write_proxy_mesh_worker_request(path: str | Path, request: ProxyMeshWorkerRequest) -> None:
    write_worker_payload_atomic(path, request)


def read_proxy_mesh_worker_request(path: str | Path) -> ProxyMeshWorkerRequest:
    payload = read_worker_payload(path)
    if not isinstance(payload, ProxyMeshWorkerRequest):
        raise TypeError("Invalid Proxy Mesh worker request payload.")
    return payload


def read_proxy_mesh_worker_error(path: str | Path) -> tuple[str, str] | None:
    return read_error_payload(path)


def run_proxy_mesh_worker_request_file(path: str | Path) -> int:
    suppress_windows_native_error_dialogs()
    try:
        faulthandler.enable(file=sys.stderr, all_threads=True)
    except Exception:
        pass
    _worker_stage("request.read.start")
    request = read_proxy_mesh_worker_request(path)
    try:
        validate_worker_token(request.worker_token)
        _worker_stage(f"{request.action}.profile.start")
        apply_process_profile(request.request.cpu_profile)
        if request.action == "preview":
            _worker_stage(
                "preview.generate.start",
                final_polycount=request.settings.final_polycount,
                density_resolution=request.settings.density_resolution,
                fuse_base_mesh_vertices=request.settings.fuse_base_mesh_vertices,
                branch_prune_aggression=request.settings.branch_prune_aggression,
                method=request.settings.method,
            )
            result = ProxyMeshJobResult(
                proxy=generate_proxy_preview_from_source_request(request.request, request.settings)
            )
            _worker_stage("preview.generate.end")
        elif request.action == "collision":
            _worker_stage("collision.generate.start")
            result = ProxyMeshJobResult(
                collision_meshes=generate_proxy_collision_meshes_from_source_request(
                    request.request,
                    request.settings.collision,
                )
            )
            _worker_stage("collision.generate.end")
        elif request.action == "export":
            _worker_stage(
                "export.generate.start",
                final_polycount=request.settings.final_polycount,
                density_resolution=request.settings.density_resolution,
                fuse_base_mesh_vertices=request.settings.fuse_base_mesh_vertices,
                branch_prune_aggression=request.settings.branch_prune_aggression,
                method=request.settings.method,
            )
            result = ProxyMeshJobResult(
                export=export_proxy_usda_from_source_request(request.request, request.settings)
            )
            _worker_stage("export.generate.end")
        else:
            raise ValueError(f"Unsupported proxy mesh worker action: {request.action}")
        _worker_stage("result.write.start")
        write_worker_payload_atomic(request.result_path, result)
        _worker_stage("result.write.end")
        cleanup_file(request.error_path)
        return 0
    except Exception as exc:
        _worker_stage("error.write.start", error_type=type(exc).__name__, message=str(exc))
        write_error_payload(request.error_path, message=str(exc), formatted_traceback=traceback.format_exc())
        return 1


def _worker_stage(stage: str, **fields: object) -> None:
    details = " ".join(f"{key}={value}" for key, value in sorted(fields.items()))
    suffix = f" {details}" if details else ""
    print(f"proxy-mesh-worker stage={stage}{suffix}", file=sys.stderr, flush=True)
