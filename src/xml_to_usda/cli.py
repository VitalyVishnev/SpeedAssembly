from __future__ import annotations

import argparse
import multiprocessing
import sys
import time

from .fbx_adapter import load_fbx_geometry
from .fbx_payload_cache import FbxPayloadCacheOptions, load_fbx_payload_from_cache, store_fbx_payload_in_cache
from .fbx_worker_subprocess import FBX_WORKER_COMMAND, run_fbx_worker_request_file
from .conversion_worker_subprocess import CONVERSION_WORKER_COMMAND, run_conversion_worker_request_file
from .conversion_orchestrator import convert_request
from .conversion_service import prepare_conversion_plan
from .fracture_worker_subprocess import FRACTURE_WORKER_COMMAND, run_fracture_worker_request_file
from .models import CleanupPolicy, CpuProfile, FbxMaterialMode, GeometryBuffer, MaterialPolicy
from .part_preview_worker_subprocess import PART_PREVIEW_WORKER_COMMAND, run_part_preview_worker_request_file
from .pipeline import generate_wind_json, inspect_source
from .prototype_sources import fbx_import_read_options_for_material_mode, load_prototype_source_configs_from_json
from .proxy_mesh_worker_subprocess import PROXY_MESH_WORKER_COMMAND, run_proxy_mesh_worker_request_file
from .runtime_paths import resolve_runtime_paths, sweep_stale_job_workspaces
from .udim_settings import load_udim_material_settings_from_json
from .xml_reader import render_inspect_report


CLI_ASYNC_THRESHOLD_BYTES = 2**63 - 1


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
        default=MaterialPolicy.SOURCE_MATERIALS.value,
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
        "--udim-settings",
        help="Path to a JSON array with per-material UDIM mode and udim_id settings.",
    )
    convert_parser.add_argument(
        "--cpu-profile",
        choices=[profile.value for profile in CpuProfile],
        default=CpuProfile.BALANCED.value,
        help="CPU usage profile for heavy FBX and USDA export work. Default: balanced.",
    )
    convert_parser.add_argument(
        "--preserve-temp-files",
        action="store_true",
        help="Keep runtime job temp files and manifests for debugging instead of cleaning them immediately.",
    )

    wind_parser = subparsers.add_parser("generate-wind-json", help="Generate Dynamic Wind JSON from XML.")
    wind_parser.add_argument("input", help="Path to the source XML file.")
    wind_parser.add_argument("output", help="Path to the output JSON file.")

    benchmark_fbx_parser = subparsers.add_parser("benchmark-fbx", help="Benchmark one explicit Assembly Part FBX payload.")
    benchmark_fbx_parser.add_argument("input", help="Path to the FBX file.")
    benchmark_fbx_parser.add_argument(
        "--material-mode",
        choices=[mode.value for mode in FbxMaterialMode],
        default=FbxMaterialMode.SINGLE_MATERIAL.value,
        help="Repeated-part material mode to benchmark. Default: single_material.",
    )
    benchmark_fbx_parser.add_argument(
        "--cpu-profile",
        choices=[profile.value for profile in CpuProfile],
        default=CpuProfile.BALANCED.value,
        help="CPU usage profile for the benchmark. Default: balanced.",
    )

    subparsers.add_parser("gui", help="Launch the primary PySide6 desktop GUI.")
    fbx_worker_parser = subparsers.add_parser(FBX_WORKER_COMMAND, help=argparse.SUPPRESS)
    fbx_worker_parser.add_argument("--request", required=True, help=argparse.SUPPRESS)
    conversion_worker_parser = subparsers.add_parser(CONVERSION_WORKER_COMMAND, help=argparse.SUPPRESS)
    conversion_worker_parser.add_argument("--request", required=True, help=argparse.SUPPRESS)
    proxy_worker_parser = subparsers.add_parser(PROXY_MESH_WORKER_COMMAND, help=argparse.SUPPRESS)
    proxy_worker_parser.add_argument("--request", required=True, help=argparse.SUPPRESS)
    fracture_worker_parser = subparsers.add_parser(FRACTURE_WORKER_COMMAND, help=argparse.SUPPRESS)
    fracture_worker_parser.add_argument("--request", required=True, help=argparse.SUPPRESS)
    part_preview_worker_parser = subparsers.add_parser(PART_PREVIEW_WORKER_COMMAND, help=argparse.SUPPRESS)
    part_preview_worker_parser.add_argument("--request", required=True, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv[:1] == ["gui"]:
        runtime_paths = resolve_runtime_paths()
        _report_runtime_cleanup_summary(sweep_stale_job_workspaces(runtime_paths))
        from .qt_ui.entry import main as gui_main

        return gui_main(raw_argv[1:])

    parser = build_parser()
    args = parser.parse_args(raw_argv)
    if args.command == FBX_WORKER_COMMAND:
        return run_fbx_worker_request_file(args.request)
    if args.command == CONVERSION_WORKER_COMMAND:
        return run_conversion_worker_request_file(args.request)
    if args.command == PROXY_MESH_WORKER_COMMAND:
        return run_proxy_mesh_worker_request_file(args.request)
    if args.command == FRACTURE_WORKER_COMMAND:
        return run_fracture_worker_request_file(args.request)
    if args.command == PART_PREVIEW_WORKER_COMMAND:
        return run_part_preview_worker_request_file(args.request)
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
                udim_settings_path=args.udim_settings,
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
        if args.command == "benchmark-fbx":
            return _run_benchmark_fbx(
                args.input,
                material_mode=FbxMaterialMode(args.material_mode),
                cpu_profile=CpuProfile(args.cpu_profile),
            )
        if args.command == "gui":
            from .qt_ui.entry import main as gui_main

            return gui_main([])
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
    udim_settings_path: str | None = None,
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
    cleanup_policy: CleanupPolicy = CleanupPolicy.EPHEMERAL,
    runtime_paths=None,
) -> int:
    prototype_source_configs = (
        load_prototype_source_configs_from_json(part_source_config_path)
        if part_source_config_path
        else ()
    )
    udim_material_settings = (
        load_udim_material_settings_from_json(udim_settings_path)
        if udim_settings_path
        else ()
    )
    plan = prepare_conversion_plan(
        input_path=input_path,
        output_path=output_path,
        cpu_profile=cpu_profile,
        cleanup_policy=cleanup_policy,
        material_policy=material_policy,
        bark_material_path=bark_material_path,
        leaves_material_path=leaves_material_path,
        single_material_path=single_material_path,
        base_material_overrides=(),
        prototype_source_configs=prototype_source_configs,
        async_threshold_bytes=CLI_ASYNC_THRESHOLD_BYTES,
        udim_material_settings=udim_material_settings,
    )
    result = convert_request(plan.request, runtime_paths=runtime_paths)[0]
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


