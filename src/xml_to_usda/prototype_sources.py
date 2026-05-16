"""Prototype Source infrastructure adapters and retained compatibility bridges.

Layer: infrastructure with light application-facing compatibility helpers.

This module owns Prototype Source config loading and FBX payload loading.
Resolved Prototype matching lives in `prototype_resolution`.
"""

from __future__ import annotations

import multiprocessing
import os
import pickle
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
import json
from dataclasses import dataclass
from pathlib import Path
import tempfile
import traceback

from .fbx_adapter import load_fbx_geometry
from .fbx_import_supervisor import FbxImportTask, import_fbx_payloads
from .fbx_worker_subprocess import (
    FBX_WORKER_COMMAND,
    FbxWorkerRequest,
    read_fbx_worker_error,
    write_fbx_worker_request,
)
from .job_control import cpu_worker_count, emit_telemetry, throw_if_cancelled
from .models import (
    CanonicalTreeModel,
    ConversionPhase,
    CpuProfile,
    FbxMaterialMode,
    FbxMaterialSlotOverride,
    PrototypeSourceConfig,
    PrototypeSourceMode,
)
from .prototype_resolution import (
    _PreparedFbxImport,
    merge_legacy_part_mesh_configs,
    resolve_prototype_sources,
)


@dataclass(frozen=True)
class _FrozenFbxHelperProcess:
    process: subprocess.Popen
    prepared_import: _PreparedFbxImport
    request_path: Path
    result_path: Path
    error_path: Path


_FROZEN_HUGE_FBX_MAX_BYTES = 350 * 1024 * 1024
_FROZEN_HUGE_FBX_TOTAL_BYTES = 700 * 1024 * 1024


