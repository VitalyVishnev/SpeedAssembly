"""Theme contract, merge logic, and asset loading for the PySide6 shell.

Layer: UI.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from importlib.resources import files


@dataclass(frozen=True)
class _ThemeBase:
    name: str
    display_name: str
    colors: dict[str, str]
    font_sizes: dict[str, int]
    radii: dict[str, int]
    spacing: dict[str, int]
    control_heights: dict[str, int]
    border_widths: dict[str, int]
    layout: dict[str, int]
    glass: dict[str, Any]
    chrome: dict[str, Any]
    effects: dict[str, Any]
    assets: dict[str, Any]

    @property
    def package_root(self) -> str:
        return f"xml_to_usda.qt_ui.themes.{self.name}"

    @property
    def background_image(self) -> str:
        return str(self.assets["background_image"])

    @property
    def background_blur_image(self) -> str:
        return str(self.assets["background_blur_image"])


@dataclass(frozen=True)
class ThemeSpec(_ThemeBase):
    """Bundled theme payload as authored in the repository."""


@dataclass(frozen=True)
class ResolvedTheme(_ThemeBase):
    """Final runtime theme after bundled tokens and user overrides are merged."""


@dataclass(frozen=True)
class ThemeOverrides:
    """Partial runtime overrides applied on top of a bundled theme."""

    theme_name: str
    payload: dict[str, Any]

    @property
    def is_empty(self) -> bool:
        return not bool(self.payload)


def load_bundled_theme(theme_name: str = "default") -> ThemeSpec:
    theme_path = files("xml_to_usda.qt_ui").joinpath("themes", theme_name, "theme.json")
    payload = json.loads(theme_path.read_text(encoding="utf-8"))
    _validate_theme_payload(payload)
    return _theme_from_payload(payload, cls=ThemeSpec)


def load_theme(
    theme_name: str = "default",
    *,
    overrides: ThemeOverrides | None = None,
) -> ResolvedTheme:
    bundled = load_bundled_theme(theme_name)
    return merge_theme(bundled, overrides)


def merge_theme(theme: ThemeSpec, overrides: ThemeOverrides | None = None) -> ResolvedTheme:
    merged_payload = theme_to_payload(theme)
    if overrides is not None and not overrides.is_empty:
        _validate_theme_overrides(merged_payload, overrides.payload)
        merged_payload = _deep_merge(merged_payload, overrides.payload)
    _validate_theme_payload(merged_payload)
    return _theme_from_payload(merged_payload, cls=ResolvedTheme)


def theme_to_payload(theme: _ThemeBase) -> dict[str, Any]:
    return {
        "name": theme.name,
        "display_name": theme.display_name,
        "colors": deepcopy(theme.colors),
        "font_sizes": deepcopy(theme.font_sizes),
        "radii": deepcopy(theme.radii),
        "spacing": deepcopy(theme.spacing),
        "control_heights": deepcopy(theme.control_heights),
        "border_widths": deepcopy(theme.border_widths),
        "layout": deepcopy(theme.layout),
        "glass": deepcopy(theme.glass),
        "chrome": deepcopy(theme.chrome),
        "effects": deepcopy(theme.effects),
        "assets": deepcopy(theme.assets),
    }


def write_theme_payload(path: str | Path, payload: Mapping[str, Any]) -> None:
    target_path = Path(path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def resolve_theme_asset(theme: _ThemeBase, relative_path: str) -> Path:
    if not relative_path:
        return Path()
    return Path(files("xml_to_usda.qt_ui").joinpath("themes", theme.name, relative_path))


def compute_cover_source_rect(
    image_width: int,
    image_height: int,
    target_width: int,
    target_height: int,
) -> tuple[int, int, int, int]:
    if image_width <= 0 or image_height <= 0 or target_width <= 0 or target_height <= 0:
        return (0, 0, max(1, image_width), max(1, image_height))

    image_ratio = image_width / image_height
    target_ratio = target_width / target_height
    if target_ratio > image_ratio:
        crop_height = int(round(image_width / target_ratio))
        return (0, 0, image_width, max(1, crop_height))
    crop_width = int(round(image_height * target_ratio))
    left = max(0, (image_width - crop_width) // 2)
    return (left, 0, max(1, crop_width), image_height)


def build_stylesheet(theme: ResolvedTheme) -> str:
    titlebar_fill = _css_color(theme.chrome["titlebar_fill"])
    titlebar_text = _css_color(theme.chrome["titlebar_text"])
    input_fill = _css_color(theme.colors["input_fill"])
    input_text = _css_color(theme.colors["input_text"])
    button_fill = _css_color(theme.colors["button_fill"])
    button_text = _css_color(theme.colors["button_text"])
    accent_fill = _css_color(theme.colors["accent_fill"])
    secondary_fill = _css_color(theme.colors["secondary_fill"])
    danger_fill = _css_color(theme.colors["danger_fill"])
    log_fill = _css_color(theme.colors["log_fill"])
    card_fill = _css_color(theme.colors["card_fill"])
    card_text = _css_color(theme.colors["card_text"])
    card_border = _css_color(theme.colors["card_border"])
    tab_fill = _css_color(theme.colors["tab_fill"])
    tab_selected_fill = _css_color(theme.colors["tab_selected_fill"])
    tab_hover_fill = _css_color(theme.colors["tab_hover_fill"])
    tab_text = _css_color(theme.colors["tab_text"])
    window_text = _css_color(theme.colors["window_text"])
    muted_text = _css_color(theme.colors["muted_text"])
    menu_fill = _css_color(theme.colors["card_fill"])
    menu_text = _css_color(theme.colors["card_text"])
    panel_radius = theme.radii["control"]
    button_radius = theme.radii["button"]
    tab_radius = theme.radii.get("tab", button_radius)
    window_radius = theme.radii["window"]
    card_radius = theme.radii.get("card", panel_radius)
    titlebar_height = theme.control_heights["titlebar"]
    input_height = theme.control_heights["input"]
    button_height = theme.control_heights["button"]
    file_button_width = int(theme.chrome.get("file_button_width", 74))
    file_button_height = int(theme.chrome.get("file_button_height", input_height))
    wind_refresh_button_width = int(theme.chrome.get("wind_refresh_button_width", 164))
    wind_refresh_button_height = int(theme.chrome.get("wind_refresh_button_height", 28))
    window_button_size = int(theme.chrome.get("window_button_size", 22))
    title_pill_width = int(theme.chrome.get("title_pill_width", 78))
    title_pill_height = int(theme.chrome.get("title_pill_height", 24))
    adjust_ui_button_width = int(theme.chrome.get("adjust_ui_button_width", 104))
    adjust_ui_button_height = int(theme.chrome.get("adjust_ui_button_height", title_pill_height))
    title_preset_width = int(theme.chrome.get("title_preset_width", 210))
    title_preset_height = int(theme.chrome.get("title_preset_height", window_button_size))
    tab_min_width = int(theme.layout.get("tab_min_width", 120))
    button_fill_disabled = _with_alpha(theme.colors["button_fill"], 0.42)
    accent_fill_soft = _with_alpha(theme.colors["accent_fill"], 0.35)
    secondary_fill_soft = _with_alpha(theme.colors["secondary_fill"], 0.92)
    danger_fill_soft = _with_alpha(theme.colors["danger_fill"], 0.78)

    return f"""
