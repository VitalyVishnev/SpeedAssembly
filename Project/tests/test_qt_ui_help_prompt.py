from __future__ import annotations

import json

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytestmark = pytest.mark.qt

from PySide6.QtCore import Qt

from xml_to_usda.qt_ui.dependencies import build_default_dependencies
from xml_to_usda.qt_ui.persistence import UiShellState, load_ui_shell_state
from xml_to_usda.qt_ui.theme import load_theme
from xml_to_usda.qt_ui.window import MainWindow


def test_tutorial_prompt_is_a_child_callout_and_stays_within_the_window(qtbot, tmp_path) -> None:
    window = MainWindow(
        load_theme(),
        UiShellState(width=1160, height=780),
        dependencies=build_default_dependencies(),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    callout = window.help_callout
    assert callout.parentWidget() is window
    assert callout.window() is window
    assert not callout.windowFlags() & Qt.WindowType.Tool
    assert window.rect().contains(callout.geometry())

    window.dismiss_help_prompt()
    assert load_ui_shell_state(tmp_path / "ui_next_state.json").help_prompt_dismissed is True


def test_tutorial_prompt_reappears_for_a_new_build_signature(tmp_path) -> None:
    state_path = tmp_path / "ui_next_state.json"
    state_path.write_text(
        json.dumps(
            {
                "help_prompt_dismissed": True,
                "help_prompt_build_signature": "previous-build",
            }
        ),
        encoding="utf-8",
    )

    state = load_ui_shell_state(state_path, current_build_signature="current-build")

    assert state.help_prompt_dismissed is False
    assert state.help_prompt_build_signature == "current-build"
