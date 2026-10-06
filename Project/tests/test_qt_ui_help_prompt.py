from __future__ import annotations

import json
from pathlib import Path

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytestmark = pytest.mark.qt

from PySide6.QtCore import Qt

from xml_to_usda.qt_ui.dependencies import build_default_dependencies
from xml_to_usda.qt_ui.persistence import UiShellState, load_ui_shell_state
from xml_to_usda.qt_ui.theme import load_theme
from xml_to_usda.qt_ui.window import MainWindow
from xml_to_usda.qt_ui.documentation import DOCUMENTATION_TOPICS, DOCUMENTATION_URL, DocumentationButton
from xml_to_usda.qt_ui.material_controls import MaterialUdimRow, make_udim_controls, make_udim_id_cell
from xml_to_usda.qt_ui.theme import build_stylesheet
from xml_to_usda.qt_ui.proxy_preview import ProxyPreviewDialog
from xml_to_usda.proxy_mesh_service import ProxyMeshSettings
from xml_to_usda.models import UdimMode
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel, QWidget


def test_tutorial_prompt_is_a_child_callout_and_stays_within_the_window(qtbot, tmp_path, monkeypatch) -> None:
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True)
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

    window.title_bar.help_button.click()
    assert opened == [DOCUMENTATION_URL]

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


def test_contextual_help_opens_existing_workflow_pages_for_shared_udim_and_proxy_controls(qtbot, monkeypatch) -> None:
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True)
    host = QWidget()
    host.setStyleSheet(build_stylesheet(load_theme()))
    qtbot.addWidget(host)
    rows = [MaterialUdimRow(label="Material", stacked_udim=stacked, parent=host) for stacked in (False, True)]
    _combo, spin = make_udim_controls(host, mode=UdimMode.OFF, udim_id=1001)
    cell = make_udim_id_cell(host, QLabel("ID", host), spin)
    proxy = ProxyPreviewDialog(settings=ProxyMeshSettings())
    qtbot.addWidget(proxy)

    for control in (*rows, cell, proxy):
        buttons = control.findChildren(DocumentationButton)
        assert len(buttons) == 1
        buttons[0].ensurePolished()
        assert buttons[0].minimumWidth() == buttons[0].minimumHeight() == 24
        assert buttons[0].maximumWidth() == buttons[0].maximumHeight() == 24
        buttons[0].click()
        assert buttons[0].toolTip().startswith("Open ")
        assert buttons[0].accessibleName()

    assert opened == [DOCUMENTATION_URL + "workflows/udim/"] * 3 + [
        DOCUMENTATION_URL + "workflows/proxy-mesh/"
    ]
    project = Path(__file__).resolve().parents[1]
    navigation = (project / "mkdocs.yml").read_text(encoding="utf-8")
    for route, _title in DOCUMENTATION_TOPICS.values():
        article = route.rstrip("/") + ".md" if route else "index.md"
        assert (project / "docs/user" / article).is_file()
        assert article in navigation
