from __future__ import annotations

import multiprocessing
import shutil
import subprocess
import tempfile
import traceback
from dataclasses import dataclass, field
from queue import Empty
from pathlib import Path

from .job_control import apply_process_profile
from .models import ConversionJobResult, ConversionRequest
from .part_preview_service import PartPrototypePreviewRequest, PartPrototypePreviewSettings
from .part_preview_worker_subprocess import (
    PART_PREVIEW_WORKER_COMMAND,
    PartPreviewWorkerRequest,
    read_part_preview_worker_error,
    read_part_preview_worker_result,
    write_part_preview_worker_request,
)
from .pipeline import convert_request
from .conversion_worker_subprocess import (
    CONVERSION_WORKER_COMMAND,
    ConversionWorkerRequest,
    read_conversion_worker_error,
    write_conversion_worker_request,
)
from .fracture_service import FractureSettings
from .fracture_export_service import FractureExportRequest
from .fracture_preview_service import FracturePreviewSettings, FracturePreviewSourceRequest
from .fracture_worker_subprocess import (
    FRACTURE_WORKER_ACTION_EXPORT,
    FRACTURE_WORKER_ACTION_PREVIEW,
    FRACTURE_WORKER_COMMAND,
    FractureWorkerRequest,
    read_fracture_worker_error,
    read_fracture_worker_result,
    write_fracture_worker_request,
)
from .proxy_mesh_service import (
    ProxyMeshJobResult,
    ProxyMeshSettings,
    ProxyMeshSourceRequest,
)
from .proxy_mesh_worker_subprocess import (
    PROXY_MESH_WORKER_COMMAND,
    ProxyMeshWorkerRequest,
    read_proxy_mesh_worker_error,
    write_proxy_mesh_worker_request,
)
from .runtime_error_mode import suppress_windows_native_error_dialogs
from .worker_file_protocol import (
    cleanup_file,
    create_temp_path,
    new_worker_token,
    read_worker_payload,
    resolve_worker_command,
    worker_env,
)


def get_spawn_context() -> multiprocessing.context.BaseContext:
    return multiprocessing.get_context("spawn")


