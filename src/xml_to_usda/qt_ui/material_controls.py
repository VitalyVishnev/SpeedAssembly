"""
Reusable Qt controls for operator-facing Unreal material paths with UDIM intent.

Layer: UI.

This module owns the visual/editing pattern only. Callers still own whether the
value represents a base XML material, repeated-part material, or Fracture Cap.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from ..models import UdimMode


UDIM_MODE_COMBO_WIDTH = 180
UDIM_ID_SPIN_WIDTH = 76
UDIM_ID_LABEL_SPACING = 4


@dataclass(frozen=True)
class MaterialUdimValue:
    material_path: str = ""
    udim_mode: UdimMode = UdimMode.OFF
    udim_id: int = 1001


class NoWheelComboBox(QComboBox):
    def wheelEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()


def set_combo_value(combo: QComboBox, value: str) -> None:
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)
        return
    index = combo.findText(value)
    if index >= 0:
        combo.setCurrentIndex(index)


def make_path_edit(
    text: str,
    parent: QWidget,
    *,
    placeholder: str,
    max_width: int | None = None,
) -> QLineEdit:
    edit = QLineEdit(text, parent)
    edit.setObjectName("PathInput")
    edit.setPlaceholderText(placeholder)
    if max_width is not None:
        edit.setMaximumWidth(int(max_width))
    return edit


def make_udim_controls(parent: QWidget, *, mode: UdimMode, udim_id: int) -> tuple[NoWheelComboBox, QSpinBox]:
    mode_combo = NoWheelComboBox(parent)
    mode_combo.setObjectName("InteractiveCombo")
    for label, value in (
        ("UDIM Off", UdimMode.OFF.value),
        ("Shift UV", UdimMode.SHIFT_PRIMARY_UV.value),
        ("Write UV1 Offset", UdimMode.WRITE_SECONDARY_UV_OFFSET.value),
    ):
        mode_combo.addItem(label, value)
    set_combo_value(mode_combo, mode.value)
    mode_combo.setFixedWidth(UDIM_MODE_COMBO_WIDTH)
    udim_id_spin = QSpinBox(parent)
    udim_id_spin.setRange(1001, 1999)
    udim_id_spin.setValue(int(udim_id))
    udim_id_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    udim_id_spin.setAlignment(Qt.AlignmentFlag.AlignRight)
    udim_id_spin.setFixedWidth(UDIM_ID_SPIN_WIDTH)
    return mode_combo, udim_id_spin


def make_compact_udim_controls(parent: QWidget, *, mode: UdimMode, udim_id: int) -> tuple[NoWheelComboBox, QSpinBox]:
    mode_combo, udim_id_spin = make_udim_controls(parent, mode=mode, udim_id=udim_id)
    mode_combo.setFixedWidth(142)
    udim_id_spin.setFixedWidth(64)
    return mode_combo, udim_id_spin


def make_udim_id_cell(parent: QWidget, label: QLabel, spin: QSpinBox) -> QWidget:
    cell = QWidget(parent)
    layout = QHBoxLayout(cell)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(UDIM_ID_LABEL_SPACING)
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    layout.addWidget(label, 0)
    layout.addWidget(spin, 0)
    return cell


class MaterialUdimRow(QWidget):
    valueChanged = Signal()

    def __init__(
        self,
        *,
        label: str,
        value: MaterialUdimValue | None = None,
        placeholder: str = "/Game/Path/Material.Material",
        path_max_width: int | None = 220,
        stacked_udim: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._stacked_udim = bool(stacked_udim)
        resolved = value or MaterialUdimValue()
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(4)
        self.label = QLabel(label, self)
        self.color_dot = QFrame(self)
        self.color_dot.setFixedSize(12, 12)
        self.color_dot.setObjectName("MaterialColorDot")
        self.color_dot.setVisible(False)
        label_cell = QWidget(self)
        label_layout = QHBoxLayout(label_cell)
        label_layout.setContentsMargins(0, 0, 0, 0)
        label_layout.setSpacing(5)
        label_layout.addWidget(self.color_dot, 0)
        label_layout.addWidget(self.label, 1)
        self.path_edit = make_path_edit(
            resolved.material_path,
            self,
            placeholder=placeholder,
            max_width=path_max_width,
        )
        make_udims = make_compact_udim_controls if self._stacked_udim else make_udim_controls
        self.udim_mode_combo, self.udim_id_spin = make_udims(self, mode=resolved.udim_mode, udim_id=resolved.udim_id)
        layout.addWidget(label_cell, 0, 0)
        if self._stacked_udim:
            layout.addWidget(self.path_edit, 0, 1, 1, 2)
            layout.addWidget(self.udim_mode_combo, 1, 1)
            layout.addWidget(self.udim_id_spin, 1, 2)
        else:
            layout.addWidget(self.path_edit, 0, 1)
            layout.addWidget(self.udim_mode_combo, 0, 2)
            layout.addWidget(self.udim_id_spin, 0, 3)
        layout.setColumnStretch(1, 1)

        self.path_edit.textChanged.connect(lambda _text: self.valueChanged.emit())
        self.udim_mode_combo.currentIndexChanged.connect(lambda _index: self.valueChanged.emit())
        self.udim_id_spin.valueChanged.connect(lambda _value: self.valueChanged.emit())

    def value(self) -> MaterialUdimValue:
        return MaterialUdimValue(
            material_path=self.path_edit.text().strip(),
            udim_mode=UdimMode.parse(self.udim_mode_combo.currentData()),
            udim_id=int(self.udim_id_spin.value()),
        )

    def set_controls_visible(self, visible: bool) -> None:
        self.setVisible(visible)
        self.setEnabled(visible)

    def set_color_dot(self, color) -> None:
        if color is None:
            self.color_dot.setVisible(False)
            return
        red = max(0, min(255, int(round(float(color.r) * 255.0))))
        green = max(0, min(255, int(round(float(color.g) * 255.0))))
        blue = max(0, min(255, int(round(float(color.b) * 255.0))))
        self.color_dot.setStyleSheet(
            "QFrame#MaterialColorDot {"
            f"background: rgb({red}, {green}, {blue});"
            "border: 1px solid rgba(0, 0, 0, 70);"
            "border-radius: 6px;"
            "}"
        )
        self.color_dot.setVisible(True)
