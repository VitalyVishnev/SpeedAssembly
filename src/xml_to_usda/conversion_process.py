from __future__ import annotations

import multiprocessing
import pickle
import subprocess
import sys
import tempfile
import traceback
from dataclasses import dataclass
from queue import Empty
from pathlib import Path

from .job_control import apply_process_profile
from .models import ConversionJobResult, ConversionRequest
from .pipeline import convert_request
from .proxy_mesh_service import (
    ProxyMeshJobResult,
    ProxyMeshSettings,
)
from .proxy_mesh_worker_subprocess import (
    PROXY_MESH_WORKER_COMMAND,
    ProxyMeshWorkerRequest,
    read_proxy_mesh_worker_error,
    write_proxy_mesh_worker_request,
)
from .runtime_error_mode import suppress_windows_native_error_dialogs


def get_spawn_context() -> multiprocessing.context.BaseContext:
    return multiprocessing.get_context("spawn")


def start_conversion_process(
    request: ConversionRequest,
    *,
    runtime_paths,
):
    suppress_windows_native_error_dialogs()
    context = get_spawn_context()
    message_queue = context.Queue()
    cancel_event = context.Event()
    process = context.Process(
        target=_conversion_process_entry,
        kwargs={
            "request": request,
            "runtime_paths": runtime_paths,
            "message_queue": message_queue,
            "cancel_event": cancel_event,
        },
        daemon=False,
    )
    process.start()
    return process, message_queue, cancel_event


def start_proxy_mesh_process(
    request: ConversionRequest,
    settings: ProxyMeshSettings,
    *,
    action: str,
):
    suppress_windows_native_error_dialogs()
    request_path = _create_proxy_temp_path(".request.pkl")
    result_path = _create_proxy_temp_path(".result.pkl")
    error_path = _create_proxy_temp_path(".error.json")
    write_proxy_mesh_worker_request(
        request_path,
        ProxyMeshWorkerRequest(
            request=request,
            settings=settings,
            action=action,
            result_path=str(result_path),
            error_path=str(error_path),
        ),
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        _resolve_proxy_mesh_worker_command(request_path),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    return (
        _ProxyMeshWorkerProcess(process),
        _ProxyMeshWorkerQueue(request_path=request_path, result_path=result_path, error_path=error_path),
        _ProxyMeshCancelEvent(process),
    )


def drain_process_queue(message_queue) -> list[tuple[str, object]]:
    if hasattr(message_queue, "drain"):
        return message_queue.drain()
    events: list[tuple[str, object]] = []
    while True:
        try:
            events.append(message_queue.get_nowait())
        except Empty:
            break
    return events


def close_process_queue(message_queue) -> None:
    if message_queue is None:
        return
    if hasattr(message_queue, "drain"):
        message_queue.close()
        return
    try:
        message_queue.close()
    except Exception:
        pass
    try:
        message_queue.join_thread()
    except Exception:
        pass


def _conversion_process_entry(
    *,
    request: ConversionRequest,
    runtime_paths,
    message_queue,
    cancel_event,
) -> None:
    suppress_windows_native_error_dialogs()
    try:
        apply_process_profile(request.cpu_profile)
        result = convert_request(
            request,
            telemetry_callback=lambda telemetry: message_queue.put(("telemetry", telemetry)),
            cancel_event=cancel_event,
            runtime_paths=runtime_paths,
        )[0]
        message_queue.put(("result", ConversionJobResult(result=result)))
    except Exception as exc:
        message_queue.put(("error_traceback", traceback.format_exc()))
        message_queue.put(
            (
                "result",
                ConversionJobResult(
                    cancelled=bool(cancel_event.is_set()),
                    error_message=str(exc),
                ),
            )
        )


def _proxy_mesh_process_entry(
    *,
    request: ConversionRequest,
    settings: ProxyMeshSettings,
    action: str,
    message_queue,
    cancel_event,
) -> None:
    suppress_windows_native_error_dialogs()
    try:
        apply_process_profile(request.cpu_profile)
        if bool(cancel_event.is_set()):
            raise RuntimeError("Proxy mesh generation cancelled by user.")
        from .proxy_mesh_service import export_proxy_usda_from_request, generate_proxy_mesh_from_request

        if action == "preview":
            proxy = generate_proxy_mesh_from_request(request, settings)
            message_queue.put(("result", ProxyMeshJobResult(proxy=proxy)))
            return
        if action == "export":
            export = export_proxy_usda_from_request(request, settings)
            message_queue.put(("result", ProxyMeshJobResult(export=export)))
            return
        raise ValueError(f"Unsupported proxy mesh worker action: {action}")
    except Exception as exc:
        message_queue.put(("error_traceback", traceback.format_exc()))
        message_queue.put(
            (
                "result",
                ProxyMeshJobResult(
                    cancelled=bool(cancel_event.is_set()),
                    error_message=str(exc),
                ),
            )
        )

@dataclass
class _ProxyMeshWorkerProcess:
    process: subprocess.Popen

    @property
    def exitcode(self):
        return self.process.poll()

    def is_alive(self) -> bool:
        return self.process.poll() is None

    def join(self, timeout=None) -> None:
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return

    def terminate(self) -> None:
        self.process.terminate()


@dataclass
class _ProxyMeshCancelEvent:
    process: subprocess.Popen

    def is_set(self) -> bool:
        return False

    def set(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()


@dataclass
class _ProxyMeshWorkerQueue:
    request_path: Path
    result_path: Path
    error_path: Path
    delivered: bool = False

    def drain(self) -> list[tuple[str, object]]:
        if self.delivered:
            return []
        if self.error_path.exists():
            self.delivered = True
            message, formatted_traceback = read_proxy_mesh_worker_error(self.error_path)
            return [
                ("error_traceback", formatted_traceback),
                ("result", ProxyMeshJobResult(error_message=message)),
            ]
        if not self.result_path.exists():
            return []
        with self.result_path.open("rb") as handle:
            payload = pickle.load(handle)
        self.delivered = True
        return [("result", payload)]

    def close(self) -> None:
        for path in (self.request_path, self.result_path, self.error_path):
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass


def _create_proxy_temp_path(suffix: str) -> Path:
    handle = tempfile.NamedTemporaryFile(prefix="xml_to_usda_proxy_", suffix=suffix, delete=False)
    path = Path(handle.name)
    handle.close()
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass
    return path


def _resolve_proxy_mesh_worker_command(request_path: Path) -> list[str]:
    if bool(getattr(sys, "frozen", False)):
        worker_dir_executable = Path(sys.executable).parent / "XMLtoUSDAWorker" / "XMLtoUSDAWorker.exe"
        if worker_dir_executable.exists():
            return [str(worker_dir_executable), PROXY_MESH_WORKER_COMMAND, "--request", str(request_path)]
        worker_executable = Path(sys.executable).with_name("XMLtoUSDAWorker.exe")
        if worker_executable.exists():
            return [str(worker_executable), PROXY_MESH_WORKER_COMMAND, "--request", str(request_path)]
        return [sys.executable, PROXY_MESH_WORKER_COMMAND, "--request", str(request_path)]
    return [sys.executable, "-m", "xml_to_usda", PROXY_MESH_WORKER_COMMAND, "--request", str(request_path)]
