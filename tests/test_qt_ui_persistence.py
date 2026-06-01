from __future__ import annotations

import pytest

pytestmark = pytest.mark.qt

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


def test_ui_shell_state_resets_help_prompt_for_new_build(tmp_path) -> None:
    state_path = tmp_path / "ui_next_state.json"
    build_info_path = tmp_path / "build_info.json"
    expected = UiShellState(
        help_prompt_dismissed=True,
        help_prompt_build_signature="release|old|2026-01-01 00:00:00 +00:00|app.exe",
    )
    build_info_path.write_text(
        (
            "{"
            '"build_mode": "release", '
            '"git_head": "new", '
            '"built_at": "2026-06-01 10:00:00 +00:00", '
            '"exe_path": "app.exe"'
            "}"
        ),
        encoding="utf-8",
    )

    save_ui_shell_state(expected, state_path)
    restored = load_ui_shell_state(state_path, build_info_path=build_info_path)

    assert restored.help_prompt_dismissed is False
    assert restored.help_prompt_build_signature == "release|new|2026-06-01 10:00:00 +00:00|app.exe"


def test_ui_shell_state_resets_help_prompt_when_build_info_has_bom(tmp_path) -> None:
    state_path = tmp_path / "ui_next_state.json"
    build_info_path = tmp_path / "build_info.json"
    save_ui_shell_state(
        UiShellState(
            help_prompt_dismissed=True,
            help_prompt_build_signature="release|old|2026-01-01 00:00:00 +00:00|app.exe",
        ),
        state_path,
    )
    build_info_path.write_text(
        (
            "{"
            '"build_mode": "release", '
            '"git_head": "bom", '
            '"built_at": "2026-06-01 10:00:00 +00:00", '
            '"exe_path": "app.exe"'
            "}"
        ),
        encoding="utf-8-sig",
    )

    restored = load_ui_shell_state(state_path, build_info_path=build_info_path)

    assert restored.help_prompt_dismissed is False
    assert restored.help_prompt_build_signature == "release|bom|2026-06-01 10:00:00 +00:00|app.exe"


def test_ui_shell_state_resets_help_prompt_from_current_build_signature(tmp_path) -> None:
    state_path = tmp_path / "ui_next_state.json"
    save_ui_shell_state(
        UiShellState(
            help_prompt_dismissed=True,
            help_prompt_build_signature="release|old|2026-01-01 00:00:00 +00:00|app.exe",
        ),
        state_path,
    )

    restored = load_ui_shell_state(state_path, current_build_signature="exe|123|456")

    assert restored.help_prompt_dismissed is False
    assert restored.help_prompt_build_signature == "exe|123|456"


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
