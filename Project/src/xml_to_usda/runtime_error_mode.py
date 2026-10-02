"""Windows native error-dialog policy for runtime workers."""

from __future__ import annotations

import ctypes
import sys


def suppress_windows_native_error_dialogs() -> None:
    if sys.platform != "win32":
        return
    try:
        SEM_FAILCRITICALERRORS = 0x0001
        SEM_NOGPFAULTERRORBOX = 0x0002
        SEM_NOOPENFILEERRORBOX = 0x8000
        ctypes.windll.kernel32.SetErrorMode(
            SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX
        )
    except Exception:
        return
