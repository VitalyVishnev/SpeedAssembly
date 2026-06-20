"""Instanced Geometry Prototype preview dialog."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QPushButton, QHBoxLayout

from ..models import CpuProfile, PrototypeSourceMode
from ..part_preview_service import PartPreviewDisplayMode, PartPrototypePreviewRequest, PartPrototypePreviewSettings
from .part_source_controls import PartSourceMaterialEditor, PartSourceMaterialValue
from .preview_shell import PreviewShellDialog
from .viewport import MatcapViewport


class PartPrototypePreviewDialog(PreviewShellDialog):
    def __init__(
        self,
        *,
        input_path: str,
        value: PartSourceMaterialValue,
        cpu_profile: CpuProfile,
        fbx_cache_max_bytes: int,
        fbx_cache_max_age_seconds: int,
        browse_fbx=None,
        inspect_fbx_slots=None,
        on_apply=None,
        on_preview_requested=None,
        parent=None,
    ) -> None:
        super().__init__(title=f"Prototype Preview - {value.source_name or value.source_key}", parent=parent)
        self._input_path = input_path
        self._cpu_profile = cpu_profile
        self._fbx_cache_max_bytes = int(fbx_cache_max_bytes)
        self._fbx_cache_max_age_seconds = int(fbx_cache_max_age_seconds)
        self._on_apply = on_apply or (lambda value: None)
        self._on_preview_requested = on_preview_requested or (lambda request, settings: None)
        self._pending_preview = False

        self.viewport = MatcapViewport(self)
        self.set_viewport_widget(self.viewport)

        settings_panel, settings_layout = self.create_settings_panel()
        title = QLabel(value.source_name or value.source_key, settings_panel)
        title.setStyleSheet("font-weight: 700;")
        settings_layout.addWidget(title)
        self.editor = PartSourceMaterialEditor(
            value=value,
            browse_fbx=browse_fbx,
            inspect_fbx_slots=inspect_fbx_slots,
            parent=settings_panel,
        )
        settings_layout.addWidget(self.editor)
        self.status_label = QLabel("", settings_panel)
        self.status_label.setWordWrap(True)
        settings_layout.addWidget(self.status_label)

        actions = QHBoxLayout()
        self.apply_button = QPushButton("Apply", settings_panel)
        self.close_button = QPushButton("Close", settings_panel)
        actions.addWidget(self.apply_button)
        actions.addWidget(self.close_button)
        settings_layout.addLayout(actions)
        settings_layout.addStretch(1)

        self.editor.previewAffectingChanged.connect(self.schedule_preview)
        self.editor.simplificationReleased.connect(self.schedule_preview)
        self.apply_button.clicked.connect(self._apply)
        self.close_button.clicked.connect(self.close)
        QTimer.singleShot(0, self.schedule_preview)

    def current_value(self) -> PartSourceMaterialValue:
        return self.editor.value()

    def schedule_preview(self) -> None:
        if self._pending_preview:
            return
        self._pending_preview = True
        QTimer.singleShot(0, self._regenerate_preview)

    def _regenerate_preview(self) -> None:
        self._pending_preview = False
        value = self.editor.value()
        if value.source_mode == PrototypeSourceMode.UNREAL_ASSET:
            self.viewport.set_mesh(None)
            self.set_viewport_visible(False)
            self.editor.set_triangle_count_text("")
            self.status_label.setText("Unreal Path mode has no local preview geometry.")
            return
        self.set_viewport_visible(True)
        self.set_loading("Generating preview...")
        self._on_preview_requested(self._preview_request(value), PartPrototypePreviewSettings(display_mode=value.display_mode))

    def set_loading(self, message: str) -> None:
        self.status_label.setText(message)

    def set_error(self, message: str) -> None:
        self.viewport.set_mesh(None)
        self.status_label.setText(message)
        self.editor.set_triangle_count_text("Preview failed.")

    def set_preview(self, result) -> None:
        value = self.editor.value()
        if result.mesh is None:
            self.viewport.set_mesh(None)
            self.status_label.setText("No inline prototype mesh is available.")
            self.editor.set_triangle_count_text("")
            return
        tint_alpha = 0.0
        if value.display_mode == PartPreviewDisplayMode.VERTEX_COLORS:
            tint_alpha = 0.8
        elif value.display_mode == PartPreviewDisplayMode.MATERIAL_COLORS:
            tint_alpha = 0.7
        self.viewport.set_matcap_tint_strength(1.0 if tint_alpha > 0.0 else 0.0)
        self.viewport.set_mesh(result.mesh, tint_alpha=tint_alpha)
        self.editor.set_material_colors(result.material_colors)
        self.editor.set_triangle_prediction_base(result.source_section_triangle_counts)
        self.status_label.setText("")

    def _preview_request(self, value: PartSourceMaterialValue) -> PartPrototypePreviewRequest:
        return PartPrototypePreviewRequest(
            input_path=self._input_path,
            source_key=value.source_key,
            source_name=value.source_name,
            prototype_source_config=value.to_prototype_source_config(),
            cpu_profile=self._cpu_profile,
            fbx_cache_max_bytes=self._fbx_cache_max_bytes,
            fbx_cache_max_age_seconds=self._fbx_cache_max_age_seconds,
        )

    def _apply(self) -> None:
        self._on_apply(self.editor.value())
