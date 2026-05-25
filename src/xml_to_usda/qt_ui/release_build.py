"""Release-build helpers for the PySide6 shell."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QImageReader, QImageWriter


JPEG_QUALITY_DEFAULT = 85
_QT_CORE_APPLICATION: QCoreApplication | None = None

PYINSTALLER_EXCLUDES: tuple[str, ...] = (
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtGraphs",
    "PySide6.QtGraphsWidgets",
    "PySide6.QtHelp",
    "PySide6.QtHttpServer",
    "PySide6.QtLocation",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNfc",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtPrintSupport",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialBus",
    "PySide6.QtSerialPort",
    "PySide6.QtSql",
    "PySide6.QtStateMachine",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
    "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools",
    "PySide6.QtVirtualKeyboard",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
    "PySide6.QtNetwork",
    "PySide6.QtNetworkAuth",
)


def build_release_data_tree(
    *,
    source_ui_root: str | Path,
    staging_root: str | Path,
    jpeg_quality: int = JPEG_QUALITY_DEFAULT,
) -> Path:
    """Stage the Qt UI data tree for release packaging.

    The staging tree preserves the package-relative layout expected by
    ``importlib.resources``. Photo-like JPEG assets are re-encoded with a fixed
    quality setting; all non-noise assets keep the original relative path.
    """

    source_root = Path(source_ui_root).resolve()
    resolved_staging_root = Path(staging_root).resolve()

    if not source_root.is_dir():
        raise FileNotFoundError(f"Missing Qt UI source tree: {source_root}")

    assets_root = source_root / "assets"
    themes_root = source_root / "themes"
    if not assets_root.is_dir():
        raise FileNotFoundError(f"Missing Qt UI assets directory: {assets_root}")
    if not themes_root.is_dir():
        raise FileNotFoundError(f"Missing Qt UI themes directory: {themes_root}")

    if resolved_staging_root.exists():
        shutil.rmtree(resolved_staging_root)
    resolved_staging_root.mkdir(parents=True, exist_ok=True)

    _copy_tree(assets_root, resolved_staging_root / "assets", jpeg_quality=jpeg_quality)
    _copy_tree(themes_root, resolved_staging_root / "themes", jpeg_quality=jpeg_quality)
    return resolved_staging_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage Qt UI release assets into a build directory.")
    parser.add_argument("--source-ui-root", required=True)
    parser.add_argument("--staging-root", required=True)
    parser.add_argument("--jpeg-quality", type=int, default=JPEG_QUALITY_DEFAULT)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    staged_root = build_release_data_tree(
        source_ui_root=args.source_ui_root,
        staging_root=args.staging_root,
        jpeg_quality=args.jpeg_quality,
    )
    print(f"Staged Qt UI release assets: {staged_root}")
    return 0


def _copy_tree(source_root: Path, staging_root: Path, *, jpeg_quality: int) -> None:
    staging_root.mkdir(parents=True, exist_ok=True)
    _ensure_qt_core_application()

    for source_path in sorted((candidate for candidate in source_root.rglob("*") if candidate.is_file()), key=_path_key):
        relative_path = source_path.relative_to(source_root)
        destination_path = staging_root / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        if _should_reencode_as_jpeg(source_path):
            _write_jpeg_with_fallback(source_path, destination_path, jpeg_quality=jpeg_quality)
            continue
        shutil.copy2(source_path, destination_path)


def _ensure_qt_core_application() -> None:
    global _QT_CORE_APPLICATION
    if QCoreApplication.instance() is None:
        _QT_CORE_APPLICATION = QCoreApplication([])


def _should_reencode_as_jpeg(path: Path) -> bool:
    if path.suffix.lower() not in {".jpg", ".jpeg"}:
        return False
    return not any("noise" in part.casefold() for part in path.parts)


def _write_jpeg_with_fallback(source_path: Path, destination_path: Path, *, jpeg_quality: int) -> None:
    reader = QImageReader(str(source_path))
    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        raise RuntimeError(f"Failed to read image for release build: {source_path} ({reader.errorString()})")

    temp_path = destination_path.with_name(f"{destination_path.name}.tmp.jpg")
    if temp_path.exists():
        temp_path.unlink()

    writer = QImageWriter(str(temp_path), b"jpeg")
    writer.setQuality(jpeg_quality)
    if hasattr(writer, "setOptimizedWrite"):
        writer.setOptimizedWrite(True)
    if not writer.write(image):
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to write compressed JPEG for release build: {source_path} ({writer.errorString()})")
    del writer

    source_size = source_path.stat().st_size
    temp_size = temp_path.stat().st_size
    if temp_size >= source_size:
        temp_path.unlink()
        shutil.copy2(source_path, destination_path)
        return

    temp_path.replace(destination_path)


def _path_key(path: Path) -> str:
    return path.as_posix().casefold()


if __name__ == "__main__":
    raise SystemExit(main())
