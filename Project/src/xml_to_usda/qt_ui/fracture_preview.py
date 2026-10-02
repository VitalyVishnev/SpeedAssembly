"""Qt-facing fracture preview payload preparation.

Layer: UI adapter.

This module converts `FracturePreviewResult` into a flat colored triangle
payload that an OpenGL widget can draw without knowing fracture planning rules.
"""

from __future__ import annotations

import math
import contextlib
from array import array
from dataclasses import dataclass, replace

import numpy as np

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..fracture_collision import FractureCollisionMode, FractureCollisionSettings
from ..fracture_preview_service import (
    DEFAULT_FRACTURE_PREVIEW_POLYCOUNT,
    FracturePreviewBoneSegment,
    FracturePreviewResult,
    FracturePreviewSettings,
)
from ..fracture_service import MAX_AUTO_BRANCH_CUT_OFFSET, MIN_AUTO_BRANCH_CUT_OFFSET, FractureSettings
from ..fracture_viewport_scene import build_fracture_viewport_scene
from ..models import Color4, GeometryBuffer, Quaternion, UdimMode, Vector3
from ..viewport_scene import ViewportScene
from .material_controls import MaterialUdimRow, MaterialUdimValue, set_tooltip
from .preview_shell import PreviewShellDialog, apply_compact_preview_panel_style
from .viewport import MAX_QT_OPENGL_BUFFER_BYTES, MATCAP_VERTEX_STRIDE, MatcapInstanceDraw, MatcapViewport


FRACTURE_SOURCE_VERTEX_STRIDE = 10
FRACTURE_VERTEX_STRIDE = MATCAP_VERTEX_STRIDE
FRACTURE_MATCAP_TINT_STRENGTH = 0.78
MAX_FRACTURE_PREVIEW_UPLOAD_BYTES = 256 * 1024 * 1024
BRANCH_PRUNE_SLIDER_EXPONENT = 4.0


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
    explode_offset: Vector3 = Vector3(0.0, 0.0, 0.0)


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
    base_vertex_count: int = 0
    base_triangle_count: int = 0
    base_uploaded_triangle_count: int = 0


@dataclass(frozen=True)
class FractureRenderPayload:
    vertex_components: np.ndarray
    min_point: Vector3
    max_point: Vector3


class _CollapsibleSettingsSection(QFrame):
    """Compact settings group with a stable header and hideable contents."""

    def __init__(self, title: str, *, expanded: bool, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("FractureSettingsSection")
        section_layout = QVBoxLayout(self)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(5)

        self.toggle = QToolButton(self)
        self.toggle.setObjectName("SettingsSectionToggle")
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.toggle.setChecked(expanded)
        section_layout.addWidget(self.toggle)

        self.content = QWidget(self)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(5)
        section_layout.addWidget(self.content)
        self.toggle.toggled.connect(self._set_expanded)
        self._set_expanded(expanded)

    def _set_expanded(self, expanded: bool) -> None:
        self.content.setVisible(expanded)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)


