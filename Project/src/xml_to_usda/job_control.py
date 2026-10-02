from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes

from .models import ConversionPhase, ConversionTelemetry, CpuProfile


class ConversionCancelledError(RuntimeError):
    pass


_PRIORITY_CLASSES = {
    CpuProfile.BALANCED: 0x00004000,  # BELOW_NORMAL_PRIORITY_CLASS
    CpuProfile.MAX_SPEED: 0x00000020,  # NORMAL_PRIORITY_CLASS
    CpuProfile.QUIET: 0x00004000,
}


def logical_cpu_count() -> int:
    return max(1, os.cpu_count() or 1)


def reserved_cpu_count(profile: CpuProfile, cpu_count: int | None = None) -> int:
    cpu_count = cpu_count or logical_cpu_count()
    if profile == CpuProfile.MAX_SPEED:
        return 1
    if profile == CpuProfile.QUIET:
        return max(1, cpu_count // 2)
    return min(2, max(1, cpu_count - 1))


def cpu_worker_count(profile: CpuProfile, cpu_count: int | None = None) -> int:
    cpu_count = cpu_count or logical_cpu_count()
    if profile == CpuProfile.QUIET:
        return max(1, cpu_count // 2)
    return max(1, cpu_count - reserved_cpu_count(profile, cpu_count))


def apply_process_profile(profile: CpuProfile) -> None:
    if os.name != "nt":
        return
    if not hasattr(ctypes, "WinDLL"):
        return
    priority_class = _PRIORITY_CLASSES.get(profile)
    if priority_class is None:
        return

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _configure_kernel32_process_api(kernel32)
        process_handle = kernel32.GetCurrentProcess()
        if process_handle:
            kernel32.SetPriorityClass(process_handle, priority_class)
    except Exception:
        return


def _configure_kernel32_process_api(kernel32) -> None:
    kernel32.GetCurrentProcess.argtypes = ()
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.SetPriorityClass.restype = wintypes.BOOL


def emit_telemetry(
    callback,
    phase: ConversionPhase,
    *,
    completed_units: int = 0,
    total_units: int = 0,
    message: str = "",
    output_bytes_written: int = 0,
    started_at: float | None = None,
) -> ConversionTelemetry | None:
    if callback is None:
        return None
    telemetry = ConversionTelemetry(
        phase=phase,
        completed_units=completed_units,
        total_units=total_units,
        message=message,
        output_bytes_written=output_bytes_written,
        elapsed_seconds=max(0.0, time.perf_counter() - started_at) if started_at is not None else 0.0,
    )
    callback(telemetry)
    return telemetry


def throw_if_cancelled(cancel_event) -> None:
    if cancel_event is not None and bool(cancel_event.is_set()):
        raise ConversionCancelledError("Conversion cancelled by user.")
