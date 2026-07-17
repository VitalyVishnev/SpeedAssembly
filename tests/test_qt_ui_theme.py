from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.qt

from xml_to_usda.qt_ui.theme import (
    ThemeOverrides,
    bake_theme_payload,
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
