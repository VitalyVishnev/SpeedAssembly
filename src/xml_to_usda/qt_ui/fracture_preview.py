"""Qt-facing fracture preview payload preparation.

Layer: UI adapter.

This module converts `FracturePreviewResult` into a flat colored triangle
payload that an OpenGL widget can draw without knowing fracture planning rules.
"""

from __future__ import annotations

import math
from array import array
from dataclasses import dataclass
from math import sqrt

import numpy as np

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QShortcut, QVector3D
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..fracture_preview_service import (
    DEFAULT_FRACTURE_PREVIEW_POLYCOUNT,
    FracturePreviewBoneSegment,
    FracturePreviewResult,
    FracturePreviewSettings,
)
from ..fracture_service import (
    FRACTURE_METHOD_BRANCH_BASE_GREEDY,
    FRACTURE_METHOD_MANUAL_PINNED_BONES,
    FRACTURE_METHOD_PURE_HIERARCHY,
    FRACTURE_METHOD_WIND_GUIDED_HIERARCHY,
    FractureSettings,
)
from ..models import Color4, GeometryBuffer, Quaternion, Vector3
from .proxy_preview import GL_FLOAT, MatcapViewport, _build_grid_vertices


FRACTURE_VERTEX_STRIDE = 10
FRACTURE_MATCAP_TINT_STRENGTH = 0.78


@dataclass(frozen=True)
class FractureDrawSource:
    name: str
    first_vertex: int
    vertex_count: int
    triangle_count: int


@dataclass(frozen=True)
class FractureDrawCall:
    source_index: int
    translate: Vector3
    orientation: Quaternion
    scale: Vector3


@dataclass(frozen=True)
class FractureViewportMesh:
    name: str
    vertex_components: array
    triangle_count: int
    uploaded_triangle_count: int
    piece_count: int
    instance_count: int
    draw_sources: tuple[FractureDrawSource, ...]
    draw_calls: tuple[FractureDrawCall, ...]
    bone_segments: tuple[FracturePreviewBoneSegment, ...] = ()


@dataclass(frozen=True)
class FractureRenderPayload:
    vertex_components: np.ndarray
    min_point: Vector3
    max_point: Vector3


