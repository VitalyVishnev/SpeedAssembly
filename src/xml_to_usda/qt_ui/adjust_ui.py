"""Interactive Adjust UI editor for the PySide6 shell.

Layer: UI.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .theme import (
    ResolvedTheme,
    ThemeOverrides,
    ThemeSpec,
    available_asset_options,
    delete_nested_value,
    get_nested_value,
    merge_theme,
    set_nested_value,
)


@dataclass(frozen=True)
class ThemeFieldDefinition:
    category: str
    label: str
    path: tuple[str, ...]
    kind: str
    minimum: float | int | None = None
    maximum: float | int | None = None
    step: float | int | None = None
    option_source: tuple[str, ...] | None = None


def build_theme_field_definitions() -> tuple[ThemeFieldDefinition, ...]:
    return (
        ThemeFieldDefinition("Window", "Window Corner Radius", ("radii", "window"), "int", 0, 64, 1),
        ThemeFieldDefinition("Window", "Outer Margin", ("spacing", "outer_margin"), "int", 0, 64, 1),
        ThemeFieldDefinition("Window", "Panel Min Width Clamp", ("layout", "panel_min_width"), "int", 320, 2200, 10),
        ThemeFieldDefinition("Window", "Panel Width", ("layout", "panel_preferred_width"), "int", 360, 2600, 10),
        ThemeFieldDefinition("Window", "Panel Max Width Clamp", ("layout", "panel_max_width"), "int", 400, 3200, 10),
        ThemeFieldDefinition("Window", "Panel Height", ("layout", "panel_min_height"), "int", 320, 2200, 10),
        ThemeFieldDefinition("Window", "Panel Vertical Offset", ("layout", "panel_vertical_offset"), "int", -480, 480, 1),
        ThemeFieldDefinition("Title Bar", "Title Bar Fill", ("chrome", "titlebar_fill"), "color"),
        ThemeFieldDefinition("Title Bar", "Title Bar Text", ("chrome", "titlebar_text"), "color"),
        ThemeFieldDefinition("Title Bar", "Title Control Fill", ("colors", "chrome_control_fill"), "color"),
        ThemeFieldDefinition("Title Bar", "Title Control Hover", ("colors", "chrome_control_hover_fill"), "color"),
        ThemeFieldDefinition("Title Bar", "Title Bar Height", ("control_heights", "titlebar"), "int", 12, 120, 1),
        ThemeFieldDefinition("Title Bar", "Window Button Size", ("chrome", "window_button_size"), "int", 10, 72, 1),
        ThemeFieldDefinition("Title Bar", "LOG Pill Width", ("chrome", "title_pill_width"), "int", 24, 320, 1),
        ThemeFieldDefinition("Title Bar", "LOG Pill Height", ("chrome", "title_pill_height"), "int", 10, 72, 1),
        ThemeFieldDefinition("Title Bar", "Adjust UI Width", ("chrome", "adjust_ui_button_width"), "int", 24, 360, 1),
        ThemeFieldDefinition("Title Bar", "Adjust UI Height", ("chrome", "adjust_ui_button_height"), "int", 10, 72, 1),
        ThemeFieldDefinition("Main Glass", "Glass Radius", ("radii", "panel"), "int", 8, 64, 1),
        ThemeFieldDefinition("Main Glass", "Glass Tint", ("glass", "tint_color"), "color"),
        ThemeFieldDefinition("Main Glass", "Tint Opacity", ("glass", "tint_opacity"), "float", 0.0, 1.0, 0.01),
        ThemeFieldDefinition("Main Glass", "Glass Border Color", ("glass", "border_color"), "color"),
        ThemeFieldDefinition("Main Glass", "Border Opacity", ("glass", "border_opacity"), "float", 0.0, 1.0, 0.01),
        ThemeFieldDefinition("Main Glass", "Border Width", ("border_widths", "panel"), "int", 0, 6, 1),
        ThemeFieldDefinition("Main Glass", "Light Gradient Opacity", ("glass", "light_gradient_opacity"), "float", 0.0, 1.0, 0.01),
        ThemeFieldDefinition("Main Glass", "Mid Light Opacity", ("glass", "light_gradient_mid_opacity"), "float", 0.0, 1.0, 0.01),
        ThemeFieldDefinition("Main Glass", "Light Gradient Height", ("glass", "light_gradient_height"), "float", 0.0, 1.0, 0.01),
        ThemeFieldDefinition("Main Glass", "Dark Gradient Opacity", ("glass", "dark_gradient_opacity"), "float", 0.0, 1.0, 0.01),
        ThemeFieldDefinition("Main Glass", "Dark Gradient Height", ("glass", "dark_gradient_height"), "float", 0.0, 1.0, 0.01),
        ThemeFieldDefinition("Main Glass", "Noise Asset", ("glass", "noise_asset"), "choice", option_source=("assets", "noise_assets")),
        ThemeFieldDefinition("Main Glass", "Noise Opacity", ("glass", "noise_opacity"), "float", 0.0, 1.0, 0.01),
        ThemeFieldDefinition("Main Glass", "Noise Scale", ("glass", "noise_scale"), "float", 0.25, 8.0, 0.05),
        ThemeFieldDefinition("Main Glass", "Shadow Blur", ("effects", "panel_shadow_blur"), "int", 0, 80, 1),
        ThemeFieldDefinition("Main Glass", "Shadow Alpha", ("effects", "panel_shadow_alpha"), "int", 0, 255, 1),
        ThemeFieldDefinition("Main Glass", "Shadow Y Offset", ("effects", "panel_shadow_offset_y"), "int", 0, 20, 1),
        ThemeFieldDefinition("Cards", "Card Fill", ("colors", "card_fill"), "color"),
        ThemeFieldDefinition("Cards", "Card Text", ("colors", "card_text"), "color"),
        ThemeFieldDefinition("Cards", "Card Border", ("colors", "card_border"), "color"),
        ThemeFieldDefinition("Cards", "Card Radius", ("radii", "card"), "int", 4, 48, 1),
        ThemeFieldDefinition("Cards", "Card Border Width", ("border_widths", "card"), "int", 0, 6, 1),
        ThemeFieldDefinition("Buttons", "Primary Fill", ("colors", "button_fill"), "color"),
        ThemeFieldDefinition("Buttons", "Button Text", ("colors", "button_text"), "color"),
        ThemeFieldDefinition("Buttons", "Secondary Fill", ("colors", "secondary_fill"), "color"),
        ThemeFieldDefinition("Buttons", "Hover Accent", ("colors", "accent_fill"), "color"),
        ThemeFieldDefinition("Buttons", "Shared Control Fill", ("colors", "control_fill"), "color"),
        ThemeFieldDefinition("Buttons", "Shared Control Hover", ("colors", "control_hover_fill"), "color"),
        ThemeFieldDefinition("Buttons", "Danger Fill", ("colors", "danger_fill"), "color"),
        ThemeFieldDefinition("Buttons", "Button Radius", ("radii", "button"), "int", 4, 48, 1),
        ThemeFieldDefinition("Buttons", "Button Height", ("control_heights", "button"), "int", 18, 96, 1),
        ThemeFieldDefinition("Buttons", "Action Column Width", ("layout", "action_column_width"), "int", 80, 420, 1),
        ThemeFieldDefinition("Buttons", "File Button Width", ("chrome", "file_button_width"), "int", 36, 220, 1),
        ThemeFieldDefinition("Buttons", "File Button Height", ("chrome", "file_button_height"), "int", 18, 96, 1),
        ThemeFieldDefinition("Buttons", "Refresh Button Width", ("chrome", "wind_refresh_button_width"), "int", 60, 280, 1),
        ThemeFieldDefinition("Buttons", "Refresh Button Height", ("chrome", "wind_refresh_button_height"), "int", 18, 72, 1),
        ThemeFieldDefinition("Inputs", "Input Fill", ("colors", "input_fill"), "color"),
        ThemeFieldDefinition("Inputs", "Input Text", ("colors", "input_text"), "color"),
        ThemeFieldDefinition("Inputs", "Path Input Fill", ("colors", "path_input_fill"), "color"),
        ThemeFieldDefinition("Inputs", "Path Input Hover", ("colors", "path_input_hover_fill"), "color"),
        ThemeFieldDefinition("Inputs", "Path Input Border", ("colors", "path_input_border"), "color"),
        ThemeFieldDefinition("Inputs", "Path Input Focus Border", ("colors", "path_input_focus_border"), "color"),
        ThemeFieldDefinition("Inputs", "Input Radius", ("radii", "control"), "int", 4, 48, 1),
        ThemeFieldDefinition("Inputs", "Input Height", ("control_heights", "input"), "int", 18, 96, 1),
        ThemeFieldDefinition("Tabs", "Tab Fill", ("colors", "tab_fill"), "color"),
        ThemeFieldDefinition("Tabs", "Tab Selected Fill", ("colors", "tab_selected_fill"), "color"),
        ThemeFieldDefinition("Tabs", "Tab Hover Fill", ("colors", "tab_hover_fill"), "color"),
        ThemeFieldDefinition("Tabs", "Tab Text", ("colors", "tab_text"), "color"),
        ThemeFieldDefinition("Tabs", "Tab Radius", ("radii", "tab"), "int", 4, 48, 1),
        ThemeFieldDefinition("Tabs", "Tab Min Width", ("layout", "tab_min_width"), "int", 48, 320, 1),
        ThemeFieldDefinition("Tabs", "Tabs Height", ("layout", "tabs_min_height"), "int", 180, 1200, 10),
        ThemeFieldDefinition("Typography", "Title Font", ("font_sizes", "title"), "int", 10, 32, 1),
        ThemeFieldDefinition("Typography", "Body Font", ("font_sizes", "body"), "int", 10, 28, 1),
        ThemeFieldDefinition("Typography", "Small Font", ("font_sizes", "small"), "int", 8, 22, 1),
        ThemeFieldDefinition("Layout", "Panel Padding", ("spacing", "panel_padding"), "int", 0, 120, 1),
        ThemeFieldDefinition("Layout", "Section Gap", ("spacing", "section_gap"), "int", 0, 96, 1),
        ThemeFieldDefinition("Layout", "Control Gap", ("spacing", "control_gap"), "int", 0, 72, 1),
        ThemeFieldDefinition("Layout", "File Row Gap", ("layout", "file_row_gap"), "int", -24, 96, 1),
        ThemeFieldDefinition("Layout", "Left Column Width", ("layout", "left_column_width"), "int", 120, 720, 1),
        ThemeFieldDefinition("Assets", "Background", ("assets", "background_image"), "choice", option_source=("assets", "background_options")),
        ThemeFieldDefinition("Assets", "Blur Background", ("assets", "background_blur_image"), "choice", option_source=("assets", "background_blur_options")),
    )


class NumberEditor(QWidget):
    valueChanged = Signal(object)

    def __init__(
        self,
        *,
        value: float | int,
        minimum: float,
        maximum: float,
        step: float,
        is_float: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._is_float = is_float
        self._scale = 100 if is_float else 1
        self._slider_minimum = int(round(minimum * self._scale))
        self._slider_maximum = int(round(maximum * self._scale))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(self._slider_minimum, self._slider_maximum)
        self.slider.setSingleStep(max(1, int(round(step * self._scale))))
        layout.addWidget(self.slider, 1)

        if is_float:
            self.spin = QDoubleSpinBox(self)
            self.spin.setDecimals(2)
            self.spin.setRange(min(minimum, -100000.0), max(maximum, 100000.0))
            self.spin.setSingleStep(step)
        else:
            self.spin = QSpinBox(self)
            self.spin.setRange(min(int(round(minimum)), -1000000), max(int(round(maximum)), 1000000))
            self.spin.setSingleStep(int(round(step)))
        self.spin.setAccelerated(True)
        self.spin.setMinimumWidth(88)
        layout.addWidget(self.spin, 0)

        self.slider.valueChanged.connect(self._handle_slider_changed)
        self.spin.valueChanged.connect(self._handle_spin_changed)
        self.set_value(value)

    def value(self) -> float | int:
        return self.spin.value()

    def set_value(self, value: float | int) -> None:
        with QSignalBlocker(self.slider), QSignalBlocker(self.spin):
            self.spin.setValue(value)
            self.slider.setValue(self._clamp_slider_value(value))

    def _handle_slider_changed(self, raw_value: int) -> None:
        value = raw_value / self._scale if self._is_float else raw_value
        with QSignalBlocker(self.spin):
            self.spin.setValue(value)
        self.valueChanged.emit(self.spin.value())

    def _handle_spin_changed(self, value: float) -> None:
        with QSignalBlocker(self.slider):
            self.slider.setValue(self._clamp_slider_value(value))
        self.valueChanged.emit(self.spin.value())

    def _clamp_slider_value(self, value: float | int) -> int:
        raw_value = int(round(float(value) * self._scale))
        return max(self._slider_minimum, min(self._slider_maximum, raw_value))


class ColorEditor(QWidget):
    valueChanged = Signal(str)

    def __init__(self, value: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)
        self.preview = QFrame(self)
        self.preview.setFixedSize(28, 28)
        self.preview.setObjectName("EditorPanelCard")
        top_row.addWidget(self.preview, 0)
        self.hex_input = QLineEdit(self)
        self.hex_input.setPlaceholderText("#RRGGBB or #AARRGGBB")
        top_row.addWidget(self.hex_input, 1)
        layout.addLayout(top_row)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        self.h_spin = QSpinBox(self)
        self.h_spin.setRange(0, 359)
        self.s_spin = QSpinBox(self)
        self.s_spin.setRange(0, 255)
        self.v_spin = QSpinBox(self)
        self.v_spin.setRange(0, 255)
        self.a_spin = QSpinBox(self)
        self.a_spin.setRange(0, 255)
        for column, (label_text, spin) in enumerate((("H", self.h_spin), ("S", self.s_spin), ("V", self.v_spin), ("A", self.a_spin))):
            grid.addWidget(QLabel(label_text, self), 0, column)
            grid.addWidget(spin, 1, column)
        layout.addLayout(grid)

        self.hex_input.editingFinished.connect(self._handle_hex_edited)
        self.h_spin.valueChanged.connect(self._handle_hsva_changed)
        self.s_spin.valueChanged.connect(self._handle_hsva_changed)
        self.v_spin.valueChanged.connect(self._handle_hsva_changed)
        self.a_spin.valueChanged.connect(self._handle_hsva_changed)
        self.set_value(value)

    def set_value(self, value: str) -> None:
        color = _color_from_string(value)
        self._apply_color(color, emit=False)

    def value(self) -> str:
        return self.hex_input.text().strip()

    def _handle_hex_edited(self) -> None:
        color = _color_from_string(self.hex_input.text().strip())
        self._apply_color(color, emit=True)

    def _handle_hsva_changed(self) -> None:
        color = QColor()
        color.setHsv(self.h_spin.value(), self.s_spin.value(), self.v_spin.value(), self.a_spin.value())
        self._apply_color(color, emit=True)

    def _apply_color(self, color: QColor, *, emit: bool) -> None:
        hex_value = _color_to_serialized_hex(color)
        with QSignalBlocker(self.hex_input), QSignalBlocker(self.h_spin), QSignalBlocker(self.s_spin), QSignalBlocker(self.v_spin), QSignalBlocker(self.a_spin):
            self.hex_input.setText(hex_value)
            self.h_spin.setValue(color.hsvHue() if color.hsvHue() >= 0 else 0)
            self.s_spin.setValue(color.hsvSaturation())
            self.v_spin.setValue(color.value())
            self.a_spin.setValue(color.alpha())
        self.preview.setStyleSheet(f"background: {hex_value}; border-radius: 8px; border: 1px solid rgba(0, 0, 0, 0.15);")
        if emit:
            self.valueChanged.emit(hex_value)


class ChoiceEditor(QComboBox):
    valueChanged = Signal(str)

    def __init__(self, options: dict[str, str], value: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._options = options
        for label, option_value in options.items():
            self.addItem(label, option_value)
        if value and self.findData(value) == -1:
            self.addItem(Path(value).name or value, value)
        self.currentIndexChanged.connect(self._handle_index_changed)
        self.set_value(value)

    def set_value(self, value: str) -> None:
        index = self.findData(value)
        if index >= 0:
            with QSignalBlocker(self):
                self.setCurrentIndex(index)

    def value(self) -> str:
        return str(self.currentData())

    def _handle_index_changed(self, _index: int) -> None:
        self.valueChanged.emit(self.value())


class BoolEditor(QCheckBox):
    valueChanged = Signal(bool)

    def __init__(self, value: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.toggled.connect(self.valueChanged.emit)
        self.setChecked(value)

    def set_value(self, value: bool) -> None:
        with QSignalBlocker(self):
            self.setChecked(value)

    def value(self) -> bool:
        return self.isChecked()


@dataclass
class FieldBinding:
    definition: ThemeFieldDefinition
    editor: QWidget
    set_value: Callable[[Any], None]


class AdjustUiDialog(QDialog):
    def __init__(
        self,
        *,
        base_theme: ThemeSpec,
        applied_overrides: ThemeOverrides,
        current_theme: ResolvedTheme,
        on_preview: Callable[[ThemeOverrides, ResolvedTheme], None],
        on_apply: Callable[[ThemeOverrides, ResolvedTheme], None],
        on_save: Callable[[ThemeOverrides, ResolvedTheme], None],
        on_export: Callable[[ResolvedTheme], Path],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AdjustUiWindow")
        self.setWindowTitle("Adjust UI")
        self.resize(1160, 820)
        self.setModal(False)

        self._base_theme = base_theme
        self._applied_overrides = ThemeOverrides(applied_overrides.theme_name, deepcopy(applied_overrides.payload))
        self._working_overrides = ThemeOverrides(applied_overrides.theme_name, deepcopy(applied_overrides.payload))
        self._current_theme = current_theme
        self._on_preview = on_preview
        self._on_apply = on_apply
        self._on_save = on_save
        self._on_export = on_export
        self._dirty = False
        self._field_definitions = build_theme_field_definitions()
        self._field_bindings: dict[tuple[str, ...], FieldBinding] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        header = QLabel("Adjust UI", self)
        header.setObjectName("TitleLabel")
        root.addWidget(header, 0)

        body = QHBoxLayout()
        body.setSpacing(14)

        self.category_list = QListWidget(self)
        self.category_list.setObjectName("AdjustUiCategoryList")
        self.category_list.setMinimumWidth(210)
        body.addWidget(self.category_list, 0)

        self.pages = QStackedWidget(self)
        body.addWidget(self.pages, 1)
        root.addLayout(body, 1)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.status_label = QLabel("No unsaved UI changes.", self)
        self.status_label.setObjectName("MutedLabel")
        footer.addWidget(self.status_label, 1)

        self.export_button = QPushButton("Export Current Theme", self)
        self.export_button.setObjectName("EditorActionButton")
        self.export_button.clicked.connect(self._export_current_theme)
        footer.addWidget(self.export_button, 0)

        self.reset_category_button = QPushButton("Reset Category", self)
        self.reset_category_button.setObjectName("EditorActionButton")
        self.reset_category_button.clicked.connect(self._reset_category)
        footer.addWidget(self.reset_category_button, 0)

        self.reset_all_button = QPushButton("Reset All", self)
        self.reset_all_button.setObjectName("EditorActionButton")
        self.reset_all_button.clicked.connect(self._reset_all)
        footer.addWidget(self.reset_all_button, 0)

        self.apply_button = QPushButton("Apply", self)
        self.apply_button.setObjectName("EditorActionButton")
        self.apply_button.clicked.connect(self._apply_changes)
        footer.addWidget(self.apply_button, 0)

        self.save_button = QPushButton("Save", self)
        self.save_button.setObjectName("EditorActionButton")
        self.save_button.clicked.connect(self._save_changes)
        footer.addWidget(self.save_button, 0)

        self.close_button = QPushButton("Close", self)
        self.close_button.setObjectName("EditorActionButton")
        self.close_button.clicked.connect(self.close)
        footer.addWidget(self.close_button, 0)
        root.addLayout(footer, 0)

        self._build_pages()
        self.category_list.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.category_list.setCurrentRow(0)
        self._sync_widgets_from_theme()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._dirty:
            reverted_theme = merge_theme(self._base_theme, self._applied_overrides)
            self._on_preview(self._applied_overrides, reverted_theme)
        super().closeEvent(event)

    def _build_pages(self) -> None:
        categories: list[str] = []
        seen: set[str] = set()
        for definition in self._field_definitions:
            if definition.category not in seen:
                seen.add(definition.category)
                categories.append(definition.category)

        for category in categories:
            self.category_list.addItem(category)
            container = QWidget(self)
            scroll = QScrollArea(self)
            scroll.setWidgetResizable(True)
            scroll.setObjectName("ScrollContainer")
            scroll.setWidget(container)
            page_layout = QVBoxLayout(container)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(10)

            card = QFrame(container)
            card.setObjectName("EditorPanelCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(18, 18, 18, 18)
            card_layout.setSpacing(10)
            title = QLabel(category, card)
            title.setObjectName("EditorSectionTitle")
            card_layout.addWidget(title, 0)

            form = QFormLayout()
            form.setHorizontalSpacing(12)
            form.setVerticalSpacing(12)
            card_layout.addLayout(form, 1)

            for definition in (field for field in self._field_definitions if field.category == category):
                binding = self._create_field_binding(definition, card)
                self._field_bindings[definition.path] = binding
                form.addRow(definition.label, binding.editor)

            page_layout.addWidget(card, 0)
            page_layout.addStretch(1)
            self.pages.addWidget(scroll)

    def _create_field_binding(self, definition: ThemeFieldDefinition, parent: QWidget) -> FieldBinding:
        current_value = get_nested_value(self._current_theme.__dict__, definition.path)
        if definition.kind == "int":
            editor = NumberEditor(
                value=int(current_value),
                minimum=float(definition.minimum or 0),
                maximum=float(definition.maximum or 100),
                step=float(definition.step or 1),
                is_float=False,
                parent=parent,
            )
            editor.valueChanged.connect(lambda value, d=definition: self._handle_field_changed(d, int(value)))
            return FieldBinding(definition, editor, editor.set_value)
        if definition.kind == "float":
            editor = NumberEditor(
                value=float(current_value),
                minimum=float(definition.minimum or 0.0),
                maximum=float(definition.maximum or 1.0),
                step=float(definition.step or 0.01),
                is_float=True,
                parent=parent,
            )
            editor.valueChanged.connect(lambda value, d=definition: self._handle_field_changed(d, float(value)))
            return FieldBinding(definition, editor, editor.set_value)
        if definition.kind == "color":
            editor = ColorEditor(str(current_value), parent)
            editor.valueChanged.connect(lambda value, d=definition: self._handle_field_changed(d, value))
            return FieldBinding(definition, editor, editor.set_value)
        if definition.kind == "choice":
            options = available_asset_options(self._current_theme, definition.option_source[1]) if definition.option_source else {}
            editor = ChoiceEditor(options, str(current_value), parent)
            editor.valueChanged.connect(lambda value, d=definition: self._handle_field_changed(d, value))
            return FieldBinding(definition, editor, editor.set_value)
        if definition.kind == "bool":
            editor = BoolEditor(bool(current_value), parent)
            editor.valueChanged.connect(lambda value, d=definition: self._handle_field_changed(d, bool(value)))
            return FieldBinding(definition, editor, editor.set_value)
        raise ValueError(f"Unsupported theme editor field kind: {definition.kind}")

    def _handle_field_changed(self, definition: ThemeFieldDefinition, value: Any) -> None:
        payload = deepcopy(self._working_overrides.payload)
        set_nested_value(payload, definition.path, value)
        self._working_overrides = ThemeOverrides(self._working_overrides.theme_name, payload)
        self._recompute_preview()

    def _recompute_preview(self) -> None:
        self._current_theme = merge_theme(self._base_theme, self._working_overrides)
        self._dirty = self._working_overrides.payload != self._applied_overrides.payload
        self._status()
        self._on_preview(self._working_overrides, self._current_theme)

    def _sync_widgets_from_theme(self) -> None:
        theme_payload = self._current_theme.__dict__
        for binding in self._field_bindings.values():
            value = get_nested_value(theme_payload, binding.definition.path)
            binding.set_value(value)

    def _apply_changes(self) -> None:
        self._applied_overrides = ThemeOverrides(self._working_overrides.theme_name, deepcopy(self._working_overrides.payload))
        self._dirty = False
        self._status()
        self._on_apply(self._applied_overrides, self._current_theme)

    def _save_changes(self) -> None:
        self._apply_changes()
        self._on_save(self._applied_overrides, self._current_theme)
        self.status_label.setText("Theme overrides saved.")

    def _export_current_theme(self) -> None:
        export_path = self._on_export(self._current_theme)
        QMessageBox.information(self, "Theme exported", f"Exported merged theme to:\n{export_path}")

    def _reset_category(self) -> None:
        current_item = self.category_list.currentItem()
        if current_item is None:
            return
        category = current_item.text()
        payload = deepcopy(self._working_overrides.payload)
        for definition in (field for field in self._field_definitions if field.category == category):
            delete_nested_value(payload, definition.path)
        self._working_overrides = ThemeOverrides(self._working_overrides.theme_name, payload)
        self._current_theme = merge_theme(self._base_theme, self._working_overrides)
        self._sync_widgets_from_theme()
        self._recompute_preview()

    def _reset_all(self) -> None:
        self._working_overrides = ThemeOverrides(self._working_overrides.theme_name, {})
        self._current_theme = merge_theme(self._base_theme, self._working_overrides)
        self._sync_widgets_from_theme()
        self._recompute_preview()

    def _status(self) -> None:
        self.status_label.setText("Unsaved UI changes." if self._dirty else "No unsaved UI changes.")
        self.setWindowTitle("Adjust UI*" if self._dirty else "Adjust UI")


def _color_from_string(value: str) -> QColor:
    normalized = (value or "#000000").strip()
    color = QColor(normalized)
    if not color.isValid():
        color = QColor("#DCE5E8")
    return color


def _color_to_serialized_hex(color: QColor) -> str:
    if color.alpha() < 255:
        return f"#{color.alpha():02X}{color.red():02X}{color.green():02X}{color.blue():02X}"
    return color.name().upper()
