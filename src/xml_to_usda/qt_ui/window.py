"""Frameless PySide6 shell for the primary operator UI.

Layer: UI.

This shell keeps the glassmorphism direction isolated from the retired Tk
GUI while reusing the same conversion, discovery, wind, and settings services.
"""

from __future__ import annotations

import os
import time
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSignalBlocker, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QCursor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QLayout,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QApplication,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..diagnostics_bundle import build_diagnostics_bundle_request, export_diagnostics_bundle
from ..fbx_payload_cache import (
    FbxPayloadCacheSummary,
    clear_fbx_payload_cache,
    summarize_fbx_payload_cache,
    sweep_fbx_payload_cache,
)
from ..gui_formatters import format_wind_group_summary, format_wind_json_result
from ..models import CleanupPolicy, ConversionMode, ConversionRequest, OutputMode
from ..proxy_mesh_service import (
    ProxyMeshResult,
    ProxyMeshSettings,
    ProxyMeshSourceRequest,
    prepare_proxy_mesh_source_request,
)
from ..fracture_export_service import FractureExportRequest
from ..fracture_preview_service import (
    FracturePreviewSettings,
    FracturePreviewSourceRequest,
    prepare_fracture_preview_source_request,
)
from ..runtime_paths import resolve_runtime_paths, sweep_stale_job_workspaces
from ..settings_service import (
    FACTORY_DEFAULT_PRESET_NAME,
    factory_default_preset,
    load_gui_preset,
    save_gui_preset,
    sorted_gui_presets,
)
from .adjust_ui import AdjustUiDialog
from .background_jobs import QtBackgroundJobsController
from .dependencies import QtUiDependencies
from .dialogs import HelpDeckDialog, SupportDialog, TextDialog
from .operator_state import (
    SETTINGS_DIR,
    SETTINGS_PATH,
    apply_preset_to_operator_state,
    load_base_material_records,
    load_operator_state,
    load_part_source_records,
    load_wind_group_records,
    preset_from_operator_state,
    save_nested_input_settings,
)
from .panels import GeometryTabPanel, MaterialsTabPanel, WindTabPanel
from .persistence import (
    UiShellState,
    default_ui_theme_export_path,
    default_ui_theme_overrides_path,
    save_ui_shell_state,
    save_ui_theme_overrides,
)
from .fracture_preview import FracturePreviewDialog
from .proxy_preview import ProxyPreviewDialog
from .theme import (
    ResolvedTheme,
    ThemeOverrides,
    ThemeSpec,
    build_stylesheet,
    compute_screen_scale,
    compute_cover_source_rect,
    load_bundled_theme,
    resolve_theme_asset,
    scale_theme_for_runtime,
    theme_to_payload,
    write_theme_payload,
)
from .trace import QtTraceLogger, trace_path_for_settings_dir


@dataclass(frozen=True)
class WindowAssets:
    background: QPixmap
    panel_blur: QPixmap
    noise: QPixmap


CONVERSION_MODES: tuple[tuple[str, str, bool], ...] = (
    # The mode switch is intentionally ahead of backend support so the future
    # shell layout does not need another structural change when the additional
    # assembly/parts modes land. Unsupported entries stay visible but disabled
    # until their application-layer contracts exist.
    ("skeletal_assembly", "Skeletal Assembly", True),
    ("skeletal_parts", "Skeletal Parts", True),
    ("static_assembly", "Static Assembly", True),
    ("static_parts", "Static Parts", False),
)


def _format_bytes(value: int) -> str:
    amount = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024.0 or unit == "TB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024.0
    return f"{int(value)} B"


def _widget_trace_name(widget: QWidget) -> str:
    text = ""
    if hasattr(widget, "text"):
        try:
            text = str(widget.text()).replace("\n", " ").strip()
        except RuntimeError:
            text = ""
    if text:
        return text
    object_name = widget.objectName()
    if object_name:
        return object_name
    return type(widget).__name__


class PathLineEdit(QLineEdit):
    pathChanged = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.textEdited.connect(self._handle_text_edited)

    def text(self) -> str:  # type: ignore[override]
        return self._full_text

    def setText(self, text: str) -> None:  # type: ignore[override]
        self._full_text = text or ""
        self._sync_visible_text(emit_signal=True)

    def focusInEvent(self, event) -> None:  # type: ignore[override]
        self._sync_visible_text(emit_signal=False)
        super().focusInEvent(event)
        if self._full_text:
            QTimer.singleShot(0, self.selectAll)

    def focusOutEvent(self, event) -> None:  # type: ignore[override]
        self._full_text = super().text()
        super().focusOutEvent(event)
        self._sync_visible_text(emit_signal=False)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if not self.hasFocus():
            self._sync_visible_text(emit_signal=False)

    def _handle_text_edited(self, text: str) -> None:
        self._full_text = text
        self.pathChanged.emit(self._full_text)

    def _sync_visible_text(self, *, emit_signal: bool) -> None:
        display_text = self._full_text if self.hasFocus() else self._compact_path(self._full_text)
        with QSignalBlocker(self):
            super().setText(display_text)
        if emit_signal:
            self.pathChanged.emit(self._full_text)

    @staticmethod
    def _compact_path(text: str) -> str:
        # The unfocused preview intentionally shows only the tail of the path so
        # operators can scan the last folder + file name at a glance while the
        # focused state still exposes the full path for copy/edit workflows.
        normalized = text.strip().replace("/", "\\")
        if not normalized:
            return ""
        parts = [part for part in normalized.split("\\") if part]
        if len(parts) <= 1:
            return parts[0] if parts else normalized
        return f"...\\{parts[-2]}\\{parts[-1]}"


class TitleBar(QFrame):
    def __init__(self, window: "MainWindow", theme: ResolvedTheme) -> None:
        super().__init__(window)
        self._window = window
        self._drag_origin: QPoint | None = None
        self.setObjectName("TitleBar")

        self._layout = QHBoxLayout(self)

        self.help_button = QPushButton("How to use", self)
        self.help_button.setObjectName("HelpTitleButton")
        self.help_button.clicked.connect(window.open_help_dialog)
        self._layout.addWidget(self.help_button, 0, Qt.AlignmentFlag.AlignLeft)

        self.log_button = QPushButton("LOG", self)
        self.log_button.setObjectName("TitlePillButton")
        self.log_button.clicked.connect(window.open_log_dialog)
        self._layout.addWidget(self.log_button, 0, Qt.AlignmentFlag.AlignLeft)

        self.support_button = QPushButton("Support", self)
        self.support_button.setObjectName("TitlePillButton")
        self.support_button.clicked.connect(window.open_support_dialog)
        self._layout.addWidget(self.support_button, 0, Qt.AlignmentFlag.AlignLeft)

        self.adjust_button = QPushButton("Adjust UI", self)
        self.adjust_button.setObjectName("AdjustUiButton")
        self.adjust_button.clicked.connect(window.open_adjust_ui_dialog)
        self._layout.addWidget(self.adjust_button, 0, Qt.AlignmentFlag.AlignLeft)

        self.preset_host = QWidget(self)
        self.preset_host.setObjectName("TitlePresetHost")
        self.preset_layout = QHBoxLayout(self.preset_host)
        self.preset_layout.setContentsMargins(0, 0, 0, 0)
        self.preset_layout.setSpacing(0)
        self._layout.addWidget(self.preset_host, 0, Qt.AlignmentFlag.AlignLeft)

        self.settings_button = QPushButton("⚙", self)
        self.settings_button.setObjectName("GlobalSettingsButton")
        self.settings_button.setToolTip("Global settings")
        self.settings_button.clicked.connect(window.open_global_settings_dialog)
        self._layout.addWidget(self.settings_button)
        self._layout.addStretch(1)

        self.minimize_button = QPushButton("\u2212", self)
        self.minimize_button.setObjectName("WindowButton")
        self.minimize_button.clicked.connect(window.showMinimized)
        self._layout.addWidget(self.minimize_button)

        self.maximize_button = QPushButton("\u25a1", self)
        self.maximize_button.setObjectName("WindowButton")
        self.maximize_button.clicked.connect(window.toggle_maximized)
        self._layout.addWidget(self.maximize_button)

        self.close_button = QPushButton("\u00d7", self)
        self.close_button.setObjectName("CloseWindowButton")
        self.close_button.clicked.connect(window.close)
        self._layout.addWidget(self.close_button)

        self.apply_theme(theme)

    def apply_theme(self, theme: ResolvedTheme) -> None:
        spacing = theme.spacing["control_gap"]
        edge_padding = max(spacing, 18)
        self._layout.setContentsMargins(edge_padding, 2, edge_padding, 2)
        self._layout.setSpacing(max(8, spacing - 2))
        titlebar_height = int(theme.control_heights["titlebar"])
        button_size = int(theme.chrome.get("window_button_size", 22))
        pill_height = max(
            int(theme.chrome.get("title_pill_height", 24)),
            self._minimum_text_button_height(
                self.help_button,
                self.log_button,
                self.support_button,
            ),
        )
        adjust_height = max(
            int(theme.chrome.get("adjust_ui_button_height", pill_height)),
            self._minimum_text_button_height(self.adjust_button),
        )
        self.setFixedHeight(max(24, titlebar_height + 4, pill_height + 8, adjust_height + 8, button_size + 8))
        self.help_button.setFixedWidth(
            max(
                int(theme.chrome.get("title_pill_width", 78)) + 28,
                self._minimum_text_button_width(self.help_button),
            )
        )
        self.help_button.setFixedHeight(pill_height)
        self.log_button.setFixedWidth(int(theme.chrome.get("title_pill_width", 78)))
        self.log_button.setFixedHeight(pill_height)
        self.support_button.setFixedWidth(int(theme.chrome.get("title_pill_width", 78)) + 20)
        self.support_button.setFixedHeight(pill_height)
        self.adjust_button.setFixedWidth(int(theme.chrome.get("adjust_ui_button_width", 104)))
        self.adjust_button.setFixedHeight(adjust_height)
        self.preset_host.setFixedHeight(max(button_size, pill_height, adjust_height))
        self.settings_button.setFixedSize(button_size, button_size)
        for button in (self.minimize_button, self.maximize_button, self.close_button):
            button.setFixedSize(button_size, button_size)

    @staticmethod
    def _minimum_text_button_height(*buttons: QPushButton) -> int:
        for button in buttons:
            button.ensurePolished()
        return max((button.fontMetrics().height() + 6 for button in buttons), default=0)

    @staticmethod
    def _minimum_text_button_width(button: QPushButton) -> int:
        button.ensurePolished()
        return button.fontMetrics().horizontalAdvance(button.text()) + 32

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._window.toggle_maximized()
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and not self._window.isMaximized():
            window_point = self.mapTo(self._window, event.position().toPoint())
            edges = self._window._hit_test_edges(window_point)
            if edges != Qt.Edge(0) and self._window.windowHandle() is not None:
                self._window.windowHandle().startSystemResize(edges)
                event.accept()
                return
            self._drag_origin = event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        window_point = self.mapTo(self._window, event.position().toPoint())
        if self._drag_origin is None:
            self._window._update_cursor_for_position(window_point)
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton and not self._window.isMaximized():
            self._window.move(event.globalPosition().toPoint() - self._drag_origin)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self._drag_origin = None
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        if not self._window.isMaximized():
            self._window.unsetCursor()
        super().leaveEvent(event)
