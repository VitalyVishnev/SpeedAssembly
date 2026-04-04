from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

from .dynamic_wind import build_dynamic_wind_data, write_dynamic_wind_json
from .job_control import ConversionCancelledError, emit_telemetry, throw_if_cancelled
from .material_resolver import apply_material_policy as resolve_material_policy, resolve_prototype_materials
from .models import (
    BaseMaterialOverride,
    CanonicalTreeModel,
    CleanupPolicy,
    ConversionRequest,
    ConversionResult,
    ConversionPhase,
    CpuProfile,
    DynamicWindData,
    DynamicWindSimulationGroup,
    Joint,
    MaterialPolicy,
    ObservedXmlSchemaReport,
    OutputMode,
    PrototypeSourceConfig,
    PrototypeDiscoveryEntry,
    ValidationIssue,
    WindJsonResult,
)
from .normalizer import normalize_to_canonical
from .normalizer import _joint_name_from_bone_id, _parse_generator_label
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


def discover_part_prototypes(input_path: str) -> tuple[PrototypeDiscoveryEntry, ...]:
    mesh_names_by_id: dict[int, str] = {}
    mesh_instance_counts_by_id: dict[int, int] = {}
    ordered_mesh_ids: list[int] = []
    seen_mesh_ids: set[int] = set()
    saw_leaf_references = False
    leaf_without_mesh_id_instance_count = 0

    for _event, elem in ET.iterparse(input_path, events=("end",)):
        if elem.tag == "Mesh":
            raw_mesh_id = elem.attrib.get("ID")
            if raw_mesh_id is not None and raw_mesh_id.isdigit():
                mesh_id = int(raw_mesh_id)
                mesh_names_by_id[mesh_id] = elem.attrib.get("Name", f"Mesh_{mesh_id}")
            elem.clear()
            continue
        if elem.tag != "LeafReferences":
            continue

        saw_leaf_references = True
        mesh_ids = _read_streamed_mesh_ids(elem.findtext("MeshID"))
        instance_count = _read_leaf_reference_instance_count(elem)
        if mesh_ids:
            mesh_count_deltas = _mesh_instance_count_deltas(mesh_ids, instance_count)
            for mesh_id in mesh_ids:
                if mesh_id in seen_mesh_ids:
                    continue
                seen_mesh_ids.add(mesh_id)
                ordered_mesh_ids.append(mesh_id)
                mesh_instance_counts_by_id.setdefault(mesh_id, 0)
            for mesh_id, count_delta in mesh_count_deltas.items():
                mesh_instance_counts_by_id[mesh_id] = mesh_instance_counts_by_id.get(mesh_id, 0) + count_delta
        elif _leaf_reference_has_instances(elem):
            leaf_without_mesh_id_instance_count += max(instance_count, 1)
        elem.clear()

    prototypes = tuple(
        PrototypeDiscoveryEntry(
            source_key=f"Mesh_{mesh_id}",
            source_mesh_id=mesh_id,
            source_name=mesh_names_by_id.get(mesh_id, f"Mesh_{mesh_id}"),
            instance_count=mesh_instance_counts_by_id.get(mesh_id, 0),
        )
        for mesh_id in ordered_mesh_ids
    )
    if prototypes or not saw_leaf_references or not leaf_without_mesh_id_instance_count:
        return prototypes
    return (
        PrototypeDiscoveryEntry(
            source_key="LeafPrototype",
            source_mesh_id=None,
            source_name="LeafPrototype",
            instance_count=leaf_without_mesh_id_instance_count,
        ),
    )


def discover_source_materials(input_path: str) -> tuple[BaseMaterialOverride, ...]:
    material_names_by_id: dict[int, str] = {}
    material_id_order: list[int] = []
    used_base_material_ids: set[int] = set()
    element_stack: list[str] = []

    for event, elem in ET.iterparse(input_path, events=("start", "end")):
        if event == "start":
            element_stack.append(elem.tag)
            continue

        if elem.tag == "Material":
            raw_source_id = elem.attrib.get("ID")
            if raw_source_id is not None and raw_source_id.lstrip("-").isdigit():
                source_id = int(raw_source_id)
                if source_id not in material_names_by_id:
                    material_id_order.append(source_id)
                material_names_by_id[source_id] = elem.attrib.get("Name", f"Material_{source_id}")
        elif elem.tag == "Triangles":
            raw_source_id = elem.attrib.get("Material")
            if (
                raw_source_id is not None
                and raw_source_id.lstrip("-").isdigit()
                and "Object" in element_stack
                and "Mesh" not in element_stack
            ):
                used_base_material_ids.add(int(raw_source_id))

        if element_stack:
            element_stack.pop()
        elem.clear()

    return tuple(
        BaseMaterialOverride(
            source_id=source_id,
            source_name=material_names_by_id.get(source_id, f"Material_{source_id}"),
        )
        for source_id in material_id_order
        if source_id in used_base_material_ids
    )


