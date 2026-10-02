from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytestmark = pytest.mark.qt

from PySide6.QtWidgets import QMessageBox

from xml_to_usda.qt_ui.dependencies import build_default_dependencies
from xml_to_usda.qt_ui.persistence import UiShellState
from xml_to_usda.qt_ui.theme import load_theme
from xml_to_usda.qt_ui.window import MainWindow
from xml_to_usda.settings_service import GuiSettingsSnapshot, save_gui_settings


class _RunningProcess:
    exitcode = None

    def __init__(self) -> None:
        self.terminated = False

    def is_alive(self) -> bool:
        return not self.terminated

    def join(self, timeout=None) -> None:
        return None

    def terminate(self) -> None:
        self.terminated = True


class _Queue:
    def drain(self):
        return []

    def close(self) -> None:
        return None


class _CancelEvent:
    def __init__(self, process: _RunningProcess) -> None:
        self.process = process

    def set(self) -> None:
        self.process.terminate()

    def is_set(self) -> bool:
        return self.process.terminated


def test_restored_large_xml_starts_isolated_discovery_without_sync_parsing(qtbot, tmp_path) -> None:
    xml_path = tmp_path / "WorldTree.xml"
    xml_path.write_text("<Tree />", encoding="utf-8")
    settings_path = tmp_path / "gui_settings.json"
    save_gui_settings(settings_path, GuiSettingsSnapshot(last_input_path=str(xml_path)))
    starts = []

    def fail_sync_discovery(*_args, **_kwargs):
        raise AssertionError("large XML discovery ran in the GUI process")

    def start_source_discovery(request):
        starts.append(request)
        process = _RunningProcess()
        return process, _Queue(), _CancelEvent(process)

    deps = replace(
        build_default_dependencies(),
        discover_base_material_rows=fail_sync_discovery,
        discover_part_prototype_rows=fail_sync_discovery,
        start_source_discovery_process=start_source_discovery,
    )
    original_threshold = MainWindow.ASYNC_SOURCE_DISCOVERY_THRESHOLD_BYTES
    MainWindow.ASYNC_SOURCE_DISCOVERY_THRESHOLD_BYTES = 1
    try:
        window = MainWindow(
            load_theme(),
            UiShellState(help_prompt_dismissed=True),
            dependencies=deps,
            state_path=tmp_path / "ui_next_state.json",
            operator_settings_path=settings_path,
        )
        qtbot.addWidget(window)
        assert [request.input_path for request in starts] == [str(xml_path)]
        assert window._background_jobs.source_discovery_running is True
    finally:
        MainWindow.ASYNC_SOURCE_DISCOVERY_THRESHOLD_BYTES = original_threshold


def test_missing_bone_group_warning_requires_acknowledgement_but_does_not_change_state(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        "xml_to_usda.qt_ui.window.QMessageBox.warning",
        lambda parent, title, message, buttons: calls.append((parent, title, message, buttons)),
    )
    window = SimpleNamespace(_shown_bone_gap_warning=None)

    MainWindow._warn_about_missing_bone_generator_groups(window, "tree.xml", ("Group_2",))
    MainWindow._warn_about_missing_bone_generator_groups(window, "tree.xml", ("Group_2",))

    assert len(calls) == 1
    assert calls[0][1] == "Missing skeleton bones"
    assert "Group_2" in calls[0][2]
    assert calls[0][3] == QMessageBox.StandardButton.Ok