def load_prototype_source_configs_from_json(path: str) -> tuple[PrototypeSourceConfig, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Part source config JSON must be an object keyed by prototype name or Mesh_<id>.")

    configs: list[PrototypeSourceConfig] = []
    for raw_key, raw_value in payload.items():
        if not isinstance(raw_value, dict):
            raise ValueError(f"Part source config for {raw_key!r} must be an object.")
        mode = PrototypeSourceMode(str(raw_value.get("mode", PrototypeSourceMode.XML_MESH.value)))
        configs.append(
            PrototypeSourceConfig(
                source_key=str(raw_key),
                source_name=str(raw_value.get("source_name", "")),
                mode=mode,
                fbx_material_mode=FbxMaterialMode(
                    str(raw_value.get("fbx_material_mode", FbxMaterialMode.AUTO.value))
                ),
                asset_path=_coerce_optional_string(raw_value.get("asset_path")),
                fbx_path=_coerce_optional_string(raw_value.get("fbx_path")),
                single_material_path=_coerce_optional_string(raw_value.get("single_material_path")),
                black_material_path=_coerce_optional_string(raw_value.get("black_material_path")),
                white_material_path=_coerce_optional_string(raw_value.get("white_material_path")),
                fbx_material_slot_overrides=_load_fbx_material_slot_overrides(
                    raw_value.get("fbx_material_slot_overrides")
                ),
            )
        )
    return tuple(configs)


def apply_prototype_source_configs(
    model: CanonicalTreeModel,
    prototype_source_configs: tuple[PrototypeSourceConfig, ...],
    *,
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
    telemetry_callback=None,
    cancel_event=None,
    started_at: float | None = None,
) -> CanonicalTreeModel:
    """Compatibility wrapper for older callers importing from prototype_sources."""
    return resolve_prototype_sources(
        model,
        prototype_source_configs,
        cpu_profile=cpu_profile,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
        started_at=started_at,
        payload_loader=load_fbx_payloads_for_prototype_resolution,
    )


def load_fbx_payloads_for_prototype_resolution(
    prepared_imports: tuple[_PreparedFbxImport, ...],
    *,
    cpu_profile: CpuProfile,
    telemetry_callback=None,
    cancel_event=None,
    started_at: float | None = None,
):
    """Infrastructure adapter for Prototype Source FBX payload loading."""
    return _load_fbx_payloads(
        prepared_imports,
        cpu_profile=cpu_profile,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
        started_at=started_at,
    )


def _coerce_optional_string(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _load_fbx_material_slot_overrides(raw_value) -> tuple[FbxMaterialSlotOverride, ...]:
    if raw_value is None or raw_value == "":
        return ()
    if not isinstance(raw_value, list):
        raise ValueError("fbx_material_slot_overrides must be a list of objects.")
    overrides: list[FbxMaterialSlotOverride] = []
    seen_names: set[str] = set()
    for raw_override in raw_value:
        if not isinstance(raw_override, dict):
            raise ValueError("Each FBX material slot override must be an object.")
        slot_name = _coerce_optional_string(raw_override.get("slot_name"))
        if not slot_name:
            raise ValueError("FBX material slot override is missing slot_name.")
        if slot_name in seen_names:
            raise ValueError(f"Duplicate FBX material slot override for {slot_name}.")
        seen_names.add(slot_name)
        overrides.append(
            FbxMaterialSlotOverride(
                slot_name=slot_name,
                ue_asset_path=_coerce_optional_string(raw_override.get("ue_asset_path")),
            )
        )
    return tuple(overrides)


def _load_fbx_payloads(
    prepared_imports: tuple[_PreparedFbxImport, ...],
    *,
    cpu_profile: CpuProfile,
    telemetry_callback=None,
    cancel_event=None,
    started_at: float | None = None,
):
    if not prepared_imports:
        return {}

    tasks = tuple(
        FbxImportTask(
            task_id=prepared_import.prototype_index,
            display_name=prepared_import.resolved_source_name,
            prototype_name=prepared_import.resolved_identity.prim_name,
            fbx_path=prepared_import.config.fbx_path or "",
            cpu_profile=cpu_profile,
            strict_vertex_colors=(
                prepared_import.config.fbx_material_mode == FbxMaterialMode.VERTEX_COLOR_SPLIT
            ),
        )
        for prepared_import in prepared_imports
    )
    return import_fbx_payloads(
        tasks,
        cpu_profile=cpu_profile,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
        started_at=started_at,
    )


def _frozen_runtime_requires_isolated_fbx_import() -> bool:
    return bool(getattr(sys, "frozen", False))


def _resolve_frozen_fbx_worker_count(
    prepared_imports: tuple[_PreparedFbxImport, ...],
    *,
    cpu_profile: CpuProfile,
) -> tuple[int, str | None]:
    requested_worker_count = min(len(prepared_imports), max(1, cpu_worker_count(cpu_profile)))
    if requested_worker_count <= 1 or len(prepared_imports) <= 1:
        return 1, None

    input_sizes = _collect_prepared_fbx_input_sizes(prepared_imports)
    if input_sizes:
        if max(input_sizes) >= _FROZEN_HUGE_FBX_MAX_BYTES or sum(input_sizes) >= _FROZEN_HUGE_FBX_TOTAL_BYTES:
            return (
                1,
                (
                    "Large packaged FBX replacements exceed the verified safe frozen parallel threshold. "
                    "Using 1 helper process to avoid Autodesk FBX SDK crashes on monster payloads."
                ),
            )
    return requested_worker_count, None


def _collect_prepared_fbx_input_sizes(prepared_imports: tuple[_PreparedFbxImport, ...]) -> tuple[int, ...]:
    sizes: list[int] = []
    for prepared_import in prepared_imports:
        try:
            sizes.append(Path(prepared_import.config.fbx_path or "").stat().st_size)
        except OSError:
            continue
    return tuple(sizes)


def _load_fbx_payloads_frozen(
    prepared_imports: tuple[_PreparedFbxImport, ...],
    *,
    cpu_profile: CpuProfile,
    telemetry_callback=None,
    cancel_event=None,
    started_at: float | None = None,
):
    worker_count, worker_count_warning = _resolve_frozen_fbx_worker_count(
        prepared_imports,
        cpu_profile=cpu_profile,
    )
    if worker_count_warning:
        emit_telemetry(
            telemetry_callback,
            ConversionPhase.FBX_IMPORT,
            completed_units=0,
            total_units=len(prepared_imports),
            message=worker_count_warning,
            started_at=started_at,
        )
    if worker_count <= 1 or len(prepared_imports) <= 1:
        emit_telemetry(
            telemetry_callback,
            ConversionPhase.FBX_IMPORT,
            completed_units=0,
            total_units=len(prepared_imports),
            message=f"Importing {len(prepared_imports)} FBX prototype(s) in 1 isolated frozen helper process.",
            started_at=started_at,
        )
        return _load_fbx_payloads_frozen_subprocess(
            prepared_imports,
            cpu_profile=cpu_profile,
            worker_count=1,
            telemetry_callback=telemetry_callback,
            cancel_event=cancel_event,
            started_at=started_at,
        )
    emit_telemetry(
        telemetry_callback,
        ConversionPhase.FBX_IMPORT,
        completed_units=0,
        total_units=len(prepared_imports),
        message=(
            f"Importing {len(prepared_imports)} FBX prototype(s) in isolated frozen helper processes "
            f"using {worker_count} process(es)."
        ),
        started_at=started_at,
    )
    return _load_fbx_payloads_frozen_subprocess(
        prepared_imports,
        cpu_profile=cpu_profile,
        worker_count=worker_count,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
        started_at=started_at,
    )


def _load_fbx_payloads_frozen_subprocess(
    prepared_imports: tuple[_PreparedFbxImport, ...],
    *,
    cpu_profile: CpuProfile,
    worker_count: int,
    telemetry_callback=None,
    cancel_event=None,
    started_at: float | None = None,
):
    pending = list(prepared_imports)
    active: dict[int, _FrozenFbxHelperProcess] = {}
    resolved_payloads: dict[int, object] = {}
    completed = 0

    try:
        while pending and len(active) < worker_count:
            launched = _launch_frozen_fbx_helper_process(pending.pop(0), cpu_profile=cpu_profile)
            active[launched.process.pid] = launched

        while active:
            throw_if_cancelled(cancel_event)
            finished_pids: list[int] = []
            for process_pid, launched in list(active.items()):
                exit_code = launched.process.poll()
                if exit_code is None:
                    continue
                try:
                    resolved_payloads[launched.prepared_import.prototype_index] = _finalize_frozen_fbx_helper_process(
                        launched,
                        exit_code=exit_code,
                    )
                except Exception as exc:
                    raise RuntimeError(
                        f"FBX import failed for {launched.prepared_import.resolved_source_name}: {exc}"
                    ) from exc
                completed += 1
                emit_telemetry(
                    telemetry_callback,
                    ConversionPhase.FBX_IMPORT,
                    completed_units=completed,
                    total_units=len(prepared_imports),
                    message=f"Imported FBX {launched.prepared_import.resolved_source_name}.",
                    started_at=started_at,
                )
                finished_pids.append(process_pid)

            for process_pid in finished_pids:
                active.pop(process_pid, None)
                if pending:
                    launched = _launch_frozen_fbx_helper_process(pending.pop(0), cpu_profile=cpu_profile)
                    active[launched.process.pid] = launched

            if active and not finished_pids:
                time.sleep(0.05)
    finally:
        for launched in active.values():
            _terminate_frozen_fbx_helper_process(launched)
    return resolved_payloads


def _launch_frozen_fbx_helper_process(
    prepared_import: _PreparedFbxImport,
    *,
    cpu_profile: CpuProfile,
) -> _FrozenFbxHelperProcess:
    request_path = _create_isolated_fbx_result_path().with_suffix(".request.json")
    result_path = _create_isolated_fbx_result_path()
    error_path = _create_isolated_fbx_result_path().with_suffix(".error.json")
    _cleanup_isolated_fbx_result_file(request_path)
    _cleanup_isolated_fbx_result_file(error_path)
    write_fbx_worker_request(
        request_path,
        FbxWorkerRequest(
            fbx_path=prepared_import.config.fbx_path or "",
            prototype_name=prepared_import.resolved_identity.prim_name,
            cpu_profile=cpu_profile,
            strict_vertex_colors=(
                prepared_import.config.fbx_material_mode == FbxMaterialMode.VERTEX_COLOR_SPLIT
            ),
            result_path=str(result_path),
            error_path=str(error_path),
        ),
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    helper_executable = _resolve_frozen_fbx_helper_executable()
    process = subprocess.Popen(
        [helper_executable, FBX_WORKER_COMMAND, "--request", str(request_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    return _FrozenFbxHelperProcess(
        process=process,
        prepared_import=prepared_import,
        request_path=request_path,
        result_path=result_path,
        error_path=error_path,
    )


def _resolve_frozen_fbx_helper_executable() -> str:
    worker_dir_executable = Path(sys.executable).parent / "XMLtoUSDAWorker" / "XMLtoUSDAWorker.exe"
    if worker_dir_executable.exists():
        return str(worker_dir_executable)
    worker_executable = Path(sys.executable).with_name("XMLtoUSDAWorker.exe")
    if worker_executable.exists():
        return str(worker_executable)
    return sys.executable


def _finalize_frozen_fbx_helper_process(
    launched: _FrozenFbxHelperProcess,
    *,
    exit_code: int,
):
    try:
        if exit_code != 0:
            error_payload = read_fbx_worker_error(launched.error_path)
            if error_payload is not None:
                error_message, formatted_traceback = error_payload
                raise RuntimeError(f"{error_message}\n{formatted_traceback.strip()}")
            raise RuntimeError(
                "Frozen FBX helper subprocess crashed while importing "
                f"{launched.prepared_import.resolved_source_name} from {launched.prepared_import.config.fbx_path} "
                f"(exit code {exit_code})."
            )
        if not launched.result_path.exists():
            raise RuntimeError(
                "Frozen FBX helper subprocess exited without returning a payload file for "
                f"{launched.prepared_import.resolved_source_name}."
            )
        return _load_isolated_fbx_payload_file(launched.result_path)
    finally:
        _cleanup_isolated_fbx_result_file(launched.request_path)
        _cleanup_isolated_fbx_result_file(launched.result_path)
        _cleanup_isolated_fbx_result_file(launched.error_path)


def _terminate_frozen_fbx_helper_process(launched: _FrozenFbxHelperProcess) -> None:
    try:
        if launched.process.poll() is None:
            launched.process.terminate()
            launched.process.wait(timeout=1.0)
    except Exception:
        pass
    _cleanup_isolated_fbx_result_file(launched.request_path)
    _cleanup_isolated_fbx_result_file(launched.result_path)
    _cleanup_isolated_fbx_result_file(launched.error_path)


def _load_fbx_payloads_isolated_sequential(
    prepared_imports: tuple[_PreparedFbxImport, ...],
    *,
    cpu_profile: CpuProfile,
    telemetry_callback=None,
    cancel_event=None,
    started_at: float | None = None,
):
    resolved_payloads: dict[int, object] = {}
    for completed, prepared_import in enumerate(prepared_imports, start=1):
        throw_if_cancelled(cancel_event)
        try:
            resolved_payloads[prepared_import.prototype_index] = _load_fbx_payload_in_fresh_process(
                prepared_import,
                cpu_profile=cpu_profile,
            )
        except Exception as exc:
            raise RuntimeError(
                f"FBX import failed for {prepared_import.resolved_source_name}: {exc}"
            ) from exc
        emit_telemetry(
            telemetry_callback,
            ConversionPhase.FBX_IMPORT,
            completed_units=completed,
            total_units=len(prepared_imports),
            message=f"Imported FBX {prepared_import.resolved_source_name}.",
            started_at=started_at,
        )
    return resolved_payloads


def _load_fbx_payloads_isolated_parallel(
    prepared_imports: tuple[_PreparedFbxImport, ...],
    *,
    cpu_profile: CpuProfile,
    worker_count: int,
    telemetry_callback=None,
    cancel_event=None,
    started_at: float | None = None,
):
    context = multiprocessing.get_context("spawn")
    pending = list(prepared_imports)
    active: dict[int, tuple[object, object, _PreparedFbxImport, Path]] = {}
    resolved_payloads: dict[int, object] = {}
    completed = 0

    def _launch(prepared_import: _PreparedFbxImport) -> None:
        message_queue = context.Queue()
        result_path = _create_isolated_fbx_result_path()
        process = context.Process(
            target=_fbx_payload_process_entry,
            kwargs={
                "prepared_import": prepared_import,
                "cpu_profile_value": cpu_profile.value,
                "message_queue": message_queue,
                "result_path": str(result_path),
            },
            daemon=False,
        )
        process.start()
        active[process.pid] = (process, message_queue, prepared_import, result_path)

    try:
        while pending and len(active) < worker_count:
            _launch(pending.pop(0))

        while active:
            throw_if_cancelled(cancel_event)
            finished_pids: list[int] = []
            for process_pid, (process, message_queue, prepared_import, result_path) in list(active.items()):
                process.join(timeout=0)
                if process.is_alive():
                    continue
                message = _read_isolated_fbx_worker_message(message_queue)
                _close_isolated_fbx_worker_queue(message_queue)
                if process.exitcode not in (0, None):
                    if message and message[0] == "error":
                        _, error_message, formatted_traceback = message
                        raise RuntimeError(
                            f"FBX import failed for {prepared_import.resolved_source_name}: "
                            f"{error_message}\n{formatted_traceback.strip()}"
                        )
                    raise RuntimeError(
                        "Fresh isolated FBX worker crashed while importing "
                        f"{prepared_import.resolved_source_name} from {prepared_import.config.fbx_path} "
                        f"(exit code {process.exitcode})."
                    )
                if message and message[0] == "error":
                    _, error_message, formatted_traceback = message
                    raise RuntimeError(
                        f"FBX import failed for {prepared_import.resolved_source_name}: "
                        f"{error_message}\n{formatted_traceback.strip()}"
                    )
                if not result_path.exists():
                    raise RuntimeError(
                        "Fresh isolated FBX worker exited without returning a payload file for "
                        f"{prepared_import.resolved_source_name}."
                    )
                resolved_payloads[prepared_import.prototype_index] = _load_isolated_fbx_payload_file(result_path)
                completed += 1
                emit_telemetry(
                    telemetry_callback,
                    ConversionPhase.FBX_IMPORT,
                    completed_units=completed,
                    total_units=len(prepared_imports),
                    message=f"Imported FBX {prepared_import.resolved_source_name}.",
                    started_at=started_at,
                )
                finished_pids.append(process_pid)

            for process_pid in finished_pids:
                active.pop(process_pid, None)
                if pending:
                    _launch(pending.pop(0))

            if active and not finished_pids:
                time.sleep(0.05)
    finally:
        for process, message_queue, _prepared_import, result_path in active.values():
            try:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=0.2)
            except Exception:
                pass
            _close_isolated_fbx_worker_queue(message_queue)
            _cleanup_isolated_fbx_result_file(result_path)
    return resolved_payloads


def _load_fbx_payloads_sequential(
    prepared_imports: tuple[_PreparedFbxImport, ...],
    *,
    cpu_profile: CpuProfile,
    telemetry_callback=None,
    cancel_event=None,
    started_at: float | None = None,
):
    emit_telemetry(
        telemetry_callback,
        ConversionPhase.FBX_IMPORT,
        completed_units=0,
        total_units=len(prepared_imports),
        message=f"Importing {len(prepared_imports)} FBX prototype(s) sequentially.",
        started_at=started_at,
    )
    resolved_payloads: dict[int, object] = {}
    for completed, prepared_import in enumerate(prepared_imports, start=1):
        throw_if_cancelled(cancel_event)
        try:
            resolved_payloads[prepared_import.prototype_index] = _load_fbx_payload_worker(
                prepared_import.config.fbx_path or "",
                prepared_import.resolved_identity.prim_name,
                cpu_profile.value,
                prepared_import.config.fbx_material_mode == FbxMaterialMode.VERTEX_COLOR_SPLIT,
            )
        except Exception as exc:
            if _should_retry_vertex_color_import(prepared_import, exc):
                emit_telemetry(
                    telemetry_callback,
                    ConversionPhase.FBX_IMPORT,
                    completed_units=completed - 1,
                    total_units=len(prepared_imports),
                    message=(
                        f"Retrying FBX {prepared_import.resolved_source_name} in a fresh worker "
                        "after Autodesk vertex-color access failure."
                    ),
                    started_at=started_at,
                )
                try:
                    resolved_payloads[prepared_import.prototype_index] = _retry_fbx_payload_in_fresh_process(
                        prepared_import,
                        cpu_profile=cpu_profile,
                    )
                except Exception as retry_exc:
                    raise RuntimeError(
                        f"FBX import failed for {prepared_import.resolved_source_name} after vertex-color retry: {retry_exc}"
                    ) from retry_exc
            else:
                raise RuntimeError(
                    f"FBX import failed for {prepared_import.resolved_source_name}: {exc}"
                ) from exc
        emit_telemetry(
            telemetry_callback,
            ConversionPhase.FBX_IMPORT,
            completed_units=completed,
            total_units=len(prepared_imports),
            message=f"Imported FBX {prepared_import.resolved_source_name}.",
            started_at=started_at,
        )
    return resolved_payloads


def _load_fbx_payload_worker(
    fbx_path: str,
    prototype_name: str,
    cpu_profile_value: str,
    strict_vertex_colors: bool = False,
):
    return load_fbx_geometry(
        fbx_path,
        prototype_name,
        cpu_profile=CpuProfile(cpu_profile_value),
        strict_vertex_colors=strict_vertex_colors,
    )


def _should_retry_vertex_color_import(prepared_import: _PreparedFbxImport, exc: Exception) -> bool:
    if prepared_import.config.fbx_material_mode != FbxMaterialMode.VERTEX_COLOR_SPLIT:
        return False
    return "Autodesk FBX SDK vertex-color access failed" in str(exc)


def _retry_fbx_payload_in_fresh_process(
    prepared_import: _PreparedFbxImport,
    *,
    cpu_profile: CpuProfile,
):
    with ProcessPoolExecutor(
        max_workers=1,
        mp_context=multiprocessing.get_context("spawn"),
    ) as executor:
        future = executor.submit(
            _load_fbx_payload_worker,
            prepared_import.config.fbx_path or "",
            prepared_import.resolved_identity.prim_name,
            cpu_profile.value,
            True,
        )
        try:
            return future.result()
        except BrokenProcessPool as exc:
            raise RuntimeError(
                "Fresh FBX retry worker crashed while importing "
                f"{prepared_import.resolved_source_name} from {prepared_import.config.fbx_path}."
            ) from exc


def _load_fbx_payload_in_fresh_process(
    prepared_import: _PreparedFbxImport,
    *,
    cpu_profile: CpuProfile,
):
    context = multiprocessing.get_context("spawn")
    message_queue = context.Queue()
    result_path = _create_isolated_fbx_result_path()
    process = context.Process(
        target=_fbx_payload_process_entry,
        kwargs={
            "prepared_import": prepared_import,
            "cpu_profile_value": cpu_profile.value,
            "message_queue": message_queue,
            "result_path": str(result_path),
        },
        daemon=False,
    )
    process.start()
    process.join()

    message = _read_isolated_fbx_worker_message(message_queue)
    _close_isolated_fbx_worker_queue(message_queue)

    try:
        if process.exitcode not in (0, None):
            if message and message[0] == "error":
                _, error_message, formatted_traceback = message
                raise RuntimeError(f"{error_message}\n{formatted_traceback.strip()}")
            raise RuntimeError(
                "Fresh isolated FBX worker crashed while importing "
                f"{prepared_import.resolved_source_name} from {prepared_import.config.fbx_path} "
                f"(exit code {process.exitcode})."
            )
        if message and message[0] == "error":
            _, error_message, formatted_traceback = message
            raise RuntimeError(f"{error_message}\n{formatted_traceback.strip()}")
        if not result_path.exists():
            raise RuntimeError(
                "Fresh isolated FBX worker exited without returning a payload file for "
                f"{prepared_import.resolved_source_name}."
            )
        return _load_isolated_fbx_payload_file(result_path)
    finally:
        _cleanup_isolated_fbx_result_file(result_path)


def _create_isolated_fbx_result_path() -> Path:
    file_descriptor, raw_path = tempfile.mkstemp(prefix="xml_to_usda_fbx_payload_", suffix=".pkl")
    os.close(file_descriptor)
    result_path = Path(raw_path)
    _cleanup_isolated_fbx_result_file(result_path)
    return result_path


def _load_isolated_fbx_payload_file(result_path: Path) -> object:
    try:
        with result_path.open("rb") as handle:
            return pickle.load(handle)
    finally:
        _cleanup_isolated_fbx_result_file(result_path)


def _cleanup_isolated_fbx_result_file(result_path: Path) -> None:
    try:
        result_path.unlink(missing_ok=True)
    except Exception:
        pass


def _read_isolated_fbx_worker_message(message_queue):
    message = None
    try:
        while True:
            message = message_queue.get_nowait()
    except Exception:
        pass
    return message


def _close_isolated_fbx_worker_queue(message_queue) -> None:
    try:
        message_queue.close()
    except Exception:
        pass
    try:
        message_queue.join_thread()
    except Exception:
        pass


def _fbx_payload_process_entry(
    *,
    prepared_import: _PreparedFbxImport,
    cpu_profile_value: str,
    message_queue,
    result_path: str,
) -> None:
    try:
        payload = _load_fbx_payload_worker(
            prepared_import.config.fbx_path or "",
            prepared_import.resolved_identity.prim_name,
            cpu_profile_value,
            prepared_import.config.fbx_material_mode == FbxMaterialMode.VERTEX_COLOR_SPLIT,
        )
        with Path(result_path).open("wb") as handle:
            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as exc:
        message_queue.put(("error", str(exc), traceback.format_exc()))
