from __future__ import annotations

from types import SimpleNamespace

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytestmark = pytest.mark.qt

from PySide6.QtWidgets import QWidget

from xml_to_usda.fracture_preview_service import FracturePreviewSettings, FracturePreviewSourceRequest
from xml_to_usda.fracture_service import FractureSettings
from xml_to_usda.qt_ui.background_jobs import QtBackgroundJobsController


class _Process:
    exitcode = 0

    def __init__(self, *, alive: bool) -> None:
        self.alive = alive
        self.terminated = False

    def is_alive(self) -> bool:
        return self.alive and not self.terminated

    def join(self, timeout=None) -> None:
        return None

    def terminate(self) -> None:
        self.terminated = True


class _CancelEvent:
    def __init__(self) -> None:
        self.was_set = False

    def set(self) -> None:
        self.was_set = True

    def is_set(self) -> bool:
        return self.was_set


class _Window(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.results = []
        self._fracture_preview_dialog = None

    def _set_status(self, _message: str) -> None:
        return None

    def _update_action_state(self) -> None:
        return None

    def _trace(self, *_args, **_kwargs) -> None:
        return None

    def _handle_fracture_preview_result(self, result) -> None:
        self.results.append(result)

    def _handle_fracture_preview_error_message(self, message: str) -> None:
        raise AssertionError(message)

    def _report_error(self, _title: str, message: str, **_kwargs) -> None:
        raise AssertionError(message)


def test_qt_fracture_controller_delivers_only_latest_settings_without_killing_active_worker(qtbot) -> None:
    window = _Window()
    qtbot.addWidget(window)
    first_process = _Process(alive=True)
    first_cancel = _CancelEvent()
    first_queue = []
    latest_result = SimpleNamespace(plan=SimpleNamespace(actual_piece_count=9))
    starts = []

    def start_fracture_preview(request, settings):
        starts.append((request, settings))
        if len(starts) == 1:
            return first_process, first_queue, first_cancel
        return _Process(alive=False), [("result", latest_result)], _CancelEvent()

    def drain(queue):
        events = list(queue)
        queue.clear()
        return events

    deps = SimpleNamespace(
        start_wind_preview_process=lambda *_args: None,
        start_proxy_mesh_process=lambda *_args, **_kwargs: None,
        start_fracture_preview_process=start_fracture_preview,
        start_part_preview_process=lambda *_args: None,
        start_source_discovery_process=lambda *_args: None,
        drain_process_queue=drain,
        close_process_queue=lambda _queue: None,
    )
    controller = QtBackgroundJobsController(window, deps=deps, runtime_paths=SimpleNamespace())
    request = FracturePreviewSourceRequest(input_path="tree.xml")
    first_settings = FracturePreviewSettings(fracture=FractureSettings(target_piece_count=5))
    latest_settings = FracturePreviewSettings(
        fracture=FractureSettings(target_piece_count=9, detailed_cuts_enabled=True)
    )

    try:
        controller.start_fracture_preview(request, first_settings)
        controller.start_fracture_preview(request, latest_settings)

        assert len(starts) == 1
        assert first_process.terminated is False
        assert first_cancel.was_set is False

        first_queue.append(("result", SimpleNamespace(plan=SimpleNamespace(actual_piece_count=5))))
        first_process.alive = False
        qtbot.waitUntil(lambda: window.results == [latest_result], timeout=3_000)

        assert [settings for _request, settings in starts] == [first_settings, latest_settings]
        assert first_process.terminated is False
        assert first_cancel.was_set is False
    finally:
        controller.shutdown()
