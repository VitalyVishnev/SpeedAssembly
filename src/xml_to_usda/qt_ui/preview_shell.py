"""Shared preview dialog shell behavior.

Layer: UI infrastructure.

This module centralizes window ownership, modality, and focus rules for preview
dialogs. Mode-specific panels still live in their own dialog classes.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QGridLayout, QSplitter, QVBoxLayout, QWidget


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
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(6)
        self.shell_layout.addWidget(self.splitter, 0, 0, 1, 2)
        self.viewport_widget: QWidget | None = None
        self.settings_panel: QFrame | None = None
        self.settings_panel_min_width = 0
        self.settings_panel_max_width = 0

    def set_viewport_widget(self, widget: QWidget) -> None:
        self.viewport_widget = widget
        self.splitter.insertWidget(0, widget)
        self.splitter.setStretchFactor(0, 1)
        self._apply_splitter_sizes()

    def set_viewport_visible(self, visible: bool) -> None:
        if self.viewport_widget is None:
            return
        self.viewport_widget.setVisible(bool(visible))
        if visible:
            self._apply_splitter_sizes()
            return
        if self.settings_panel is not None:
            self.splitter.setSizes((0, max(self.settings_panel_min_width, self.settings_panel.width())))

    def create_settings_panel(self, *, width: int = 260) -> tuple[QFrame, QVBoxLayout]:
        panel = QFrame(self)
        panel.setObjectName("PanelCard")
        self.settings_panel_min_width = int(width)
        self.settings_panel_max_width = int(width) * 2
        panel.setMinimumWidth(self.settings_panel_min_width)
        panel.setMaximumWidth(self.settings_panel_max_width)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        self.settings_panel = panel
        self.splitter.addWidget(panel)
        self.splitter.setStretchFactor(self.splitter.indexOf(panel), 0)
        self._apply_splitter_sizes()
        return panel, layout

    def _apply_splitter_sizes(self) -> None:
        if self.viewport_widget is None or self.settings_panel is None:
            return
        available_width = max(1, self.width())
        panel_width = self.settings_panel_min_width or self.settings_panel.minimumWidth()
        self.splitter.setSizes((max(1, available_width - panel_width), panel_width))


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