def load_canonical_model(
    input_path: str,
    output_mode: OutputMode = OutputMode.SELF_CONTAINED,
    material_policy: MaterialPolicy = MaterialPolicy.SOURCE_MATERIAL_ROLES,
    bark_material_path: str | None = None,
    leaves_material_path: str | None = None,
    single_material_path: str | None = None,
    base_material_overrides: tuple[BaseMaterialOverride, ...] = (),
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
    use_explicit_material_contract: bool = False,
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
    emit_telemetry(
        telemetry_callback,
        ConversionPhase.MATERIAL_RESOLUTION,
        message="Applying material policy.",
        started_at=started_at,
    )
    throw_if_cancelled(cancel_event)
    if use_explicit_material_contract:
        model = resolve_material_policy(
            model,
            material_policy=material_policy,
            bark_material_path=bark_material_path,
            leaves_material_path=leaves_material_path,
            single_material_path=single_material_path,
            normalize_asset_path=_normalize_unreal_asset_path,
            base_material_overrides=base_material_overrides,
            explicit_part_material_contract=True,
            cpu_profile=cpu_profile,
            cancel_event=cancel_event,
        )
    else:
        model = resolve_prototype_materials(
            model,
            cpu_profile=cpu_profile,
            cancel_event=cancel_event,
        )
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
    skeleton = _load_wind_skeleton(input_path)
    return build_dynamic_wind_data(
        skeleton,
        is_ground_cover=is_ground_cover,
    )


def generate_wind_json(
    input_path: str,
    output_path: str,
    group_settings: tuple[DynamicWindSimulationGroup, ...] = (),
    gust_attenuation: float = 0.0,
    is_ground_cover: bool = False,
) -> WindJsonResult:
    skeleton = _load_wind_skeleton(input_path)
    dynamic_wind = build_dynamic_wind_data(
        skeleton,
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


def _load_wind_skeleton(input_path: str) -> tuple[Joint, ...]:
    joints: list[Joint] = []
    for _event, elem in ET.iterparse(input_path, events=("end",)):
        if elem.tag != "Bone":
            continue
        raw_bone_id = elem.attrib.get("ID")
        if raw_bone_id is None or not raw_bone_id.lstrip("-").isdigit():
            elem.clear()
            continue
        bone_id = int(raw_bone_id)
        raw_parent_id = elem.attrib.get("ParentID")
        parsed_parent_id = None
        if raw_parent_id not in {None, "", "-1"} and raw_parent_id.lstrip("-").isdigit():
            parsed_parent_id = int(raw_parent_id)
        generator_label, generator_level = _parse_generator_label(elem.attrib.get("Generator"), bone_id)
        joints.append(
            Joint(
                name=_joint_name_from_bone_id(bone_id),
                source_id=bone_id,
                parent=_joint_name_from_bone_id(parsed_parent_id) if parsed_parent_id is not None else None,
                generator_label=generator_label,
                generator_level=generator_level,
            )
        )
        elem.clear()
    return tuple(joints)


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


def _read_streamed_mesh_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    mesh_ids: list[int] = []
    for token in raw.replace(",", " ").split():
        if token.lstrip("-").isdigit():
            mesh_ids.append(int(token))
    return mesh_ids


def _leaf_reference_has_instances(elem: ET.Element) -> bool:
    for tag_name in ("MeshID", "X", "Y", "Z"):
        text = elem.findtext(tag_name)
        if text and text.strip():
            return True
    return False


def _read_leaf_reference_instance_count(elem: ET.Element) -> int:
    raw_count = (elem.attrib.get("Count") or "").strip()
    if raw_count.isdigit():
        parsed = int(raw_count)
        if parsed > 0:
            return parsed
    return max(
        _count_streamed_value_tokens(elem.findtext(tag_name))
        for tag_name in ("MeshID", "X", "Y", "Z", "Scale", "BoneID")
    )


def _count_streamed_value_tokens(raw: str | None) -> int:
    if raw is None:
        return 0
    text = raw.strip()
    if not text:
        return 0
    return len(text.split())


def _mesh_instance_count_deltas(mesh_ids: list[int], instance_count: int) -> dict[int, int]:
    if not mesh_ids:
        return {}
    if len(mesh_ids) == 1 and instance_count > 1:
        return {mesh_ids[0]: instance_count}
    counts: dict[int, int] = {}
    for mesh_id in mesh_ids:
        counts[mesh_id] = counts.get(mesh_id, 0) + 1
    return counts
