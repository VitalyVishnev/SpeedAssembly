"""Strict packaged runtime stability gate.

Layer: release diagnostics.

This module validates packaged smoke evidence. It deliberately treats any
worker crash or retry as a failed run, even if a later preview succeeds.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_REQUIRED_SAMPLE_PROFILES: dict[str, Path] = {
    "spruce_big_low": Path("D:/3D Personal/XMLtoUSD_miscFiles/SkeletyalAssemblyTest_Spruce_Big_low.xml"),
    "skeletal_28mil": Path("D:/3D Personal/XMLtoUSD_miscFiles/SkeletalAssemblyTest_03_28mil.xml"),
}

FORBIDDEN_TRACE_KINDS = frozenset(
    {
        "worker.crash",
        "worker.error",
    }
)
FORBIDDEN_TEXT_MARKERS = (
    "Retrying after worker crash",
    "worker crashed once",
    "worker process crashed unexpectedly",
    "Preview generation failed",
    "Fracture Preview failed",
    "Proxy Preview failed",
)


class StabilityGateError(RuntimeError):
    """Raised when packaged runtime evidence proves instability."""


@dataclass(frozen=True)
class StabilityArtifactAnalysis:
    passed: bool
    worker_crash_count: int = 0
    retry_count: int = 0
    forbidden_markers: tuple[str, ...] = ()


@dataclass(frozen=True)
class StabilityGateOptions:
    dist_path: Path = Path("dist-next")
    report_path: Path | None = None
    sample_profiles: tuple[str, ...] = tuple(DEFAULT_REQUIRED_SAMPLE_PROFILES)
    iterations: int = 0
    worker_iterations: int = 50
    ui_iterations: int = 10
    timeout_ms: int = 180_000
    fail_on_retry: bool = True
    run_ui: bool = True
    run_worker: bool = True
    enable_crash_dumps: bool = True


def analyze_stability_artifacts(
    *,
    report_path: Path,
    trace_path: Path | None = None,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
    fail_on_retry: bool = True,
) -> StabilityArtifactAnalysis:
    """Fail loudly on instability markers from packaged smoke artifacts."""

    report_path = Path(report_path)
    if not report_path.exists():
        raise StabilityGateError(f"missing smoke report: {report_path}")
    report = _read_json_object(report_path)
    if not bool(report.get("passed")):
        raise StabilityGateError(f"smoke report failed: {report_path}")

    worker_crash_count = 0
    forbidden: list[str] = []
    trace_text = _read_optional_text(trace_path)
    for line_number, event in _iter_trace_events(trace_text):
        kind = str(event.get("kind", ""))
        if kind in FORBIDDEN_TRACE_KINDS:
            worker_crash_count += 1
            forbidden.append(f"{kind} at trace line {line_number}")

    combined_text = "\n".join(
        text
        for text in (
            json.dumps(report, sort_keys=True),
            trace_text,
            _read_optional_text(stdout_path),
            _read_optional_text(stderr_path),
        )
        if text
    )
    retry_count = sum(combined_text.count(marker) for marker in FORBIDDEN_TEXT_MARKERS)
    for marker in FORBIDDEN_TEXT_MARKERS:
        if fail_on_retry and marker in combined_text:
            forbidden.append(marker)

    if forbidden:
        raise StabilityGateError("Packaged stability gate found forbidden runtime evidence: " + "; ".join(forbidden))
    return StabilityArtifactAnalysis(
        passed=True,
        worker_crash_count=worker_crash_count,
        retry_count=retry_count,
        forbidden_markers=tuple(forbidden),
    )


def required_sample_paths(
    profiles: dict[str, Path] | None = None,
    *,
    names: Iterable[str] | None = None,
) -> dict[str, Path]:
    """Resolve required real-tree sample paths and fail if any is unavailable."""

    available = profiles or DEFAULT_REQUIRED_SAMPLE_PROFILES
    requested = tuple(names) if names is not None else tuple(available)
    resolved: dict[str, Path] = {}
    for name in requested:
        if name not in available:
            raise StabilityGateError(f"Unknown stability sample profile: {name}")
        path = Path(available[name])
        if not path.exists():
            raise StabilityGateError(f"Required stability sample is missing: {name} -> {path}")
        resolved[name] = path
    return resolved


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="packaged-stability-gate")
    parser.add_argument("--dist-path", default="dist-next")
    parser.add_argument("--report", default="")
    parser.add_argument("--iterations", type=int, default=0)
    parser.add_argument("--worker-iterations", type=int, default=50)
    parser.add_argument("--ui-iterations", type=int, default=10)
    parser.add_argument("--timeout-ms", type=int, default=180_000)
    parser.add_argument("--sample-profile", action="append", default=[])
    parser.add_argument("--skip-ui", action="store_true")
    parser.add_argument("--skip-worker", action="store_true")
    parser.add_argument("--allow-retry", action="store_true")
    parser.add_argument("--no-crash-dumps", action="store_true")
    return parser


def run_stability_gate_cli(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    options = StabilityGateOptions(
        dist_path=Path(args.dist_path),
        report_path=Path(args.report) if args.report else None,
        sample_profiles=tuple(args.sample_profile) if args.sample_profile else tuple(DEFAULT_REQUIRED_SAMPLE_PROFILES),
        iterations=max(0, int(args.iterations)),
        worker_iterations=max(1, int(args.worker_iterations)),
        ui_iterations=max(1, int(args.ui_iterations)),
        timeout_ms=max(1_000, int(args.timeout_ms)),
        fail_on_retry=not bool(args.allow_retry),
        run_ui=not bool(args.skip_ui),
        run_worker=not bool(args.skip_worker),
        enable_crash_dumps=not bool(args.no_crash_dumps),
    )
    try:
        report = run_stability_gate(options)
    except Exception as exc:
        report_path = options.report_path or Path(options.dist_path) / "stability" / "stability_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps({"schema_version": 1, "passed": False, "error": str(exc)}, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(f"Packaged stability gate failed: {exc}", file=sys.stderr)
        return 1
    report_path = options.report_path or Path(options.dist_path) / "stability" / "stability_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if not bool(report.get("passed")):
        for failure in _stability_failure_lines(report):
            print(f"Packaged stability failure: {failure}", file=sys.stderr)
    return 0 if bool(report.get("passed")) else 1


def _stability_failure_lines(report: dict[str, object]) -> tuple[str, ...]:
    lines: list[str] = []
    for run in report.get("runs", ()):
        if not isinstance(run, dict) or bool(run.get("passed")):
            continue
        label = "/".join(
            str(value)
            for value in (run.get("profile"), run.get("kind"), run.get("scenario"), run.get("iteration"))
            if value not in (None, "")
        )
        detail = str(run.get("error") or f"exit code {run.get('exit_code')}")
        artifacts = run.get("artifacts")
        smoke_artifact = artifacts.get("smoke_report") if isinstance(artifacts, dict) else None
        smoke_path = smoke_artifact.get("path") if isinstance(smoke_artifact, dict) else None
        if smoke_path and Path(str(smoke_path)).exists():
            try:
                smoke_report = json.loads(Path(str(smoke_path)).read_text(encoding="utf-8"))
                scenario_errors = tuple(
                    str(scenario.get("error"))
                    for scenario in smoke_report.get("scenarios", ())
                    if isinstance(scenario, dict) and not bool(scenario.get("passed")) and scenario.get("error")
                )
                if scenario_errors:
                    detail = " | ".join(scenario_errors)
            except (OSError, json.JSONDecodeError):
                pass
        lines.append(f"{label}: {detail}")
    return tuple(lines)


def run_stability_gate(options: StabilityGateOptions) -> dict[str, object]:
    dist_path = Path(options.dist_path)
    gui_exe = dist_path / "SpeedAssembly.exe"
    if not gui_exe.exists():
        raise StabilityGateError(f"Missing packaged GUI executable: {gui_exe}")

    samples = required_sample_paths(names=options.sample_profiles)
    report_root = options.report_path.parent if options.report_path else dist_path / "stability"
    report_root.mkdir(parents=True, exist_ok=True)
    crash_dump_status = prepare_crash_dump_collection(report_root, enabled=options.enable_crash_dumps)
    runs: list[dict[str, object]] = []
    started = time.time()
    for profile_name, input_path in samples.items():
        if options.run_worker:
            runs.extend(_run_worker_stress(gui_exe, input_path, report_root, options, profile_name))
        if options.run_ui:
            runs.extend(_run_ui_stress(gui_exe, input_path, report_root, options, profile_name))
    passed = all(bool(run.get("passed")) for run in runs)
    return {
        "schema_version": 1,
        "passed": passed,
        "duration_seconds": round(time.time() - started, 3),
        "worker_iterations": _effective_worker_iterations(options),
        "ui_iterations": _effective_ui_iterations(options),
        "sample_profiles": tuple(samples),
        "crash_dump_collection": crash_dump_status,
        "runs": runs,
    }


def prepare_crash_dump_collection(report_root: Path, *, enabled: bool = True) -> dict[str, object]:
    if not enabled:
        return {"enabled": False, "warning": "Crash dump collection disabled by option."}
    if sys.platform != "win32":
        return {"enabled": False, "warning": "Windows crash dump collection is only available on Windows."}
    dump_dir = Path(report_root) / "crash_dumps"
    dump_dir.mkdir(parents=True, exist_ok=True)
    try:
        import winreg

        base_path = r"Software\Microsoft\Windows\Windows Error Reporting\LocalDumps"
        for executable_name in ("SpeedAssembly.exe",):
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, base_path + "\\" + executable_name)
            try:
                winreg.SetValueEx(key, "DumpFolder", 0, winreg.REG_EXPAND_SZ, str(dump_dir))
                winreg.SetValueEx(key, "DumpCount", 0, winreg.REG_DWORD, 10)
                winreg.SetValueEx(key, "DumpType", 0, winreg.REG_DWORD, 2)
            finally:
                winreg.CloseKey(key)
    except Exception as exc:
        return {
            "enabled": False,
            "dump_dir": str(dump_dir),
            "warning": f"Could not enable Windows LocalDumps: {exc}",
        }
    return {
        "enabled": True,
        "dump_dir": str(dump_dir),
        "executables": ("SpeedAssembly.exe",),
    }


def _run_worker_stress(
    worker_exe: Path,
    input_path: Path,
    report_root: Path,
    options: StabilityGateOptions,
    profile_name: str,
) -> list[dict[str, object]]:
    # The direct packaged-worker contract is validated in a separate scriptable
    # path below; UI smoke remains the primary high-risk end-to-end signal.
    runs: list[dict[str, object]] = []
    from ..fracture_preview_service import FracturePreviewSettings, FracturePreviewSourceRequest
    from ..fracture_service import FractureSettings
    from ..fracture_worker_subprocess import (
        FRACTURE_WORKER_ACTION_PREVIEW,
        FractureWorkerRequest,
        write_fracture_worker_request,
    )
    from ..worker_commands import FRACTURE_WORKER_COMMAND
    from ..worker_file_protocol import new_worker_token, worker_env

    settings_matrix = _worker_settings_matrix(_effective_worker_iterations(options))
    for index, fracture_settings in enumerate(settings_matrix):
        run_dir = report_root / profile_name / "worker" / f"{index:03d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        request_path = run_dir / "request.json"
        result_path = run_dir / "result.json"
        error_path = run_dir / "error.json"
        stdout_path = run_dir / "stdout.txt"
        stderr_path = run_dir / "stderr.txt"
        worker_token = new_worker_token()
        write_fracture_worker_request(
            request_path,
            FractureWorkerRequest(
                request=FracturePreviewSourceRequest(
                    input_path=str(input_path),
                    output_path=str(run_dir / f"{input_path.stem}.usda"),
                ),
                settings=FracturePreviewSettings(fracture=fracture_settings),
                action=FRACTURE_WORKER_ACTION_PREVIEW,
                result_path=str(result_path),
                error_path=str(error_path),
                worker_token=worker_token,
            ),
        )
        with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
            process = subprocess.run(
                [str(worker_exe), FRACTURE_WORKER_COMMAND, "--request", str(request_path)],
                stdout=stdout_handle,
                stderr=stderr_handle,
                timeout=options.timeout_ms / 1000,
                check=False,
                env=worker_env(worker_token),
            )
        passed = process.returncode == 0 and result_path.exists() and not error_path.exists()
        runs.append(
            {
                "kind": "worker",
                "profile": profile_name,
                "iteration": index,
                "passed": passed,
                "exit_code": process.returncode,
                "settings": _fracture_settings_payload(fracture_settings),
                "artifacts": _artifact_payload(request_path, result_path, error_path, stdout_path, stderr_path),
            }
        )
    return runs


def _run_ui_stress(
    gui_exe: Path,
    input_path: Path,
    report_root: Path,
    options: StabilityGateOptions,
    profile_name: str,
) -> list[dict[str, object]]:
    runs: list[dict[str, object]] = []
    for index in range(_effective_ui_iterations(options)):
        for scenario in ("fracture-preview-interactive", "fracture-preview-rapid-settings", "proxy-preview"):
            run_dir = report_root / profile_name / "ui" / scenario / f"{index:03d}"
            run_dir.mkdir(parents=True, exist_ok=True)
            report_path = run_dir / "smoke_report.json"
            stdout_path = run_dir / "stdout.txt"
            stderr_path = run_dir / "stderr.txt"
            with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
                process = subprocess.run(
                    [
                        str(gui_exe),
                        "smoke",
                        "--scenario",
                        scenario,
                        "--input",
                        str(input_path),
                        "--output",
                        str(run_dir / f"{input_path.stem}.usda"),
                        "--report",
                        str(report_path),
                        "--timeout-ms",
                        str(options.timeout_ms),
                        "--debug-trace",
                    ],
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    timeout=options.timeout_ms / 1000,
                    check=False,
                )
            trace_path = run_dir / "gui_trace.jsonl"
            passed = process.returncode == 0
            error = ""
            try:
                analyze_stability_artifacts(
                    report_path=report_path,
                    trace_path=trace_path,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    fail_on_retry=options.fail_on_retry,
                )
            except StabilityGateError as exc:
                passed = False
                error = str(exc)
            runs.append(
                {
                    "kind": "ui",
                    "scenario": scenario,
                    "profile": profile_name,
                    "iteration": index,
                    "passed": passed,
                    "exit_code": process.returncode,
                    "error": error,
                    "artifacts": _artifact_payload(report_path, trace_path, stdout_path, stderr_path),
                }
            )
    return runs


def _effective_worker_iterations(options: StabilityGateOptions) -> int:
    return options.iterations if options.iterations > 0 else options.worker_iterations


def _effective_ui_iterations(options: StabilityGateOptions) -> int:
    return options.iterations if options.iterations > 0 else options.ui_iterations


def _worker_settings_matrix(iterations: int):
    from ..fracture_service import FractureSettings

    baseline = FractureSettings(
        target_piece_count=5,
        generate_caps=False,
        force_stump_piece=False,
        separate_stems=False,
        branch_height_bias=0.0,
    )
    targets = (5, 14, 26, 48)
    height_biases = (-1.0, 0.0, 1.0)
    items: list[FractureSettings] = []
    for target in targets:
        for generate_caps in (False, True):
            for force_stump_piece in (False, True):
                for separate_stems in (False, True):
                    for bias in height_biases:
                        items.append(
                            FractureSettings(
                                target_piece_count=target,
                                generate_caps=generate_caps,
                                force_stump_piece=force_stump_piece,
                                separate_stems=separate_stems,
                                branch_height_bias=bias,
                            )
                        )
    matrix: list[FractureSettings] = []
    scenario_index = 0
    while len(matrix) < max(1, iterations):
        matrix.append(baseline)
        if len(matrix) >= max(1, iterations):
            break
        matrix.append(items[scenario_index % len(items)])
        scenario_index += 1
    return tuple(matrix)


def _fracture_settings_payload(settings) -> dict[str, object]:
    return {
        "target_branch_count": settings.target_piece_count,
        "generate_caps": settings.generate_caps,
        "force_stump_piece": settings.force_stump_piece,
        "separate_stems": settings.separate_stems,
        "branch_height_bias": settings.branch_height_bias,
        "detailed_cuts_enabled": settings.detailed_cuts_enabled,
        "detailed_cut_intensity": settings.detailed_cut_intensity,
        "detailed_cut_scale": settings.detailed_cut_scale,
        "detailed_cut_density": settings.detailed_cut_density,
    }


def _artifact_payload(*paths: Path) -> dict[str, object]:
    return {
        path.stem: {
            "path": str(path),
            "exists": path.exists(),
            "size": path.stat().st_size if path.exists() else None,
        }
        for path in paths
    }


def _read_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise StabilityGateError(f"JSON report must be an object: {path}")
    return payload


def _read_optional_text(path: Path | None) -> str:
    if path is None or not Path(path).exists():
        return ""
    return Path(path).read_text(encoding="utf-8", errors="replace")


def _iter_trace_events(text: str):
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            yield line_number, payload


if __name__ == "__main__":
    raise SystemExit(run_stability_gate_cli())
