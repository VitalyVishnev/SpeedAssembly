"""Compact program status and source summary for the main window."""

from __future__ import annotations

from html import escape
from pathlib import PurePosixPath, PureWindowsPath

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..models import ConversionPhase, ConversionTelemetry


_CONVERSION_STEPS = (
    ("Prepare", frozenset((ConversionPhase.PREPARING,))),
    ("Normalize XML", frozenset((ConversionPhase.XML_NORMALIZATION,))),
    (
        "Resolve Geometry",
        frozenset((ConversionPhase.PROTOTYPE_RESOLUTION, ConversionPhase.FBX_IMPORT)),
    ),
    ("Resolve Materials", frozenset((ConversionPhase.MATERIAL_RESOLUTION,))),
    ("Write USDA", frozenset((ConversionPhase.USDA_WRITING,))),
)
_SPINNER_FRAMES = ("◴", "◷", "◶", "◵")


class ProgramStatusCard(QFrame):
    SUCCESS_RESET_MS = 5_000

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("PanelCard")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._conversion_active = False
        self._active_step_index: int | None = None
        self._spinner_index = 0

        card_layout = QVBoxLayout(self)
        card_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("ProgramStatusScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.viewport().setAutoFillBackground(False)
        card_layout.addWidget(self.scroll)

        host = QWidget(self.scroll)
        host.setObjectName("ProgramStatusHost")
        host.setMinimumWidth(0)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        self.scroll.setWidget(host)

        title = QLabel("Program Status", host)
        title.setObjectName("ProgramStatusTitle")
        layout.addWidget(title)

        state_row = QHBoxLayout()
        state_row.setSpacing(8)
        self.state_indicator = QLabel("●", host)
        self.state_indicator.setObjectName("ProgramStatusIndicator")
        self.state_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state_label = QLabel("Ready", host)
        self.state_label.setObjectName("ProgramStatusState")
        state_row.addWidget(self.state_indicator, 0)
        state_row.addWidget(self.state_label, 1)
        layout.addLayout(state_row)

        self.status_label = QLabel("SpeedAssembly is ready.", host)
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumWidth(0)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.status_label)

        self.progress = QProgressBar(host)
        self.progress.setObjectName("ProgramStatusProgress")
        self.progress.setTextVisible(False)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.steps_frame = QFrame(host)
        self.steps_frame.setObjectName("ProgramStatusSteps")
        steps_layout = QVBoxLayout(self.steps_frame)
        steps_layout.setContentsMargins(0, 2, 0, 2)
        steps_layout.setSpacing(6)
        self.step_labels: list[QLabel] = []
        self.step_markers: list[QLabel] = []
        for name, _phases in _CONVERSION_STEPS:
            row = QHBoxLayout()
            row.setSpacing(6)
            marker = QLabel("○", self.steps_frame)
            marker.setObjectName("ProgramStatusStepMarker")
            marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label = QLabel(name, self.steps_frame)
            label.setObjectName("ProgramStatusStep")
            label.setProperty("stepState", "pending")
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            self.step_markers.append(marker)
            self.step_labels.append(label)
            row.addWidget(marker, 0)
            row.addWidget(label, 1)
            steps_layout.addLayout(row)
        self.steps_frame.hide()
        layout.addWidget(self.steps_frame)

        summary_title = QLabel("CURRENT SETUP", host)
        summary_title.setObjectName("ProgramStatusSectionTitle")
        layout.addWidget(summary_title)
        self.mode_label = self._summary_label(host, "Mode", "Skeletal Assembly")
        self.material_label = self._summary_label(host, "Materials", "Source materials")
        self.source_label = self._summary_label(host, "Source", "No XML selected")
        layout.addWidget(self.mode_label)
        layout.addWidget(self.material_label)
        layout.addWidget(self.source_label)
        layout.addStretch(1)

        self._reset_timer = QTimer(self)
        self._reset_timer.setSingleShot(True)
        self._reset_timer.timeout.connect(self.set_ready)
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(140)
        self._spinner_timer.timeout.connect(self._advance_spinner)
        self.set_ready()

    @staticmethod
    def _summary_label(parent: QWidget, title: str, value: str) -> QLabel:
        label = QLabel(parent)
        label.setObjectName("ProgramStatusSummary")
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        label.setText(_summary_html(title, value))
        label.setToolTip(value)
        return label

    def set_summary(
        self,
        *,
        mode: str | None = None,
        materials: str | None = None,
        source: str | None = None,
        materials_tooltip: str | None = None,
    ) -> None:
        for label, title, value, tooltip in (
            (self.mode_label, "Mode", mode, None),
            (self.material_label, "Materials", materials, materials_tooltip),
            (self.source_label, "Source", source, None),
        ):
            if value is None:
                continue
            label.setText(_summary_html(title, value))
            label.setToolTip(tooltip or value)

    def set_message(self, text: str) -> None:
        self.status_label.setText(_compact_path(text))
        self.status_label.setToolTip(text)

    def set_passive_message(self, text: str) -> None:
        if self.state_label.property("statusState") == "working":
            self.set_message(text)
            return
        self.set_ready(text)

    def set_ready(self, message: str = "SpeedAssembly is ready.") -> None:
        self._reset_timer.stop()
        self._conversion_active = False
        self._active_step_index = None
        self._set_state("ready", "Ready", "●")
        self.set_message(message)
        self.progress.hide()
        self.steps_frame.hide()

    def begin_activity(self, title: str, message: str) -> None:
        self._reset_timer.stop()
        self._conversion_active = False
        self._active_step_index = None
        self._set_state("working", title, _SPINNER_FRAMES[0])
        self.set_message(message)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.steps_frame.hide()

    def begin_conversion(self, message: str) -> None:
        self._reset_timer.stop()
        self._conversion_active = True
        self._active_step_index = 0
        self._set_state("working", "Converting Tree", _SPINNER_FRAMES[0])
        self.set_message(message)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.steps_frame.show()
        self._render_steps()

    def set_conversion_telemetry(self, telemetry: ConversionTelemetry) -> None:
        if not self._conversion_active:
            self.begin_conversion("Preparing conversion job...")
        step_index = self._step_index(telemetry.phase)
        if step_index is not None:
            self._active_step_index = step_index
        self.set_message(_format_telemetry(telemetry))
        if telemetry.total_units > 0:
            self.progress.setRange(0, max(1, int(telemetry.total_units)))
            self.progress.setValue(max(0, min(int(telemetry.completed_units), int(telemetry.total_units))))
        else:
            self.progress.setRange(0, 0)
        self.progress.show()
        self.steps_frame.show()
        self._render_steps(completed=telemetry.phase == ConversionPhase.COMPLETED)

    def finish(self, outcome: str, message: str) -> None:
        labels = {
            "success": ("Success", "✓"),
            "error": ("Error", "!"),
            "cancelled": ("Cancelled", "×"),
        }
        if outcome not in labels:
            raise ValueError(f"Unsupported program status outcome: {outcome}")
        title, indicator = labels[outcome]
        self._set_state(outcome, title, indicator)
        self.set_message(message)
        self.progress.hide()
        if self._conversion_active:
            self.steps_frame.show()
            self._render_steps(completed=outcome == "success", failed=outcome != "success")
        else:
            self.steps_frame.hide()
        self._conversion_active = False
        if outcome == "success":
            self._reset_timer.start(self.SUCCESS_RESET_MS)
        else:
            self._reset_timer.stop()

    def _render_steps(self, *, completed: bool = False, failed: bool = False) -> None:
        active_index = self._active_step_index if self._active_step_index is not None else 0
        for index, (marker_label, label) in enumerate(zip(self.step_markers, self.step_labels)):
            if completed or index < active_index:
                state, marker = "complete", "✓"
            elif index == active_index:
                state, marker = ("failed", "!") if failed else ("active", _SPINNER_FRAMES[self._spinner_index])
            else:
                state, marker = "pending", "○"
            marker_label.setText(marker)
            for widget in (marker_label, label):
                widget.setProperty("stepState", state)
                _refresh_style(widget)

    @staticmethod
    def _step_index(phase: ConversionPhase) -> int | None:
        if phase == ConversionPhase.COMPLETED:
            return len(_CONVERSION_STEPS) - 1
        for index, (_name, phases) in enumerate(_CONVERSION_STEPS):
            if phase in phases:
                return index
        return None

    def _set_state(self, state: str, title: str, indicator: str) -> None:
        self.state_indicator.setText(indicator)
        self.state_label.setText(title)
        for widget in (self.state_indicator, self.state_label):
            widget.setProperty("statusState", state)
            _refresh_style(widget)
        if state == "working":
            self._spinner_index = 0
            self._spinner_timer.start()
        else:
            self._spinner_timer.stop()

    def _advance_spinner(self) -> None:
        self._spinner_index = (self._spinner_index + 1) % len(_SPINNER_FRAMES)
        self.state_indicator.setText(_SPINNER_FRAMES[self._spinner_index])
        if self._conversion_active:
            self._render_steps()


