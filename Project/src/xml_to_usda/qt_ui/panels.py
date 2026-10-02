"""Qt tab panels for the PySide6 shell.

Layer: UI.

These widgets render operator-facing lists for wind, geometry, and materials
while delegating discovery and conversion semantics to the existing application
services.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QSignalBlocker, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..asset_paths import normalize_unreal_asset_path
from ..discovery_service import PrototypeMaterialSlotRowSpec
from ..fracture_preview_service import FracturePreviewSettings
from ..models import (
    BaseMaterialOverride,
    CpuProfile,
    DynamicWindData,
    DynamicWindSimulationGroup,
    FbxMaterialMode,
    FbxMaterialSlotOverride,
    PrototypeSourceConfig,
    PrototypeSourceMode,
    SkinningQuality,
    ScatteredRigMode,
    UdimMaterialSetting,
    UdimMode,
)
from ..proxy_mesh_service import ProxyMeshSettings
from ..settings_service import (
    BaseMaterialSettingRecord,
    FbxMaterialSlotSettingRecord,
    PartSourceSettingRecord,
    WindGroupSettingRecord,
)
from .scrollbars import keep_vertical_scrollbar_visible
from .material_controls import (
    MaterialUdimRow,
    MaterialUdimValue,
    NoWheelComboBox,
    make_path_edit,
    make_udim_controls,
    make_udim_id_cell,
    set_tooltip,
    set_combo_value,
)
from .part_source_controls import PartSourceMaterialValue
from .preview_shell import apply_compact_preview_panel_style


_SKINNING_TICK_LABELS = (
    ("1 weight", "Default and cheapest. Rigid skinning works well for many trees."),
    ("2 weights", "Soft branch bending. Attachment artifacts may still be visible."),
    ("3 weights\n(Expensive)", "Soft bending with fewer attachment artifacts, at higher runtime cost."),
    ("4 weights\n(Expensive)", "Most visually stable deformation, with the highest runtime cost."),
)
_SLIDER_TO_SCATTERED_MODE = {
    1: ScatteredRigMode.WHOLE_MESH_SKINNED,
    2: ScatteredRigMode.PER_CLUSTER_RIGID,
    3: ScatteredRigMode.PER_CLUSTER_SKINNED,
    4: ScatteredRigMode.PER_INSTANCE_RIGID,
}
_SCATTERED_MODE_TO_SLIDER = {mode: value for value, mode in _SLIDER_TO_SCATTERED_MODE.items()}


def _make_scroll_host(parent: QWidget) -> tuple[QWidget, QVBoxLayout]:
    container = QWidget(parent)
    container.setObjectName("ScrollContainer")
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)
    layout.addStretch(1)
    return container, layout


def _make_scroll_area(parent: QWidget) -> QScrollArea:
    scroll = QScrollArea(parent)
    keep_vertical_scrollbar_visible(scroll)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.viewport().setObjectName("ScrollViewport")
    scroll.viewport().setAutoFillBackground(False)
    return scroll


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        if child_layout is not None:
            _clear_layout(child_layout)


def _rebuild_scroll_layout(layout: QVBoxLayout) -> None:
    _clear_layout(layout)
    layout.addStretch(1)


def _make_path_edit(
    text: str,
    parent: QWidget,
    *,
    placeholder: str,
    max_width: int | None = None,
) -> QLineEdit:
    return make_path_edit(text, parent, placeholder=placeholder, max_width=max_width)


def _make_udim_controls(parent: QWidget, *, mode: UdimMode, udim_id: int) -> tuple[NoWheelComboBox, QSpinBox]:
    return make_udim_controls(parent, mode=mode, udim_id=udim_id)


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setKeyboardTracking(False)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()


class SliderSpinEditor(QWidget):
    valueChanged = Signal(float)

    def __init__(
        self,
        *,
        minimum: float,
        maximum: float,
        step: float,
        value: float,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._scale = 100
        self._slider_minimum = int(round(minimum * self._scale))
        self._slider_maximum = int(round(maximum * self._scale))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(self._slider_minimum, self._slider_maximum)
        self.slider.setSingleStep(max(1, int(round(step * self._scale))))
        self.slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.slider, 1)

        self.spin = NoWheelDoubleSpinBox(self)
        self.spin.setRange(minimum, maximum)
        self.spin.setDecimals(2)
        self.spin.setSingleStep(step)
        self.spin.setMinimumWidth(88)
        layout.addWidget(self.spin, 0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.slider.valueChanged.connect(self._handle_slider_changed)
        self.spin.valueChanged.connect(self._handle_spin_changed)
        self.setValue(value)

    def value(self) -> float:
        return float(self.spin.value())

    def setValue(self, value: float) -> None:
        clamped_value = max(self.spin.minimum(), min(self.spin.maximum(), float(value)))
        with QSignalBlocker(self.slider), QSignalBlocker(self.spin):
            self.spin.setValue(clamped_value)
            self.slider.setValue(self._clamp_slider_value(clamped_value))

    def _handle_slider_changed(self, raw_value: int) -> None:
        value = raw_value / self._scale
        with QSignalBlocker(self.spin):
            self.spin.setValue(value)
        self.valueChanged.emit(self.value())

    def _handle_spin_changed(self, value: float) -> None:
        with QSignalBlocker(self.slider):
            self.slider.setValue(self._clamp_slider_value(value))
        self.valueChanged.emit(float(value))

    def _clamp_slider_value(self, value: float) -> int:
        raw_value = int(round(float(value) * self._scale))
        return max(self._slider_minimum, min(self._slider_maximum, raw_value))


class DiscreteSlider(QSlider):
    """Integer slider supporting both direct track clicks and handle dragging."""

    def __init__(self, orientation: Qt.Orientation, parent=None) -> None:
        super().__init__(orientation, parent)
        self._track_drag_active = False

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderHandle,
            self,
        )
        if handle.contains(event.position().toPoint()):
            super().mousePressEvent(event)
            return
        self._track_drag_active = True
        self.setSliderDown(True)
        self.setValue(self._value_at(event.position().toPoint()))
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if not self._track_drag_active:
            super().mouseMoveEvent(event)
            return
        self.setValue(self._value_at(event.position().toPoint()))
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if not self._track_drag_active:
            super().mouseReleaseEvent(event)
            return
        self.setValue(self._value_at(event.position().toPoint()))
        self._track_drag_active = False
        self.setSliderDown(False)
        event.accept()

    def _value_at(self, position: QPoint) -> int:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderGroove,
            self,
        )
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderHandle,
            self,
        )
        span = max(1, groove.width() - handle.width())
        handle_position = position.x() - groove.x() - handle.width() // 2
        return QStyle.sliderValueFromPosition(
            self.minimum(),
            self.maximum(),
            handle_position,
            span,
            option.upsideDown,
        )


class SkinningTickLabel(QLabel):
    selected = Signal(int)

    def __init__(self, value: int, text: str, tooltip: str, parent=None) -> None:
        super().__init__(text, parent)
        self.value = value
        self.setObjectName("SkinningTickLabel")
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if self.isEnabled() and event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.value)
            event.accept()
            return
        super().mousePressEvent(event)


class SkinningTickLabels(QWidget):
    """Place labels below the exact styled handle centers for each tick."""

    def __init__(self, slider: QSlider, labels: tuple[tuple[str, str], ...], parent=None) -> None:
        super().__init__(parent)
        self._slider = slider
        self.labels = tuple(
            SkinningTickLabel(value, text, tooltip, self)
            for value, (text, tooltip) in zip(range(slider.minimum(), slider.maximum() + 1), labels, strict=True)
        )
        for label in self.labels:
            label.selected.connect(slider.setValue)
        slider.valueChanged.connect(self._set_selected)
        slider.installEventFilter(self)
        self._update_label_metrics()
        self._set_selected(slider.value())
        QTimer.singleShot(0, self._update_label_metrics)

    def set_labels(
        self,
        labels: tuple[tuple[str, str], ...],
        *,
        enabled_values: frozenset[int] | None = None,
    ) -> None:
        if len(labels) != len(self.labels):
            raise ValueError("Tick label count must match the slider range.")
        enabled_values = enabled_values or frozenset(label.value for label in self.labels)
        for label, (text, tooltip) in zip(self.labels, labels, strict=True):
            label.setText(text)
            label.setToolTip(tooltip)
            label.setEnabled(label.value in enabled_values)
            label.setCursor(
                Qt.CursorShape.PointingHandCursor if label.isEnabled() else Qt.CursorShape.ArrowCursor
            )
        self._set_selected(self._slider.value())
        self._update_label_metrics()

    def edge_margin(self) -> int:
        return max(label.sizeHint().width() for label in self.labels) // 2

    def _set_selected(self, _selected_value: int) -> None:
        selected_value = self._slider.value()
        for label in self.labels:
            font = label.font()
            font.setBold(label.isEnabled() and label.value == selected_value)
            label.setFont(font)
        self._layout_labels()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._layout_labels()

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if watched is self._slider and event.type() in {
            QEvent.Type.Move,
            QEvent.Type.Resize,
            QEvent.Type.StyleChange,
        }:
            QTimer.singleShot(0, self._layout_labels)
        return super().eventFilter(watched, event)

    def changeEvent(self, event) -> None:  # type: ignore[override]
        super().changeEvent(event)
        if event.type() in {QEvent.Type.StyleChange, QEvent.Type.FontChange}:
            QTimer.singleShot(0, self._update_label_metrics)

    def _update_label_metrics(self) -> None:
        bold_heights: list[int] = []
        for label in self.labels:
            selected = label.font().bold()
            normal_font = label.font()
            normal_font.setBold(False)
            bold_font = label.font()
            bold_font.setBold(True)
            label.setMinimumWidth(0)
            label.setMaximumWidth(16_777_215)
            label.setFont(bold_font)
            bold_size = label.sizeHint()
            label.setFixedWidth(bold_size.width())
            bold_heights.append(bold_size.height())
            label.setFont(bold_font if selected else normal_font)
        self.setMinimumHeight(max(bold_heights) + 4)
        self._layout_labels()

    def _layout_labels(self) -> None:
        if not self.width() or not self._slider.width():
            return
        option = QStyleOptionSlider()
        self._slider.initStyleOption(option)
        groove = self._slider.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderGroove,
            self._slider,
        )
        handle = self._slider.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderHandle,
            self._slider,
        )
        span = max(1, groove.width() - handle.width())
        slider_offset = self.mapFromGlobal(self._slider.mapToGlobal(QPoint(0, 0))).x()
        for label in self.labels:
            handle_position = QStyle.sliderPositionFromValue(
                self._slider.minimum(),
                self._slider.maximum(),
                label.value,
                span,
                option.upsideDown,
            )
            center = slider_offset + groove.x() + handle.width() // 2 + handle_position
            width = label.width()
            label.setGeometry(center - width // 2, 0, width, self.height())


@dataclass(frozen=True)
class GeometryRowState:
    source_key: str
    source_name: str
    source_mesh_id: int | None
    instance_count: int
    source_mode: PrototypeSourceMode
    unreal_asset_path: str
    fbx_path: str


@dataclass
class WindRowWidgets:
    group_index: int
    branch_order: int
    trunk_checkbox: QCheckBox
    dual_checkbox: QCheckBox
    influence_spin: SliderSpinEditor
    min_influence_spin: SliderSpinEditor
    max_influence_spin: SliderSpinEditor
    shift_spin: SliderSpinEditor
    single_frame: QFrame
    dual_frame: QFrame


class WindTabPanel(QWidget):
    def __init__(self, *, on_change, on_refresh_requested, on_preview_requested) -> None:
        super().__init__()
        apply_compact_preview_panel_style(self)
        self._on_change = on_change
        self._on_refresh_requested = on_refresh_requested
        self._on_preview_requested = on_preview_requested
        self._persisted_settings: dict[str, WindGroupSettingRecord] = {}
        self._rows: list[WindRowWidgets] = []
        self._scattered_parts_active = False
        self._scattered_parts_clustered = False
        self._scattered_cluster_count = 0
        self._scattered_instance_count = 0
        self._normal_skinning_quality = SkinningQuality.ONE_WEIGHT
        self._scattered_rig_mode = ScatteredRigMode.PER_CLUSTER_SKINNED

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        controls = QFrame(self)
        controls.setObjectName("PanelCard")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(16, 12, 16, 12)
        controls_layout.setSpacing(12)

        self.ground_cover_checkbox = QCheckBox("Ground Cover", controls)
        self.ground_cover_checkbox.toggled.connect(lambda _checked: self._on_change())
        self.skinning_label = QLabel("Skinning Quality", controls)
        self.skinning_quality_slider = DiscreteSlider(Qt.Orientation.Horizontal, controls)
        self.skinning_quality_slider.setRange(1, 4)
        self.skinning_quality_slider.setValue(1)
        self.skinning_quality_slider.setSingleStep(1)
        self.skinning_quality_slider.setPageStep(1)
        self.skinning_quality_slider.setTickInterval(1)
        self.skinning_quality_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.skinning_quality_slider.setAccessibleName("Skinning Quality")
        self.skinning_quality_slider.valueChanged.connect(self._handle_skinning_slider_changed)
        self.skinning_tick_labels = SkinningTickLabels(
            self.skinning_quality_slider,
            _SKINNING_TICK_LABELS,
            controls,
        )
        self.skinning_description_label = QLabel(controls)
        self.skinning_description_label.setWordWrap(True)
        self.skinning_description_label.setObjectName("MutedText")
        self.scattered_orientation_checkbox = QCheckBox(
            "Average Instance Orientation",
            controls,
        )
        self.scattered_orientation_checkbox.setChecked(False)
        self.scattered_orientation_checkbox.toggled.connect(lambda _checked: self._on_change())
        self.scattered_orientation_checkbox.hide()
        self.skinning_slider_row = QHBoxLayout()
        self.skinning_slider_row.setContentsMargins(self.skinning_tick_labels.edge_margin(), 0, self.skinning_tick_labels.edge_margin(), 0)
        self.skinning_slider_row.addWidget(self.skinning_quality_slider)
        self.gust_spin = self._make_spin(0.0, 1.0, 0.01, 0.0)
        self.gust_spin.valueChanged.connect(lambda _value: self._on_change())
        set_tooltip(
            "Marks the tree as low vegetation. Off uses normal tree wind; on uses ground-cover wind behavior.",
            self.ground_cover_checkbox,
        )
        set_tooltip(
            "Reduces gust strength globally. Lower keeps sharper gusts; higher softens sudden gust motion.",
            self.gust_spin,
        )
        set_tooltip(
            "Maximum skinning influences per base-mesh vertex. 1 is rigid and cheapest; 2 uses the soft child-attachment collar; 3 and 4 preserve deeper inherited deformation at higher runtime cost.",
            self.skinning_label,
            self.skinning_quality_slider,
        )
        set_tooltip(
            "Uses the surface-area-weighted average of member instances' rotated local +Y axes, so larger instances contribute more. Whole Mesh averages all instances; cluster modes average each cluster; Per Instance uses its own axis. Off keeps deterministic near-up bones.",
            self.scattered_orientation_checkbox,
        )
        # Wind inspection stays beside the controls so the group list keeps the
        # vertical room needed for more than one group card.
        self.refresh_button = QPushButton("Refresh Wind Groups", controls)
        self.refresh_button.setObjectName("WindRefreshButton")
        self.refresh_button.clicked.connect(self._on_refresh_requested)
        self.preview_button = QPushButton("Advanced Wind Settings", controls)
        self.preview_button.setObjectName("WindPreviewButton")
        self.preview_button.clicked.connect(self._on_preview_requested)
        self.preview_button.setToolTip("Opens advanced Wind Preview settings for the selected XML.")

        skinning_controls = QWidget(controls)
        skinning_layout = QGridLayout(skinning_controls)
        skinning_layout.setContentsMargins(0, 0, 0, 0)
        skinning_layout.setHorizontalSpacing(8)
        skinning_layout.setVerticalSpacing(4)
        skinning_layout.addWidget(self.ground_cover_checkbox, 0, 0)
        skinning_layout.addWidget(self.skinning_label, 0, 1)
        skinning_layout.addWidget(self.scattered_orientation_checkbox, 0, 2)
        skinning_layout.addLayout(self.skinning_slider_row, 1, 0, 1, 3)
        skinning_layout.addWidget(self.skinning_tick_labels, 2, 0, 1, 3)
        self.skinning_description_label.hide()
        gust_label = QLabel("Gust Attenuation", controls)
        set_tooltip(self.gust_spin.toolTip(), gust_label)
        skinning_layout.addWidget(gust_label, 3, 0)
        skinning_layout.addWidget(self.gust_spin, 3, 1, 1, 2)
        skinning_layout.setColumnStretch(1, 1)

        actions = QWidget(controls)
        actions.setMinimumWidth(286)
        actions_layout = QVBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(6)
        action_top_row = QHBoxLayout()
        action_top_row.setContentsMargins(0, 0, 0, 0)
        action_top_row.setSpacing(6)
        self.total_bones_label = QLabel("Total bones: 0", actions)
        self.total_bones_label.setObjectName("WindTotalBones")
        self.total_bones_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.total_bones_label.setMinimumWidth(116)
        action_top_row.addWidget(self.total_bones_label, 1)
        action_top_row.addWidget(self.refresh_button, 0)
        actions_layout.addLayout(action_top_row)
        actions_layout.addWidget(self.preview_button)

        controls_layout.addWidget(skinning_controls, 2)
        controls_layout.addWidget(actions, 1)
        outer.addWidget(controls)

        self.scroll = _make_scroll_area(self)
        self.scroll_container, self.scroll_layout = _make_scroll_host(self)
        self.scroll.setWidget(self.scroll_container)
        outer.addWidget(self.scroll, 1)

    def set_persisted_settings(self, settings: dict[str, WindGroupSettingRecord]) -> None:
        self._persisted_settings = dict(settings)

    def clear(self) -> None:
        self._rows.clear()
        self.total_bones_label.setText("Total bones: 0")
        _rebuild_scroll_layout(self.scroll_layout)

    def set_global_options(
        self,
        *,
        is_ground_cover: bool,
        gust_attenuation: float,
        skinning_quality: SkinningQuality | int = SkinningQuality.ONE_WEIGHT,
        scattered_rig_mode: ScatteredRigMode | str = ScatteredRigMode.PER_CLUSTER_SKINNED,
        orient_scattered_bones_from_instances: bool = False,
    ) -> None:
        with QSignalBlocker(self.ground_cover_checkbox):
            self.ground_cover_checkbox.setChecked(bool(is_ground_cover))
        with QSignalBlocker(self.gust_spin):
            self.gust_spin.setValue(float(gust_attenuation))
        self._normal_skinning_quality = SkinningQuality.parse(skinning_quality)
        self._scattered_rig_mode = ScatteredRigMode.parse(scattered_rig_mode)
        with QSignalBlocker(self.scattered_orientation_checkbox):
            self.scattered_orientation_checkbox.setChecked(
                bool(orient_scattered_bones_from_instances)
            )
        if not self._scattered_parts_active:
            with QSignalBlocker(self.skinning_quality_slider):
                self.skinning_quality_slider.setValue(int(self._normal_skinning_quality))
        self._update_skinning_description()

    def is_ground_cover_enabled(self) -> bool:
        return bool(self.ground_cover_checkbox.isChecked())

    def gust_attenuation(self) -> float:
        return float(self.gust_spin.value())

    def skinning_quality(self) -> SkinningQuality:
        return self._normal_skinning_quality

    def effective_skinning_quality(self) -> SkinningQuality:
        return SkinningQuality.TWO_WEIGHTS if self._scattered_parts_active else self._normal_skinning_quality

    def scattered_rig_mode(self) -> ScatteredRigMode:
        return self._scattered_rig_mode

    def orient_scattered_bones_from_instances(self) -> bool:
        return bool(self.scattered_orientation_checkbox.isChecked())

    def set_scattered_parts_mode(
        self,
        *,
        active: bool,
        clustered: bool = False,
        cluster_count: int = 0,
        instance_count: int = 0,
    ) -> None:
        self._scattered_parts_active = bool(active)
        self._scattered_parts_clustered = bool(active and clustered)
        self._scattered_cluster_count = max(0, int(cluster_count))
        self._scattered_instance_count = max(0, int(instance_count))
        self.scattered_orientation_checkbox.setVisible(self._scattered_parts_active)
        if self._scattered_parts_active:
            if not self._scattered_parts_clustered and self._scattered_rig_mode in {
                ScatteredRigMode.PER_CLUSTER_RIGID,
                ScatteredRigMode.PER_CLUSTER_SKINNED,
            }:
                self._scattered_rig_mode = ScatteredRigMode.WHOLE_MESH_SKINNED
            self.skinning_label.setText("Scattered Rig Mode")
            self.skinning_quality_slider.setAccessibleName("Scattered Rig Mode")
            value = _SCATTERED_MODE_TO_SLIDER[self._scattered_rig_mode]
            with QSignalBlocker(self.skinning_quality_slider):
                self.skinning_quality_slider.setValue(value)
            enabled = frozenset({1, 2, 3, 4} if self._scattered_parts_clustered else {1, 4})
            self.skinning_tick_labels.set_labels(self._scattered_tick_labels(), enabled_values=enabled)
            tooltip = "Selects how leaf-only repeated geometry is baked and bound to the synthetic near-up skeleton."
        else:
            self.skinning_label.setText("Skinning Quality")
            self.skinning_quality_slider.setAccessibleName("Skinning Quality")
            with QSignalBlocker(self.skinning_quality_slider):
                self.skinning_quality_slider.setValue(int(self._normal_skinning_quality))
            self.skinning_tick_labels.set_labels(_SKINNING_TICK_LABELS)
            tooltip = (
                "Maximum skinning influences per base-mesh vertex. 1 is rigid and cheapest; "
                "2 uses the soft child-attachment collar; 3 and 4 preserve deeper inherited deformation."
            )
        set_tooltip(tooltip, self.skinning_label, self.skinning_quality_slider)
        margin = self.skinning_tick_labels.edge_margin()
        self.skinning_slider_row.setContentsMargins(margin, 0, margin, 0)
        self._update_skinning_description()

    def _handle_skinning_slider_changed(self, value: int) -> None:
        if self._scattered_parts_active:
            if not self._scattered_parts_clustered and value in {2, 3}:
                value = 1 if value == 2 else 4
                with QSignalBlocker(self.skinning_quality_slider):
                    self.skinning_quality_slider.setValue(value)
            self._scattered_rig_mode = _SLIDER_TO_SCATTERED_MODE[value]
        else:
            self._normal_skinning_quality = SkinningQuality(value)
        self._update_skinning_description()
        self._on_change()

    def _scattered_tick_labels(self) -> tuple[tuple[str, str], ...]:
        unavailable = "Unavailable: this source has no structural clusters."
        return (
            ("Whole Mesh\n(Skinned)", "Bakes every instance into one deforming two-weight mesh."),
            ("Per Cluster\n(Rigid)", "Keeps instancing and assigns one rigid near-up joint per structural cluster." if self._scattered_parts_clustered else unavailable),
            ("Per Cluster\n(Skinned)", "Bakes every instance and applies two-weight deformation per structural cluster." if self._scattered_parts_clustered else unavailable),
            ("Per Instance\n(Rigid · Warning)", "Assigns one rigid joint per source instance and can create a very large skeleton."),
        )

    def _update_skinning_description(self) -> None:
        if not self._scattered_parts_active:
            descriptions = {
                SkinningQuality.ONE_WEIGHT: "Rigid single-weight skinning. Lowest runtime cost.",
                SkinningQuality.TWO_WEIGHTS: "Two-weight bending at branch attachments.",
                SkinningQuality.THREE_WEIGHTS: "Inherited three-weight deformation. Expensive.",
                SkinningQuality.FOUR_WEIGHTS: "Inherited four-weight deformation. Most expensive.",
            }
            self.skinning_description_label.setText(descriptions[self._normal_skinning_quality])
            return
        joint_count = self._scattered_cluster_count + 1
        descriptions = {
            ScatteredRigMode.WHOLE_MESH_SKINNED: "All blades become one real mesh with two-weight deformation · 2 joints.",
            ScatteredRigMode.PER_CLUSTER_RIGID: f"Instances stay instanced; one rigid near-up joint per cluster · {joint_count:,} joints.",
            ScatteredRigMode.PER_CLUSTER_SKINNED: f"All blades become real geometry with one deform joint per cluster · {joint_count:,} joints.",
            ScatteredRigMode.PER_INSTANCE_RIGID: f"Warning: one rigid joint per blade · {self._scattered_instance_count + 1:,} joints.",
        }
        self.skinning_description_label.setText(descriptions[self._scattered_rig_mode])

    def rebuild(self, dynamic_wind: DynamicWindData) -> None:
        self._rows.clear()
        _rebuild_scroll_layout(self.scroll_layout)
        groups = dynamic_wind.simulation_groups
        assignments_by_group: dict[int, int] = {}
        for assignment in dynamic_wind.joint_assignments:
            assignments_by_group[assignment.simulation_group_index] = (
                assignments_by_group.get(assignment.simulation_group_index, 0) + 1
            )
        self.total_bones_label.setText(f"Total bones: {len(dynamic_wind.joint_assignments):,}")
        if not groups:
            return
        for group in groups:
            card = QFrame(self.scroll_container)
            card.setObjectName("PanelCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 16, 16, 16)
            card_layout.setSpacing(10)

            header = QHBoxLayout()
            joint_count = assignments_by_group.get(group.group_index, 0)
            bone_label = "bone" if joint_count == 1 else "bones"
            title = f"Group {group.group_index} (Generator level {group.branch_order}) · {joint_count:,} {bone_label}"
            header_label = QLabel(title, card)
            header_label.setStyleSheet("font-weight: 600;")
            header.addWidget(header_label, 1)
            trunk_checkbox = QCheckBox("Trunk", card)
            trunk_checkbox.setChecked(self._persisted_group_bool(group.group_index, "is_trunk_group", group.is_trunk_group))
            set_tooltip(
                "Treats this group as primary trunk wind. Off bends like branches; on keeps trunk-style motion.",
                trunk_checkbox,
            )
            header.addWidget(trunk_checkbox, 0)
            dual_checkbox = QCheckBox("Dual Influence", card)
            dual_checkbox.setChecked(self._persisted_group_bool(group.group_index, "use_dual_influence", group.use_dual_influence))
            set_tooltip(
                "Uses a base-to-top influence range. Off uses one strength; on blends from Min to Max.",
                dual_checkbox,
            )
            header.addWidget(dual_checkbox, 0)
            card_layout.addLayout(header)

            single_frame = QFrame(card)
            single_layout = QFormLayout(single_frame)
            single_layout.setContentsMargins(0, 0, 0, 0)
            influence_spin = self._make_spin(0.0, 1.0, 0.05, self._persisted_group_value(group.group_index, "influence", group.influence))
            influence_label = QLabel("Influence", single_frame)
            set_tooltip(
                "Wind strength for this generator group. Lower barely moves it; higher bends it more.",
                influence_label,
                influence_spin,
            )
            single_layout.addRow(influence_label, influence_spin)
            card_layout.addWidget(single_frame)

            dual_frame = QFrame(card)
            dual_layout = QFormLayout(dual_frame)
            dual_layout.setContentsMargins(0, 0, 0, 0)
            min_spin = self._make_spin(0.0, 1.0, 0.01, self._persisted_group_value(group.group_index, "min_influence", group.min_influence))
            max_default = group.max_influence if group.max_influence else group.influence
            max_spin = self._make_spin(0.0, 1.0, 0.01, self._persisted_group_value(group.group_index, "max_influence", max_default))
            shift_spin = self._make_spin(0.0, 1.0, 0.01, self._persisted_group_value(group.group_index, "shift_top", group.shift_top))
            min_label = QLabel("Min Influence", dual_frame)
            max_label = QLabel("Max Influence", dual_frame)
            shift_label = QLabel("Shift Top", dual_frame)
            set_tooltip(
                "Lower-end wind strength. Lower keeps bases calmer; higher moves the whole group more.",
                min_label,
                min_spin,
            )
            set_tooltip(
                "Upper-end wind strength. Lower calms tips; higher makes tips bend more.",
                max_label,
                max_spin,
            )
            set_tooltip(
                "Moves the high-influence zone toward the tip. Lower spreads motion down; higher concentrates it at the top.",
                shift_label,
                shift_spin,
            )
            dual_layout.addRow(min_label, min_spin)
            dual_layout.addRow(max_label, max_spin)
            dual_layout.addRow(shift_label, shift_spin)
            card_layout.addWidget(dual_frame)

            row = WindRowWidgets(
                group_index=group.group_index,
                branch_order=group.branch_order,
                trunk_checkbox=trunk_checkbox,
                dual_checkbox=dual_checkbox,
                influence_spin=influence_spin,
                min_influence_spin=min_spin,
                max_influence_spin=max_spin,
                shift_spin=shift_spin,
                single_frame=single_frame,
                dual_frame=dual_frame,
            )
            self._rows.append(row)
            self._apply_row_mode(row)
            trunk_checkbox.toggled.connect(lambda _checked: self._on_change())
            dual_checkbox.toggled.connect(lambda _checked, current=row: self._handle_row_mode_changed(current))
            for spin in (influence_spin, min_spin, max_spin, shift_spin):
                spin.valueChanged.connect(lambda _value: self._on_change())
            self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, card)

    def collect_group_settings(self) -> tuple[DynamicWindSimulationGroup, ...]:
        return tuple(
            DynamicWindSimulationGroup(
                group_index=row.group_index,
                branch_order=row.branch_order,
                influence=float(row.influence_spin.value()),
                shift_top=float(row.shift_spin.value()),
                is_trunk_group=bool(row.trunk_checkbox.isChecked()),
                use_dual_influence=bool(row.dual_checkbox.isChecked()),
                min_influence=float(row.min_influence_spin.value()),
                max_influence=float(row.max_influence_spin.value()),
            )
            for row in self._rows
        )

    def serialize_settings(self) -> dict[str, WindGroupSettingRecord]:
        if not self._rows:
            return dict(self._persisted_settings)
        payload: dict[str, WindGroupSettingRecord] = {}
        for row in self._rows:
            payload[str(row.group_index)] = WindGroupSettingRecord(
                is_trunk_group=bool(row.trunk_checkbox.isChecked()),
                use_dual_influence=bool(row.dual_checkbox.isChecked()),
                influence=float(row.influence_spin.value()),
                min_influence=float(row.min_influence_spin.value()),
                max_influence=float(row.max_influence_spin.value()),
                shift_top=float(row.shift_spin.value()),
            )
        self._persisted_settings = dict(payload)
        return payload

    def _persisted_group_value(self, group_index: int, field_name: str, default: float) -> float:
        persisted = self._persisted_settings.get(str(group_index))
        if persisted is None:
            return default
        value = getattr(persisted, field_name, default)
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return default
        return max(0.0, min(numeric, 1.0))

    def _persisted_group_bool(self, group_index: int, field_name: str, default: bool) -> bool:
        persisted = self._persisted_settings.get(str(group_index))
        if persisted is None:
            return default
        return bool(getattr(persisted, field_name, default))

    def _handle_row_mode_changed(self, row: WindRowWidgets) -> None:
        self._apply_row_mode(row)
        self._on_change()

    @staticmethod
    def _apply_row_mode(row: WindRowWidgets) -> None:
        dual = bool(row.dual_checkbox.isChecked())
        row.single_frame.setVisible(not dual)
        row.dual_frame.setVisible(dual)

    @staticmethod
    def _make_spin(minimum: float, maximum: float, step: float, value: float) -> SliderSpinEditor:
        return SliderSpinEditor(minimum=minimum, maximum=maximum, step=step, value=value)


@dataclass
class GeometryRowWidgets:
    source_key: str
    source_name: str
    source_mesh_id: int | None
    instance_count: int
    source_mode_combo: NoWheelComboBox
    asset_label: QLabel
    asset_edit: QLineEdit
    fbx_label: QLabel
    fbx_edit: QLineEdit
    browse_button: QPushButton
    preview_button: QPushButton


class GeometryTabPanel(QWidget):
    def __init__(
        self,
        *,
        browse_fbx,
        on_change,
        on_preview_proxy_requested,
        on_preview_fracture_requested,
        on_preview_part_requested,
        on_export_fracture_requested,
        on_proxy_settings_changed,
    ) -> None:
        super().__init__()
        apply_compact_preview_panel_style(self)
        self._browse_fbx = browse_fbx
        self._on_change = on_change
        self._on_preview_proxy_requested = on_preview_proxy_requested
        self._on_preview_fracture_requested = on_preview_fracture_requested
        self._on_preview_part_requested = on_preview_part_requested
        self._on_export_fracture_requested = on_export_fracture_requested
        self._on_proxy_settings_changed = on_proxy_settings_changed
        self._rows: list[GeometryRowWidgets] = []
        self._proxy_settings = ProxyMeshSettings()
        self._fracture_preview_settings = FracturePreviewSettings()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        actions_card = QFrame(self)
        actions_card.setObjectName("PanelCard")
        actions_layout = QGridLayout(actions_card)
        actions_layout.setContentsMargins(16, 16, 16, 16)
        actions_layout.setHorizontalSpacing(10)
        actions_layout.setVerticalSpacing(8)
        actions_title = QLabel("Preview", actions_card)
        actions_title.setStyleSheet("font-weight: 600;")
        self.preview_proxy_button = QPushButton("Preview Proxy Mesh", actions_card)
        self.preview_proxy_button.clicked.connect(self._on_preview_proxy_requested)
        self.preview_proxy_button.setToolTip(
            "Opens proxy settings and preview. Lower proxy values make cheaper meshes; higher values preserve more shape."
        )
        self.preview_fracture_button = QPushButton("Preview Fracturing", actions_card)
        self.preview_fracture_button.clicked.connect(self._on_preview_fracture_requested)
        self.preview_fracture_button.setToolTip(
            "Opens fracture settings and preview. Auto Branches detaches natural branch bases; stump and stems are separate."
        )
        actions_layout.addWidget(actions_title, 0, 0)
        actions_layout.addWidget(self.preview_proxy_button, 1, 0)
        actions_layout.addWidget(self.preview_fracture_button, 1, 1)
        actions_layout.setColumnStretch(2, 1)
        outer.addWidget(actions_card)

        self.scroll = _make_scroll_area(self)
        self.scroll_container, self.scroll_layout = _make_scroll_host(self)
        self.scroll.setWidget(self.scroll_container)
        outer.addWidget(self.scroll, 1)

    def clear(self) -> None:
        self._rows.clear()
        _rebuild_scroll_layout(self.scroll_layout)

    def load(self, discovery) -> None:
        self._rows.clear()
        _rebuild_scroll_layout(self.scroll_layout)
        if not discovery.rows:
            return
        for spec in discovery.rows:
            card = QFrame(self.scroll_container)
            card.setObjectName("PanelCard")
            card_layout = QGridLayout(card)
            card_layout.setContentsMargins(16, 16, 16, 16)
            card_layout.setHorizontalSpacing(10)
            card_layout.setVerticalSpacing(8)

            name_label = QLabel(f"{spec.source_name}  ({spec.instance_count} instance(s))", card)
            name_label.setStyleSheet("font-weight: 600;")
            card_layout.addWidget(name_label, 0, 0, 1, 4)
            mesh_label = QLabel(
                f"Mesh ID: {spec.source_mesh_id if spec.source_mesh_id is not None else '<none>'}",
                card,
            )
            mesh_label.setObjectName("MutedLabel")
            card_layout.addWidget(mesh_label, 1, 0, 1, 4)

            mode_combo = NoWheelComboBox(card)
            mode_combo.addItem("Use XML Mesh", PrototypeSourceMode.XML_MESH.value)
            mode_combo.addItem("Use Unreal Reference", PrototypeSourceMode.UNREAL_ASSET.value)
            mode_combo.addItem("Use FBX File", PrototypeSourceMode.FBX_FILE.value)
            mode_combo.setObjectName("InteractiveCombo")
            set_combo_value(mode_combo, spec.source_mode.value)
            set_tooltip(
                "Chooses the prototype source. XML keeps source mesh; Unreal reuses an asset; FBX replaces local geometry.",
                mode_combo,
            )

            asset_edit = _make_path_edit(spec.unreal_asset_path, card, placeholder="/Game/Path/Asset.Asset")
            asset_label = QLabel("Unreal Path", card)
            set_tooltip(
                "Existing Unreal asset for this prototype. Empty disables reuse; filled exports an external reference.",
                asset_label,
                asset_edit,
            )

            fbx_edit = _make_path_edit(spec.fbx_path, card, placeholder="Choose an FBX replacement file")
            fbx_label = QLabel("FBX File", card)
            set_tooltip(
                "FBX mesh replacing this prototype. Empty keeps XML mesh; filled uses the FBX geometry at source instances.",
                fbx_label,
                fbx_edit,
            )

            browse_button = QPushButton("Browse...", card)
            browse_button.clicked.connect(lambda _checked=False, edit=fbx_edit: self._browse_fbx(edit))
            preview_button = QPushButton("Preview/Edit", card)
            browse_button.setToolTip("Pick an FBX replacement file for this prototype.")
            preview_button.setToolTip("Preview and edit this prototype. Lower simplification exports less detail; higher keeps more.")

            source_mode_label = QLabel("Source Mode", card)
            set_tooltip(mode_combo.toolTip(), source_mode_label)
            card_layout.addWidget(source_mode_label, 2, 0)
            card_layout.addWidget(mode_combo, 2, 1)
            card_layout.addWidget(asset_label, 3, 0)
            card_layout.addWidget(asset_edit, 3, 1, 1, 3)
            card_layout.addWidget(fbx_label, 4, 0)
            card_layout.addWidget(fbx_edit, 4, 1, 1, 2)
            card_layout.addWidget(browse_button, 4, 3)
            card_layout.addWidget(preview_button, 5, 1)

            row = GeometryRowWidgets(
                source_key=spec.source_key,
                source_name=spec.source_name,
                source_mesh_id=spec.source_mesh_id,
                instance_count=spec.instance_count,
                source_mode_combo=mode_combo,
                asset_label=asset_label,
                asset_edit=asset_edit,
                fbx_label=fbx_label,
                fbx_edit=fbx_edit,
                browse_button=browse_button,
                preview_button=preview_button,
            )
            self._rows.append(row)
            self._apply_row_mode(row)
            mode_combo.currentIndexChanged.connect(lambda _index, current=row: self._handle_row_mode_changed(current))
            asset_edit.textChanged.connect(lambda _text: self._on_change())
            fbx_edit.textChanged.connect(lambda _text, current=row: self._handle_fbx_changed(current))
            preview_button.clicked.connect(lambda _checked=False, current=row: self._on_preview_part_requested(current.source_key))
            self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, card)

    def current_snapshot(self) -> dict[str, GeometryRowState]:
        snapshot: dict[str, GeometryRowState] = {}
        for row in self._rows:
            snapshot[row.source_key] = GeometryRowState(
                source_key=row.source_key,
                source_name=row.source_name,
                source_mesh_id=row.source_mesh_id,
                instance_count=row.instance_count,
                source_mode=PrototypeSourceMode(row.source_mode_combo.currentData()),
                unreal_asset_path=row.asset_edit.text().strip(),
                fbx_path=row.fbx_edit.text().strip(),
            )
        return snapshot

    def part_source_geometry(self, source_key: str) -> GeometryRowState | None:
        return self.current_snapshot().get(source_key)

    def apply_part_source_value(self, value: PartSourceMaterialValue) -> None:
        row = next((candidate for candidate in self._rows if candidate.source_key == value.source_key), None)
        if row is None:
            return
        set_combo_value(row.source_mode_combo, value.source_mode.value)
        row.asset_edit.setText(value.unreal_asset_path)
        row.fbx_edit.setText(value.fbx_path)
        self._apply_row_mode(row)
        self._on_change()

    def has_rows(self) -> bool:
        return bool(self._rows)

    def proxy_settings(self) -> ProxyMeshSettings:
        return self._proxy_settings

    def apply_proxy_settings(self, settings: ProxyMeshSettings) -> None:
        self._proxy_settings = settings

    def fracture_preview_settings(self) -> FracturePreviewSettings:
        return self._fracture_preview_settings

    def apply_fracture_preview_settings(self, settings: FracturePreviewSettings) -> None:
        self._fracture_preview_settings = settings

    def _handle_proxy_settings_changed(self) -> None:
        self._proxy_settings = self.proxy_settings()
        self._on_proxy_settings_changed()

    def _handle_row_mode_changed(self, row: GeometryRowWidgets) -> None:
        self._apply_row_mode(row)
        self._on_change()

    def _handle_fbx_changed(self, row: GeometryRowWidgets) -> None:
        self._apply_row_mode(row)
        self._on_change()

    @staticmethod
    def _apply_row_mode(row: GeometryRowWidgets) -> None:
        mode = PrototypeSourceMode(row.source_mode_combo.currentData())
        unreal_enabled = mode == PrototypeSourceMode.UNREAL_ASSET
        row.asset_label.setVisible(unreal_enabled)
        row.asset_edit.setVisible(unreal_enabled)
        row.asset_edit.setEnabled(unreal_enabled)
        fbx_enabled = mode == PrototypeSourceMode.FBX_FILE
        row.fbx_label.setVisible(fbx_enabled)
        row.fbx_edit.setVisible(fbx_enabled)
        row.browse_button.setVisible(fbx_enabled)
        row.fbx_edit.setEnabled(fbx_enabled)
        row.browse_button.setEnabled(fbx_enabled)


@dataclass
class BaseMaterialRowWidgets:
    source_id: int
    source_name: str
    path_edit: QLineEdit
    udim_mode_combo: NoWheelComboBox
    udim_id_spin: QSpinBox


@dataclass
class SlotOverrideWidgets:
    slot_name: str
    path_edit: QLineEdit
    udim_mode_combo: NoWheelComboBox
    udim_id_spin: QSpinBox


@dataclass
class PartMaterialRowWidgets:
    source_key: str
    source_name: str
    material_mode_label: QLabel
    material_mode_combo: NoWheelComboBox
    single_label: QLabel
    single_edit: QLineEdit
    single_udim_label: QLabel
    single_udim_mode_combo: NoWheelComboBox
    single_udim_id_cell: QWidget
    single_udim_id_label: QLabel
    single_udim_id_spin: QSpinBox
    black_label: QLabel
    black_edit: QLineEdit
    black_udim_label: QLabel
    black_udim_mode_combo: NoWheelComboBox
    black_udim_id_cell: QWidget
    black_udim_id_label: QLabel
    black_udim_id_spin: QSpinBox
    white_label: QLabel
    white_edit: QLineEdit
    white_udim_label: QLabel
    white_udim_mode_combo: NoWheelComboBox
    white_udim_id_cell: QWidget
    white_udim_id_label: QLabel
    white_udim_id_spin: QSpinBox
    slots_frame: QFrame
    slots_layout: QVBoxLayout
    slot_rows: list[SlotOverrideWidgets]
    restored_slot_override_records: tuple[FbxMaterialSlotSettingRecord, ...]
    header_label: QLabel
    simplification_percent: int


@dataclass(frozen=True)
class _PartMaterialValues:
    fbx_material_mode: FbxMaterialMode
    single_material_path: str
    single_material_udim_mode: UdimMode
    single_material_udim_id: int
    black_material_path: str
    black_material_udim_mode: UdimMode
    black_material_udim_id: int
    white_material_path: str
    white_material_udim_mode: UdimMode
    white_material_udim_id: int


class MaterialsTabPanel(QWidget):
    def __init__(self, *, deps, on_change) -> None:
        super().__init__()
        apply_compact_preview_panel_style(self)
        self._deps = deps
        self._on_change = on_change
        self._base_rows: list[BaseMaterialRowWidgets] = []
        self._part_rows: list[PartMaterialRowWidgets] = []
        self._geometry_snapshot: dict[str, GeometryRowState] = {}
        self._cpu_profile = CpuProfile.BALANCED

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        self.scroll = _make_scroll_area(self)
        self.scroll_container, self.scroll_layout = _make_scroll_host(self)
        self.scroll.setWidget(self.scroll_container)
        outer.addWidget(self.scroll, 1)

    def clear(self) -> None:
        self._base_rows.clear()
        self._part_rows.clear()
        _rebuild_scroll_layout(self.scroll_layout)

    def load(
        self,
        *,
        input_path: str,
        base_persisted_records: tuple[BaseMaterialSettingRecord, ...],
        part_persisted_records: tuple[PartSourceSettingRecord, ...],
        geometry_snapshot: dict[str, GeometryRowState],
        cpu_profile: CpuProfile,
        base_discovery=None,
        part_discovery=None,
    ) -> None:
        if base_discovery is None:
            base_discovery = self._deps.discover_base_material_rows(input_path, persisted_records=base_persisted_records)
        if part_discovery is None:
            part_discovery = self._deps.discover_part_prototype_rows(input_path, persisted_records=part_persisted_records)

        self._base_rows.clear()
        self._part_rows.clear()
        self._geometry_snapshot = dict(geometry_snapshot)
        self._cpu_profile = cpu_profile
        _rebuild_scroll_layout(self.scroll_layout)

        self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, self._build_base_materials_card(base_discovery))
        self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, self._build_part_materials_card(part_discovery))
        self.apply_geometry_state(self._geometry_snapshot, cpu_profile=cpu_profile)

    def apply_geometry_state(self, geometry_snapshot: dict[str, GeometryRowState], *, cpu_profile: CpuProfile) -> None:
        self._geometry_snapshot = dict(geometry_snapshot)
        self._cpu_profile = cpu_profile
        for row in self._part_rows:
            geometry = self._geometry_snapshot.get(row.source_key)
            if geometry is None:
                row.header_label.setText(row.source_name)
                self._set_part_material_fields_visible(
                    row,
                    mode_visible=False,
                    single_visible=False,
                    split_visible=False,
                )
                self._refresh_slot_rows(row)
                continue
            row.header_label.setText(f"{row.source_name}  [{geometry.source_mode.value}]")
            source_mode = geometry.source_mode
            material_controls_visible = source_mode != PrototypeSourceMode.UNREAL_ASSET
            row.material_mode_label.setVisible(material_controls_visible)
            row.material_mode_combo.setVisible(material_controls_visible)
            row.material_mode_combo.setEnabled(material_controls_visible)
            allowed_modes = [
                (FbxMaterialMode.VERTEX_COLOR_SPLIT.value, "Vertex Color Split"),
                (FbxMaterialMode.SINGLE_MATERIAL.value, "Single Material"),
            ]
            if source_mode == PrototypeSourceMode.FBX_FILE:
                allowed_modes.append((FbxMaterialMode.MATERIAL_SLOTS.value, "Material Slots"))
            current_mode = row.material_mode_combo.currentData() or FbxMaterialMode.VERTEX_COLOR_SPLIT.value
            row.material_mode_combo.blockSignals(True)
            row.material_mode_combo.clear()
            for value, label in allowed_modes:
                row.material_mode_combo.addItem(label, value)
            if current_mode not in {value for value, _label in allowed_modes}:
                current_mode = FbxMaterialMode.VERTEX_COLOR_SPLIT.value
            set_combo_value(row.material_mode_combo, current_mode)
            row.material_mode_combo.blockSignals(False)

            mode = FbxMaterialMode(row.material_mode_combo.currentData())
            self._set_part_material_fields_visible(
                row,
                mode_visible=material_controls_visible,
                single_visible=material_controls_visible and mode == FbxMaterialMode.SINGLE_MATERIAL,
                split_visible=material_controls_visible and mode == FbxMaterialMode.VERTEX_COLOR_SPLIT,
            )
            self._refresh_slot_rows(row)

    def part_source_value(self, source_key: str) -> PartSourceMaterialValue | None:
        row = next((candidate for candidate in self._part_rows if candidate.source_key == source_key), None)
        geometry = self._geometry_snapshot.get(source_key)
        if row is None or geometry is None:
            return None
        values = self._part_material_values(row)
        return PartSourceMaterialValue(
            source_key=row.source_key,
            source_name=row.source_name,
            source_mode=geometry.source_mode,
            unreal_asset_path=geometry.unreal_asset_path,
            fbx_path=geometry.fbx_path,
            fbx_material_mode=values.fbx_material_mode,
            single_material=MaterialUdimValue(
                values.single_material_path,
                values.single_material_udim_mode,
                values.single_material_udim_id,
            ),
            black_material=MaterialUdimValue(
                values.black_material_path,
                values.black_material_udim_mode,
                values.black_material_udim_id,
            ),
            white_material=MaterialUdimValue(
                values.white_material_path,
                values.white_material_udim_mode,
                values.white_material_udim_id,
            ),
            fbx_material_slot_overrides=self._part_slot_overrides(row),
            simplification_percent=row.simplification_percent,
        )

    def apply_part_source_value(self, value: PartSourceMaterialValue) -> None:
        row = next((candidate for candidate in self._part_rows if candidate.source_key == value.source_key), None)
        if row is None:
            return
        set_combo_value(row.material_mode_combo, value.fbx_material_mode.value)
        row.single_edit.setText(value.single_material.material_path)
        set_combo_value(row.single_udim_mode_combo, value.single_material.udim_mode.value)
        row.single_udim_id_spin.setValue(value.single_material.udim_id)
        row.black_edit.setText(value.black_material.material_path)
        set_combo_value(row.black_udim_mode_combo, value.black_material.udim_mode.value)
        row.black_udim_id_spin.setValue(value.black_material.udim_id)
        row.white_edit.setText(value.white_material.material_path)
        set_combo_value(row.white_udim_mode_combo, value.white_material.udim_mode.value)
        row.white_udim_id_spin.setValue(value.white_material.udim_id)
        row.simplification_percent = value.simplification_percent
        row.restored_slot_override_records = tuple(
            FbxMaterialSlotSettingRecord(
                slot_name=override.slot_name,
                ue_asset_path=override.ue_asset_path or "",
                udim_mode=override.udim_mode,
                udim_id=override.udim_id,
            )
            for override in value.fbx_material_slot_overrides
        )
        self.apply_geometry_state(self._geometry_snapshot, cpu_profile=self._cpu_profile)
        self._on_change()

    def collect_base_material_overrides(self) -> tuple[BaseMaterialOverride, ...]:
        return tuple(
            BaseMaterialOverride(
                source_id=row.source_id,
                source_name=row.source_name,
                ue_asset_path=row.path_edit.text().strip() or None,
            )
            for row in self._base_rows
        )

    def collect_udim_material_settings(self) -> tuple[UdimMaterialSetting, ...]:
        settings: list[UdimMaterialSetting] = []
        for row in self._base_rows:
            mode = UdimMode.parse(row.udim_mode_combo.currentData())
            if mode == UdimMode.OFF:
                continue
            settings.append(
                UdimMaterialSetting(
                    material_id=row.source_id,
                    mode=mode,
                    udim_id=row.udim_id_spin.value(),
                )
            )
        return tuple(settings)

    @staticmethod
    def _part_slot_overrides(row: PartMaterialRowWidgets) -> tuple[FbxMaterialSlotOverride, ...]:
        if row.slot_rows:
            return tuple(
                FbxMaterialSlotOverride(
                    slot_name=slot_row.slot_name,
                    ue_asset_path=slot_row.path_edit.text().strip() or None,
                    udim_mode=UdimMode.parse(slot_row.udim_mode_combo.currentData()),
                    udim_id=slot_row.udim_id_spin.value(),
                )
                for slot_row in row.slot_rows
                if slot_row.slot_name.strip()
            )
        return tuple(
            FbxMaterialSlotOverride(
                slot_name=record.slot_name,
                ue_asset_path=record.ue_asset_path or None,
                udim_mode=record.udim_mode,
                udim_id=record.udim_id,
            )
            for record in row.restored_slot_override_records
        )

    def collect_prototype_source_configs(self) -> tuple[PrototypeSourceConfig, ...]:
        configs: list[PrototypeSourceConfig] = []
        for row in self._part_rows:
            geometry = self._geometry_snapshot.get(row.source_key)
            if geometry is None:
                continue
            source_mode = geometry.source_mode
            values = self._part_material_values(row)
            slot_overrides = tuple(
                FbxMaterialSlotOverride(
                    slot_name=slot_row.slot_name,
                    ue_asset_path=slot_row.path_edit.text().strip() or None,
                    udim_mode=UdimMode.parse(slot_row.udim_mode_combo.currentData()),
                    udim_id=slot_row.udim_id_spin.value(),
                )
                for slot_row in row.slot_rows
                    if slot_row.slot_name.strip()
                )

            has_explicit_material_content = self._part_material_values_have_explicit_content(values, slot_overrides)
            if source_mode == PrototypeSourceMode.XML_MESH:
                if (
                    values.fbx_material_mode != FbxMaterialMode.VERTEX_COLOR_SPLIT
                    or has_explicit_material_content
                    or row.simplification_percent != 100
                ):
                    configs.append(
                        PrototypeSourceConfig(
                            source_key=row.source_key,
                            source_name=row.source_name,
                            mode=source_mode,
                            fbx_material_mode=values.fbx_material_mode,
                            single_material_path=values.single_material_path or None,
                            single_material_udim_mode=values.single_material_udim_mode,
                            single_material_udim_id=values.single_material_udim_id,
                            black_material_path=values.black_material_path or None,
                            black_material_udim_mode=values.black_material_udim_mode,
                            black_material_udim_id=values.black_material_udim_id,
                            white_material_path=values.white_material_path or None,
                            white_material_udim_mode=values.white_material_udim_mode,
                            white_material_udim_id=values.white_material_udim_id,
                            simplification_percent=row.simplification_percent,
                        )
                    )
                continue

            if source_mode == PrototypeSourceMode.UNREAL_ASSET:
                asset_path = geometry.unreal_asset_path.strip()
                if not asset_path:
                    continue
                configs.append(
                    PrototypeSourceConfig(
                        source_key=row.source_key,
                        source_name=row.source_name,
                        mode=source_mode,
                        asset_path=normalize_unreal_asset_path(asset_path),
                        simplification_percent=row.simplification_percent,
                    )
                )
                continue

            fbx_path = geometry.fbx_path.strip()
            if not fbx_path:
                continue
            resolved = Path(fbx_path).expanduser().resolve()
            configs.append(
                PrototypeSourceConfig(
                    source_key=row.source_key,
                    source_name=row.source_name,
                    mode=source_mode,
                    fbx_material_mode=values.fbx_material_mode,
                    fbx_path=str(resolved),
                    single_material_path=values.single_material_path or None,
                    single_material_udim_mode=values.single_material_udim_mode,
                    single_material_udim_id=values.single_material_udim_id,
                    black_material_path=values.black_material_path or None,
                    black_material_udim_mode=values.black_material_udim_mode,
                    black_material_udim_id=values.black_material_udim_id,
                    white_material_path=values.white_material_path or None,
                    white_material_udim_mode=values.white_material_udim_mode,
                    white_material_udim_id=values.white_material_udim_id,
                    fbx_material_slot_overrides=slot_overrides,
                    simplification_percent=row.simplification_percent,
                )
            )
        return tuple(configs)

    def serialize_base_material_records(self) -> tuple[BaseMaterialSettingRecord, ...]:
        payload: list[BaseMaterialSettingRecord] = []
        for row in self._base_rows:
            value = row.path_edit.text().strip()
            udim_mode = UdimMode.parse(row.udim_mode_combo.currentData())
            if not value and udim_mode == UdimMode.OFF:
                continue
            payload.append(
                BaseMaterialSettingRecord(
                    source_id=row.source_id,
                    source_name=row.source_name,
                    ue_asset_path=value,
                    udim_mode=udim_mode,
                    udim_id=row.udim_id_spin.value(),
                )
            )
        return tuple(payload)

    def serialize_part_source_records(self) -> tuple[PartSourceSettingRecord, ...]:
        payload: list[PartSourceSettingRecord] = []
        for row in self._part_rows:
            geometry = self._geometry_snapshot.get(row.source_key)
            if geometry is None:
                continue
            source_mode = geometry.source_mode
            values = self._part_material_values(row)
            slot_records = tuple(
                FbxMaterialSlotSettingRecord(
                    slot_name=slot_row.slot_name,
                    ue_asset_path=slot_row.path_edit.text().strip(),
                    udim_mode=UdimMode.parse(slot_row.udim_mode_combo.currentData()),
                    udim_id=slot_row.udim_id_spin.value(),
                )
                for slot_row in row.slot_rows
                if slot_row.slot_name.strip()
            )
            has_explicit_material_content = self._part_material_values_have_explicit_content(values, slot_records)
            if (
                source_mode == PrototypeSourceMode.XML_MESH
                and not geometry.unreal_asset_path.strip()
                and not geometry.fbx_path.strip()
                and values.fbx_material_mode == FbxMaterialMode.VERTEX_COLOR_SPLIT
                and not has_explicit_material_content
                and not slot_records
                and row.simplification_percent == 100
            ):
                continue
            payload.append(
                PartSourceSettingRecord(
                    source_name=row.source_name,
                    source_key=row.source_key,
                    source_mode=source_mode,
                    unreal_asset_path=geometry.unreal_asset_path.strip(),
                    fbx_path=geometry.fbx_path.strip(),
                    fbx_material_mode=values.fbx_material_mode,
                    single_material_path=values.single_material_path,
                    single_material_udim_mode=values.single_material_udim_mode,
                    single_material_udim_id=values.single_material_udim_id,
                    black_material_path=values.black_material_path,
                    black_material_udim_mode=values.black_material_udim_mode,
                    black_material_udim_id=values.black_material_udim_id,
                    white_material_path=values.white_material_path,
                    white_material_udim_mode=values.white_material_udim_mode,
                    white_material_udim_id=values.white_material_udim_id,
                    fbx_material_slot_overrides=slot_records,
                    simplification_percent=row.simplification_percent,
                )
            )
        return tuple(payload)

    @staticmethod
    def _part_material_values(row: PartMaterialRowWidgets) -> _PartMaterialValues:
        return _PartMaterialValues(
            fbx_material_mode=FbxMaterialMode(row.material_mode_combo.currentData()),
            single_material_path=row.single_edit.text().strip(),
            single_material_udim_mode=UdimMode.parse(row.single_udim_mode_combo.currentData()),
            single_material_udim_id=row.single_udim_id_spin.value(),
            black_material_path=row.black_edit.text().strip(),
            black_material_udim_mode=UdimMode.parse(row.black_udim_mode_combo.currentData()),
            black_material_udim_id=row.black_udim_id_spin.value(),
            white_material_path=row.white_edit.text().strip(),
            white_material_udim_mode=UdimMode.parse(row.white_udim_mode_combo.currentData()),
            white_material_udim_id=row.white_udim_id_spin.value(),
        )

    @staticmethod
    def _part_material_values_have_active_udim(
        values: _PartMaterialValues,
        slot_overrides: tuple[object, ...],
    ) -> bool:
        if values.single_material_udim_mode != UdimMode.OFF:
            return True
        if values.black_material_udim_mode != UdimMode.OFF:
            return True
        if values.white_material_udim_mode != UdimMode.OFF:
            return True
        return any(UdimMode.parse(getattr(override, "udim_mode", UdimMode.OFF)) != UdimMode.OFF for override in slot_overrides)

    @classmethod
    def _part_material_values_have_explicit_content(
        cls,
        values: _PartMaterialValues,
        slot_overrides: tuple[object, ...],
    ) -> bool:
        return bool(
            values.single_material_path
            or values.black_material_path
            or values.white_material_path
            or cls._part_material_values_have_active_udim(values, slot_overrides)
        )

    def _build_base_materials_card(self, discovery) -> QWidget:
        card = QFrame(self.scroll_container)
        card.setObjectName("PanelCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        title = QLabel("Base Mesh Materials", card)
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)
        if not discovery.rows:
            layout.addWidget(QLabel("No base XML material slots found in this file.", card))
            return card
        for spec in discovery.rows:
            row = MaterialUdimRow(
                label=spec.source_name or f"Material_{spec.source_id}",
                value=MaterialUdimValue(
                    material_path=spec.ue_asset_path,
                    udim_mode=spec.udim_mode,
                    udim_id=spec.udim_id,
                ),
                placeholder="/Game/Path/Material.Material",
                path_max_width=220,
                parent=card,
            )
            row.valueChanged.connect(self._on_change)
            self._base_rows.append(
                BaseMaterialRowWidgets(
                    source_id=spec.source_id,
                    source_name=spec.source_name,
                    path_edit=row.path_edit,
                    udim_mode_combo=row.udim_mode_combo,
                    udim_id_spin=row.udim_id_spin,
                )
            )
            layout.addWidget(row)
        return card

    def _build_part_materials_card(self, discovery) -> QWidget:
        card = QFrame(self.scroll_container)
        card.setObjectName("PanelCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        title = QLabel("Instanced Part Materials", card)
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)
        if not discovery.rows:
            layout.addWidget(QLabel("No repeated branch prototypes found in this XML.", card))
            return card
        for spec in discovery.rows:
            row_card = QFrame(card)
            row_card_layout = QVBoxLayout(row_card)
            row_card_layout.setContentsMargins(0, 0, 0, 0)
            row_card_layout.setSpacing(8)

            header_label = QLabel(spec.source_name, row_card)
            header_label.setStyleSheet("font-weight: 600;")
            row_card_layout.addWidget(header_label)

            form = QGridLayout()
            form.setHorizontalSpacing(6)
            form.setVerticalSpacing(8)
            mode_combo = NoWheelComboBox(row_card)
            mode_combo.addItem("Vertex Color Split", FbxMaterialMode.VERTEX_COLOR_SPLIT.value)
            mode_combo.addItem("Single Material", FbxMaterialMode.SINGLE_MATERIAL.value)
            mode_combo.setObjectName("InteractiveCombo")
            set_combo_value(mode_combo, spec.fbx_material_mode.value)

            single_edit = _make_path_edit(
                spec.single_material_path,
                row_card,
                placeholder="/Game/Path/Material.Material",
                max_width=190,
            )
            single_udim_mode_combo, single_udim_id_spin = make_udim_controls(
                row_card,
                mode=spec.single_material_udim_mode,
                udim_id=spec.single_material_udim_id,
            )
            black_edit = _make_path_edit(
                spec.black_material_path,
                row_card,
                placeholder="/Game/Path/Black.Material",
                max_width=190,
            )
            black_udim_mode_combo, black_udim_id_spin = make_udim_controls(
                row_card,
                mode=spec.black_material_udim_mode,
                udim_id=spec.black_material_udim_id,
            )
            white_edit = _make_path_edit(
                spec.white_material_path,
                row_card,
                placeholder="/Game/Path/White.Material",
                max_width=190,
            )
            white_udim_mode_combo, white_udim_id_spin = make_udim_controls(
                row_card,
                mode=spec.white_material_udim_mode,
                udim_id=spec.white_material_udim_id,
            )
            material_mode_label = QLabel("Part Material Mode", row_card)
            single_label = QLabel("Single Material", row_card)
            single_udim_label = QLabel("UDIM", row_card)
            single_udim_id_label = QLabel("ID", row_card)
            single_udim_id_cell = make_udim_id_cell(row_card, single_udim_id_label, single_udim_id_spin)
            black_label = QLabel("Black Material", row_card)
            black_udim_label = QLabel("UDIM", row_card)
            black_udim_id_label = QLabel("ID", row_card)
            black_udim_id_cell = make_udim_id_cell(row_card, black_udim_id_label, black_udim_id_spin)
            white_label = QLabel("White Material", row_card)
            white_udim_label = QLabel("UDIM", row_card)
            white_udim_id_label = QLabel("ID", row_card)
            white_udim_id_cell = make_udim_id_cell(row_card, white_udim_id_label, white_udim_id_spin)
            set_tooltip(
                "Chooses how part materials are resolved. Split uses vertex colors; single forces one material; slots uses FBX slots.",
                material_mode_label,
                mode_combo,
            )
            set_tooltip(
                "Material used when Single Material is active. Empty keeps generated material; filled forces one asset.",
                single_label,
                single_edit,
            )
            set_tooltip(
                "UDIM mode for the single material. Off keeps UVs; higher modes shift or write UV1 offsets.",
                single_udim_label,
                single_udim_mode_combo,
            )
            set_tooltip(
                "UDIM tile for the single material. Lower uses earlier tiles; higher uses later tiles.",
                single_udim_id_cell,
            )
            set_tooltip(
                "Material for black vertex-color faces. Empty keeps generated material; filled forces that bucket.",
                black_label,
                black_edit,
            )
            set_tooltip(
                "UDIM mode for black faces. Off keeps UVs; higher modes shift or write UV1 offsets.",
                black_udim_label,
                black_udim_mode_combo,
            )
            set_tooltip(
                "UDIM tile for black faces. Lower uses earlier tiles; higher uses later tiles.",
                black_udim_id_cell,
            )
            set_tooltip(
                "Material for white vertex-color faces. Empty keeps generated material; filled forces that bucket.",
                white_label,
                white_edit,
            )
            set_tooltip(
                "UDIM mode for white faces. Off keeps UVs; higher modes shift or write UV1 offsets.",
                white_udim_label,
                white_udim_mode_combo,
            )
            set_tooltip(
                "UDIM tile for white faces. Lower uses earlier tiles; higher uses later tiles.",
                white_udim_id_cell,
            )

            form.addWidget(material_mode_label, 0, 0)
            form.addWidget(mode_combo, 0, 1)
            form.addWidget(single_label, 1, 0)
            form.addWidget(single_edit, 1, 1)
            form.addWidget(single_udim_label, 1, 2)
            form.addWidget(single_udim_mode_combo, 1, 3)
            form.addWidget(single_udim_id_cell, 1, 4, 1, 2)
            form.addWidget(black_label, 2, 0)
            form.addWidget(black_edit, 2, 1)
            form.addWidget(black_udim_label, 2, 2)
            form.addWidget(black_udim_mode_combo, 2, 3)
            form.addWidget(black_udim_id_cell, 2, 4, 1, 2)
            form.addWidget(white_label, 3, 0)
            form.addWidget(white_edit, 3, 1)
            form.addWidget(white_udim_label, 3, 2)
            form.addWidget(white_udim_mode_combo, 3, 3)
            form.addWidget(white_udim_id_cell, 3, 4, 1, 2)
            row_card_layout.addLayout(form)

            slots_frame = QFrame(row_card)
            slots_layout = QVBoxLayout(slots_frame)
            slots_layout.setContentsMargins(0, 0, 0, 0)
            slots_layout.setSpacing(6)
            row_card_layout.addWidget(slots_frame)

            row = PartMaterialRowWidgets(
                source_key=spec.source_key,
                source_name=spec.source_name,
                material_mode_label=material_mode_label,
                material_mode_combo=mode_combo,
                single_label=single_label,
                single_edit=single_edit,
                single_udim_label=single_udim_label,
                single_udim_mode_combo=single_udim_mode_combo,
                single_udim_id_cell=single_udim_id_cell,
                single_udim_id_label=single_udim_id_label,
                single_udim_id_spin=single_udim_id_spin,
                black_label=black_label,
                black_edit=black_edit,
                black_udim_label=black_udim_label,
                black_udim_mode_combo=black_udim_mode_combo,
                black_udim_id_cell=black_udim_id_cell,
                black_udim_id_label=black_udim_id_label,
                black_udim_id_spin=black_udim_id_spin,
                white_label=white_label,
                white_edit=white_edit,
                white_udim_label=white_udim_label,
                white_udim_mode_combo=white_udim_mode_combo,
                white_udim_id_cell=white_udim_id_cell,
                white_udim_id_label=white_udim_id_label,
                white_udim_id_spin=white_udim_id_spin,
                slots_frame=slots_frame,
                slots_layout=slots_layout,
                slot_rows=[],
                restored_slot_override_records=spec.fbx_material_slot_overrides,
                header_label=header_label,
                simplification_percent=spec.simplification_percent,
            )
            self._part_rows.append(row)
            mode_combo.currentIndexChanged.connect(lambda _index, current=row: self._handle_material_mode_changed(current))
            single_edit.textChanged.connect(lambda _text: self._on_change())
            single_udim_mode_combo.currentIndexChanged.connect(lambda _index: self._on_change())
            single_udim_id_spin.valueChanged.connect(lambda _value: self._on_change())
            black_edit.textChanged.connect(lambda _text: self._on_change())
            black_udim_mode_combo.currentIndexChanged.connect(lambda _index: self._on_change())
            black_udim_id_spin.valueChanged.connect(lambda _value: self._on_change())
            white_edit.textChanged.connect(lambda _text: self._on_change())
            white_udim_mode_combo.currentIndexChanged.connect(lambda _index: self._on_change())
            white_udim_id_spin.valueChanged.connect(lambda _value: self._on_change())
            layout.addWidget(row_card)
        return card

    @staticmethod
    def _set_part_material_fields_visible(
        row: PartMaterialRowWidgets,
        *,
        mode_visible: bool,
        single_visible: bool,
        split_visible: bool,
    ) -> None:
        row.material_mode_label.setVisible(mode_visible)
        row.material_mode_combo.setVisible(mode_visible)
        row.material_mode_combo.setEnabled(mode_visible)
        row.single_label.setVisible(single_visible)
        row.single_edit.setVisible(single_visible)
        row.single_edit.setEnabled(single_visible)
        row.single_udim_label.setVisible(single_visible)
        row.single_udim_mode_combo.setVisible(single_visible)
        row.single_udim_mode_combo.setEnabled(single_visible)
        row.single_udim_id_cell.setVisible(single_visible)
        row.single_udim_id_cell.setEnabled(single_visible)
        row.single_udim_id_label.setVisible(single_visible)
        row.single_udim_id_spin.setVisible(single_visible)
        row.single_udim_id_spin.setEnabled(single_visible)
        row.black_label.setVisible(split_visible)
        row.black_edit.setVisible(split_visible)
        row.black_edit.setEnabled(split_visible)
        row.black_udim_label.setVisible(split_visible)
        row.black_udim_mode_combo.setVisible(split_visible)
        row.black_udim_mode_combo.setEnabled(split_visible)
        row.black_udim_id_cell.setVisible(split_visible)
        row.black_udim_id_cell.setEnabled(split_visible)
        row.black_udim_id_label.setVisible(split_visible)
        row.black_udim_id_spin.setVisible(split_visible)
        row.black_udim_id_spin.setEnabled(split_visible)
        row.white_label.setVisible(split_visible)
        row.white_edit.setVisible(split_visible)
        row.white_edit.setEnabled(split_visible)
        row.white_udim_label.setVisible(split_visible)
        row.white_udim_mode_combo.setVisible(split_visible)
        row.white_udim_mode_combo.setEnabled(split_visible)
        row.white_udim_id_cell.setVisible(split_visible)
        row.white_udim_id_cell.setEnabled(split_visible)
        row.white_udim_id_label.setVisible(split_visible)
        row.white_udim_id_spin.setVisible(split_visible)
        row.white_udim_id_spin.setEnabled(split_visible)

    def _handle_material_mode_changed(self, row: PartMaterialRowWidgets) -> None:
        self.apply_geometry_state(self._geometry_snapshot, cpu_profile=self._cpu_profile)
        self._on_change()

    def _refresh_slot_rows(self, row: PartMaterialRowWidgets) -> None:
        _rebuild_scroll_layout(row.slots_layout)
        row.slot_rows.clear()
        geometry = self._geometry_snapshot.get(row.source_key)
        if geometry is None:
            row.slots_frame.setVisible(False)
            return
        mode = FbxMaterialMode(row.material_mode_combo.currentData())
        if geometry.source_mode != PrototypeSourceMode.FBX_FILE or mode != FbxMaterialMode.MATERIAL_SLOTS:
            row.slots_frame.setVisible(False)
            return

        fbx_path = geometry.fbx_path.strip()
        row.slots_frame.setVisible(True)
        if not fbx_path:
            row.slots_layout.insertWidget(0, QLabel("Choose an FBX file in the Geometry tab to inspect material slots.", row.slots_frame))
            return
        try:
            slots = self._deps.inspect_fbx_material_slot_rows(
                fbx_path,
                cpu_profile=self._cpu_profile,
                persisted_records=row.restored_slot_override_records,
            )
        except Exception as exc:
            row.slots_layout.insertWidget(0, QLabel(f"FBX material slot analysis failed: {exc}", row.slots_frame))
            return
        if not slots:
            row.slots_layout.insertWidget(0, QLabel("No face-used FBX material slots were found in this file.", row.slots_frame))
            return
        row.slots_layout.insertWidget(0, QLabel("FBX Material Slots", row.slots_frame))
        for slot_spec in slots:
            slot_widget = self._build_slot_row(slot_spec, row)
            row.slots_layout.insertWidget(row.slots_layout.count() - 1, slot_widget)
        row.restored_slot_override_records = ()

    def _build_slot_row(self, slot_spec: PrototypeMaterialSlotRowSpec, row: PartMaterialRowWidgets) -> QWidget:
        widget = QFrame(row.slots_frame)
        layout = QGridLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(6)
        label = QLabel(f"{slot_spec.slot_name} ({slot_spec.face_count} faces)", widget)
        edit = _make_path_edit(
            slot_spec.ue_asset_path,
            widget,
            placeholder="/Game/Path/Material.Material",
            max_width=190,
        )
        udim_mode_combo, udim_id_spin = make_udim_controls(widget, mode=slot_spec.udim_mode, udim_id=slot_spec.udim_id)
        set_tooltip(
            "Material override for this FBX slot. Empty may reuse another filled slot; filled forces this slot.",
            label,
            edit,
        )
        set_tooltip(
            "UDIM handling for this FBX slot. Off keeps UVs; higher modes shift or write UV1 offsets.",
            udim_mode_combo,
        )
        set_tooltip(
            "UDIM tile for this FBX slot. Lower uses earlier tiles; higher uses later tiles.",
            udim_id_spin,
        )
        edit.textChanged.connect(lambda _text: self._on_change())
        udim_mode_combo.currentIndexChanged.connect(lambda _index: self._on_change())
        udim_id_spin.valueChanged.connect(lambda _value: self._on_change())
        layout.addWidget(label, 0, 0)
        layout.addWidget(edit, 0, 1)
        layout.addWidget(udim_mode_combo, 0, 2)
        layout.addWidget(udim_id_spin, 0, 3)
        row.slot_rows.append(
            SlotOverrideWidgets(
                slot_name=slot_spec.slot_name,
                path_edit=edit,
                udim_mode_combo=udim_mode_combo,
                udim_id_spin=udim_id_spin,
            )
        )
        return widget
