"""Proxy mesh preview dialog.

Layer: UI.

This is a lightweight GPU 3D viewport for the same mesh object that export uses.
"""

from __future__ import annotations

import math
from array import array

from PySide6.QtCore import Qt, QSignalBlocker, QTimer
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSlider,
    QSpinBox,
)

from ..models import GeometryBuffer
from ..proxy_viewport_scene import build_proxy_viewport_scene
from ..proxy_mesh_service import (
    DEFAULT_PROXY_POLYCOUNT,
    MAX_PROXY_DENSITY_RESOLUTION,
    PROXY_METHOD_DENSITY_FIELD,
    ProxyMeshResult,
    ProxyMeshSettings,
)
from .preview_shell import PreviewShellDialog
from .material_controls import set_tooltip
from .viewport import ProxyViewport


PROXY_PREVIEW_MAX_POLYCOUNT = 100_000
BRANCH_PRUNE_SLIDER_EXPONENT = 4.0


class ProxyPreviewDialog(PreviewShellDialog):
    def __init__(
        self,
        *,
        settings: ProxyMeshSettings,
        on_settings_changed=None,
        preview_mesh: GeometryBuffer | None = None,
        initial_proxy: ProxyMeshResult | None = None,
        on_preview_ready=None,
        on_preview_closed=None,
        parent=None,
    ) -> None:
        super().__init__(title="Proxy Mesh Preview", parent=parent)
        self._on_settings_changed = on_settings_changed or (lambda settings: None)
        self._preview_mesh = preview_mesh
        self._current_proxy: ProxyMeshResult | None = initial_proxy
        self._on_preview_ready = on_preview_ready or (lambda proxy: None)
        self._on_preview_closed = on_preview_closed or (lambda settings, proxy: None)

        self.viewport = ProxyViewport(self)
        self.set_viewport_widget(self.viewport)
        if initial_proxy is not None:
            self.viewport.set_scene(build_proxy_viewport_scene(initial_proxy))

        settings_panel, settings_layout = self.create_settings_panel()

        title = QLabel("Proxy Mesh", settings_panel)
        title.setStyleSheet("font-weight: 700;")
        settings_layout.addWidget(title)

        _add_group_header(settings_layout, settings_panel, "Method")
        self.method_combo = QComboBox(settings_panel)
        self.method_combo.addItem("Density Field", PROXY_METHOD_DENSITY_FIELD)
        self.method_combo.setCurrentIndex(self.method_combo.findData(settings.method))
        method_label = QLabel("Method", settings_panel)
        set_tooltip(
            "Proxy generation algorithm. Density Field builds a compact shell from source geometry.",
            method_label,
            self.method_combo,
        )
        settings_layout.addWidget(method_label)
        settings_layout.addWidget(self.method_combo)

        _add_group_header(settings_layout, settings_panel, "Simplification")
        self.polycount_slider, self.polycount_spin = _build_int_slider_row(
            settings_panel,
            minimum=6,
            maximum=PROXY_PREVIEW_MAX_POLYCOUNT,
            value=min(PROXY_PREVIEW_MAX_POLYCOUNT, int(settings.final_polycount or DEFAULT_PROXY_POLYCOUNT)),
            step=100,
        )
        self.polycount_spin.setValue(min(PROXY_PREVIEW_MAX_POLYCOUNT, int(settings.final_polycount or DEFAULT_PROXY_POLYCOUNT)))
        polycount_label = QLabel("Final Polycount", settings_panel)
        set_tooltip(
            "Target proxy triangle budget. Lower is cheaper and rougher; higher preserves more shape.",
            polycount_label,
            self.polycount_slider,
            self.polycount_spin,
        )
        settings_layout.addWidget(polycount_label)
        settings_layout.addLayout(_slider_row(self.polycount_slider, self.polycount_spin))

        _add_group_header(settings_layout, settings_panel, "Extraction")
        self.inflation_slider, self.inflation_spin = _build_float_slider_row(
            settings_panel,
            minimum=0.1,
            maximum=5.0,
            value=float(settings.bounds_inflation),
            step=0.01,
            scale=100,
        )
        inflation_label = QLabel("Bounds Inflation", settings_panel)
        set_tooltip(
            "Expands the density volume around the tree. Lower fits tighter; higher leaves more outside margin.",
            inflation_label,
            self.inflation_slider,
            self.inflation_spin,
        )
        settings_layout.addWidget(inflation_label)
        settings_layout.addLayout(_slider_row(self.inflation_slider, self.inflation_spin))

        self.density_resolution_slider, self.density_resolution_spin = _build_int_slider_row(
            settings_panel,
            minimum=2,
            maximum=MAX_PROXY_DENSITY_RESOLUTION,
            value=int(settings.density_resolution),
            step=1,
        )
        density_label = QLabel("Density Resolution", settings_panel)
        set_tooltip(
            "Voxel resolution for proxy extraction. Lower is faster and softer; higher captures finer structure.",
            density_label,
            self.density_resolution_slider,
            self.density_resolution_spin,
        )
        settings_layout.addWidget(density_label)
        settings_layout.addLayout(_slider_row(self.density_resolution_slider, self.density_resolution_spin))

        _add_group_header(settings_layout, settings_panel, "Source Priority")
        self.base_priority_slider, self.base_priority_spin = _build_float_slider_row(
            settings_panel,
            minimum=0.0,
            maximum=1.0,
            value=float(settings.base_mesh_priority),
            step=0.01,
            scale=100,
        )
        base_priority_label = QLabel("Base Mesh Priority", settings_panel)
        set_tooltip(
            "Reserves proxy budget for trunk/base geometry. Lower favors foliage volume; higher preserves base mesh.",
            base_priority_label,
            self.base_priority_slider,
            self.base_priority_spin,
        )
        settings_layout.addWidget(base_priority_label)
        settings_layout.addLayout(_slider_row(self.base_priority_slider, self.base_priority_spin))

        self.branch_prune_slider, self.branch_prune_spin = _build_branch_prune_slider_row(
            settings_panel,
            value=float(settings.branch_prune_aggression),
        )
        branch_prune_label = QLabel("Remove Small Branches", settings_panel)
        set_tooltip(
            "Removes the smallest disconnected base-mesh islands first. Lower keeps twigs; higher leaves larger branches only.",
            branch_prune_label,
            self.branch_prune_slider,
            self.branch_prune_spin,
        )
        settings_layout.addWidget(branch_prune_label)
        settings_layout.addLayout(_slider_row(self.branch_prune_slider, self.branch_prune_spin))

        self.status_label = QLabel("", settings_panel)
        self.status_label.setWordWrap(True)
        settings_layout.addWidget(self.status_label)
        settings_layout.addStretch(1)
        if initial_proxy is not None:
            self.status_label.setText(
                f"{initial_proxy.mesh.face_count} polygons / {initial_proxy.mesh.point_count} points"
            )

        self.method_combo.currentIndexChanged.connect(lambda _index: self.regenerate())
        self.polycount_slider.sliderReleased.connect(self.regenerate)
        self.polycount_spin.editingFinished.connect(self.regenerate)
        self.inflation_slider.sliderReleased.connect(self.regenerate)
        self.inflation_spin.editingFinished.connect(self.regenerate)
        self.density_resolution_slider.sliderReleased.connect(self.regenerate)
        self.density_resolution_spin.editingFinished.connect(self.regenerate)
        self.base_priority_slider.sliderReleased.connect(self.regenerate)
        self.base_priority_spin.editingFinished.connect(self.regenerate)
        self.branch_prune_slider.sliderReleased.connect(self.regenerate)
        self.branch_prune_spin.editingFinished.connect(self.regenerate)
        QTimer.singleShot(0, self.regenerate)

    @property
    def current_proxy(self) -> ProxyMeshResult | None:
        return self._current_proxy

    def settings(self) -> ProxyMeshSettings:
        return ProxyMeshSettings(
            method=str(self.method_combo.currentData() or PROXY_METHOD_DENSITY_FIELD),
            final_polycount=int(self.polycount_spin.value()),
            bounds_inflation=float(self.inflation_spin.value()),
            density_resolution=int(self.density_resolution_spin.value()),
            base_mesh_priority=float(self.base_priority_spin.value()),
            branch_prune_aggression=float(self.branch_prune_spin.value()),
        )

    def regenerate(self) -> None:
        settings = self.settings()
        if self._preview_mesh is not None:
            self._set_current_proxy(ProxyMeshResult(
                mesh=self._preview_mesh,
                settings=settings,
                method="viewport_cube",
                source_instance_count=0,
                included_base_mesh=False,
            ))
            self.status_label.setText(
                f"Viewport cube preview: {self._preview_mesh.face_count} polygons / "
                f"{self._preview_mesh.point_count} points"
            )
            return
        self.status_label.setText("Updating..." if self._current_proxy is not None else "Generating...")
        self._on_settings_changed(settings)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._on_preview_closed(self.settings(), self._current_proxy)
        super().closeEvent(event)

    def set_loading(self, message: str = "Generating...") -> None:
        self.status_label.setText(message)

    def set_error(self, message: str) -> None:
        self.status_label.setText(message)

    def set_proxy(self, proxy: ProxyMeshResult) -> None:
        self._set_current_proxy(proxy)
        self.status_label.setText(f"{proxy.mesh.face_count} polygons / {proxy.mesh.point_count} points")

    def _set_current_proxy(self, proxy: ProxyMeshResult) -> None:
        had_mesh = self.viewport.has_mesh()
        self._current_proxy = proxy
        self.viewport.set_scene(build_proxy_viewport_scene(proxy), frame_camera=not had_mesh)
        self._on_preview_ready(proxy)


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
    slider.setPageStep(step * 4)
    slider.setValue(value)

    spin = QSpinBox(parent)
    spin.setRange(minimum, maximum)
    spin.setSingleStep(step)
    spin.setValue(value)
    spin.setKeyboardTracking(False)
    spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    digit_width = spin.fontMetrics().horizontalAdvance(str(maximum))
    spin.setFixedWidth(max(92, digit_width + 24))

    slider.valueChanged.connect(lambda raw: _sync_int_spin(spin, raw, step))
    spin.editingFinished.connect(lambda: _sync_int_slider(slider, spin.value()))
    return slider, spin


