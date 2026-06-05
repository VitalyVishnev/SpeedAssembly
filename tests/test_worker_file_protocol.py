from __future__ import annotations

import pickle
from pathlib import Path

import pytest

from xml_to_usda.worker_commands import CONVERSION_WORKER_COMMAND


def test_atomic_pickle_write_does_not_leave_final_file_after_dump_failure(monkeypatch, tmp_path: Path) -> None:
    from xml_to_usda import worker_file_protocol

    target_path = tmp_path / "worker.result.pkl"

    def fail_dump(_payload, _handle, *, protocol=None):  # noqa: ARG001
        raise RuntimeError("simulated pickle failure")

    monkeypatch.setattr(worker_file_protocol.pickle, "dump", fail_dump)

    with pytest.raises(RuntimeError, match="simulated pickle failure"):
        worker_file_protocol.write_pickle_atomic(target_path, {"result": "payload"})

    assert not target_path.exists()
    assert not target_path.with_name(f"{target_path.name}.tmp").exists()


def test_atomic_pickle_write_round_trips_payload(tmp_path: Path) -> None:
    from xml_to_usda.worker_file_protocol import read_pickle_payload, write_pickle_atomic

    target_path = tmp_path / "worker.result.pkl"
    payload = {"result": ("ok", 3)}

    write_pickle_atomic(target_path, payload)

    assert read_pickle_payload(target_path) == payload


def test_error_payload_round_trips_message_and_traceback(tmp_path: Path) -> None:
    from xml_to_usda.worker_file_protocol import read_error_payload, write_error_payload

    error_path = tmp_path / "worker.error.json"

    write_error_payload(error_path, message="broken", formatted_traceback="Traceback\nboom")

    assert read_error_payload(error_path) == ("broken", "Traceback\nboom")


def test_worker_command_resolution_preserves_development_command(monkeypatch, tmp_path: Path) -> None:
    from xml_to_usda.worker_file_protocol import resolve_worker_command

    request_path = tmp_path / "worker.request.pkl"
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


def test_worker_command_resolution_prefers_packaged_worker_directory(monkeypatch, tmp_path: Path) -> None:
    from xml_to_usda.worker_file_protocol import resolve_worker_command

    exe_path = tmp_path / "XMLtoUSDAConverter.exe"
    worker_path = tmp_path / "XMLtoUSDAWorker" / "XMLtoUSDAWorker.exe"
    worker_path.parent.mkdir()
    worker_path.write_text("", encoding="utf-8")
    request_path = tmp_path / "worker.request.pkl"
    monkeypatch.setattr("xml_to_usda.worker_file_protocol.sys.executable", str(exe_path))
    monkeypatch.setattr("xml_to_usda.worker_file_protocol.sys.frozen", True, raising=False)

    assert resolve_worker_command(CONVERSION_WORKER_COMMAND, request_path) == [
        str(worker_path),
        CONVERSION_WORKER_COMMAND,
        "--request",
        str(request_path),
    ]