class FracturePreviewDialog(PreviewShellDialog):
    def __init__(
        self,
        *,
        settings: FracturePreviewSettings | None = None,
        preview: FracturePreviewResult | None = None,
        on_settings_changed=None,
        on_export_requested=None,
        parent=None,
    ) -> None:
        super().__init__(title="Fracture Preview", parent=parent)
        self._on_settings_changed = on_settings_changed or (lambda settings: None)
        self._on_export_requested = on_export_requested or (lambda: None)
        self._settings = settings or FracturePreviewSettings()
        self._manual_cut_tokens = self._settings.fracture.pinned_cut_joint_tokens
        self._manual_cut_undo_stack = list(self._manual_cut_tokens)
        self._cut_delete_buttons: dict[str, QPushButton] = {}
        self._collision_visual_base_scale = self._collision_geometry_setting(self._settings.collision)
        self._collision_visual_base_length_scale = self._collision_length_setting(self._settings.collision)
        self.current_preview: FracturePreviewResult | None = None
        self.viewport_mesh: FractureViewportMesh | None = None
        self._full_viewport_mesh: FractureViewportMesh | None = None

        viewport_host = QWidget(self)
        viewport_layout = QGridLayout(viewport_host)
        viewport_layout.setContentsMargins(0, 0, 0, 0)
        viewport_layout.setSpacing(0)
        self.viewport = MatcapViewport(viewport_host)
        self.viewport.set_matcap_tint_strength(FRACTURE_MATCAP_TINT_STRENGTH)
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
        self.set_viewport_widget(viewport_host)

        settings_panel, settings_shell_layout = self.create_settings_panel(width=320, default_width=480)
        apply_compact_preview_panel_style(settings_panel)
        settings_shell_layout.setContentsMargins(0, 0, 0, 0)
        settings_shell_layout.setSpacing(0)
        settings_scroll = QScrollArea(settings_panel)
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        settings_content = QWidget(settings_scroll)
        settings_layout = QVBoxLayout(settings_content)
        settings_layout.setContentsMargins(14, 14, 14, 14)
        settings_layout.setSpacing(8)
        settings_scroll.setWidget(settings_content)
        settings_shell_layout.addWidget(settings_scroll)

        title = QLabel("Fracturing", settings_panel)
        title.setStyleSheet("font-weight: 700;")
        settings_layout.addWidget(title)

        mode_label = QLabel("Manual Fracturing", settings_panel)
        mode_label.setStyleSheet("font-weight: 700; color: #2b3032;")
        settings_layout.addWidget(mode_label)

        self.preview_geometry_section = _CollapsibleSettingsSection(
            "Preview Geometry", expanded=True, parent=settings_content
        )
        self.automatic_cuts_section = _CollapsibleSettingsSection(
            "Automatic Cuts", expanded=True, parent=settings_content
        )
        self.cut_surface_section = _CollapsibleSettingsSection(
            "Cut Surface", expanded=False, parent=settings_content
        )
        self.viewport_section = _CollapsibleSettingsSection("Viewport", expanded=True, parent=settings_content)
        self.collision_section = _CollapsibleSettingsSection("Collision", expanded=False, parent=settings_content)
        self.manual_cuts_section = _CollapsibleSettingsSection("Manual Cuts", expanded=False, parent=settings_content)
        for section in (
            self.preview_geometry_section,
            self.automatic_cuts_section,
            self.cut_surface_section,
            self.viewport_section,
            self.collision_section,
            self.manual_cuts_section,
        ):
            settings_layout.addWidget(section)

        automatic_cuts_layout = self.automatic_cuts_section.content_layout
        preview_geometry_layout = self.preview_geometry_section.content_layout
        cut_surface_layout = self.cut_surface_section.content_layout
        viewport_layout = self.viewport_section.content_layout
        collision_layout = self.collision_section.content_layout
        manual_cuts_layout = self.manual_cuts_section.content_layout

        self.piece_count_slider, self.piece_count_spin = _build_int_slider_row(
            settings_panel,
            minimum=0,
            maximum=64,
            value=int(self._settings.fracture.target_piece_count),
            step=1,
        )
        self.branch_count_label = QLabel("Auto Branches", settings_panel)
        set_tooltip(
            "Automatic branch detach count. Stump and separated stems are counted separately.",
            self.branch_count_label,
            self.piece_count_slider,
            self.piece_count_spin,
        )
        automatic_cuts_layout.addWidget(self.branch_count_label)
        automatic_cuts_layout.addLayout(_slider_row(self.piece_count_slider, self.piece_count_spin))

        self.polycount_slider, self.polycount_spin = _build_int_slider_row(
            settings_panel,
            minimum=1,
            maximum=10_000_000,
            value=int(self._settings.final_polycount),
            step=50_000,
        )
        preview_polycount_label = QLabel("Preview Polycount", settings_panel)
        set_tooltip(
            "Triangle budget for the preview mesh. Lower previews faster and rougher; higher keeps more detail.",
            preview_polycount_label,
            self.polycount_slider,
            self.polycount_spin,
        )
        preview_geometry_layout.addWidget(preview_polycount_label)
        preview_geometry_layout.addLayout(_slider_row(self.polycount_slider, self.polycount_spin))

        self.branch_prune_slider, self.branch_prune_spin = _build_branch_prune_slider_row(
            settings_panel,
            value=float(self._settings.branch_prune_aggression),
        )
        branch_prune_label = QLabel("Remove Small Branches", settings_panel)
        set_tooltip(
            "Removes the smallest disconnected base-mesh islands first. Lower keeps twigs; higher leaves larger branches only.",
            branch_prune_label,
            self.branch_prune_slider,
            self.branch_prune_spin,
        )
        preview_geometry_layout.addWidget(branch_prune_label)
        preview_geometry_layout.addLayout(_slider_row(self.branch_prune_slider, self.branch_prune_spin))

        self.base_priority_slider, self.base_priority_spin = _build_float_slider_row(
            settings_panel,
            minimum=0.0,
            maximum=1.0,
            value=float(self._settings.base_mesh_priority),
            step=0.01,
            scale=100,
        )
        base_priority_label = QLabel("Base Priority", settings_panel)
        set_tooltip(
            "Reserves preview budget for base/trunk geometry. Lower favors repeated parts; higher preserves the base mesh.",
            base_priority_label,
            self.base_priority_slider,
            self.base_priority_spin,
        )
        preview_geometry_layout.addWidget(base_priority_label)
        preview_geometry_layout.addLayout(_slider_row(self.base_priority_slider, self.base_priority_spin))

        self.branch_height_bias_slider, self.branch_height_bias_spin = _build_float_slider_row(
            settings_panel,
            minimum=-1.0,
            maximum=1.0,
            value=float(self._settings.fracture.branch_height_bias),
            step=0.01,
            scale=100,
        )
        branch_height_bias_label = QLabel("Branch Height Bias", settings_panel)
        set_tooltip(
            "Biases automatic branch ranking by height. Negative favors lower branches; positive favors upper branches.",
            branch_height_bias_label,
            self.branch_height_bias_slider,
            self.branch_height_bias_spin,
        )
        branch_height_bias_hint_host = QWidget(settings_panel)
        branch_height_bias_hint_layout = QGridLayout(branch_height_bias_hint_host)
        branch_height_bias_hint_layout.setContentsMargins(0, 0, 0, 0)
        branch_height_bias_hint_layout.setHorizontalSpacing(0)
        for column in range(3):
            branch_height_bias_hint_layout.setColumnStretch(column, 1)
        for column, text, alignment in (
            (0, "Lower", Qt.AlignmentFlag.AlignLeft),
            (1, "Even", Qt.AlignmentFlag.AlignHCenter),
            (2, "Upper", Qt.AlignmentFlag.AlignRight),
        ):
            hint = QLabel(text, branch_height_bias_hint_host)
            hint.setObjectName("MutedLabel")
            branch_height_bias_hint_layout.addWidget(hint, 0, column, alignment=alignment)
        branch_height_bias_hint_row = QHBoxLayout()
        branch_height_bias_hint_row.setContentsMargins(0, 0, 0, 0)
        branch_height_bias_hint_row.setSpacing(0)
        branch_height_bias_hint_row.addWidget(branch_height_bias_hint_host, 1)
        branch_height_bias_hint_row.addSpacing(self.branch_height_bias_spin.width() + 8)
        automatic_cuts_layout.addWidget(branch_height_bias_label)
        automatic_cuts_layout.addLayout(_slider_row(self.branch_height_bias_slider, self.branch_height_bias_spin))
        automatic_cuts_layout.addLayout(branch_height_bias_hint_row)

        self.auto_branch_cut_offset_slider, self.auto_branch_cut_offset_spin = _build_float_slider_row(
            settings_panel,
            minimum=MIN_AUTO_BRANCH_CUT_OFFSET,
            maximum=MAX_AUTO_BRANCH_CUT_OFFSET,
            value=float(self._settings.fracture.auto_branch_cut_offset),
            step=0.01,
            scale=100,
        )
        auto_branch_cut_offset_label = QLabel("Cut From Branch Start", settings_panel)
        set_tooltip(
            "Automatic cut position along the physical branch, measured from its start. "
            "0.30 means 30% along the branch. Applies to both flat and Detailed Cuts.",
            auto_branch_cut_offset_label,
            self.auto_branch_cut_offset_slider,
            self.auto_branch_cut_offset_spin,
        )
        automatic_cuts_layout.addWidget(auto_branch_cut_offset_label)
        automatic_cuts_layout.addLayout(_slider_row(self.auto_branch_cut_offset_slider, self.auto_branch_cut_offset_spin))

        self.exploded_view_slider, self.exploded_view_spin = _build_float_slider_row(
            settings_panel,
            minimum=0.0,
            maximum=2.0,
            value=0.0,
            step=0.01,
            scale=100,
        )
        exploded_view_label = QLabel("Exploded View", settings_panel)
        set_tooltip(
            "Visual spacing between pieces only. Lower shows intact placement; higher pulls pieces apart.",
            exploded_view_label,
            self.exploded_view_slider,
            self.exploded_view_spin,
        )
        viewport_layout.addWidget(exploded_view_label)
        viewport_layout.addLayout(_slider_row(self.exploded_view_slider, self.exploded_view_spin))

        self.color_strength_slider, self.color_strength_spin = _build_float_slider_row(
            settings_panel,
            minimum=0.0,
            maximum=1.0,
            value=FRACTURE_MATCAP_TINT_STRENGTH,
            step=0.01,
            scale=100,
        )
        piece_color_label = QLabel("Piece Color", settings_panel)
        set_tooltip(
            "Piece color tint strength in the viewport. Lower looks more neutral; higher separates pieces more clearly.",
            piece_color_label,
            self.color_strength_slider,
            self.color_strength_spin,
        )
        viewport_layout.addWidget(piece_color_label)
        viewport_layout.addLayout(_slider_row(self.color_strength_slider, self.color_strength_spin))

        self.show_bones_check = QCheckBox("Show Bones", settings_panel)
        self.hide_repeated_parts_check = QCheckBox("Hide Repeated Parts", settings_panel)
        self.hide_repeated_parts_check.setChecked(True)
        self.generate_caps_check = QCheckBox("Generate Caps", settings_panel)
        self.detailed_cut_check = QCheckBox("Detailed Cuts", settings_panel)
        self.detailed_cut_intensity_slider, self.detailed_cut_intensity_spin = _build_float_slider_row(
            settings_panel,
            minimum=0.0,
            maximum=100.0,
            value=float(self._settings.fracture.detailed_cut_intensity),
            step=0.1,
            scale=10,
        )
        self.detailed_cut_scale_slider, self.detailed_cut_scale_spin = _build_float_slider_row(
            settings_panel,
            minimum=0.1,
            maximum=2.0,
            value=float(self._settings.fracture.detailed_cut_scale),
            step=0.01,
            scale=100,
        )
        self.detailed_cut_density_slider, self.detailed_cut_density_spin = _build_int_slider_row(
            settings_panel,
            minimum=4,
            maximum=64,
            value=int(self._settings.fracture.detailed_cut_density),
            step=1,
        )
        self.detailed_cut_bend_slider, self.detailed_cut_bend_spin = _build_float_slider_row(
            settings_panel,
            minimum=1.0,
            maximum=180.0,
            value=float(self._settings.fracture.detailed_cut_max_bend_angle),
            step=1.0,
            scale=1,
        )
        self.detailed_cut_intensity_label = QLabel("Cut Intensity", settings_panel)
        self.detailed_cut_scale_label = QLabel("Chip Scale", settings_panel)
        self.detailed_cut_density_label = QLabel("Cut Detail", settings_panel)
        self.detailed_cut_bend_label = QLabel("Bend Limit", settings_panel)
        self.override_caps_material_check = QCheckBox("Override Caps Material", settings_panel)
        set_tooltip("Shows selectable skeleton cut segments. Off hides guides; on shows bones for manual cuts.", self.show_bones_check)
        set_tooltip(
            "Hides instanced repeated parts in preview. Off uploads each prototype once and draws every placed instance.",
            self.hide_repeated_parts_check,
        )
        set_tooltip("Writes cap faces on cut surfaces. Off leaves open cuts; on closes piece interiors.", self.generate_caps_check)
        set_tooltip(
            "Uses a closed displaced cutter and exact Boolean split. Off uses fast flat cuts.",
            self.detailed_cut_check,
        )
        set_tooltip(
            "Requested splinter depth. The effective depth stops before a branch fork or a sharp skeleton bend.",
            self.detailed_cut_intensity_label,
            self.detailed_cut_intensity_slider,
            self.detailed_cut_intensity_spin,
        )
        set_tooltip(
            "Noise wavelength relative to local branch radius. Lower creates finer splinters; higher creates broader chips without changing depth.",
            self.detailed_cut_scale_label,
            self.detailed_cut_scale_slider,
            self.detailed_cut_scale_spin,
        )
        set_tooltip(
            "Triangular cutter density across the local branch diameter. Higher values add detail and Boolean cost.",
            self.detailed_cut_density_label,
            self.detailed_cut_density_slider,
            self.detailed_cut_density_spin,
        )
        set_tooltip(
            "Stops displacement before the next skeleton segment whose direction changes by at least this angle.",
            self.detailed_cut_bend_label,
            self.detailed_cut_bend_slider,
            self.detailed_cut_bend_spin,
        )
        set_tooltip(
            "Uses a separate material for cap faces. Off reuses defaults; on assigns the Caps Material row.",
            self.override_caps_material_check,
        )
        self.caps_material_row = MaterialUdimRow(
            label="Caps Material",
            value=MaterialUdimValue(udim_mode=UdimMode.OFF, udim_id=1001),
            placeholder="/Game/Path/Material.Material",
            path_max_width=None,
            stacked_udim=True,
            parent=settings_panel,
        )
        self.stump_piece_check = QCheckBox("Stump Piece", settings_panel)
        self.separate_stems_check = QCheckBox("Separate Stems", settings_panel)
        self.collision_check = QCheckBox("Generate Collision", settings_panel)
        set_tooltip(
            "Forces a ground stump cut on every independent stem. With Separate Stems, each stump is its own piece.",
            self.stump_piece_check,
        )
        set_tooltip(
            "Separates independent root-level stems before automatic branch detachment.",
            self.separate_stems_check,
        )
        set_tooltip("Exports simple collision for pieces. Off exports visuals only; on adds collision companion meshes.", self.collision_check)
        self.collision_mode_combo = QComboBox(settings_panel)
        self.collision_mode_combo.addItem("Convex Hull", FractureCollisionMode.CONVEX.value)
        self.collision_mode_combo.addItem("Capsules", FractureCollisionMode.CAPSULE.value)
        self.collision_mode_combo.addItem("Sphere", FractureCollisionMode.SPHERE.value)
        self.collision_mode_combo.hide()
        self.collision_mode_button_row = QWidget(settings_panel)
        collision_mode_button_layout = QHBoxLayout(self.collision_mode_button_row)
        collision_mode_button_layout.setContentsMargins(0, 0, 0, 0)
        collision_mode_button_layout.setSpacing(6)
        self.collision_mode_buttons: dict[FractureCollisionMode, QPushButton] = {}
        for label, mode in (
            ("Convex", FractureCollisionMode.CONVEX),
            ("Capsule", FractureCollisionMode.CAPSULE),
            ("Sphere", FractureCollisionMode.SPHERE),
        ):
            button = QPushButton(label, self.collision_mode_button_row)
            button.setCheckable(True)
            button.setObjectName("CollisionModeButton")
            button.clicked.connect(lambda _checked, selected=mode: self._select_collision_mode(selected))
            button.setToolTip(
                "Collision shape mode. Convex is fitted hulls; Capsule follows skeleton segments; Sphere uses one bound."
            )
            collision_mode_button_layout.addWidget(button)
            self.collision_mode_buttons[mode] = button
        self.collision_include_parts_check = QCheckBox("Collision Includes Parts", settings_panel)
        set_tooltip(
            "Includes repeated parts when fitting collision. Off fits base mesh only; on grows collision around parts too.",
            self.collision_include_parts_check,
        )
        self.convex_vertices_slider, self.convex_vertices_spin = _build_int_slider_row(
            settings_panel,
            minimum=4,
            maximum=32,
            value=int(self._settings.collision.convex_max_vertices),
            step=1,
        )
        self.sphere_scale_slider, self.sphere_scale_spin = _build_float_slider_row(
            settings_panel,
            minimum=0.5,
            maximum=1.25,
            value=float(self._settings.collision.sphere_radius_scale),
            step=0.01,
            scale=100,
        )
        self.capsule_simplify_slider, self.capsule_simplify_spin = _build_int_slider_row(
            settings_panel,
            minimum=0,
            maximum=100,
            value=int(self._settings.collision.capsule_simplify),
            step=1,
        )
        self.capsule_scale_slider, self.capsule_scale_spin = _build_float_slider_row(
            settings_panel,
            minimum=0.05,
            maximum=6.0,
            value=float(self._settings.collision.capsule_scale),
            step=0.01,
            scale=100,
        )
        self.capsule_scale_by_length_slider, self.capsule_scale_by_length_spin = _build_float_slider_row(
            settings_panel,
            minimum=0.0,
            maximum=6.0,
            value=float(self._settings.collision.capsule_scale_by_length),
            step=0.01,
            scale=100,
        )
        self.collision_opacity_slider, self.collision_opacity_spin = _build_float_slider_row(
            settings_panel,
            minimum=0.05,
            maximum=0.8,
            value=float(self._settings.collision.ghost_opacity),
            step=0.01,
            scale=100,
        )
        self.reset_cuts_button = QPushButton("Reset Cuts", settings_panel)
        self.reset_cuts_button.clicked.connect(self._reset_manual_cuts)
        self.reset_cuts_button.setToolTip("Clears manual cuts. Fewer cuts lets auto-fill decide; more manual cuts pins split sites.")
        viewport_layout.addWidget(self.show_bones_check)
        viewport_layout.addWidget(self.hide_repeated_parts_check)
        automatic_cuts_layout.addWidget(self.stump_piece_check)
        automatic_cuts_layout.addWidget(self.separate_stems_check)
        cut_surface_layout.addWidget(self.detailed_cut_check)
        cut_surface_layout.addWidget(self.detailed_cut_intensity_label)
        cut_surface_layout.addLayout(_slider_row(self.detailed_cut_intensity_slider, self.detailed_cut_intensity_spin))
        cut_surface_layout.addWidget(self.detailed_cut_scale_label)
        cut_surface_layout.addLayout(_slider_row(self.detailed_cut_scale_slider, self.detailed_cut_scale_spin))
        cut_surface_layout.addWidget(self.detailed_cut_density_label)
        cut_surface_layout.addLayout(_slider_row(self.detailed_cut_density_slider, self.detailed_cut_density_spin))
        cut_surface_layout.addWidget(self.detailed_cut_bend_label)
        cut_surface_layout.addLayout(_slider_row(self.detailed_cut_bend_slider, self.detailed_cut_bend_spin))
        cut_surface_layout.addWidget(self.generate_caps_check)
        cut_surface_layout.addWidget(self.override_caps_material_check)
        cut_surface_layout.addWidget(self.caps_material_row)
        collision_layout.addWidget(self.collision_check)
        self.collision_mode_label = QLabel("Collision Mode", settings_panel)
        self.convex_vertices_label = QLabel("Convex Vertices", settings_panel)
        self.sphere_scale_label = QLabel("Sphere Scale", settings_panel)
        self.capsule_simplify_label = QLabel("Capsule Simplify", settings_panel)
        self.capsule_scale_label = QLabel("Capsule Scale", settings_panel)
        self.capsule_scale_by_length_label = QLabel("Capsule Scale By Length", settings_panel)
        self.collision_opacity_label = QLabel("Collision Opacity", settings_panel)
        set_tooltip(
            "Collision shape mode. Convex is fitted hulls; Capsule follows skeleton segments; Sphere uses one bound.",
            self.collision_mode_label,
            self.collision_mode_button_row,
        )
        set_tooltip(
            "Maximum vertices in a convex collision hull. Lower is simpler; higher follows the piece outline better.",
            self.convex_vertices_label,
            self.convex_vertices_slider,
            self.convex_vertices_spin,
        )
        set_tooltip(
            "Scale for sphere collision radius. Lower tightens the sphere; higher gives more coverage.",
            self.sphere_scale_label,
            self.sphere_scale_slider,
            self.sphere_scale_spin,
        )
        set_tooltip(
            "Simplifies capsule chains. Lower keeps more segments; higher merges into fewer capsules.",
            self.capsule_simplify_label,
            self.capsule_simplify_slider,
            self.capsule_simplify_spin,
        )
        set_tooltip(
            "Scales capsule radius. Lower tightens capsules; higher covers more nearby geometry.",
            self.capsule_scale_label,
            self.capsule_scale_slider,
            self.capsule_scale_spin,
        )
        set_tooltip(
            "Adds radius from segment length. Lower keeps thin capsules; higher fattens long segments.",
            self.capsule_scale_by_length_label,
            self.capsule_scale_by_length_slider,
            self.capsule_scale_by_length_spin,
        )
        set_tooltip(
            "Collision preview opacity only. Lower is more transparent; higher makes collision shapes easier to see.",
            self.collision_opacity_label,
            self.collision_opacity_slider,
            self.collision_opacity_spin,
        )
        collision_layout.addWidget(self.collision_mode_label)
        collision_layout.addWidget(self.collision_mode_button_row)
        collision_layout.addWidget(self.collision_include_parts_check)
        collision_layout.addWidget(self.convex_vertices_label)
        collision_layout.addLayout(_slider_row(self.convex_vertices_slider, self.convex_vertices_spin))
        collision_layout.addWidget(self.sphere_scale_label)
        collision_layout.addLayout(_slider_row(self.sphere_scale_slider, self.sphere_scale_spin))
        collision_layout.addWidget(self.capsule_simplify_label)
        collision_layout.addLayout(_slider_row(self.capsule_simplify_slider, self.capsule_simplify_spin))
        collision_layout.addWidget(self.capsule_scale_label)
        collision_layout.addLayout(_slider_row(self.capsule_scale_slider, self.capsule_scale_spin))
        self.capsule_tuning_label = QLabel(
            "Capsule Fine Tune (temporary): tune these against UE behavior; stable values will move into code.",
            settings_panel,
        )
        self.capsule_tuning_label.setWordWrap(True)
        self.capsule_tuning_label.setObjectName("MutedLabel")
        collision_layout.addWidget(self.capsule_tuning_label)
        collision_layout.addWidget(self.capsule_scale_by_length_label)
        collision_layout.addLayout(_slider_row(self.capsule_scale_by_length_slider, self.capsule_scale_by_length_spin))
        collision_layout.addWidget(self.collision_opacity_label)
        collision_layout.addLayout(_slider_row(self.collision_opacity_slider, self.collision_opacity_spin))

        self.cut_list_label = QLabel("Cuts", settings_panel)
        self.cut_list_host = QWidget(settings_panel)
        self.cut_list_layout = QVBoxLayout(self.cut_list_host)
        self.cut_list_layout.setContentsMargins(0, 0, 0, 0)
        self.cut_list_layout.setSpacing(4)
        manual_cuts_layout.addWidget(self.cut_list_label)
        manual_cuts_layout.addWidget(self.cut_list_host)
        manual_cuts_layout.addWidget(self.reset_cuts_button)

        self.export_button = QPushButton("Export Fracture Pieces", settings_panel)
        self.export_button.clicked.connect(self._on_export_requested)
        settings_layout.addWidget(self.export_button)

        self.summary_label = QLabel("Preparing preview geometry...", settings_panel)
        self.summary_label.setWordWrap(True)
        settings_layout.addWidget(self.summary_label)
        settings_layout.addStretch(1)

        self.viewport.on_bone_cut_toggled = self._toggle_manual_cut_token
        self.undo_cut_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        self.undo_cut_shortcut.activated.connect(self._undo_last_manual_cut)
        self._sync_settings_controls(self._settings)
        self.piece_count_slider.sliderReleased.connect(self._emit_settings_changed)
        self.piece_count_spin.editingFinished.connect(self._emit_settings_changed)
        self.polycount_slider.sliderReleased.connect(self._emit_settings_changed)
        self.polycount_spin.editingFinished.connect(self._emit_settings_changed)
        self.branch_prune_slider.sliderReleased.connect(self._emit_settings_changed)
        self.branch_prune_spin.editingFinished.connect(self._emit_settings_changed)
        self.base_priority_slider.sliderReleased.connect(self._emit_settings_changed)
        self.base_priority_spin.editingFinished.connect(self._emit_settings_changed)
        self.branch_height_bias_slider.sliderReleased.connect(self._emit_settings_changed)
        self.branch_height_bias_spin.editingFinished.connect(self._emit_settings_changed)
        self.auto_branch_cut_offset_slider.sliderReleased.connect(self._emit_settings_changed)
        self.auto_branch_cut_offset_spin.editingFinished.connect(self._emit_settings_changed)
        self.exploded_view_spin.valueChanged.connect(self._handle_exploded_view_changed)
        self.exploded_view_slider.valueChanged.connect(
            lambda raw: self._handle_exploded_view_changed(float(raw) / 100.0)
        )
        self.color_strength_spin.valueChanged.connect(self._handle_color_strength_changed)
        self.color_strength_slider.valueChanged.connect(lambda raw: self._handle_color_strength_changed(float(raw) / 100.0))
        self.show_bones_check.toggled.connect(self._handle_show_bones_changed)
        self.hide_repeated_parts_check.toggled.connect(self._handle_hide_repeated_parts_changed)
        self.generate_caps_check.toggled.connect(self._handle_generate_caps_changed)
        self.detailed_cut_check.toggled.connect(lambda _checked: self._handle_detailed_cut_controls_changed())
        self.detailed_cut_intensity_slider.sliderReleased.connect(self._emit_settings_changed)
        self.detailed_cut_intensity_spin.editingFinished.connect(self._emit_settings_changed)
        self.detailed_cut_scale_slider.sliderReleased.connect(self._emit_settings_changed)
        self.detailed_cut_scale_spin.editingFinished.connect(self._emit_settings_changed)
        self.detailed_cut_density_slider.sliderReleased.connect(self._emit_settings_changed)
        self.detailed_cut_density_spin.editingFinished.connect(self._emit_settings_changed)
        self.detailed_cut_bend_slider.sliderReleased.connect(self._emit_settings_changed)
        self.detailed_cut_bend_spin.editingFinished.connect(self._emit_settings_changed)
        self.override_caps_material_check.toggled.connect(lambda _checked: self._sync_caps_material_controls())
        self.stump_piece_check.toggled.connect(lambda _checked: self._emit_settings_changed())
        self.separate_stems_check.toggled.connect(lambda _checked: self._emit_settings_changed())
        self.collision_check.toggled.connect(lambda _checked: self._handle_collision_controls_changed())
        self.collision_mode_combo.currentIndexChanged.connect(lambda _index: self._handle_collision_controls_changed())
        self.collision_include_parts_check.toggled.connect(lambda _checked: self._emit_settings_changed())
        self.convex_vertices_slider.sliderReleased.connect(self._emit_settings_changed)
        self.convex_vertices_spin.editingFinished.connect(self._emit_settings_changed)
        self.sphere_scale_slider.valueChanged.connect(lambda _raw: self._handle_collision_visual_changed())
        self.sphere_scale_spin.valueChanged.connect(lambda _value: self._handle_collision_visual_changed())
        self.capsule_simplify_slider.sliderReleased.connect(self._emit_settings_changed)
        self.capsule_simplify_spin.editingFinished.connect(self._emit_settings_changed)
        self.capsule_scale_slider.valueChanged.connect(lambda _raw: self._handle_collision_visual_changed())
        self.capsule_scale_spin.valueChanged.connect(lambda _value: self._handle_collision_visual_changed())
        self.capsule_scale_by_length_slider.valueChanged.connect(lambda _raw: self._handle_collision_visual_changed())
        self.capsule_scale_by_length_spin.valueChanged.connect(lambda _value: self._handle_collision_visual_changed())
        self.collision_opacity_slider.valueChanged.connect(lambda _raw: self._handle_collision_visual_changed())
        self.collision_opacity_spin.valueChanged.connect(lambda _value: self._handle_collision_visual_changed())
        if preview is not None:
            self.set_preview(preview)

    def settings(self) -> FracturePreviewSettings:
        return FracturePreviewSettings(
            fracture=FractureSettings(
                target_piece_count=int(self.piece_count_spin.value()),
                pinned_cut_joint_tokens=self._manual_cut_tokens,
                generate_caps=self.generate_caps_check.isChecked(),
                preserve_trunk_bias=float(self._settings.fracture.preserve_trunk_bias),
                force_stump_piece=self.stump_piece_check.isChecked(),
                separate_stems=self.separate_stems_check.isChecked(),
                branch_height_bias=float(self.branch_height_bias_spin.value()),
                auto_branch_cut_offset=float(self.auto_branch_cut_offset_spin.value()),
                detailed_cuts_enabled=self.detailed_cut_check.isChecked(),
                detailed_cut_intensity=float(self.detailed_cut_intensity_spin.value()),
                detailed_cut_scale=float(self.detailed_cut_scale_spin.value()),
                detailed_cut_density=int(self.detailed_cut_density_spin.value()),
                detailed_cut_max_bend_angle=float(self.detailed_cut_bend_spin.value()),
            ),
            collision=FractureCollisionSettings(
                enabled=self.collision_check.isChecked(),
                mode=FractureCollisionMode(str(self.collision_mode_combo.currentData())),
                include_instance_parts=self.collision_include_parts_check.isChecked(),
                convex_max_vertices=int(self.convex_vertices_spin.value()),
                sphere_radius_scale=float(self.sphere_scale_spin.value()),
                capsule_simplify=int(self.capsule_simplify_spin.value()),
                capsule_scale=float(self.capsule_scale_spin.value()),
                capsule_scale_by_length=float(self.capsule_scale_by_length_spin.value()),
                ghost_opacity=float(self.collision_opacity_spin.value()),
            ),
            final_polycount=int(self.polycount_spin.value() or DEFAULT_FRACTURE_PREVIEW_POLYCOUNT),
            base_mesh_priority=float(self.base_priority_spin.value()),
            branch_prune_aggression=float(self.branch_prune_spin.value()),
        )

    def caps_material_override_enabled(self) -> bool:
        return bool(self.generate_caps_check.isChecked() and self.override_caps_material_check.isChecked())

    def caps_material_value(self) -> MaterialUdimValue:
        return self.caps_material_row.value()

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
        frame_camera = self.current_preview is None
        if preview.viewport_scene is None:
            preview = replace(preview, viewport_scene=build_fracture_viewport_scene(preview))
        self._collision_visual_base_scale = self._collision_geometry_setting(self._settings.collision)
        self._collision_visual_base_length_scale = self._collision_length_setting(self._settings.collision)
        self.current_preview = preview
        self._full_viewport_mesh = None
        self._sync_repeated_parts_visibility(frame_camera=frame_camera)
        self._apply_collision_visual_settings()
        self.viewport.set_selected_cut_tokens(self._manual_cut_tokens)
        self.viewport.set_show_bones(self.show_bones_check.isChecked())
        self.loading_label.hide()

    def set_error(self, message: str) -> None:
        self.loading_label.setText(message)
        self.loading_label.show()
        self.summary_label.setText(message)

    def _sync_settings_controls(self, settings: FracturePreviewSettings) -> None:
        blockers = (
            self.piece_count_slider,
            self.piece_count_spin,
            self.polycount_slider,
            self.polycount_spin,
            self.branch_prune_slider,
            self.branch_prune_spin,
            self.base_priority_slider,
            self.base_priority_spin,
            self.branch_height_bias_slider,
            self.branch_height_bias_spin,
            self.auto_branch_cut_offset_slider,
            self.auto_branch_cut_offset_spin,
            self.show_bones_check,
            self.generate_caps_check,
            self.detailed_cut_check,
            self.detailed_cut_intensity_slider,
            self.detailed_cut_intensity_spin,
            self.detailed_cut_scale_slider,
            self.detailed_cut_scale_spin,
            self.detailed_cut_density_slider,
            self.detailed_cut_density_spin,
            self.detailed_cut_bend_slider,
            self.detailed_cut_bend_spin,
            self.override_caps_material_check,
            self.stump_piece_check,
            self.separate_stems_check,
            self.collision_check,
            self.collision_mode_label,
            self.collision_mode_combo,
            self.collision_mode_button_row,
            self.collision_include_parts_check,
            self.convex_vertices_label,
            self.convex_vertices_slider,
            self.convex_vertices_spin,
            self.sphere_scale_label,
            self.sphere_scale_slider,
            self.sphere_scale_spin,
            self.capsule_simplify_label,
            self.capsule_simplify_slider,
            self.capsule_simplify_spin,
            self.capsule_scale_label,
            self.capsule_scale_slider,
            self.capsule_scale_spin,
            self.capsule_tuning_label,
            self.capsule_scale_by_length_label,
            self.capsule_scale_by_length_slider,
            self.capsule_scale_by_length_spin,
            self.collision_opacity_label,
            self.collision_opacity_slider,
            self.collision_opacity_spin,
        )
        with contextlib.ExitStack() as stack:
            for widget in blockers:
                stack.enter_context(QSignalBlocker(widget))
            self.piece_count_slider.setValue(int(settings.fracture.target_piece_count))
            self.piece_count_spin.setValue(int(settings.fracture.target_piece_count))
            self.polycount_slider.setValue(int(settings.final_polycount))
            self.polycount_spin.setValue(int(settings.final_polycount))
            self.branch_prune_slider.setValue(_branch_prune_value_to_slider(float(settings.branch_prune_aggression)))
            self.branch_prune_spin.setValue(float(settings.branch_prune_aggression))
            self.base_priority_slider.setValue(int(round(float(settings.base_mesh_priority) * 100)))
            self.base_priority_spin.setValue(float(settings.base_mesh_priority))
            self.branch_height_bias_slider.setValue(int(round(float(settings.fracture.branch_height_bias) * 100)))
            self.branch_height_bias_spin.setValue(float(settings.fracture.branch_height_bias))
            self.auto_branch_cut_offset_slider.setValue(
                int(round(float(settings.fracture.auto_branch_cut_offset) * 100))
            )
            self.auto_branch_cut_offset_spin.setValue(float(settings.fracture.auto_branch_cut_offset))
            self.generate_caps_check.setChecked(settings.fracture.generate_caps)
            self.detailed_cut_check.setChecked(settings.fracture.detailed_cuts_enabled)
            self.detailed_cut_intensity_slider.setValue(int(round(float(settings.fracture.detailed_cut_intensity) * 10)))
            self.detailed_cut_intensity_spin.setValue(float(settings.fracture.detailed_cut_intensity))
            self.detailed_cut_scale_slider.setValue(int(round(float(settings.fracture.detailed_cut_scale) * 100)))
            self.detailed_cut_scale_spin.setValue(float(settings.fracture.detailed_cut_scale))
            self.detailed_cut_density_slider.setValue(int(settings.fracture.detailed_cut_density))
            self.detailed_cut_density_spin.setValue(int(settings.fracture.detailed_cut_density))
            self.detailed_cut_bend_slider.setValue(int(round(float(settings.fracture.detailed_cut_max_bend_angle))))
            self.detailed_cut_bend_spin.setValue(float(settings.fracture.detailed_cut_max_bend_angle))
            self.stump_piece_check.setChecked(settings.fracture.force_stump_piece)
            self.separate_stems_check.setChecked(settings.fracture.separate_stems)
            self.collision_check.setChecked(settings.collision.enabled)
            _set_combo_data(self.collision_mode_combo, settings.collision.mode.value)
            self._sync_collision_mode_buttons()
            self.collision_include_parts_check.setChecked(settings.collision.include_instance_parts)
            self.convex_vertices_slider.setValue(int(settings.collision.convex_max_vertices))
            self.convex_vertices_spin.setValue(int(settings.collision.convex_max_vertices))
            self.sphere_scale_slider.setValue(int(round(float(settings.collision.sphere_radius_scale) * 100)))
            self.sphere_scale_spin.setValue(float(settings.collision.sphere_radius_scale))
            self.capsule_simplify_slider.setValue(int(settings.collision.capsule_simplify))
            self.capsule_simplify_spin.setValue(int(settings.collision.capsule_simplify))
            self.capsule_scale_slider.setValue(int(round(float(settings.collision.capsule_scale) * 100)))
            self.capsule_scale_spin.setValue(float(settings.collision.capsule_scale))
            self.capsule_scale_by_length_slider.setValue(int(round(float(settings.collision.capsule_scale_by_length) * 100)))
            self.capsule_scale_by_length_spin.setValue(float(settings.collision.capsule_scale_by_length))
            self.collision_opacity_slider.setValue(int(round(float(settings.collision.ghost_opacity) * 100)))
            self.collision_opacity_spin.setValue(float(settings.collision.ghost_opacity))
            if not settings.fracture.generate_caps:
                self.override_caps_material_check.setChecked(False)
        self._sync_detailed_cut_controls()
        self._sync_caps_material_controls()
        self._sync_collision_controls()
        self._sync_manual_controls()

    def _sync_caps_material_controls(self) -> None:
        enabled = bool(self.generate_caps_check.isChecked())
        self.override_caps_material_check.setVisible(enabled)
        self.override_caps_material_check.setEnabled(enabled)
        override_enabled = enabled and bool(self.override_caps_material_check.isChecked())
        self.caps_material_row.set_controls_visible(override_enabled)

    def _handle_generate_caps_changed(self, _checked: bool) -> None:
        self._sync_caps_material_controls()
        self._emit_settings_changed()

    def _sync_detailed_cut_controls(self) -> None:
        enabled = self.detailed_cut_check.isChecked()
        if enabled:
            with QSignalBlocker(self.generate_caps_check):
                self.generate_caps_check.setChecked(True)
        self.generate_caps_check.setEnabled(not enabled)
        self.generate_caps_check.setToolTip(
            "Detailed Cuts use a closed Boolean solid and therefore always generate matching caps."
            if enabled
            else "Writes cap faces on cut surfaces. Off leaves open cuts; on closes piece interiors."
        )
        for widget in (
            self.detailed_cut_intensity_label,
            self.detailed_cut_intensity_slider,
            self.detailed_cut_intensity_spin,
            self.detailed_cut_scale_label,
            self.detailed_cut_scale_slider,
            self.detailed_cut_scale_spin,
            self.detailed_cut_density_label,
            self.detailed_cut_density_slider,
            self.detailed_cut_density_spin,
            self.detailed_cut_bend_label,
            self.detailed_cut_bend_slider,
            self.detailed_cut_bend_spin,
        ):
            widget.setEnabled(enabled)

    def _handle_detailed_cut_controls_changed(self) -> None:
        self._sync_detailed_cut_controls()
        self._sync_caps_material_controls()
        self._emit_settings_changed()

    def _handle_collision_controls_changed(self) -> None:
        self._sync_collision_mode_buttons()
        self._sync_collision_controls()
        self._emit_settings_changed()

    def _select_collision_mode(self, mode: FractureCollisionMode) -> None:
        before = self.collision_mode_combo.currentData()
        _set_combo_data(self.collision_mode_combo, mode.value)
        if before == mode.value:
            self._sync_collision_mode_buttons()

    def _sync_collision_mode_buttons(self) -> None:
        current = str(self.collision_mode_combo.currentData())
        for mode, button in self.collision_mode_buttons.items():
            with QSignalBlocker(button):
                button.setChecked(mode.value == current)

    def _handle_collision_visual_changed(self) -> None:
        self._apply_collision_visual_settings()

    def _apply_collision_visual_settings(self) -> None:
        settings = self.settings().collision
        scale = self._collision_geometry_setting(settings) / max(0.001, self._collision_visual_base_scale)
        self.viewport.set_collision_visuals(
            opacity=float(settings.ghost_opacity),
            geometry_scale=scale,
            length_scale=self._collision_length_setting(settings),
            base_length_scale=self._collision_visual_base_length_scale,
        )

    def _collision_geometry_setting(self, settings: FractureCollisionSettings) -> float:
        if settings.mode == FractureCollisionMode.CAPSULE:
            return max(0.001, float(settings.capsule_scale))
        if settings.mode == FractureCollisionMode.SPHERE:
            return max(0.001, float(settings.sphere_radius_scale))
        return 1.0

    def _collision_length_setting(self, settings: FractureCollisionSettings) -> float:
        if settings.mode == FractureCollisionMode.CAPSULE:
            return max(0.0, float(settings.capsule_scale_by_length))
        return 0.0

    def _sync_collision_controls(self) -> None:
        enabled = self.collision_check.isChecked()
        mode = FractureCollisionMode(str(self.collision_mode_combo.currentData()))
        always = (
            self.collision_mode_label,
            self.collision_mode_button_row,
            self.collision_opacity_label,
            self.collision_opacity_slider,
            self.collision_opacity_spin,
        )
        convex = (
            self.convex_vertices_label,
            self.convex_vertices_slider,
            self.convex_vertices_spin,
        )
        sphere = (
            self.sphere_scale_label,
            self.sphere_scale_slider,
            self.sphere_scale_spin,
        )
        capsule = (
            self.capsule_simplify_label,
            self.capsule_simplify_slider,
            self.capsule_simplify_spin,
            self.capsule_scale_label,
            self.capsule_scale_slider,
            self.capsule_scale_spin,
            self.capsule_tuning_label,
            self.capsule_scale_by_length_label,
            self.capsule_scale_by_length_slider,
            self.capsule_scale_by_length_spin,
        )
        for widget in (*always, self.collision_include_parts_check, *convex, *sphere, *capsule):
            widget.setEnabled(enabled)
            widget.setVisible(enabled)
        for button in self.collision_mode_buttons.values():
            button.setEnabled(enabled)
            button.setVisible(enabled)
        self.collision_include_parts_check.setVisible(enabled and mode != FractureCollisionMode.CAPSULE)
        for widget in convex:
            widget.setVisible(enabled and mode == FractureCollisionMode.CONVEX)
        for widget in sphere:
            widget.setVisible(enabled and mode == FractureCollisionMode.SPHERE)
        for widget in capsule:
            widget.setVisible(enabled and mode == FractureCollisionMode.CAPSULE)

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

    def _handle_exploded_view_changed(self, value: float) -> None:
        resolved = float(value)
        with QSignalBlocker(self.exploded_view_slider):
            self.exploded_view_slider.setValue(int(round(resolved * 100)))
        self.viewport.set_exploded_view_strength(resolved)

    def _sync_manual_controls(self) -> None:
        self.reset_cuts_button.setVisible(True)
        self.cut_list_label.setVisible(True)
        self.cut_list_host.setVisible(True)
        self.show_bones_check.setEnabled(True)
        self.viewport.set_show_bones(self.show_bones_check.isChecked())
        self._sync_cut_list()

    def _handle_show_bones_changed(self, checked: bool) -> None:
        self.viewport.set_show_bones(checked)

    def _handle_hide_repeated_parts_changed(self, _checked: bool) -> None:
        try:
            self._sync_repeated_parts_visibility()
        except ValueError as exc:
            with QSignalBlocker(self.hide_repeated_parts_check):
                self.hide_repeated_parts_check.setChecked(True)
            self.summary_label.setText(f"Repeated Parts remain hidden: {exc}")

    def _sync_repeated_parts_visibility(self, *, frame_camera: bool = False) -> None:
        if self.current_preview is None or self.current_preview.viewport_scene is None:
            return
        hide_repeated = self.hide_repeated_parts_check.isChecked()
        if hide_repeated and self._full_viewport_mesh is not None:
            self.viewport.set_visible_vertex_count_override(self._full_viewport_mesh.base_vertex_count)
            self.viewport_mesh = replace(
                self._full_viewport_mesh,
                triangle_count=self._full_viewport_mesh.base_triangle_count,
                uploaded_triangle_count=self._full_viewport_mesh.base_uploaded_triangle_count,
                instance_count=0,
            )
            self._update_viewport_summary()
            return
        if not hide_repeated and self._full_viewport_mesh is not None:
            self.viewport.set_visible_vertex_count_override(None)
            self.viewport_mesh = self._full_viewport_mesh
            self._update_viewport_summary()
            return
        viewport_scene = _filtered_repeated_parts_scene(
            self.current_preview.viewport_scene,
            include_repeated_parts=not hide_repeated,
        )
        viewport_mesh = build_fracture_viewport_mesh_from_scene(viewport_scene)
        apply_fracture_viewport_mesh(
            self.viewport,
            viewport_mesh,
            scene=viewport_scene,
            frame_camera=frame_camera,
        )
        self.viewport.set_visible_vertex_count_override(None)
        self.viewport_mesh = viewport_mesh
        if not hide_repeated:
            self._full_viewport_mesh = viewport_mesh
        self._update_viewport_summary()

    def _update_viewport_summary(self) -> None:
        if self.viewport_mesh is None:
            return
        notices = (
            issue.message
            for issue in (() if self.current_preview is None else self.current_preview.diagnostics)
            if issue.code in (
                "fracture_manual_cut_snapped",
                "fracture_auto_cut_shifted",
            )
        )
        self.summary_label.setText(
            (
                f"{self.viewport_mesh.piece_count} pieces\n"
                f"{self.viewport_mesh.triangle_count} preview triangles\n"
                f"{self.viewport_mesh.uploaded_triangle_count} uploaded triangles\n"
                f"{self.viewport_mesh.instance_count} repeated instances"
                + "".join(f"\n{notice}" for notice in notices)
            )
        )

    def _toggle_manual_cut_token(self, joint_token: str) -> None:
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
            label.setWordWrap(False)
            button = QPushButton("x", row)
            button.setFixedSize(22, 22)
            button.setMaximumWidth(22)
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


