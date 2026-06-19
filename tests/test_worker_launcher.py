from __future__ import annotations

import importlib.util
from pathlib import Path

from xml_to_usda.worker_commands import (
    CONVERSION_WORKER_COMMAND,
    FRACTURE_WORKER_COMMAND,
    PROXY_MESH_WORKER_COMMAND,
)


def test_packaged_worker_launcher_routes_worker_commands(monkeypatch) -> None:
    launcher = _load_worker_launcher()
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "xml_to_usda.conversion_worker_subprocess.run_conversion_worker_request_file",
        lambda request: calls.append(("conversion", request)) or 0,
    )
    monkeypatch.setattr(
        "xml_to_usda.proxy_mesh_worker_subprocess.run_proxy_mesh_worker_request_file",
        lambda request: calls.append(("proxy", request)) or 0,
    )
    monkeypatch.setattr(
        "xml_to_usda.fracture_worker_subprocess.run_fracture_worker_request_file",
        lambda request: calls.append(("fracture", request)) or 0,
    )

    assert launcher.main([CONVERSION_WORKER_COMMAND, "--request", "conversion.pkl"]) == 0
    assert launcher.main([PROXY_MESH_WORKER_COMMAND, "--request", "proxy.pkl"]) == 0
    assert launcher.main([FRACTURE_WORKER_COMMAND, "--request", "fracture.pkl"]) == 0

    assert calls == [
        ("conversion", "conversion.pkl"),
        ("proxy", "proxy.pkl"),
        ("fracture", "fracture.pkl"),
    ]


def test_packaged_worker_launcher_does_not_depend_on_qt_entrypoint() -> None:
    source = Path("scripts/launch_worker.py").read_text(encoding="utf-8")

    assert "qt_ui" not in source
    assert "PySide6" not in source


def _load_worker_launcher():
    spec = importlib.util.spec_from_file_location("xml_to_usda_worker_launcher_test", "scripts/launch_worker.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
