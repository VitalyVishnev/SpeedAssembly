"""Shared preview dialog shell behavior.

Layer: UI infrastructure.

This module centralizes window ownership, modality, and focus rules for preview
dialogs. Mode-specific panels still live in their own dialog classes.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QGridLayout, QVBoxLayout, QWidget


class PreviewShellDialog(QDialog):
    """Shared shell frame for preview dialogs.

    Mode dialogs provide the viewport widget and settings panel content; the
    shell owns the two-column layout and stable window sizing.
    """

    def __init__(self, *, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1040, 720)
        self.shell_layout = QGridLayout(self)
        self.shell_layout.setContentsMargins(0, 0, 0, 0)
        self.shell_layout.setSpacing(0)
        self.shell_layout.setColumnStretch(0, 1)
        self.viewport_widget: QWidget | None = None
        self.settings_panel: QFrame | None = None

    def set_viewport_widget(self, widget: QWidget) -> None:
        self.viewport_widget = widget
        self.shell_layout.addWidget(widget, 0, 0)

    def create_settings_panel(self, *, width: int = 260) -> tuple[QFrame, QVBoxLayout]:
        panel = QFrame(self)
        panel.setObjectName("PanelCard")
        panel.setFixedWidth(width)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        self.settings_panel = panel
        self.shell_layout.addWidget(panel, 0, 1)
        return panel, layout


def configure_preview_dialog(dialog: QDialog, *, owner: QWidget, stylesheet: str) -> None:
    dialog.setParent(owner)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.setModal(True)
    dialog.setWindowFlag(Qt.WindowType.Window, True)
    dialog.setStyleSheet(stylesheet)


def focus_preview_dialog(dialog: QDialog) -> None:
    if dialog.isMinimized():
        dialog.showNormal()
    else:
        dialog.show()
    dialog.raise_()
    dialog.activateWindow()
