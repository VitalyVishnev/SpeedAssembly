"""Shared file protocol helpers for isolated worker processes.

Layer: infrastructure.

This module owns atomic request/result/error file exchange and worker command
resolution. It must not know conversion, proxy, fracture, or FBX semantics.
"""

from __future__ import annotations

import json
import os
import pickle
import sys
import tempfile
from pathlib import Path
from typing import Any


def write_pickle_atomic(path: str | Path, payload: object) -> None:
    target_path = Path(path)
    temp_path = target_path.with_name(f"{target_path.name}.tmp")
    try:
        with temp_path.open("wb") as handle:
            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
        temp_path.replace(target_path)
    except Exception:
        cleanup_file(temp_path)
        cleanup_file(target_path)
        raise


def read_pickle_payload(path: str | Path) -> Any:
    with Path(path).open("rb") as handle:
        return pickle.load(handle)


def write_json_atomic(path: str | Path, payload: dict[str, object]) -> None:
    target_path = Path(path)
    temp_path = target_path.with_name(f"{target_path.name}.tmp")
    try:
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        temp_path.replace(target_path)
    except Exception:
        cleanup_file(temp_path)
        cleanup_file(target_path)
        raise


def read_json_payload(path: str | Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("Worker JSON payload must be an object.")
    return payload


def write_error_payload(path: str | Path, *, message: str, formatted_traceback: str) -> None:
    write_json_atomic(
        path,
        {
            "message": message,
            "traceback": formatted_traceback,
        },
    )


def read_error_payload(path: str | Path) -> tuple[str, str] | None:
    error_path = Path(path)
    if not error_path.exists():
        return None
    payload = read_json_payload(error_path)
    return str(payload.get("message", "")), str(payload.get("traceback", ""))


def create_temp_path(prefix: str, suffix: str) -> Path:
    file_descriptor, raw_path = tempfile.mkstemp(prefix=prefix, suffix=suffix)
    os.close(file_descriptor)
    path = Path(raw_path)
    cleanup_file(path)
    return path


def cleanup_file(path: str | Path) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except Exception:
        pass


def resolve_worker_command(command: str, request_path: str | Path) -> list[str]:
    request = str(request_path)
    if bool(getattr(sys, "frozen", False)):
        worker_dir_executable = Path(sys.executable).parent / "XMLtoUSDAWorker" / "XMLtoUSDAWorker.exe"
        if worker_dir_executable.exists():
            return [str(worker_dir_executable), command, "--request", request]
        worker_executable = Path(sys.executable).with_name("XMLtoUSDAWorker.exe")
        if worker_executable.exists():
            return [str(worker_executable), command, "--request", request]
        return [sys.executable, command, "--request", request]
    return [sys.executable, "-m", "xml_to_usda", command, "--request", request]
