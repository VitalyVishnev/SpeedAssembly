from __future__ import annotations

from xml_to_usda.qt_ui.persistence import (
    UiShellState,
    load_ui_shell_state,
    load_ui_theme_overrides,
    save_ui_shell_state,
    save_ui_theme_overrides,
)
from xml_to_usda.qt_ui.theme import ThemeOverrides


def test_ui_shell_state_round_trip(tmp_path) -> None:
    path = tmp_path / "ui_next_state.json"
    expected = UiShellState(
        x=10,
        y=20,
        width=1440,
        height=900,
        is_maximized=True,
        theme_name="default",
        active_tab_name="Materials",
    )

    save_ui_shell_state(expected, path)
    restored = load_ui_shell_state(path)

    assert restored == expected


def test_ui_shell_state_invalid_json_falls_back_to_defaults(tmp_path) -> None:
    path = tmp_path / "ui_next_state.json"
    path.write_text("{broken", encoding="utf-8")

    restored = load_ui_shell_state(path)

    assert restored == UiShellState()


def test_ui_theme_overrides_round_trip(tmp_path) -> None:
    path = tmp_path / "ui_next_theme_overrides.json"
    expected = ThemeOverrides(
        theme_name="default",
        payload={"glass": {"tint_opacity": 0.35}, "layout": {"panel_preferred_width": 980}},
    )

    save_ui_theme_overrides(expected, path)
    restored = load_ui_theme_overrides(path)

    assert restored == expected


def test_ui_theme_overrides_invalid_json_falls_back_to_empty(tmp_path) -> None:
    path = tmp_path / "ui_next_theme_overrides.json"
    path.write_text("{broken", encoding="utf-8")

    restored = load_ui_theme_overrides(path)

    assert restored == ThemeOverrides(theme_name="default", payload={})
