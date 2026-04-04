"""Conversion orchestration over validated requests and runtime workspaces.

Layer: application/infrastructure boundary.

This module owns the request-level conversion flow, runtime job workspace
lifecycles, telemetry bridging, and final `ConversionResult` assembly. It
should not absorb GUI behavior or low-level USDA authoring logic.
"""

from __future__ import annotations

from .canonical_loader import load_canonical_model
from .conversion_validation import validate_conversion_request
from .job_control import ConversionCancelledError, throw_if_cancelled
from .models import (
    BaseMaterialOverride,
    CleanupPolicy,
    ConversionRequest,
    ConversionResult,
    CpuProfile,
    MaterialPolicy,
    OutputMode,
    PrototypeSourceConfig,
    ValidationIssue,
)
from .output_resolution import ensure_output_path_allowed, resolve_output_path
from .runtime_paths import JobWorkspace, RuntimePaths, resolve_runtime_paths
from .usda_writer import write_usda_document


def convert_file(
    input_path: str,
    output_path: str | None,
    output_mode: OutputMode = OutputMode.SELF_CONTAINED,
    material_policy: MaterialPolicy = MaterialPolicy.SOURCE_MATERIAL_ROLES,
    bark_material_path: str | None = None,
    leaves_material_path: str | None = None,
    single_material_path: str | None = None,
    base_material_overrides: tuple[BaseMaterialOverride, ...] = (),
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
    cleanup_policy: CleanupPolicy = CleanupPolicy.EPHEMERAL,
    use_explicit_material_contract: bool = False,
    prototype_source_configs: tuple[PrototypeSourceConfig, ...] = (),
    use_existing_part_meshes: bool = False,
    part_mesh_asset_paths: tuple[tuple[str, str], ...] = (),
    telemetry_callback=None,
    cancel_event=None,
    runtime_paths: RuntimePaths | None = None,
) -> ConversionResult:
    """Convenience wrapper that converts one input path via `ConversionRequest`."""
    request = ConversionRequest(
        input_paths=(input_path,),
        output_path=output_path,
        output_mode=output_mode,
        material_policy=material_policy,
        bark_material_path=bark_material_path,
        leaves_material_path=leaves_material_path,
        single_material_path=single_material_path,
        base_material_overrides=base_material_overrides,
        cpu_profile=cpu_profile,
        cleanup_policy=cleanup_policy,
        use_explicit_material_contract=use_explicit_material_contract,
        prototype_source_configs=prototype_source_configs,
        use_existing_part_meshes=use_existing_part_meshes,
        part_mesh_asset_paths=part_mesh_asset_paths,
    )
    return convert_request(
        request,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
        runtime_paths=runtime_paths,
    )[0]


def convert_request(
    request: ConversionRequest,
    telemetry_callback=None,
    cancel_event=None,
    runtime_paths: RuntimePaths | None = None,
) -> tuple[ConversionResult, ...]:
    """Convert one or more inputs described by a validated request."""
    validate_conversion_request(request)

    results: list[ConversionResult] = []
    resolved_runtime_paths = runtime_paths or resolve_runtime_paths()
    for input_path in request.input_paths:
        throw_if_cancelled(cancel_event)
        results.append(
            _convert_single_input(
                request=request,
                input_path=input_path,
                telemetry_callback=telemetry_callback,
                cancel_event=cancel_event,
                runtime_paths=resolved_runtime_paths,
            )
        )
    return tuple(results)


def _convert_single_input(
    *,
    request: ConversionRequest,
    input_path: str,
    telemetry_callback,
    cancel_event,
    runtime_paths: RuntimePaths,
) -> ConversionResult:
    resolved_output = resolve_output_path(request, input_path)
    if resolved_output is not None:
        ensure_output_path_allowed(resolved_output)

    job_workspace = JobWorkspace.create(
        runtime_paths,
        input_path=input_path,
        output_path=str(resolved_output) if resolved_output is not None else None,
        cleanup_policy=request.cleanup_policy,
    )
    runtime_telemetry = _wrap_runtime_telemetry_callback(telemetry_callback, job_workspace)
    try:
        _, model, diagnostics = load_canonical_model(
            input_path,
            request.output_mode,
            material_policy=request.material_policy,
            bark_material_path=request.bark_material_path,
            leaves_material_path=request.leaves_material_path,
            single_material_path=request.single_material_path,
            base_material_overrides=request.base_material_overrides,
            cpu_profile=request.cpu_profile,
            use_explicit_material_contract=request.use_explicit_material_contract,
            prototype_source_configs=request.prototype_source_configs,
            use_existing_part_meshes=request.use_existing_part_meshes,
            part_mesh_asset_paths=request.part_mesh_asset_paths,
            telemetry_callback=runtime_telemetry,
            cancel_event=cancel_event,
        )
        errors = [issue for issue in diagnostics if issue.severity == "error"]
        if errors:
            diagnostics = _append_cleanup_warning(
                diagnostics,
                job_workspace.finalize(status="failed"),
            )
            return ConversionResult(
                input_path=input_path,
                output_path=str(resolved_output) if resolved_output is not None else None,
                diagnostics=diagnostics,
                usda_document=None,
                telemetry=(),
                runtime_job_dir=str(job_workspace.job_dir) if job_workspace.debug_preserve else None,
            )

        usda_document = write_usda_document(
            model,
            diagnostics,
            output_path=resolved_output,
            base_mesh_name=resolved_output.stem if resolved_output is not None else None,
            telemetry_callback=runtime_telemetry,
            cancel_event=cancel_event,
        )
    except ConversionCancelledError:
        diagnostics = _append_cleanup_warning((), job_workspace.finalize(status="cancelled"))
        return ConversionResult(
            input_path=input_path,
            output_path=str(resolved_output) if resolved_output is not None else None,
            diagnostics=diagnostics,
            usda_document=None,
            telemetry=(),
            runtime_job_dir=str(job_workspace.job_dir) if job_workspace.debug_preserve else None,
        )
    except Exception as exc:
        cleanup_warning = job_workspace.finalize(status="failed", error_message=str(exc))
        if cleanup_warning:
            raise RuntimeError(f"{exc}\nRuntime cleanup warning: {cleanup_warning}") from exc
        raise

    diagnostics = _append_cleanup_warning(diagnostics, job_workspace.finalize(status="succeeded"))
    return ConversionResult(
        input_path=input_path,
        output_path=str(resolved_output) if resolved_output is not None else None,
        diagnostics=diagnostics,
        usda_document=usda_document,
        telemetry=(),
        runtime_job_dir=str(job_workspace.job_dir) if job_workspace.debug_preserve else None,
    )


def _wrap_runtime_telemetry_callback(callback, job_workspace: JobWorkspace):
    def _wrapped(telemetry) -> None:
        job_workspace.update_phase(telemetry.phase)
        if callback is not None:
            callback(telemetry)

    return _wrapped


def _append_cleanup_warning(
    diagnostics: tuple[ValidationIssue, ...],
    cleanup_warning: str | None,
) -> tuple[ValidationIssue, ...]:
    if not cleanup_warning:
        return diagnostics
    return diagnostics + (
        ValidationIssue(
            severity="warning",
            code="runtime_cleanup_warning",
            message=cleanup_warning,
        ),
    )
