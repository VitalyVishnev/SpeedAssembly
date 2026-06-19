"""Packaged Qt smoke runner.

Layer: UI/infrastructure edge.

Smoke scenarios exercise packaged GUI workflows. They do not define conversion
semantics; they verify that the packaged shell can drive the existing services.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Any


SMOKE_COMMAND = "smoke"
SMOKE_SCENARIO_STARTUP = "startup"
SMOKE_SCENARIO_FRACTURE_PREVIEW = "fracture-preview"
SMOKE_SCENARIO_FRACTURE_PREVIEW_INTERACTIVE = "fracture-preview-interactive"
SMOKE_SCENARIO_FRACTURE_PREVIEW_RAPID_SETTINGS = "fracture-preview-rapid-settings"
SMOKE_SCENARIO_PROXY_PREVIEW = "proxy-preview"
SMOKE_SCENARIO_CONVERSION_WORKER = "conversion-worker"
SMOKE_SCENARIO_DIAGNOSTICS_EXPORT = "diagnostics-export"
SMOKE_SCENARIO_HIGH_RISK = "high-risk"
SMOKE_SCENARIO_PACKAGED_STABILITY = "packaged-stability"

HIGH_RISK_SCENARIOS: tuple[str, ...] = (
    SMOKE_SCENARIO_STARTUP,
    SMOKE_SCENARIO_FRACTURE_PREVIEW,
    SMOKE_SCENARIO_FRACTURE_PREVIEW_INTERACTIVE,
    SMOKE_SCENARIO_FRACTURE_PREVIEW_RAPID_SETTINGS,
    SMOKE_SCENARIO_PROXY_PREVIEW,
    SMOKE_SCENARIO_CONVERSION_WORKER,
    SMOKE_SCENARIO_DIAGNOSTICS_EXPORT,
)

PACKAGED_STABILITY_SCENARIOS: tuple[str, ...] = (
    SMOKE_SCENARIO_FRACTURE_PREVIEW_INTERACTIVE,
    SMOKE_SCENARIO_FRACTURE_PREVIEW_RAPID_SETTINGS,
)

SMOKE_SCENARIOS: tuple[str, ...] = HIGH_RISK_SCENARIOS + (
    SMOKE_SCENARIO_HIGH_RISK,
    SMOKE_SCENARIO_PACKAGED_STABILITY,
)


@dataclass(frozen=True)
class SmokeContext:
    input_path: str
    output_path: str
    report_path: Path
    timeout_ms: int
    debug_trace: bool = False


ScenarioRunner = Callable[[str, SmokeContext], dict[str, Any]]


def build_smoke_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xml-to-usda-gui smoke")
    parser.add_argument("--scenario", choices=SMOKE_SCENARIOS, default=SMOKE_SCENARIO_HIGH_RISK)
    parser.add_argument("--input", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--report", default="")
    parser.add_argument("--timeout-ms", type=int, default=180_000)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--debug-trace", action="store_true")
    parser.add_argument("--fail-on-retry", action="store_true")
    parser.add_argument("--sample-profile", action="append", default=[])
    return parser


def run_smoke_cli(argv: list[str] | None = None, *, scenario_runner: ScenarioRunner | None = None) -> int:
    parser = build_smoke_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    report_path = Path(args.report) if args.report else _default_report_path()
    context = SmokeContext(
        input_path=str(args.input),
        output_path=str(args.output),
        report_path=report_path,
        timeout_ms=max(1_000, int(args.timeout_ms)),
        debug_trace=bool(args.debug_trace),
    )
    runner = scenario_runner or run_real_smoke_scenario
    scenario_names = _scenario_names(args.scenario)
    scenario_reports: list[dict[str, Any]] = []
    started = time.time()

    for _repeat_index in range(max(1, int(args.repeat))):
        for name in scenario_names:
            scenario_started = time.time()
            try:
                result = dict(runner(name, context))
                result.setdefault("name", name)
                result.setdefault("passed", True)
                result.setdefault("duration_seconds", round(time.time() - scenario_started, 3))
            except Exception as exc:
                result = {
                    "name": name,
                    "passed": False,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                    "duration_seconds": round(time.time() - scenario_started, 3),
                }
            scenario_reports.append(result)

    report = {
        "schema_version": 1,
        "passed": all(bool(scenario.get("passed")) for scenario in scenario_reports),
        "scenario": args.scenario,
        "repeat": max(1, int(args.repeat)),
        "duration_seconds": round(time.time() - started, 3),
        "input_path": context.input_path,
        "output_path": context.output_path,
        "debug_trace": context.debug_trace,
        "fail_on_retry": bool(args.fail_on_retry),
        "sample_profiles": tuple(args.sample_profile),
        "scenarios": scenario_reports,
    }
    if bool(args.fail_on_retry):
        strict_failure = _strict_runtime_evidence_failure(context, report)
        if strict_failure is not None:
            scenario_reports.append(strict_failure)
            report["passed"] = False
        else:
            report["passed"] = all(bool(scenario.get("passed")) for scenario in scenario_reports)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return 0 if report["passed"] else 1


def run_real_smoke_scenario(name: str, context: SmokeContext) -> dict[str, Any]:
    if name == SMOKE_SCENARIO_STARTUP:
        return _run_startup_smoke(context)
    if name == SMOKE_SCENARIO_FRACTURE_PREVIEW:
        return _run_fracture_preview_smoke(context)
    if name == SMOKE_SCENARIO_FRACTURE_PREVIEW_INTERACTIVE:
        return _run_fracture_preview_interactive_smoke(context)
    if name == SMOKE_SCENARIO_FRACTURE_PREVIEW_RAPID_SETTINGS:
        return _run_fracture_preview_rapid_settings_smoke(context)
    if name == SMOKE_SCENARIO_PROXY_PREVIEW:
        return _run_proxy_preview_smoke(context)
    if name == SMOKE_SCENARIO_CONVERSION_WORKER:
        return _run_conversion_worker_smoke(context)
    if name == SMOKE_SCENARIO_DIAGNOSTICS_EXPORT:
        return _run_diagnostics_export_smoke(context)
    raise ValueError(f"Unsupported smoke scenario: {name}")


def _scenario_names(name: str) -> tuple[str, ...]:
    if name == SMOKE_SCENARIO_HIGH_RISK:
        return HIGH_RISK_SCENARIOS
    if name == SMOKE_SCENARIO_PACKAGED_STABILITY:
        return PACKAGED_STABILITY_SCENARIOS
    return (name,)


def _default_report_path() -> Path:
    return Path.cwd() / "dist-next" / "smoke" / "smoke_report.json"


def _run_startup_smoke(context: SmokeContext) -> dict[str, Any]:
    window = _create_smoke_window(context)
    try:
        _pump_events(150)
        _assert(window.isVisible(), "startup window is visible")
        return _passed(name=SMOKE_SCENARIO_STARTUP, checks=("window.visible",))
    finally:
        _close_window(window)


def _run_fracture_preview_smoke(context: SmokeContext) -> dict[str, Any]:
    window = _create_smoke_window(context)
    try:
        input_path, output_path = _resolve_input_output(context, suffix=".usda")
        window.source_input.setText(str(input_path))
        window.output_input.setText(str(output_path))
        window.open_fracture_preview_dialog()
        _wait_until(
            lambda: window._fracture_preview_dialog is not None
            and window._fracture_preview_dialog.current_preview is not None,
            timeout_ms=context.timeout_ms,
            label="fracture preview result",
        )
        dialog = window._fracture_preview_dialog
        _assert(dialog is not None, "fracture dialog exists")
        _assert(dialog.isModal(), "fracture dialog is modal")
        _assert(dialog.viewport_mesh is not None, "fracture viewport mesh exists")
        _assert(dialog.viewport_mesh.uploaded_triangle_count > 0, "fracture viewport uploaded triangles")
        _assert(dialog.viewport.has_mesh(), "fracture viewport has mesh")
        trace_text = _trace_text(context)
        for milestone in (
            "Fracture Preview requested",
            "Fracture Preview result received",
            '"kind":"scene.ready"',
            '"kind":"viewport.set_scene"',
            "Fracture Preview preparing viewport mesh",
            '"kind":"viewport.upload_end"',
            "Fracture Preview viewport mesh ready",
        ):
            _assert(milestone in trace_text, f"trace contains {milestone}")
        return _passed(
            name=SMOKE_SCENARIO_FRACTURE_PREVIEW,
            checks=(
                "dialog.result",
                "dialog.modal",
                "viewport.mesh",
                "viewport.uploaded_triangles",
                "trace.milestones",
            ),
            data={
                "uploaded_triangles": dialog.viewport_mesh.uploaded_triangle_count,
                "logical_triangles": dialog.viewport_mesh.triangle_count,
            },
        )
    finally:
        _close_window(window)


def _run_fracture_preview_interactive_smoke(context: SmokeContext) -> dict[str, Any]:
    window = _create_smoke_window(context)
    try:
        input_path, output_path = _resolve_input_output(context, suffix=".usda")
        window.source_input.setText(str(input_path))
        window.output_input.setText(str(output_path))
        window.open_fracture_preview_dialog()
        _wait_until(
            lambda: window._fracture_preview_dialog is not None
            and window._fracture_preview_dialog.current_preview is not None,
            timeout_ms=context.timeout_ms,
            label="initial fracture preview result",
        )
        dialog = window._fracture_preview_dialog
        _assert(dialog is not None, "fracture dialog exists")
        _assert(dialog.isModal(), "fracture dialog is modal")
        dialog.piece_count_spin.setValue(26)
        dialog.piece_count_spin.editingFinished.emit()
        _wait_until(
            lambda: dialog.current_preview is not None and dialog.current_preview.plan.actual_piece_count == 26,
            timeout_ms=context.timeout_ms,
            label="fracture preview target pieces update",
        )
        dialog.preserve_trunk_spin.setValue(1.0)
        dialog.preserve_trunk_spin.editingFinished.emit()
        _wait_until(
            lambda: dialog.current_preview is not None
            and dialog.current_preview.plan.method == "manual_fracturing"
            and dialog.settings().fracture.preserve_trunk_bias == 1.0,
            timeout_ms=context.timeout_ms,
            label="fracture preview preserve trunk update",
        )
        previous_caps_preview = dialog.current_preview
        dialog.generate_caps_check.setChecked(True)
        _wait_until(
            lambda: dialog.current_preview is not None
            and dialog.current_preview is not previous_caps_preview
            and dialog.settings().fracture.generate_caps,
            timeout_ms=context.timeout_ms,
            label="fracture preview caps update",
        )
        dialog.show_bones_check.setChecked(True)
        _assert(dialog.show_bones_check.isChecked(), "Show Bones can be enabled")
        _assert(dialog.viewport.show_bones, "viewport bone overlay is visible")
        for raw_color in (0, 35, 92, 78):
            dialog.color_strength_slider.setValue(raw_color)
            _pump_events(25)
            _assert(
                abs(dialog.viewport.matcap_tint_strength - (raw_color / 100.0)) < 0.001,
                f"Piece Color updates immediately to {raw_color}",
            )
        for raw_exploded in (0, 25, 70, 0):
            dialog.exploded_view_slider.setValue(raw_exploded)
            _pump_events(25)
            _assert(
                abs(dialog.viewport.exploded_view_strength - (raw_exploded / 100.0)) < 0.001,
                f"Exploded View updates immediately to {raw_exploded}",
            )
        _assert(dialog.viewport_mesh is not None, "fracture viewport mesh exists")
        _assert(dialog.viewport_mesh.bone_segments, "bone overlay payload exists")
        _assert(dialog.viewport.bone_vertex_count > 0, "viewport bone overlay vertices exist")
        return _passed(
            name=SMOKE_SCENARIO_FRACTURE_PREVIEW_INTERACTIVE,
            checks=(
                "initial.result",
                "dialog.modal",
                "target.update",
                "method.update",
                "caps.update",
                "manual.bones",
                "piece_color.visual",
                "exploded_view.visual",
                "viewport.bones",
            ),
            data={
                "piece_count": dialog.current_preview.plan.actual_piece_count,
                "bone_segments": len(dialog.viewport_mesh.bone_segments),
                "bone_vertices": dialog.viewport.bone_vertex_count,
            },
        )
    finally:
        _close_window(window)


def _run_fracture_preview_rapid_settings_smoke(context: SmokeContext) -> dict[str, Any]:
    window = _create_smoke_window(context)
    try:
        input_path, output_path = _resolve_input_output(context, suffix=".usda")
        window.source_input.setText(str(input_path))
        window.output_input.setText(str(output_path))
        window.open_fracture_preview_dialog()
        _wait_until(
            lambda: window._fracture_preview_dialog is not None,
            timeout_ms=context.timeout_ms,
            label="fracture preview dialog",
        )
        dialog = window._fracture_preview_dialog
        _assert(dialog is not None, "fracture dialog exists")
        _assert(dialog.isModal(), "fracture dialog is modal")

        for index in range(10):
            dialog.stump_piece_check.setChecked(index % 2 == 0)
            dialog.generate_caps_check.setChecked(index % 3 != 0)
            dialog.piece_count_spin.setValue((5, 14, 26, 5)[index % 4])
            dialog.piece_count_spin.editingFinished.emit()
            dialog.preserve_trunk_spin.setValue((0.0, 0.5, 1.0)[index % 3])
            dialog.preserve_trunk_spin.editingFinished.emit()
            dialog.base_priority_spin.setValue((0.33, 0.74, 0.51)[index % 3])
            dialog.base_priority_spin.editingFinished.emit()
            dialog.color_strength_slider.setValue((0, 78, 35, 92)[index % 4])
            dialog.exploded_view_slider.setValue((0, 20, 70, 0)[index % 4])
            _pump_events(10)

        dialog.piece_count_spin.setValue(5)
        dialog.piece_count_spin.editingFinished.emit()
        dialog.stump_piece_check.setChecked(True)
        dialog.generate_caps_check.setChecked(True)
        _wait_until(
            lambda: dialog.current_preview is not None
            and dialog.current_preview.plan.actual_piece_count == 5
            and dialog.settings().fracture.force_stump_piece
            and dialog.settings().fracture.generate_caps,
            timeout_ms=context.timeout_ms,
            label="rapid fracture preview latest settings result",
        )
        _assert(dialog.viewport_mesh is not None, "fracture viewport mesh exists")
        _assert(dialog.viewport.has_mesh(), "fracture viewport has mesh")
        return _passed(
            name=SMOKE_SCENARIO_FRACTURE_PREVIEW_RAPID_SETTINGS,
            checks=(
                "dialog.open",
                "rapid.settings.coalesced",
                "latest.result",
                "viewport.mesh",
            ),
            data={
                "piece_count": dialog.current_preview.plan.actual_piece_count,
                "generate_caps": dialog.settings().fracture.generate_caps,
                "force_stump_piece": dialog.settings().fracture.force_stump_piece,
            },
        )
    finally:
        _close_window(window)


def _run_proxy_preview_smoke(context: SmokeContext) -> dict[str, Any]:
    window = _create_smoke_window(context)
    try:
        input_path, output_path = _resolve_input_output(context, suffix=".usda")
        window.source_input.setText(str(input_path))
        window.output_input.setText(str(output_path))
        window.open_proxy_preview_dialog()
        _wait_until(
            lambda: window._proxy_preview_dialog is not None
            and window._proxy_preview_dialog.current_proxy is not None,
            timeout_ms=context.timeout_ms,
            label="proxy preview result",
        )
        dialog = window._proxy_preview_dialog
        _assert(dialog is not None, "proxy dialog exists")
        _assert(dialog.isModal(), "proxy dialog is modal")
        _assert(dialog.current_proxy is not None, "proxy result exists")
        _assert(dialog.viewport.has_mesh(), "proxy viewport has mesh")
        trace_text = _trace_text(context)
        for milestone in (
            '"job":"proxy_preview"',
            '"kind":"scene.ready"',
            '"kind":"viewport.set_scene"',
            '"kind":"viewport.upload_end"',
        ):
            _assert(milestone in trace_text, f"trace contains {milestone}")
        return _passed(name=SMOKE_SCENARIO_PROXY_PREVIEW, checks=("dialog.result", "dialog.modal", "viewport.mesh"))
    finally:
        _close_window(window)


def _run_conversion_worker_smoke(context: SmokeContext) -> dict[str, Any]:
    window = _create_smoke_window(context)
    try:
        input_path, output_path = _resolve_input_output(context, suffix=".usda")
        window.source_input.setText(str(input_path))
        window.output_input.setText(str(output_path))
        window.ASYNC_CONVERSION_THRESHOLD_BYTES = 0
        window.run_conversion()
        _wait_until(
            lambda: "Wrote USDA to" in window.status_label.text(),
            timeout_ms=context.timeout_ms,
            label="conversion worker completion",
        )
        _assert(output_path.exists(), "conversion output exists")
        return _passed(name=SMOKE_SCENARIO_CONVERSION_WORKER, checks=("worker.result", "output.exists"))
    finally:
        _close_window(window)


def _run_diagnostics_export_smoke(context: SmokeContext) -> dict[str, Any]:
    window = _create_smoke_window(context)
    try:
        input_path, output_path = _resolve_input_output(context, suffix=".usda")
        window.source_input.setText(str(input_path))
        window.output_input.setText(str(output_path))
        bundle_path = context.report_path.parent / "smoke_diagnostics.zip"
        from ..diagnostics_bundle import build_diagnostics_bundle_request, export_diagnostics_bundle

        exported = export_diagnostics_bundle(
            build_diagnostics_bundle_request(
                bundle_path=bundle_path,
                settings_path=window._operator_settings_path,
                runtime_paths=window._runtime_paths,
                runtime_cleanup_summary=window._runtime_cleanup_summary,
                active_preset_name=window._current_preset_name(),
                selected_input_path=str(input_path),
                selected_output_path=str(output_path),
                in_app_log_text=window._log_text,
            )
        )
        _assert(exported.exists(), "diagnostics bundle exists")
        return _passed(
            name=SMOKE_SCENARIO_DIAGNOSTICS_EXPORT,
            checks=("diagnostics.bundle",),
            data={"bundle_path": str(exported)},
        )
    finally:
        _close_window(window)


def _create_smoke_window(context: SmokeContext):
    from PySide6.QtWidgets import QApplication

    from .dependencies import build_default_dependencies
    from .persistence import UiShellState
    from .theme import load_theme
    from .window import MainWindow
    from ..settings_service import GuiSettingsSnapshot, save_gui_settings

    app = QApplication.instance() or QApplication([sys.argv[0] if sys.argv else "xml-to-usda-smoke"])
    settings_path = context.report_path.parent / "gui_settings.json"
    save_gui_settings(settings_path, GuiSettingsSnapshot(debug_trace_enabled=context.debug_trace))
    window = MainWindow(
        load_theme(),
        UiShellState(help_prompt_dismissed=True),
        dependencies=build_default_dependencies(),
        state_path=context.report_path.parent / "ui_next_state.json",
        operator_settings_path=settings_path,
    )
    window._operator_snapshot = replace(window._operator_snapshot, debug_trace_enabled=context.debug_trace)
    window._trace_logger = replace(window._trace_logger, debug_enabled=context.debug_trace)
    window.show()
    app.processEvents()
    return window


def _resolve_input_output(context: SmokeContext, *, suffix: str) -> tuple[Path, Path]:
    input_path = Path(context.input_path) if context.input_path else _default_sample_path()
    output_path = Path(context.output_path) if context.output_path else context.report_path.parent / "smoke_output.usda"
    if output_path.suffix.lower() != suffix:
        output_path = output_path.with_suffix(suffix)
    _assert(input_path.exists(), f"smoke input exists: {input_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return input_path, output_path


def _default_sample_path() -> Path:
    return Path.cwd() / "samples" / "speedtree" / "simple_tree" / "variants" / "SimpleTree_01.xml"


def _wait_until(condition: Callable[[], bool], *, timeout_ms: int, label: str) -> None:
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        if condition():
            return
        _pump_events(50)
    raise AssertionError(f"Timed out waiting for {label}.")


def _pump_events(duration_ms: int) -> None:
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    loop = QEventLoop()
    QTimer.singleShot(max(0, int(duration_ms)), loop.quit)
    loop.exec()
    app.processEvents()


def _close_window(window) -> None:
    from PySide6.QtWidgets import QApplication

    window.close()
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def _trace_text(context: SmokeContext) -> str:
    trace_path = context.report_path.parent / "gui_trace.jsonl"
    if not trace_path.exists():
        return ""
    return trace_path.read_text(encoding="utf-8")


def _strict_runtime_evidence_failure(context: SmokeContext, report: dict[str, Any]) -> dict[str, Any] | None:
    from .stability_gate import FORBIDDEN_TEXT_MARKERS, FORBIDDEN_TRACE_KINDS

    markers: list[str] = []
    trace_text = _trace_text(context)
    for line_number, raw_line in enumerate(trace_text.splitlines(), start=1):
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        kind = str(payload.get("kind", ""))
        if kind in FORBIDDEN_TRACE_KINDS:
            markers.append(f"{kind} at trace line {line_number}")
    combined_text = "\n".join((json.dumps(report, sort_keys=True), trace_text))
    for marker in FORBIDDEN_TEXT_MARKERS:
        if marker in combined_text:
            markers.append(marker)
    if not markers:
        return None
    return {
        "name": "strict-runtime-evidence",
        "passed": False,
        "error": "; ".join(markers),
        "duration_seconds": 0,
    }


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _passed(*, name: str, checks: tuple[str, ...], data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "passed": True,
        "checks": tuple({"name": check, "passed": True} for check in checks),
        "data": data or {},
    }
