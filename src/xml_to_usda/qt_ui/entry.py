"""Public entrypoint for the primary PySide6 GUI shell."""

from __future__ import annotations

import argparse
import ctypes
import json
import multiprocessing
import sys
from importlib.resources import files
from pathlib import Path

from ..diagnostics_bundle import default_build_info_path
from ..runtime_error_mode import suppress_windows_native_error_dialogs
from ..worker_commands import (
    CONVERSION_WORKER_COMMAND,
    FBX_WORKER_COMMAND,
    FRACTURE_WORKER_COMMAND,
    PART_PREVIEW_WORKER_COMMAND,
    PROXY_MESH_WORKER_COMMAND,
    WIND_PREVIEW_WORKER_COMMAND,
)
from .smoke import SMOKE_COMMAND

WINDOWS_APP_USER_MODEL_ID = "SpeedAssembly.SpeedAssembly"


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
    suppress_windows_native_error_dialogs()
    multiprocessing.freeze_support()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == FBX_WORKER_COMMAND:
        from ..fbx_worker_entry import main as fbx_worker_main

        return fbx_worker_main(argv)
    if argv and argv[0] == CONVERSION_WORKER_COMMAND:
        from ..conversion_worker_subprocess import run_conversion_worker_request_file

        request_path = argv[argv.index("--request") + 1] if "--request" in argv else ""
        return run_conversion_worker_request_file(request_path)
    if argv and argv[0] == PROXY_MESH_WORKER_COMMAND:
        from ..proxy_mesh_worker_subprocess import run_proxy_mesh_worker_request_file

        request_path = argv[argv.index("--request") + 1] if "--request" in argv else ""
        return run_proxy_mesh_worker_request_file(request_path)
    if argv and argv[0] == FRACTURE_WORKER_COMMAND:
        from ..fracture_worker_subprocess import run_fracture_worker_request_file

        request_path = argv[argv.index("--request") + 1] if "--request" in argv else ""
        return run_fracture_worker_request_file(request_path)
    if argv and argv[0] == PART_PREVIEW_WORKER_COMMAND:
        from ..part_preview_worker_subprocess import run_part_preview_worker_request_file

        request_path = argv[argv.index("--request") + 1] if "--request" in argv else ""
        return run_part_preview_worker_request_file(request_path)
    if argv and argv[0] == WIND_PREVIEW_WORKER_COMMAND:
        from ..wind_preview_worker_subprocess import run_wind_preview_worker_request_file

        request_path = argv[argv.index("--request") + 1] if "--request" in argv else ""
        return run_wind_preview_worker_request_file(request_path)
    if argv and argv[0] == SMOKE_COMMAND:
        from .smoke import run_smoke_cli

        return run_smoke_cli(argv[1:])
    if argv and argv[0] == "boolean-prototype":
        from .boolean_prototype import run_boolean_prototype_cli

        return run_boolean_prototype_cli(argv[1:])
    if argv and argv[0] == "boolean-multi-prototype":
        from .boolean_prototype import run_boolean_multi_prototype_cli

        return run_boolean_multi_prototype_cli(argv[1:])

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

    build_info_path = default_build_info_path()
    current_help_prompt_signature = _current_help_prompt_build_signature(build_info_path)
    state = load_ui_shell_state(current_build_signature=current_help_prompt_signature)
    theme_name = args.theme or state.theme_name
    base_theme = load_bundled_theme(theme_name)
    theme_overrides = load_ui_theme_overrides()
    if theme_overrides.theme_name != theme_name and theme_overrides.payload:
        theme_overrides = ThemeOverrides(theme_name=theme_name, payload=theme_overrides.payload)
    theme = merge_theme(base_theme, theme_overrides)
    deps = build_default_dependencies()
    configure_windows_taskbar_identity()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("SpeedAssembly")
    app.setWindowIcon(QIcon(application_icon_path()))
    window = MainWindow(
        theme,
        state,
        dependencies=deps,
        base_theme=base_theme,
        theme_overrides=theme_overrides,
        build_signature=current_help_prompt_signature,
    )
    window.show()
    if args.smoke_exit_ms > 0:
        QTimer.singleShot(args.smoke_exit_ms, app.quit)
    return app.exec()


def _current_help_prompt_build_signature(build_info_path: Path | None) -> str:
    signature = _build_signature_from_build_info_path(build_info_path)
    if signature:
        return signature
    return _build_signature_from_executable_path(Path(sys.executable))


def _build_signature_from_build_info_path(path) -> str:
    if path is None:
        return ""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    built_at = str(payload.get("built_at", "")).strip()
    build_mode = str(payload.get("build_mode", "")).strip()
    git_head = str(payload.get("git_head", "")).strip()
    exe_path = str(payload.get("exe_path", "")).strip()
    if not any((built_at, build_mode, git_head, exe_path)):
        return ""
    return "|".join(part for part in (build_mode, git_head, built_at, exe_path) if part)


def _build_signature_from_executable_path(path: Path) -> str:
    try:
        stat = path.stat()
    except OSError:
        return ""
    return f"exe|{stat.st_size}|{stat.st_mtime_ns}"