def _add_group_header(layout, parent, title: str) -> None:
    line = QFrame(parent)
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Plain)
    label = QLabel(title, parent)
    label.setObjectName("MutedLabel")
    label.setStyleSheet("font-weight: 700;")
    layout.addSpacing(6)
    layout.addWidget(line)
    layout.addSpacing(4)
    layout.addWidget(label)


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
    slider.setValue(int(round(value * scale)))

    spin = QDoubleSpinBox(parent)
    spin.setRange(minimum, maximum)
    spin.setSingleStep(step)
    spin.setDecimals(2)
    spin.setValue(value)
    spin.setKeyboardTracking(False)
    spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    spin.setFixedWidth(70)

    slider.valueChanged.connect(lambda raw: _sync_float_spin(spin, raw, scale))
    spin.editingFinished.connect(lambda: _sync_float_slider(slider, spin.value(), scale))
    return slider, spin


def _build_branch_prune_slider_row(parent, *, value: float) -> tuple[QSlider, QDoubleSpinBox]:
    slider = QSlider(Qt.Orientation.Horizontal, parent)
    slider.setRange(0, 100)
    slider.setSingleStep(1)
    slider.setPageStep(4)
    slider.setValue(_branch_prune_value_to_slider(value))

    spin = QDoubleSpinBox(parent)
    spin.setRange(0.0, 1.0)
    spin.setSingleStep(0.001)
    spin.setDecimals(4)
    spin.setValue(max(0.0, min(1.0, value)))
    spin.setKeyboardTracking(False)
    spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    spin.setFixedWidth(82)

    slider.valueChanged.connect(lambda raw: _sync_branch_prune_spin(spin, raw))
    spin.editingFinished.connect(lambda: _sync_branch_prune_slider(slider, spin.value()))
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


