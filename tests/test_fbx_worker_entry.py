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


def test_qt_entry_routes_fbx_worker_mode_before_gui_import(monkeypatch) -> None:
    observed: list[list[str]] = []

    monkeypatch.setattr(
        "xml_to_usda.fbx_worker_entry.main",
        lambda argv: observed.append(list(argv)) or 9,
    )

    from xml_to_usda.qt_ui.entry import main as qt_entry_main

    exit_code = qt_entry_main(["fbx-worker", "--request", "payload.json"])

    assert exit_code == 9
    assert observed == [["fbx-worker", "--request", "payload.json"]]


def test_frozen_fbx_helper_falls_back_to_gui_executable_without_sidecar(
    tmp_path,
    monkeypatch,
) -> None:
    import xml_to_usda.fbx_import_supervisor as supervisor_module

    request_path = tmp_path / "worker_request.json"
    gui_executable = tmp_path / "XMLtoUSDAConverter.exe"
    gui_executable.write_bytes(b"")

    monkeypatch.setattr(supervisor_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(supervisor_module.sys, "executable", str(gui_executable))

    command = supervisor_module._resolve_helper_command(request_path)

    assert command == [
        str(gui_executable),
        supervisor_module.FBX_WORKER_COMMAND,
        "--request",
        str(request_path),
    ]
