"""Qt tab panels for the PySide6 shell.

Layer: UI.

These widgets render operator-facing lists for wind, geometry, and materials
while delegating discovery and conversion semantics to the existing application
services.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
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
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..asset_paths import normalize_unreal_asset_path
from ..discovery_service import PrototypeMaterialSlotRowSpec
from ..models import (
    BaseMaterialOverride,
    CpuProfile,
    DynamicWindSimulationGroup,
    FbxMaterialMode,
    FbxMaterialSlotOverride,
    PrototypeSourceConfig,
    PrototypeSourceMode,
)
from ..settings_service import (
    BaseMaterialSettingRecord,
    FbxMaterialSlotSettingRecord,
    PartSourceSettingRecord,
    WindGroupSettingRecord,
)


def _make_scroll_host(parent: QWidget) -> tuple[QWidget, QVBoxLayout]:
    container = QWidget(parent)
    container.setObjectName("ScrollContainer")
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)
    layout.addStretch(1)
    return container, layout


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


def _set_combo_value(combo: QComboBox, value: str) -> None:
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)
        return
    index = combo.findText(value)
    if index >= 0:
        combo.setCurrentIndex(index)


def _make_path_edit(text: str, parent: QWidget, *, placeholder: str) -> QLineEdit:
    edit = QLineEdit(text, parent)
    edit.setObjectName("PathInput")
    edit.setPlaceholderText(placeholder)
    return edit


class NoWheelComboBox(QComboBox):
    def wheelEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()


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
    def __init__(self, *, on_change, on_refresh_requested) -> None:
        super().__init__()
        self._on_change = on_change
        self._on_refresh_requested = on_refresh_requested
        self._persisted_settings: dict[str, WindGroupSettingRecord] = {}
        self._rows: list[WindRowWidgets] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        self.summary_label = QLabel("Click Refresh Wind Groups to inspect wind settings.", self)
        self.summary_label.setWordWrap(True)
        outer.addWidget(self.summary_label)

        controls = QFrame(self)
        controls.setObjectName("PanelCard")
        controls_layout = QGridLayout(controls)
        controls_layout.setContentsMargins(16, 16, 16, 16)
        controls_layout.setHorizontalSpacing(12)
        controls_layout.setVerticalSpacing(8)

        self.ground_cover_checkbox = QCheckBox("Ground Cover", controls)
        self.ground_cover_checkbox.toggled.connect(lambda _checked: self._on_change())
        self.gust_spin = self._make_spin(0.0, 1.0, 0.01, 0.0)
        self.gust_spin.valueChanged.connect(lambda _value: self._on_change())
        # Wind inspection is now owned by the Wind tab itself instead of the
        # global action column so the operator can tweak wind globals and refresh
        # from the same focused surface.
        self.refresh_button = QPushButton("Refresh Wind Groups", controls)
        self.refresh_button.setObjectName("WindRefreshButton")
        self.refresh_button.clicked.connect(self._on_refresh_requested)

        controls_layout.addWidget(self.ground_cover_checkbox, 0, 0, 1, 2)
        controls_layout.addWidget(self.refresh_button, 0, 2, 1, 1)
        controls_layout.addWidget(QLabel("Gust Attenuation", controls), 1, 0)
        controls_layout.addWidget(self.gust_spin, 1, 1, 1, 2)
        controls_layout.setColumnStretch(1, 1)
        controls_layout.setColumnStretch(3, 1)
        outer.addWidget(controls)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_container, self.scroll_layout = _make_scroll_host(self)
        self.scroll.viewport().setObjectName("ScrollViewport")
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setWidget(self.scroll_container)
        outer.addWidget(self.scroll, 1)

    def set_persisted_settings(self, settings: dict[str, WindGroupSettingRecord]) -> None:
        self._persisted_settings = dict(settings)

    def clear(self, message: str = "Click Refresh Wind Groups to inspect wind settings.") -> None:
        self.summary_label.setText(message)
        self._rows.clear()
        _rebuild_scroll_layout(self.scroll_layout)

    def set_global_options(self, *, is_ground_cover: bool, gust_attenuation: float) -> None:
        with QSignalBlocker(self.ground_cover_checkbox):
            self.ground_cover_checkbox.setChecked(bool(is_ground_cover))
        with QSignalBlocker(self.gust_spin):
            self.gust_spin.setValue(float(gust_attenuation))

    def is_ground_cover_enabled(self) -> bool:
        return bool(self.ground_cover_checkbox.isChecked())

    def gust_attenuation(self) -> float:
        return float(self.gust_spin.value())

    def rebuild(self, groups: tuple[DynamicWindSimulationGroup, ...]) -> None:
        self._rows.clear()
        _rebuild_scroll_layout(self.scroll_layout)
        if not groups:
            self.summary_label.setText("No skeleton joints found.")
            return
        self.summary_label.setText(f"Loaded {len(groups)} wind group(s).")
        for group in groups:
            card = QFrame(self.scroll_container)
            card.setObjectName("PanelCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 16, 16, 16)
            card_layout.setSpacing(10)

            header = QHBoxLayout()
            title = f"Group {group.group_index} (Generator level {group.branch_order})"
            header_label = QLabel(title, card)
            header_label.setStyleSheet("font-weight: 600;")
            header.addWidget(header_label, 1)
            trunk_checkbox = QCheckBox("Trunk", card)
            trunk_checkbox.setChecked(self._persisted_group_bool(group.group_index, "is_trunk_group", group.is_trunk_group))
            header.addWidget(trunk_checkbox, 0)
            dual_checkbox = QCheckBox("Dual Influence", card)
            dual_checkbox.setChecked(self._persisted_group_bool(group.group_index, "use_dual_influence", group.use_dual_influence))
            header.addWidget(dual_checkbox, 0)
            card_layout.addLayout(header)

            single_frame = QFrame(card)
            single_layout = QFormLayout(single_frame)
            single_layout.setContentsMargins(0, 0, 0, 0)
            influence_spin = self._make_spin(0.0, 1.0, 0.05, self._persisted_group_value(group.group_index, "influence", group.influence))
            single_layout.addRow("Influence", influence_spin)
            card_layout.addWidget(single_frame)

            dual_frame = QFrame(card)
            dual_layout = QFormLayout(dual_frame)
            dual_layout.setContentsMargins(0, 0, 0, 0)
            min_spin = self._make_spin(0.0, 1.0, 0.01, self._persisted_group_value(group.group_index, "min_influence", group.min_influence))
            max_default = group.max_influence if group.max_influence else group.influence
            max_spin = self._make_spin(0.0, 1.0, 0.01, self._persisted_group_value(group.group_index, "max_influence", max_default))
            shift_spin = self._make_spin(0.0, 1.0, 0.01, self._persisted_group_value(group.group_index, "shift_top", group.shift_top))
            dual_layout.addRow("Min Influence", min_spin)
            dual_layout.addRow("Max Influence", max_spin)
            dual_layout.addRow("Shift Top", shift_spin)
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


class GeometryTabPanel(QWidget):
    def __init__(self, *, browse_fbx, on_change) -> None:
        super().__init__()
        self._browse_fbx = browse_fbx
        self._on_change = on_change
        self._rows: list[GeometryRowWidgets] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        self.summary_label = QLabel("Select an XML file to load repeated branch prototypes.", self)
        self.summary_label.setWordWrap(True)
        outer.addWidget(self.summary_label)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_container, self.scroll_layout = _make_scroll_host(self)
        self.scroll.viewport().setObjectName("ScrollViewport")
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setWidget(self.scroll_container)
        outer.addWidget(self.scroll, 1)

    def clear(self, message: str = "Select an XML file to load repeated branch prototypes.") -> None:
        self.summary_label.setText(message)
        self._rows.clear()
        _rebuild_scroll_layout(self.scroll_layout)

    def load(self, discovery) -> None:
        self._rows.clear()
        _rebuild_scroll_layout(self.scroll_layout)
        self.summary_label.setText(discovery.summary)
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
            _set_combo_value(mode_combo, spec.source_mode.value)

            asset_edit = _make_path_edit(spec.unreal_asset_path, card, placeholder="/Game/Path/Asset.Asset")
            asset_label = QLabel("Unreal Path", card)

            fbx_edit = _make_path_edit(spec.fbx_path, card, placeholder="Choose an FBX replacement file")
            fbx_label = QLabel("FBX File", card)

            browse_button = QPushButton("Browse...", card)
            browse_button.clicked.connect(lambda _checked=False, edit=fbx_edit: self._browse_fbx(edit))

            card_layout.addWidget(QLabel("Source Mode", card), 2, 0)
            card_layout.addWidget(mode_combo, 2, 1)
            card_layout.addWidget(asset_label, 3, 0)
            card_layout.addWidget(asset_edit, 3, 1, 1, 3)
            card_layout.addWidget(fbx_label, 4, 0)
            card_layout.addWidget(fbx_edit, 4, 1, 1, 2)
            card_layout.addWidget(browse_button, 4, 3)

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
            )
            self._rows.append(row)
            self._apply_row_mode(row)
            mode_combo.currentIndexChanged.connect(lambda _index, current=row: self._handle_row_mode_changed(current))
            asset_edit.textChanged.connect(lambda _text: self._on_change())
            fbx_edit.textChanged.connect(lambda _text, current=row: self._handle_fbx_changed(current))
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

    def has_rows(self) -> bool:
        return bool(self._rows)

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


@dataclass
class SlotOverrideWidgets:
    slot_name: str
    path_edit: QLineEdit


@dataclass
class PartMaterialRowWidgets:
    source_key: str
    source_name: str
    material_mode_label: QLabel
    material_mode_combo: NoWheelComboBox
    single_label: QLabel
    single_edit: QLineEdit
    black_label: QLabel
    black_edit: QLineEdit
    white_label: QLabel
    white_edit: QLineEdit
    slots_frame: QFrame
    slots_layout: QVBoxLayout
    slot_rows: list[SlotOverrideWidgets]
    restored_slot_override_records: tuple[FbxMaterialSlotSettingRecord, ...]
    header_label: QLabel


class MaterialsTabPanel(QWidget):
    def __init__(self, *, deps, on_change) -> None:
        super().__init__()
        self._deps = deps
        self._on_change = on_change
        self._base_rows: list[BaseMaterialRowWidgets] = []
        self._part_rows: list[PartMaterialRowWidgets] = []
        self._geometry_snapshot: dict[str, GeometryRowState] = {}
        self._cpu_profile = CpuProfile.BALANCED

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        self.summary_label = QLabel("Select an XML file to load material settings.", self)
        self.summary_label.setWordWrap(True)
        outer.addWidget(self.summary_label)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_container, self.scroll_layout = _make_scroll_host(self)
        self.scroll.viewport().setObjectName("ScrollViewport")
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setWidget(self.scroll_container)
        outer.addWidget(self.scroll, 1)

    def clear(self, message: str = "Select an XML file to load material settings.") -> None:
        self.summary_label.setText(message)
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
    ) -> None:
        self._base_rows.clear()
        self._part_rows.clear()
        self._geometry_snapshot = dict(geometry_snapshot)
        self._cpu_profile = cpu_profile
        _rebuild_scroll_layout(self.scroll_layout)

        base_discovery = self._deps.discover_base_material_rows(input_path, persisted_records=base_persisted_records)
        part_discovery = self._deps.discover_part_prototype_rows(input_path, persisted_records=part_persisted_records)
        self.summary_label.setText(f"{base_discovery.summary} {part_discovery.summary}".strip())

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
            _set_combo_value(row.material_mode_combo, current_mode)
            row.material_mode_combo.blockSignals(False)

            mode = FbxMaterialMode(row.material_mode_combo.currentData())
            self._set_part_material_fields_visible(
                row,
                mode_visible=material_controls_visible,
                single_visible=material_controls_visible and mode == FbxMaterialMode.SINGLE_MATERIAL,
                split_visible=material_controls_visible and mode == FbxMaterialMode.VERTEX_COLOR_SPLIT,
            )
            self._refresh_slot_rows(row)

    def collect_base_material_overrides(self) -> tuple[BaseMaterialOverride, ...]:
        return tuple(
            BaseMaterialOverride(
                source_id=row.source_id,
                source_name=row.source_name,
                ue_asset_path=row.path_edit.text().strip() or None,
            )
            for row in self._base_rows
        )

    def collect_prototype_source_configs(self) -> tuple[PrototypeSourceConfig, ...]:
        configs: list[PrototypeSourceConfig] = []
        for row in self._part_rows:
            geometry = self._geometry_snapshot.get(row.source_key)
            if geometry is None:
                continue
            source_mode = geometry.source_mode
            material_mode = FbxMaterialMode(row.material_mode_combo.currentData())
            single_material_path = row.single_edit.text().strip() or None
            black_material_path = row.black_edit.text().strip() or None
            white_material_path = row.white_edit.text().strip() or None
            slot_overrides = tuple(
                FbxMaterialSlotOverride(
                    slot_name=slot_row.slot_name,
                    ue_asset_path=slot_row.path_edit.text().strip() or None,
                )
                for slot_row in row.slot_rows
                if slot_row.slot_name.strip()
            )

            if source_mode == PrototypeSourceMode.XML_MESH:
                if (
                    material_mode != FbxMaterialMode.VERTEX_COLOR_SPLIT
                    or single_material_path
                    or black_material_path
                    or white_material_path
                ):
                    configs.append(
                        PrototypeSourceConfig(
                            source_key=row.source_key,
                            source_name=row.source_name,
                            mode=source_mode,
                            fbx_material_mode=material_mode,
                            single_material_path=single_material_path,
                            black_material_path=black_material_path,
                            white_material_path=white_material_path,
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
                    fbx_material_mode=material_mode,
                    fbx_path=str(resolved),
                    single_material_path=single_material_path,
                    black_material_path=black_material_path,
                    white_material_path=white_material_path,
                    fbx_material_slot_overrides=slot_overrides,
                )
            )
        return tuple(configs)

    def serialize_base_material_records(self) -> tuple[BaseMaterialSettingRecord, ...]:
        payload: list[BaseMaterialSettingRecord] = []
        for row in self._base_rows:
            value = row.path_edit.text().strip()
            if not value:
                continue
            payload.append(
                BaseMaterialSettingRecord(
                    source_id=row.source_id,
                    source_name=row.source_name,
                    ue_asset_path=value,
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
            fbx_material_mode = FbxMaterialMode(row.material_mode_combo.currentData())
            single_material_path = row.single_edit.text().strip()
            black_material_path = row.black_edit.text().strip()
            white_material_path = row.white_edit.text().strip()
            slot_records = tuple(
                FbxMaterialSlotSettingRecord(
                    slot_name=slot_row.slot_name,
                    ue_asset_path=slot_row.path_edit.text().strip(),
                )
                for slot_row in row.slot_rows
                if slot_row.slot_name.strip()
            )
            if (
                source_mode == PrototypeSourceMode.XML_MESH
                and not geometry.unreal_asset_path.strip()
                and not geometry.fbx_path.strip()
                and fbx_material_mode == FbxMaterialMode.VERTEX_COLOR_SPLIT
                and not single_material_path
                and not black_material_path
                and not white_material_path
                and not slot_records
            ):
                continue
            payload.append(
                PartSourceSettingRecord(
                    source_name=row.source_name,
                    source_key=row.source_key,
                    source_mode=source_mode,
                    unreal_asset_path=geometry.unreal_asset_path.strip(),
                    fbx_path=geometry.fbx_path.strip(),
                    fbx_material_mode=fbx_material_mode,
                    single_material_path=single_material_path,
                    black_material_path=black_material_path,
                    white_material_path=white_material_path,
                    fbx_material_slot_overrides=slot_records,
                )
            )
        return tuple(payload)

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
            row = QFrame(card)
            row_layout = QGridLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setHorizontalSpacing(10)
            row_layout.addWidget(QLabel(spec.source_name or f"Material_{spec.source_id}", row), 0, 0)
            row_layout.addWidget(QLabel(str(spec.source_id), row), 0, 1)
            path_edit = _make_path_edit(spec.ue_asset_path, row, placeholder="/Game/Path/Material.Material")
            path_edit.textChanged.connect(lambda _text: self._on_change())
            row_layout.addWidget(path_edit, 0, 2)
            self._base_rows.append(
                BaseMaterialRowWidgets(
                    source_id=spec.source_id,
                    source_name=spec.source_name,
                    path_edit=path_edit,
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
            form.setHorizontalSpacing(10)
            form.setVerticalSpacing(8)
            mode_combo = NoWheelComboBox(row_card)
            mode_combo.addItem("Vertex Color Split", FbxMaterialMode.VERTEX_COLOR_SPLIT.value)
            mode_combo.addItem("Single Material", FbxMaterialMode.SINGLE_MATERIAL.value)
            mode_combo.setObjectName("InteractiveCombo")
            _set_combo_value(mode_combo, spec.fbx_material_mode.value)

            single_edit = _make_path_edit(spec.single_material_path, row_card, placeholder="/Game/Path/Material.Material")
            black_edit = _make_path_edit(spec.black_material_path, row_card, placeholder="/Game/Path/Black.Material")
            white_edit = _make_path_edit(spec.white_material_path, row_card, placeholder="/Game/Path/White.Material")
            material_mode_label = QLabel("Part Material Mode", row_card)
            single_label = QLabel("Single Material", row_card)
            black_label = QLabel("Black Material", row_card)
            white_label = QLabel("White Material", row_card)

            form.addWidget(material_mode_label, 0, 0)
            form.addWidget(mode_combo, 0, 1)
            form.addWidget(single_label, 1, 0)
            form.addWidget(single_edit, 1, 1)
            form.addWidget(black_label, 2, 0)
            form.addWidget(black_edit, 2, 1)
            form.addWidget(white_label, 3, 0)
            form.addWidget(white_edit, 3, 1)
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
                black_label=black_label,
                black_edit=black_edit,
                white_label=white_label,
                white_edit=white_edit,
                slots_frame=slots_frame,
                slots_layout=slots_layout,
                slot_rows=[],
                restored_slot_override_records=spec.fbx_material_slot_overrides,
                header_label=header_label,
            )
            self._part_rows.append(row)
            mode_combo.currentIndexChanged.connect(lambda _index, current=row: self._handle_material_mode_changed(current))
            single_edit.textChanged.connect(lambda _text: self._on_change())
            black_edit.textChanged.connect(lambda _text: self._on_change())
            white_edit.textChanged.connect(lambda _text: self._on_change())
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
        row.black_label.setVisible(split_visible)
        row.black_edit.setVisible(split_visible)
        row.black_edit.setEnabled(split_visible)
        row.white_label.setVisible(split_visible)
        row.white_edit.setVisible(split_visible)
        row.white_edit.setEnabled(split_visible)

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
        layout.setHorizontalSpacing(10)
        label = QLabel(f"{slot_spec.slot_name} ({slot_spec.face_count} faces)", widget)
        edit = _make_path_edit(slot_spec.ue_asset_path, widget, placeholder="/Game/Path/Material.Material")
        edit.textChanged.connect(lambda _text: self._on_change())
        layout.addWidget(label, 0, 0)
        layout.addWidget(edit, 0, 1)
        row.slot_rows.append(SlotOverrideWidgets(slot_name=slot_spec.slot_name, path_edit=edit))
        return widget
