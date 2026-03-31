from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

from .dynamic_wind import build_dynamic_wind_data, write_dynamic_wind_json
from .job_control import ConversionCancelledError, emit_telemetry, throw_if_cancelled
from .material_resolver import apply_material_policy as resolve_material_policy, resolve_prototype_materials
from .models import (
    CanonicalTreeModel,
    CleanupPolicy,
    ConversionRequest,
    ConversionResult,
    ConversionPhase,
    CpuProfile,
    DynamicWindData,
    DynamicWindSimulationGroup,
    MaterialPolicy,
    ObservedXmlSchemaReport,
    OutputMode,
    PrototypeSourceConfig,
    ValidationIssue,
    WindJsonResult,
)
from .normalizer import normalize_to_canonical
from .prototype_sources import (
    apply_prototype_source_configs,
    merge_legacy_part_mesh_configs,
    normalize_prototype_override_key as normalize_prototype_source_key,
)
from .usda_writer import render_usda, write_usda_document
from .validator import validate_model
from .runtime_paths import JobWorkspace, RuntimePaths, resolve_runtime_paths
from .xml_reader import inspect_xml, read_source_xml


REPO_ROOT = Path(__file__).resolve().parents[2]
VAULT_ROOT = REPO_ROOT / "vault"
BASELINE_BARK_MATERIAL_ID = 1
BASELINE_LEAVES_MATERIAL_ID = 2


def inspect_source(input_path: str) -> ObservedXmlSchemaReport:
    document = read_source_xml(input_path)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    return replace(
        report,
        base_geometry_mode=_base_geometry_mode(model),
        base_mesh_part_count=len(model.base_tree_parts),
        base_mesh_point_count=len(model.base_mesh.points) if model.base_mesh is not None else 0,
        base_mesh_face_count=len(model.base_mesh.face_vertex_counts) if model.base_mesh is not None else 0,
        base_material_distribution=_mesh_material_distribution(model.base_mesh),
        prototype_material_distribution=_prototype_material_distribution(model),
        prototype_structure=model.prototype_strategy.value,
        binding_mode=model.binding_mode,
        binding_element_size=model.binding_element_size,
        support_primvars=_support_primvars(model),
        orientation_sample=tuple(part.orientation.to_usda() for part in model.assembly_parts[:3]),
    )


def load_canonical_model(
    input_path: str,
    output_mode: OutputMode = OutputMode.SELF_CONTAINED,
    material_policy: MaterialPolicy = MaterialPolicy.LEGACY_ROLE_IDS,
    bark_material_path: str | None = None,
    leaves_material_path: str | None = None,
    single_material_path: str | None = None,
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
    prototype_source_configs: tuple[PrototypeSourceConfig, ...] = (),
    use_existing_part_meshes: bool = False,
    part_mesh_asset_paths: tuple[tuple[str, str], ...] = (),
    telemetry_callback=None,
    cancel_event=None,
) -> tuple[ObservedXmlSchemaReport, CanonicalTreeModel, tuple]:
    started_at = time.perf_counter()
    emit_telemetry(
        telemetry_callback,
        ConversionPhase.XML_NORMALIZATION,
        message="Reading and normalizing XML source.",
        started_at=started_at,
    )
    throw_if_cancelled(cancel_event)
    document = read_source_xml(input_path)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    source_configs = merge_legacy_part_mesh_configs(
        prototype_source_configs,
        use_existing_part_meshes,
        part_mesh_asset_paths,
    )
    model = apply_prototype_source_configs(
        model,
        source_configs,
        normalize_asset_path=_normalize_unreal_asset_path,
        is_valid_unreal_asset_path=_is_valid_unreal_asset_path,
        cpu_profile=cpu_profile,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
        started_at=started_at,
    )
    model = resolve_prototype_materials(
        model,
        cpu_profile=cpu_profile,
        cancel_event=cancel_event,
    )
    emit_telemetry(
        telemetry_callback,
        ConversionPhase.MATERIAL_RESOLUTION,
        message="Applying material policy.",
        started_at=started_at,
    )
    throw_if_cancelled(cancel_event)
    model = resolve_material_policy(
        model,
        material_policy=material_policy,
        bark_material_path=bark_material_path,
        leaves_material_path=leaves_material_path,
        single_material_path=single_material_path,
        normalize_asset_path=_normalize_unreal_asset_path,
    )
    model = replace(
        model,
        metadata=replace(model.metadata, output_mode=output_mode, material_policy=material_policy),
    )
    diagnostics = validate_model(model)
    return report, model, diagnostics


