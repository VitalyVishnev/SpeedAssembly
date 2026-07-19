"""Shared preview dialog shell behavior.

Layer: UI infrastructure.

This module centralizes window ownership, modality, and focus rules for preview
dialogs. Mode-specific panels still live in their own dialog classes.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QGridLayout, QSplitter, QVBoxLayout, QWidget


_DROPDOWN_ARROW_ICON = Path(__file__).with_name("themes") / "default" / "assets" / "dropdown_arrow.svg"


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
        self.settings_panel_default_width = 0

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

    def create_settings_panel(self, *, width: int = 260, default_width: int | None = None) -> tuple[QFrame, QVBoxLayout]:
        panel = QFrame(self)
        panel.setObjectName("PanelCard")
        self.settings_panel_min_width = int(width)
        self.settings_panel_max_width = int(width) * 2
        requested_default = self.settings_panel_min_width if default_width is None else int(default_width)
        self.settings_panel_default_width = max(self.settings_panel_min_width, min(self.settings_panel_max_width, requested_default))
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
        panel_width = self.settings_panel_default_width or self.settings_panel_min_width or self.settings_panel.minimumWidth()
        self.splitter.setSizes((max(1, available_width - panel_width), panel_width))


def configure_preview_dialog(dialog: QDialog, *, owner: QWidget, stylesheet: str) -> None:
    dialog.setParent(owner, dialog.windowFlags() | Qt.WindowType.Window)
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setModal(True)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
    owner.destroyed.connect(dialog.close)
    dialog.setStyleSheet(stylesheet)


def focus_preview_dialog(dialog: QDialog) -> None:
    if dialog.isMinimized():
        dialog.showNormal()
    else:
        dialog.show()
    dialog.raise_()
    dialog.activateWindow()


def apply_compact_preview_panel_style(panel: QWidget) -> None:
    """Apply the Wind Preview control treatment to a settings surface."""
    arrow_url = _DROPDOWN_ARROW_ICON.as_posix()
    panel.setStyleSheet(
        f"""
QPushButton {{
    background: rgba(148, 157, 77, 210);
    color: #111111;
    border: 0px;
    min-height: 20px;
    max-height: 24px;
    padding: 2px 8px;
    border-radius: 5px;
}}
QPushButton:hover {{ background: rgba(166, 175, 91, 225); }}
QPushButton:disabled {{
    background: rgba(180, 188, 156, 145);
    color: rgba(20, 20, 20, 120);
}}
QComboBox, QLineEdit {{
    background: rgba(255, 255, 255, 150);
    color: #111111;
    border: 1px solid rgba(0, 0, 0, 55);
    border-radius: 5px;
    min-height: 22px;
    max-height: 26px;
    padding: 1px 7px;
}}
QComboBox:hover, QComboBox:focus, QLineEdit:hover, QLineEdit:focus {{
    background: rgba(255, 255, 255, 220);
    border: 1px solid rgba(63, 143, 197, 190);
}}
QComboBox::drop-down {{
    border-left: 1px solid rgba(0, 0, 0, 35);
    background: rgba(255, 255, 255, 65);
    border-top-right-radius: 5px;
    border-bottom-right-radius: 5px;
    width: 20px;
}}
QComboBox::down-arrow {{
    image: url("{arrow_url}");
    width: 8px;
    height: 6px;
}}
QComboBox QAbstractItemView {{
    background: rgba(245, 247, 244, 252);
    color: #111111;
    border: 1px solid rgba(0, 0, 0, 55);
    selection-background-color: rgba(166, 175, 91, 170);
    selection-color: #111111;
    outline: none;
}}
QComboBox:disabled, QLineEdit:disabled {{
    background: rgba(235, 238, 235, 120);
    color: rgba(20, 20, 20, 120);
    border: 1px solid rgba(0, 0, 0, 30);
}}
QSpinBox#UdimIdSpin {{
    background: rgba(255, 255, 255, 150);
    color: #111111;
    border: 1px solid rgba(0, 0, 0, 55);
    border-radius: 5px;
    min-height: 22px;
    max-height: 26px;
    padding: 1px 7px;
}}
QSpinBox#UdimIdSpin:hover, QSpinBox#UdimIdSpin:focus {{
    background: rgba(255, 255, 255, 220);
    border: 1px solid rgba(63, 143, 197, 190);
}}
QSlider {{ min-height: 24px; max-height: 30px; }}
QScrollArea {{ background: transparent; }}
QFrame#LayersPane {{
    background: rgba(255, 255, 255, 32);
    border: 1px solid rgba(0, 0, 0, 35);
    border-radius: 5px;
}}
QCheckBox {{
    spacing: 5px;
    min-height: 16px;
    font-size: 11px;
    color: rgba(0, 0, 0, 190);
}}
QFrame#LayerResizeHandle {{
    background: rgba(0, 0, 0, 70);
    min-height: 6px;
    max-height: 6px;
    border-radius: 3px;
    margin: 1px 0px;
}}
"""
    )
