from __future__ import annotations

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

pytestmark = pytest.mark.qt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from xml_to_usda.qt_ui.preview_shell import (
    PreviewShellDialog,
    apply_compact_preview_panel_style,
    configure_preview_dialog,
    focus_preview_dialog,
)


def test_preview_shell_owns_viewport_and_settings_slots(qtbot) -> None:
    dialog = PreviewShellDialog(title="Preview")
    qtbot.addWidget(dialog)
    viewport = QLabel("viewport", dialog)
    panel, panel_layout = dialog.create_settings_panel()

    dialog.set_viewport_widget(viewport)
    panel_layout.addWidget(QLabel("settings", panel))

    assert dialog.windowTitle() == "Preview"
    assert dialog.viewport_widget is viewport
    assert dialog.settings_panel is panel
    assert dialog.shell_layout.itemAtPosition(0, 0).widget() is dialog.splitter
    assert dialog.splitter.widget(0) is viewport
    assert dialog.splitter.widget(1) is panel
    assert dialog.shell_layout.columnStretch(0) == 1
    assert panel.minimumWidth() == 260
    assert panel.maximumWidth() == 520


def test_preview_shell_configures_non_modal_owned_focus_contract(qtbot) -> None:
    owner = QLabel("owner")
    dialog = PreviewShellDialog(title="Preview")
    qtbot.addWidget(owner)
    qtbot.addWidget(dialog)

    configure_preview_dialog(dialog, owner=owner, stylesheet="QLabel { color: red; }")
    focus_preview_dialog(dialog)

    assert dialog.parent() is None
    assert dialog.isVisible()
    assert dialog.windowModality() == Qt.WindowModality.NonModal
    assert not dialog.isModal()


def test_compact_preview_style_can_be_shared_by_main_settings_surfaces(qtbot) -> None:
    panel = QWidget()
    qtbot.addWidget(panel)

    apply_compact_preview_panel_style(panel)

    assert "QComboBox::drop-down" in panel.styleSheet()
    assert "QComboBox QAbstractItemView" in panel.styleSheet()
