"""Qt-facing runtime trace facade."""

from __future__ import annotations

from ..runtime_trace import (
    DEFAULT_TRACE_BACKUP_COUNT,
    DEFAULT_TRACE_MAX_BYTES,
    TRACE_FILE_NAME,
    RuntimeTraceLogger,
    rotated_trace_paths,
    trace_path_for_settings_dir,
)


QtTraceLogger = RuntimeTraceLogger

__all__ = [
    "DEFAULT_TRACE_BACKUP_COUNT",
    "DEFAULT_TRACE_MAX_BYTES",
    "TRACE_FILE_NAME",
    "QtTraceLogger",
    "rotated_trace_paths",
    "trace_path_for_settings_dir",
]
