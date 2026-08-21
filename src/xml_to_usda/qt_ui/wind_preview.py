"""Wind Preview dialog."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..dynamic_wind import write_dynamic_wind_json
from ..models import Color4, DynamicWindData, DynamicWindSimulationGroup
from ..wind_external_skeleton import (
    ExternalSkeletonChoicesRequest,
    ExternalSkeletonPreviewRequest,
    external_vertical_bone_names,
    external_skeleton_backend_available,
    list_external_usd_skeletons,
    load_external_skeleton_preview,
    transform_external_skeleton_scene,
)
from ..wind_service import derive_wind_json_output_path
from ..wind_preview_service import WindPreviewResult
from ..wind_group_stack import (
    EDIT_MODE_BONES,
    EDIT_MODE_SUBTREE,
    WindFlattenResult,
    WindManualGroup,
    add_tokens_to_manual_group,
    flatten_wind_group_stack,
    make_manual_group,
    next_manual_layer_id,
    remove_tokens_from_manual_group,
    skeleton_fingerprint,
    subtree_joint_tokens,
)
from ..wind_viewport_scene import (
    AUTO_WIND_GROUP_MAX_COUNT,
    WindViewportGroup,
    WindViewportSelection,
    build_auto_wind_viewport_data,
    build_wind_viewport_bone_segments,
    build_wind_viewport_groups,
    recolor_wind_viewport_scene,
    subtree_root_from_pick_token,
)
from .material_controls import set_tooltip
from .panels import SliderSpinEditor
from .preview_shell import PreviewShellDialog, apply_compact_preview_panel_style
from .viewport import MatcapViewport


WIND_MATCAP_TINT_STRENGTH = 0.82
WIND_PREVIEW_DEFAULT_WIDTH = 1160
WIND_PREVIEW_DEFAULT_HEIGHT = 936
WIND_SETTINGS_PANEL_MIN_WIDTH = 320
WIND_SETTINGS_PANEL_DEFAULT_WIDTH = 480
LAYERS_SCROLL_MIN_HEIGHT = 92
LAYERS_SCROLL_DEFAULT_HEIGHT = 210
LAYERS_SCROLL_MAX_HEIGHT = 560
GROUPING_MODE_XML = "xml"
GROUPING_MODE_AUTO = "auto"
SOURCE_MODE_XML = "source_xml"
SOURCE_MODE_EXTERNAL = "source_external"
DISPLAY_UNITS = (("Millimeters", "mm"), ("Centimeters", "cm"), ("Meters", "m"))
DISPLAY_UP_AXES = (("Y-up", "Y"), ("Z-up", "Z"))
_WIND_GROUP_BOOLEAN_FIELDS = frozenset({"is_trunk_group", "use_dual_influence"})
_WIND_GROUP_NUMERIC_FIELDS = frozenset({"influence", "min_influence", "max_influence", "shift_top"})


class WindPreviewDialog(PreviewShellDialog):
    def __init__(
        self,
        *,
        preview: WindPreviewResult | None = None,
        external_preview_requested=None,
        wind_session_snapshot: dict[str, object] | None = None,
        wind_session_changed: Callable[[dict[str, object]], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(title="Advanced Wind Settings", parent=parent)
        self.resize(WIND_PREVIEW_DEFAULT_WIDTH, WIND_PREVIEW_DEFAULT_HEIGHT)
        self.current_preview: WindPreviewResult | None = None
        self._external_preview_requested = external_preview_requested
        self._initial_wind_session_snapshot = dict(wind_session_snapshot or {})
        self._wind_session_changed = wind_session_changed
        self._restoring_session = False
        self._selection = WindViewportSelection()
        self._group_buttons: dict[int, QPushButton] = {}
        self._group_cards: dict[int, QFrame] = {}
        self._manual_group_cards: dict[int, QFrame] = {}
        self._expanded_group_source_keys: set[str] = set()
        self._group_settings_by_source_key: dict[str, dict[str, bool | float]] = {}
        self._auto_group_count = 1
        self._auto_continuous_levels: set[int] = set()
        self._manual_groups: tuple[WindManualGroup, ...] = ()
        self._active_manual_layer_id: int | None = None
        self._undo_stack: list[tuple[tuple[WindManualGroup, ...], int | None]] = []
        self._redo_stack: list[tuple[tuple[WindManualGroup, ...], int | None]] = []
        self._active_scene = None
        self._external_skeleton_choices_path = ""
        self._external_skeleton_choice_count = 0
        self._display_source_unit = "m"
        self._display_preview_unit = "m"
        self._display_source_up_axis = "Y"
        self._display_preview_up_axis = "Y"

        self.viewport = MatcapViewport(self)
        self.viewport.set_matcap_tint_strength(WIND_MATCAP_TINT_STRENGTH)
        self.viewport.set_show_bones(True)
        self.viewport.set_bone_pick_requires_control(False)
        self.viewport.on_bone_clicked = self._edit_group_from_pick_token
        self._update_shortcut_hints()
        self.set_viewport_widget(self.viewport)

        settings_panel, panel_layout = self.create_settings_panel(
            width=WIND_SETTINGS_PANEL_MIN_WIDTH,
            default_width=WIND_SETTINGS_PANEL_DEFAULT_WIDTH,
        )
        apply_compact_preview_panel_style(settings_panel)
        panel_layout.setContentsMargins(10, 10, 10, 10)
        panel_layout.setSpacing(6)
        title = QLabel("Wind Groups", settings_panel)
        title.setStyleSheet("font-weight: 700;")
        panel_layout.addWidget(title)

        self.global_scroll = QScrollArea(settings_panel)
        self.global_scroll.setWidgetResizable(True)
        self.global_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.global_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.global_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        panel_layout.addWidget(self.global_scroll, 1)
        self.global_host = QWidget(self.global_scroll)
        settings_layout = QVBoxLayout(self.global_host)
        settings_layout.setContentsMargins(0, 0, 4, 0)
        settings_layout.setSpacing(5)
        self.global_scroll.setWidget(self.global_host)

        _add_group_header(settings_layout, settings_panel, "Source")
        self.source_mode_combo = QComboBox(settings_panel)
        self.source_mode_combo.addItem("SpeedTree XML", SOURCE_MODE_XML)
        self.source_mode_combo.addItem("External Skeleton", SOURCE_MODE_EXTERNAL)
        self.source_mode_combo.currentIndexChanged.connect(lambda _index: self._on_source_mode_changed())
        set_tooltip("Advanced Wind Settings source. XML uses the current SpeedTree tree; External loads an FBX rig or a USD skeleton.", self.source_mode_combo)
        settings_layout.addWidget(self.source_mode_combo)
        self.external_path_edit = QLineEdit(settings_panel)
        self.external_path_edit.setPlaceholderText("FBX/USD skeleton path")
        self.external_path_edit.setReadOnly(True)
        self.external_path_edit.textChanged.connect(lambda _text: self._clear_external_skeleton_choices())
        set_tooltip("Selected external skeleton file. Use Browse to select and load another file.", self.external_path_edit)
        settings_layout.addWidget(self.external_path_edit)
        self.external_skeleton_combo = QComboBox(settings_panel)
        self.external_skeleton_combo.setFixedHeight(24)
        self.external_skeleton_combo.currentIndexChanged.connect(lambda _index: self._on_external_skeleton_changed())
        set_tooltip("Skeleton prim to load from this USD file. Shown only when the file contains multiple skeletons.", self.external_skeleton_combo)
        settings_layout.addWidget(self.external_skeleton_combo)
        external_row = QWidget(settings_panel)
        external_layout = QHBoxLayout(external_row)
        external_layout.setContentsMargins(0, 0, 0, 0)
        external_layout.setSpacing(6)
        self.browse_external_button = QPushButton("Browse", external_row)
        self.browse_external_button.clicked.connect(self.browse_external_path)
        self.browse_external_button.setFixedHeight(24)
        external_layout.addWidget(self.browse_external_button, 1)
        settings_layout.addWidget(external_row)

        self.external_display_transform_frame = QFrame(settings_panel)
        self.external_display_transform_frame.setObjectName("LayerCard")
        transform_layout = QFormLayout(self.external_display_transform_frame)
        transform_layout.setContentsMargins(6, 5, 6, 5)
        transform_layout.setSpacing(4)
        transform_title = QLabel("Display Transform", self.external_display_transform_frame)
        transform_title.setStyleSheet("font-weight: 600;")
        transform_layout.addRow(transform_title)
        self.source_units_combo = _display_combo(DISPLAY_UNITS, self.external_display_transform_frame)
        self.preview_units_combo = _display_combo(DISPLAY_UNITS, self.external_display_transform_frame)
        self.source_up_axis_combo = _display_combo(DISPLAY_UP_AXES, self.external_display_transform_frame)
        self.preview_up_axis_combo = _display_combo(DISPLAY_UP_AXES, self.external_display_transform_frame)
        _set_combo_data(self.source_units_combo, self._display_source_unit)
        _set_combo_data(self.preview_units_combo, self._display_preview_unit)
        _set_combo_data(self.source_up_axis_combo, self._display_source_up_axis)
        _set_combo_data(self.preview_up_axis_combo, self._display_preview_up_axis)
        transform_layout.addRow("Source Units", self.source_units_combo)
        transform_layout.addRow("Preview Units", self.preview_units_combo)
        transform_layout.addRow("Source Up Axis", self.source_up_axis_combo)
        transform_layout.addRow("Preview Up Axis", self.preview_up_axis_combo)
        self.external_vertical_warning_label = QLabel(self.external_display_transform_frame)
        self.external_vertical_warning_label.setObjectName("ProgramStatusWarning")
        self.external_vertical_warning_label.setWordWrap(True)
        self.external_vertical_warning_label.hide()
        transform_layout.addRow(self.external_vertical_warning_label)
        for combo in (
            self.source_units_combo,
            self.preview_units_combo,
            self.source_up_axis_combo,
            self.preview_up_axis_combo,
        ):
            combo.currentIndexChanged.connect(lambda _index: self._on_external_display_transform_changed())
        settings_layout.addWidget(self.external_display_transform_frame)

        self.external_diagnostics_frame = QFrame(settings_panel)
        self.external_diagnostics_frame.setObjectName("LayerCard")
        diagnostics_layout = QVBoxLayout(self.external_diagnostics_frame)
        diagnostics_layout.setContentsMargins(6, 5, 6, 5)
        diagnostics_layout.setSpacing(4)
        diagnostics_title = QLabel("FBX Diagnostics", self.external_diagnostics_frame)
        diagnostics_title.setStyleSheet("font-weight: 600;")
        diagnostics_layout.addWidget(diagnostics_title)
        self.external_diagnostics_label = QLabel("Load an FBX rig to inspect it.", self.external_diagnostics_frame)
        self.external_diagnostics_label.setWordWrap(True)
        self.external_diagnostics_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        diagnostics_layout.addWidget(self.external_diagnostics_label)
        settings_layout.addWidget(self.external_diagnostics_frame)
        self._external_controls = (
            self.external_path_edit,
            self.external_skeleton_combo,
            external_row,
            self.external_display_transform_frame,
        )
        self.total_bones_label = QLabel("Total bones: —", settings_panel)
        self.total_bones_label.setObjectName("MutedText")
        settings_layout.addWidget(self.total_bones_label)

        _add_group_header(settings_layout, settings_panel, "Grouping")
        mode_label = QLabel("Mode", settings_panel)
        self.grouping_mode_combo = QComboBox(settings_panel)
        self.grouping_mode_combo.addItem("XML Generator Groups", GROUPING_MODE_XML)
        self.grouping_mode_combo.addItem("Auto Hierarchy", GROUPING_MODE_AUTO)
        set_tooltip(
            "Wind grouping source. Auto follows skeleton order; layer checkboxes allow endpoint-continuous chains.",
            mode_label,
            self.grouping_mode_combo,
        )
        settings_layout.addWidget(mode_label)
        settings_layout.addWidget(self.grouping_mode_combo)

        self.group_count_slider = QSlider(Qt.Orientation.Horizontal, settings_panel)
        self.group_count_slider.setRange(1, AUTO_WIND_GROUP_MAX_COUNT)
        self.group_count_slider.setSingleStep(1)
        self.group_count_slider.setPageStep(1)
        self.group_count_slider.setTickInterval(1)
        self.group_count_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.group_count_slider.setValue(self._auto_group_count)
        self.group_count_label = QLabel("Groups: 1", settings_panel)
        set_tooltip(
            "Auto group count. Lower merges branch levels; higher separates deeper fork levels.",
            self.group_count_label,
            self.group_count_slider,
        )
        settings_layout.addWidget(self.group_count_label)
        settings_layout.addWidget(self.group_count_slider)

        _add_group_header(settings_layout, settings_panel, "Edit")
        edit_mode_label = QLabel("Pick mode", settings_panel)
        settings_layout.addWidget(edit_mode_label)
        self.edit_mode_combo = QComboBox(settings_panel)
        self.edit_mode_combo.addItem("Select subtree", EDIT_MODE_SUBTREE)
        self.edit_mode_combo.addItem("Select bones", EDIT_MODE_BONES)
        self.edit_mode_combo.currentIndexChanged.connect(lambda _index: self._on_edit_mode_changed())
        set_tooltip(
            "Manual pick mode. Subtree adds descendants; Bones edits only the clicked child joint.",
            edit_mode_label,
            self.edit_mode_combo,
        )
        self.edit_mode_combo.setFixedHeight(24)
        settings_layout.addWidget(self.edit_mode_combo)
        edit_actions_row = QWidget(settings_panel)
        edit_actions_layout = QHBoxLayout(edit_actions_row)
        edit_actions_layout.setContentsMargins(0, 0, 0, 0)
        edit_actions_layout.setSpacing(6)
        self.clear_group_button = QPushButton("Clear", edit_actions_row)
        self.clear_group_button.clicked.connect(self.clear_active_manual_group)
        self.clear_group_button.setFixedSize(54, 22)
        self.clear_group_button.setToolTip("Clears assignments from the active manual group. Undo is available.")
        edit_actions_layout.addWidget(self.clear_group_button, 0)
        edit_actions_layout.addStretch(1)
        settings_layout.addWidget(edit_actions_row)

        self.layers_pane = QFrame(self.global_host)
        self.layers_pane.setObjectName("LayersPane")
        layers_layout = QVBoxLayout(self.layers_pane)
        layers_layout.setContentsMargins(0, 0, 0, 3)
        layers_layout.setSpacing(5)
        layers_layout.addSpacing(5)
        layers_line = QFrame(self.layers_pane)
        layers_line.setFrameShape(QFrame.Shape.HLine)
        layers_line.setFrameShadow(QFrame.Shadow.Plain)
        layers_line.setStyleSheet("color: rgba(0, 0, 0, 85);")
        layers_layout.addWidget(layers_line)
        layers_layout.addSpacing(3)
        layers_header = QWidget(self.layers_pane)
        layers_header_layout = QHBoxLayout(layers_header)
        layers_header_layout.setContentsMargins(0, 0, 0, 0)
        layers_header_layout.setSpacing(5)
        layers_label = QLabel("Layers", layers_header)
        layers_label.setStyleSheet("font-weight: 700;")
        self.add_group_button = QPushButton("+", layers_header)
        self.add_group_button.setFixedSize(24, 21)
        self.add_group_button.clicked.connect(self.add_manual_group)
        self.add_group_button.setToolTip("Adds a new empty manual group at the top of the layer stack.")
        self.remove_group_button = QPushButton("-", layers_header)
        self.remove_group_button.setFixedSize(24, 21)
        self.remove_group_button.clicked.connect(self.delete_active_manual_group)
        self.remove_group_button.setToolTip("Deletes the active manual group after confirmation.")
        layers_header_layout.addWidget(layers_label, 0)
        layers_header_layout.addStretch(1)
        layers_header_layout.addWidget(self.add_group_button, 0)
        layers_header_layout.addWidget(self.remove_group_button, 0)
        layers_layout.addWidget(layers_header)
        self.scroll = QScrollArea(self.layers_pane)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setFixedHeight(LAYERS_SCROLL_DEFAULT_HEIGHT)
        self.scroll.viewport().setObjectName("ScrollViewport")
        self.group_host = QWidget(self.scroll)
        self.group_layout = QVBoxLayout(self.group_host)
        self.group_layout.setContentsMargins(0, 0, 0, 0)
        self.group_layout.setSpacing(5)
        self.group_layout.addStretch(1)
        self.scroll.setWidget(self.group_host)
        layers_layout.addWidget(self.scroll)
        self.layers_resize_handle = _LayerResizeHandle(self.layers_pane, self._resize_layers_scroll)
        layers_layout.addWidget(self.layers_resize_handle)
        settings_layout.addWidget(self.layers_pane)

        self.export_pane = QWidget(self.global_host)
        export_pane_layout = QVBoxLayout(self.export_pane)
        export_pane_layout.setContentsMargins(0, 0, 0, 0)
        export_pane_layout.setSpacing(5)
        _add_group_header(export_pane_layout, self.export_pane, "Generate JSON")
        output_label = QLabel("Output Path", self.export_pane)
        self.output_path_edit = QLineEdit(settings_panel)
        self.output_path_edit.setPlaceholderText("Select an output JSON path")
        self.output_path_edit.editingFinished.connect(self._save_wind_session)
        set_tooltip("Dynamic Wind JSON path. Defaults next to the source; Browse or type to override.", output_label, self.output_path_edit)
        export_pane_layout.addWidget(output_label)
        export_pane_layout.addWidget(self.output_path_edit)
        export_row = QWidget(self.export_pane)
        export_layout = QHBoxLayout(export_row)
        export_layout.setContentsMargins(0, 0, 0, 0)
        export_layout.setSpacing(6)
        self.browse_output_button = QPushButton("Browse", export_row)
        self.browse_output_button.clicked.connect(self.browse_output_path)
        self.browse_output_button.setFixedHeight(24)
        self.browse_output_button.setToolTip("Choose where to write the Dynamic Wind JSON file.")
        self.generate_json_button = QPushButton("Generate JSON", export_row)
        self.generate_json_button.clicked.connect(self.generate_json)
        self.generate_json_button.setFixedHeight(24)
        self.generate_json_button.setToolTip("Writes Dynamic Wind JSON from the final visible group stack.")
        export_layout.addWidget(self.browse_output_button, 0)
        export_layout.addWidget(self.generate_json_button, 1)
        export_pane_layout.addWidget(export_row)

        self.summary_label = QLabel("Preparing wind preview...", settings_panel)
        self.summary_label.setWordWrap(True)
        export_pane_layout.addWidget(self.summary_label)
        export_pane_layout.addStretch(1)
        settings_layout.addWidget(self.export_pane)
        settings_layout.addStretch(1)

        self.grouping_mode_combo.currentIndexChanged.connect(lambda _index: self._on_grouping_mode_changed())
        self.group_count_slider.valueChanged.connect(self._on_auto_group_count_changed)
        self._sync_grouping_controls()
        self._sync_source_controls()

        if preview is not None:
            self.set_preview(preview)

    def set_loading(self, message: str = "Preparing wind preview...") -> None:
        self.summary_label.setText(message)

    def set_error(self, message: str) -> None:
        self.summary_label.setText(message)

    def _resize_layers_scroll(self, delta_y: int) -> None:
        current_height = self.scroll.minimumHeight() or self.scroll.height()
        next_height = max(LAYERS_SCROLL_MIN_HEIGHT, min(LAYERS_SCROLL_MAX_HEIGHT, current_height + int(delta_y)))
        self.scroll.setFixedHeight(next_height)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Z and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.redo_manual_edit()
            else:
                self.undo_manual_edit()
            event.accept()
            return
        super().keyPressEvent(event)

    def set_preview(self, preview: WindPreviewResult) -> None:
        self.current_preview = preview
        self.total_bones_label.setText(f"Total bones: {len(preview.source_model.skeleton):,}")
        self._selection = WindViewportSelection()
        self._auto_group_count = max(1, min(AUTO_WIND_GROUP_MAX_COUNT, len(preview.groups) or 1))
        self._auto_continuous_levels = set()
        self._manual_groups = ()
        self._expanded_group_source_keys = set()
        self._group_settings_by_source_key = {}
        self._active_manual_layer_id = None
        self._undo_stack = []
        self._redo_stack = []
        self.output_path_edit.setText(str(derive_wind_json_output_path(preview.input_path, "")))
        source_index = self.source_mode_combo.findData(_source_mode_for_preview(preview))
        if source_index >= 0:
            with QSignalBlocker(self.source_mode_combo):
                self.source_mode_combo.setCurrentIndex(source_index)
        if _source_mode_for_preview(preview) == SOURCE_MODE_EXTERNAL:
            self.external_path_edit.setText(str(preview.input_path))
        self._sync_xml_group_mode_available(preview.xml_groups_available)
        preferred_index = self.grouping_mode_combo.findData(preview.preferred_grouping_mode)
        if preferred_index >= 0:
            with QSignalBlocker(self.grouping_mode_combo):
                self.grouping_mode_combo.setCurrentIndex(preferred_index)
        restore_notice = self._restore_wind_session_if_matching(preview)
        with QSignalBlocker(self.group_count_slider):
            self.group_count_slider.setValue(self._auto_group_count)
        self._sync_source_controls()
        self._sync_external_skeleton_warning()
        self._sync_external_diagnostics()
        self._sync_grouping_controls()
        self._rebuild_group_list()
        self._apply_scene(frame_camera=True)
        if restore_notice:
            self.summary_label.setText(f"{restore_notice}\n{self.summary_label.text()}")
        self._save_wind_session()

    def add_manual_group(self) -> None:
        self._push_undo()
        self._manual_groups = self._manual_groups + (make_manual_group(next_manual_layer_id(self._manual_groups)),)
        self._rebuild_group_list()
        self._sync_grouping_controls()
        self._save_wind_session()

    def clear_active_manual_group(self) -> None:
        group = self._active_manual_group()
        if group is None or not group.joint_tokens:
            return
        self._push_undo()
        self._replace_manual_group(WindManualGroup(group.layer_id, group.name, frozenset(), group.edit_mode))
        self._selection = WindViewportSelection()
        self._rebuild_group_list()
        self._apply_scene(frame_camera=False)
        self._save_wind_session()

    def delete_active_manual_group(self) -> None:
        group = self._active_manual_group()
        if group is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete Manual Group?",
            f"Delete {group.name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._push_undo()
        self._manual_groups = tuple(item for item in self._manual_groups if item.layer_id != group.layer_id)
        self._active_manual_layer_id = None
        self._selection = WindViewportSelection()
        self._rebuild_group_list()
        self._apply_scene(frame_camera=False)
        self._save_wind_session()

    def undo_manual_edit(self) -> None:
        if not self._undo_stack:
            return
        self._redo_stack.append((self._manual_groups, self._active_manual_layer_id))
        self._restore_manual_state(self._undo_stack.pop())
        self._save_wind_session()

    def redo_manual_edit(self) -> None:
        if not self._redo_stack:
            return
        self._undo_stack.append((self._manual_groups, self._active_manual_layer_id))
        self._restore_manual_state(self._redo_stack.pop())
        self._save_wind_session()

    def browse_external_path(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "Load External Skeleton",
            self.external_path_edit.text().strip(),
            "Skeleton files (*.fbx *.usd *.usda *.usdc);;FBX files (*.fbx);;USD files (*.usd *.usda *.usdc);;All files (*)",
        )
        if selected:
            self.external_path_edit.setText(selected)
            self._save_wind_session()
            self.load_external_skeleton()

    def load_external_skeleton(self) -> None:
        path = self.external_path_edit.text().strip()
        available, reason = external_skeleton_backend_available(Path(path).suffix)
        if not available:
            self.summary_label.setText(reason)
            return
        if Path(path).suffix.lower() in {".usd", ".usda", ".usdc"}:
            skeleton_index = self._selected_external_skeleton_index(path)
            if skeleton_index is None:
                choices_request = ExternalSkeletonChoicesRequest(path)
                if self._external_preview_requested is not None:
                    self.set_loading("Inspecting USD skeletons...")
                    self._external_preview_requested(choices_request)
                    return
                try:
                    request = self.set_external_skeleton_choices(list_external_usd_skeletons(path))
                except Exception as exc:
                    self.summary_label.setText(str(exc))
                    return
                if request is None:
                    return
                skeleton_index = request.skeleton_index
        else:
            skeleton_index = None
        try:
            request = ExternalSkeletonPreviewRequest(path, group_count=self._auto_group_count, skeleton_index=skeleton_index)
            if self._external_preview_requested is not None:
                self.set_loading("Loading external skeleton...")
                self._external_preview_requested(request)
                return
            preview = load_external_skeleton_preview(request)
        except Exception as exc:
            self.summary_label.setText(str(exc))
            return
        auto_index = self.grouping_mode_combo.findData(GROUPING_MODE_AUTO)
        if auto_index >= 0:
            self.grouping_mode_combo.setCurrentIndex(auto_index)
        self.set_preview(preview)
        self.summary_label.setText(f"External skeleton loaded\n{len(preview.source_model.skeleton)} joints")

    def set_external_skeleton_choices(self, result):
        path = result.input_path
        choices = tuple(result.choices)
        self._external_skeleton_choices_path = _external_path_key(path)
        self._external_skeleton_choice_count = len(choices)
        with QSignalBlocker(self.external_skeleton_combo):
            self.external_skeleton_combo.clear()
            if len(choices) > 1:
                self.external_skeleton_combo.addItem("Choose Skeleton prim...", None)
            for choice in choices:
                self.external_skeleton_combo.addItem(
                    f"{choice.name}  ({choice.joint_count} joints)",
                    choice.index,
                )
        self._sync_source_controls()
        if not choices:
            self.summary_label.setText("No skeleton found in USD file.")
            return None
        if len(choices) == 1:
            return ExternalSkeletonPreviewRequest(path, group_count=self._auto_group_count, skeleton_index=choices[0].index)
        self.summary_label.setText("Choose a Skeleton prim to load it.")
        self._save_wind_session()
        return None

    def browse_output_path(self) -> None:
        current = self.output_path_edit.text().strip()
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            "Save Dynamic Wind JSON",
            current,
            "JSON files (*.json);;All files (*)",
        )
        if selected:
            self.output_path_edit.setText(selected)
            self._save_wind_session()

    def generate_json(self) -> None:
        preview = self.current_preview
        if preview is None:
            self.summary_label.setText("Load a Wind Preview source before generating JSON.")
            return
        output_path = Path(self.output_path_edit.text().strip() or derive_wind_json_output_path(preview.input_path, ""))
        if output_path.exists():
            answer = QMessageBox.question(
                self,
                "Overwrite Dynamic Wind JSON?",
                f"Overwrite existing file?\n{output_path}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        written = write_dynamic_wind_json(self._current_dynamic_wind(), output_path)
        self.output_path_edit.setText(str(written))
        self.summary_label.setText(f"Wrote Dynamic Wind JSON\n{written}")
        self._save_wind_session()

    def select_group(self, group_index: int) -> None:
        self._active_manual_layer_id = None
        selection = WindViewportSelection(group_index=group_index)
        if self._selection == selection:
            self._sync_group_buttons()
            return
        self._selection = selection
        self._apply_selection()
        self._save_wind_session()

    def toggle_manual_group_edit(self, layer_id: int, final_group_index: int | None = None) -> None:
        active = self._active_manual_layer_id != layer_id
        self._active_manual_layer_id = layer_id if active else None
        self._selection = (
            WindViewportSelection(group_index=final_group_index)
            if active and final_group_index is not None
            else WindViewportSelection()
        )
        self._sync_grouping_controls()
        self._apply_selection()
        self._save_wind_session()

    def _select_subtree_from_pick_token(self, pick_token: str) -> None:
        selection = WindViewportSelection(subtree_root_token=subtree_root_from_pick_token(pick_token))
        if self._selection == selection:
            self._sync_group_buttons()
            return
        self._selection = selection
        self._apply_selection()
        self._save_wind_session()

    def _edit_group_from_pick_token(self, pick_token: str, modifiers) -> None:
        preview = self.current_preview
        if preview is None or self._active_manual_layer_id is None:
            return
        group = self._active_manual_group()
        if group is None:
            return
        root_token = subtree_root_from_pick_token(pick_token)
        tokens = (
            subtree_joint_tokens(preview.source_model.skeleton, root_token)
            if group.edit_mode == EDIT_MODE_SUBTREE
            else frozenset({root_token})
        )
        self._push_undo()
        edited = (
            remove_tokens_from_manual_group(group, tokens)
            if modifiers & Qt.KeyboardModifier.AltModifier
            else add_tokens_to_manual_group(group, tokens)
        )
        self._replace_manual_group(edited)
        final_index = self._manual_group_final_index(edited.layer_id)
        self._selection = WindViewportSelection(group_index=final_index) if final_index is not None else WindViewportSelection()
        self._rebuild_group_list()
        self._apply_scene(frame_camera=False)
        self._save_wind_session()

    def _apply_scene(self, *, frame_camera: bool) -> None:
        preview = self.current_preview
        if preview is None:
            return
        dynamic_wind = self._current_dynamic_wind()
        groups = self._current_groups()
        if dynamic_wind == preview.dynamic_wind and self._selection == WindViewportSelection():
            scene = preview.viewport_scene
        else:
            scene = recolor_wind_viewport_scene(
                preview.viewport_scene,
                preview.source_model,
                dynamic_wind,
                selection=self._selection,
            )
        if _source_mode_for_preview(preview) == SOURCE_MODE_EXTERNAL:
            scene = transform_external_skeleton_scene(
                scene,
                source_unit=self._display_source_unit,
                preview_unit=self._display_preview_unit,
                source_up_axis=self._display_source_up_axis,
                preview_up_axis=self._display_preview_up_axis,
            )
        self._active_scene = scene
        self.viewport.set_scene(scene, frame_camera=frame_camera, precompute_static=True)
        self.viewport.set_show_bones(True)
        self._update_summary(scene, groups)

    def _apply_selection(self) -> None:
        preview = self.current_preview
        if preview is None:
            return
        if self._active_scene is None:
            self._apply_scene(frame_camera=False)
            return
        dynamic_wind = self._current_dynamic_wind()
        groups = self._current_groups()
        bone_segments = build_wind_viewport_bone_segments(
            preview.source_model,
            dynamic_wind,
            selection=self._selection,
        )
        if _source_mode_for_preview(preview) == SOURCE_MODE_EXTERNAL:
            bone_segments = transform_external_skeleton_scene(
                replace(preview.viewport_scene, bone_segments=bone_segments),
                source_unit=self._display_source_unit,
                preview_unit=self._display_preview_unit,
                source_up_axis=self._display_source_up_axis,
                preview_up_axis=self._display_preview_up_axis,
            ).bone_segments
        self.viewport.set_bone_segments(bone_segments)
        self._update_summary(self._active_scene, groups)

    def _update_summary(self, scene, groups: tuple[WindViewportGroup, ...]) -> None:
        self._sync_group_buttons()
        selected = ""
        if self._active_manual_layer_id is not None:
            selected = f"\nEditing manual group: {self._active_manual_layer_id}"
        elif self._selection.group_index is not None:
            selected = f"\nSelected group: {self._selection.group_index}"
        elif self._selection.subtree_root_token:
            selected = f"\nSelected subtree: {self._selection.subtree_root_token}"
        mode_label = "Auto hierarchy" if self._grouping_mode() == GROUPING_MODE_AUTO else "XML generator"
        self.summary_label.setText(
            (
                f"{len(groups)} groups ({mode_label})\n"
                f"{scene.stats.logical_triangles} logical triangles"
                f"{selected}"
            )
        )

    def _rebuild_group_list(self) -> None:
        while self.group_layout.count():
            item = self.group_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._group_buttons = {}
        self._group_cards = {}
        self._manual_group_cards = {}
        preview = self.current_preview
        if preview is None:
            self.group_layout.addStretch(1)
            return
        flatten_result = self._flattened()
        visible_manual_ids = {
            group.source_layer_id
            for group in flatten_result.groups
            if group.source_layer_id is not None
        }
        for group in reversed(self._manual_groups):
            if group.layer_id not in visible_manual_ids:
                self._add_manual_group_row(group, final_group_index=None, visible_count=0)
        for group in reversed(flatten_result.groups):
            self._add_final_group_row(group)
        self.group_layout.addStretch(1)

    def _add_final_group_row(self, group) -> None:
        card = QFrame(self.group_host)
        card.setObjectName("LayerCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(6, 4, 6, 5)
        card_layout.setSpacing(3)
        row = QWidget(card)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(5)
        chip = QLabel(card)
        chip.setFixedSize(12, 12)
        chip.setStyleSheet(f"background: {_css_color(self._group_color(group.final_group_index))}; border: 1px solid rgba(0, 0, 0, 70);")
        label = _flattened_group_button_text(group.name, group.final_group_index, len(group.joint_tokens))
        if group.source_layer_id is None:
            group_control = QLabel(label, card)
            group_control.setObjectName("LayerLabel")
            group_control.setFixedHeight(22)
            group_control.setStyleSheet(_layer_label_stylesheet())
            group_control.setToolTip(f"{group.name}. XML group; assignments are read-only here.")
        else:
            group_control = QPushButton(label, card)
            group_control.setObjectName("LayerButton")
            group_control.setCheckable(True)
            group_control.setFixedHeight(22)
            group_control.setStyleSheet(_layer_button_stylesheet())
            group_control.clicked.connect(
                lambda _checked=False, layer=group.source_layer_id, index=group.final_group_index: self.toggle_manual_group_edit(layer, index)
            )
            group_control.setToolTip("Manual group. Click to enter Edit; click again to stop editing.")
            self._group_buttons[group.final_group_index] = group_control
            self._group_cards[group.final_group_index] = card
        disclosure = QToolButton(card)
        disclosure.setText("▾" if group.source_key in self._expanded_group_source_keys else "▸")
        disclosure.setFixedSize(22, 22)
        disclosure.setToolTip("Show or hide wind settings for this group.")
        disclosure.clicked.connect(lambda _checked=False, source_key=group.source_key: self._toggle_group_settings(source_key))
        row_layout.addWidget(chip, 0)
        row_layout.addWidget(group_control, 1)
        row_layout.addWidget(disclosure, 0)
        card_layout.addWidget(row)
        if group.source_key in self._expanded_group_source_keys:
            card_layout.addWidget(self._make_group_settings_editor(group, card))
        if self._is_auto_mode() and group.source_group_index is not None:
            options_row = QWidget(card)
            options_layout = QHBoxLayout(options_row)
            options_layout.setContentsMargins(17, 0, 0, 0)
            options_layout.setSpacing(0)
            continuous_box = QCheckBox("Continue line", card)
            continuous_box.setChecked(group.final_group_index in self._auto_continuous_levels)
            continuous_box.setToolTip(
                "Continue this layer through endpoint-connected child chains. "
                "Off uses strict SpeedTree skeleton order."
            )
            continuous_box.toggled.connect(
                lambda checked=False, level=group.final_group_index: self._on_auto_continuation_toggled(level, checked)
            )
            options_layout.addWidget(continuous_box, 0)
            options_layout.addStretch(1)
            card_layout.addWidget(options_row)
        self.group_layout.addWidget(card)

    def _add_manual_group_row(self, group: WindManualGroup, *, final_group_index: int | None, visible_count: int) -> None:
        card = QFrame(self.group_host)
        card.setObjectName("LayerCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(6, 4, 6, 5)
        card_layout.setSpacing(3)
        row = QWidget(card)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(5)
        chip = QLabel(card)
        chip.setFixedSize(12, 12)
        chip.setStyleSheet(f"background: {_css_color(Color4(0.55, 0.57, 0.34, 1.0))}; border: 1px solid rgba(0, 0, 0, 70);")
        button = QPushButton(_flattened_group_button_text(group.name, final_group_index, visible_count), card)
        button.setObjectName("LayerButton")
        button.setCheckable(True)
        button.setFixedHeight(22)
        button.setStyleSheet(_layer_button_stylesheet())
        button.clicked.connect(lambda _checked=False, layer=group.layer_id, index=final_group_index: self.toggle_manual_group_edit(layer, index))
        button.setToolTip("Manual group. Click to enter Edit; click again to stop editing.")
        row_layout.addWidget(chip, 0)
        row_layout.addWidget(button, 1)
        card_layout.addWidget(row)
        self.group_layout.addWidget(card)
        self._manual_group_cards[group.layer_id] = card
        if final_group_index is not None:
            self._group_buttons[final_group_index] = button
            self._group_cards[final_group_index] = card

    def _sync_group_buttons(self) -> None:
        for group_index, button in self._group_buttons.items():
            button.setChecked(self._selection.group_index == group_index)
            card = self._group_cards.get(group_index)
            if card is not None:
                card.setStyleSheet(_layer_card_stylesheet(self._selection.group_index == group_index))
        for layer_id, card in self._manual_group_cards.items():
            card.setStyleSheet(_layer_card_stylesheet(self._active_manual_layer_id == layer_id))
        self.edit_mode_combo.setEnabled(self._active_manual_layer_id is not None)
        self.clear_group_button.setEnabled(self._active_manual_group() is not None)
        self.remove_group_button.setEnabled(self._active_manual_group() is not None)
        active_group = self._active_manual_group()
        if active_group is not None:
            index = self.edit_mode_combo.findData(active_group.edit_mode)
            if index >= 0 and index != self.edit_mode_combo.currentIndex():
                with QSignalBlocker(self.edit_mode_combo):
                    self.edit_mode_combo.setCurrentIndex(index)

    def _grouping_mode(self) -> str:
        return str(self.grouping_mode_combo.currentData() or GROUPING_MODE_XML)

    def _is_auto_mode(self) -> bool:
        return self._grouping_mode() == GROUPING_MODE_AUTO

    def _current_dynamic_wind(self) -> DynamicWindData:
        flattened = self._flattened()
        groups = tuple(
            self._group_settings_for_flattened_group(group, fallback)
            for group, fallback in zip(flattened.groups, flattened.dynamic_wind.simulation_groups)
        )
        return replace(flattened.dynamic_wind, simulation_groups=groups)

    def _group_settings_for_flattened_group(
        self,
        group,
        fallback: DynamicWindSimulationGroup,
    ) -> DynamicWindSimulationGroup:
        if group.source_group_index is not None:
            source_group = next(
                (
                    item
                    for item in self._base_dynamic_wind().simulation_groups
                    if item.group_index == group.source_group_index
                ),
                fallback,
            )
            fallback = replace(
                source_group,
                group_index=fallback.group_index,
                branch_order=fallback.branch_order,
            )
        values = self._group_settings_by_source_key.get(group.source_key, {})
        return replace(fallback, **values)

    def _group_settings_for_editor(self, group) -> DynamicWindSimulationGroup:
        flattened = self._flattened()
        return self._group_settings_for_flattened_group(
            group,
            flattened.dynamic_wind.simulation_groups[group.final_group_index],
        )

    def _toggle_group_settings(self, source_key: str) -> None:
        if source_key in self._expanded_group_source_keys:
            self._expanded_group_source_keys.remove(source_key)
        else:
            self._expanded_group_source_keys.add(source_key)
        self._rebuild_group_list()
        self._save_wind_session()

    def _make_group_settings_editor(self, group, parent: QWidget) -> QFrame:
        settings = self._group_settings_for_editor(group)
        frame = QFrame(parent)
        frame.setObjectName("WindGroupSettings")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(17, 2, 2, 2)
        layout.setSpacing(4)
        options = QHBoxLayout()
        trunk_checkbox = QCheckBox("Trunk", frame)
        trunk_checkbox.setChecked(settings.is_trunk_group)
        set_tooltip("Treats this group as primary trunk wind.", trunk_checkbox)
        dual_checkbox = QCheckBox("Dual Influence", frame)
        dual_checkbox.setChecked(settings.use_dual_influence)
        set_tooltip("Uses a base-to-top influence range instead of one strength.", dual_checkbox)
        options.addWidget(trunk_checkbox, 0)
        options.addWidget(dual_checkbox, 0)
        options.addStretch(1)
        layout.addLayout(options)

        single_frame = QFrame(frame)
        single_layout = QFormLayout(single_frame)
        single_layout.setContentsMargins(0, 0, 0, 0)
        influence_spin = SliderSpinEditor(minimum=0.0, maximum=1.0, step=0.05, value=settings.influence, parent=single_frame)
        influence_label = QLabel("Influence", single_frame)
        set_tooltip("Wind strength for this group.", influence_label, influence_spin)
        single_layout.addRow(influence_label, influence_spin)
        layout.addWidget(single_frame)

        dual_frame = QFrame(frame)
        dual_layout = QFormLayout(dual_frame)
        dual_layout.setContentsMargins(0, 0, 0, 0)
        min_spin = SliderSpinEditor(minimum=0.0, maximum=1.0, step=0.01, value=settings.min_influence, parent=dual_frame)
        max_spin = SliderSpinEditor(minimum=0.0, maximum=1.0, step=0.01, value=settings.max_influence, parent=dual_frame)
        shift_spin = SliderSpinEditor(minimum=0.0, maximum=1.0, step=0.01, value=settings.shift_top, parent=dual_frame)
        for text, editor, tooltip in (
            ("Min Influence", min_spin, "Lower-end wind strength."),
            ("Max Influence", max_spin, "Upper-end wind strength."),
            ("Shift Top", shift_spin, "Moves the high-influence zone toward the tip."),
        ):
            label = QLabel(text, dual_frame)
            set_tooltip(tooltip, label, editor)
            dual_layout.addRow(label, editor)
        layout.addWidget(dual_frame)

        trunk_checkbox.toggled.connect(lambda checked, current=group: self._set_group_setting(current.source_key, "is_trunk_group", checked))
        dual_checkbox.toggled.connect(lambda checked, current=group: self._set_group_setting(current.source_key, "use_dual_influence", checked))
        for field, editor in (
            ("influence", influence_spin),
            ("min_influence", min_spin),
            ("max_influence", max_spin),
            ("shift_top", shift_spin),
        ):
            editor.valueChanged.connect(
                lambda value, source_key=group.source_key, name=field: self._set_group_setting(source_key, name, value)
            )
        single_frame.setVisible(not settings.use_dual_influence)
        dual_frame.setVisible(settings.use_dual_influence)
        dual_checkbox.toggled.connect(lambda checked: single_frame.setVisible(not checked))
        dual_checkbox.toggled.connect(dual_frame.setVisible)
        return frame

    def _set_group_setting(self, source_key: str, field: str, value: bool | float) -> None:
        if field in _WIND_GROUP_BOOLEAN_FIELDS:
            normalized: bool | float = bool(value)
        elif field in _WIND_GROUP_NUMERIC_FIELDS:
            normalized = max(0.0, min(float(value), 1.0))
        else:
            return
        self._group_settings_by_source_key.setdefault(source_key, {})[field] = normalized
        self._save_wind_session()

    def _base_dynamic_wind(self) -> DynamicWindData:
        preview = self.current_preview
        if preview is None:
            raise RuntimeError("wind preview is not loaded")
        if self._is_auto_mode():
            return build_auto_wind_viewport_data(
                preview.source_model.skeleton,
                self._auto_group_count,
                continuous_branch_orders=frozenset(self._auto_continuous_levels),
            )
        return preview.dynamic_wind

    def _flattened(self) -> WindFlattenResult:
        preview = self.current_preview
        if preview is None:
            return flatten_wind_group_stack(DynamicWindData(joint_assignments=(), simulation_groups=()), ())
        return flatten_wind_group_stack(
            self._base_dynamic_wind(),
            self._manual_groups,
            all_joint_tokens=tuple(joint.name for joint in preview.source_model.skeleton),
        )

    def _current_groups(self) -> tuple[WindViewportGroup, ...]:
        if self.current_preview is None:
            return ()
        return build_wind_viewport_groups(self._current_dynamic_wind(), label_kind="Final layer")

    def _on_grouping_mode_changed(self) -> None:
        if self.current_preview is not None and not self.current_preview.xml_groups_available and self._grouping_mode() == GROUPING_MODE_XML:
            auto_index = self.grouping_mode_combo.findData(GROUPING_MODE_AUTO)
            if auto_index >= 0:
                self.grouping_mode_combo.setCurrentIndex(auto_index)
            return
        self._selection = WindViewportSelection()
        self._sync_grouping_controls()
        self._rebuild_group_list()
        self._apply_scene(frame_camera=False)
        self._save_wind_session()

    def _on_auto_group_count_changed(self, value: int) -> None:
        self._auto_group_count = int(value)
        self._sync_grouping_controls()
        if not self._is_auto_mode():
            self._save_wind_session()
            return
        self._selection = WindViewportSelection()
        self._rebuild_group_list()
        self._apply_scene(frame_camera=False)
        self._save_wind_session()

    def _on_auto_continuation_toggled(self, level: int, checked: bool) -> None:
        if checked:
            self._auto_continuous_levels.add(level)
        else:
            self._auto_continuous_levels.discard(level)
        self._selection = WindViewportSelection()
        self._sync_grouping_controls()
        self._rebuild_group_list()
        self._apply_scene(frame_camera=False)
        self._save_wind_session()

    def _on_edit_mode_changed(self) -> None:
        group = self._active_manual_group()
        if group is None:
            return
        mode = str(self.edit_mode_combo.currentData() or EDIT_MODE_SUBTREE)
        if mode == group.edit_mode:
            return
        self._push_undo()
        self._replace_manual_group(WindManualGroup(group.layer_id, group.name, group.joint_tokens, mode))
        self._sync_group_buttons()
        self._update_shortcut_hints()
        self._save_wind_session()

    def _sync_grouping_controls(self) -> None:
        auto_enabled = self._is_auto_mode()
        self.group_count_slider.setEnabled(auto_enabled)
        self.group_count_label.setEnabled(auto_enabled)
        display_count = len(self._current_groups()) if auto_enabled and self.current_preview is not None else self._auto_group_count
        self.group_count_label.setText(f"Groups: {display_count}")
        self._sync_group_buttons()
        self._update_shortcut_hints()

    def _sync_source_controls(self) -> None:
        external = self.source_mode_combo.currentData() == SOURCE_MODE_EXTERNAL
        for widget in self._external_controls:
            widget.setVisible(external)
        self.external_skeleton_combo.setVisible(external and self._external_skeleton_choice_count > 1)
        preview = self.current_preview
        is_fbx = preview is not None and Path(preview.input_path).suffix.lower() == ".fbx"
        self.external_diagnostics_frame.setVisible(external and is_fbx)

    def _on_source_mode_changed(self) -> None:
        self._sync_source_controls()
        self._sync_external_skeleton_warning()
        self._sync_external_diagnostics()
        self._save_wind_session()

    def _on_external_display_transform_changed(self) -> None:
        self._display_source_unit = str(self.source_units_combo.currentData() or "m")
        self._display_preview_unit = str(self.preview_units_combo.currentData() or "m")
        self._display_source_up_axis = str(self.source_up_axis_combo.currentData() or "Y")
        self._display_preview_up_axis = str(self.preview_up_axis_combo.currentData() or "Y")
        self._sync_external_skeleton_warning()
        preview = self.current_preview
        if preview is not None and _source_mode_for_preview(preview) == SOURCE_MODE_EXTERNAL:
            self._apply_scene(frame_camera=False)
        self._save_wind_session()

    def _sync_external_skeleton_warning(self) -> None:
        preview = self.current_preview
        if preview is None or _source_mode_for_preview(preview) != SOURCE_MODE_EXTERNAL:
            self.external_vertical_warning_label.clear()
            self.external_vertical_warning_label.setToolTip("")
            self.external_vertical_warning_label.hide()
            return
        vertical_bones = external_vertical_bone_names(
            preview.source_model.skeleton,
            self._display_source_up_axis,
        )
        if not vertical_bones:
            self.external_vertical_warning_label.clear()
            self.external_vertical_warning_label.setToolTip("")
            self.external_vertical_warning_label.hide()
            return
        self.external_vertical_warning_label.setText(
            f"⚠ {len(vertical_bones)} vertical bone(s) detected. External skeleton is unchanged."
        )
        self.external_vertical_warning_label.setToolTip(", ".join(vertical_bones))
        self.external_vertical_warning_label.show()

    def _sync_external_diagnostics(self) -> None:
        preview = self.current_preview
        if preview is None or Path(preview.input_path).suffix.lower() != ".fbx":
            self.external_diagnostics_label.setText("Load an FBX rig to inspect it.")
            self.external_diagnostics_label.setToolTip("")
            return
        errors = sum(issue.severity == "error" for issue in preview.diagnostics)
        warnings = sum(issue.severity == "warning" for issue in preview.diagnostics)
        header = f"{errors} error(s) · {warnings} warning(s)"
        lines = [header]
        for issue in preview.diagnostics:
            prefix = "Error" if issue.severity == "error" else "Warning" if issue.severity == "warning" else "Info"
            lines.append(f"{prefix}: {issue.message}")
        self.external_diagnostics_label.setText("\n".join(lines))
        self.external_diagnostics_label.setToolTip(
            "\n".join(f"{issue.code}: {issue.message}" for issue in preview.diagnostics)
        )

    def _on_external_skeleton_changed(self) -> None:
        self._save_wind_session()
        if self.external_skeleton_combo.currentData() is not None:
            self.load_external_skeleton()

    def _clear_external_skeleton_choices(self) -> None:
        self._external_skeleton_choices_path = ""
        self._external_skeleton_choice_count = 0
        with QSignalBlocker(self.external_skeleton_combo):
            self.external_skeleton_combo.clear()
        self._sync_source_controls()

    def _selected_external_skeleton_index(self, path: str) -> int | None:
        if self._external_skeleton_choices_path != _external_path_key(path) or self._external_skeleton_choice_count <= 0:
            return None
        data = self.external_skeleton_combo.currentData()
        return int(data) if data is not None else None

    def _sync_xml_group_mode_available(self, available: bool) -> None:
        xml_index = self.grouping_mode_combo.findData(GROUPING_MODE_XML)
        if xml_index < 0:
            return
        model = self.grouping_mode_combo.model()
        item = model.item(xml_index) if hasattr(model, "item") else None
        if item is not None:
            item.setEnabled(available)

    def _active_manual_group(self) -> WindManualGroup | None:
        for group in self._manual_groups:
            if group.layer_id == self._active_manual_layer_id:
                return group
        return None

    def _replace_manual_group(self, edited: WindManualGroup) -> None:
        self._manual_groups = tuple(
            edited if group.layer_id == edited.layer_id else group
            for group in self._manual_groups
        )

    def _push_undo(self) -> None:
        self._undo_stack.append((self._manual_groups, self._active_manual_layer_id))
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _restore_manual_state(self, state: tuple[tuple[WindManualGroup, ...], int | None]) -> None:
        self._manual_groups, self._active_manual_layer_id = state
        final_index = self._manual_group_final_index(self._active_manual_layer_id) if self._active_manual_layer_id is not None else None
        self._selection = WindViewportSelection(group_index=final_index) if final_index is not None else WindViewportSelection()
        self._rebuild_group_list()
        self._apply_scene(frame_camera=False)

    def _manual_group_final_index(self, layer_id: int) -> int | None:
        for group in self._flattened().groups:
            if group.source_layer_id == layer_id:
                return group.final_group_index
        return None

    def _group_color(self, group_index: int) -> Color4:
        for group in build_wind_viewport_groups(self._current_dynamic_wind(), label_kind="Final layer"):
            if group.group_index == group_index:
                return group.color
        return Color4(0.55, 0.57, 0.34, 1.0)

    def _update_shortcut_hints(self) -> None:
        active = self._active_manual_group()
        history = []
        if self._undo_stack:
            history.append("Ctrl+Z undo")
        if self._redo_stack:
            history.append("Ctrl+Shift+Z redo")
        if active is None:
            self.viewport.set_shortcut_hints(("LMB orbit", "Wheel zoom", *history))
            return
        pick_label = "LMB add subtree" if active.edit_mode == EDIT_MODE_SUBTREE else "LMB add bone"
        remove_label = "Alt+LMB remove subtree" if active.edit_mode == EDIT_MODE_SUBTREE else "Alt+LMB remove bone"
        self.viewport.set_shortcut_hints((pick_label, remove_label, "Wheel zoom", *history))

    def wind_session_snapshot(self) -> dict[str, object]:
        preview = self.current_preview
        if preview is None:
            return {}
        return {
            "schema_version": 3,
            "fingerprint": _json_fingerprint(preview),
            "input_path": str(preview.input_path),
            "source_mode": self.source_mode_combo.currentData() or SOURCE_MODE_XML,
            "external_path": self.external_path_edit.text().strip(),
            "display_source_unit": self._display_source_unit,
            "display_preview_unit": self._display_preview_unit,
            "display_source_up_axis": self._display_source_up_axis,
            "display_preview_up_axis": self._display_preview_up_axis,
            "output_path": self.output_path_edit.text().strip(),
            "grouping_mode": self._grouping_mode(),
            "auto_group_count": int(self._auto_group_count),
            "auto_continuous_levels": sorted(int(level) for level in self._auto_continuous_levels),
            "expanded_group_source_keys": sorted(self._expanded_group_source_keys),
            "group_settings": {
                source_key: dict(sorted(settings.items()))
                for source_key, settings in sorted(self._group_settings_by_source_key.items())
            },
            "active_manual_layer_id": self._active_manual_layer_id,
            "manual_groups": [
                {
                    "layer_id": group.layer_id,
                    "name": group.name,
                    "edit_mode": group.edit_mode,
                    "joint_tokens": sorted(group.joint_tokens),
                }
                for group in self._manual_groups
            ],
        }

    def _save_wind_session(self) -> None:
        if self._restoring_session or self.current_preview is None:
            return
        snapshot = self.wind_session_snapshot()
        self._initial_wind_session_snapshot = snapshot
        if self._wind_session_changed is not None:
            self._wind_session_changed(snapshot)

    def _restore_wind_session_if_matching(self, preview: WindPreviewResult) -> str:
        session = self._initial_wind_session_snapshot
        if not session:
            return ""
        session_version = session.get("schema_version")
        if session_version not in {1, 2, 3}:
            return "Previous Wind Preview session reset: unsupported session version."
        if session.get("fingerprint") != _json_fingerprint(preview):
            return "Previous Wind Preview session reset: skeleton changed."

        valid_tokens = {joint.name for joint in preview.source_model.skeleton}
        self._restoring_session = True
        try:
            same_source = str(session.get("input_path", "")) == str(preview.input_path)
            if same_source:
                source_mode = str(session.get("source_mode", SOURCE_MODE_XML))
                source_index = self.source_mode_combo.findData(source_mode)
                if source_index >= 0:
                    with QSignalBlocker(self.source_mode_combo):
                        self.source_mode_combo.setCurrentIndex(source_index)
                external_path = session.get("external_path")
                if isinstance(external_path, str):
                    self.external_path_edit.setText(external_path)
            display_values = session if session_version >= 2 else {}
            self._display_source_unit = _restore_display_value(
                self.source_units_combo,
                display_values.get("display_source_unit"),
                "m",
            )
            self._display_preview_unit = _restore_display_value(
                self.preview_units_combo,
                display_values.get("display_preview_unit"),
                "m",
            )
            self._display_source_up_axis = _restore_display_value(
                self.source_up_axis_combo,
                display_values.get("display_source_up_axis"),
                "Y",
            )
            self._display_preview_up_axis = _restore_display_value(
                self.preview_up_axis_combo,
                display_values.get("display_preview_up_axis"),
                "Y",
            )
            output_path = session.get("output_path")
            if isinstance(output_path, str) and output_path:
                self.output_path_edit.setText(output_path)

            grouping_mode = str(session.get("grouping_mode", preview.preferred_grouping_mode))
            if grouping_mode == GROUPING_MODE_XML and not preview.xml_groups_available:
                grouping_mode = GROUPING_MODE_AUTO
            grouping_index = self.grouping_mode_combo.findData(grouping_mode)
            if grouping_index >= 0:
                with QSignalBlocker(self.grouping_mode_combo):
                    self.grouping_mode_combo.setCurrentIndex(grouping_index)

            self._auto_group_count = _coerce_group_count(session.get("auto_group_count"), self._auto_group_count)
            self._auto_continuous_levels = _restore_continuous_levels(session.get("auto_continuous_levels"))
            self._expanded_group_source_keys = _restore_expanded_group_source_keys(
                session.get("expanded_group_source_keys") if session_version >= 3 else None
            )
            self._group_settings_by_source_key = _restore_group_settings(
                session.get("group_settings") if session_version >= 3 else None
            )
            self._manual_groups = _restore_manual_groups(session.get("manual_groups"), valid_tokens)
            active_layer = _coerce_optional_int(session.get("active_manual_layer_id"))
            self._active_manual_layer_id = (
                active_layer
                if any(group.layer_id == active_layer for group in self._manual_groups)
                else None
            )
        finally:
            self._restoring_session = False
            self._sync_source_controls()
            self._sync_external_skeleton_warning()
        return ""


def _css_color(color: Color4) -> str:
    return (
        "rgb("
        f"{max(0, min(255, int(round(color.r * 255))))}, "
        f"{max(0, min(255, int(round(color.g * 255))))}, "
        f"{max(0, min(255, int(round(color.b * 255))))}"
        ")"
    )


def _flattened_group_button_text(name: str, final_group_index: int | None, count: int) -> str:
    prefix = "Empty" if final_group_index is None else f"G{final_group_index}"
    return f"{prefix} | {name} | {count} {'bone' if count == 1 else 'bones'}"


def _layer_button_stylesheet() -> str:
    return (
        "QPushButton#LayerButton { text-align: left; padding: 1px 5px; border-radius: 4px; font-size: 12px; "
        "background: rgba(148, 157, 77, 185); color: #111111; }"
        "QPushButton#LayerButton:hover { background: rgba(166, 175, 91, 220); }"
        "QPushButton#LayerButton:checked { font-weight: 700; background: rgba(228, 197, 75, 165); }"
    )


def _layer_label_stylesheet() -> str:
    return (
        "QLabel#LayerLabel { padding: 1px 5px; border-radius: 4px; font-size: 12px; "
        "background: rgba(148, 157, 77, 185); color: #111111; }"
    )


def _layer_card_stylesheet(active: bool) -> str:
    if active:
        return (
            "QFrame#LayerCard { background: rgba(228, 214, 112, 120); "
            "border: 1px solid rgba(118, 102, 22, 105); border-radius: 5px; }"
        )
    return (
        "QFrame#LayerCard { background: rgba(255, 255, 255, 38); "
        "border: 1px solid rgba(0, 0, 0, 28); border-radius: 5px; }"
        "QFrame#LayerCard:hover { background: rgba(255, 255, 255, 64); }"
    )


class _LayerResizeHandle(QFrame):
    def __init__(self, parent, resize_callback) -> None:
        super().__init__(parent)
        self._resize_callback = resize_callback
        self._drag_y: int | None = None
        self.setObjectName("LayerResizeHandle")
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setToolTip("Drag to give Layers more or less height.")

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._drag_y = int(event.globalPosition().y())
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_y is None:
            super().mouseMoveEvent(event)
            return
        y = int(event.globalPosition().y())
        self._resize_callback(y - self._drag_y)
        self._drag_y = y
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self._drag_y = None
        event.accept()


def _json_fingerprint(preview: WindPreviewResult) -> list[list[str | None]]:
    return [[name, parent] for name, parent in skeleton_fingerprint(preview.source_model.skeleton)]


def _source_mode_for_preview(preview: WindPreviewResult) -> str:
    suffix = Path(preview.input_path).suffix.casefold()
    return SOURCE_MODE_EXTERNAL if suffix in {".fbx", ".usd", ".usda", ".usdc"} else SOURCE_MODE_XML


def _external_path_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path.strip()))


def _display_combo(items, parent: QWidget) -> QComboBox:
    combo = QComboBox(parent)
    combo.setFixedHeight(24)
    for label, value in items:
        combo.addItem(label, value)
    return combo


def _set_combo_data(combo: QComboBox, value: str) -> bool:
    index = combo.findData(value)
    if index < 0:
        return False
    with QSignalBlocker(combo):
        combo.setCurrentIndex(index)
    return True


def _restore_display_value(combo: QComboBox, value, default: str) -> str:
    candidate = str(value) if isinstance(value, str) else default
    if not _set_combo_data(combo, candidate):
        _set_combo_data(combo, default)
        candidate = default
    return candidate


def _coerce_optional_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_group_count(value, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(AUTO_WIND_GROUP_MAX_COUNT, parsed))


def _restore_continuous_levels(value) -> set[int]:
    if not isinstance(value, list):
        return set()
    levels: set[int] = set()
    for item in value:
        try:
            level = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= level < AUTO_WIND_GROUP_MAX_COUNT:
            levels.add(level)
    return levels


def _restore_manual_groups(value, valid_tokens: set[str]) -> tuple[WindManualGroup, ...]:
    if not isinstance(value, list):
        return ()
    groups: list[WindManualGroup] = []
    used_layer_ids: set[int] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        layer_id = _coerce_optional_int(item.get("layer_id"))
        if layer_id is None or layer_id in used_layer_ids:
            continue
        raw_tokens = item.get("joint_tokens")
        tokens = frozenset(str(token) for token in raw_tokens if isinstance(token, str)) if isinstance(raw_tokens, list) else frozenset()
        tokens = frozenset(token for token in tokens if token in valid_tokens)
        edit_mode = str(item.get("edit_mode", EDIT_MODE_SUBTREE))
        if edit_mode not in {EDIT_MODE_SUBTREE, EDIT_MODE_BONES}:
            edit_mode = EDIT_MODE_SUBTREE
        name = str(item.get("name", f"Manual group {layer_id}")).strip() or f"Manual group {layer_id}"
        groups.append(WindManualGroup(layer_id=layer_id, name=name, joint_tokens=tokens, edit_mode=edit_mode))
        used_layer_ids.add(layer_id)
    return tuple(sorted(groups, key=lambda group: group.layer_id))


def _restore_expanded_group_source_keys(value) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str) and item}


def _restore_group_settings(value) -> dict[str, dict[str, bool | float]]:
    if not isinstance(value, dict):
        return {}
    restored: dict[str, dict[str, bool | float]] = {}
    for source_key, raw_settings in value.items():
        if not isinstance(source_key, str) or not source_key or not isinstance(raw_settings, dict):
            continue
        settings: dict[str, bool | float] = {}
        for field in _WIND_GROUP_BOOLEAN_FIELDS:
            raw_value = raw_settings.get(field)
            if isinstance(raw_value, bool):
                settings[field] = raw_value
        for field in _WIND_GROUP_NUMERIC_FIELDS:
            raw_value = raw_settings.get(field)
            if isinstance(raw_value, bool):
                continue
            try:
                settings[field] = max(0.0, min(float(raw_value), 1.0))
            except (TypeError, ValueError):
                continue
        if settings:
            restored[source_key] = settings
    return restored


def _add_group_header(layout, parent, title: str) -> None:
    line = QFrame(parent)
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Plain)
    line.setStyleSheet("color: rgba(0, 0, 0, 85);")
    label = QLabel(title, parent)
    label.setObjectName("MutedLabel")
    label.setStyleSheet("font-weight: 700;")
    layout.addSpacing(5)
    layout.addWidget(line)
    layout.addSpacing(3)
    layout.addWidget(label)
