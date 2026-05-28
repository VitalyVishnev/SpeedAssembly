"""Unified FBX helper-process supervision for launcher and packaged runs.

Layer: infrastructure.

This module owns the runtime strategy for explicit FBX prototype imports. The
FBX import semantics themselves still live in `fbx_adapter`; the supervisor
only decides how many isolated helpers to launch, how to exchange payloads,
and how to recover from native helper crashes by reducing concurrency.

The supervisor intentionally starts from the requested runtime concurrency
instead of applying a proactive size-based cap. Heavy files must go through
the same fast path first and only downgrade when the current runtime shows
evidence that a lower helper count is required.
"""

from __future__ import annotations

import os
import pickle
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .fbx_worker_subprocess import (
    FBX_WORKER_COMMAND,
    FbxWorkerRequest,
    read_fbx_worker_error,
    write_fbx_worker_request,
)
from .job_control import cpu_worker_count, emit_telemetry, throw_if_cancelled
from .models import ConversionPhase, CpuProfile

@dataclass(frozen=True)
class FbxImportTask:
    task_id: int
    display_name: str
    prototype_name: str
    fbx_path: str
    cpu_profile: CpuProfile
    strict_vertex_colors: bool = False
    read_vertex_colors: bool = True
    read_material_slots: bool = True


@dataclass(frozen=True)
class _RunningHelper:
    process: subprocess.Popen
    task: FbxImportTask
    request_path: Path
    result_path: Path
    error_path: Path


class _NativeHelperCrash(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        partial_results: dict[int, object],
        remaining_tasks: tuple[FbxImportTask, ...],
    ) -> None:
        super().__init__(message)
        self.partial_results = partial_results
        self.remaining_tasks = remaining_tasks


def import_fbx_payloads(
    tasks: tuple[FbxImportTask, ...],
    *,
    cpu_profile: CpuProfile,
    telemetry_callback=None,
    cancel_event=None,
    started_at: float | None = None,
) -> dict[int, object]:
    if not tasks:
        return {}

    requested_worker_count = min(len(tasks), max(1, cpu_worker_count(cpu_profile)))
    worker_count = _resolve_initial_worker_count(tasks, requested_worker_count)

    resolved_payloads: dict[int, object] = {}
    pending_tasks = tasks
    current_worker_count = worker_count

    while pending_tasks:
        emit_telemetry(
            telemetry_callback,
            ConversionPhase.FBX_IMPORT,
            completed_units=len(resolved_payloads),
            total_units=len(tasks),
            message=(
                f"Importing {len(pending_tasks)} FBX prototype(s) via isolated helper subprocesses "
                f"using {current_worker_count} process(es)."
            ),
            started_at=started_at,
        )
        try:
            batch_results = _run_import_batch(
                pending_tasks,
                worker_count=current_worker_count,
                telemetry_callback=telemetry_callback,
                cancel_event=cancel_event,
                started_at=started_at,
                completed_offset=len(resolved_payloads),
                total_units=len(tasks),
            )
            resolved_payloads.update(batch_results)
            break
        except _NativeHelperCrash as exc:
            resolved_payloads.update(exc.partial_results)
            pending_tasks = exc.remaining_tasks
            if current_worker_count <= 1:
                raise RuntimeError(str(exc)) from exc
            next_worker_count = max(1, current_worker_count - 1)
            emit_telemetry(
                telemetry_callback,
                ConversionPhase.FBX_IMPORT,
                completed_units=len(resolved_payloads),
                total_units=len(tasks),
                message=(
                    f"FBX helper subprocess crashed at concurrency {current_worker_count}. "
                    f"Retrying remaining {len(pending_tasks)} import(s) with {next_worker_count} process(es)."
                ),
                started_at=started_at,
            )
            current_worker_count = next_worker_count
    return resolved_payloads


def _resolve_initial_worker_count(
    tasks: tuple[FbxImportTask, ...],
    requested_worker_count: int,
) -> int:
    if requested_worker_count <= 1 or len(tasks) <= 1:
        return 1
    return requested_worker_count


