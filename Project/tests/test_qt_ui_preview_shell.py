from __future__ import annotations

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytestmark = pytest.mark.qt

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget

from xml_to_usda.qt_ui.preview_shell import configure_preview_dialog, focus_preview_dialog


@pytest.mark.parametrize("maximized", (False, True))
def test_preview_dialog_is_modal_without_recreating_its_main_window(qtbot, qapp, maximized) -> None:
    owner = QWidget()
    unrelated = QWidget()
    dialog = QDialog()
    QVBoxLayout(dialog).addWidget(QOpenGLWidget(dialog))
    qtbot.addWidget(owner)
    qtbot.addWidget(unrelated)
    qtbot.addWidget(dialog)
    if maximized:
        owner.setWindowState(Qt.WindowState.WindowMaximized)
    owner.show()
    unrelated.show()
    qapp.processEvents()
    original_handle = int(owner.winId())
    original_surface = owner.windowHandle().surfaceType()
    original_state = owner.windowState()
    events = []

    class Monitor(QObject):
        def eventFilter(self, obj, event):
            events.append((obj, event.type()))
            return False

    monitor = Monitor()
    owner.installEventFilter(monitor)
    unrelated.installEventFilter(monitor)

    configure_preview_dialog(dialog, owner=owner, stylesheet="")
    focus_preview_dialog(dialog)
    qapp.processEvents()

    assert dialog.parentWidget() is None
    assert dialog.windowHandle().transientParent() is owner.windowHandle()
    assert dialog.windowModality() == Qt.WindowModality.WindowModal
    assert dialog.isModal()
    assert dialog.windowFlags() & Qt.WindowType.Window
    assert (owner, QEvent.Type.WindowBlocked) in events
    assert (unrelated, QEvent.Type.WindowBlocked) not in events
    dialog.close()
    qapp.processEvents()
    assert (owner, QEvent.Type.WindowUnblocked) in events
    focus_preview_dialog(dialog)
    qapp.processEvents()
    assert dialog.windowHandle().transientParent() is owner.windowHandle()
    assert owner.isVisible()
    assert int(owner.winId()) == original_handle
    assert owner.windowHandle().surfaceType() == original_surface
    assert owner.windowState() == original_state
    assert not any(event in (QEvent.Type.Hide, QEvent.Type.WinIdChange, QEvent.Type.PlatformSurface) for _, event in events)
