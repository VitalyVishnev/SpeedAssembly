from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .dynamic_wind import build_dynamic_wind_data, write_dynamic_wind_json
from .models import (
    CanonicalTreeModel,
    ConversionRequest,
    ConversionResult,
    DynamicWindData,
    DynamicWindSimulationGroup,
    MaterialSpec,
    ObservedXmlSchemaReport,
    OutputMode,
    Prototype,
    PrototypeResolutionMode,
    WindJsonResult,
)
from .normalizer import normalize_to_canonical
from .usda_writer import render_usda
from .validator import validate_model
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
    bark_material_path: str | None = None,
    leaves_material_path: str | None = None,
    use_existing_part_meshes: bool = False,
    part_mesh_asset_paths: tuple[tuple[str, str], ...] = (),
) -> tuple[ObservedXmlSchemaReport, CanonicalTreeModel, tuple]:
    document = read_source_xml(input_path)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    model = _apply_material_role_overrides(model, bark_material_path, leaves_material_path)
    model = _apply_external_part_mesh_overrides(model, use_existing_part_meshes, part_mesh_asset_paths)
    metadata = replace(model.metadata, output_mode=output_mode)
    model = replace(model, metadata=metadata)
    diagnostics = validate_model(model)
    return report, model, diagnostics


def convert_file(
    input_path: str,
    output_path: str | None,
    output_mode: OutputMode = OutputMode.SELF_CONTAINED,
    bark_material_path: str | None = None,
    leaves_material_path: str | None = None,
    use_existing_part_meshes: bool = False,
    part_mesh_asset_paths: tuple[tuple[str, str], ...] = (),
) -> ConversionResult:
    request = ConversionRequest(
        input_paths=(input_path,),
        output_path=output_path,
        output_mode=output_mode,
        bark_material_path=bark_material_path,
        leaves_material_path=leaves_material_path,
        use_existing_part_meshes=use_existing_part_meshes,
        part_mesh_asset_paths=part_mesh_asset_paths,
    )
    return convert_request(request)[0]


def convert_request(request: ConversionRequest) -> tuple[ConversionResult, ...]:
    if not request.input_paths:
        raise ValueError("ConversionRequest requires at least one input path.")
    if request.output_path and len(request.input_paths) != 1:
        raise ValueError("Explicit output_path is only valid for single-file conversion.")
    if request.part_mesh_asset_paths and not request.use_existing_part_meshes:
        raise ValueError("part_mesh_asset_paths require use_existing_part_meshes=True.")

    results: list[ConversionResult] = []
    for input_path in request.input_paths:
        resolved_output = _resolve_output_path(request, input_path)
        if resolved_output is not None:
            _ensure_output_path_allowed(resolved_output)

        _, model, diagnostics = load_canonical_model(
            input_path,
            request.output_mode,
            bark_material_path=request.bark_material_path,
            leaves_material_path=request.leaves_material_path,
            use_existing_part_meshes=request.use_existing_part_meshes,
            part_mesh_asset_paths=request.part_mesh_asset_paths,
        )
        errors = [issue for issue in diagnostics if issue.severity == "error"]
        if errors:
            results.append(
                ConversionResult(
                    input_path=input_path,
                    output_path=str(resolved_output) if resolved_output is not None else None,
                    diagnostics=diagnostics,
                    usda_document=None,
                )
            )
            continue

        usda_document = render_usda(model, diagnostics)
        if resolved_output is not None:
            resolved_output.parent.mkdir(parents=True, exist_ok=True)
            resolved_output.write_text(usda_document.text, encoding="utf-8")

        results.append(
            ConversionResult(
                input_path=input_path,
                output_path=str(resolved_output) if resolved_output is not None else None,
                diagnostics=diagnostics,
                usda_document=usda_document,
            )
        )
    return tuple(results)


