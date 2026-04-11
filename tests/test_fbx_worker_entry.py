from __future__ import annotations

from xml_to_usda.fbx_worker_entry import main


def test_fbx_worker_entry_accepts_plain_request_args(monkeypatch) -> None:
    observed: list[str] = []

    monkeypatch.setattr(
        "xml_to_usda.fbx_worker_entry.run_fbx_worker_request_file",
        lambda request_path: observed.append(request_path) or 0,
    )

    exit_code = main(["--request", "payload.json"])

    assert exit_code == 0
    assert observed == ["payload.json"]


def test_fbx_worker_entry_accepts_compat_command_prefix(monkeypatch) -> None:
    observed: list[str] = []

    monkeypatch.setattr(
        "xml_to_usda.fbx_worker_entry.run_fbx_worker_request_file",
        lambda request_path: observed.append(request_path) or 7,
    )

    exit_code = main(["fbx-worker", "--request", "payload.json"])

    assert exit_code == 7
    assert observed == ["payload.json"]
