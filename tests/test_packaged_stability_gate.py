from __future__ import annotations

import json
from pathlib import Path

import pytest

from xml_to_usda.qt_ui.stability_gate import (
    DEFAULT_REQUIRED_SAMPLE_PROFILES,
    StabilityGateError,
    StabilityGateOptions,
    _stability_failure_lines,
    _worker_settings_matrix,
    analyze_stability_artifacts,
    prepare_crash_dump_collection,
    required_sample_paths,
    run_stability_gate,
)


def test_stability_artifact_analysis_fails_on_worker_crash_even_when_report_passed(tmp_path: Path) -> None:
    report_path = tmp_path / "smoke_report.json"
    trace_path = tmp_path / "gui_trace.jsonl"
    report_path.write_text(
        json.dumps(
            {
                "passed": True,
                "scenarios": [{"name": "fracture-preview", "passed": True}],
            }
        ),
        encoding="utf-8",
    )
    trace_path.write_text(
        json.dumps({"kind": "worker.crash", "job": "fracture_preview", "debug": {"exit_code": 3221225477}})
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(StabilityGateError, match="worker.crash"):
        analyze_stability_artifacts(report_path=report_path, trace_path=trace_path)


def test_stability_artifact_analysis_fails_on_retry_text(tmp_path: Path) -> None:
    report_path = tmp_path / "smoke_report.json"
    stdout_path = tmp_path / "stdout.txt"
    report_path.write_text(json.dumps({"passed": True, "scenarios": []}), encoding="utf-8")
    stdout_path.write_text("Fracture Preview worker crashed once. Retrying after worker crash...\n", encoding="utf-8")

    with pytest.raises(StabilityGateError, match="Retrying after worker crash"):
        analyze_stability_artifacts(report_path=report_path, stdout_path=stdout_path)


def test_stability_artifact_analysis_fails_on_missing_report(tmp_path: Path) -> None:
    with pytest.raises(StabilityGateError, match="missing smoke report"):
        analyze_stability_artifacts(report_path=tmp_path / "missing.json")


def test_stability_artifact_analysis_accepts_clean_user_cancellation(tmp_path: Path) -> None:
    report_path = tmp_path / "smoke_report.json"
    trace_path = tmp_path / "gui_trace.jsonl"
    report_path.write_text(json.dumps({"passed": True, "scenarios": []}), encoding="utf-8")
    trace_path.write_text(
        json.dumps({"kind": "worker.cancel_request", "job": "fracture_preview"})
        + "\n"
        + json.dumps({"kind": "worker.cancel_result", "job": "fracture_preview", "debug": {"terminated": False}})
        + "\n",
        encoding="utf-8",
    )

    result = analyze_stability_artifacts(report_path=report_path, trace_path=trace_path)

    assert result.passed is True
    assert result.worker_crash_count == 0
    assert result.retry_count == 0


def test_stability_failure_lines_include_the_nested_smoke_error(tmp_path: Path) -> None:
    smoke_path = tmp_path / "smoke_report.json"
    smoke_path.write_text(
        json.dumps(
            {
                "passed": False,
                "scenarios": [
                    {"name": "fracture-preview", "passed": False, "error": "Fracture cap bone_033 is open."}
                ],
            }
        ),
        encoding="utf-8",
    )
    report = {
        "passed": False,
        "runs": [
            {
                "profile": "spruce",
                "kind": "ui",
                "scenario": "fracture-preview",
                "iteration": 0,
                "passed": False,
                "exit_code": 1,
                "error": "smoke report failed",
                "artifacts": {"smoke_report": {"path": str(smoke_path)}},
            }
        ],
    }

    assert _stability_failure_lines(report) == (
        "spruce/ui/fracture-preview/0: Fracture cap bone_033 is open.",
    )


def test_required_sample_profiles_include_real_problem_trees() -> None:
    assert "spruce_big_low" in DEFAULT_REQUIRED_SAMPLE_PROFILES
    assert "skeletal_28mil" in DEFAULT_REQUIRED_SAMPLE_PROFILES
    assert (
        DEFAULT_REQUIRED_SAMPLE_PROFILES["spruce_big_low"]
        == Path("D:/3D Personal/XMLtoUSD_miscFiles/SkeletyalAssemblyTest_Spruce_Big_low.xml")
    )
    assert (
        DEFAULT_REQUIRED_SAMPLE_PROFILES["skeletal_28mil"]
        == Path("D:/3D Personal/XMLtoUSD_miscFiles/SkeletalAssemblyTest_03_28mil.xml")
    )


def test_required_sample_paths_fail_loudly_when_required_tree_is_missing(tmp_path: Path) -> None:
    missing = tmp_path / "missing.xml"

    with pytest.raises(StabilityGateError, match="Required stability sample is missing"):
        required_sample_paths({"problem": missing})


def test_options_default_to_strict_required_samples_and_many_iterations() -> None:
    options = StabilityGateOptions()

    assert options.worker_iterations >= 50
    assert options.ui_iterations >= 10
    assert tuple(options.sample_profiles) == tuple(DEFAULT_REQUIRED_SAMPLE_PROFILES)
    assert options.fail_on_retry is True
    assert options.enable_crash_dumps is True


def test_worker_stability_matrix_repeats_default_fracture_preview_path() -> None:
    matrix = _worker_settings_matrix(6)

    for settings in (matrix[0], matrix[2], matrix[4]):
        assert settings.target_piece_count == 5
        assert settings.separate_stems is False
        assert settings.branch_height_bias == 0.0
        assert settings.force_stump_piece is False
        assert settings.generate_caps is False


def test_crash_dump_collection_can_be_disabled_explicitly(tmp_path: Path) -> None:
    status = prepare_crash_dump_collection(tmp_path, enabled=False)

    assert status["enabled"] is False
    assert "disabled" in status["warning"]


def test_stability_gate_uses_packaged_gui_exe_for_direct_worker_stress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import xml_to_usda.qt_ui.stability_gate as stability_gate

    dist_path = tmp_path / "dist-next"
    dist_path.mkdir()
    gui_exe = dist_path / "XMLtoUSDAConverter.exe"
    gui_exe.write_bytes(b"gui")
    calls: list[Path] = []

    def run_worker_stress(worker_exe, input_path, report_root, options, profile_name):  # noqa: ARG001
        calls.append(worker_exe)
        return ()

    monkeypatch.setattr(stability_gate, "_run_worker_stress", run_worker_stress)
    monkeypatch.setattr(stability_gate, "required_sample_paths", lambda names: {"sample": tmp_path / "sample.xml"})

    report = run_stability_gate(
        StabilityGateOptions(
            dist_path=dist_path,
            sample_profiles=("sample",),
            iterations=1,
            run_ui=False,
            run_worker=True,
        )
    )

    assert report["passed"] is True
    assert calls == [gui_exe]


def test_stability_artifact_analysis_can_allow_retry_only_when_requested(tmp_path: Path) -> None:
    report_path = tmp_path / "smoke_report.json"
    stdout_path = tmp_path / "stdout.txt"
    report_path.write_text(json.dumps({"passed": True, "scenarios": []}), encoding="utf-8")
    stdout_path.write_text("Retrying after worker crash...\n", encoding="utf-8")

    result = analyze_stability_artifacts(report_path=report_path, stdout_path=stdout_path, fail_on_retry=False)

    assert result.passed is True
    assert result.retry_count == 1
