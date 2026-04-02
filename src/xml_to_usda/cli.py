from __future__ import annotations

import argparse
import sys

from .models import CleanupPolicy, CpuProfile, MaterialPolicy
from .pipeline import convert_file, generate_wind_json, inspect_source
from .prototype_sources import load_prototype_source_configs_from_json
from .runtime_paths import resolve_runtime_paths, sweep_stale_job_workspaces
from .xml_reader import render_inspect_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xml-to-usda")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect observed XML schema.")
    inspect_parser.add_argument("input", help="Path to the source XML file.")

    convert_parser = subparsers.add_parser("convert", help="Convert XML to USDA.")
    convert_parser.add_argument("input", help="Path to the source XML file.")
    convert_parser.add_argument("output", help="Path to the output USDA file.")
    convert_parser.add_argument(
        "--material-policy",
        choices=MaterialPolicy.cli_choices(),
        default=MaterialPolicy.SOURCE_MATERIAL_ROLES.value,
        help="Material authoring mode.",
    )
    convert_parser.add_argument("--bark-material-path", help="Unreal material path for the primary material bucket.")
    convert_parser.add_argument("--leaves-material-path", help="Unreal material path for the secondary material bucket.")
    convert_parser.add_argument("--single-material-path", help="Unreal material path used by single_material mode.")
    convert_parser.add_argument(
        "--part-source-config",
        help="Path to a JSON object keyed by prototype name or Mesh_<id> with per-prototype source mode config.",
    )
    convert_parser.add_argument(
        "--cpu-profile",
        choices=[profile.value for profile in CpuProfile],
        default=CpuProfile.BALANCED.value,
        help="CPU usage profile for heavy FBX and USDA export work.",
    )
    convert_parser.add_argument(
        "--preserve-temp-files",
        action="store_true",
        help="Keep runtime job temp files and manifests for debugging instead of cleaning them immediately.",
    )

    wind_parser = subparsers.add_parser("generate-wind-json", help="Generate Dynamic Wind JSON from XML.")
    wind_parser.add_argument("input", help="Path to the source XML file.")
    wind_parser.add_argument("output", help="Path to the output JSON file.")

    subparsers.add_parser("gui", help="Launch the desktop GUI.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    runtime_paths = resolve_runtime_paths()
    _report_runtime_cleanup_summary(sweep_stale_job_workspaces(runtime_paths))

    try:
        if args.command == "inspect":
            return _run_inspect(args.input)
        if args.command == "convert":
            return _run_convert(
                args.input,
                args.output,
                MaterialPolicy.parse(args.material_policy),
                bark_material_path=args.bark_material_path,
                leaves_material_path=args.leaves_material_path,
                single_material_path=args.single_material_path,
                part_source_config_path=args.part_source_config,
                cpu_profile=CpuProfile(args.cpu_profile),
                cleanup_policy=(
                    CleanupPolicy.PRESERVE_FOR_DEBUGGING
                    if args.preserve_temp_files
                    else CleanupPolicy.EPHEMERAL
                ),
                runtime_paths=runtime_paths,
            )
        if args.command == "generate-wind-json":
            return _run_generate_wind_json(args.input, args.output)
        if args.command == "gui":
            from .gui import main as gui_main

            return gui_main()
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2

    parser.error(f"Unsupported command: {args.command}")
    return 2


def _run_inspect(input_path: str) -> int:
    report = inspect_source(input_path)
    sys.stdout.write(render_inspect_report(report) + "\n")
    return 0


def _run_convert(
    input_path: str,
    output_path: str,
    material_policy: MaterialPolicy,
    bark_material_path: str | None = None,
    leaves_material_path: str | None = None,
    single_material_path: str | None = None,
    part_source_config_path: str | None = None,
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
    cleanup_policy: CleanupPolicy = CleanupPolicy.EPHEMERAL,
    runtime_paths=None,
) -> int:
    prototype_source_configs = (
        load_prototype_source_configs_from_json(part_source_config_path)
        if part_source_config_path
        else ()
    )
    result = convert_file(
        input_path,
        output_path,
        material_policy=material_policy,
        bark_material_path=bark_material_path,
        leaves_material_path=leaves_material_path,
        single_material_path=single_material_path,
        cpu_profile=cpu_profile,
        cleanup_policy=cleanup_policy,
        prototype_source_configs=prototype_source_configs,
        runtime_paths=runtime_paths,
    )
    for issue in result.diagnostics:
        _print_issue(issue)
    if result.usda_document is None:
        return 1
    sys.stdout.write(f"Wrote USDA to {result.output_path}\n")
    return 0


def _run_generate_wind_json(input_path: str, output_path: str) -> int:
    result = generate_wind_json(input_path, output_path)
    sys.stdout.write(f"Wrote wind JSON to {result.output_path}\n")
    return 0


def _print_issue(issue) -> None:
    sys.stderr.write(f"[{issue.severity}] {issue.code}: {issue.message}\n")


def _report_runtime_cleanup_summary(summary) -> None:
    if not summary.has_activity:
        return
    sys.stderr.write(f"[info] runtime_cleanup: {summary.to_message()}\n")
    for failed_path in summary.failed_paths:
        sys.stderr.write(f"[warning] runtime_cleanup: stale job workspace not removed: {failed_path}\n")


if __name__ == "__main__":
    raise SystemExit(main())