def inspect_wind_data(input_path: str) -> DynamicWindData:
    document = read_source_xml(input_path)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    if model.dynamic_wind is None:
        return build_dynamic_wind_data(model.skeleton, source_objects=model.source_objects)
    return model.dynamic_wind


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
        if prototype.mesh is None:
            continue
        for section in prototype.mesh.sections:
            key = str(section.material_id)
            distribution[key] = distribution.get(key, 0) + len(section.face_indices)
    return dict(sorted(distribution.items(), key=lambda item: int(item[0]) if item[0].lstrip("-").isdigit() else item[0]))


def _apply_material_role_overrides(
    model: CanonicalTreeModel,
    bark_material_path: str | None,
    leaves_material_path: str | None,
) -> CanonicalTreeModel:
    if not bark_material_path and not leaves_material_path:
        return model

    overrides = {
        BASELINE_BARK_MATERIAL_ID: bark_material_path,
        BASELINE_LEAVES_MATERIAL_ID: leaves_material_path,
    }
    materials = tuple(_apply_material_override(material, overrides) for material in model.materials)
    return replace(model, materials=materials)


def _apply_material_override(material: MaterialSpec, overrides: dict[int, str | None]) -> MaterialSpec:
    ue_asset_path = overrides.get(material.source_id)
    if not ue_asset_path:
        return material
    return replace(material, ue_asset_path=_normalize_unreal_asset_path(ue_asset_path))


def _apply_external_part_mesh_overrides(
    model: CanonicalTreeModel,
    use_existing_part_meshes: bool,
    part_mesh_asset_paths: tuple[tuple[str, str], ...],
) -> CanonicalTreeModel:
    if not use_existing_part_meshes:
        return model

    overrides = _normalize_part_mesh_asset_paths(part_mesh_asset_paths)
    if not overrides:
        return model

    unused_keys = sorted(set(overrides) - {prototype.source_key for prototype in model.prototypes})
    metadata = model.metadata
    if unused_keys:
        metadata = replace(
            metadata,
            warnings=metadata.warnings + tuple(
                f"Unused existing PartMesh override ignored: {source_key}" for source_key in unused_keys
            ),
        )

    prototypes = tuple(_apply_external_part_mesh_override(prototype, overrides) for prototype in model.prototypes)
    return replace(model, prototypes=prototypes, metadata=metadata)


def _apply_external_part_mesh_override(
    prototype: Prototype,
    overrides: dict[str, str],
) -> Prototype:
    mesh_asset_path = overrides.get(prototype.source_key)
    if mesh_asset_path is None:
        return prototype
    return replace(
        prototype,
        resolution_mode=PrototypeResolutionMode.EXTERNAL_ASSET,
        mesh_asset_path=mesh_asset_path,
    )


def _normalize_part_mesh_asset_paths(
    part_mesh_asset_paths: tuple[tuple[str, str], ...],
) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for raw_key, raw_asset_path in part_mesh_asset_paths:
        source_key = _normalize_prototype_override_key(raw_key)
        if not source_key:
            raise ValueError("PartMesh override keys must not be empty.")
        asset_path = _normalize_unreal_asset_path(raw_asset_path)
        if not _is_valid_unreal_asset_path(asset_path):
            raise ValueError(f"PartMesh asset path for {source_key} must start with /Game/.")
        existing = overrides.get(source_key)
        if existing is not None and existing != asset_path:
            raise ValueError(f"Duplicate PartMesh override for {source_key} uses conflicting asset paths.")
        overrides[source_key] = asset_path
    return overrides


def _normalize_prototype_override_key(raw_key: str) -> str:
    key = raw_key.strip()
    if not key:
        return ""
    lower_key = key.lower()
    for prefix in ("mesh_", "meshid:", "mesh_id:"):
        if lower_key.startswith(prefix) and key[len(prefix):].strip().isdigit():
            return f"Mesh_{int(key[len(prefix):].strip())}"
    if key.isdigit():
        return f"Mesh_{int(key)}"
    return key


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