def _summary_html(title: str, value: str) -> str:
    escaped_value = escape(value).replace("\n", "<br>")
    return f"<b>{escape(title.upper())}</b><br>{escaped_value}"


def _compact_path(text: str) -> str:
    for separator in (" to ", ": "):
        prefix, found, candidate = text.rpartition(separator)
        if not found:
            continue
        raw_path = candidate.strip().rstrip("/\\")
        windows_path = PureWindowsPath(raw_path)
        posix_path = PurePosixPath(raw_path)
        if windows_path.is_absolute():
            name = windows_path.name
        elif posix_path.is_absolute():
            name = posix_path.name
        else:
            continue
        if name:
            return f"{prefix}{separator.rstrip()}\n{name}"
    return text


def _format_telemetry(telemetry: ConversionTelemetry) -> str:
    text = telemetry.message or telemetry.phase.value.replace("_", " ").title()
    details: list[str] = []
    if telemetry.total_units > 0:
        details.append(f"{telemetry.completed_units}/{telemetry.total_units}")
    if telemetry.output_bytes_written > 0:
        details.append(f"{telemetry.output_bytes_written:,} bytes")
    if telemetry.elapsed_seconds > 0:
        details.append(f"{telemetry.elapsed_seconds:.1f}s")
    return f"{text}  ·  {' · '.join(details)}" if details else text


def _refresh_style(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