def convert_file(
    input_path: str,
    output_path: str | None,
    output_mode: OutputMode = OutputMode.SELF_CONTAINED,
    material_policy: MaterialPolicy = MaterialPolicy.LEGACY_ROLE_IDS,
    bark_material_path: str | None = None,
    leaves_material_path: str | None = None,
    single_material_path: str | None = None,
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
    cleanup_policy: CleanupPolicy = CleanupPolicy.EPHEMERAL,
    prototype_source_configs: tuple[PrototypeSourceConfig, ...] = (),
    use_existing_part_meshes: bool = False,
    part_mesh_asset_paths: tuple[tuple[str, str], ...] = (),
    telemetry_callback=None,
    cancel_event=None,
    runtime_paths: RuntimePaths | None = None,
) -> ConversionResult:
    request = ConversionRequest(
        input_paths=(input_path,),
        output_path=output_path,
        output_mode=output_mode,
        material_policy=material_policy,
        bark_material_path=bark_material_path,
        leaves_material_path=leaves_material_path,
        single_material_path=single_material_path,
        cpu_profile=cpu_profile,
        cleanup_policy=cleanup_policy,
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
    if not request.input_paths:
        raise ValueError("ConversionRequest requires at least one input path.")
    if request.output_path and len(request.input_paths) != 1:
        raise ValueError("Explicit output_path is only valid for single-file conversion.")
    if request.part_mesh_asset_paths and not request.use_existing_part_meshes and not request.prototype_source_configs:
        raise ValueError("part_mesh_asset_paths require use_existing_part_meshes=True.")
    _validate_material_request(request)

    results: list[ConversionResult] = []
    resolved_runtime_paths = runtime_paths or resolve_runtime_paths()
    for input_path in request.input_paths:
        throw_if_cancelled(cancel_event)
        resolved_output = _resolve_output_path(request, input_path)
        if resolved_output is not None:
            _ensure_output_path_allowed(resolved_output)

        job_workspace = JobWorkspace.create(
            resolved_runtime_paths,
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
                cpu_profile=request.cpu_profile,
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
                results.append(
                    ConversionResult(
                        input_path=input_path,
                        output_path=str(resolved_output) if resolved_output is not None else None,
                        diagnostics=diagnostics,
                        usda_document=None,
                        telemetry=(),
                        runtime_job_dir=str(job_workspace.job_dir) if job_workspace.debug_preserve else None,
                    )
                )
                continue

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
            results.append(
                ConversionResult(
                    input_path=input_path,
                    output_path=str(resolved_output) if resolved_output is not None else None,
                    diagnostics=diagnostics,
                    usda_document=None,
                    telemetry=(),
                    runtime_job_dir=str(job_workspace.job_dir) if job_workspace.debug_preserve else None,
                )
            )
            continue
        except Exception as exc:
            cleanup_warning = job_workspace.finalize(status="failed", error_message=str(exc))
            if cleanup_warning:
                raise RuntimeError(f"{exc}\nRuntime cleanup warning: {cleanup_warning}") from exc
            raise

        diagnostics = _append_cleanup_warning(diagnostics, job_workspace.finalize(status="succeeded"))
        results.append(
            ConversionResult(
                input_path=input_path,
                output_path=str(resolved_output) if resolved_output is not None else None,
                diagnostics=diagnostics,
                usda_document=usda_document,
                telemetry=(),
                runtime_job_dir=str(job_workspace.job_dir) if job_workspace.debug_preserve else None,
            )
        )
    return tuple(results)


def inspect_wind_data(input_path: str, is_ground_cover: bool = False) -> DynamicWindData:
    document = read_source_xml(input_path)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    return build_dynamic_wind_data(
        model.skeleton,
        is_ground_cover=is_ground_cover,
    )


def generate_wind_json(
    input_path: str,
    output_path: str,
    group_settings: tuple[DynamicWindSimulationGroup, ...] = (),
    gust_attenuation: float = 0.0,
    is_ground_cover: bool = False,
) -> WindJsonResult:
    document = read_source_xml(input_path)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    dynamic_wind = build_dynamic_wind_data(
        model.skeleton,
        source_objects=model.source_objects,
        group_settings=group_settings,
        gust_attenuation=gust_attenuation,
        is_ground_cover=is_ground_cover,
    )
    if not dynamic_wind.joint_assignments:
        raise ValueError("missing_skeleton: wind JSON generation requires a normalized skeleton.")
    resolved_output = write_dynamic_wind_json(dynamic_wind, output_path)
    return WindJsonResult(
        input_path=input_path,
        output_path=str(resolved_output),
        dynamic_wind=dynamic_wind,
    )


def _resolve_output_path(request: ConversionRequest, input_path: str) -> Path | None:
    if request.output_path:
        return Path(request.output_path)

    if request.output_directory:
        output_dir = Path(request.output_directory)
        file_name = _render_output_file_name(Path(input_path), request.output_naming_template)
        return output_dir / file_name

    if len(request.input_paths) == 1:
        input_file = Path(input_path)
        return input_file.with_suffix(".usda")

    raise ValueError("Batch conversion requires output_directory or explicit per-file naming.")


def _render_output_file_name(input_path: Path, naming_template: str | None) -> str:
    stem = input_path.stem
    if naming_template:
        file_name = naming_template.format(stem=stem)
        if not file_name.lower().endswith(".usda"):
            file_name = f"{file_name}.usda"
        return file_name
    return f"{stem}.usda"


def _ensure_output_path_allowed(output_path: Path) -> None:
    if not VAULT_ROOT.exists():
        return
    resolved_output = output_path.resolve()
    resolved_vault = VAULT_ROOT.resolve()
    if resolved_output.is_relative_to(resolved_vault):
        raise ValueError(f"Generated outputs must not be written inside the immutable vault: {resolved_output}")


def _base_geometry_mode(model: CanonicalTreeModel) -> str:
    if not model.base_tree_parts:
        return "missing"
    return "merged" if len(model.base_tree_parts) > 1 else "single_object"


def _support_primvars(model: CanonicalTreeModel) -> tuple[str, ...]:
    if model.skeletal_support_primvars is None:
        return ()
    return ("boneCapture_pCaptPath", "ueJointNames", "hierarchicalDepth", "logicalDepth", "localtransform")


def _mesh_material_distribution(mesh) -> dict[str, int]:
    if mesh is None:
        return {}
    return {str(section.material_id): len(section.face_indices) for section in mesh.sections}


def _prototype_material_distribution(model: CanonicalTreeModel) -> dict[str, int]:
    distribution: dict[str, int] = {}
    for prototype in model.prototypes:
        section_source = prototype.geometry_payload.sections if prototype.geometry_payload is not None else (
            prototype.mesh.sections if prototype.mesh is not None else ()
        )
        for section in section_source:
            key = str(section.material_id)
            distribution[key] = distribution.get(key, 0) + len(section.face_indices)
    return dict(sorted(distribution.items(), key=lambda item: int(item[0]) if item[0].lstrip("-").isdigit() else item[0]))


def _apply_material_policy(
    model: CanonicalTreeModel,
    material_policy: MaterialPolicy,
    bark_material_path: str | None,
    leaves_material_path: str | None,
    single_material_path: str | None,
) -> CanonicalTreeModel:
    return resolve_material_policy(
        model,
        material_policy=material_policy,
        bark_material_path=bark_material_path,
        leaves_material_path=leaves_material_path,
        single_material_path=single_material_path,
        normalize_asset_path=_normalize_unreal_asset_path,
    )


def _validate_material_request(request: ConversionRequest) -> None:
    checks: list[tuple[str, str | None]]
    if request.material_policy == MaterialPolicy.SINGLE_MATERIAL:
        checks = [("Single", request.single_material_path)]
    else:
        checks = [
            ("Bark", request.bark_material_path),
            ("Leaves", request.leaves_material_path),
        ]
    for label, path in checks:
        if not path:
            continue
        normalized = _normalize_unreal_asset_path(path)
        if not _is_valid_unreal_asset_path(normalized):
            raise ValueError(f"{label} material path must start with /Game/.")


def _normalize_prototype_override_key(raw_key: str) -> str:
    return normalize_prototype_source_key(raw_key)


def _is_valid_unreal_asset_path(path: str) -> bool:
    return path.startswith("/Game/")


def _normalize_unreal_asset_path(path: str) -> str:
    normalized = path.strip()
    if not normalized.startswith("/Game/"):
        return normalized
    package_path = normalized.rsplit("/", 1)[-1]
    if "." in package_path:
        return normalized
    return f"{normalized}.{package_path}"


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
