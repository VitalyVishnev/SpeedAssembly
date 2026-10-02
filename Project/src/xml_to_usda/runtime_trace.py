"""Structured runtime trace logging.

Layer: infrastructure.

The trace observes operator and runtime behavior for diagnostics. It must not
define conversion semantics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_TRACE_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_TRACE_BACKUP_COUNT = 5
TRACE_FILE_NAME = "gui_trace.jsonl"
FORCE_DEBUG_TRACE = True


@dataclass(frozen=True)
class RuntimeTraceLogger:
    path: Path
    debug_enabled: bool = False
    max_bytes: int = DEFAULT_TRACE_MAX_BYTES
    backup_count: int = DEFAULT_TRACE_BACKUP_COUNT

    def log(
        self,
        kind: str,
        *,
        level: str = "info",
        message: str = "",
        action: str = "",
        widget: str = "",
        job: str = "",
        worker: str = "",
        data: dict[str, Any] | None = None,
        debug_data: dict[str, Any] | None = None,
    ) -> None:
        event: dict[str, Any] = {
            "ts": _timestamp(),
            "level": str(level),
            "kind": str(kind),
        }
        if message:
            event["message"] = str(message)
        if action:
            event["action"] = str(action)
        if widget:
            event["widget"] = str(widget)
        if job:
            event["job"] = str(job)
        if worker:
            event["worker"] = str(worker)
        if data:
            event["data"] = _json_safe(data)
        if (self.debug_enabled or FORCE_DEBUG_TRACE) and debug_data:
            event["debug"] = _json_safe(debug_data)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, sort_keys=True, separators=(",", ":"), default=str)
        self._rotate_if_needed(len(line.encode("utf-8")) + 1)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(f"{line}\n")

    def _rotate_if_needed(self, next_bytes: int) -> None:
        if self.max_bytes <= 0 or not self.path.exists():
            return
        try:
            current_size = self.path.stat().st_size
        except OSError:
            return
        if current_size + next_bytes <= self.max_bytes:
            return
        for index in range(max(0, self.backup_count - 1), 0, -1):
            source = _rotated_path(self.path, index)
            target = _rotated_path(self.path, index + 1)
            if source.exists():
                try:
                    source.replace(target)
                except OSError:
                    pass
        try:
            self.path.replace(_rotated_path(self.path, 1))
        except OSError:
            pass


def trace_path_for_settings_dir(settings_dir: Path) -> Path:
    return Path(settings_dir) / TRACE_FILE_NAME


def rotated_trace_paths(settings_dir: Path, *, backup_count: int = DEFAULT_TRACE_BACKUP_COUNT) -> tuple[Path, ...]:
    base_path = trace_path_for_settings_dir(settings_dir)
    return tuple(_rotated_path(base_path, index) for index in range(1, backup_count + 1))


def _rotated_path(path: Path, index: int) -> Path:
    if path.name.endswith(".jsonl"):
        return path.with_name(f"{path.name[:-6]}.{index}.jsonl")
    return path.with_name(f"{path.name}.{index}")


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json_safe(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload, default=str))
