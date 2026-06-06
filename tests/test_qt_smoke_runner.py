from __future__ import annotations

import json
from pathlib import Path

from xml_to_usda.qt_ui.smoke import HIGH_RISK_SCENARIOS, build_smoke_parser, run_smoke_cli


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
        ]
    )

    assert args.scenario == "fracture-preview"
    assert args.input == "tree.xml"
    assert args.output == "tree.usda"
    assert args.report == str(report_path)
    assert args.timeout_ms == 120000
    assert args.repeat == 2
    assert args.debug_trace is True


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
