"""Retired Tk GUI entrypoint.

Layer: UI facade.

The supported desktop UI lives in `qt_ui`. This module deliberately keeps no
Tk implementation behind the retired entrypoint.
"""

from __future__ import annotations

import multiprocessing
import sys

from .fbx_worker_subprocess import FBX_WORKER_COMMAND
from .gui_formatters import format_conversion_results, format_wind_group_summary, format_wind_json_result


def main() -> int:
    """Reject retired Tk launches while preserving frozen FBX helper dispatch."""
    if len(sys.argv) > 1 and sys.argv[1] == FBX_WORKER_COMMAND:
        from .cli import main as cli_main

        multiprocessing.freeze_support()
        return cli_main(sys.argv[1:])
    raise RuntimeError("The Tk GUI is retired. Use `python -m xml_to_usda gui` for the supported PySide6 shell.")


__all__ = [
    "main",
    "format_conversion_results",
    "format_wind_group_summary",
    "format_wind_json_result",
]
