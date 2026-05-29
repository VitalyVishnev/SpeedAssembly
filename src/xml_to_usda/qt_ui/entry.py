"""Public entrypoint for the primary PySide6 GUI shell."""

from __future__ import annotations

import argparse
import ctypes
import multiprocessing
import sys
from importlib.resources import files

from ..fbx_worker_subprocess import FBX_WORKER_COMMAND

WINDOWS_APP_USER_MODEL_ID = "XMLtoUSDAConverter.XMLtoUSDAConverter"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xml-to-usda-gui")
    parser.add_argument("--theme", default=None, help="Bundled theme name to load for the PySide6 shell.")
    parser.add_argument("--smoke-exit-ms", type=int, default=0, help=argparse.SUPPRESS)
    return parser


def configure_windows_taskbar_identity() -> None:
    if sys.platform != "win32":
        return
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_USER_MODEL_ID)


def application_icon_path() -> str:
    return str(files("xml_to_usda.qt_ui").joinpath("assets", "Icon.ico"))


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == FBX_WORKER_COMMAND:
        from ..fbx_worker_entry import main as fbx_worker_main

        return fbx_worker_main(argv)

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication
    except ImportError:
        sys.stderr.write(
            "PySide6 is required for the GUI shell. Install the 'ui-next' extra in .venv310.\n"
        )
        return 2

    from .dependencies import build_default_dependencies
    from .persistence import load_ui_shell_state, load_ui_theme_overrides
    from .theme import ThemeOverrides, load_bundled_theme, merge_theme
    from .window import MainWindow

    state = load_ui_shell_state()
    theme_name = args.theme or state.theme_name
    base_theme = load_bundled_theme(theme_name)
    theme_overrides = load_ui_theme_overrides()
    if theme_overrides.theme_name != theme_name and theme_overrides.payload:
        theme_overrides = ThemeOverrides(theme_name=theme_name, payload=theme_overrides.payload)
    theme = merge_theme(base_theme, theme_overrides)
    deps = build_default_dependencies()
    configure_windows_taskbar_identity()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("XML to USDA Converter")
    app.setWindowIcon(QIcon(application_icon_path()))
    window = MainWindow(theme, state, dependencies=deps, base_theme=base_theme, theme_overrides=theme_overrides)
    window.show()
    if args.smoke_exit_ms > 0:
        QTimer.singleShot(args.smoke_exit_ms, app.quit)
    return app.exec()
