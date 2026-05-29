from __future__ import annotations

import json
from pathlib import Path

import pytest

from xml_to_usda.qt_ui.theme import (
    ThemeOverrides,
    bake_theme_payload,
    build_stylesheet,
    build_ui_palette,
    compute_screen_scale,
    compute_cover_source_rect,
    load_bundled_theme,
    load_theme,
    merge_theme,
    resolve_theme_asset,
    scale_theme_for_runtime,
    theme_to_payload,
)


def test_load_theme_reads_default_bundle() -> None:
    theme = load_theme()

    assert theme.name == "default"
    assert theme.display_name
    assert theme.background_image
    assert theme.background_blur_image
    assert "noise_assets" in theme.assets


def test_resolve_theme_asset_returns_existing_path() -> None:
    theme = load_theme()

    background_path = resolve_theme_asset(theme, theme.background_image)
    blur_path = resolve_theme_asset(theme, theme.background_blur_image)

    assert Path(background_path).exists()
    assert Path(blur_path).exists()


def test_compute_cover_source_rect_crops_horizontally() -> None:
    assert compute_cover_source_rect(2000, 1000, 800, 800) == (500, 0, 1000, 1000)


def test_compute_cover_source_rect_crops_vertically() -> None:
    assert compute_cover_source_rect(1000, 2000, 800, 800) == (0, 0, 1000, 1000)


def test_compute_screen_scale_keeps_reference_screen_at_current_size() -> None:
    assert compute_screen_scale(2048, 1104) == pytest.approx(1.0)


def test_compute_screen_scale_uses_readability_floor_for_full_hd() -> None:
    assert compute_screen_scale(1920, 1080) == pytest.approx(0.9375)
    assert compute_screen_scale(1280, 720) == pytest.approx(0.90)


def test_compute_screen_scale_caps_very_large_monitors() -> None:
    assert compute_screen_scale(5120, 2880) == pytest.approx(1.75)


def test_merge_theme_applies_overrides() -> None:
    bundled = load_bundled_theme()

    merged = merge_theme(
        bundled,
        ThemeOverrides(
            theme_name="default",
            payload={"glass": {"tint_opacity": 0.35}, "layout": {"panel_preferred_width": 980}},
        ),
    )

    assert merged.glass["tint_opacity"] == 0.35
    assert merged.layout["panel_preferred_width"] == 980
    assert bundled.layout["panel_preferred_width"] != 980


def test_scale_theme_for_runtime_scales_layout_without_mutating_base_theme() -> None:
    theme = load_theme()

    scaled = scale_theme_for_runtime(theme, 1.25)

    assert scaled.layout["panel_preferred_width"] == 1224
    assert scaled.control_heights["button"] == 55
    assert scaled.font_sizes["body"] == 16
    assert scaled.glass["light_gradient_height"] == theme.glass["light_gradient_height"]
    assert theme.layout["panel_preferred_width"] == 979
    assert theme.control_heights["button"] == 44


def test_bake_theme_payload_overwrites_target_theme(tmp_path) -> None:
    source_theme = load_theme()
    snapshot_path = tmp_path / "snapshot.json"
    target_path = tmp_path / "theme.json"
    payload = theme_to_payload(source_theme)
    payload["glass"]["noise_asset"] = "assets/BlueNoise256.png"
    snapshot_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    bake_theme_payload(snapshot_path=snapshot_path, target_theme_path=target_path)

    baked = json.loads(target_path.read_text(encoding="utf-8"))
    assert baked["glass"]["noise_asset"] == "assets/BlueNoise256.png"


def test_merge_theme_rejects_unknown_override_fields() -> None:
    bundled = load_bundled_theme()

    with pytest.raises(ValueError, match="unknown key"):
        merge_theme(
            bundled,
            ThemeOverrides(theme_name="default", payload={"glass": {"made_up_knob": 1}}),
        )


def test_primary_action_button_uses_theme_button_fill() -> None:
    theme = load_theme(
        overrides=ThemeOverrides(
            theme_name="default",
            payload={"colors": {"button_fill": "#123456", "danger_fill": "#654321"}},
        )
    )

    stylesheet = build_stylesheet(theme)

    assert "QPushButton#PrimaryActionButton" in stylesheet
    assert "#123456" in stylesheet
    assert "rgba(101, 67, 33" in stylesheet
    assert "rgba(109, 115, 64, 0.94)" not in stylesheet


def test_ui_palette_exposes_shared_control_tokens() -> None:
    palette = build_ui_palette(load_theme())

    assert palette["control_fill"] == "#DDBB64"
    assert palette["control_hover_fill"] == "#BF8C4E"
    assert palette["chrome_control_fill"] == "rgba(220, 229, 232, 0.878)"
    assert palette["path_input_fill"] == "rgba(183, 197, 201, 0.722)"


def test_shared_controls_use_one_hover_color() -> None:
    theme = load_theme(
        overrides=ThemeOverrides(
            theme_name="default",
            payload={
                "colors": {
                    "control_fill": "#445566",
                    "control_hover_fill": "#778899",
                    "chrome_control_fill": "#AABBCC",
                    "chrome_control_hover_fill": "#778899",
                }
            },
        )
    )

    stylesheet = build_stylesheet(theme)

    assert "QPushButton#FileButton" in stylesheet
    assert "QComboBox#InteractiveCombo" in stylesheet
    assert "QPushButton#WindRefreshButton" in stylesheet
    assert stylesheet.count("background: #445566;") >= 3
    assert stylesheet.count("background: #778899;") >= 6
