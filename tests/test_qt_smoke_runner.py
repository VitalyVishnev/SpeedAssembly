from __future__ import annotations

import json
from pathlib import Path

from xml_to_usda.qt_ui.smoke import (
    HIGH_RISK_SCENARIOS,
    SMOKE_SCENARIO_FRACTURE_PREVIEW_INTERACTIVE,
    SMOKE_SCENARIO_FRACTURE_PREVIEW_RAPID_SETTINGS,
    SMOKE_SCENARIO_PACKAGED_STABILITY,
    SMOKE_SCENARIO_WIND_PREVIEW,
    build_smoke_parser,
    run_smoke_cli,
)


def test_smoke_parser_accepts_required_packaged_smoke_arguments(tmp_path: Path) -> None:
    report_path = tmp_path / "smoke_report.json"
    args = build_smoke_parser().parse_args(
        [
            "--scenario",
            "fracture-preview",
            "--input",
            "tree.xml",
            "--output",
            "tree.usda",
            "--report",
            str(report_path),
            "--timeout-ms",
            "120000",
            "--repeat",
            "2",
            "--debug-trace",
            "--fail-on-retry",
            "--sample-profile",
            "spruce_big_low",
        ]
    )

    assert args.scenario == "fracture-preview"
    assert args.input == "tree.xml"
    assert args.output == "tree.usda"
    assert args.report == str(report_path)
    assert args.timeout_ms == 120000
    assert args.repeat == 2
    assert args.debug_trace is True
    assert args.fail_on_retry is True
    assert args.sample_profile == ["spruce_big_low"]


def test_high_risk_smoke_runs_scenarios_in_deterministic_order(tmp_path: Path) -> None:
    report_path = tmp_path / "smoke_report.json"
    seen: list[str] = []

    def scenario_runner(name, context):
        seen.append(name)
        return {"passed": True, "checks": [{"name": f"{name}.ok", "passed": True}]}

    exit_code = run_smoke_cli(
        [
            "--scenario",
            "high-risk",
            "--input",
            "tree.xml",
            "--output",
            "tree.usda",
            "--report",
            str(report_path),
        ],
        scenario_runner=scenario_runner,
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert SMOKE_SCENARIO_WIND_PREVIEW in HIGH_RISK_SCENARIOS
    assert SMOKE_SCENARIO_FRACTURE_PREVIEW_INTERACTIVE in HIGH_RISK_SCENARIOS
    assert SMOKE_SCENARIO_FRACTURE_PREVIEW_RAPID_SETTINGS in HIGH_RISK_SCENARIOS
    assert seen == list(HIGH_RISK_SCENARIOS)
    assert report["passed"] is True
    assert [scenario["name"] for scenario in report["scenarios"]] == list(HIGH_RISK_SCENARIOS)


def test_smoke_runner_records_failed_assertion_and_returns_nonzero(tmp_path: Path) -> None:
    report_path = tmp_path / "smoke_report.json"

    def scenario_runner(name, context):
        raise AssertionError("viewport mesh was not uploaded")

    exit_code = run_smoke_cli(
        [
            "--scenario",
            "fracture-preview",
            "--input",
            "tree.xml",
            "--output",
            "tree.usda",
            "--report",
            str(report_path),
        ],
        scenario_runner=scenario_runner,
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert report["passed"] is False
    assert report["scenarios"][0]["name"] == "fracture-preview"
    assert report["scenarios"][0]["passed"] is False
    assert "viewport mesh was not uploaded" in report["scenarios"][0]["error"]


def test_packaged_stability_smoke_scenario_runs_interactive_preview_repeatedly(tmp_path: Path) -> None:
    report_path = tmp_path / "smoke_report.json"
    seen: list[str] = []

    def scenario_runner(name, context):
        seen.append(name)
        return {"passed": True, "checks": [{"name": f"{name}.ok", "passed": True}]}

    exit_code = run_smoke_cli(
        [
            "--scenario",
            SMOKE_SCENARIO_PACKAGED_STABILITY,
            "--input",
            "tree.xml",
            "--output",
            "tree.usda",
            "--report",
            str(report_path),
            "--repeat",
            "3",
            "--fail-on-retry",
        ],
        scenario_runner=scenario_runner,
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert seen == [
        SMOKE_SCENARIO_FRACTURE_PREVIEW_INTERACTIVE,
        SMOKE_SCENARIO_FRACTURE_PREVIEW_RAPID_SETTINGS,
    ] * 3
    assert report["scenario"] == SMOKE_SCENARIO_PACKAGED_STABILITY
    assert report["fail_on_retry"] is True


def test_smoke_runner_fail_on_retry_marks_report_failed_from_trace_even_after_success(tmp_path: Path) -> None:
    report_path = tmp_path / "smoke_report.json"
    trace_path = tmp_path / "gui_trace.jsonl"
    trace_path.write_text(json.dumps({"kind": "worker.crash", "job": "fracture_preview"}) + "\n", encoding="utf-8")

    def scenario_runner(name, context):
        return {"passed": True, "checks": [{"name": f"{name}.ok", "passed": True}]}

    exit_code = run_smoke_cli(
        [
            "--scenario",
            "fracture-preview",
            "--input",
            "tree.xml",
            "--output",
            "tree.usda",
            "--report",
            str(report_path),
            "--fail-on-retry",
        ],
        scenario_runner=scenario_runner,
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert report["passed"] is False
    assert report["scenarios"][-1]["name"] == "strict-runtime-evidence"
    assert "worker.crash" in report["scenarios"][-1]["error"]


def test_qt_package_build_waits_for_windowed_smoke_process() -> None:
    script = Path("scripts/build_qt_gui_exe.ps1").read_text(encoding="utf-8")

    assert "System.Diagnostics.ProcessStartInfo" in script
    assert "RedirectStandardOutput = $true" in script
    assert "RedirectStandardError = $true" in script
    assert "$smokeProcess.WaitForExit()" in script
    assert "Test-Path $smokeReportPath" in script


def test_strict_packaged_stability_script_targets_real_problem_trees() -> None:
    script = Path("scripts/run_packaged_stability_gate.ps1").read_text(encoding="utf-8")

    assert "SkeletyalAssemblyTest_Spruce_Big_low.xml" in script
    assert "SkeletalAssemblyTest_03_28mil.xml" in script
    assert "xml_to_usda.qt_ui.stability_gate" in script
    assert "--iterations" in script


def test_fracture_interactive_smoke_waits_for_caps_preview_result() -> None:
    smoke_source = Path("src/xml_to_usda/qt_ui/smoke.py").read_text(encoding="utf-8")

    assert "previous_caps_preview = dialog.current_preview" in smoke_source
    assert "dialog.current_preview is not previous_caps_preview" in smoke_source
    assert '"caps.update"' in smoke_source