class FracturePreviewDialog(QDialog):
    def __init__(
        self,
        *,
        settings: FracturePreviewSettings | None = None,
        preview: FracturePreviewResult | None = None,
        on_settings_changed=None,
        on_export_requested=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._on_settings_changed = on_settings_changed or (lambda settings: None)
        self._on_export_requested = on_export_requested or (lambda: None)
        self._settings = settings or FracturePreviewSettings()
        self._manual_cut_tokens = self._settings.fracture.pinned_cut_joint_tokens
        self._manual_cut_undo_stack = list(self._manual_cut_tokens)
        self._cut_delete_buttons: dict[str, QPushButton] = {}
        self.current_preview: FracturePreviewResult | None = None
        self.viewport_mesh: FractureViewportMesh | None = None
        self.setWindowTitle("Fracture Preview")
        self.resize(1040, 720)

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        viewport_host = QWidget(self)
        viewport_layout = QGridLayout(viewport_host)
        viewport_layout.setContentsMargins(0, 0, 0, 0)
        viewport_layout.setSpacing(0)
        self.viewport = FractureViewport(viewport_host)
        viewport_layout.addWidget(self.viewport, 0, 0)
        self.loading_label = QLabel("Preparing preview geometry...", viewport_host)
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_label.setObjectName("FracturePreviewLoadingLabel")
        self.loading_label.setStyleSheet(
            "background: rgba(20, 24, 26, 180);"
            "color: #f2f2f2;"
            "font-weight: 700;"
            "padding: 14px 18px;"
            "border-radius: 6px;"
        )
        viewport_layout.addWidget(self.loading_label, 0, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(viewport_host, 0, 0)

        settings_panel = QFrame(self)
        settings_panel.setObjectName("PanelCard")
        settings_panel.setFixedWidth(260)
        settings_layout = QVBoxLayout(settings_panel)
        settings_layout.setContentsMargins(14, 14, 14, 14)
        settings_layout.setSpacing(8)

        title = QLabel("Fracturing", settings_panel)
        title.setStyleSheet("font-weight: 700;")
        settings_layout.addWidget(title)

        self.method_combo = QComboBox(settings_panel)
        self.method_combo.addItem("Wind Guided Hierarchy", FRACTURE_METHOD_WIND_GUIDED_HIERARCHY)
        self.method_combo.addItem("Pure Hierarchy", FRACTURE_METHOD_PURE_HIERARCHY)
        self.method_combo.addItem("Branch Base Greedy", FRACTURE_METHOD_BRANCH_BASE_GREEDY)
        self.method_combo.addItem("Manual Fracturing", FRACTURE_METHOD_MANUAL_PINNED_BONES)
        self.method_combo.setProperty("prominent", True)
        self.method_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.method_combo.setStyleSheet(
            "QComboBox[prominent=\"true\"] {"
            "background: rgba(151, 163, 77, 0.22);"
            "border: 1px solid rgba(151, 163, 77, 0.72);"
            "border-radius: 6px;"
            "padding: 6px 10px;"
            "}"
            "QComboBox[prominent=\"true\"]:hover {"
            "background: rgba(151, 163, 77, 0.34);"
            "}"
        )
        settings_layout.addWidget(QLabel("Method", settings_panel))
        settings_layout.addWidget(self.method_combo)

        self.manual_auto_fill_label = QLabel("Manual Auto Fill", settings_panel)
        self.manual_auto_fill_combo = QComboBox(settings_panel)
        self.manual_auto_fill_combo.addItem("Wind Guided Hierarchy", FRACTURE_METHOD_WIND_GUIDED_HIERARCHY)
        self.manual_auto_fill_combo.addItem("Pure Hierarchy", FRACTURE_METHOD_PURE_HIERARCHY)
        self.manual_auto_fill_combo.addItem("Branch Base Greedy", FRACTURE_METHOD_BRANCH_BASE_GREEDY)
        settings_layout.addWidget(self.manual_auto_fill_label)
        settings_layout.addWidget(self.manual_auto_fill_combo)

        self.piece_count_slider, self.piece_count_spin = _build_int_slider_row(
            settings_panel,
            minimum=1,
            maximum=64,
            value=int(self._settings.fracture.target_piece_count),
            step=1,
        )
        settings_layout.addWidget(QLabel("Target Pieces", settings_panel))
        settings_layout.addLayout(_slider_row(self.piece_count_slider, self.piece_count_spin))

        self.polycount_slider, self.polycount_spin = _build_int_slider_row(
            settings_panel,
            minimum=1,
            maximum=10_000_000,
            value=int(self._settings.final_polycount),
            step=50_000,
        )
        settings_layout.addWidget(QLabel("Preview Polycount", settings_panel))
        settings_layout.addLayout(_slider_row(self.polycount_slider, self.polycount_spin))

        self.base_priority_slider, self.base_priority_spin = _build_float_slider_row(
            settings_panel,
            minimum=0.0,
            maximum=1.0,
            value=float(self._settings.base_mesh_priority),
            step=0.01,
            scale=100,
        )
        settings_layout.addWidget(QLabel("Base Priority", settings_panel))
        settings_layout.addLayout(_slider_row(self.base_priority_slider, self.base_priority_spin))

        self.color_strength_slider, self.color_strength_spin = _build_float_slider_row(
            settings_panel,
            minimum=0.0,
            maximum=1.0,
            value=FRACTURE_MATCAP_TINT_STRENGTH,
            step=0.01,
            scale=100,
        )
        settings_layout.addWidget(QLabel("Piece Color", settings_panel))
        settings_layout.addLayout(_slider_row(self.color_strength_slider, self.color_strength_spin))

        self.show_bones_check = QCheckBox("Show Bones", settings_panel)
        self.hide_repeated_parts_check = QCheckBox("Hide Repeated Parts", settings_panel)
        self.reset_cuts_button = QPushButton("Reset Cuts", settings_panel)
        self.reset_cuts_button.clicked.connect(self._reset_manual_cuts)
        settings_layout.addWidget(self.show_bones_check)
        settings_layout.addWidget(self.hide_repeated_parts_check)
        settings_layout.addWidget(self.reset_cuts_button)

        self.cut_list_label = QLabel("Cuts", settings_panel)
        self.cut_list_host = QWidget(settings_panel)
        self.cut_list_layout = QVBoxLayout(self.cut_list_host)
        self.cut_list_layout.setContentsMargins(0, 0, 0, 0)
        self.cut_list_layout.setSpacing(4)
        settings_layout.addWidget(self.cut_list_label)
        settings_layout.addWidget(self.cut_list_host)

        self.export_button = QPushButton("Export Fracture Pieces", settings_panel)
        self.export_button.clicked.connect(self._on_export_requested)
        settings_layout.addWidget(self.export_button)

        self.summary_label = QLabel("Preparing preview geometry...", settings_panel)
        self.summary_label.setWordWrap(True)
        settings_layout.addWidget(self.summary_label)
        settings_layout.addStretch(1)

        layout.addWidget(settings_panel, 0, 1)
        self.viewport.on_bone_cut_toggled = self._toggle_manual_cut_token
        self.undo_cut_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        self.undo_cut_shortcut.activated.connect(self._undo_last_manual_cut)
        self._sync_settings_controls(self._settings)
        self.method_combo.currentIndexChanged.connect(lambda _index: self._handle_method_changed())
        self.manual_auto_fill_combo.currentIndexChanged.connect(lambda _index: self._emit_settings_changed())
        self.piece_count_slider.sliderReleased.connect(self._emit_settings_changed)
        self.piece_count_spin.editingFinished.connect(self._emit_settings_changed)
        self.polycount_slider.sliderReleased.connect(self._emit_settings_changed)
        self.polycount_spin.editingFinished.connect(self._emit_settings_changed)
        self.base_priority_slider.sliderReleased.connect(self._emit_settings_changed)
        self.base_priority_spin.editingFinished.connect(self._emit_settings_changed)
        self.color_strength_spin.valueChanged.connect(self._handle_color_strength_changed)
        self.color_strength_slider.valueChanged.connect(lambda _value: self._handle_color_strength_changed(self.color_strength_spin.value()))
        self.show_bones_check.toggled.connect(self._handle_show_bones_changed)
        self.hide_repeated_parts_check.toggled.connect(self._handle_hide_repeated_parts_changed)
        if preview is not None:
            self.set_preview(preview)

    def settings(self) -> FracturePreviewSettings:
        return FracturePreviewSettings(
            fracture=FractureSettings(
                method=str(self.method_combo.currentData() or FRACTURE_METHOD_WIND_GUIDED_HIERARCHY),
                target_piece_count=int(self.piece_count_spin.value()),
                pinned_cut_joint_tokens=self._manual_cut_tokens,
                manual_auto_fill_method=str(
                    self.manual_auto_fill_combo.currentData() or FRACTURE_METHOD_WIND_GUIDED_HIERARCHY
                ),
            ),
            final_polycount=int(self.polycount_spin.value() or DEFAULT_FRACTURE_PREVIEW_POLYCOUNT),
            base_mesh_priority=float(self.base_priority_spin.value()),
        )

    def set_settings(self, settings: FracturePreviewSettings) -> None:
        self._settings = settings
        self._manual_cut_tokens = settings.fracture.pinned_cut_joint_tokens
        self._manual_cut_undo_stack = list(self._manual_cut_tokens)
        self._sync_settings_controls(settings)

    def set_loading(self, message: str = "Preparing preview geometry...") -> None:
        self.loading_label.setText(message)
        self.loading_label.show()
        self.summary_label.setText(message)

    def set_preview(self, preview: FracturePreviewResult) -> None:
        self.current_preview = preview
        self.viewport_mesh = build_fracture_viewport_mesh(
            preview,
            include_repeated_parts=not self.hide_repeated_parts_check.isChecked(),
        )
        self.viewport.set_mesh(self.viewport_mesh)
        self.viewport.set_selected_cut_tokens(self._manual_cut_tokens)
        self.viewport.set_show_bones(self.show_bones_check.isChecked())
        self.loading_label.hide()
        self.summary_label.setText(
            (
                f"{self.viewport_mesh.piece_count} pieces\n"
                f"{self.viewport_mesh.triangle_count} preview triangles\n"
                f"{self.viewport_mesh.uploaded_triangle_count} uploaded triangles\n"
                f"{self.viewport_mesh.instance_count} repeated instances"
            )
        )

    def set_error(self, message: str) -> None:
        self.loading_label.setText(message)
        self.loading_label.show()
        self.summary_label.setText(message)

    def _sync_settings_controls(self, settings: FracturePreviewSettings) -> None:
        with (
            QSignalBlocker(self.method_combo),
            QSignalBlocker(self.manual_auto_fill_combo),
            QSignalBlocker(self.piece_count_slider),
            QSignalBlocker(self.piece_count_spin),
            QSignalBlocker(self.polycount_slider),
            QSignalBlocker(self.polycount_spin),
            QSignalBlocker(self.base_priority_slider),
            QSignalBlocker(self.base_priority_spin),
            QSignalBlocker(self.show_bones_check),
        ):
            method_index = self.method_combo.findData(settings.fracture.method)
            self.method_combo.setCurrentIndex(max(0, method_index))
            auto_fill_index = self.manual_auto_fill_combo.findData(settings.fracture.manual_auto_fill_method)
            self.manual_auto_fill_combo.setCurrentIndex(max(0, auto_fill_index))
            self.piece_count_slider.setValue(int(settings.fracture.target_piece_count))
            self.piece_count_spin.setValue(int(settings.fracture.target_piece_count))
            self.polycount_slider.setValue(int(settings.final_polycount))
            self.polycount_spin.setValue(int(settings.final_polycount))
            self.base_priority_slider.setValue(int(round(float(settings.base_mesh_priority) * 100)))
            self.base_priority_spin.setValue(float(settings.base_mesh_priority))
            if settings.fracture.method == FRACTURE_METHOD_MANUAL_PINNED_BONES and not self.show_bones_check.isChecked():
                self.show_bones_check.setChecked(True)
        self._sync_manual_controls()

    def _emit_settings_changed(self) -> None:
        self._sync_manual_controls()
        settings = self.settings()
        if settings == self._settings:
            return
        self._settings = settings
        self.set_loading()
        self._on_settings_changed(settings)

    def _handle_color_strength_changed(self, value: float) -> None:
        resolved = float(value)
        with QSignalBlocker(self.color_strength_slider):
            self.color_strength_slider.setValue(int(round(resolved * 100)))
        self.viewport.set_matcap_tint_strength(resolved)

    def _handle_method_changed(self) -> None:
        self._sync_manual_controls()
        self._emit_settings_changed()

    def _sync_manual_controls(self) -> None:
        manual = self.method_combo.currentData() == FRACTURE_METHOD_MANUAL_PINNED_BONES
        self.manual_auto_fill_label.setVisible(manual)
        self.manual_auto_fill_combo.setVisible(manual)
        self.reset_cuts_button.setVisible(manual)
        self.cut_list_label.setVisible(manual)
        self.cut_list_host.setVisible(manual)
        if manual:
            self.show_bones_check.setEnabled(True)
        else:
            self.show_bones_check.setEnabled(True)
        self.viewport.set_show_bones(self.show_bones_check.isChecked())
        self._sync_cut_list()

    def _handle_show_bones_changed(self, checked: bool) -> None:
        self.viewport.set_show_bones(checked)

    def _handle_hide_repeated_parts_changed(self, _checked: bool) -> None:
        if self.current_preview is not None:
            self.set_preview(self.current_preview)

    def _toggle_manual_cut_token(self, joint_token: str) -> None:
        if self.method_combo.currentData() != FRACTURE_METHOD_MANUAL_PINNED_BONES:
            return
        tokens = list(self._manual_cut_tokens)
        if joint_token in tokens:
            tokens.remove(joint_token)
            self._manual_cut_undo_stack = [token for token in self._manual_cut_undo_stack if token != joint_token]
        else:
            tokens.append(joint_token)
            self._manual_cut_undo_stack.append(joint_token)
        self._manual_cut_tokens = tuple(tokens)
        self.viewport.set_selected_cut_tokens(self._manual_cut_tokens)
        self._sync_cut_list()
        self._emit_settings_changed()

    def _remove_manual_cut_token(self, joint_token: str) -> None:
        if joint_token not in self._manual_cut_tokens:
            return
        self._manual_cut_tokens = tuple(token for token in self._manual_cut_tokens if token != joint_token)
        self._manual_cut_undo_stack = [token for token in self._manual_cut_undo_stack if token != joint_token]
        self.viewport.set_selected_cut_tokens(self._manual_cut_tokens)
        self._sync_cut_list()
        self._emit_settings_changed()

    def _undo_last_manual_cut(self) -> None:
        while self._manual_cut_undo_stack:
            joint_token = self._manual_cut_undo_stack.pop()
            if joint_token in self._manual_cut_tokens:
                self._manual_cut_tokens = tuple(token for token in self._manual_cut_tokens if token != joint_token)
                self.viewport.set_selected_cut_tokens(self._manual_cut_tokens)
                self._sync_cut_list()
                self._emit_settings_changed()
                return

    def _reset_manual_cuts(self) -> None:
        if not self._manual_cut_tokens:
            return
        self._manual_cut_tokens = ()
        self._manual_cut_undo_stack = []
        self.viewport.set_selected_cut_tokens(self._manual_cut_tokens)
        self._sync_cut_list()
        self._emit_settings_changed()

    def _sync_cut_list(self) -> None:
        while self.cut_list_layout.count():
            item = self.cut_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cut_delete_buttons = {}
        for joint_token in self._manual_cut_tokens:
            row = QWidget(self.cut_list_host)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            label = QLabel(joint_token, row)
            button = QPushButton("x", row)
            button.setFixedSize(24, 22)
            button.setToolTip(f"Remove {joint_token}")
            button.clicked.connect(lambda _checked=False, token=joint_token: self._remove_manual_cut_token(token))
            row_layout.addWidget(label, 1)
            row_layout.addWidget(button, 0)
            self.cut_list_layout.addWidget(row)
            self._cut_delete_buttons[joint_token] = button


def _build_int_slider_row(
    parent,
    *,
    minimum: int,
    maximum: int,
    value: int,
    step: int,
) -> tuple[QSlider, QSpinBox]:
    slider = QSlider(Qt.Orientation.Horizontal, parent)
    slider.setRange(minimum, maximum)
    slider.setSingleStep(step)
    slider.setPageStep(max(step, step * 4))
    slider.setValue(max(minimum, min(maximum, value)))

    spin = QSpinBox(parent)
    spin.setRange(minimum, maximum)
    spin.setSingleStep(step)
    spin.setValue(max(minimum, min(maximum, value)))
    spin.setKeyboardTracking(False)
    spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    spin.setFixedWidth(92)

    slider.valueChanged.connect(lambda raw: _sync_int_spin(spin, raw, step))
    spin.editingFinished.connect(lambda: _sync_int_slider(slider, spin.value()))
    return slider, spin


def _build_float_slider_row(
    parent,
    *,
    minimum: float,
    maximum: float,
    value: float,
    step: float,
    scale: int,
) -> tuple[QSlider, QDoubleSpinBox]:
    slider = QSlider(Qt.Orientation.Horizontal, parent)
    slider.setRange(int(round(minimum * scale)), int(round(maximum * scale)))
    slider.setSingleStep(max(1, int(round(step * scale))))
    slider.setPageStep(max(1, int(round(step * scale * 4))))
    slider.setValue(int(round(max(minimum, min(maximum, value)) * scale)))

    spin = QDoubleSpinBox(parent)
    spin.setRange(minimum, maximum)
    spin.setSingleStep(step)
    spin.setDecimals(2)
    spin.setValue(max(minimum, min(maximum, value)))
    spin.setKeyboardTracking(False)
    spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    spin.setFixedWidth(70)

    slider.valueChanged.connect(lambda raw: _sync_float_spin(spin, raw, scale))
    spin.editingFinished.connect(lambda: _sync_float_slider(slider, spin.value(), scale))
    return slider, spin


def _slider_row(slider: QSlider, spin) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    row.addWidget(slider, 1)
    row.addWidget(spin, 0)
    return row


def _sync_int_spin(spin: QSpinBox, value: int, step: int) -> None:
    snapped = max(spin.minimum(), min(spin.maximum(), int(round(value / step) * step)))
    with QSignalBlocker(spin):
        spin.setValue(snapped)


def _sync_int_slider(slider: QSlider, value: int) -> None:
    with QSignalBlocker(slider):
        slider.setValue(value)


def _sync_float_spin(spin: QDoubleSpinBox, value: int, scale: int) -> None:
    with QSignalBlocker(spin):
        spin.setValue(value / scale)


def _sync_float_slider(slider: QSlider, value: float, scale: int) -> None:
    with QSignalBlocker(slider):
        slider.setValue(int(round(value * scale)))


class FractureViewport(MatcapViewport):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._fracture_mesh: FractureViewportMesh | None = None
        self._fracture_render_payload: FractureRenderPayload | None = None
        self._matcap_tint_strength = FRACTURE_MATCAP_TINT_STRENGTH
        self._show_bones = False
        self._selected_cut_tokens: tuple[str, ...] = ()
        self._hover_cut_token: str | None = None
        self.on_bone_cut_toggled = lambda _joint_token: None
        self.setMouseTracking(True)

    def has_mesh(self) -> bool:
        return self._fracture_mesh is not None and self._vertex_count > 0

    def set_mesh(self, mesh: FractureViewportMesh) -> None:
        self._fracture_mesh = mesh
        self._fracture_render_payload = _build_fracture_render_payload(
            mesh,
            tint_strength=self._matcap_tint_strength,
        )
        self._vertex_count = len(self._fracture_render_payload.vertex_components) // FRACTURE_VERTEX_STRIDE
        self._update_fracture_mesh_metrics(self._fracture_render_payload)
        self._grid_vertex_count = int(len(self._build_grid_vertices_for_current_camera()) // 4)
        self._mesh_dirty = True
        self._grid_dirty = True
        if self.isValid():
            self.makeCurrent()
            try:
                self._upload_mesh()
                self._upload_grid()
            finally:
                self.doneCurrent()
        self.update()

    def set_matcap_tint_strength(self, value: float) -> None:
        self._matcap_tint_strength = max(0.0, min(1.0, float(value)))
        if self._fracture_mesh is not None:
            self._fracture_render_payload = _build_fracture_render_payload(
                self._fracture_mesh,
                tint_strength=self._matcap_tint_strength,
            )
            self._mesh_dirty = True
            if self.isValid():
                self.makeCurrent()
                try:
                    self._upload_mesh()
                finally:
                    self.doneCurrent()
        self.update()

    @property
    def mesh(self) -> FractureViewportMesh | None:
        return self._fracture_mesh

    @property
    def show_bones(self) -> bool:
        return self._show_bones

    @property
    def bone_vertex_count(self) -> int:
        mesh = self._fracture_mesh
        if not self._show_bones or mesh is None:
            return 0
        return len(mesh.bone_segments) * 2

    def set_show_bones(self, value: bool) -> None:
        self._show_bones = bool(value)
        if not self._show_bones:
            self._hover_cut_token = None
        self.update()

    @property
    def hover_cut_token(self) -> str | None:
        return self._hover_cut_token

    def set_selected_cut_tokens(self, joint_tokens: tuple[str, ...]) -> None:
        self._selected_cut_tokens = tuple(joint_tokens)
        if self._hover_cut_token is not None and self._bone_segment_by_child_token(self._hover_cut_token) is None:
            self._hover_cut_token = None
        self.update()

    def paintGL(self) -> None:  # type: ignore[override]
        super().paintGL()
        if self._show_bones:
            self._paint_bone_overlay()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if (
            event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and self._show_bones
        ):
            token = self._hover_cut_token or self.pick_bone_segment_child_token(event.position().x(), event.position().y())
            if token:
                self.on_bone_cut_toggled(token)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._show_bones and not event.buttons() and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            token = self.pick_bone_segment_child_token(event.position().x(), event.position().y())
            if token != self._hover_cut_token:
                self._hover_cut_token = token
                self.update()
            event.accept()
            return
        if self._hover_cut_token is not None and not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._hover_cut_token = None
            self.update()
        super().mouseMoveEvent(event)

    def keyReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Control and self._hover_cut_token is not None:
            self._hover_cut_token = None
            self.update()
        super().keyReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        if self._hover_cut_token is not None:
            self._hover_cut_token = None
            self.update()
        super().leaveEvent(event)

    def pick_bone_segment_child_token(self, x: float, y: float, *, max_distance: float = 14.0) -> str | None:
        mesh = self._fracture_mesh
        if mesh is None or not mesh.bone_segments:
            return None
        best: tuple[float, str] | None = None
        for segment in mesh.bone_segments:
            parent = self._project_point_to_screen(segment.parent_position)
            child = self._project_point_to_screen(segment.child_position)
            if parent is None or child is None:
                continue
            distance = _distance_to_screen_segment(float(x), float(y), parent, child)
            candidate = (distance, segment.child_joint_token)
            if best is None or candidate < best:
                best = candidate
        if best is None or best[0] > max_distance:
            return None
        return best[1]

    def _bone_segment_by_child_token(self, joint_token: str) -> FracturePreviewBoneSegment | None:
        mesh = self._fracture_mesh
        if mesh is None:
            return None
        for segment in mesh.bone_segments:
            if segment.child_joint_token == joint_token:
                return segment
        return None

    def _project_point_to_screen(self, point: Vector3) -> tuple[float, float] | None:
        width = max(1, self.width())
        height = max(1, self.height())
        mapped = (self._projection_matrix() * self._view_matrix()).map(
            QVector3D(float(point.x), float(point.y), float(point.z))
        )
        ndc_x = float(mapped.x())
        ndc_y = float(mapped.y())
        if ndc_x < -1.5 or ndc_x > 1.5 or ndc_y < -1.5 or ndc_y > 1.5:
            return None
        return ((ndc_x + 1.0) * 0.5 * width, (1.0 - ndc_y) * 0.5 * height)

    def _build_grid_vertices_for_current_camera(self) -> np.ndarray:
        return _build_grid_vertices(self._target, self._radius, self._ground_y)

    def _upload_mesh(self) -> None:
        if self._program is None or self._vertex_buffer is None or self._vao is None:
            return
        payload = self._fracture_render_payload
        vertices = payload.vertex_components if payload is not None else np.asarray([], dtype=np.float32)
        self._vertex_count = int(len(vertices) // FRACTURE_VERTEX_STRIDE)
        self._vao.bind()
        self._vertex_buffer.bind()
        self._vertex_buffer.allocate(vertices.tobytes(), vertices.nbytes)
        self._program.bind()
        stride = FRACTURE_VERTEX_STRIDE * 4
        position_location = self._program.attributeLocation("position")
        normal_location = self._program.attributeLocation("normal")
        piece_tint_location = self._program.attributeLocation("pieceTint")
        if position_location >= 0:
            self._program.enableAttributeArray(position_location)
            self._program.setAttributeBuffer(position_location, GL_FLOAT, 0, 3, stride)
        if normal_location >= 0:
            self._program.enableAttributeArray(normal_location)
            self._program.setAttributeBuffer(normal_location, GL_FLOAT, 12, 3, stride)
        if piece_tint_location >= 0:
            self._program.enableAttributeArray(piece_tint_location)
            self._program.setAttributeBuffer(piece_tint_location, GL_FLOAT, 24, 4, stride)
        self._program.release()
        self._vertex_buffer.release()
        self._vao.release()
        self._mesh_dirty = False

    def _update_fracture_mesh_metrics(self, payload: FractureRenderPayload) -> None:
        if self._vertex_count <= 0:
            return
        min_x = payload.min_point.x
        min_y = payload.min_point.y
        min_z = payload.min_point.z
        max_x = payload.max_point.x
        max_y = payload.max_point.y
        max_z = payload.max_point.z
        self._ground_y = float(min_y)
        self._radius = max(
            0.001,
            math.sqrt((max_x - min_x) ** 2 + (max_y - min_y) ** 2 + (max_z - min_z) ** 2) * 0.5,
        )
        self._target = Vector3((min_x + max_x) * 0.5, (min_y + max_y) * 0.5, (min_z + max_z) * 0.5)
        self._distance = self._radius * 3.0

    def _paint_bone_overlay(self) -> None:
        mesh = self._fracture_mesh
        if mesh is None or not mesh.bone_segments:
            return
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            for segment in mesh.bone_segments:
                parent = self._project_point_to_screen(segment.parent_position)
                child = self._project_point_to_screen(segment.child_position)
                if parent is None or child is None:
                    continue
                selected = segment.is_selected_cut or segment.child_joint_token in self._selected_cut_tokens
                halo = QPen(QColor(6, 10, 12, 210), 7.0 if selected else 6.0)
                halo.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(halo)
                painter.drawLine(int(round(parent[0])), int(round(parent[1])), int(round(child[0])), int(round(child[1])))
                if selected:
                    pen = QPen(_qcolor_from_color4(segment.color, alpha=255), 4.5)
                else:
                    pen = QPen(_qcolor_from_color4(segment.color, alpha=230), 3.6)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawLine(int(round(parent[0])), int(round(parent[1])), int(round(child[0])), int(round(child[1])))
                if selected:
                    _paint_cut_marker(painter, child, QColor(255, 245, 185, 245), radius=6.5, width=2.0)
                    painter.setPen(QPen(QColor(255, 245, 185, 245), 1.0))
                    painter.drawText(int(round(child[0])) + 5, int(round(child[1])) - 5, segment.child_joint_token)
            if self._hover_cut_token is not None:
                hover_segment = self._bone_segment_by_child_token(self._hover_cut_token)
                if hover_segment is not None:
                    hover_point = self._project_point_to_screen(hover_segment.child_position)
                    if hover_point is not None:
                        _paint_cut_marker(painter, hover_point, QColor(155, 235, 255, 245), radius=8.5, width=2.2)
        finally:
            painter.end()


def build_fracture_viewport_mesh(
    preview: FracturePreviewResult,
    *,
    include_repeated_parts: bool = True,
) -> FractureViewportMesh:
    vertices = array("f")
    draw_sources: list[FractureDrawSource] = []
    draw_calls: list[FractureDrawCall] = []
    logical_triangle_count = 0
    uploaded_triangle_count = 0
    source_by_instance_key: dict[tuple[str, int], int] = {}

    def add_source(name: str, source_vertices: array, source_triangle_count: int) -> int:
        source_index = len(draw_sources)
        first_vertex = len(vertices) // FRACTURE_VERTEX_STRIDE
        vertices.extend(source_vertices)
        draw_sources.append(
            FractureDrawSource(
                name=name,
                first_vertex=first_vertex,
                vertex_count=len(source_vertices) // FRACTURE_VERTEX_STRIDE,
                triangle_count=source_triangle_count,
            )
        )
        return source_index

    for piece in preview.pieces:
        source_vertices = array("f")
        source_triangle_count = _append_mesh_triangles(
            source_vertices,
            piece.base_mesh,
            color=piece.color,
        )
        if source_triangle_count:
            source_index = add_source(piece.piece.name, source_vertices, source_triangle_count)
            draw_calls.append(_identity_draw_call(source_index))
            logical_triangle_count += source_triangle_count
            uploaded_triangle_count += source_triangle_count
    visible_instance_count = 0
    if include_repeated_parts:
        for instance in preview.instances:
            instance_key = (instance.prototype_key, instance.piece_index)
            source_index = source_by_instance_key.get(instance_key)
            if source_index is None:
                prototype = preview.prototypes[instance.prototype_key]
                source_vertices = array("f")
                source_triangle_count = _append_mesh_triangles(
                    source_vertices,
                    prototype.mesh,
                    color=instance.color,
                )
                source_index = add_source(
                    f"{prototype.source_name}_piece_{instance.piece_index:02d}",
                    source_vertices,
                    source_triangle_count,
                )
                source_by_instance_key[instance_key] = source_index
                uploaded_triangle_count += source_triangle_count
            source = draw_sources[source_index]
            draw_calls.append(
                FractureDrawCall(
                    source_index=source_index,
                    translate=instance.position,
                    orientation=instance.orientation,
                    scale=instance.scale,
                )
            )
            visible_instance_count += 1
            logical_triangle_count += source.triangle_count
    return FractureViewportMesh(
        name=f"{preview.plan.output_stem}_fracture_preview",
        vertex_components=vertices,
        triangle_count=logical_triangle_count,
        uploaded_triangle_count=uploaded_triangle_count,
        piece_count=len(preview.pieces),
        instance_count=visible_instance_count,
        draw_sources=tuple(draw_sources),
        draw_calls=tuple(draw_calls),
        bone_segments=preview.bone_segments,
    )


def _build_fracture_render_payload(
    mesh: FractureViewportMesh,
    *,
    tint_strength: float = FRACTURE_MATCAP_TINT_STRENGTH,
) -> FractureRenderPayload:
    source_vertices = np.asarray(mesh.vertex_components, dtype=np.float32).reshape((-1, FRACTURE_VERTEX_STRIDE))
    total_vertex_count = sum(mesh.draw_sources[draw_call.source_index].vertex_count for draw_call in mesh.draw_calls)
    if total_vertex_count <= 0:
        return FractureRenderPayload(
            vertex_components=np.asarray([], dtype=np.float32),
            min_point=Vector3(0.0, 0.0, 0.0),
            max_point=Vector3(0.0, 0.0, 0.0),
        )

    render_vertices = np.empty((total_vertex_count, FRACTURE_VERTEX_STRIDE), dtype=np.float32)
    min_values = np.array((math.inf, math.inf, math.inf), dtype=np.float32)
    max_values = np.array((-math.inf, -math.inf, -math.inf), dtype=np.float32)
    output_start = 0
    for draw_call in mesh.draw_calls:
        source = mesh.draw_sources[draw_call.source_index]
        start = source.first_vertex
        end = start + source.vertex_count
        if end <= start:
            continue
        output_end = output_start + source.vertex_count
        source_slice = source_vertices[start:end]
        positions = np.array(source_slice[:, 0:3], dtype=np.float32, copy=True)
        positions *= np.array((draw_call.scale.x, draw_call.scale.y, draw_call.scale.z), dtype=np.float32)
        positions = _rotate_positions(draw_call.orientation, positions)
        positions += np.array((draw_call.translate.x, draw_call.translate.y, draw_call.translate.z), dtype=np.float32)
        triangles = positions.reshape((-1, 3, 3))
        normals = np.cross(triangles[:, 1, :] - triangles[:, 0, :], triangles[:, 2, :] - triangles[:, 0, :])
        lengths = np.linalg.norm(normals, axis=1)
        safe_lengths = np.where(lengths > 1e-8, lengths, 1.0)
        normals = normals / safe_lengths[:, None]
        normals[lengths <= 1e-8] = np.array((0.0, 0.0, 1.0), dtype=np.float32)

        render_vertices[output_start:output_end, 0:3] = positions
        render_vertices[output_start:output_end, 3:6] = np.repeat(normals, 3, axis=0)
        render_vertices[output_start:output_end, 6:9] = source_slice[:, 6:9]
        render_vertices[output_start:output_end, 9] = float(max(0.0, min(1.0, tint_strength)))
        min_values = np.minimum(min_values, positions.min(axis=0))
        max_values = np.maximum(max_values, positions.max(axis=0))
        output_start = output_end

    render_vertices = render_vertices[:output_start].reshape(-1)
    return FractureRenderPayload(
        vertex_components=render_vertices,
        min_point=Vector3(float(min_values[0]), float(min_values[1]), float(min_values[2])),
        max_point=Vector3(float(max_values[0]), float(max_values[1]), float(max_values[2])),
    )


def _distance_to_screen_segment(
    x: float,
    y: float,
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-8:
        return math.sqrt((x - sx) ** 2 + (y - sy) ** 2)
    t = max(0.0, min(1.0, ((x - sx) * dx + (y - sy) * dy) / length_squared))
    px = sx + t * dx
    py = sy + t * dy
    return math.sqrt((x - px) ** 2 + (y - py) ** 2)


def _qcolor_from_color4(color: Color4, *, alpha: int) -> QColor:
    return QColor(
        max(0, min(255, int(round(float(color.r) * 255)))),
        max(0, min(255, int(round(float(color.g) * 255)))),
        max(0, min(255, int(round(float(color.b) * 255)))),
        max(0, min(255, int(alpha))),
    )


def _paint_cut_marker(
    painter: QPainter,
    screen_point: tuple[float, float],
    color: QColor,
    *,
    radius: float,
    width: float,
) -> None:
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(4, 8, 10, 230), width + 2.0))
    x = float(screen_point[0])
    y = float(screen_point[1])
    painter.drawEllipse(int(round(x - radius)), int(round(y - radius)), int(round(radius * 2)), int(round(radius * 2)))
    painter.setPen(QPen(color, width))
    painter.drawEllipse(int(round(x - radius)), int(round(y - radius)), int(round(radius * 2)), int(round(radius * 2)))


def _rotate_positions(q: Quaternion, positions: np.ndarray) -> np.ndarray:
    q_vector = np.array((q.i, q.j, q.k), dtype=np.float32)
    t = 2.0 * np.cross(q_vector, positions)
    return positions + float(q.real) * t + np.cross(q_vector, t)


def _identity_draw_call(source_index: int) -> FractureDrawCall:
    return FractureDrawCall(
        source_index=source_index,
        translate=Vector3(0.0, 0.0, 0.0),
        orientation=Quaternion(1.0, 0.0, 0.0, 0.0),
        scale=Vector3(1.0, 1.0, 1.0),
    )


def _append_mesh_triangles(
    vertices: array,
    mesh: GeometryBuffer,
    *,
    color: Color4,
    translate: Vector3 = Vector3(0.0, 0.0, 0.0),
    orientation: Quaternion = Quaternion(1.0, 0.0, 0.0, 0.0),
    scale: Vector3 = Vector3(1.0, 1.0, 1.0),
) -> int:
    points = tuple(_points(mesh))
    offset = 0
    triangle_count = 0
    for count in mesh.face_vertex_counts:
        indices = tuple(int(mesh.face_vertex_indices[offset + index]) for index in range(count))
        offset += count
        if count < 3:
            continue
        transformed = tuple(
            _transform_point(points[index], translate=translate, orientation=orientation, scale=scale)
            for index in indices
        )
        for index in range(1, count - 1):
            triangle = (transformed[0], transformed[index], transformed[index + 1])
            normal = _face_normal(triangle)
            for point in triangle:
                vertices.extend(
                    (
                        point.x,
                        point.y,
                        point.z,
                        normal.x,
                        normal.y,
                        normal.z,
                        color.r,
                        color.g,
                        color.b,
                        color.a,
                    )
                )
            triangle_count += 1
    return triangle_count


def _points(mesh: GeometryBuffer):
    for index in range(0, len(mesh.point_components), 3):
        yield Vector3(mesh.point_components[index], mesh.point_components[index + 1], mesh.point_components[index + 2])


def _transform_point(
    point: Vector3,
    *,
    translate: Vector3,
    orientation: Quaternion,
    scale: Vector3,
) -> Vector3:
    scaled = Vector3(point.x * scale.x, point.y * scale.y, point.z * scale.z)
    rotated = _rotate_vector(orientation, scaled)
    return Vector3(rotated.x + translate.x, rotated.y + translate.y, rotated.z + translate.z)


def _rotate_vector(q: Quaternion, value: Vector3) -> Vector3:
    x, y, z = _rotate_components(q, value.x, value.y, value.z)
    return Vector3(x, y, z)


def _rotate_components(q: Quaternion, x: float, y: float, z: float) -> tuple[float, float, float]:
    qw, qx, qy, qz = q.real, q.i, q.j, q.k
    tx = 2.0 * (qy * z - qz * y)
    ty = 2.0 * (qz * x - qx * z)
    tz = 2.0 * (qx * y - qy * x)
    return (
        x + qw * tx + (qy * tz - qz * ty),
        y + qw * ty + (qz * tx - qx * tz),
        z + qw * tz + (qx * ty - qy * tx),
    )


def _face_normal(points: tuple[Vector3, Vector3, Vector3]) -> Vector3:
    a, b, c = points
    ux = b.x - a.x
    uy = b.y - a.y
    uz = b.z - a.z
    vx = c.x - a.x
    vy = c.y - a.y
    vz = c.z - a.z
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    length = sqrt(nx * nx + ny * ny + nz * nz)
    if length <= 0.0:
        return Vector3(0.0, 0.0, 1.0)
    return Vector3(nx / length, ny / length, nz / length)
