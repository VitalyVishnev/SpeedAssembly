"""Public GUI facade for launcher, package, and tests.

Layer: UI facade.

The real Tk application shell lives in `gui_app`. This module intentionally
re-exports a stable `ConversionApp`, formatter helpers, and `main()` entrypoint
so packaged builds, tests, and monkeypatched launcher flows do not depend on
internal GUI module layout.
"""

from __future__ import annotations

import multiprocessing
import sys
import tkinter as tk
from tkinter import filedialog, messagebox

from .conversion_process import close_process_queue, drain_process_queue, start_conversion_process
from .conversion_service import prepare_conversion_plan
from .discovery_service import inspect_fbx_material_slot_rows
from .gui_app import ConversionApp as _ConversionApp
from .gui_app import GuiDependencies
from .gui_formatters import format_conversion_results, format_wind_group_summary, format_wind_json_result
from .pipeline import convert_request
from .settings_service import load_gui_settings, resolve_input_settings_key, save_gui_settings
from .wind_service import (
    WindGenerationRequest,
    derive_wind_json_output_path,
    format_wind_error,
    generate_wind_json_from_request,
    inspect_wind_groups,
    prepare_wind_inspection_plan,
    should_retry_wind_error,
)


def _build_gui_dependencies() -> GuiDependencies:
    """Capture the current public GUI-module globals into one dependency bundle."""
    return GuiDependencies(
        prepare_conversion_plan=prepare_conversion_plan,
        start_conversion_process=start_conversion_process,
        close_process_queue=close_process_queue,
        drain_process_queue=drain_process_queue,
        convert_request=convert_request,
        inspect_fbx_material_slot_rows=inspect_fbx_material_slot_rows,
        load_gui_settings=load_gui_settings,
        save_gui_settings=save_gui_settings,
        resolve_input_settings_key=resolve_input_settings_key,
        prepare_wind_inspection_plan=prepare_wind_inspection_plan,
        inspect_wind_groups=inspect_wind_groups,
        WindGenerationRequest=WindGenerationRequest,
        generate_wind_json_from_request=generate_wind_json_from_request,
        derive_wind_json_output_path=derive_wind_json_output_path,
        format_wind_error=format_wind_error,
        should_retry_wind_error=should_retry_wind_error,
        messagebox=messagebox,
        filedialog=filedialog,
        sys=sys,
    )


class ConversionApp(_ConversionApp):
    """Compatibility wrapper that feeds public-module dependencies into the app shell."""
    def __init__(self, root: tk.Tk) -> None:
        super().__init__(root, dependencies=_build_gui_dependencies())


def main() -> int:
    """Launch the Tk GUI entrypoint used by the project package/launcher."""
    multiprocessing.freeze_support()
    root = tk.Tk()
    ConversionApp(root)
    root.mainloop()
    return 0


__all__ = [
    "ConversionApp",
    "main",
    "format_conversion_results",
    "format_wind_group_summary",
    "format_wind_json_result",
]
