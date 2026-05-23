"""Persistence helpers for the PySide6 shell."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .theme import ThemeOverrides


@dataclass(frozen=True)
class UiShellState:
    x: int = 120
    y: int = 80
    width: int = 1360
    height: int = 860
    is_maximized: bool = False
    theme_name: str = "default"
    help_prompt_dismissed: bool = False


def default_ui_state_path() -> Path:
    return Path.home() / ".xml_to_usda" / "ui_next_state.json"


def default_ui_theme_overrides_path() -> Path:
    return Path.home() / ".xml_to_usda" / "ui_next_theme_overrides.json"


def default_ui_theme_export_path() -> Path:
    return Path.home() / ".xml_to_usda" / "ui_next_theme_export.json"


def load_ui_shell_state(path: str | Path | None = None) -> UiShellState:
    state_path = Path(path) if path is not None else default_ui_state_path()
    if not state_path.exists():
        return UiShellState()
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return UiShellState()
    return UiShellState(
        x=int(payload.get("x", 120)),
        y=int(payload.get("y", 80)),
        width=max(960, int(payload.get("width", 1360))),
        height=max(640, int(payload.get("height", 860))),
        is_maximized=bool(payload.get("is_maximized", False)),
        theme_name=str(payload.get("theme_name", "default")),
        help_prompt_dismissed=bool(payload.get("help_prompt_dismissed", False)),
    )


def save_ui_shell_state(state: UiShellState, path: str | Path | None = None) -> None:
    state_path = Path(path) if path is not None else default_ui_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")


def load_ui_theme_overrides(path: str | Path | None = None) -> ThemeOverrides:
    overrides_path = Path(path) if path is not None else default_ui_theme_overrides_path()
    if not overrides_path.exists():
        return ThemeOverrides(theme_name="default", payload={})
    try:
        payload = json.loads(overrides_path.read_text(encoding="utf-8"))
    except Exception:
        return ThemeOverrides(theme_name="default", payload={})
    theme_name = str(payload.get("theme_name", "default"))
    nested_payload = payload.get("payload", {})
    if not isinstance(nested_payload, dict):
        return ThemeOverrides(theme_name=theme_name, payload={})
    return ThemeOverrides(theme_name=theme_name, payload=nested_payload)


def save_ui_theme_overrides(overrides: ThemeOverrides, path: str | Path | None = None) -> None:
    overrides_path = Path(path) if path is not None else default_ui_theme_overrides_path()
    overrides_path.parent.mkdir(parents=True, exist_ok=True)
    overrides_path.write_text(
        json.dumps(
            {
                "theme_name": overrides.theme_name,
                "payload": overrides.payload,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