def _run_benchmark_fbx(
    input_path: str,
    *,
    material_mode: FbxMaterialMode,
    cpu_profile: CpuProfile,
) -> int:
    read_options = fbx_import_read_options_for_material_mode(material_mode)
    options = FbxPayloadCacheOptions(
        read_vertex_colors=read_options.read_vertex_colors,
        read_material_slots=read_options.read_material_slots,
        strict_vertex_colors=read_options.strict_vertex_colors,
    )
    started_at = time.perf_counter()
    cache_result = load_fbx_payload_from_cache(input_path, options)
    cache_seconds = time.perf_counter() - started_at
    payload = cache_result.payload
    import_seconds = 0.0
    store_seconds = 0.0
    telemetry_messages: list[str] = []
    if payload is None:
        import_started_at = time.perf_counter()
        payload = load_fbx_geometry(
            input_path,
            "BenchmarkPayload",
            cpu_profile=cpu_profile,
            strict_vertex_colors=read_options.strict_vertex_colors,
            read_vertex_colors=read_options.read_vertex_colors,
            read_material_slots=read_options.read_material_slots,
            telemetry_callback=lambda telemetry: telemetry_messages.append(telemetry.message),
        )
        import_seconds = time.perf_counter() - import_started_at
        if isinstance(payload, GeometryBuffer):
            store_started_at = time.perf_counter()
            store_fbx_payload_in_cache(input_path, options, payload)
            store_seconds = time.perf_counter() - store_started_at

    sys.stdout.write(f"FBX benchmark: {input_path}\n")
    sys.stdout.write(f"material_mode: {material_mode.value}\n")
    sys.stdout.write(f"cache_hit: {cache_result.hit}\n")
    sys.stdout.write(f"cache_lookup_seconds: {cache_seconds:.3f}\n")
    sys.stdout.write(f"import_seconds: {import_seconds:.3f}\n")
    sys.stdout.write(f"cache_store_seconds: {store_seconds:.3f}\n")
    if isinstance(payload, GeometryBuffer):
        sys.stdout.write(f"points: {payload.point_count}\n")
        sys.stdout.write(f"faces: {payload.face_count}\n")
        sys.stdout.write(f"uvs: {payload.uv_count}\n")
        sys.stdout.write(f"vertex_colors: {payload.vertex_color_count}\n")
        sys.stdout.write(f"material_slots: {len(payload.fbx_material_slots)}\n")
    for message in telemetry_messages:
        if message:
            sys.stdout.write(f"stage: {message}\n")
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