QWidget {{
    color: {window_text};
    font-size: {theme.font_sizes['body']}px;
}}
QWidget:focus {{
    outline: none;
}}
QWidget#ScrollContainer,
QWidget#ScrollViewport {{
    background: transparent;
}}
QWidget#AdjustUiWindow {{
    background: {card_fill};
}}
QLabel#MutedLabel {{
    color: {muted_text};
    font-size: {theme.font_sizes['small']}px;
}}
QLabel#StatusLabel {{
    color: {window_text};
    font-size: {theme.font_sizes['body']}px;
    font-weight: 600;
    padding: 6px 4px;
}}
QLabel#TitleLabel {{
    color: {titlebar_text};
    font-size: {theme.font_sizes['title']}px;
    font-weight: 600;
}}
QLabel#EditorSectionTitle {{
    color: {window_text};
    font-size: {theme.font_sizes['body']}px;
    font-weight: 600;
}}
QLineEdit {{
    background: {input_fill};
    color: {input_text};
    border-radius: {panel_radius}px;
    padding: 8px 14px;
    min-height: {input_height}px;
    border: {theme.border_widths['control']}px solid transparent;
}}
QLineEdit:hover {{
    background: {input_fill};
}}
QLineEdit#PathInput {{
    background: rgba(183, 197, 201, 0.72);
    color: {input_text};
    border-radius: {panel_radius}px;
    padding: 8px 14px;
    border: 1px solid rgba(64, 61, 48, 0.10);
}}
QLineEdit#PathInput:hover,
QLineEdit#PathInput:focus {{
    background: rgba(196, 213, 217, 0.86);
    border: 1px solid rgba(143, 150, 78, 0.42);
}}
QPushButton {{
    background: {button_fill};
    color: {button_text};
    border-radius: {button_radius}px;
    min-height: {button_height}px;
    min-width: 132px;
    padding: 6px 18px;
    border: none;
}}
QPushButton:hover {{
    background: {accent_fill};
}}
QPushButton:disabled {{
    background: {button_fill_disabled};
    color: rgba(19, 19, 15, 0.6);
}}
QFrame#TitleBar {{
    background: {titlebar_fill};
    border-top-left-radius: {window_radius}px;
    border-top-right-radius: {window_radius}px;
    border-bottom-left-radius: 0px;
    border-bottom-right-radius: 0px;
    min-height: {titlebar_height}px;
}}
QFrame#TitleBar[maximized=\"true\"] {{
    border-top-left-radius: 0px;
    border-top-right-radius: 0px;
    border-bottom-left-radius: 0px;
    border-bottom-right-radius: 0px;
}}
QFrame#PanelCard,
QFrame#EditorPanelCard {{
    background: {card_fill};
    color: {card_text};
    border-radius: {card_radius}px;
    border: {theme.border_widths.get('card', 1)}px solid {card_border};
}}
QFrame#TutorialCallout {{
    background: {accent_fill};
    color: {button_text};
    border-radius: {card_radius}px;
    border: 1px solid {secondary_fill};
}}
QLabel#TutorialCalloutTitle {{
    color: {button_text};
    font-size: {theme.font_sizes['body']}px;
    font-weight: 700;
}}
QLabel#TutorialCalloutBody {{
    color: {button_text};
    font-size: {theme.font_sizes['small']}px;
}}
QPushButton#TutorialCalloutCloseButton {{
    background: rgba(255, 255, 255, 0.24);
    color: {button_text};
    border-radius: {window_button_size // 2}px;
    min-width: {window_button_size}px;
    max-width: {window_button_size}px;
    min-height: {window_button_size}px;
    max-height: {window_button_size}px;
    padding: 0px;
    font-size: 12px;
    font-weight: 700;
}}
QPushButton#TutorialCalloutCloseButton:hover {{
    background: rgba(255, 255, 255, 0.38);
}}
QPushButton#WindowButton {{
    background: transparent;
    border-radius: {window_button_size // 2}px;
    min-width: {window_button_size}px;
    max-width: {window_button_size}px;
    min-height: {window_button_size}px;
    max-height: {window_button_size}px;
    padding: 0px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#WindowButton:hover {{
    background: {accent_fill_soft};
}}
QPushButton#CloseWindowButton {{
    background: transparent;
    border-radius: {window_button_size // 2}px;
    min-width: {window_button_size}px;
    max-width: {window_button_size}px;
    min-height: {window_button_size}px;
    max-height: {window_button_size}px;
    padding: 0px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#CloseWindowButton:hover {{
    background: {danger_fill_soft};
    color: {log_fill};
}}
QPushButton#TitlePillButton {{
    background: rgba(220, 229, 232, 0.88);
    border-radius: {button_radius}px;
    min-width: {title_pill_width}px;
    max-width: {title_pill_width}px;
    min-height: {title_pill_height}px;
    max-height: {title_pill_height}px;
}}
QPushButton#AdjustUiButton {{
    background: rgba(220, 229, 232, 0.88);
    border-radius: {button_radius}px;
    min-width: {adjust_ui_button_width}px;
    max-width: {adjust_ui_button_width}px;
    min-height: {adjust_ui_button_height}px;
    max-height: {adjust_ui_button_height}px;
}}
QPushButton#TitlePillButton:hover,
QPushButton#AdjustUiButton:hover {{
    background: {accent_fill_soft};
}}
QComboBox#TitlePresetCombo {{
    background: rgba(220, 229, 232, 0.88);
    color: {input_text};
    border-top-left-radius: {title_preset_height // 2}px;
    border-bottom-left-radius: {title_preset_height // 2}px;
    border-top-right-radius: 0px;
    border-bottom-right-radius: 0px;
    min-width: {title_preset_width}px;
    max-width: {title_preset_width}px;
    min-height: {title_preset_height}px;
    max-height: {title_preset_height}px;
    padding: 2px 8px 2px 12px;
    border: none;
}}
QComboBox#TitlePresetCombo:hover {{
    background: {accent_fill_soft};
}}
QComboBox#TitlePresetCombo::drop-down {{
    border: none;
    width: 22px;
}}
QToolButton#TitlePresetMenuButton {{
    background: rgba(220, 229, 232, 0.88);
    color: {button_text};
    border-top-left-radius: 0px;
    border-bottom-left-radius: 0px;
    border-top-right-radius: {title_preset_height // 2}px;
    border-bottom-right-radius: {title_preset_height // 2}px;
    min-width: {title_preset_height}px;
    max-width: {title_preset_height}px;
    min-height: {title_preset_height}px;
    max-height: {title_preset_height}px;
    padding: 0px;
    border: none;
}}
QToolButton#TitlePresetMenuButton:hover {{
    background: {accent_fill_soft};
}}
QToolButton#TitlePresetMenuButton::menu-indicator {{
    image: none;
    width: 0px;
}}
QPushButton#FileButton {{
    background: {secondary_fill};
    color: {button_text};
    min-width: {file_button_width}px;
    max-width: {file_button_width}px;
    min-height: {file_button_height}px;
    max-height: {file_button_height}px;
}}
QPushButton#FileButton:hover {{
    background: {secondary_fill_soft};
}}
QPushButton#PrimaryActionButton {{
    background: {button_fill};
}}
QPushButton#PrimaryActionButton:hover {{
    background: {accent_fill};
}}
QPushButton#WindRefreshButton {{
    background: {tab_fill};
    color: {tab_text};
    border-radius: {tab_radius}px;
    min-width: {wind_refresh_button_width}px;
    max-width: {wind_refresh_button_width}px;
    min-height: {wind_refresh_button_height}px;
    max-height: {wind_refresh_button_height}px;
    padding: 4px 10px;
}}
QPushButton#WindRefreshButton:hover {{
    background: {tab_hover_fill};
}}
QPushButton#WindRefreshButton:disabled {{
    background: {tab_fill};
    color: rgba(26, 26, 21, 0.58);
}}
QPushButton#SplitActionMainButton {{
    background: {button_fill};
    color: {button_text};
    border-top-left-radius: {button_radius}px;
    border-bottom-left-radius: {button_radius}px;
    border-top-right-radius: 0px;
    border-bottom-right-radius: 0px;
    min-width: 0px;
}}
QPushButton#SplitActionMainButton:hover,
QToolButton#SplitActionMenuButton:hover {{
    background: {accent_fill};
}}
QPushButton#SplitActionMainButton:disabled,
QToolButton#SplitActionMenuButton:disabled {{
    background: {button_fill_disabled};
    color: rgba(19, 19, 15, 0.6);
}}
QToolButton#SplitActionMenuButton {{
    background: {button_fill};
    color: {button_text};
    border-top-left-radius: 0px;
    border-bottom-left-radius: 0px;
    border-top-right-radius: {button_radius}px;
    border-bottom-right-radius: {button_radius}px;
    min-width: 34px;
    padding: 0px;
    border: none;
}}
QToolButton#SplitActionMenuButton::menu-indicator {{
    image: none;
    width: 0px;
}}
QMenu {{
    background: {menu_fill};
    color: {menu_text};
    border: {theme.border_widths.get('card', 1)}px solid {card_border};
    border-radius: {card_radius}px;
    padding: 6px;
}}
QMenu::item {{
    background: transparent;
    color: {menu_text};
    padding: 8px 18px;
    border-radius: {button_radius}px;
    min-height: 18px;
}}
QMenu::item:selected {{
    background: {tab_selected_fill};
    color: {button_text};
}}
QMenu::item:disabled {{
    color: {muted_text};
}}
QMenu::separator {{
    height: 1px;
    background: {card_border};
    margin: 6px 10px;
}}
QFrame#SplitActionDivider {{
    background: rgba(220, 229, 232, 0.58);
    min-width: 1px;
    max-width: 1px;
}}
QPushButton#EditorActionButton {{
    min-width: 108px;
}}
QComboBox,
QSpinBox,
QDoubleSpinBox {{
    background: rgba(220, 229, 232, 0.94);
    color: {input_text};
    border-radius: {panel_radius}px;
    min-height: {input_height}px;
    padding: 6px 12px;
    border: none;
}}
QComboBox::drop-down {{
    border: none;
    width: 28px;
}}
QComboBox::down-arrow {{
    width: 12px;
    height: 12px;
}}
QComboBox QAbstractItemView {{
    background: rgba(220, 229, 232, 0.98);
    color: {input_text};
    border: 1px solid rgba(109, 115, 64, 0.24);
    selection-background-color: rgba(217, 187, 98, 0.92);
    selection-color: {input_text};
    outline: none;
}}
QComboBox#InteractiveCombo {{
    background: {secondary_fill};
    color: {button_text};
    border-radius: {button_radius}px;
    min-height: {input_height}px;
    padding: 6px 12px;
    border: none;
}}
QComboBox#InteractiveCombo:hover,
QComboBox#InteractiveCombo:focus {{
    background: {accent_fill};
}}
QComboBox#InteractiveCombo::drop-down {{
    border: none;
    width: 30px;
}}
QComboBox#InteractiveCombo::down-arrow {{
    width: 12px;
    height: 12px;
}}
QTabWidget::pane {{
    border: none;
    background: transparent;
}}
QTabBar::tab {{
    background: {tab_fill};
    color: {tab_text};
    border-radius: {tab_radius}px;
    min-width: {tab_min_width}px;
    padding: 8px 16px;
    margin-right: 8px;
}}
QTabBar::tab:selected {{
    background: {tab_selected_fill};
}}
QTabBar::tab:hover {{
    background: {tab_hover_fill};
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QListWidget#AdjustUiCategoryList {{
    background: rgba(220, 229, 232, 0.78);
    border-radius: {card_radius}px;
    border: 1px solid {card_border};
    padding: 6px;
}}
QListWidget#AdjustUiCategoryList::item {{
    border-radius: {button_radius}px;
    padding: 8px 10px;
    margin: 2px 0px;
}}
QListWidget#AdjustUiCategoryList::item:selected {{
    background: {secondary_fill};
    color: {window_text};
}}
QScrollBar:vertical {{
    background: rgba(220, 229, 232, 0.18);
    width: 10px;
    margin: 4px 0px 4px 0px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical {{
    background: rgba(220, 229, 232, 0.78);
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{
    background: transparent;
    height: 0px;
}}
QScrollBar:horizontal {{
    background: rgba(220, 229, 232, 0.18);
    height: 10px;
    margin: 0px 4px 0px 4px;
    border-radius: 5px;
}}
QScrollBar::handle:horizontal {{
    background: rgba(220, 229, 232, 0.78);
    border-radius: 5px;
    min-width: 24px;
}}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {{
    background: transparent;
    width: 0px;
}}
QPlainTextEdit {{
    background: {log_fill};
    border-radius: {panel_radius}px;
    padding: 12px;
    border: none;
}}
QDialog {{
    background: {card_fill};
}}
"""


def get_nested_value(mapping: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = mapping
    for key in path:
        current = current[key]
    return current


def set_nested_value(mapping: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    current = mapping
    for key in path[:-1]:
        current = current.setdefault(key, {})
    current[path[-1]] = value


def delete_nested_value(mapping: dict[str, Any], path: tuple[str, ...]) -> None:
    current = mapping
    parents: list[tuple[dict[str, Any], str]] = []
    for key in path[:-1]:
        next_value = current.get(key)
        if not isinstance(next_value, dict):
            return
        parents.append((current, key))
        current = next_value
    current.pop(path[-1], None)
    for parent, key in reversed(parents):
        child = parent.get(key)
        if isinstance(child, dict) and not child:
            parent.pop(key, None)


def available_asset_options(theme: _ThemeBase, option_key: str) -> dict[str, str]:
    options = theme.assets.get(option_key, {})
    if not isinstance(options, dict):
        return {}
    return {str(label): str(path) for label, path in options.items()}


def bake_theme_payload(
    *,
    snapshot_path: str | Path,
    target_theme_path: str | Path,
) -> None:
    snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    _validate_theme_payload(snapshot)
    write_theme_payload(target_theme_path, snapshot)


def _theme_from_payload(payload: Mapping[str, Any], *, cls: type[_ThemeBase]) -> _ThemeBase:
    return cls(
        name=str(payload["name"]),
        display_name=str(payload["display_name"]),
        colors={str(key): str(value) for key, value in payload["colors"].items()},
        font_sizes={str(key): int(value) for key, value in payload["font_sizes"].items()},
        radii={str(key): int(value) for key, value in payload["radii"].items()},
        spacing={str(key): int(value) for key, value in payload["spacing"].items()},
        control_heights={str(key): int(value) for key, value in payload["control_heights"].items()},
        border_widths={str(key): int(value) for key, value in payload["border_widths"].items()},
        layout={str(key): int(value) for key, value in payload["layout"].items()},
        glass=_coerce_theme_section(payload["glass"]),
        chrome=_coerce_theme_section(payload["chrome"]),
        effects=_coerce_theme_section(payload["effects"]),
        assets=_coerce_theme_section(payload["assets"]),
    )


def _coerce_theme_section(section: Mapping[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in section.items():
        if isinstance(value, dict):
            normalized[str(key)] = {str(inner_key): inner_value for inner_key, inner_value in value.items()}
        else:
            normalized[str(key)] = value
    return normalized


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _css_color(value: str) -> str:
    normalized = value.strip()
    if normalized.startswith("#") and len(normalized) == 9:
        alpha = int(normalized[1:3], 16)
        red = int(normalized[3:5], 16)
        green = int(normalized[5:7], 16)
        blue = int(normalized[7:9], 16)
        return f"rgba({red}, {green}, {blue}, {alpha / 255:.3f})"
    return normalized


def _with_alpha(value: str, alpha_fraction: float) -> str:
    normalized = value.strip()
    if normalized.startswith("#") and len(normalized) in {7, 9}:
        if len(normalized) == 9:
            red = int(normalized[3:5], 16)
            green = int(normalized[5:7], 16)
            blue = int(normalized[7:9], 16)
        else:
            red = int(normalized[1:3], 16)
            green = int(normalized[3:5], 16)
            blue = int(normalized[5:7], 16)
        alpha = max(0.0, min(1.0, alpha_fraction))
        return f"rgba({red}, {green}, {blue}, {alpha:.3f})"
    return normalized


def _validate_theme_payload(payload: Mapping[str, Any]) -> None:
    required_top_level = (
        "name",
        "display_name",
        "colors",
        "font_sizes",
        "radii",
        "spacing",
        "control_heights",
        "border_widths",
        "layout",
        "glass",
        "chrome",
        "effects",
        "assets",
    )
    for key in required_top_level:
        if key not in payload:
            raise ValueError(f"Theme payload is missing required key: {key}")
    unexpected_keys = sorted(set(payload.keys()) - set(required_top_level))
    if unexpected_keys:
        raise ValueError(f"Theme payload contains unexpected keys: {', '.join(unexpected_keys)}")


def _validate_theme_overrides(base_payload: Mapping[str, Any], override_payload: Mapping[str, Any], *, prefix: str = "") -> None:
    for key, value in override_payload.items():
        dotted = f"{prefix}.{key}" if prefix else str(key)
        if key not in base_payload:
            raise ValueError(f"Theme override contains unknown key: {dotted}")
        base_value = base_payload[key]
        if isinstance(base_value, Mapping):
            if not isinstance(value, Mapping):
                raise ValueError(f"Theme override must keep section '{dotted}' as an object.")
            _validate_theme_overrides(base_value, value, prefix=dotted)
            continue
        if isinstance(base_value, bool):
            if not isinstance(value, bool):
                raise ValueError(f"Theme override value for '{dotted}' must be a boolean.")
            continue
        if isinstance(base_value, (int, float)):
            if not isinstance(value, (int, float)):
                raise ValueError(f"Theme override value for '{dotted}' must be numeric.")
            continue
        if isinstance(base_value, str):
            if not isinstance(value, str):
                raise ValueError(f"Theme override value for '{dotted}' must be a string.")
