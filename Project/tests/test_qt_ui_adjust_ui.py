from __future__ import annotations

import json

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytestmark = pytest.mark.qt

from PySide6.QtCore import Qt

from xml_to_usda.qt_ui.dependencies import build_default_dependencies
from xml_to_usda.qt_ui.persistence import UiShellState
from xml_to_usda.qt_ui.theme import ThemeOverrides, load_bundled_theme, load_theme
from xml_to_usda.qt_ui.window import MainWindow


def test_adjust_ui_signal_updates_theme_and_persists_selected_override(qtbot, tmp_path) -> None:
    overrides_path = tmp_path / "ui_next_theme_overrides.json"
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=build_default_dependencies(),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
        base_theme=load_bundled_theme(),
        theme_overrides=ThemeOverrides(theme_name="default", payload={}),
        theme_overrides_path=overrides_path,
    )
    qtbot.addWidget(window)
    window.show()
    window.open_adjust_ui_dialog()
    dialog = window._adjust_ui_dialog
    assert dialog is not None

    dialog._field_bindings[("glass", "tint_opacity")].editor.spin.setValue(0.35)
    qtbot.waitUntil(lambda: window._theme.glass["tint_opacity"] == pytest.approx(0.35), timeout=1000)
    qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    payload = json.loads(overrides_path.read_text(encoding="utf-8"))
    assert payload["payload"]["glass"]["tint_opacity"] == pytest.approx(0.35)
