from __future__ import annotations

import json
import pickle
from pathlib import Path

import pytest

from xml_to_usda.worker_commands import CONVERSION_WORKER_COMMAND


def test_atomic_worker_payload_write_does_not_leave_final_file_after_dump_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from xml_to_usda import worker_file_protocol

    target_path = tmp_path / "worker.result.json"

    def fail_dump(_payload, **_kwargs):
        raise RuntimeError("simulated JSON failure")

    monkeypatch.setattr(worker_file_protocol.json, "dumps", fail_dump)

    with pytest.raises(RuntimeError, match="simulated JSON failure"):
        worker_file_protocol.write_worker_payload_atomic(target_path, {"result": "payload"})

    assert not target_path.exists()
    assert not target_path.with_name(f"{target_path.name}.tmp").exists()


def test_atomic_worker_payload_write_round_trips_payload(tmp_path: Path) -> None:
    from array import array
    from xml_to_usda.models import CpuProfile
    from xml_to_usda.worker_file_protocol import read_worker_payload, write_worker_payload_atomic

    target_path = tmp_path / "worker.result.json"
    payload = {"result": ("ok", CpuProfile.BALANCED, array("i", [1, 2, 3]))}

    write_worker_payload_atomic(target_path, payload)

    assert read_worker_payload(target_path) == payload


def test_worker_payload_reader_rejects_pickle_without_executing(tmp_path: Path) -> None:
    from xml_to_usda.worker_file_protocol import read_worker_payload

    called: list[str] = []

    class _Exploit:
        def __reduce__(self):
            return (called.append, ("executed",))

    payload_path = tmp_path / "worker.result.json"
    payload_path.write_bytes(pickle.dumps(_Exploit()))

    with pytest.raises((UnicodeDecodeError, json.JSONDecodeError)):
        read_worker_payload(payload_path)

    assert called == []


def test_error_payload_round_trips_message_and_traceback(tmp_path: Path) -> None:
    from xml_to_usda.worker_file_protocol import read_error_payload, write_error_payload

    error_path = tmp_path / "worker.error.json"

    write_error_payload(error_path, message="broken", formatted_traceback="Traceback\nboom")

    assert read_error_payload(error_path) == ("broken", "Traceback\nboom")


def test_worker_command_resolution_preserves_development_command(monkeypatch, tmp_path: Path) -> None:
    from xml_to_usda.worker_file_protocol import resolve_worker_command

    request_path = tmp_path / "worker.request.json"
    monkeypatch.setattr("xml_to_usda.worker_file_protocol.sys.executable", "python-test")
    monkeypatch.setattr("xml_to_usda.worker_file_protocol.sys.frozen", False, raising=False)

    assert resolve_worker_command(CONVERSION_WORKER_COMMAND, request_path) == [
        "python-test",
        "-m",
        "xml_to_usda",
        CONVERSION_WORKER_COMMAND,
        "--request",
        str(request_path),
    ]


def test_worker_command_resolution_uses_self_executable_in_frozen_mode(monkeypatch, tmp_path: Path) -> None:
    from xml_to_usda.worker_file_protocol import resolve_worker_command

    exe_path = tmp_path / "XMLtoUSDAConverter.exe"
    request_path = tmp_path / "worker.request.json"
    monkeypatch.setattr("xml_to_usda.worker_file_protocol.sys.executable", str(exe_path))
    monkeypatch.setattr("xml_to_usda.worker_file_protocol.sys.frozen", True, raising=False)

    assert resolve_worker_command(CONVERSION_WORKER_COMMAND, request_path) == [
        str(exe_path),
        CONVERSION_WORKER_COMMAND,
        "--request",
        str(request_path),
    ]