def _sync_branch_prune_spin(spin: QDoubleSpinBox, slider_value: int) -> None:
    with QSignalBlocker(spin):
        spin.setValue(_branch_prune_slider_to_value(slider_value))


def _sync_branch_prune_slider(slider: QSlider, value: float) -> None:
    with QSignalBlocker(slider):
        slider.setValue(_branch_prune_value_to_slider(value))


def _branch_prune_slider_to_value(slider_value: int) -> float:
    position = max(0.0, min(1.0, float(slider_value) / 100.0))
    return 1.0 - ((1.0 - position) ** BRANCH_PRUNE_SLIDER_EXPONENT)


def _branch_prune_value_to_slider(value: float) -> int:
    clamped = max(0.0, min(1.0, value))
    if clamped <= 0.0:
        return 0
    if clamped >= 1.0:
        return 100
    position = 1.0 - math.pow(1.0 - clamped, 1.0 / BRANCH_PRUNE_SLIDER_EXPONENT)
    return int(round(position * 100.0))


def build_preview_cube_mesh() -> GeometryBuffer:
    return GeometryBuffer(
        name="ViewportCubePreview",
        point_components=array(
            "f",
            (
                -0.5,
                -0.5,
                -0.5,
                0.5,
                -0.5,
                -0.5,
                0.5,
                0.5,
                -0.5,
                -0.5,
                0.5,
                -0.5,
                -0.5,
                -0.5,
                0.5,
                0.5,
                -0.5,
                0.5,
                0.5,
                0.5,
                0.5,
                -0.5,
                0.5,
                0.5,
            ),
        ),
        face_vertex_counts=array("i", (4, 4, 4, 4, 4, 4)),
        face_vertex_indices=array(
            "i",
            (
                0,
                3,
                2,
                1,
                4,
                5,
                6,
                7,
                0,
                1,
                5,
                4,
                1,
                2,
                6,
                5,
                2,
                3,
                7,
                6,
                3,
                0,
                4,
                7,
            ),
        ),
    )
