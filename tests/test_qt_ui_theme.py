from __future__ import annotations

import json
from pathlib import Path

import pytest

from xml_to_usda.qt_ui.theme import (
    ThemeOverrides,
    bake_theme_payload,
    build_stylesheet,
    compute_cover_source_rect,
    load_bundled_theme,
    load_theme,
    merge_theme,
    resolve_theme_asset,
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
