from __future__ import annotations

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytestmark = pytest.mark.qt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QWidget

from xml_to_usda.qt_ui.preview_shell import configure_preview_dialog


def test_preview_dialog_is_modal_to_its_main_window(qtbot) -> None:
    owner = QWidget()
    dialog = QDialog(owner)
    qtbot.addWidget(owner)
    qtbot.addWidget(dialog)

    configure_preview_dialog(dialog, owner=owner, stylesheet="")

    assert dialog.parentWidget() is owner
    assert dialog.windowModality() == Qt.WindowModality.WindowModal
    assert dialog.isModal()
    assert dialog.windowFlags() & Qt.WindowType.Window
