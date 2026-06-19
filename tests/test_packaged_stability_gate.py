from __future__ import annotations

import json
from pathlib import Path

import pytest

from xml_to_usda.qt_ui.stability_gate import (
    DEFAULT_REQUIRED_SAMPLE_PROFILES,
    StabilityGateError,
    StabilityGateOptions,
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
        assert settings.preserve_trunk_bias == 0.5
        assert settings.force_stump_piece is False
        assert settings.generate_caps is False


def test_crash_dump_collection_can_be_disabled_explicitly(tmp_path: Path) -> None:
    status = prepare_crash_dump_collection(tmp_path, enabled=False)

    assert status["enabled"] is False
    assert "disabled" in status["warning"]


def test_stability_gate_fails_when_packaged_worker_exe_is_missing(tmp_path: Path) -> None:
    dist_path = tmp_path / "dist-next"
    dist_path.mkdir()
    (dist_path / "XMLtoUSDAConverter.exe").write_bytes(b"gui")

    with pytest.raises(StabilityGateError, match="Missing packaged worker executable"):
        run_stability_gate(
            StabilityGateOptions(
                dist_path=dist_path,
                sample_profiles=(),
                iterations=1,
                run_ui=False,
                run_worker=False,
            )
        )


def test_stability_artifact_analysis_can_allow_retry_only_when_requested(tmp_path: Path) -> None:
    report_path = tmp_path / "smoke_report.json"
    stdout_path = tmp_path / "stdout.txt"
    report_path.write_text(json.dumps({"passed": True, "scenarios": []}), encoding="utf-8")
    stdout_path.write_text("Retrying after worker crash...\n", encoding="utf-8")

    result = analyze_stability_artifacts(report_path=report_path, stdout_path=stdout_path, fail_on_retry=False)

    assert result.passed is True
    assert result.retry_count == 1