def _set_combo_data(combo: QComboBox, value: str) -> None:
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)


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


def build_fracture_viewport_mesh(
    preview: FracturePreviewResult,
    *,
    include_repeated_parts: bool = True,
) -> FractureViewportMesh:
    scene = preview.viewport_scene
    if scene is None:
        scene = build_fracture_viewport_scene(preview)
    scene = _filtered_repeated_parts_scene(scene, include_repeated_parts=include_repeated_parts)
    return build_fracture_viewport_mesh_from_scene(scene)


def _filtered_repeated_parts_scene(scene: ViewportScene, *, include_repeated_parts: bool) -> ViewportScene:
    if include_repeated_parts:
        return scene
    return replace(
        scene,
        draw_calls=tuple(draw_call for draw_call in scene.draw_calls if draw_call.visibility_group != "repeated_parts"),
    )


def build_fracture_viewport_mesh_from_scene(
    scene: ViewportScene,
    *,
    include_repeated_parts: bool = True,
) -> FractureViewportMesh:
    vertices = array("f")
    draw_sources: list[FractureDrawSource] = []
    draw_calls: list[FractureDrawCall] = []
    logical_triangle_count = 0
    uploaded_triangle_count = 0
    base_vertex_count = 0
    base_triangle_count = 0
    base_uploaded_triangle_count = 0
    base_source_indices: set[int] = set()
    source_by_key: dict[tuple[str, tuple[float, float, float, float]], int] = {}
    batch_by_id = {batch.batch_id: batch for batch in scene.mesh_batches}
    included_draw_calls = tuple(
        draw_call
        for draw_call in scene.draw_calls
        if draw_call.visibility_group != "collision"
        and (include_repeated_parts or draw_call.visibility_group != "repeated_parts")
    )

    def add_source(name: str, source_vertices: array, source_triangle_count: int) -> int:
        source_index = len(draw_sources)
        first_vertex = len(vertices) // FRACTURE_SOURCE_VERTEX_STRIDE
        vertices.extend(source_vertices)
        draw_sources.append(
            FractureDrawSource(
                name=name,
                first_vertex=first_vertex,
                vertex_count=len(source_vertices) // FRACTURE_SOURCE_VERTEX_STRIDE,
                triangle_count=source_triangle_count,
            )
        )
        return source_index

    for scene_draw_call in included_draw_calls:
        batch = batch_by_id.get(scene_draw_call.batch_id)
        if batch is None:
            continue
        color = scene_draw_call.tint or batch.color or Color4(1.0, 1.0, 1.0, 1.0)
        source_key = (batch.batch_id, (float(color.r), float(color.g), float(color.b), float(color.a)))
        source_index = source_by_key.get(source_key)
        if source_index is None:
            source_vertices = array("f")
            source_triangle_count = _append_mesh_triangles(source_vertices, batch.mesh, color=color)
            if source_triangle_count <= 0:
                continue
            source_index = add_source(batch.name, source_vertices, source_triangle_count)
            source_by_key[source_key] = source_index
            uploaded_triangle_count += source_triangle_count
        source = draw_sources[source_index]
        draw_calls.append(
            FractureDrawCall(
                source_index=source_index,
                translate=scene_draw_call.translate,
                orientation=scene_draw_call.orientation,
                scale=scene_draw_call.scale,
                explode_offset=scene_draw_call.explode_direction,
            )
        )
        logical_triangle_count += source.triangle_count
        if scene_draw_call.visibility_group == "base_mesh":
            base_vertex_count += source.vertex_count
            base_triangle_count += source.triangle_count
            if source_index not in base_source_indices:
                base_source_indices.add(source_index)
                base_uploaded_triangle_count += source.triangle_count
    bone_segments = tuple(
        FracturePreviewBoneSegment(
            parent_joint_token=segment.parent_token,
            child_joint_token=segment.child_token,
            parent_position=segment.start,
            child_position=segment.end,
            is_selected_cut=segment.selected,
            color=segment.color,
            selectable=segment.selectable_id is not None,
        )
        for segment in scene.bone_segments
    )
    return FractureViewportMesh(
        name=scene.scene_id,
        vertex_components=vertices,
        triangle_count=logical_triangle_count,
        uploaded_triangle_count=uploaded_triangle_count,
        piece_count=_scene_piece_count(scene),
        instance_count=sum(1 for draw_call in included_draw_calls if draw_call.visibility_group == "repeated_parts"),
        draw_sources=tuple(draw_sources),
        draw_calls=tuple(draw_calls),
        bone_segments=bone_segments,
        base_vertex_count=base_vertex_count,
        base_triangle_count=base_triangle_count,
        base_uploaded_triangle_count=base_uploaded_triangle_count,
    )