def start_conversion_process(
    request: ConversionRequest,
    *,
    runtime_paths,
):
    suppress_windows_native_error_dialogs()
    request_path = _create_conversion_temp_path(".request.json")
    result_path = _create_conversion_temp_path(".result.json")
    error_path = _create_conversion_temp_path(".error.json")
    stderr_path = _create_conversion_temp_path(".stderr.log")
    worker_token = new_worker_token()
    event_dir = Path(tempfile.mkdtemp(prefix="xml_to_usda_conversion_events_"))
    write_conversion_worker_request(
        request_path,
        ConversionWorkerRequest(
            request=request,
            runtime_paths=runtime_paths,
            result_path=str(result_path),
            error_path=str(error_path),
            event_dir=str(event_dir),
            worker_token=worker_token,
        ),
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with stderr_path.open("wb") as stderr_handle:
        process = subprocess.Popen(
            _resolve_conversion_worker_command(request_path),
            stdout=subprocess.DEVNULL,
            stderr=stderr_handle,
            creationflags=creation_flags,
            env=worker_env(worker_token),
        )
    return (
        _SubprocessWorkerProcess(process),
        _ConversionWorkerQueue(
            request_path=request_path,
            result_path=result_path,
            error_path=error_path,
            stderr_path=stderr_path,
            event_dir=event_dir,
        ),
        _SubprocessCancelEvent(process),
    )


def start_proxy_mesh_process(
    request: ProxyMeshSourceRequest,
    settings: ProxyMeshSettings,
    *,
    action: str,
):
    suppress_windows_native_error_dialogs()
    request_path = _create_proxy_temp_path(".request.json")
    result_path = _create_proxy_temp_path(".result.json")
    error_path = _create_proxy_temp_path(".error.json")
    stderr_path = _create_proxy_temp_path(".stderr.log")
    worker_token = new_worker_token()
    write_proxy_mesh_worker_request(
        request_path,
        ProxyMeshWorkerRequest(
            request=request,
            settings=settings,
            action=action,
            result_path=str(result_path),
            error_path=str(error_path),
            worker_token=worker_token,
        ),
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with stderr_path.open("wb") as stderr_handle:
        process = subprocess.Popen(
            _resolve_proxy_mesh_worker_command(request_path),
            stdout=subprocess.DEVNULL,
            stderr=stderr_handle,
            creationflags=creation_flags,
            env=worker_env(worker_token),
        )
    return (
        _SubprocessWorkerProcess(process),
        _ProxyMeshWorkerQueue(
            request_path=request_path,
            result_path=result_path,
            error_path=error_path,
            stderr_path=stderr_path,
        ),
        _SubprocessCancelEvent(process),
    )


def start_fracture_export_process(
    request: FractureExportRequest,
    settings: FractureSettings,
):
    return _start_fracture_worker_process(request, settings, action=FRACTURE_WORKER_ACTION_EXPORT)


def start_fracture_preview_process(
    request: FracturePreviewSourceRequest,
    settings: FracturePreviewSettings,
):
    return _start_fracture_worker_process(request, settings, action=FRACTURE_WORKER_ACTION_PREVIEW)


def start_part_preview_process(
    request: PartPrototypePreviewRequest,
    settings: PartPrototypePreviewSettings,
):
    suppress_windows_native_error_dialogs()
    request_path = _create_part_preview_temp_path(".request.json")
    result_path = _create_part_preview_temp_path(".result.json")
    error_path = _create_part_preview_temp_path(".error.json")
    stderr_path = _create_part_preview_temp_path(".stderr.log")
    worker_token = new_worker_token()
    write_part_preview_worker_request(
        request_path,
        PartPreviewWorkerRequest(
            request=request,
            settings=settings,
            result_path=str(result_path),
            error_path=str(error_path),
            worker_token=worker_token,
        ),
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with stderr_path.open("wb") as stderr_handle:
        process = subprocess.Popen(
            _resolve_part_preview_worker_command(request_path),
            stdout=subprocess.DEVNULL,
            stderr=stderr_handle,
            creationflags=creation_flags,
            env=worker_env(worker_token),
        )
    return (
        _SubprocessWorkerProcess(process),
        _PartPreviewWorkerQueue(
            request_path=request_path,
            result_path=result_path,
            error_path=error_path,
            stderr_path=stderr_path,
        ),
        _SubprocessCancelEvent(process),
    )


def _start_fracture_worker_process(
    request: FractureExportRequest | FracturePreviewSourceRequest,
    settings: FractureSettings | FracturePreviewSettings,
    *,
    action: str,
):
    suppress_windows_native_error_dialogs()
    request_path = _create_fracture_temp_path(".request.json")
    result_path = _create_fracture_temp_path(".result.json")
    error_path = _create_fracture_temp_path(".error.json")
    stderr_path = _create_fracture_temp_path(".stderr.log")
    worker_token = new_worker_token()
    write_fracture_worker_request(
        request_path,
        FractureWorkerRequest(
            request=request,
            settings=settings,
            action=action,
            result_path=str(result_path),
            error_path=str(error_path),
            worker_token=worker_token,
        ),
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with stderr_path.open("wb") as stderr_handle:
        process = subprocess.Popen(
            _resolve_fracture_worker_command(request_path),
            stdout=subprocess.DEVNULL,
            stderr=stderr_handle,
            creationflags=creation_flags,
            env=worker_env(worker_token),
        )
    return (
        _SubprocessWorkerProcess(process),
        _FractureWorkerQueue(
            request_path=request_path,
            result_path=result_path,
            error_path=error_path,
            stderr_path=stderr_path,
        ),
        _SubprocessCancelEvent(process),
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
    request: ProxyMeshSourceRequest,
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
        from .proxy_mesh_service import export_proxy_usda_from_source_request, generate_proxy_mesh_from_source_request

        if action == "preview":
            proxy = generate_proxy_mesh_from_source_request(request, settings)
            message_queue.put(("result", ProxyMeshJobResult(proxy=proxy)))
            return
        if action == "export":
            export = export_proxy_usda_from_source_request(request, settings)
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
class _SubprocessWorkerProcess:
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
class _SubprocessCancelEvent:
    process: subprocess.Popen

    def is_set(self) -> bool:
        return False

    def set(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()


@dataclass
class _ConversionWorkerQueue:
    request_path: Path
    result_path: Path
    error_path: Path
    stderr_path: Path
    event_dir: Path
    delivered_events: set[str] = field(default_factory=set)
    delivered_result: bool = False

    def drain(self) -> list[tuple[str, object]]:
        events: list[tuple[str, object]] = []
        for event_path in sorted(self.event_dir.glob("*.event.json")):
            event_name = event_path.name
            if event_name in self.delivered_events:
                continue
            events.append(read_worker_payload(event_path))
            self.delivered_events.add(event_name)

        if self.delivered_result:
            return events
        if self.error_path.exists():
            self.delivered_result = True
            message, formatted_traceback = read_conversion_worker_error(self.error_path)
            result = _read_conversion_job_result(self.result_path, fallback_error_message=message)
            return events + [
                ("error_traceback", formatted_traceback),
                ("result", result),
            ]
        if not self.result_path.exists():
            return events
        self.delivered_result = True
        return events + [("result", _read_conversion_job_result(self.result_path))]

    def close(self) -> None:
        for path in (self.request_path, self.result_path, self.error_path, self.stderr_path):
            try:
                cleanup_file(path)
            except Exception:
                pass
        try:
            shutil.rmtree(self.event_dir)
        except FileNotFoundError:
            pass
        except Exception:
            pass


@dataclass
class _ProxyMeshWorkerQueue:
    request_path: Path
    result_path: Path
    error_path: Path
    stderr_path: Path
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
        payload = read_worker_payload(self.result_path)
        self.delivered = True
        return [("result", payload)]

    def close(self) -> None:
        for path in (self.request_path, self.result_path, self.error_path, self.stderr_path):
            try:
                cleanup_file(path)
            except Exception:
                pass


@dataclass
class _FractureWorkerQueue:
    request_path: Path
    result_path: Path
    error_path: Path
    stderr_path: Path
    delivered: bool = False

    def drain(self) -> list[tuple[str, object]]:
        if self.delivered:
            return []
        if self.error_path.exists():
            self.delivered = True
            message, formatted_traceback = read_fracture_worker_error(self.error_path)
            return [
                ("error_traceback", formatted_traceback),
                ("error", message),
            ]
        if not self.result_path.exists():
            return []
        self.delivered = True
        return [("result", read_fracture_worker_result(self.result_path))]

    def close(self) -> None:
        for path in (self.request_path, self.result_path, self.error_path, self.stderr_path):
            try:
                cleanup_file(path)
            except Exception:
                pass


@dataclass
class _PartPreviewWorkerQueue:
    request_path: Path
    result_path: Path
    error_path: Path
    stderr_path: Path
    delivered: bool = False

    def drain(self) -> list[tuple[str, object]]:
        if self.delivered:
            return []
        if self.error_path.exists():
            self.delivered = True
            message, formatted_traceback = read_part_preview_worker_error(self.error_path)
            return [
                ("error_traceback", formatted_traceback),
                ("error", message),
            ]
        if not self.result_path.exists():
            return []
        self.delivered = True
        return [("result", read_part_preview_worker_result(self.result_path))]

    def close(self) -> None:
        for path in (self.request_path, self.result_path, self.error_path, self.stderr_path):
            try:
                cleanup_file(path)
            except Exception:
                pass


def _create_proxy_temp_path(suffix: str) -> Path:
    return _create_temp_path("xml_to_usda_proxy_", suffix)


def _create_conversion_temp_path(suffix: str) -> Path:
    return _create_temp_path("xml_to_usda_conversion_", suffix)


def _create_fracture_temp_path(suffix: str) -> Path:
    return _create_temp_path("xml_to_usda_fracture_", suffix)


def _create_part_preview_temp_path(suffix: str) -> Path:
    return _create_temp_path("xml_to_usda_part_preview_", suffix)


def _create_temp_path(prefix: str, suffix: str) -> Path:
    return create_temp_path(prefix, suffix)


def _read_conversion_job_result(path: Path, *, fallback_error_message: str = "") -> ConversionJobResult:
    if not path.exists():
        return ConversionJobResult(
            error_message=fallback_error_message or "Conversion worker finished without a result."
        )
    payload = read_worker_payload(path)
    if isinstance(payload, ConversionJobResult):
        return payload
    return ConversionJobResult(error_message="Conversion worker returned an invalid result payload.")


def _resolve_conversion_worker_command(request_path: Path) -> list[str]:
    return resolve_worker_command(CONVERSION_WORKER_COMMAND, request_path)


def _resolve_proxy_mesh_worker_command(request_path: Path) -> list[str]:
    return resolve_worker_command(PROXY_MESH_WORKER_COMMAND, request_path)


def _resolve_fracture_worker_command(request_path: Path) -> list[str]:
    return resolve_worker_command(FRACTURE_WORKER_COMMAND, request_path)


def _resolve_part_preview_worker_command(request_path: Path) -> list[str]:
    return resolve_worker_command(PART_PREVIEW_WORKER_COMMAND, request_path)
