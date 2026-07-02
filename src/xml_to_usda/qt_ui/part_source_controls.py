"""Reusable Qt controls for one repeated-part Prototype Source row.

Layer: UI.

This module owns the editing pattern for source mode, repeated-part material
mode, material + UDIM rows, preview display mode, and simplification percent.
Callers still own persistence, conversion planning, FBX slot discovery, and
preview worker lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..models import FbxMaterialMode, FbxMaterialSlotOverride, PrototypeSourceConfig, PrototypeSourceMode, UdimMode
from ..part_preview_service import PartPreviewDisplayMode
from .material_controls import MaterialUdimRow, MaterialUdimValue, NoWheelComboBox, make_path_edit, set_combo_value, set_tooltip


@dataclass(frozen=True)
class PartSourceMaterialValue:
    source_key: str
    source_name: str = ""
    source_mode: PrototypeSourceMode = PrototypeSourceMode.XML_MESH
    unreal_asset_path: str = ""
    fbx_path: str = ""
    fbx_material_mode: FbxMaterialMode = FbxMaterialMode.VERTEX_COLOR_SPLIT
    single_material: MaterialUdimValue = MaterialUdimValue()
    black_material: MaterialUdimValue = MaterialUdimValue()
    white_material: MaterialUdimValue = MaterialUdimValue()
    fbx_material_slot_overrides: tuple[FbxMaterialSlotOverride, ...] = ()
    simplification_percent: int = 100
    display_mode: PartPreviewDisplayMode = PartPreviewDisplayMode.DEFAULT

    def to_prototype_source_config(self) -> PrototypeSourceConfig:
        return PrototypeSourceConfig(
            source_key=self.source_key,
            source_name=self.source_name,
            mode=self.source_mode,
            asset_path=self.unreal_asset_path or None,
            fbx_path=self.fbx_path or None,
            fbx_material_mode=self.fbx_material_mode,
            single_material_path=self.single_material.material_path or None,
            single_material_udim_mode=self.single_material.udim_mode,
            single_material_udim_id=self.single_material.udim_id,
            black_material_path=self.black_material.material_path or None,
            black_material_udim_mode=self.black_material.udim_mode,
            black_material_udim_id=self.black_material.udim_id,
            white_material_path=self.white_material.material_path or None,
            white_material_udim_mode=self.white_material.udim_mode,
            white_material_udim_id=self.white_material.udim_id,
            fbx_material_slot_overrides=self.fbx_material_slot_overrides,
            simplification_percent=self.simplification_percent,
        )


class PartSourceMaterialEditor(QWidget):
    valueChanged = Signal()
    previewAffectingChanged = Signal()
    simplificationReleased = Signal()

    def __init__(
        self,
        *,
        value: PartSourceMaterialValue,
        browse_fbx=None,
        inspect_fbx_slots: Callable[[str, tuple[FbxMaterialSlotOverride, ...]], tuple[object, ...]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._source_key = value.source_key
        self._source_name = value.source_name
        self._slot_overrides = value.fbx_material_slot_overrides
        self._browse_fbx = browse_fbx or (lambda edit: None)
        self._inspect_fbx_slots = inspect_fbx_slots
        self._slot_rows: list[tuple[str, MaterialUdimRow]] = []
        self._triangle_section_counts: tuple[int, ...] = ()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        source_grid = QGridLayout()
        source_grid.setHorizontalSpacing(8)
        source_grid.setVerticalSpacing(6)
        self.source_mode_combo = NoWheelComboBox(self)
        self.source_mode_combo.addItem("XML", PrototypeSourceMode.XML_MESH.value)
        self.source_mode_combo.addItem("FBX", PrototypeSourceMode.FBX_FILE.value)
        self.source_mode_combo.addItem("Unreal Path", PrototypeSourceMode.UNREAL_ASSET.value)
        set_combo_value(self.source_mode_combo, value.source_mode.value)
        set_tooltip(
            "Chooses the prototype source. XML keeps source mesh; FBX replaces geometry; Unreal uses an external asset.",
            self.source_mode_combo,
        )

        self.unreal_path_edit = make_path_edit(
            value.unreal_asset_path,
            self,
            placeholder="/Game/Path/Asset.Asset",
        )
        self.fbx_path_edit = make_path_edit(
            value.fbx_path,
            self,
            placeholder="Choose an FBX replacement file",
        )
        self.fbx_browse_button = QPushButton("Browse...", self)
        self.fbx_browse_button.clicked.connect(lambda _checked=False: self._browse_fbx(self.fbx_path_edit))
        source_label = QLabel("Source", self)
        set_tooltip(self.source_mode_combo.toolTip(), source_label)
        source_grid.addWidget(source_label, 0, 0)
        source_grid.addWidget(self.source_mode_combo, 0, 1, 1, 2)
        self.unreal_path_label = QLabel("Unreal Path", self)
        set_tooltip(
            "Existing Unreal asset for this prototype. Empty disables reuse; filled exports an external reference.",
            self.unreal_path_label,
            self.unreal_path_edit,
        )
        source_grid.addWidget(self.unreal_path_label, 1, 0)
        source_grid.addWidget(self.unreal_path_edit, 1, 1, 1, 2)
        self.fbx_path_label = QLabel("FBX", self)
        set_tooltip(
            "FBX mesh replacing this prototype. Empty keeps XML mesh; filled uses the FBX geometry at source instances.",
            self.fbx_path_label,
            self.fbx_path_edit,
        )
        source_grid.addWidget(self.fbx_path_label, 2, 0)
        source_grid.addWidget(self.fbx_path_edit, 2, 1)
        source_grid.addWidget(self.fbx_browse_button, 2, 2)
        self.fbx_browse_button.setToolTip("Pick an FBX replacement file for this prototype.")
        layout.addLayout(source_grid)

        self.material_frame = QFrame(self)
        material_layout = QVBoxLayout(self.material_frame)
        material_layout.setContentsMargins(0, 0, 0, 0)
        material_layout.setSpacing(8)
        mode_row = QHBoxLayout()
        material_mode_label = QLabel("Material Mode", self.material_frame)
        mode_row.addWidget(material_mode_label)
        self.material_mode_combo = NoWheelComboBox(self.material_frame)
        set_tooltip(
            "Chooses how materials are resolved. Split uses vertex colors; single forces one material; slots uses FBX slots.",
            material_mode_label,
            self.material_mode_combo,
        )
        mode_row.addWidget(self.material_mode_combo, 1)
        material_layout.addLayout(mode_row)

        self.single_row = MaterialUdimRow(
            label="Single Material",
            value=value.single_material,
            stacked_udim=True,
            parent=self.material_frame,
        )
        self.black_row = MaterialUdimRow(
            label="Black Material",
            value=value.black_material,
            stacked_udim=True,
            parent=self.material_frame,
        )
        self.white_row = MaterialUdimRow(
            label="White Material",
            value=value.white_material,
            stacked_udim=True,
            parent=self.material_frame,
        )
        material_layout.addWidget(self.single_row)
        material_layout.addWidget(self.black_row)
        material_layout.addWidget(self.white_row)
        self.slots_frame = QFrame(self.material_frame)
        self.slots_layout = QVBoxLayout(self.slots_frame)
        self.slots_layout.setContentsMargins(0, 0, 0, 0)
        self.slots_layout.setSpacing(6)
        material_layout.addWidget(self.slots_frame)
        layout.addWidget(self.material_frame)

        display_row = QHBoxLayout()
        display_label = QLabel("Display", self)
        display_row.addWidget(display_label)
        self.display_mode_combo = NoWheelComboBox(self)
        self.display_mode_combo.addItem("Default", PartPreviewDisplayMode.DEFAULT.value)
        self.display_mode_combo.addItem("Vertex Colors", PartPreviewDisplayMode.VERTEX_COLORS.value)
        self.display_mode_combo.addItem("Material Colors", PartPreviewDisplayMode.MATERIAL_COLORS.value)
        set_combo_value(self.display_mode_combo, value.display_mode.value)
        set_tooltip(
            "Preview coloring mode only. Default shows shaded mesh; higher debug modes reveal vertex/material buckets.",
            display_label,
            self.display_mode_combo,
        )
        display_row.addWidget(self.display_mode_combo, 1)
        layout.addLayout(display_row)

        self.simplification_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.simplification_slider.setRange(0, 100)
        self.simplification_slider.setValue(max(0, min(100, int(value.simplification_percent))))
        self.simplification_spin = QSpinBox(self)
        self.simplification_spin.setRange(0, 100)
        self.simplification_spin.setValue(self.simplification_slider.value())
        self.simplification_spin.setSuffix("%")
        self.simplification_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        simplify_row = QHBoxLayout()
        simplify_label = QLabel("Simplification", self)
        set_tooltip(
            "Percent of prototype triangles kept for export. Lower is lighter and rougher; higher keeps more detail.",
            simplify_label,
            self.simplification_slider,
            self.simplification_spin,
        )
        simplify_row.addWidget(simplify_label)
        simplify_row.addWidget(self.simplification_slider, 1)
        simplify_row.addWidget(self.simplification_spin)
        layout.addLayout(simplify_row)
        self.triangle_count_label = QLabel("", self)
        self.triangle_count_label.setObjectName("MutedLabel")
        layout.addWidget(self.triangle_count_label)

        self.source_mode_combo.currentIndexChanged.connect(lambda _index: self._handle_source_mode_changed())
        self.material_mode_combo.currentIndexChanged.connect(lambda _index: self._handle_material_mode_changed())
        self.display_mode_combo.currentIndexChanged.connect(lambda _index: self.previewAffectingChanged.emit())
        self.unreal_path_edit.textChanged.connect(lambda _text: self.valueChanged.emit())
        self.fbx_path_edit.textChanged.connect(lambda _text: self.previewAffectingChanged.emit())
        self.fbx_path_edit.editingFinished.connect(self._refresh_slot_rows)
        for row in (self.single_row, self.black_row, self.white_row):
            row.valueChanged.connect(lambda: self.valueChanged.emit())
        self.simplification_slider.valueChanged.connect(self._sync_slider_to_spin)
        self.simplification_spin.valueChanged.connect(self._sync_spin_to_slider)
        self.simplification_slider.sliderReleased.connect(self.simplificationReleased.emit)
        self.simplification_spin.editingFinished.connect(self.simplificationReleased.emit)

        self._refresh_material_modes(value.fbx_material_mode)
        self._refresh_display_modes(value.display_mode)
        self._apply_visibility()

    def value(self) -> PartSourceMaterialValue:
        return PartSourceMaterialValue(
            source_key=self._source_key,
            source_name=self._source_name,
            source_mode=PrototypeSourceMode(self.source_mode_combo.currentData()),
            unreal_asset_path=self.unreal_path_edit.text().strip(),
            fbx_path=self.fbx_path_edit.text().strip(),
            fbx_material_mode=FbxMaterialMode(self.material_mode_combo.currentData()),
            single_material=self.single_row.value(),
            black_material=self.black_row.value(),
            white_material=self.white_row.value(),
            fbx_material_slot_overrides=self._current_slot_overrides(),
            simplification_percent=int(self.simplification_spin.value()),
            display_mode=PartPreviewDisplayMode(self.display_mode_combo.currentData()),
        )

    def set_triangle_count_text(self, text: str) -> None:
        self._triangle_section_counts = ()
        self.triangle_count_label.setText(text)

    def set_triangle_prediction_base(self, section_triangle_counts: tuple[int, ...]) -> None:
        self._triangle_section_counts = tuple(max(0, int(value)) for value in section_triangle_counts if int(value) > 0)
        self._update_triangle_count_label()

    def set_material_colors(self, material_colors) -> None:
        rows = self._active_material_rows()
        colors = list(material_colors or ())
        for _label, row in rows:
            row.set_color_dot(None)
        if PartPreviewDisplayMode(self.display_mode_combo.currentData()) != PartPreviewDisplayMode.MATERIAL_COLORS:
            return
        for (_label, row), color_entry in zip(rows, colors, strict=False):
            row.set_color_dot(getattr(color_entry, "color", None))

    def _handle_source_mode_changed(self) -> None:
        current_material_mode = FbxMaterialMode(self.material_mode_combo.currentData())
        self._refresh_material_modes(current_material_mode)
        self._refresh_display_modes(PartPreviewDisplayMode(self.display_mode_combo.currentData()))
        self._apply_visibility()
        self.previewAffectingChanged.emit()

    def _handle_material_mode_changed(self) -> None:
        self._refresh_display_modes(PartPreviewDisplayMode(self.display_mode_combo.currentData()))
        self._apply_visibility()
        self._refresh_slot_rows()
        self.previewAffectingChanged.emit()

    def _refresh_material_modes(self, preferred: FbxMaterialMode) -> None:
        mode = PrototypeSourceMode(self.source_mode_combo.currentData())
        allowed = [
            (FbxMaterialMode.SINGLE_MATERIAL, "Single Material"),
            (FbxMaterialMode.VERTEX_COLOR_SPLIT, "Vertex Color"),
        ]
        if mode == PrototypeSourceMode.FBX_FILE:
            allowed.append((FbxMaterialMode.MATERIAL_SLOTS, "FBX Materials"))
        if preferred not in {item[0] for item in allowed}:
            preferred = FbxMaterialMode.VERTEX_COLOR_SPLIT
        self.material_mode_combo.blockSignals(True)
        self.material_mode_combo.clear()
        for material_mode, label in allowed:
            self.material_mode_combo.addItem(label, material_mode.value)
        set_combo_value(self.material_mode_combo, preferred.value)
        self.material_mode_combo.blockSignals(False)

    def _refresh_display_modes(self, preferred: PartPreviewDisplayMode) -> None:
        source_mode = PrototypeSourceMode(self.source_mode_combo.currentData())
        material_mode = FbxMaterialMode(self.material_mode_combo.currentData())
        allowed = [(PartPreviewDisplayMode.DEFAULT, "Default")]
        if source_mode != PrototypeSourceMode.UNREAL_ASSET:
            if material_mode == FbxMaterialMode.VERTEX_COLOR_SPLIT:
                allowed.extend(
                    (
                        (PartPreviewDisplayMode.VERTEX_COLORS, "Vertex Colors"),
                        (PartPreviewDisplayMode.MATERIAL_COLORS, "Material Colors"),
                    )
                )
            elif material_mode == FbxMaterialMode.MATERIAL_SLOTS:
                allowed.append((PartPreviewDisplayMode.MATERIAL_COLORS, "Material Colors"))
        if preferred not in {item[0] for item in allowed}:
            preferred = PartPreviewDisplayMode.DEFAULT
        self.display_mode_combo.blockSignals(True)
        self.display_mode_combo.clear()
        for display_mode, label in allowed:
            self.display_mode_combo.addItem(label, display_mode.value)
        set_combo_value(self.display_mode_combo, preferred.value)
        self.display_mode_combo.blockSignals(False)

    def _apply_visibility(self) -> None:
        source_mode = PrototypeSourceMode(self.source_mode_combo.currentData())
        material_mode = FbxMaterialMode(self.material_mode_combo.currentData())
        is_unreal = source_mode == PrototypeSourceMode.UNREAL_ASSET
        is_fbx = source_mode == PrototypeSourceMode.FBX_FILE
        self.unreal_path_label.setVisible(is_unreal)
        self.unreal_path_edit.setVisible(is_unreal)
        self.unreal_path_edit.setEnabled(is_unreal)
        self.fbx_path_label.setVisible(is_fbx)
        self.fbx_path_edit.setVisible(is_fbx)
        self.fbx_path_edit.setEnabled(is_fbx)
        self.fbx_browse_button.setVisible(is_fbx)
        self.fbx_browse_button.setEnabled(is_fbx)
        self.material_frame.setVisible(not is_unreal)
        self.material_frame.setEnabled(not is_unreal)
        self.display_mode_combo.setEnabled(not is_unreal)
        self.simplification_slider.setEnabled(not is_unreal)
        self.simplification_spin.setEnabled(not is_unreal)
        self.single_row.set_controls_visible(not is_unreal and material_mode == FbxMaterialMode.SINGLE_MATERIAL)
        split_visible = not is_unreal and material_mode == FbxMaterialMode.VERTEX_COLOR_SPLIT
        self.black_row.set_controls_visible(split_visible)
        self.white_row.set_controls_visible(split_visible)
        slots_visible = not is_unreal and is_fbx and material_mode == FbxMaterialMode.MATERIAL_SLOTS
        self.slots_frame.setVisible(slots_visible)
        self.slots_frame.setEnabled(slots_visible)
        if slots_visible and not self._slot_rows:
            self._refresh_slot_rows()

    def _sync_slider_to_spin(self, value: int) -> None:
        if self.simplification_spin.value() != value:
            self.simplification_spin.setValue(value)
        self._update_triangle_count_label()
        self.valueChanged.emit()

    def _sync_spin_to_slider(self, value: int) -> None:
        if self.simplification_slider.value() != value:
            self.simplification_slider.setValue(value)
        self._update_triangle_count_label()
        self.valueChanged.emit()

    def _refresh_slot_rows(self) -> None:
        for index in reversed(range(self.slots_layout.count())):
            item = self.slots_layout.takeAt(index)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._slot_rows.clear()

        source_mode = PrototypeSourceMode(self.source_mode_combo.currentData())
        material_mode = FbxMaterialMode(self.material_mode_combo.currentData())
        if source_mode != PrototypeSourceMode.FBX_FILE or material_mode != FbxMaterialMode.MATERIAL_SLOTS:
            return
        fbx_path = self.fbx_path_edit.text().strip()
        if not fbx_path:
            self.slots_layout.addWidget(QLabel("Choose an FBX file to inspect material slots.", self.slots_frame))
            return
        try:
            specs = self._inspect_fbx_slots(fbx_path, self._slot_overrides) if self._inspect_fbx_slots is not None else ()
        except Exception as exc:
            self.slots_layout.addWidget(QLabel(f"FBX material slot analysis failed: {exc}", self.slots_frame))
            return
        if not specs and self._slot_overrides:
            specs = self._slot_overrides
        if not specs:
            self.slots_layout.addWidget(QLabel("No face-used FBX material slots were found in this file.", self.slots_frame))
            return
        self.slots_layout.addWidget(QLabel("FBX Material Slots", self.slots_frame))
        for spec in specs:
            slot_name = str(getattr(spec, "slot_name", ""))
            if not slot_name:
                continue
            face_count = int(getattr(spec, "face_count", 0) or 0)
            label = f"{slot_name} ({face_count} faces)" if face_count else slot_name
            row = MaterialUdimRow(
                label=label,
                value=MaterialUdimValue(
                    material_path=str(getattr(spec, "ue_asset_path", "") or ""),
                    udim_mode=UdimMode.parse(getattr(spec, "udim_mode", UdimMode.OFF)),
                    udim_id=int(getattr(spec, "udim_id", 1001) or 1001),
                ),
                stacked_udim=True,
                parent=self.slots_frame,
            )
            row.valueChanged.connect(lambda: self.valueChanged.emit())
            self.slots_layout.addWidget(row)
            self._slot_rows.append((slot_name, row))
        self._slot_overrides = ()

    def _current_slot_overrides(self) -> tuple[FbxMaterialSlotOverride, ...]:
        if self._slot_rows:
            return tuple(
                FbxMaterialSlotOverride(
                    slot_name=slot_name,
                    ue_asset_path=row.value().material_path or None,
                    udim_mode=row.value().udim_mode,
                    udim_id=row.value().udim_id,
                )
                for slot_name, row in self._slot_rows
                if slot_name.strip()
            )
        return self._slot_overrides

    def _active_material_rows(self) -> list[tuple[str, MaterialUdimRow]]:
        material_mode = FbxMaterialMode(self.material_mode_combo.currentData())
        if material_mode == FbxMaterialMode.SINGLE_MATERIAL:
            return [("single", self.single_row)]
        if material_mode == FbxMaterialMode.VERTEX_COLOR_SPLIT:
            return [("black", self.black_row), ("white", self.white_row)]
        if material_mode == FbxMaterialMode.MATERIAL_SLOTS:
            return list(self._slot_rows)
        return []

    def _update_triangle_count_label(self) -> None:
        if not self._triangle_section_counts:
            return
        percent = int(self.simplification_spin.value())
        total = sum(self._triangle_section_counts)
        predicted = _predicted_triangle_count(self._triangle_section_counts, percent)
        self.triangle_count_label.setText(
            "Triangles: "
            f"{format_triangle_count(predicted)} export / "
            f"{format_triangle_count(total)} source"
        )


def format_triangle_count(value: int) -> str:
    return f"{max(0, int(value)):,}".replace(",", " ")


def _predicted_triangle_count(section_counts: tuple[int, ...], percent: int) -> int:
    percent = max(0, min(100, int(percent)))
    if percent >= 100:
        return sum(section_counts)
    if percent <= 0:
        return len(tuple(count for count in section_counts if count > 0))
    return sum(max(1, min(count, int(round(count * percent / 100.0)))) for count in section_counts if count > 0)