class GlassPanel(QFrame):
    def __init__(
        self,
        theme: ResolvedTheme,
        panel_pixmap: QPixmap,
        noise_pixmap: QPixmap,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        shadow = QGraphicsDropShadowEffect(self)
        self.setGraphicsEffect(shadow)
        self._theme = theme
        self._panel_pixmap = panel_pixmap
        self._noise_pixmap = noise_pixmap
        self._noise_tile = QPixmap()
        self.set_theme(theme, panel_pixmap, noise_pixmap)

    def set_theme(self, theme: ResolvedTheme, panel_pixmap: QPixmap, noise_pixmap: QPixmap) -> None:
        self._theme = theme
        self._panel_pixmap = panel_pixmap
        self._noise_pixmap = noise_pixmap
        effect = self.graphicsEffect()
        if isinstance(effect, QGraphicsDropShadowEffect):
            effect.setBlurRadius(int(theme.effects.get("panel_shadow_blur", 22)))
            effect.setColor(QColor(0, 0, 0, int(theme.effects.get("panel_shadow_alpha", 68))))
            effect.setOffset(0, int(theme.effects.get("panel_shadow_offset_y", 6)))
        self._noise_tile = self._build_noise_tile()
        self.update()

    def _build_noise_tile(self) -> QPixmap:
        if self._noise_pixmap.isNull():
            return QPixmap()
        noise_scale = max(0.25, float(self._theme.glass.get("noise_scale", 1.0)))
        target_width = max(8, int(round(self._noise_pixmap.width() * noise_scale)))
        target_height = max(8, int(round(self._noise_pixmap.height() * noise_scale)))
        return self._noise_pixmap.scaled(
            target_width,
            target_height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        rect = QRectF(self.rect())
        border_rect = rect.adjusted(0.5, 0.5, -0.5, -0.5)
        radius = self._theme.radii["panel"]

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.setClipPath(path)
        owner_window = self.window()
        if isinstance(owner_window, MainWindow):
            panel_rect = QRect(self.mapTo(owner_window, QPoint(0, 0)), self.size())
            panel_background = owner_window._panel_background_slice(panel_rect)
        else:
            panel_background = None
        if panel_background is not None and not panel_background.isNull():
            painter.drawPixmap(self.rect(), panel_background)
        else:
            _draw_cover_pixmap(painter, self.rect(), self._panel_pixmap)

        tint = QColor(str(self._theme.glass["tint_color"]))
        tint.setAlphaF(tint.alphaF() * float(self._theme.glass.get("tint_opacity", 0.22)))
        painter.fillPath(path, tint)

        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        top_height = max(0.01, min(1.0, float(self._theme.glass.get("light_gradient_height", 0.18))))
        dark_height = max(0.01, min(1.0, float(self._theme.glass.get("dark_gradient_height", 0.13))))
        dark_start = max(top_height, 1.0 - dark_height)
        gradient.setColorAt(0.0, QColor(255, 255, 255, int(round(255 * float(self._theme.glass.get("light_gradient_opacity", 0.11))))))
        gradient.setColorAt(top_height, QColor(255, 255, 255, int(round(255 * float(self._theme.glass.get("light_gradient_mid_opacity", 0.04))))))
        gradient.setColorAt(dark_start, QColor(255, 255, 255, 0))
        gradient.setColorAt(1.0, QColor(0, 0, 0, int(round(255 * float(self._theme.glass.get("dark_gradient_opacity", 0.07))))))
        painter.fillPath(path, gradient)

        if not self._noise_tile.isNull() and float(self._theme.glass.get("noise_opacity", 0.0)) > 0.0:
            painter.save()
            painter.setClipPath(path)
            painter.setOpacity(float(self._theme.glass.get("noise_opacity", 0.0)))
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Overlay)
            painter.drawTiledPixmap(self.rect(), self._noise_tile)
            painter.restore()

        painter.setClipping(False)
        border_path = QPainterPath()
        border_path.addRoundedRect(border_rect, radius, radius)
        border_color = QColor(str(self._theme.glass["border_color"]))
        border_color.setAlphaF(border_color.alphaF() * float(self._theme.glass.get("border_opacity", 0.45)))
        pen = QPen(border_color)
        pen.setWidthF(float(self._theme.border_widths.get("panel", 1)))
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(border_path)


class GlobalSettingsDialog(QDialog):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._window = window
        self.setObjectName("GlobalSettingsDialog")
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel("FBX Cache", self)
        title.setStyleSheet("font-weight: 700;")
        layout.addWidget(title)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        self.path_label = QLabel("", self)
        self.path_label.setWordWrap(True)
        self.size_label = QLabel("", self)
        self.entry_label = QLabel("", self)
        form.addRow("Path", self.path_label)
        form.addRow("Size", self.size_label)
        form.addRow("Entries", self.entry_label)
        layout.addLayout(form)

        controls = QFormLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)
        self.max_size_spin = QSpinBox(self)
        self.max_size_spin.setObjectName("FbxCacheMaxSizeSpin")
        self.max_size_spin.setRange(1, 1024)
        self.max_size_spin.setSuffix(" GB")
        self.max_age_spin = QSpinBox(self)
        self.max_age_spin.setObjectName("FbxCacheMaxAgeSpin")
        self.max_age_spin.setRange(1, 3650)
        self.max_age_spin.setSuffix(" days")
        self.debug_trace_checkbox = QCheckBox("Debug Trace", self)
        self.debug_trace_checkbox.setObjectName("DebugTraceCheckbox")
        controls.addRow("Max size", self.max_size_spin)
        controls.addRow("Max age", self.max_age_spin)
        controls.addRow("Diagnostics", self.debug_trace_checkbox)
        layout.addLayout(controls)

        self.warning_label = QLabel("", self)
        self.warning_label.setObjectName("MutedLabel")
        self.warning_label.setWordWrap(True)
        layout.addWidget(self.warning_label)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        self.apply_button = QPushButton("Apply", self)
        self.refresh_button = QPushButton("Refresh", self)
        self.clear_button = QPushButton("Clear FBX cache", self)
        self.apply_button.clicked.connect(self._apply_clicked)
        self.refresh_button.clicked.connect(self._refresh_clicked)
        self.clear_button.clicked.connect(self._clear_clicked)
        button_row.addWidget(self.apply_button)
        button_row.addWidget(self.refresh_button)
        button_row.addWidget(self.clear_button)
        layout.addLayout(button_row)

        self.sync_from_settings()

    def sync_from_settings(self) -> None:
        snapshot = self._window._operator_snapshot
        self.max_size_spin.setValue(snapshot.fbx_cache_max_size_gb)
        self.max_age_spin.setValue(snapshot.fbx_cache_max_age_days)
        self.debug_trace_checkbox.setChecked(bool(snapshot.debug_trace_enabled))
        self.path_label.setText(str(self._window._fbx_payload_cache_root()))

    def set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.max_size_spin,
            self.max_age_spin,
            self.debug_trace_checkbox,
            self.apply_button,
            self.refresh_button,
            self.clear_button,
        ):
            widget.setEnabled(enabled)

    def refresh_cache_summary(self) -> None:
        summary = self._window._summarize_fbx_cache()
        self._set_cache_summary(summary)

    def _apply_clicked(self) -> None:
        summary = self._window._apply_fbx_cache_settings(
            max_size_gb=self.max_size_spin.value(),
            max_age_days=self.max_age_spin.value(),
            debug_trace_enabled=self.debug_trace_checkbox.isChecked(),
        )
        self._set_cache_summary(summary)

    def _refresh_clicked(self) -> None:
        self._set_cache_summary(self._window._sweep_fbx_cache())

    def _clear_clicked(self) -> None:
        before = self._window._summarize_fbx_cache()
        answer = QMessageBox.question(
            self,
            "Clear FBX cache",
            (
                "Delete FBX payload cache?\n\n"
                f"Entries: {before.entry_count}\n"
                f"Size: {_format_bytes(before.total_bytes)}"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._set_cache_summary(self._window._clear_fbx_cache())

    def _set_cache_summary(self, summary: FbxPayloadCacheSummary) -> None:
        self.size_label.setText(_format_bytes(summary.total_bytes))
        self.entry_label.setText(str(summary.entry_count))
        if summary.failed_paths:
            self.warning_label.setText(
                "Warning: some cache files could not be updated. Details were written to the log."
            )
        else:
            self.warning_label.setText("")


class MainWindow(QWidget):
    ASYNC_WIND_REFRESH_THRESHOLD_BYTES = 5 * 1024 * 1024
    ASYNC_CONVERSION_THRESHOLD_BYTES = 5 * 1024 * 1024
    EDGE_RESIZE_MARGIN = 14
    _DWMWA_WINDOW_CORNER_PREFERENCE = 33
    _DWMWCP_DONOTROUND = 1

    def __init__(
        self,
        theme: ResolvedTheme,
        state: UiShellState,
        *,
        dependencies: QtUiDependencies,
        state_path=None,
        operator_settings_path=None,
        base_theme: ThemeSpec | None = None,
        theme_overrides: ThemeOverrides | None = None,
        theme_overrides_path=None,
        build_signature: str | None = None,
    ) -> None:
        super().__init__()
        self._design_theme = theme
        self._ui_scale = self._compute_current_screen_scale()
        self._theme = scale_theme_for_runtime(theme, self._ui_scale)
        self._base_theme = base_theme if base_theme is not None else load_bundled_theme(theme.name)
        self._theme_overrides = theme_overrides if theme_overrides is not None else ThemeOverrides(theme.name, {})
        self._theme_overrides_path = (
            Path(theme_overrides_path) if theme_overrides_path is not None else default_ui_theme_overrides_path()
        )
        self._theme_export_path = default_ui_theme_export_path()
        self._state = state
        self._build_signature = build_signature or state.help_prompt_build_signature
        self._deps = dependencies
        self._state_path = state_path
        self._operator_settings_path = Path(operator_settings_path) if operator_settings_path is not None else SETTINGS_PATH
        self._assets = self._load_window_assets(self._design_theme)
        self._native_corner_preference_applied = False
        self._screen_change_connected = False
        self._restore_geometry = QRect(state.x, state.y, state.width, state.height)
        self._active_resize_edges = Qt.Edge(0)
        self._auto_output_path: str | None = None
        self._persistence_suspended = False
        self._preset_selector_suspended = False
        self._pending_generate_after_refresh = False
        self._current_dynamic_wind = None
        self._conversion_running = False
        self._wind_refresh_running = False
        self._wind_json_running = False
        self._log_text = ""
        self._log_dialog: TextDialog | None = None
        self._help_dialog: HelpDeckDialog | None = None
        self._support_dialog: SupportDialog | None = None
        self._adjust_ui_dialog: AdjustUiDialog | None = None
        self._global_settings_dialog: GlobalSettingsDialog | None = None
        self._fracture_preview_dialog: FracturePreviewDialog | None = None
        self._proxy_preview_dialog: ProxyPreviewDialog | None = None
        self._proxy_mesh_settings = ProxyMeshSettings()
        self._fracture_preview_settings = FracturePreviewSettings()
        self._proxy_mesh_preview_result: ProxyMeshResult | None = None
        self._proxy_mesh_preview_input_path = ""

        self._operator_state, self._operator_snapshot = load_operator_state(
            self._deps,
            settings_path=self._operator_settings_path,
        )
        self._proxy_mesh_settings = self._operator_snapshot.proxy_mesh_settings
        self._conversion_mode = self._operator_state.conversion_mode.value
        self._runtime_paths = resolve_runtime_paths(
            settings_dir=self._operator_settings_path.parent,
            settings_path=self._operator_settings_path,
        )
        self._trace_logger = QtTraceLogger(
            trace_path_for_settings_dir(self._runtime_paths.settings_dir),
            debug_enabled=self._operator_snapshot.debug_trace_enabled,
        )
        self._trace(
            "app.start",
            message="Qt shell startup",
            data={
                "debug_trace_enabled": self._operator_snapshot.debug_trace_enabled,
                "settings_path": str(self._operator_settings_path),
            },
            debug_data={
                "runtime_settings_dir": str(self._runtime_paths.settings_dir),
                "runtime_cache_root": str(self._runtime_paths.cache_root),
            },
        )
        self._runtime_cleanup_summary = sweep_stale_job_workspaces(self._runtime_paths)
        self._fbx_cache_startup_summary = self._sweep_fbx_cache()

        self._settings_save_timer = QTimer(self)
        self._settings_save_timer.setSingleShot(True)
        self._settings_save_timer.setInterval(150)
        self._settings_save_timer.timeout.connect(self._save_operator_state)
        self._source_refresh_timer = QTimer(self)
        self._source_refresh_timer.setSingleShot(True)
        self._source_refresh_timer.setInterval(200)
        self._source_refresh_timer.timeout.connect(self.refresh_wind_groups)

        self._background_jobs = QtBackgroundJobsController(
            self,
            deps=self._deps,
            runtime_paths=self._runtime_paths,
        )

        self.setWindowTitle("XML to USDA Converter")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StaticContents, True)
        self.setMouseTracking(True)
        self.setMinimumSize(QSize(1160, 780))
        self.setStyleSheet(build_stylesheet(self._theme))

        self._build_layout()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self._install_resize_event_filters()
        self._apply_saved_state()
        self._apply_help_prompt_state()
        self._apply_operator_state_to_widgets()
        self._apply_saved_active_tab()
        self._set_log(self._startup_log_text())
        self._apply_runtime_cleanup_summary()
        self._apply_fbx_cache_startup_summary()
        self._reload_input_dependent_tabs()
        self._refresh_state_cards()
        self._update_action_state()
        self._update_window_shape()
        self._position_help_callout()

    def _build_layout(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._outer_layout = outer

        self.title_bar = TitleBar(self, self._theme)
        outer.addWidget(self.title_bar, 0)

        body = QWidget(self)
        self._body_widget = body
        body_layout = QVBoxLayout(body)
        self._body_layout = body_layout
        body_layout.addStretch(1)

        self.panel = GlassPanel(self._theme, self._assets.panel_blur, self._assets.noise, self)
        panel_layout = QVBoxLayout(self.panel)
        self._panel_layout = panel_layout
        panel_layout.addLayout(self._build_top_rows())
        panel_layout.addLayout(self._build_content_rows())
        body_layout.addWidget(self.panel, 0, Qt.AlignmentFlag.AlignCenter)
        body_layout.addStretch(1)
        self._apply_theme_to_layout()
        self._update_panel_metrics()

        outer.addWidget(body, 1)
        self._build_help_callout()

    def _build_help_callout(self) -> None:
        self.help_callout = QFrame(
            self,
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.help_callout.setObjectName("TutorialCallout")
        self.help_callout.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.help_callout.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.help_callout.setFixedWidth(360)
        layout = QVBoxLayout(self.help_callout)
        layout.setContentsMargins(16, 14, 14, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        self.help_callout_title = QLabel("Start here for the tutorial", self.help_callout)
        self.help_callout_title.setObjectName("TutorialCalloutTitle")
        self.help_callout_title.setWordWrap(True)
        self.help_callout_dismiss_button = QPushButton("x", self.help_callout)
        self.help_callout_dismiss_button.setObjectName("TutorialCalloutCloseButton")
        self.help_callout_dismiss_button.setText("\u00d7")
        self.help_callout_dismiss_button.clicked.connect(self.dismiss_help_prompt)
        header.addWidget(self.help_callout_title, 1)
        header.addWidget(self.help_callout_dismiss_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        self.help_callout_body = QLabel("Open How to use for the core conversion workflow.", self.help_callout)
        self.help_callout_body.setObjectName("TutorialCalloutBody")
        self.help_callout_body.setWordWrap(True)
        layout.addWidget(self.help_callout_body)
        self.help_callout.adjustSize()

    def _install_resize_event_filters(self) -> None:
        self.installEventFilter(self)
        self.title_bar.installEventFilter(self)
        self._body_widget.installEventFilter(self)
        self.setMouseTracking(True)
        self.title_bar.setMouseTracking(True)
        self._body_widget.setMouseTracking(True)
        for child in self.title_bar.findChildren(QWidget):
            child.installEventFilter(self)
            child.setMouseTracking(True)

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if (
            event.type() == QEvent.Type.MouseButtonRelease
            and isinstance(watched, (QPushButton, QToolButton))
            and watched.window() is self
        ):
            self._trace(
                "ui.action",
                action="button.click",
                widget=_widget_trace_name(watched),
                data={"enabled": watched.isEnabled()},
            )
        if isinstance(watched, QWidget) and watched.window() is not self:
            return super().eventFilter(watched, event)
        if self.isMaximized():
            return super().eventFilter(watched, event)

        if isinstance(watched, QWidget) and event.type() in {
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonDblClick,
        }:
            event_position = event.position().toPoint()
            window_position = event_position if watched is self else watched.mapTo(self, event_position)
            edges = self._hit_test_edges(window_position)
            if event.type() == QEvent.Type.MouseMove:
                self._update_cursor_for_position(window_position)
            elif (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
                and edges != Qt.Edge(0)
                and self.windowHandle() is not None
            ):
                self.windowHandle().startSystemResize(edges)
                return True

        if event.type() == QEvent.Type.Leave and watched in {self, self.title_bar, self._body_widget}:
            self.unsetCursor()

        return super().eventFilter(watched, event)

    def _build_top_rows(self):
        spacing = self._theme.spacing["control_gap"]
        layout = QGridLayout()
        self._top_rows_layout = layout
        layout.setHorizontalSpacing(spacing)

        self.source_button = QPushButton("Input XML", self)
        self.source_button.setObjectName("FileButton")
        self.source_button.clicked.connect(self.browse_input)
        self.output_button = QPushButton("Output USDA", self)
        self.output_button.setObjectName("FileButton")
        self.output_button.clicked.connect(self.browse_output)

        self.source_input = PathLineEdit(self)
        self.source_input.setPlaceholderText("Source XML path")
        self.source_input.pathChanged.connect(self._handle_source_text_changed)

        self.output_input = PathLineEdit(self)
        self.output_input.setPlaceholderText("Output USDA path")
        self.output_input.pathChanged.connect(self._handle_output_text_changed)

        self.preset_combo = QComboBox(self.title_bar.preset_host)
        self.preset_combo.setObjectName("TitlePresetCombo")
        self.preset_combo.currentIndexChanged.connect(self._handle_preset_selected)
        self.preset_menu_button = QToolButton(self.title_bar.preset_host)
        self.preset_menu_button.setObjectName("TitlePresetMenuButton")
        self.preset_menu_button.setText("...")
        self.preset_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.preset_menu_button.setMenu(self._build_preset_menu())
        self.title_bar.preset_layout.addWidget(self.preset_combo, 1)
        self.title_bar.preset_layout.addWidget(self.preset_menu_button, 0)
        self._refresh_preset_selector()

        # Convert/Cancel intentionally lives on one shared button so the action
        # column stays compact. The gear segment is a separate future-facing mode
        # selector, not a second execute button.
        self.convert_button = QPushButton("Convert to USDA", self)
        self.convert_button.setObjectName("SplitActionMainButton")
        self.convert_button.clicked.connect(self._handle_convert_button_clicked)
        self.convert_mode_button = QToolButton(self)
        self.convert_mode_button.setObjectName("SplitActionMenuButton")
        self.convert_mode_button.setText("⚙")
        self.convert_mode_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.convert_mode_button.setMenu(self._build_conversion_mode_menu())
        self.convert_action_divider = QFrame(self)
        self.convert_action_divider.setObjectName("SplitActionDivider")
        self.convert_action_frame = QFrame(self)
        self.convert_action_frame.setObjectName("SplitActionFrame")
        convert_action_layout = QHBoxLayout(self.convert_action_frame)
        convert_action_layout.setContentsMargins(0, 0, 0, 0)
        convert_action_layout.setSpacing(0)
        convert_action_layout.addWidget(self.convert_button, 1)
        convert_action_layout.addWidget(self.convert_action_divider, 0)
        convert_action_layout.addWidget(self.convert_mode_button, 0)
        self.generate_button = QPushButton("Generate\nWind JSON", self)
        self.generate_button.setObjectName("GenerateWindButton")
        self.generate_button.clicked.connect(self.run_generate_wind_json)
        self.generate_proxy_button = QPushButton("Generate\nProxy Mesh", self)
        self.generate_proxy_button.setObjectName("GenerateProxyButton")
        self.generate_proxy_button.clicked.connect(self.run_generate_proxy_mesh)
        self._action_buttons = [
            self.generate_button,
            self.generate_proxy_button,
        ]

        self.generate_action_frame = QFrame(self)
        self.generate_action_frame.setObjectName("SplitActionFrame")
        generate_action_layout = QHBoxLayout(self.generate_action_frame)
        generate_action_layout.setContentsMargins(0, 0, 0, 0)
        generate_action_layout.setSpacing(0)
        generate_action_layout.addWidget(self.generate_button, 1)
        self.generate_action_divider = QFrame(self.generate_action_frame)
        self.generate_action_divider.setObjectName("GenerateActionDivider")
        generate_action_layout.addWidget(self.generate_action_divider, 0)
        generate_action_layout.addWidget(self.generate_proxy_button, 1)
        generate_action_layout.setStretch(0, 1)
        generate_action_layout.setStretch(2, 1)

        right_column = QVBoxLayout()
        self._action_column_layout = right_column
        right_column.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        right_column.setSpacing(max(6, spacing - 4))
        right_column.addWidget(self.convert_action_frame)
        right_column.addWidget(self.generate_action_frame)
        right_column.addStretch(1)

        layout.addWidget(self.source_button, 0, 0)
        layout.addWidget(self.source_input, 0, 1)
        layout.addLayout(right_column, 0, 2, 2, 1)
        layout.addWidget(self.output_button, 1, 0)
        layout.addWidget(self.output_input, 1, 1)
        layout.setColumnStretch(1, 1)
        layout.setRowMinimumHeight(0, 34)
        layout.setRowMinimumHeight(1, 34)
        return layout

    def _build_preset_menu(self) -> QMenu:
        menu = QMenu(self)
        self.save_preset_action = QAction("Save As...", menu)
        self.save_preset_action.triggered.connect(self._save_current_as_preset)
        self.overwrite_preset_action = QAction("Overwrite", menu)
        self.overwrite_preset_action.triggered.connect(self._overwrite_current_preset)
        self.delete_preset_action = QAction("Delete", menu)
        self.delete_preset_action.triggered.connect(self._delete_current_preset)
        self.import_preset_action = QAction("Import...", menu)
        self.import_preset_action.triggered.connect(self._import_preset)
        self.export_preset_action = QAction("Export...", menu)
        self.export_preset_action.triggered.connect(self._export_current_preset)
        self.reset_preset_action = QAction("Reset To Defaults", menu)
        self.reset_preset_action.triggered.connect(self._reset_to_factory_defaults)
        for action in (
            self.save_preset_action,
            self.overwrite_preset_action,
            self.delete_preset_action,
            self.import_preset_action,
            self.export_preset_action,
            self.reset_preset_action,
        ):
            menu.addAction(action)
        return menu

    def _build_content_rows(self):
        spacing = self._theme.spacing["section_gap"]
        content = QHBoxLayout()
        self._content_layout = content
        content.setSpacing(spacing)

        left_column = QVBoxLayout()
        self._left_column_layout = left_column
        left_column.setSpacing(spacing)
        self.materials_card_label = QLabel("", self)
        self.materials_card_label.setWordWrap(True)
        self.materials_card_label.setObjectName("MutedLabel")
        self.materials_card = self._build_info_card("Loaded operator material defaults", self.materials_card_label)
        left_column.addWidget(self.materials_card)

        self.runtime_card_label = QLabel("", self)
        self.runtime_card_label.setWordWrap(True)
        self.runtime_card_label.setObjectName("MutedLabel")
        self.runtime_card = self._build_info_card("Current release runtime state", self.runtime_card_label)
        left_column.addWidget(self.runtime_card)
        left_column.addStretch(1)

        right_column = QVBoxLayout()
        self._right_column_layout = right_column
        right_column.setSpacing(spacing)
        self.status_label = QLabel("XML to USDA Converter is ready.", self)
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setWordWrap(True)
        right_column.addWidget(self.status_label, 0)

        self.wind_panel = WindTabPanel(
            on_change=self._handle_tab_state_changed,
            on_refresh_requested=self.refresh_wind_groups,
        )
        self.geometry_panel = GeometryTabPanel(
            browse_fbx=self._browse_part_fbx,
            on_change=self._handle_geometry_state_changed,
            on_preview_proxy_requested=self.open_proxy_preview_dialog,
            on_preview_fracture_requested=self.open_fracture_preview_dialog,
            on_export_fracture_requested=self.run_export_fracture_usda,
            on_proxy_settings_changed=self._handle_proxy_settings_changed,
        )
        self.materials_panel = MaterialsTabPanel(
            deps=self._deps,
            on_change=self._handle_tab_state_changed,
        )

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self.wind_panel, "Wind")
        self.tabs.addTab(self.geometry_panel, "Geometry")
        self.tabs.addTab(self.materials_panel, "Materials")
        right_column.addWidget(self.tabs, 1)

        content.addLayout(left_column, 0)
        content.addLayout(right_column, 1)
        return content

    def _build_conversion_mode_menu(self) -> QMenu:
        menu = QMenu(self)
        action_group = QActionGroup(menu)
        action_group.setExclusive(True)
        self._conversion_mode_actions: dict[str, QAction] = {}
        for mode_key, label, supported in CONVERSION_MODES:
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setData(mode_key)
            action.setEnabled(supported)
            action.setChecked(mode_key == self._conversion_mode)
            if supported:
                action.triggered.connect(lambda _checked=False, selected=mode_key: self._set_conversion_mode(selected))
            self._conversion_mode_actions[mode_key] = action
            action_group.addAction(action)
            menu.addAction(action)
        return menu

    def _set_conversion_mode(self, mode_key: str) -> None:
        self._conversion_mode = mode_key
        self._operator_state = replace(self._operator_state, conversion_mode=ConversionMode(mode_key))
        for key, action in self._conversion_mode_actions.items():
            action.setChecked(key == mode_key)
        selected_label = next((label for key, label, _supported in CONVERSION_MODES if key == mode_key), mode_key)
        self._append_log(f"Conversion mode selected: {selected_label}")
        self._schedule_operator_state_save()
        self._refresh_state_cards()

    def _refresh_preset_selector(self) -> None:
        self._preset_selector_suspended = True
        self.preset_combo.clear()
        active_name = self._operator_snapshot.active_preset_name or FACTORY_DEFAULT_PRESET_NAME
        active_index = 0
        for index, preset in enumerate(sorted_gui_presets(self._operator_snapshot)):
            self.preset_combo.addItem(preset.name, preset.name)
            if preset.name == active_name:
                active_index = index
        self.preset_combo.setCurrentIndex(active_index)
        self._preset_selector_suspended = False

    def _current_preset_name(self) -> str:
        value = self.preset_combo.currentData()
        return str(value or FACTORY_DEFAULT_PRESET_NAME)

    def _preset_by_name(self, name: str):
        if name == FACTORY_DEFAULT_PRESET_NAME:
            return factory_default_preset()
        return self._operator_snapshot.presets.get(name)

    def _active_preset(self):
        return self._preset_by_name(self._operator_snapshot.active_preset_name or FACTORY_DEFAULT_PRESET_NAME)

    def _handle_preset_selected(self, _index: int) -> None:
        if self._preset_selector_suspended:
            return
        preset = self._preset_by_name(self._current_preset_name())
        if preset is None:
            return
        self._apply_preset(preset)

    def _apply_preset(self, preset) -> None:
        self._settings_save_timer.stop()
        self._operator_state = apply_preset_to_operator_state(self._operator_state, preset)
        self._conversion_mode = self._operator_state.conversion_mode.value
        if hasattr(self, "_conversion_mode_actions"):
            for key, action in self._conversion_mode_actions.items():
                action.setChecked(key == self._conversion_mode)

        self._operator_snapshot = replace(
            self._operator_snapshot,
            active_preset_name=preset.name,
            wind_group_settings=dict(preset.wind_group_settings),
            base_material_settings=preset.base_material_settings,
            part_mesh_settings=preset.part_mesh_settings,
        )
        self._apply_operator_state_to_widgets()
        self._reload_input_dependent_tabs()
        self._set_status(f"Preset selected: {preset.name}")
        self._append_log(f"Preset selected: {preset.name}")
        self._schedule_operator_state_save()
        self._refresh_state_cards()
        self._update_action_state()

    def _save_current_as_preset(self) -> None:
        name, accepted = QInputDialog.getText(self, "Save Preset", "Preset name")
        if not accepted:
            return
        self._save_preset_with_name(name)

    def _overwrite_current_preset(self) -> None:
        name = self._current_preset_name()
        if name == FACTORY_DEFAULT_PRESET_NAME:
            self._report_error("Factory preset", "Factory defaults cannot be overwritten.")
            return
        self._save_preset_with_name(name)

    def _save_preset_with_name(self, name: str) -> None:
        preset_name = name.strip()
        if not preset_name:
            self._report_error("Invalid preset", "Preset name cannot be empty.")
            return
        if preset_name == FACTORY_DEFAULT_PRESET_NAME:
            self._report_error("Invalid preset", "Factory defaults is reserved.")
            return
        self._operator_state = replace(
            self._operator_state,
            gust_attenuation=self.wind_panel.gust_attenuation(),
            is_ground_cover=self.wind_panel.is_ground_cover_enabled(),
        )
        self._save_operator_state()
        preset = preset_from_operator_state(
            preset_name,
            self._operator_state,
            base_material_records=self.materials_panel.serialize_base_material_records(),
            part_source_records=self.materials_panel.serialize_part_source_records(),
            wind_group_records=self.wind_panel.serialize_settings(),
        )
        presets = dict(self._operator_snapshot.presets)
        presets[preset_name] = preset
        self._operator_snapshot = replace(
            self._operator_snapshot,
            active_preset_name=preset_name,
            presets=presets,
        )
        self._deps.save_gui_settings(self._operator_settings_path, self._operator_snapshot)
        self._refresh_preset_selector()
        self._set_status(f"Preset saved: {preset_name}")
        self._append_log(f"Preset saved: {preset_name}")
        self._update_action_state()

    def _delete_current_preset(self) -> None:
        name = self._current_preset_name()
        if name == FACTORY_DEFAULT_PRESET_NAME:
            self._report_error("Factory preset", "Factory defaults cannot be deleted.")
            return
        presets = dict(self._operator_snapshot.presets)
        presets.pop(name, None)
        self._operator_snapshot = replace(
            self._operator_snapshot,
            active_preset_name=FACTORY_DEFAULT_PRESET_NAME,
            presets=presets,
        )
        self._deps.save_gui_settings(self._operator_settings_path, self._operator_snapshot)
        self._refresh_preset_selector()
        self._apply_preset(factory_default_preset())
        self._set_status(f"Preset deleted: {name}")

    def _reset_to_factory_defaults(self) -> None:
        self._apply_preset(factory_default_preset())
        self._refresh_preset_selector()

    def _import_preset(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Import Preset",
            str(self._operator_settings_path.parent),
            "Preset JSON (*.json);;All files (*.*)",
        )
        if not selected:
            return
        try:
            preset = load_gui_preset(selected)
        except ValueError as exc:
            self._report_error("Invalid preset", str(exc))
            return
        presets = dict(self._operator_snapshot.presets)
        presets[preset.name] = preset
        self._operator_snapshot = replace(
            self._operator_snapshot,
            active_preset_name=preset.name,
            presets=presets,
        )
        self._deps.save_gui_settings(self._operator_settings_path, self._operator_snapshot)
        self._refresh_preset_selector()
        self._apply_preset(preset)
        self._set_status(f"Preset imported: {preset.name}")

    def _export_current_preset(self) -> None:
        name = self._current_preset_name()
        if name == FACTORY_DEFAULT_PRESET_NAME:
            self._report_error("Factory preset", "Factory defaults is built in and is not exported.")
            return
        preset = self._preset_by_name(name)
        if preset is None:
            return
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Export Preset",
            str(self._operator_settings_path.parent / f"{preset.name}.json"),
            "Preset JSON (*.json);;All files (*.*)",
        )
        if not selected:
            return
        path = Path(selected)
        if not path.suffix:
            path = path.with_suffix(".json")
        try:
            save_gui_preset(path, preset)
        except OSError as exc:
            self._report_error("Export failed", str(exc))
            return
        self._set_status(f"Preset exported: {path}")

    def _build_info_card(self, title: str, content_label: QLabel) -> QWidget:
        card = QFrame(self)
        card.setObjectName("PanelCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        title_label = QLabel(title, card)
        title_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(title_label)
        layout.addWidget(content_label)
        return card

    def _load_window_assets(self, theme: ResolvedTheme) -> WindowAssets:
        noise_asset = str(theme.glass.get("noise_asset", ""))
        noise_pixmap = QPixmap()
        if noise_asset:
            noise_pixmap = QPixmap(str(resolve_theme_asset(theme, noise_asset)))
        return WindowAssets(
            background=QPixmap(str(resolve_theme_asset(theme, theme.background_image))),
            panel_blur=QPixmap(str(resolve_theme_asset(theme, theme.background_blur_image))),
            noise=noise_pixmap,
        )

    def _compute_current_screen_scale(self) -> float:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return 1.0
        available = screen.availableGeometry()
        return compute_screen_scale(available.width(), available.height())

    def _apply_runtime_theme(self, theme: ResolvedTheme) -> None:
        self._design_theme = theme
        self._ui_scale = self._compute_current_screen_scale()
        runtime_theme = scale_theme_for_runtime(theme, self._ui_scale)
        self._assets = self._load_window_assets(theme)
        self._apply_runtime_theme_to_widgets(runtime_theme)
        self.help_callout.adjustSize()
        self._position_help_callout()
        for dialog in (self._log_dialog, self._help_dialog, self._adjust_ui_dialog, self._global_settings_dialog):
            if dialog is not None:
                dialog.setStyleSheet(build_stylesheet(runtime_theme))

    def _refresh_runtime_scale_for_current_screen(self) -> None:
        screen_scale = self._compute_current_screen_scale()
        if abs(screen_scale - self._ui_scale) < 0.001:
            return
        self._ui_scale = screen_scale
        runtime_theme = scale_theme_for_runtime(self._design_theme, self._ui_scale)
        self._apply_runtime_theme_to_widgets(runtime_theme)

    def _apply_runtime_theme_to_widgets(self, runtime_theme: ResolvedTheme) -> None:
        self._theme = runtime_theme
        self.setStyleSheet(build_stylesheet(runtime_theme))
        self.title_bar.apply_theme(runtime_theme)
        self.panel.set_theme(runtime_theme, self._assets.panel_blur, self._assets.noise)
        self._apply_theme_to_layout()
        self._update_panel_metrics()
        self._update_window_shape()
        self.panel.update()
        self.update()

    def _connect_screen_scale_updates(self) -> None:
        if self._screen_change_connected or self.windowHandle() is None:
            return
        self.windowHandle().screenChanged.connect(self._handle_screen_changed)
        self._screen_change_connected = True

    def _handle_screen_changed(self, _screen) -> None:
        self._refresh_runtime_scale_for_current_screen()

    def _apply_theme_to_layout(self) -> None:
        outer_margin = int(self._theme.spacing["outer_margin"])
        vertical_offset = int(self._theme.layout.get("panel_vertical_offset", 0))
        top_margin = max(8, outer_margin + max(0, vertical_offset))
        bottom_margin = max(8, outer_margin + max(0, -vertical_offset))
        self._body_layout.setContentsMargins(outer_margin, top_margin, outer_margin, bottom_margin)

        panel_padding = int(self._theme.spacing["panel_padding"])
        self._panel_layout.setContentsMargins(panel_padding, panel_padding, panel_padding, panel_padding)
        self._panel_layout.setSpacing(int(self._theme.spacing["section_gap"]))

        self._top_rows_layout.setHorizontalSpacing(int(self._theme.spacing["control_gap"]))
        self._top_rows_layout.setVerticalSpacing(int(self._theme.layout.get("file_row_gap", 8)))
        self._content_layout.setSpacing(int(self._theme.spacing["section_gap"]))
        self._left_column_layout.setSpacing(int(self._theme.spacing["section_gap"]))
        self._right_column_layout.setSpacing(int(self._theme.spacing["section_gap"]))
        self._action_column_layout.setSpacing(max(6, int(self._theme.spacing["control_gap"]) - 4))

        file_button_width = int(self._theme.chrome.get("file_button_width", 74))
        file_button_height = int(self._theme.chrome.get("file_button_height", self._theme.control_heights["input"]))
        self.source_button.setFixedSize(file_button_width, file_button_height)
        self.output_button.setFixedSize(file_button_width, file_button_height)
        title_preset_width = self._title_preset_width()
        title_preset_height = int(self._theme.chrome.get("title_preset_height", self._theme.chrome.get("window_button_size", 28)))
        self.preset_combo.setFixedSize(title_preset_width, title_preset_height)
        self.preset_menu_button.setFixedSize(max(32, title_preset_height), title_preset_height)

        action_width = int(self._theme.layout.get("action_column_width", 148))
        self.convert_action_frame.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.convert_action_frame.setFixedWidth(action_width)
        button_height = int(self._theme.control_heights["button"])
        gear_width = max(34, min(52, button_height + 2))
        self.convert_action_frame.setFixedHeight(button_height)
        self.convert_button.setFixedSize(max(72, action_width - gear_width - 1), button_height)
        self.convert_mode_button.setFixedSize(gear_width, button_height)
        self.generate_action_frame.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.generate_action_frame.setFixedWidth(action_width)
        self.generate_action_frame.setFixedHeight(button_height)
        generate_left_width = max(1, (action_width - 1) // 2)
        generate_right_width = max(1, action_width - generate_left_width - 1)
        self.generate_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.generate_proxy_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.generate_button.setFixedSize(generate_left_width, button_height)
        self.generate_proxy_button.setFixedSize(generate_right_width, button_height)

        refresh_width = int(self._theme.chrome.get("wind_refresh_button_width", 164))
        refresh_height = int(self._theme.chrome.get("wind_refresh_button_height", 28))
        self.wind_panel.refresh_button.setFixedSize(refresh_width, refresh_height)

        left_column_width = int(self._theme.layout.get("left_column_width", 280))
        self.materials_card.setFixedWidth(left_column_width)
        self.runtime_card.setFixedWidth(left_column_width)
        self.tabs.setMinimumHeight(int(self._theme.layout.get("tabs_min_height", 440)))
        self.panel.setMinimumHeight(int(self._theme.layout.get("panel_min_height", 680)))
        for layout in (
            self._outer_layout,
            self._body_layout,
            self._panel_layout,
            self._top_rows_layout,
            self._content_layout,
            self._action_column_layout,
        ):
            layout.invalidate()
            layout.activate()

    def _title_preset_width(self) -> int:
        configured_width = int(self._theme.chrome.get("title_preset_width", 136))
        current_text = self.preset_combo.currentText() or FACTORY_DEFAULT_PRESET_NAME
        text_width = self.preset_combo.fontMetrics().horizontalAdvance(current_text)
        return max(96, min(configured_width, text_width + 52))

    def _apply_saved_state(self) -> None:
        self._restore_geometry = self._default_restore_geometry_for_current_screen()
        self.setGeometry(self._restore_geometry)
        if self._state.is_maximized:
            self.showMaximized()

    def _default_restore_geometry_for_current_screen(self) -> QRect:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return QRect(self._restore_geometry)
        available = screen.availableGeometry()
        width = min(
            available.width(),
            max(self.minimumWidth(), int(round(available.width() * 0.66))),
        )
        height = min(
            available.height(),
            max(self.minimumHeight(), int(round(available.height() * 0.78))),
        )
        x = available.x() + max(0, (available.width() - width) // 2)
        y = available.y() + max(0, (available.height() - height) // 2)
        return QRect(x, y, width, height)

    def _refresh_layout_after_show(self) -> None:
        # The first frameless layout pass on Windows can be conservative while
        # the window is still settling. A second activation after show keeps the
        # split action column and stacked buttons at their intended sizes.
        self._apply_theme_to_layout()
        self._update_panel_metrics()
        self._sync_help_overlay_geometry()
        self.panel.updateGeometry()
        self.panel.update()
        self.updateGeometry()
        self.update()
        self._update_action_state()
        self._apply_help_prompt_state()

    def _apply_operator_state_to_widgets(self) -> None:
        self._persistence_suspended = True
        self.source_input.setText(self._operator_state.input_path)
        self.output_input.setText(self._operator_state.output_path)
        if self._operator_state.input_path:
            self._auto_output_path = str(Path(self._operator_state.input_path).with_suffix(".usda"))
        if self._operator_state.input_path and not self._operator_state.output_path:
            self._set_default_output_from_source("", None, force=True)
        self.wind_panel.set_global_options(
            is_ground_cover=self._operator_state.is_ground_cover,
            gust_attenuation=self._operator_state.gust_attenuation,
        )
        self.geometry_panel.apply_proxy_settings(self._proxy_mesh_settings)
        self.geometry_panel.apply_fracture_preview_settings(self._fracture_preview_settings)
        self._conversion_mode = self._operator_state.conversion_mode.value
        if hasattr(self, "_conversion_mode_actions"):
            for key, action in self._conversion_mode_actions.items():
                action.setChecked(key == self._conversion_mode)
        self._persistence_suspended = False

    def _apply_saved_active_tab(self) -> None:
        active_tab_name = self._state.active_tab_name
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == active_tab_name:
                self.tabs.setCurrentIndex(index)
                return

    def _apply_runtime_cleanup_summary(self) -> None:
        if not self._runtime_cleanup_summary.has_activity:
            return
        summary_message = f"Runtime cleanup: {self._runtime_cleanup_summary.to_message()}"
        if self._runtime_cleanup_summary.failed_paths:
            failed_paths = "\n".join(f"  - {failed_path}" for failed_path in self._runtime_cleanup_summary.failed_paths)
            summary_message = f"{summary_message}\n{failed_paths}"
        self._append_log(summary_message)

    def _apply_fbx_cache_startup_summary(self) -> None:
        summary = self._fbx_cache_startup_summary
        self._append_log(
            "FBX cache startup sweep: "
            f"{summary.entry_count} entrie(s), {_format_bytes(summary.total_bytes)}, "
            f"removed {summary.removed_entries} entrie(s) / {_format_bytes(summary.removed_bytes)}."
        )
        self._append_fbx_cache_failures_to_log(summary)

    def _fbx_payload_cache_root(self) -> Path:
        return self._runtime_paths.cache_root / "fbx-payloads"

    def _fbx_cache_max_bytes(self) -> int:
        return int(self._operator_snapshot.fbx_cache_max_size_gb) * 1024 * 1024 * 1024

    def _fbx_cache_max_age_seconds(self) -> int:
        return int(self._operator_snapshot.fbx_cache_max_age_days) * 24 * 60 * 60

    def _summarize_fbx_cache(self) -> FbxPayloadCacheSummary:
        return summarize_fbx_payload_cache(cache_root=self._fbx_payload_cache_root())

    def _sweep_fbx_cache(self) -> FbxPayloadCacheSummary:
        summary = sweep_fbx_payload_cache(
            cache_root=self._fbx_payload_cache_root(),
            max_bytes=self._fbx_cache_max_bytes(),
            max_age_seconds=self._fbx_cache_max_age_seconds(),
        )
        self._append_fbx_cache_failures_to_log(summary)
        return summary

    def _clear_fbx_cache(self) -> FbxPayloadCacheSummary:
        summary = clear_fbx_payload_cache(cache_root=self._fbx_payload_cache_root())
        self._append_log(
            "FBX cache clear: "
            f"removed {summary.removed_entries} entrie(s) / {_format_bytes(summary.removed_bytes)}."
        )
        self._append_fbx_cache_failures_to_log(summary)
        return summary

    def _apply_fbx_cache_settings(
        self,
        *,
        max_size_gb: int,
        max_age_days: int,
        debug_trace_enabled: bool | None = None,
    ) -> FbxPayloadCacheSummary:
        self._operator_snapshot = replace(
            self._operator_snapshot,
            fbx_cache_max_size_gb=max(1, int(max_size_gb)),
            fbx_cache_max_age_days=max(1, int(max_age_days)),
            debug_trace_enabled=(
                self._operator_snapshot.debug_trace_enabled
                if debug_trace_enabled is None
                else bool(debug_trace_enabled)
            ),
        )
        self._trace_logger = replace(self._trace_logger, debug_enabled=self._operator_snapshot.debug_trace_enabled)
        self._deps.save_gui_settings(self._operator_settings_path, self._operator_snapshot)
        self._trace(
            "settings.update",
            message="Global settings saved",
            data={"debug_trace_enabled": self._operator_snapshot.debug_trace_enabled},
        )
        summary = self._sweep_fbx_cache()
        self._set_status("FBX cache settings saved.")
        self._append_log(
            "FBX cache settings saved: "
            f"{self._operator_snapshot.fbx_cache_max_size_gb} GB, "
            f"{self._operator_snapshot.fbx_cache_max_age_days} days."
        )
        return summary

    def _append_fbx_cache_failures_to_log(self, summary: FbxPayloadCacheSummary) -> None:
        if not summary.failed_paths:
            return
        failed_paths = "\n".join(f"  - {failed_path}" for failed_path in summary.failed_paths)
        self._append_log(f"FBX cache warning: failed path(s)\n{failed_paths}")

    def _refresh_state_cards(self) -> None:
        policy = self._operator_state.material_policy.value
        if self._operator_state.material_policy.value == "single_material":
            material_detail = f"single: {self._operator_state.single_material_path or '<none>'}"
        else:
            material_detail = (
                f"bark: {self._operator_state.bark_material_path or '<none>'}\n"
                f"leaves: {self._operator_state.leaves_material_path or '<none>'}"
            )
        self.materials_card_label.setText(f"Policy: {policy}\n{material_detail}")

        prototype_count = len(self.geometry_panel.current_snapshot()) if self.geometry_panel.has_rows() else 0
        wind_state = "loaded" if self._current_dynamic_wind is not None else "not loaded"
        self.runtime_card_label.setText(
            f"CPU profile: {self._operator_state.cpu_profile.value}\n"
            f"Preserve temp files: {self._operator_state.preserve_temp_files}\n"
            f"Conversion mode: {self._conversion_mode}\n"
            f"Ground cover: {self._operator_state.is_ground_cover}\n"
            f"Gust attenuation: {self._operator_state.gust_attenuation:.2f}\n"
            f"Prototype rows: {prototype_count}\n"
            f"Wind groups: {wind_state}"
        )

    def _update_action_state(self) -> None:
        has_input = bool(self.source_input.text().strip())
        has_output = bool(self.output_input.text().strip())
        self.convert_button.setText("Cancel" if self._conversion_running else "Convert to USDA")
        self.convert_button.setEnabled(self._conversion_running or (has_input and has_output))
        self.convert_mode_button.setEnabled(not self._conversion_running)
        self.title_bar.settings_button.setEnabled(not self._conversion_running)
        if self._global_settings_dialog is not None:
            self._global_settings_dialog.set_controls_enabled(not self._conversion_running)
        self.preset_combo.setEnabled(not self._conversion_running)
        self.preset_menu_button.setEnabled(not self._conversion_running)
        if hasattr(self, "overwrite_preset_action"):
            selected_is_factory = self._current_preset_name() == FACTORY_DEFAULT_PRESET_NAME
            self.save_preset_action.setEnabled(not self._conversion_running)
            self.overwrite_preset_action.setEnabled(not self._conversion_running and not selected_is_factory)
            self.delete_preset_action.setEnabled(not self._conversion_running and not selected_is_factory)
            self.import_preset_action.setEnabled(not self._conversion_running)
            self.export_preset_action.setEnabled(not self._conversion_running and not selected_is_factory)
            self.reset_preset_action.setEnabled(not self._conversion_running)
        self.wind_panel.refresh_button.setEnabled(has_input and not self._conversion_running and not self._wind_refresh_running)
        self.generate_button.setEnabled(
            has_input and not self._conversion_running and not self._wind_refresh_running and not self._wind_json_running
        )
        proxy_running = self._background_jobs.proxy_mesh_running
        self.generate_proxy_button.setEnabled(has_input and not self._conversion_running and not proxy_running)
        self.geometry_panel.preview_proxy_button.setEnabled(has_input and not self._conversion_running and not proxy_running)
        fracture_preview_running = self._background_jobs.fracture_preview_running
        self.geometry_panel.preview_fracture_button.setEnabled(
            has_input and not self._conversion_running and not fracture_preview_running
        )

    def _handle_convert_button_clicked(self) -> None:
        # One operator-facing control handles both states. Clicking during an
        # active conversion is semantically the same as pressing Cancel.
        if self._conversion_running:
            self.cancel_conversion()
            return
        self.run_conversion()

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _set_log(self, text: str) -> None:
        self._log_text = text.strip()
        if self._log_dialog is not None:
            self._log_dialog.set_text(self._log_text)

    def _append_log(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if self._log_text:
            self._log_text = f"{self._log_text}\n\n{text}"
        else:
            self._log_text = text
        if self._log_dialog is not None:
            self._log_dialog.set_text(self._log_text)

    def _append_runtime_log(self, title: str, message: str = "") -> None:
        runtime_log_path = self._runtime_paths.settings_dir / "gui_runtime.log"
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        text = f"\n[{timestamp}] {title}\n"
        if message.strip():
            text = f"{text}{message.strip()}\n"
        try:
            self._runtime_paths.settings_dir.mkdir(parents=True, exist_ok=True)
            with runtime_log_path.open("a", encoding="utf-8") as handle:
                handle.write(text)
        except OSError:
            pass

    def _trace(self, kind: str, **kwargs) -> None:
        try:
            self._trace_logger.log(kind, **kwargs)
        except OSError:
            pass

    def _startup_log_text(self) -> str:
        return (
            "XML to USDA Converter is alive.\n\n"
            "- Frameless shell\n"
            "- Background cover/crop\n"
            "- Glass panel\n"
            "- Shared operator settings bridge\n"
            "- Real conversion / wind action wiring\n\n"
            "This pass adds tabbed Wind / Geometry / Materials panels, while keeping the left-side cards reserved."
        )

    def open_log_dialog(self) -> None:
        if self._log_dialog is None:
            self._log_dialog = TextDialog(
                title="Conversion Log",
                text=self._log_text or "No log entries yet.",
                parent=self,
            )
        else:
            self._log_dialog.set_text(self._log_text or "No log entries yet.")
        self._log_dialog.setStyleSheet(build_stylesheet(self._theme))
        self._log_dialog.show()
        self._log_dialog.raise_()
        self._log_dialog.activateWindow()

    def open_help_dialog(self) -> None:
        if self._help_dialog is None:
            self._help_dialog = HelpDeckDialog(parent=self)
        self._help_dialog.setStyleSheet(build_stylesheet(self._theme))
        self._help_dialog.show()
        self._help_dialog.raise_()
        self._help_dialog.activateWindow()

    def open_support_dialog(self) -> None:
        if self._support_dialog is None:
            self._support_dialog = SupportDialog(
                on_export_diagnostics=self.export_diagnostics_bundle,
                parent=self,
            )
        self._support_dialog.setStyleSheet(build_stylesheet(self._theme))
        self._support_dialog.show()
        self._support_dialog.raise_()
        self._support_dialog.activateWindow()

    def open_global_settings_dialog(self) -> None:
        if self._conversion_running:
            return
        if self._global_settings_dialog is None:
            self._global_settings_dialog = GlobalSettingsDialog(self)
            self._global_settings_dialog.finished.connect(self._handle_global_settings_closed)
        self._global_settings_dialog.setStyleSheet(build_stylesheet(self._theme))
        self._global_settings_dialog.sync_from_settings()
        self._global_settings_dialog.set_controls_enabled(not self._conversion_running)
        self._global_settings_dialog.refresh_cache_summary()
        anchor = self.title_bar.settings_button.mapToGlobal(QPoint(0, self.title_bar.settings_button.height() + 6))
        self._global_settings_dialog.move(anchor)
        self._global_settings_dialog.show()
        self._global_settings_dialog.raise_()
        self._global_settings_dialog.activateWindow()

    def _handle_global_settings_closed(self, _result: int) -> None:
        self._global_settings_dialog = None

    def export_diagnostics_bundle(self) -> None:
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Export diagnostics bundle",
            str(self._default_diagnostics_bundle_path()),
            "Zip files (*.zip);;All files (*.*)",
        )
        if not selected:
            return
        bundle_path = Path(selected)
        if bundle_path.suffix.lower() != ".zip":
            bundle_path = bundle_path.with_suffix(".zip")
        try:
            self._save_operator_state()
            exported_path = export_diagnostics_bundle(
                build_diagnostics_bundle_request(
                    bundle_path=bundle_path,
                    settings_path=self._operator_settings_path,
                    runtime_paths=self._runtime_paths,
                    runtime_cleanup_summary=self._runtime_cleanup_summary,
                    active_preset_name=self._current_preset_name(),
                    selected_input_path=self.source_input.text().strip(),
                    selected_output_path=self.output_input.text().strip(),
                    in_app_log_text=self._log_text,
                )
            )
        except OSError as exc:
            self._report_error("Diagnostics export failed", str(exc), status="Diagnostics export failed.")
            return
        self._set_status(f"Diagnostics bundle exported: {exported_path}")
        self._append_log(f"Diagnostics bundle exported\n{exported_path}")

    def _default_diagnostics_bundle_path(self) -> Path:
        return self._runtime_paths.settings_dir / "XMLtoUSDA_diagnostics.zip"

    def dismiss_help_prompt(self) -> None:
        self._state = replace(self._state, help_prompt_dismissed=True)
        self._apply_help_prompt_state()

    def _apply_help_prompt_state(self) -> None:
        visible = not self._state.help_prompt_dismissed
        if visible:
            self.help_callout.adjustSize()
            self._position_help_callout()
            self.help_callout.show()
            self.help_callout.raise_()
        else:
            self.help_callout.hide()

    def _position_help_callout(self) -> None:
        if not hasattr(self, "help_callout") or not hasattr(self, "title_bar"):
            return
        anchor = self.title_bar.help_button.mapTo(self, QPoint(0, self.title_bar.help_button.height()))
        margin = 8
        x = max(margin, min(anchor.x(), self.width() - self.help_callout.width() - margin))
        y = anchor.y() + margin
        self.help_callout.move(x, y)

    def _sync_help_overlay_geometry(self) -> None:
        if hasattr(self, "help_callout") and not self._state.help_prompt_dismissed:
            self._position_help_callout()
            self.help_callout.raise_()

    def open_adjust_ui_dialog(self) -> None:
        if self._adjust_ui_dialog is None:
            self._adjust_ui_dialog = AdjustUiDialog(
                base_theme=self._base_theme,
                applied_overrides=self._theme_overrides,
                current_theme=self._design_theme,
                on_preview=self._preview_theme_overrides,
                on_apply=self._apply_theme_overrides_runtime,
                on_save=self._save_theme_overrides,
                on_export=self._export_current_theme,
                parent=self,
            )
            self._adjust_ui_dialog.finished.connect(self._handle_adjust_ui_closed)
        self._adjust_ui_dialog.setStyleSheet(build_stylesheet(self._theme))
        self._adjust_ui_dialog.show()
        self._adjust_ui_dialog.raise_()
        self._adjust_ui_dialog.activateWindow()

    def _handle_adjust_ui_closed(self, _result: int) -> None:
        self._adjust_ui_dialog = None

    def _show_info(self, title: str, message: str) -> None:
        self._append_log(f"{title}\n{message}")

    def _preview_theme_overrides(self, overrides: ThemeOverrides, resolved_theme: ResolvedTheme) -> None:
        self._apply_runtime_theme(resolved_theme)

    def _apply_theme_overrides_runtime(self, overrides: ThemeOverrides, resolved_theme: ResolvedTheme) -> None:
        self._theme_overrides = ThemeOverrides(overrides.theme_name, deepcopy(overrides.payload))
        self._apply_runtime_theme(resolved_theme)

    def _save_theme_overrides(self, overrides: ThemeOverrides, resolved_theme: ResolvedTheme) -> None:
        self._apply_theme_overrides_runtime(overrides, resolved_theme)
        save_ui_theme_overrides(self._theme_overrides, self._theme_overrides_path)
        self._append_log(f"Adjust UI\nSaved theme overrides to {self._theme_overrides_path}")

    def _export_current_theme(self, resolved_theme: ResolvedTheme) -> Path:
        export_path = self._theme_export_path
        write_theme_payload(export_path, theme_to_payload(resolved_theme))
        self._append_log(f"Adjust UI\nExported merged theme to {export_path}")
        return export_path

    def _report_error(
        self,
        title: str,
        message: str,
        *,
        details: str | None = None,
        status: str | None = None,
    ) -> None:
        self._set_status(status or title)
        self._append_log(details or message)
        QMessageBox.critical(self, title, message)

    def _handle_source_text_changed(self, text: str) -> None:
        previous_input = self._operator_state.input_path
        previous_auto_output = self._auto_output_path
        normalized_text = text.strip()
        self._operator_state = replace(self._operator_state, input_path=normalized_text)
        input_changed = normalized_text != previous_input
        if input_changed:
            self._current_dynamic_wind = None
            self._proxy_mesh_preview_result = None
            self._proxy_mesh_preview_input_path = ""
            self._reset_fracture_manual_session_cuts()
            self._pending_generate_after_refresh = False
            self._set_default_output_from_source(previous_input, previous_auto_output)
        if not self._persistence_suspended:
            self._reload_input_dependent_tabs()
            self._schedule_operator_state_save()
            if input_changed:
                self._maybe_auto_refresh_wind_groups()
        self._refresh_state_cards()
        self._update_action_state()

    def _handle_output_text_changed(self, text: str) -> None:
        self._operator_state = replace(self._operator_state, output_path=text.strip())
        if not self._persistence_suspended:
            self._schedule_operator_state_save()
        self._update_action_state()

    def _reset_fracture_manual_session_cuts(self) -> None:
        fracture = self._fracture_preview_settings.fracture
        if not fracture.pinned_cut_joint_tokens:
            return
        self._fracture_preview_settings = replace(
            self._fracture_preview_settings,
            fracture=replace(fracture, pinned_cut_joint_tokens=()),
        )
        self.geometry_panel.apply_fracture_preview_settings(self._fracture_preview_settings)
        if self._fracture_preview_dialog is not None:
            self._fracture_preview_dialog.set_settings(self._fracture_preview_settings)

    def _set_default_output_from_source(
        self,
        previous_input: str,
        previous_auto_output: str | None,
        *,
        force: bool = False,
    ) -> None:
        source_path = self.source_input.text().strip()
        if not source_path:
            self._auto_output_path = None
            return
        new_auto_output = str(Path(source_path).with_suffix(".usda"))
        current_output = self.output_input.text().strip()
        previous_default = previous_auto_output or (str(Path(previous_input).with_suffix(".usda")) if previous_input else "")
        current_path = Path(current_output) if current_output else None
        current_is_relative = bool(current_path is not None and not current_path.is_absolute())
        if force or not current_output or current_output == previous_default or current_is_relative:
            next_output = new_auto_output
        else:
            next_output = str(current_path.with_name(f"{Path(source_path).stem}{current_path.suffix or '.usda'}"))
        if next_output != current_output:
            self._persistence_suspended = True
            self.output_input.setText(next_output)
            self._persistence_suspended = False
            self._operator_state = replace(self._operator_state, output_path=next_output)
        self._auto_output_path = new_auto_output

    def _maybe_auto_refresh_wind_groups(self) -> None:
        input_path = self.source_input.text().strip()
        if not input_path or not Path(input_path).exists():
            self._source_refresh_timer.stop()
            return
        if self._conversion_running or self._wind_refresh_running or self._wind_json_running:
            return
        self._source_refresh_timer.start()

    def _schedule_operator_state_save(self) -> None:
        self._settings_save_timer.start()

    def _save_operator_state(self) -> None:
        try:
            state = self._operator_state
            if state.output_path and state.output_path == self._auto_output_path:
                state = replace(state, output_path=self._operator_snapshot.last_output_path)
            self._operator_snapshot = save_nested_input_settings(
                self._deps,
                state,
                previous_snapshot=self._operator_snapshot,
                base_material_records=self.materials_panel.serialize_base_material_records(),
                part_source_records=self.materials_panel.serialize_part_source_records(),
                wind_group_records=self.wind_panel.serialize_settings(),
                proxy_mesh_settings=self._proxy_mesh_settings,
                settings_path=self._operator_settings_path,
            )
        except OSError:
            return

    def _handle_tab_state_changed(self) -> None:
        self._operator_snapshot = replace(
            self._operator_snapshot,
            wind_group_settings=self.wind_panel.serialize_settings(),
        )
        self._operator_state = replace(
            self._operator_state,
            gust_attenuation=self.wind_panel.gust_attenuation(),
            is_ground_cover=self.wind_panel.is_ground_cover_enabled(),
        )
        self._schedule_operator_state_save()
        self._refresh_state_cards()

    def _handle_geometry_state_changed(self) -> None:
        self.materials_panel.apply_geometry_state(
            self.geometry_panel.current_snapshot(),
            cpu_profile=self._operator_state.cpu_profile,
        )
        self._handle_tab_state_changed()

    def _handle_proxy_settings_changed(self) -> None:
        self._proxy_mesh_settings = self.geometry_panel.proxy_settings()
        cached_proxy = self._proxy_mesh_preview_result
        if cached_proxy is not None and cached_proxy.settings != self._proxy_mesh_settings:
            self._proxy_mesh_preview_result = None
            self._proxy_mesh_preview_input_path = ""
        self._schedule_operator_state_save()

    def _reload_input_dependent_tabs(self) -> None:
        input_path = self.source_input.text().strip()
        if not input_path:
            self._clear_input_dependent_tabs()
            return
        if not Path(input_path).exists():
            self._clear_input_dependent_tabs("Selected XML path is unavailable.")
            return

        base_records = load_base_material_records(self._operator_snapshot)
        part_records = load_part_source_records(self._operator_snapshot)
        wind_records = load_wind_group_records(self._operator_snapshot)
        active_preset = self._active_preset()
        if active_preset is not None:
            if not base_records:
                base_records = active_preset.base_material_settings
            if not part_records:
                part_records = active_preset.part_mesh_settings
            if not wind_records:
                wind_records = dict(active_preset.wind_group_settings)
        self.wind_panel.set_persisted_settings(wind_records)

        prototype_discovery = self._deps.discover_part_prototype_rows(input_path, persisted_records=part_records)
        self.geometry_panel.load(prototype_discovery)
        self.materials_panel.load(
            input_path=input_path,
            base_persisted_records=base_records,
            part_persisted_records=part_records,
            geometry_snapshot=self.geometry_panel.current_snapshot(),
            cpu_profile=self._operator_state.cpu_profile,
        )
        self.wind_panel.clear("Click Refresh Wind Groups to inspect wind settings.")

    def _clear_input_dependent_tabs(self, message: str | None = None) -> None:
        if message is None:
            self.wind_panel.clear()
            self.geometry_panel.clear()
            self.materials_panel.clear()
            return
        self.wind_panel.clear(message)
        self.geometry_panel.clear(message)
        self.materials_panel.clear(message)

    def browse_input(self) -> None:
        previous_input = self._operator_state.input_path
        previous_auto_output = self._auto_output_path
        initial = self.source_input.text().strip()
        if initial:
            initial_path = Path(initial)
            if initial_path.suffix.lower() == ".xml" or initial_path.is_file():
                initial = str(initial_path.parent)
        if not initial and self._operator_snapshot.last_input_path:
            initial = str(Path(self._operator_snapshot.last_input_path).parent)
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select SpeedTree XML",
            initial,
            "XML files (*.xml);;All files (*.*)",
        )
        if not selected:
            return
        self.source_input.setText(selected)
        self._set_default_output_from_source(previous_input, previous_auto_output)
        self._set_status("Source XML selected.")

    def browse_output(self) -> None:
        current_output = self.output_input.text().strip()
        if current_output and current_output != self._auto_output_path:
            initial = current_output
        else:
            initial = self._operator_snapshot.last_output_path or current_output or "tree.usda"
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Select USDA output",
            initial,
            "USDA files (*.usda *.usd);;All files (*.*)",
        )
        if not selected:
            return
        self.output_input.setText(selected)
        self._set_status("Output USDA selected.")
        self._save_operator_state()

    def _browse_part_fbx(self, target_edit: QLineEdit) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select part FBX",
            target_edit.text().strip() or "",
            "FBX files (*.fbx);;JSON test payloads (*.json);;All files (*.*)",
        )
        if selected:
            target_edit.setText(selected)

    def run_conversion(self) -> None:
        try:
            plan = self._prepare_current_conversion_plan()
        except ValueError as exc:
            self._report_conversion_plan_error(exc)
            return
        self._background_jobs.start_conversion(request=plan.request, run_async=plan.run_async)

    def _prepare_current_conversion_plan(self):
        return self._deps.prepare_conversion_plan(
            input_path=self.source_input.text().strip(),
            output_path=self.output_input.text().strip(),
            cpu_profile=self._operator_state.cpu_profile,
            cleanup_policy=self._current_cleanup_policy(),
            material_policy=self._operator_state.material_policy,
            bark_material_path=self._operator_state.bark_material_path or None,
            leaves_material_path=self._operator_state.leaves_material_path or None,
            single_material_path=self._operator_state.single_material_path or None,
            base_material_overrides=self.materials_panel.collect_base_material_overrides(),
            udim_material_settings=self.materials_panel.collect_udim_material_settings(),
            prototype_source_configs=self.materials_panel.collect_prototype_source_configs(),
            conversion_mode=self._operator_state.conversion_mode,
            async_threshold_bytes=self.ASYNC_CONVERSION_THRESHOLD_BYTES,
            fbx_cache_max_bytes=self._fbx_cache_max_bytes(),
            fbx_cache_max_age_seconds=self._fbx_cache_max_age_seconds(),
        )

    def _report_conversion_plan_error(self, exc: ValueError) -> None:
        message = str(exc)
        if message == "Select a source XML file.":
            self._report_error("Missing input", message)
        elif message == "Select an output USDA path.":
            self._report_error("Missing output", message)
        else:
            self._report_error("Invalid material path", message)

    def refresh_wind_groups(self) -> None:
        self._source_refresh_timer.stop()
        input_path = self.source_input.text().strip()
        if not input_path:
            self._report_error("Missing input", "Select a source XML file before loading wind groups.")
            return
        self.wind_panel.set_persisted_settings(
            load_wind_group_records(self._operator_snapshot)
        )
        plan = self._deps.prepare_wind_inspection_plan(
            input_path=input_path,
            is_ground_cover=self.wind_panel.is_ground_cover_enabled(),
            async_threshold_bytes=self.ASYNC_WIND_REFRESH_THRESHOLD_BYTES,
        )
        self._background_jobs.start_wind_refresh(plan.request)

    def run_generate_wind_json(self) -> None:
        self._source_refresh_timer.stop()
        if self._current_dynamic_wind is None:
            self._pending_generate_after_refresh = True
            self.refresh_wind_groups()
            return
        input_path = self.source_input.text().strip()
        if not input_path:
            self._report_error("Missing input", "Select a source XML file before generating wind JSON.")
            return
        output_path = self._deps.derive_wind_json_output_path(
            input_path,
            self.output_input.text().strip(),
        )
        request = self._deps.WindGenerationRequest(
            input_path=input_path,
            output_path=str(output_path),
            group_settings=self.wind_panel.collect_group_settings(),
            gust_attenuation=self.wind_panel.gust_attenuation(),
            is_ground_cover=self.wind_panel.is_ground_cover_enabled(),
        )
        self._background_jobs.start_wind_json_generation(request)

    def open_proxy_preview_dialog(self) -> None:
        self._source_refresh_timer.stop()
        if self._background_jobs.fracture_preview_running:
            self._background_jobs.cancel_fracture_preview()
            if self._fracture_preview_dialog is not None and self._fracture_preview_dialog.current_preview is None:
                self._fracture_preview_dialog.set_error("Preview generation cancelled.")
        self._proxy_mesh_settings = self.geometry_panel.proxy_settings()
        try:
            request = self._build_proxy_source_request()
        except ValueError as exc:
            self._report_error("Missing input", str(exc))
            return

        def _start_preview(settings):
            return self._deps.start_proxy_mesh_process(
                request,
                settings,
                action="preview",
            )

        input_path = request.input_path
        dialog = ProxyPreviewDialog(
            settings=self._proxy_mesh_settings,
            start_preview=_start_preview,
            run_preview_locally=lambda settings: self._deps.generate_proxy_mesh_from_source_request(request, settings),
            drain_queue=self._deps.drain_process_queue,
            close_queue=self._deps.close_process_queue,
            initial_proxy=self._proxy_preview_result_for_input(input_path),
            report_preview_error=self._record_proxy_preview_error,
            on_preview_ready=lambda proxy, current_input=input_path: self._cache_proxy_preview_result(
                current_input,
                proxy,
            ),
            on_preview_closed=lambda settings, proxy, current_input=input_path: self._apply_proxy_preview_state(
                current_input,
                settings,
                proxy,
            ),
            parent=None,
        )
        dialog.setStyleSheet(self.styleSheet())
        self._proxy_preview_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def open_fracture_preview_dialog(self) -> None:
        self._source_refresh_timer.stop()
        if self._proxy_preview_dialog is not None:
            self._proxy_preview_dialog.close()
            self._proxy_preview_dialog = None
        if self._background_jobs.fracture_preview_running:
            if self._fracture_preview_dialog is not None:
                self._fracture_preview_dialog.show()
                self._fracture_preview_dialog.raise_()
                self._fracture_preview_dialog.activateWindow()
            return
        settings = self._fracture_preview_settings
        try:
            request = self._build_fracture_preview_request()
        except ValueError as exc:
            self._report_error("Missing input", str(exc))
            return
        self._append_runtime_log(
            "INFO Fracture Preview requested",
            "\n".join(
                (
                    f"input_path={request.input_path}",
                    f"output_path={request.output_path}",
                    f"method={settings.fracture.method}",
                    f"target_piece_count={settings.fracture.target_piece_count}",
                    f"preview_polycount={settings.final_polycount}",
                    f"preview_base_priority={settings.base_mesh_priority}",
                    f"preview_prototype_faces={settings.max_prototype_faces}",
                )
            ),
        )
        self._trace(
            "job.start",
            job="fracture_preview",
            message="Fracture Preview requested",
            data={
                "input_path": request.input_path,
                "output_path": request.output_path,
                "method": settings.fracture.method,
                "target_piece_count": settings.fracture.target_piece_count,
                "preview_polycount": settings.final_polycount,
            },
            debug_data={
                "preview_base_priority": settings.base_mesh_priority,
                "preview_prototype_faces": settings.max_prototype_faces,
            },
        )
        dialog = FracturePreviewDialog(
            settings=settings,
            on_settings_changed=self._handle_fracture_preview_settings_changed,
            on_export_requested=self.run_export_fracture_usda,
            parent=None,
        )
        dialog.setStyleSheet(self.styleSheet())
        self._fracture_preview_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self._background_jobs.start_fracture_preview(request, settings)

    def _handle_fracture_preview_result(self, preview) -> None:
        dialog = self._fracture_preview_dialog
        if dialog is None:
            dialog = FracturePreviewDialog(
                settings=self._fracture_preview_settings,
                on_settings_changed=self._handle_fracture_preview_settings_changed,
                on_export_requested=self.run_export_fracture_usda,
                parent=None,
            )
            dialog.setStyleSheet(self.styleSheet())
            self._fracture_preview_dialog = dialog
        dialog.set_settings(self._fracture_preview_settings)
        self._append_runtime_log(
            "INFO Fracture Preview result received",
            "\n".join(
                (
                    f"piece_count={preview.plan.actual_piece_count}",
                    f"prototype_count={len(preview.prototypes)}",
                    f"instance_count={len(preview.instances)}",
                )
            ),
        )
        self._trace(
            "job.result",
            job="fracture_preview",
            message="Fracture Preview result received",
            data={
                "piece_count": preview.plan.actual_piece_count,
                "prototype_count": len(preview.prototypes),
                "instance_count": len(preview.instances),
            },
        )
        self._append_runtime_log("INFO Fracture Preview preparing viewport mesh")
        self._trace("viewport.prepare", job="fracture_preview", message="Fracture Preview preparing viewport mesh")
        dialog.set_preview(preview)
        viewport_mesh = dialog.viewport_mesh
        if viewport_mesh is not None:
            self._append_runtime_log(
                "INFO Fracture Preview viewport mesh ready",
                "\n".join(
                    (
                        f"piece_count={viewport_mesh.piece_count}",
                        f"instance_count={viewport_mesh.instance_count}",
                        f"uploaded_triangles={viewport_mesh.uploaded_triangle_count}",
                        f"logical_triangles={viewport_mesh.triangle_count}",
                    )
                ),
            )
            self._trace(
                "viewport.upload",
                job="fracture_preview",
                message="Fracture Preview viewport mesh ready",
                data={
                    "piece_count": viewport_mesh.piece_count,
                    "instance_count": viewport_mesh.instance_count,
                    "uploaded_triangles": viewport_mesh.uploaded_triangle_count,
                    "logical_triangles": viewport_mesh.triangle_count,
                },
            )
        self._set_status(f"Fracture Preview ready: {preview.plan.actual_piece_count} piece(s).")
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _handle_fracture_preview_error_message(self, message: str) -> None:
        if self._fracture_preview_dialog is not None:
            self._fracture_preview_dialog.set_error("Preview generation failed. See log for details.")

    def _handle_fracture_preview_settings_changed(self, settings: FracturePreviewSettings) -> None:
        self._fracture_preview_settings = settings
        self.geometry_panel.apply_fracture_preview_settings(settings)
        if self._background_jobs.fracture_preview_running:
            self._background_jobs.cancel_fracture_preview()
        try:
            request = self._build_fracture_preview_request()
        except ValueError as exc:
            self._report_error("Missing input", str(exc))
            return
        self._append_runtime_log(
            "INFO Fracture Preview settings changed",
            "\n".join(
                (
                    f"method={settings.fracture.method}",
                    f"target_piece_count={settings.fracture.target_piece_count}",
                    f"preview_polycount={settings.final_polycount}",
                    f"preview_base_priority={settings.base_mesh_priority}",
                )
            ),
        )
        self._background_jobs.start_fracture_preview(request, settings)

    def run_generate_proxy_mesh(self) -> None:
        self._source_refresh_timer.stop()
        self._proxy_mesh_settings = self.geometry_panel.proxy_settings()
        try:
            request = self._build_proxy_source_request()
        except ValueError as exc:
            self._report_error("Missing input", str(exc))
            return
        proxy = self._current_preview_proxy_for_export(request.input_path, self._proxy_mesh_settings)
        if proxy is not None:
            self._background_jobs.start_generated_proxy_mesh_export(request, proxy)
            return
        self._background_jobs.start_proxy_mesh_export(request, self._proxy_mesh_settings)

    def run_export_fracture_usda(self) -> None:
        self._source_refresh_timer.stop()
        try:
            plan = self._prepare_current_conversion_plan()
        except ValueError as exc:
            self._report_conversion_plan_error(exc)
            return
        settings = self._fracture_preview_settings.fracture
        self._background_jobs.start_fracture_export(
            FractureExportRequest.from_conversion_request(plan.request),
            settings,
        )

    def _proxy_preview_result_for_input(self, input_path: str) -> ProxyMeshResult | None:
        if self._proxy_mesh_preview_input_path != input_path:
            return None
        return self._proxy_mesh_preview_result

    def _current_preview_proxy_for_export(
        self,
        input_path: str,
        settings: ProxyMeshSettings,
    ) -> ProxyMeshResult | None:
        dialog = self._proxy_preview_dialog
        if (
            dialog is not None
            and dialog.isVisible()
            and dialog.current_proxy is not None
            and self._proxy_mesh_preview_input_path == input_path
            and dialog.current_proxy.settings == settings
        ):
            return dialog.current_proxy
        proxy = self._proxy_preview_result_for_input(input_path)
        if proxy is None or proxy.settings != settings:
            return None
        return proxy

    def _cache_proxy_preview_result(self, input_path: str, proxy: ProxyMeshResult) -> None:
        self._proxy_mesh_preview_input_path = input_path
        self._proxy_mesh_preview_result = proxy

    def _apply_proxy_preview_state(
        self,
        input_path: str,
        settings: ProxyMeshSettings,
        proxy: ProxyMeshResult | None,
    ) -> None:
        self._proxy_mesh_settings = settings
        self.geometry_panel.apply_proxy_settings(settings)
        if proxy is not None and proxy.settings == settings:
            self._cache_proxy_preview_result(input_path, proxy)
        else:
            self._proxy_mesh_preview_result = None
            self._proxy_mesh_preview_input_path = ""
        self._schedule_operator_state_save()

    def _handle_proxy_mesh_export_result(self, result) -> None:
        self._set_status(f"Wrote Proxy Mesh USDA to {result.output_path}")
        self._append_log(f"Proxy Mesh complete\nWrote Proxy Mesh USDA to {result.output_path}")

    def _handle_fracture_export_result(self, result) -> None:
        output_count = len(result.outputs)
        output_lines = "\n".join(output.output_path for output in result.outputs)
        self._set_status(f"Wrote {output_count} Fracture USDA piece(s).")
        self._append_log(
            f"Fracture export complete\n"
            f"Pieces: {result.plan.actual_piece_count}\n"
            f"{output_lines}"
        )

    def _record_proxy_preview_error(self, message: str) -> None:
        self._append_log(f"Proxy Mesh preview error\n{message}")
        self._append_runtime_log("ERROR Proxy Mesh preview failed", message)

    def _build_proxy_source_request(self) -> ProxyMeshSourceRequest:
        return prepare_proxy_mesh_source_request(
            input_path=self.source_input.text(),
            output_path=self.output_input.text().strip(),
            output_mode=OutputMode.SELF_CONTAINED,
            cpu_profile=self._operator_state.cpu_profile,
            fbx_cache_max_bytes=self._fbx_cache_max_bytes(),
            fbx_cache_max_age_seconds=self._fbx_cache_max_age_seconds(),
        )

    def _build_fracture_preview_request(self) -> FracturePreviewSourceRequest:
        return prepare_fracture_preview_source_request(
            input_path=self.source_input.text(),
            output_path=self.output_input.text().strip(),
            cpu_profile=self._operator_state.cpu_profile,
        )

    def cancel_conversion(self) -> None:
        self._background_jobs.cancel_conversion()

    def _current_cleanup_policy(self) -> CleanupPolicy:
        return CleanupPolicy.PRESERVE_FOR_DEBUGGING if self._operator_state.preserve_temp_files else CleanupPolicy.EPHEMERAL

    def _set_conversion_running(self, active: bool) -> None:
        self._conversion_running = active
        self._update_action_state()

    def _set_wind_refresh_running(self, active: bool) -> None:
        self._wind_refresh_running = active
        self._update_action_state()

    def _set_wind_json_running(self, active: bool) -> None:
        self._wind_json_running = active
        self._update_action_state()

    def _clear_pending_generate_after_refresh(self) -> None:
        self._pending_generate_after_refresh = False

    def _handle_wind_data_loaded(self, dynamic_wind, *, used_retry: bool) -> None:
        self._current_dynamic_wind = dynamic_wind
        self.wind_panel.rebuild(dynamic_wind.simulation_groups)
        self._set_status(f"Loaded {len(dynamic_wind.simulation_groups)} wind groups.")
        summary = format_wind_group_summary(dynamic_wind)
        if used_retry:
            summary = f"{summary}\n\nBackground worker failed once and succeeded on retry."
        self._set_log(summary)
        self._refresh_state_cards()
        self._update_action_state()
        self._schedule_operator_state_save()
        if self._pending_generate_after_refresh:
            self._pending_generate_after_refresh = False
            self.run_generate_wind_json()

    def _handle_wind_json_result(self, result) -> None:
        self._set_status(f"Wrote Dynamic Wind JSON to {result.output_path}")
        self._set_log(format_wind_json_result(result))
        self._append_log(f"Wind JSON complete\nWrote Dynamic Wind JSON to {result.output_path}")

    def toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
            if self._restore_geometry.width() > 0 and self._restore_geometry.height() > 0:
                self.setGeometry(self._restore_geometry)
        else:
            current_geometry = self.geometry()
            if current_geometry.width() > 0 and current_geometry.height() > 0:
                self._restore_geometry = QRect(current_geometry)
            self.showMaximized()
        self._update_window_shape()
        self._apply_native_corner_preference()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._connect_screen_scale_updates()
        self._refresh_runtime_scale_for_current_screen()
        self._apply_native_corner_preference()
        self._sync_help_overlay_geometry()
        self._position_help_callout()
        QTimer.singleShot(0, self._refresh_layout_after_show)

    def moveEvent(self, event) -> None:  # type: ignore[override]
        super().moveEvent(event)
        if not self.isMaximized():
            self._restore_geometry = QRect(self.geometry())

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if not self.isMaximized():
            self._restore_geometry = QRect(self.geometry())
        self._update_panel_metrics()
        self._sync_help_overlay_geometry()
        self._apply_help_prompt_state()
        self.panel.update()
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        full_rect = QRectF(self.rect())
        border_rect = full_rect.adjusted(0.5, 0.5, -0.5, -0.5)
        if not self.isMaximized():
            path = QPainterPath()
            path.addRoundedRect(full_rect, self._theme.radii["window"], self._theme.radii["window"])
            painter.setClipPath(path)
        _draw_cover_pixmap(painter, self.rect(), self._assets.background)
        if not self.isMaximized():
            painter.setClipping(False)
            border_color = QColor(str(self._theme.glass["border_color"]))
            border_color.setAlphaF(border_color.alphaF() * float(self._theme.glass.get("border_opacity", 0.45)))
            pen = QPen(border_color)
            pen.setWidthF(float(self._theme.border_widths.get("panel", 1)))
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(border_rect, self._theme.radii["window"], self._theme.radii["window"])

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if not self.isMaximized():
            self._update_cursor_for_position(event.position().toPoint())
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and not self.isMaximized():
            edges = self._hit_test_edges(event.position().toPoint())
            if edges != Qt.Edge(0) and self.windowHandle() is not None:
                self._active_resize_edges = edges
                self.windowHandle().startSystemResize(edges)
                event.accept()
                return
        super().mousePressEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        if not self.isMaximized():
            self.unsetCursor()
        super().leaveEvent(event)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._source_refresh_timer.stop()
        self._settings_save_timer.stop()
        if self._proxy_preview_dialog is not None:
            self._proxy_preview_dialog.close()
        self._save_operator_state()
        self._background_jobs.shutdown()
        geometry = self.normalGeometry() if self.isMaximized() else self.geometry()
        save_ui_shell_state(
            UiShellState(
                x=geometry.x(),
                y=geometry.y(),
                width=geometry.width(),
                height=geometry.height(),
                is_maximized=self.isMaximized(),
                theme_name=self._design_theme.name,
                help_prompt_dismissed=self._state.help_prompt_dismissed,
                help_prompt_build_signature=self._build_signature,
                active_tab_name=self.tabs.tabText(self.tabs.currentIndex()),
            ),
            self._state_path,
        )
        super().closeEvent(event)

    def _hit_test_edges(self, position: QPoint):
        margin = self.EDGE_RESIZE_MARGIN
        rect = self.rect()
        edges = Qt.Edge(0)
        if position.x() <= margin:
            edges |= Qt.Edge.LeftEdge
        elif position.x() >= rect.width() - margin:
            edges |= Qt.Edge.RightEdge
        if position.y() <= margin:
            edges |= Qt.Edge.TopEdge
        elif position.y() >= rect.height() - margin:
            edges |= Qt.Edge.BottomEdge
        return edges

    def _update_cursor_for_position(self, position: QPoint) -> None:
        edges = self._hit_test_edges(position)
        if edges in {Qt.Edge.LeftEdge, Qt.Edge.RightEdge}:
            self.setCursor(QCursor(Qt.CursorShape.SizeHorCursor))
        elif edges in {Qt.Edge.TopEdge, Qt.Edge.BottomEdge}:
            self.setCursor(QCursor(Qt.CursorShape.SizeVerCursor))
        elif edges in {Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.Edge.RightEdge | Qt.Edge.BottomEdge}:
            self.setCursor(QCursor(Qt.CursorShape.SizeFDiagCursor))
        elif edges in {Qt.Edge.RightEdge | Qt.Edge.TopEdge, Qt.Edge.LeftEdge | Qt.Edge.BottomEdge}:
            self.setCursor(QCursor(Qt.CursorShape.SizeBDiagCursor))
        else:
            self.unsetCursor()

    def _update_window_shape(self) -> None:
        maximized = self.isMaximized()
        self.title_bar.setProperty("maximized", maximized)
        self._apply_title_bar_style(maximized)
        self.title_bar.style().unpolish(self.title_bar)
        self.title_bar.style().polish(self.title_bar)
        self.update()

    def _update_panel_metrics(self) -> None:
        horizontal_padding = int(self._theme.spacing["outer_margin"]) * 2
        available_width = max(0, self.width() - horizontal_padding)
        minimum_width = int(self._theme.layout.get("panel_min_width", 860))
        preferred_width = int(self._theme.layout.get("panel_preferred_width", 1000))
        maximum_width = int(self._theme.layout.get("panel_max_width", 1180))
        target_width = min(preferred_width, maximum_width, available_width)
        if available_width >= minimum_width:
            target_width = max(minimum_width, target_width)
        else:
            target_width = available_width
        if target_width > 0:
            self.panel.setFixedWidth(target_width)

    def _apply_title_bar_style(self, maximized: bool) -> None:
        radius = 0 if maximized else self._theme.radii["window"]
        self.title_bar.setStyleSheet(
            "\n".join(
                (
                    "QFrame#TitleBar {",
                    f"  background: {self._theme.chrome['titlebar_fill']};",
                    f"  border-top-left-radius: {radius}px;",
                    f"  border-top-right-radius: {radius}px;",
                    "  border-bottom-left-radius: 0px;",
                    "  border-bottom-right-radius: 0px;",
                    f"  min-height: {self._theme.control_heights['titlebar']}px;",
                    "}",
                )
            )
        )

    def _apply_native_corner_preference(self) -> None:
        if os.name != "nt":
            return
        window_handle = self.windowHandle()
        if window_handle is None:
            return
        try:
            from ctypes import WinDLL, byref, c_int, c_void_p, sizeof

            hwnd = int(window_handle.winId())
            dwmapi = WinDLL("dwmapi", use_last_error=True)
            preference = c_int(self._DWMWCP_DONOTROUND)
            result = dwmapi.DwmSetWindowAttribute(
                c_void_p(hwnd),
                self._DWMWA_WINDOW_CORNER_PREFERENCE,
                byref(preference),
                sizeof(preference),
            )
            if result == 0:
                self._native_corner_preference_applied = True
        except Exception:
            return

    def _panel_background_slice(self, panel_geometry: QRect) -> QPixmap | None:
        if self._assets.panel_blur.isNull():
            return None
        clipped = panel_geometry.intersected(self.rect())
        if clipped.isEmpty() or self.width() <= 0 or self.height() <= 0:
            return None
        blur_window_source = self._scaled_source_rect_for_blur(self._current_background_source_rect())
        scale_x = blur_window_source.width() / max(1, self.width())
        scale_y = blur_window_source.height() / max(1, self.height())
        left = blur_window_source.left() + int(round(clipped.left() * scale_x))
        top = blur_window_source.top() + int(round(clipped.top() * scale_y))
        width = max(1, int(round(clipped.width() * scale_x)))
        height = max(1, int(round(clipped.height() * scale_y)))
        right = min(self._assets.panel_blur.width(), left + width)
        bottom = min(self._assets.panel_blur.height(), top + height)
        source = QRect(left, top, max(1, right - left), max(1, bottom - top))
        return self._assets.panel_blur.copy(source).scaled(
            panel_geometry.size(),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _current_background_source_rect(self) -> QRect:
        return QRect(
            *compute_cover_source_rect(
                self._assets.background.width(),
                self._assets.background.height(),
                self.width(),
                self.height(),
            )
        )

    def _scaled_source_rect_for_blur(self, source_rect: QRect) -> QRect:
        if self._assets.panel_blur.isNull():
            return QRect(0, 0, 1, 1)
        if self._assets.background.isNull():
            return QRect(
                0,
                0,
                max(1, self._assets.panel_blur.width()),
                max(1, self._assets.panel_blur.height()),
            )
        scale_x = self._assets.panel_blur.width() / max(1, self._assets.background.width())
        scale_y = self._assets.panel_blur.height() / max(1, self._assets.background.height())
        left = max(0, int(round(source_rect.left() * scale_x)))
        top = max(0, int(round(source_rect.top() * scale_y)))
        width = max(1, int(round(source_rect.width() * scale_x)))
        height = max(1, int(round(source_rect.height() * scale_y)))
        right = min(self._assets.panel_blur.width(), left + width)
        bottom = min(self._assets.panel_blur.height(), top + height)
        return QRect(left, top, max(1, right - left), max(1, bottom - top))


def _draw_cover_pixmap(painter: QPainter, target_rect: QRect, pixmap: QPixmap) -> None:
    if pixmap.isNull():
        painter.fillRect(target_rect, QColor("#2C3421"))
        return
    source_rect = compute_cover_source_rect(
        pixmap.width(),
        pixmap.height(),
        target_rect.width(),
        target_rect.height(),
    )
    painter.drawPixmap(target_rect, pixmap, QRect(*source_rect))

