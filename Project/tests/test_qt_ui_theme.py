from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QFontInfo
from PySide6.QtWidgets import QCheckBox, QLabel, QPlainTextEdit, QTabWidget, QWidget

pytestmark = pytest.mark.qt

from xml_to_usda.qt_ui.dependencies import build_default_dependencies
from xml_to_usda.qt_ui.persistence import UiShellState
from xml_to_usda.qt_ui.window import MainWindow, RoundedTabBar
from xml_to_usda.qt_ui.widget_style import install_widget_style
from xml_to_usda.qt_ui.theme import (
    ThemeOverrides,
    bake_theme_payload,
    build_ui_palette,
    build_stylesheet,
    compute_cover_source_rect,
    compute_screen_scale,
    load_bundled_theme,
    load_theme,
    merge_theme,
    resolve_theme_asset,
    scale_theme_for_runtime,
    theme_to_payload,
)


def test_default_theme_assets_resolve() -> None:
    theme = load_theme()

    assert theme.name == "default"
    assert Path(resolve_theme_asset(theme, theme.background_image)).exists()
    assert Path(resolve_theme_asset(theme, theme.background_blur_image)).exists()
    assert build_ui_palette(theme)["success_fill"] == "#3F7D4A"


def test_theme_geometry_scales_and_crops_with_readability_bounds() -> None:
    assert compute_cover_source_rect(2000, 1000, 800, 800) == (500, 0, 1000, 1000)
    assert compute_cover_source_rect(1000, 2000, 800, 800) == (0, 0, 1000, 1000)
    assert compute_screen_scale(1280, 720) == pytest.approx(0.90)
    assert compute_screen_scale(5120, 2880) == pytest.approx(1.75)


def test_theme_override_changes_runtime_copy_without_mutating_bundle() -> None:
    bundled = load_bundled_theme()
    merged = merge_theme(
        bundled,
        ThemeOverrides(theme_name="default", payload={"glass": {"tint_opacity": 0.35}}),
    )

    scaled = scale_theme_for_runtime(merged, 1.25)
    assert merged.glass["tint_opacity"] == pytest.approx(0.35)
    assert bundled.glass["tint_opacity"] != pytest.approx(0.35)
    assert scaled.layout["panel_preferred_width"] == 1224
    with pytest.raises(ValueError, match="unknown key"):
        merge_theme(bundled, ThemeOverrides(theme_name="default", payload={"glass": {"unknown": 1}}))


def test_theme_payload_bakes_and_stylesheet_uses_shared_control_colors(tmp_path) -> None:
    theme = load_theme(
        overrides=ThemeOverrides(
            theme_name="default",
            payload={"colors": {"control_fill": "#445566", "control_hover_fill": "#778899"}},
        )
    )
    snapshot_path = tmp_path / "snapshot.json"
    target_path = tmp_path / "theme.json"
    snapshot_path.write_text(json.dumps(theme_to_payload(theme)), encoding="utf-8")

    bake_theme_payload(snapshot_path=snapshot_path, target_theme_path=target_path)

    assert json.loads(target_path.read_text(encoding="utf-8"))["name"] == "default"
    stylesheet = build_stylesheet(theme)
    assert "QPushButton#FileButton" in stylesheet
    assert "#445566" in stylesheet
    assert "#778899" in stylesheet


def test_checkbox_click_paints_final_state_without_transition(qtbot) -> None:
    install_widget_style()
    checkbox = QCheckBox("Immediate checkbox")
    checkbox.setStyleSheet(build_stylesheet(load_theme()))
    qtbot.addWidget(checkbox)
    checkbox.show()
    qtbot.wait(220)
    previous_image = checkbox.grab().toImage()

    for checked in (True, False, True):
        qtbot.mouseClick(checkbox, Qt.MouseButton.LeftButton)
        assert checkbox.isChecked() is checked
        immediate_image = checkbox.grab().toImage()
        qtbot.wait(220)
        assert immediate_image == checkbox.grab().toImage()
        assert immediate_image != previous_image
        previous_image = immediate_image


@pytest.mark.parametrize("scale", (1.0, 1.75))
def test_main_tab_bar_paints_rounded_corners_at_runtime_scale(qtbot, scale: float) -> None:
    tabs = QTabWidget()
    tab_bar = RoundedTabBar(tabs)
    tabs.setTabBar(tab_bar)
    for label in ("Wind", "Geometry", "Materials"):
        tabs.addTab(QWidget(), label)

    theme = scale_theme_for_runtime(load_theme(), scale)
    tabs.setStyleSheet(build_stylesheet(theme))
    tab_bar.apply_theme(theme)
    tabs.resize(800, 480)
    qtbot.addWidget(tabs)
    tabs.show()

    image = tab_bar.grab().toImage()
    first_tab_rect = tab_bar.tabRect(0)
    gap_center_x = first_tab_rect.right() - tab_bar._tab_gap // 2
    device_pixel_ratio = image.devicePixelRatio()
    assert image.pixelColor(first_tab_rect.topLeft()) != tab_bar._selected_fill
    assert image.pixelColor(round(gap_center_x * device_pixel_ratio), round(device_pixel_ratio)) != tab_bar._selected_fill