def apply_fracture_viewport_mesh(
    viewport: MatcapViewport,
    mesh: FractureViewportMesh,
    *,
    scene: ViewportScene,
    frame_camera: bool = True,
) -> FractureRenderPayload:
    payload, draws = _build_fracture_instanced_render_payload(mesh, scene)
    required_bytes = int(payload.vertex_components.nbytes)
    upload_limit = min(MAX_QT_OPENGL_BUFFER_BYTES, MAX_FRACTURE_PREVIEW_UPLOAD_BYTES)
    if required_bytes > upload_limit:
        raise ValueError(
            f"scene requires {required_bytes} bytes; Fracture Preview safely allows at most "
            f"{upload_limit} bytes per OpenGL upload"
        )
    viewport.set_precomputed_instanced_matcap_scene(
        scene,
        vertices=payload.vertex_components,
        draws=draws,
        min_point=payload.min_point,
        max_point=payload.max_point,
        frame_camera=frame_camera,
    )
    return payload


def _build_fracture_instanced_render_payload(
    mesh: FractureViewportMesh,
    scene: ViewportScene,
) -> tuple[FractureRenderPayload, tuple[MatcapInstanceDraw, ...]]:
    source = np.asarray(mesh.vertex_components, dtype=np.float32).reshape((-1, FRACTURE_SOURCE_VERTEX_STRIDE))
    vertices = np.zeros((len(source), FRACTURE_VERTEX_STRIDE), dtype=np.float32)
    if len(source):
        vertices[:, 0:10] = source[:, 0:10]
        vertices[:, 13:16] = source[:, 0:3]
    draws = tuple(
        MatcapInstanceDraw(
            first_vertex=mesh.draw_sources[draw.source_index].first_vertex,
            vertex_count=mesh.draw_sources[draw.source_index].vertex_count,
            translate=draw.translate,
            orientation=draw.orientation,
            scale=draw.scale,
            explode_offset=draw.explode_offset,
        )
        for draw in mesh.draw_calls
    )
    return (
        FractureRenderPayload(
            vertex_components=vertices.reshape(-1),
            min_point=scene.bounds.min_point,
            max_point=scene.bounds.max_point,
        ),
        draws,
    )