def _run_import_batch(
    tasks: tuple[FbxImportTask, ...],
    *,
    worker_count: int,
    telemetry_callback=None,
    cancel_event=None,
    started_at: float | None = None,
    completed_offset: int,
    total_units: int,
) -> dict[int, object]:
    pending_tasks = list(tasks)
    active: dict[int, _RunningHelper] = {}
    resolved_payloads: dict[int, object] = {}

    try:
        while pending_tasks and len(active) < worker_count:
            helper = _launch_helper(pending_tasks.pop(0))
            active[helper.process.pid] = helper

        while active:
            throw_if_cancelled(cancel_event)
            finished_processes: list[int] = []
            for process_id, helper in list(active.items()):
                exit_code = helper.process.poll()
                if exit_code is None:
                    continue
                try:
                    resolved_payloads[helper.task.task_id] = _finalize_helper(helper, exit_code=exit_code)
                except _NativeHelperCrash:
                    raise
                except Exception as exc:
                    raise RuntimeError(f"FBX import failed for {helper.task.display_name}: {exc}") from exc
                emit_telemetry(
                    telemetry_callback,
                    ConversionPhase.FBX_IMPORT,
                    completed_units=completed_offset + len(resolved_payloads),
                    total_units=total_units,
                    message=f"Imported FBX {helper.task.display_name}.",
                    started_at=started_at,
                )
                finished_processes.append(process_id)

            for process_id in finished_processes:
                active.pop(process_id, None)
                if pending_tasks:
                    helper = _launch_helper(pending_tasks.pop(0))
                    active[helper.process.pid] = helper

            if active and not finished_processes:
                time.sleep(0.05)
    except _NativeHelperCrash as exc:
        remaining_tasks = list(exc.remaining_tasks) + pending_tasks
        for helper in active.values():
            if helper.task.task_id not in exc.partial_results and helper.task.task_id not in {
                task.task_id for task in remaining_tasks
            }:
                remaining_tasks.append(helper.task)
        raise _NativeHelperCrash(
            str(exc),
            partial_results=resolved_payloads | exc.partial_results,
            remaining_tasks=tuple(remaining_tasks),
        ) from exc
    finally:
        for helper in active.values():
            _terminate_helper(helper)
    return resolved_payloads


def _launch_helper(task: FbxImportTask) -> _RunningHelper:
    request_path = _create_temp_path(".request.json")
    result_path = _create_temp_path(".payload.pkl")
    error_path = _create_temp_path(".error.json")
    write_fbx_worker_request(
        request_path,
        FbxWorkerRequest(
            fbx_path=task.fbx_path,
            prototype_name=task.prototype_name,
            cpu_profile=task.cpu_profile,
            strict_vertex_colors=task.strict_vertex_colors,
            read_vertex_colors=task.read_vertex_colors,
            read_material_slots=task.read_material_slots,
            result_path=str(result_path),
            error_path=str(error_path),
        ),
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        _resolve_helper_command(request_path),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    return _RunningHelper(
        process=process,
        task=task,
        request_path=request_path,
        result_path=result_path,
        error_path=error_path,
    )


def _resolve_helper_command(request_path: Path) -> list[str]:
    if bool(getattr(sys, "frozen", False)):
        worker_dir_executable = Path(sys.executable).parent / "XMLtoUSDAWorker" / "XMLtoUSDAWorker.exe"
        if worker_dir_executable.exists():
            return [str(worker_dir_executable), FBX_WORKER_COMMAND, "--request", str(request_path)]
        worker_executable = Path(sys.executable).with_name("XMLtoUSDAWorker.exe")
        if worker_executable.exists():
            return [str(worker_executable), FBX_WORKER_COMMAND, "--request", str(request_path)]
        return [sys.executable, FBX_WORKER_COMMAND, "--request", str(request_path)]
    return [sys.executable, "-m", "xml_to_usda", FBX_WORKER_COMMAND, "--request", str(request_path)]


def _finalize_helper(helper: _RunningHelper, *, exit_code: int):
    try:
        if exit_code != 0:
            error_payload = read_fbx_worker_error(helper.error_path)
            if error_payload is not None:
                error_message, formatted_traceback = error_payload
                raise RuntimeError(f"{error_message}\n{formatted_traceback.strip()}")
            raise _NativeHelperCrash(
                (
                    "FBX helper subprocess crashed while importing "
                    f"{helper.task.display_name} from {helper.task.fbx_path} (exit code {exit_code})."
                ),
                partial_results={},
                remaining_tasks=(helper.task,),
            )
        if not helper.result_path.exists():
            error_payload = read_fbx_worker_error(helper.error_path)
            if error_payload is not None:
                error_message, formatted_traceback = error_payload
                raise RuntimeError(f"{error_message}\n{formatted_traceback.strip()}")
            raise _NativeHelperCrash(
                (
                    "FBX helper subprocess exited without returning a payload file for "
                    f"{helper.task.display_name}."
                ),
                partial_results={},
                remaining_tasks=(helper.task,),
            )
        return _load_payload_file(helper.result_path)
    finally:
        _cleanup_temp_path(helper.request_path)
        _cleanup_temp_path(helper.result_path)
        _cleanup_temp_path(helper.error_path)


def _terminate_helper(helper: _RunningHelper) -> None:
    try:
        if helper.process.poll() is None:
            helper.process.terminate()
            helper.process.wait(timeout=1.0)
    except Exception:
        pass
    _cleanup_temp_path(helper.request_path)
    _cleanup_temp_path(helper.result_path)
    _cleanup_temp_path(helper.error_path)


def _create_temp_path(suffix: str) -> Path:
    file_descriptor, raw_path = tempfile.mkstemp(prefix="xml_to_usda_fbx_helper_", suffix=suffix)
    os.close(file_descriptor)
    path = Path(raw_path)
    _cleanup_temp_path(path)
    return path


def _cleanup_temp_path(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def _load_payload_file(path: Path) -> object:
    try:
        with path.open("rb") as handle:
            return pickle.load(handle)
    finally:
        _cleanup_temp_path(path)