def test_main_shell_corners_follow_external_window_state_changes(qtbot, tmp_path) -> None:
    window = MainWindow(
        load_theme(),
        UiShellState(help_prompt_dismissed=True),
        dependencies=build_default_dependencies(),
        state_path=tmp_path / "ui_state.json",
        operator_settings_path=tmp_path / "operator_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    # Caption marks center their visible ink, independently of font metrics.
    mark_bounds = {}
    for button in (window.title_bar.minimize_button, window.title_bar.maximize_button, window.title_bar.close_button):
        image = button.grab().toImage()
        ink = [
            (x, y)
            for y in range(image.height())
            for x in range(image.width())
            if image.pixelColor(x, y).alpha() > 128 and max(image.pixelColor(x, y).getRgb()[:3]) < 80
        ]
        assert ink
        left, right = min(x for x, _ in ink), max(x for x, _ in ink)
        top, bottom = min(y for _, y in ink), max(y for _, y in ink)
        assert abs((left + right) / 2 - (image.width() - 1) / 2) <= 1
        if button is not window.title_bar.minimize_button:
            assert abs((top + bottom) / 2 - (image.height() - 1) / 2) <= 1
        mark_bounds[button] = bottom
    assert abs(mark_bounds[window.title_bar.minimize_button] - mark_bounds[window.title_bar.maximize_button]) <= 1

    # Windows shortcuts and saved state bypass the custom maximize button.
    for state in (Qt.WindowState.WindowMaximized, Qt.WindowState.WindowFullScreen):
        window.setWindowState(state)
        qtbot.waitUntil(lambda: window.title_bar.property("windowExpanded") is True)
        assert "border-top-left-radius: 0px" in window.title_bar.styleSheet()
        assert window.grab().toImage().pixelColor(0, 0).alpha() == 255

        window.showNormal()
        qtbot.waitUntil(lambda: window.title_bar.property("windowExpanded") is False)
        assert f"border-top-left-radius: {window._theme.radii['window']}px" in window.title_bar.styleSheet()
        assert window.grab().toImage().pixelColor(0, 0).alpha() == 0


@pytest.mark.parametrize("scale", (0.90, 1.0, 1.75))
def test_typography_roles_scale_without_resizing_approved_caption_controls(qtbot, tmp_path, scale) -> None:
    # Older presets carry title=11. Headings have their own role, and text
    # adjustments must not undo the operator-approved caption/icon geometry.
    theme = scale_theme_for_runtime(load_theme(overrides=ThemeOverrides(
        theme_name="default", payload={"font_sizes": {"title": 11}},
    )), scale)
    host = QWidget()
    qtbot.addWidget(host)
    host.setStyleSheet(build_stylesheet(theme))
    for role, token, weight in (
        ("heading", "heading", QFont.Weight.DemiBold),
        ("section", "section", QFont.Weight.DemiBold),
        ("group", "body", QFont.Weight.DemiBold),
        ("supporting", "small", QFont.Weight.Normal),
    ):
        label = QLabel("Настройки / Settings 814", host)
        label.setProperty("typographyRole", role)
        label.ensurePolished()
        assert label.font().pixelSize() == theme.font_sizes[token]
        assert label.font().weight() == weight
        if "Segoe UI" in QFontDatabase.families():
            assert QFontInfo(label.font()).family() == "Segoe UI"
    editor = QPlainTextEdit(host)
    editor.ensurePolished()
    assert editor.font().pixelSize() == theme.font_sizes["code"]
    assert QFontInfo(editor.font()).fixedPitch()

    window = MainWindow(load_theme(), UiShellState(help_prompt_dismissed=True),
                        dependencies=build_default_dependencies(),
                        state_path=tmp_path / "state.json",
                        operator_settings_path=tmp_path / "operator.json")
    qtbot.addWidget(window)
    window.title_bar.apply_theme(theme)
    window.setStyleSheet(build_stylesheet(theme))
    original_size = window.title_bar.close_button.size()
    original_mark = window.title_bar.close_button.iconSize()
    original_gear = window.title_bar.settings_button.size()
    larger_text = scale_theme_for_runtime(load_theme(overrides=ThemeOverrides(
        theme_name="default", payload={"font_sizes": {"small": 20}},
    )), scale)
    window.title_bar.apply_theme(larger_text)
    window.setStyleSheet(build_stylesheet(larger_text))
    assert window.title_bar.close_button.size() == original_size
    assert window.title_bar.close_button.iconSize() == original_mark
    assert window.title_bar.settings_button.size() == original_gear
