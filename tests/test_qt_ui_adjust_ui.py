from __future__ import annotations

import json

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from xml_to_usda.qt_ui.dependencies import build_default_dependencies
from xml_to_usda.qt_ui.persistence import UiShellState
from xml_to_usda.qt_ui.theme import ThemeOverrides, load_bundled_theme, load_theme
from xml_to_usda.qt_ui.window import MainWindow


def test_adjust_ui_dialog_opens(qtbot, tmp_path) -> None:
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=build_default_dependencies(),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
        base_theme=load_bundled_theme(),
        theme_overrides=ThemeOverrides(theme_name="default", payload={}),
        theme_overrides_path=tmp_path / "ui_next_theme_overrides.json",
    )
    qtbot.addWidget(window)
    window.show()

    window.open_adjust_ui_dialog()

    assert window._adjust_ui_dialog is not None
    assert window._adjust_ui_dialog.windowTitle().startswith("Adjust UI")


def test_adjust_ui_live_preview_and_save(qtbot, tmp_path) -> None:
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

    binding = dialog._field_bindings[("glass", "tint_opacity")]
    binding.editor.spin.setValue(0.35)
    qtbot.waitUntil(lambda: window._theme.glass["tint_opacity"] == pytest.approx(0.35), timeout=1000)

    assert not overrides_path.exists()

    qtbot.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)
    assert window._theme_overrides.payload["glass"]["tint_opacity"] == pytest.approx(0.35)
    assert not overrides_path.exists()

    qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
    payload = json.loads(overrides_path.read_text(encoding="utf-8"))
    assert payload["payload"]["glass"]["tint_opacity"] == pytest.approx(0.35)
    assert load_bundled_theme().glass["tint_opacity"] != pytest.approx(0.35)


def test_adjust_ui_panel_size_controls_update_live_preview(qtbot, tmp_path) -> None:
    window = MainWindow(
        load_theme(),
        UiShellState(width=1800, height=1100),
        dependencies=build_default_dependencies(),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
        base_theme=load_bundled_theme(),
        theme_overrides=ThemeOverrides(theme_name="default", payload={}),
        theme_overrides_path=tmp_path / "ui_next_theme_overrides.json",
    )
    qtbot.addWidget(window)
    window.show()
    window.open_adjust_ui_dialog()
    dialog = window._adjust_ui_dialog
    assert dialog is not None

    initial_width = window.panel.width()
    width_binding = dialog._field_bindings[("layout", "panel_preferred_width")]
    width_binding.editor.spin.setValue(860)
    qtbot.waitUntil(lambda: window.panel.width() < initial_width, timeout=1000)

    height_binding = dialog._field_bindings[("layout", "panel_min_height")]
    height_binding.editor.spin.setValue(920)
    qtbot.waitUntil(lambda: window.panel.minimumHeight() == 920, timeout=1000)


def test_adjust_ui_export_and_reset_all(monkeypatch, qtbot, tmp_path) -> None:
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    export_path = tmp_path / "ui_next_theme_export.json"
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=build_default_dependencies(),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
        base_theme=load_bundled_theme(),
        theme_overrides=ThemeOverrides(theme_name="default", payload={}),
        theme_overrides_path=tmp_path / "ui_next_theme_overrides.json",
    )
    window._theme_export_path = export_path
    qtbot.addWidget(window)
    window.show()
    window.open_adjust_ui_dialog()
    dialog = window._adjust_ui_dialog
    assert dialog is not None

    binding = dialog._field_bindings[("layout", "panel_preferred_width")]
    binding.editor.spin.setValue(940)
    qtbot.waitUntil(lambda: window._theme.layout["panel_preferred_width"] == 940, timeout=1000)

    qtbot.mouseClick(dialog.export_button, Qt.MouseButton.LeftButton)
    exported_payload = json.loads(export_path.read_text(encoding="utf-8"))
    assert exported_payload["layout"]["panel_preferred_width"] == 940

    qtbot.mouseClick(dialog.reset_all_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: window._theme.layout["panel_preferred_width"] == load_bundled_theme().layout["panel_preferred_width"],
        timeout=1000,
    )