def _scene_piece_count(scene: ViewportScene) -> int:
    piece_ids = {
        draw_call.selectable_id
        for draw_call in scene.draw_calls
        if draw_call.visibility_group == "base_mesh" and draw_call.selectable_id
    }
    return len(piece_ids) if piece_ids else scene.stats.batch_count


def _rotate_positions(q: Quaternion, positions: np.ndarray) -> np.ndarray:
    q_vector = np.array((q.i, q.j, q.k), dtype=np.float32)
    t = 2.0 * np.cross(q_vector, positions)
    return positions + float(q.real) * t + np.cross(q_vector, t)


def _append_mesh_triangles(
    vertices: array,
    mesh: GeometryBuffer,
    *,
    color: Color4,
    translate: Vector3 = Vector3(0.0, 0.0, 0.0),
    orientation: Quaternion = Quaternion(1.0, 0.0, 0.0, 0.0),
    scale: Vector3 = Vector3(1.0, 1.0, 1.0),
) -> int:
    counts = np.asarray(mesh.face_vertex_counts, dtype=np.int64)
    triangle_count = int(np.maximum(counts - 2, 0).sum())
    if triangle_count <= 0:
        return 0
    source_indices = np.asarray(mesh.face_vertex_indices, dtype=np.int64)
    triangle_indices = np.empty((triangle_count, 3), dtype=np.int64)
    triangle_normal_indices = np.empty((triangle_count, 3), dtype=np.int64)
    source_offset = 0
    triangle_offset = 0
    for raw_count in counts:
        count = int(raw_count)
        face_indices = source_indices[source_offset : source_offset + count]
        source_offset += count
        face_triangle_count = max(0, count - 2)
        if face_triangle_count == 0:
            continue
        end = triangle_offset + face_triangle_count
        triangle_indices[triangle_offset:end, 0] = face_indices[0]
        triangle_indices[triangle_offset:end, 1] = face_indices[1:-1]
        triangle_indices[triangle_offset:end, 2] = face_indices[2:]
        face_slots = np.arange(source_offset - count, source_offset, dtype=np.int64)
        triangle_normal_indices[triangle_offset:end, 0] = face_slots[0]
        triangle_normal_indices[triangle_offset:end, 1] = face_slots[1:-1]
        triangle_normal_indices[triangle_offset:end, 2] = face_slots[2:]
        triangle_offset = end

    points = np.asarray(mesh.point_components, dtype=np.float32).reshape((-1, 3))
    transformed = points * np.asarray((scale.x, scale.y, scale.z), dtype=np.float32)
    q = orientation
    q_vector = np.asarray((q.i, q.j, q.k), dtype=np.float32)
    twice_cross = 2.0 * np.cross(q_vector, transformed)
    transformed = transformed + float(q.real) * twice_cross + np.cross(q_vector, twice_cross)
    transformed += np.asarray((translate.x, translate.y, translate.z), dtype=np.float32)

    triangle_points = transformed[triangle_indices]
    normal_components = np.asarray(mesh.normal_components, dtype=np.float32).reshape((-1, 3))
    if len(normal_components) == len(points):
        normals = normal_components[triangle_indices]
    elif len(normal_components) == len(source_indices):
        normals = normal_components[triangle_normal_indices]
    else:
        local_triangles = points[triangle_indices]
        face_normals = np.cross(
            local_triangles[:, 1] - local_triangles[:, 0],
            local_triangles[:, 2] - local_triangles[:, 0],
        )
        point_normals = np.zeros_like(points)
        for corner in range(3):
            np.add.at(point_normals, triangle_indices[:, corner], face_normals)
        point_lengths = np.linalg.norm(point_normals, axis=1)
        point_normals /= np.where(point_lengths > 1e-8, point_lengths, 1.0)[:, None]
        normals = point_normals[triangle_indices]
    normals = normals / np.maximum(np.abs(np.asarray((scale.x, scale.y, scale.z), dtype=np.float32)), 1e-8)
    normals = _rotate_positions(orientation, normals.reshape((-1, 3))).reshape((-1, 3, 3))
    lengths = np.linalg.norm(normals, axis=2)
    normals /= np.where(lengths > 1e-8, lengths, 1.0)[:, :, None]
    normals[lengths <= 1e-8] = np.asarray((0.0, 0.0, 1.0), dtype=np.float32)

    rendered = np.empty((triangle_count, 3, FRACTURE_SOURCE_VERTEX_STRIDE), dtype=np.float32)
    rendered[:, :, 0:3] = triangle_points
    rendered[:, :, 3:6] = normals
    rendered[:, :, 6:10] = np.asarray((color.r, color.g, color.b, color.a), dtype=np.float32)
    vertices.frombytes(rendered.tobytes(order="C"))
    return triangle_count


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
