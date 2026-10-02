from __future__ import annotations

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytestmark = pytest.mark.qt

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QComboBox, QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget

from xml_to_usda.qt_ui.window import _ParameterWheelFilter


def test_parameter_wheel_scrolls_panel_without_changing_values(qtbot) -> None:
    scroll = QScrollArea()
    content = QWidget()
    layout = QVBoxLayout(content)
    slider = QSlider(Qt.Orientation.Horizontal, content)
    slider.setRange(0, 100)
    slider.setValue(50)
    spin = QSpinBox(content)
    spin.setRange(0, 100)
    spin.setValue(50)
    combo = QComboBox(content)
    combo.addItems(("First", "Second"))
    for widget in (slider, spin, combo):
        layout.addWidget(widget)
    content.setMinimumHeight(800)
    scroll.setWidget(content)
    scroll.resize(240, 180)
    qtbot.addWidget(scroll)
    scroll.show()

    wheel_filter = _ParameterWheelFilter(scroll)
    for widget in (slider, spin, combo):
        widget.installEventFilter(wheel_filter)

    bar = scroll.verticalScrollBar()
    bar.setValue(300)
    original_values = (slider.value(), spin.value(), combo.currentIndex())
    for widget in (slider, spin, combo):
        before = bar.value()
        QApplication.sendEvent(widget, _wheel_event(120))
        assert bar.value() < before
    assert (slider.value(), spin.value(), combo.currentIndex()) == original_values


def _wheel_event(delta: int) -> QWheelEvent:
    return QWheelEvent(
        QPointF(1.0, 1.0),
        QPointF(1.0, 1.0),
        QPoint(),
        QPoint(0, delta),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
