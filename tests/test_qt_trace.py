from __future__ import annotations

import json
from pathlib import Path

from xml_to_usda.qt_ui.trace import QtTraceLogger


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_qt_trace_logger_writes_jsonl_and_rotates_without_breaking_lines(tmp_path: Path) -> None:
    trace_path = tmp_path / "gui_trace.jsonl"
    logger = QtTraceLogger(trace_path, max_bytes=220, backup_count=3)

    logger.log("app.start", message="startup", data={"runtime": "launcher"})
    logger.log("ui.action", action="button.click", widget="Convert to USDA")
    logger.log("job.start", job="fracture_preview", data={"input_path": "tree.xml"})
    logger.log("job.end", job="fracture_preview", data={"result": "ok"})

    assert trace_path.exists()
    all_events: list[dict[str, object]] = []
    for path in (
        tmp_path / "gui_trace.3.jsonl",
        tmp_path / "gui_trace.2.jsonl",
        tmp_path / "gui_trace.1.jsonl",
        trace_path,
    ):
        if path.exists():
            all_events.extend(_read_jsonl(path))

    assert [event["kind"] for event in all_events] == [
        "app.start",
        "ui.action",
        "job.start",
        "job.end",
    ]
    assert all(isinstance(event["ts"], str) and event["ts"] for event in all_events)


def test_qt_trace_logger_includes_debug_data_even_when_saved_setting_is_off(tmp_path: Path) -> None:
    compact_path = tmp_path / "compact.jsonl"
    debug_path = tmp_path / "debug.jsonl"

    QtTraceLogger(compact_path, debug_enabled=False).log(
        "worker.spawn",
        worker="fracture",
        debug_data={"command": ["XMLtoUSDAConverter.exe", "fracture-worker"]},
    )
    QtTraceLogger(debug_path, debug_enabled=True).log(
        "worker.spawn",
        worker="fracture",
        debug_data={"command": ["XMLtoUSDAConverter.exe", "fracture-worker"]},
    )

    compact_event = _read_jsonl(compact_path)[0]
    debug_event = _read_jsonl(debug_path)[0]

    assert compact_event["debug"] == {"command": ["XMLtoUSDAConverter.exe", "fracture-worker"]}
    assert debug_event["debug"] == {"command": ["XMLtoUSDAConverter.exe", "fracture-worker"]}
