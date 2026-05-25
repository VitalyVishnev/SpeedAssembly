from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QColor, QImage

from xml_to_usda.qt_ui.release_build import build_release_data_tree


def test_release_build_reencodes_jpegs_and_copies_non_noise_assets(tmp_path: Path) -> None:
    source_ui_root = tmp_path / "src" / "xml_to_usda" / "qt_ui"
    theme_assets_root = source_ui_root / "themes" / "default" / "assets"
    assets_root = source_ui_root / "assets"
    theme_assets_root.mkdir(parents=True)
    assets_root.mkdir(parents=True)

    source_jpeg = theme_assets_root / "demo_background.jpg"
    source_png = theme_assets_root / "WhiteNoise256.png"
    icon_path = assets_root / "Icon.ico"
    theme_path = source_ui_root / "themes" / "default" / "theme.json"

    _write_image(source_jpeg, format_name="JPEG", quality=100, width=320, height=180, color=QColor(30, 120, 180))
    _write_image(source_png, format_name="PNG", quality=100, width=64, height=64, color=QColor(120, 30, 180))
    icon_path.write_bytes(b"icon")
    theme_path.write_text('{"name":"default","display_name":"Default","colors":{},"font_sizes":{},"radii":{},"spacing":{},"control_heights":{},"border_widths":{},"layout":{},"glass":{},"chrome":{},"effects":{},"assets":{}}', encoding="utf-8")

    staging_root = build_release_data_tree(source_ui_root=source_ui_root, staging_root=tmp_path / "stage", jpeg_quality=60)

    staged_jpeg = staging_root / "themes" / "default" / "assets" / "demo_background.jpg"
    staged_png = staging_root / "themes" / "default" / "assets" / "WhiteNoise256.png"
    staged_icon = staging_root / "assets" / "Icon.ico"
    staged_theme = staging_root / "themes" / "default" / "theme.json"

    assert staged_jpeg.exists()
    assert staged_png.exists()
    assert staged_icon.read_bytes() == b"icon"
    assert staged_theme.read_text(encoding="utf-8") == theme_path.read_text(encoding="utf-8")
    assert staged_jpeg.stat().st_size < source_jpeg.stat().st_size
    assert staged_png.read_bytes() == source_png.read_bytes()


def _write_image(path: Path, *, format_name: str, width: int, height: int, quality: int, color: QColor) -> None:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(color)
    if not image.save(str(path), format_name, quality):
        raise RuntimeError(f"Failed to write test image: {path}")
