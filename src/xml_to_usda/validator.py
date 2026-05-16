from __future__ import annotations

from .asset_paths import is_valid_unreal_asset_path
from .geometry_buffers import payload_face_count, payload_has_face_topology, payload_point_count, payload_sections
from .models import (
    CanonicalTreeModel,
    ConversionMode,
    PrototypeResolutionMode,
    PrototypeSourceMode,
    PrototypeStrategy,
    ResolvedAssemblyModel,
    ValidationIssue,
)


ERROR_MARKERS = {
    "packed_array_error:": "inconsistent_packed_arrays",
    "invalid_material_id:": "invalid_material_id",
    "missing_material_definition:": "missing_material_definition",
    "material_conflict:": "material_conflict",
    "missing_object_hierarchy:": "missing_object_hierarchy",
    "missing_leaf_binding:": "missing_leaf_binding",
    "missing_skeleton_transform:": "missing_skeleton_transform",
    "skeleton_object_mismatch:": "skeleton_object_mismatch",
    "material_policy_warning:": "material_policy_warning",
}
WARNING_MARKER_CODES = {"material_conflict", "material_policy_warning", "skeleton_object_mismatch"}
SUPPORTED_AUTHORING_MODES = {
    ConversionMode.SKELETAL_ASSEMBLY,
    ConversionMode.SKELETAL_PARTS,
    ConversionMode.STATIC_ASSEMBLY,
}


def validate_model(
    model: CanonicalTreeModel,
    conversion_mode: ConversionMode | str | None = None,
) -> tuple[ValidationIssue, ...]:
    """Compatibility wrapper for callers that still validate one final model."""
    return validate_source_model(model) + validate_authoring_model(model, conversion_mode=conversion_mode)


def validate_source_model(model: CanonicalTreeModel) -> tuple[ValidationIssue, ...]:
    """Validate source facts produced by XML normalization before operator intent."""
    issues: list[ValidationIssue] = []

    if not model.source_objects:
        issues.append(
            ValidationIssue(
                severity="error",
                code="missing_object_hierarchy",
                message="Object hierarchy data is required for assembly normalization.",
            )
        )

    for section in model.metadata.unknown_sections:
        issues.append(
            ValidationIssue(
                severity="warning",
                code="unknown_xml_section",
                message=f"Unknown XML section detected during inspection: {section}",
            )
        )

    issues.extend(_metadata_warning_issues(model.metadata.warnings))
    return tuple(issues)


def validate_resolution(resolved: ResolvedAssemblyModel) -> tuple[ValidationIssue, ...]:
    """Validate source facts after operator intent has been applied."""
    issues: list[ValidationIssue] = []
    source_warnings = set(resolved.source_model.metadata.warnings)
    resolution_warnings = tuple(
        warning for warning in resolved.authoring_model.metadata.warnings if warning not in source_warnings
    )
    issues.extend(_metadata_warning_issues(resolution_warnings))

    for prototype in resolved.authoring_model.prototypes:
        if prototype.resolution_mode == PrototypeResolutionMode.EXTERNAL_ASSET:
            if not prototype.mesh_asset_path:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="missing_prototype_asset_path",
                        message=(
                            f"Resolved Prototype {prototype.identity.prim_name} is marked as external "
                            "but has no Unreal asset path."
                        ),
                    )
                )
                continue
            if not is_valid_unreal_asset_path(prototype.mesh_asset_path):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="invalid_prototype_asset_path",
                        message=(
                            f"Resolved Prototype {prototype.identity.prim_name} uses invalid Unreal asset path "
                            f"{prototype.mesh_asset_path!r}; expected a /Game/... asset reference."
                        ),
                    )
                )
        if prototype.source_mode == PrototypeSourceMode.FBX_FILE and not prototype.fbx_source_path:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="missing_fbx_source_path",
                    message=(
                        f"Resolved Prototype {prototype.identity.prim_name} uses FBX source mode "
                        "but has no source FBX path."
                    ),
                )
            )

    return tuple(issues)


def validate_authoring_model(
    model: CanonicalTreeModel,
    conversion_mode: ConversionMode | str | None = None,
) -> tuple[ValidationIssue, ...]:
    """Validate the USDA authoring contract for the selected export mode."""
    issues: list[ValidationIssue] = []
    mode = _resolve_conversion_mode(model, conversion_mode)
    material_ids = {material.source_id for material in model.materials}

    if mode not in SUPPORTED_AUTHORING_MODES:
        issues.append(
            ValidationIssue(
                severity="error",
                code="unsupported_conversion_mode",
                message=f"Unsupported conversion mode: {mode.value}.",
            )
        )
        return tuple(issues)

    if mode == ConversionMode.STATIC_ASSEMBLY:
        issues.extend(_validate_static_assembly_model(model, material_ids))
    elif mode == ConversionMode.SKELETAL_PARTS:
        issues.extend(_validate_skeletal_parts_model(model, material_ids))
    else:
        issues.extend(_validate_skeletal_assembly_model(model, material_ids))

    if (
        mode in {ConversionMode.SKELETAL_ASSEMBLY, ConversionMode.SKELETAL_PARTS}
        and model.branch_segments
        and model.skeleton
        and not any(segment.source_joint for segment in model.branch_segments)
    ):
        issues.append(
            ValidationIssue(
                severity="warning",
                code="skeleton_object_mismatch",
                message="Branch segments were extracted, but none could be associated with a skeleton joint directly.",
            )
        )

    return tuple(issues)


def _metadata_warning_issues(warnings: tuple[str, ...]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for warning in warnings:
        matched_code = None
        for marker, code in ERROR_MARKERS.items():
            if warning.startswith(marker):
                matched_code = code
                issues.append(
                    ValidationIssue(
                        severity="warning" if code in WARNING_MARKER_CODES else "error",
                        code=code,
                        message=warning.split(": ", 1)[1] if ": " in warning else warning,
                    )
                )
                break
        if matched_code is None:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="metadata_warning",
                    message=warning,
                )
            )

    return issues


def _validate_skeletal_assembly_model(
    model: CanonicalTreeModel,
    material_ids: set[int],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if model.base_mesh is None:
        issues.append(
            ValidationIssue(
                severity="error",
                code="missing_base_tree_mesh",
                message="Tree asset requires Base Skeletal Tree geometry for skeletal assembly import.",
            )
        )
    elif not model.base_mesh.skel_joint_indices or not model.base_mesh.skel_joint_weights:
        issues.append(
            ValidationIssue(
                severity="error",
                code="missing_base_mesh_skinning",
                message="Base skeletal mesh requires explicit skel joint indices and weights derived from XML vertex bindings.",
            )
        )
    else:
        if model.base_mesh.skel_element_size <= 0:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="invalid_base_mesh_skinning_shape",
                    message="Base skeletal mesh skel elementSize must be greater than zero when skinning arrays are present.",
                )
            )
        issues.extend(_validate_mesh_materials(model.base_mesh, material_ids, "Base Skeletal Tree"))

    if model.materials and model.base_mesh is not None:
        if len(model.base_mesh.skel_joint_indices) != len(model.base_mesh.points):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="invalid_base_mesh_skinning_shape",
                    message="Base skeletal mesh joint index payload must match the authored point count for vertex interpolation.",
                )
            )
        if len(model.base_mesh.skel_joint_weights) != len(model.base_mesh.points):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="invalid_base_mesh_skinning_shape",
                    message="Base skeletal mesh joint weight payload must match the authored point count for vertex interpolation.",
                )
            )

    if not model.skeleton:
        issues.append(
            ValidationIssue(
                severity="error",
                code="missing_skeleton",
                message="Skeleton data is required for skeletal nanite assembly export.",
            )
        )
    elif model.base_mesh is not None and model.base_mesh.skel_joint_indices:
        skeleton_size = len(model.skeleton)
        out_of_range = [
            index for index in model.base_mesh.skel_joint_indices if index < 0 or index >= skeleton_size
        ]
        if out_of_range:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="invalid_base_mesh_joint_index",
                    message=(
                        "Base skeletal mesh contains joint indices outside the authored skeleton range; "
                        f"found {len(out_of_range)} invalid entries for {skeleton_size} joints."
                    ),
                )
            )

    if not model.assembly_parts:
        issues.append(
            ValidationIssue(
                severity="warning",
                code="missing_leaf_references",
                message="No LeafReferences / Assembly Parts found; converter will emit a base-only USDA.",
            )
        )

    if model.assembly_parts and any(not part.binding.joint_tokens for part in model.assembly_parts):
        issues.append(
            ValidationIssue(
                severity="error",
                code="missing_leaf_binding",
                message="Assembly Part instances must carry explicit skeletal binding data derived from the XML export.",
            )
        )
    if model.assembly_parts and model.prototype_strategy != PrototypeStrategy.INLINE_SKELETAL_PART:
        issues.append(
            ValidationIssue(
                severity="error",
                code="unsupported_prototype_strategy",
                message="Skeletal Assembly Part instancing requires inline skeletal part prototypes under PointInstancer/Prototypes.",
            )
        )
    skeleton_joint_tokens = _valid_binding_joint_tokens(model)
    if model.assembly_parts:
        prototypes_by_key = {prototype.source_key: prototype for prototype in model.prototypes}
        for part in model.assembly_parts:
            prototype = prototypes_by_key.get(part.prototype_key)
            if prototype is None:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="missing_prototype_mesh",
                        message=f"Assembly Part instance {part.name} references missing prototype {part.prototype_key}.",
                    )
                )
                continue
            invalid_tokens = [token for token in part.binding.joint_tokens if token and token not in skeleton_joint_tokens]
            if invalid_tokens:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="invalid_binding_joint",
                        message=(
                            f"Assembly Part instance {part.name} references skeletal joints that do not exist in the authored skeleton: "
                            + ", ".join(invalid_tokens)
                        ),
                    )
                )
                continue
            if prototype.resolution_mode == PrototypeResolutionMode.EXTERNAL_ASSET:
                if not prototype.mesh_asset_path:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="missing_prototype_asset_path",
                            message=f"Prototype {prototype.identity.prim_name} is marked as external but has no Unreal asset path.",
                        )
                    )
                    continue
                if not is_valid_unreal_asset_path(prototype.mesh_asset_path):
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="invalid_prototype_asset_path",
                            message=(
                                f"Prototype {prototype.identity.prim_name} uses invalid Unreal asset path "
                                f"{prototype.mesh_asset_path!r}; expected a /Game/... asset reference."
                            ),
                        )
                    )
                continue
            if prototype.mesh is None:
                if prototype.geometry_payload is None:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="missing_prototype_mesh",
                            message=f"Prototype {prototype.identity.prim_name} has no resolved mesh payload.",
                        )
                    )
                    continue
            if not payload_has_face_topology(prototype.mesh, prototype.geometry_payload):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="invalid_prototype_mesh",
                        message=(
                            f"Prototype {prototype.identity.prim_name} must contain point and face topology payloads "
                            "before prototype authoring."
                        ),
                    )
                )
                continue
            if (
                payload_point_count(prototype.mesh, prototype.geometry_payload) <= 0
                or payload_face_count(prototype.mesh, prototype.geometry_payload) <= 0
            ):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="invalid_prototype_mesh",
                        message=(
                            f"Prototype {prototype.identity.prim_name} must contain point and face topology payloads "
                            "before prototype authoring."
                        ),
                    )
                )

    for part in model.assembly_parts:
        if len(part.binding.joint_tokens) != len(part.binding.weights):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="invalid_binding_shape",
                    message=f"Assembly Part instance {part.name} has mismatched joint and weight counts.",
                )
            )
        if part.binding.weights and abs(sum(part.binding.weights) - 1.0) > 1e-4:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="non_normalized_binding_weights",
                    message=f"Assembly Part instance {part.name} binding weights sum to {sum(part.binding.weights):g} instead of 1.",
                )
            )

    return issues


def _validate_skeletal_parts_model(
    model: CanonicalTreeModel,
    material_ids: set[int],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if not model.prototypes:
        issues.append(
            ValidationIssue(
                severity="error",
                code="missing_prototypes",
                message="Skeletal parts export requires at least one valid prototype payload.",
            )
        )
        return issues

    issues.extend(_validate_prototypes(model.prototypes, material_ids))
    return issues


def _validate_static_assembly_model(
    model: CanonicalTreeModel,
    material_ids: set[int],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if model.base_mesh is None and not model.assembly_parts:
        issues.append(
            ValidationIssue(
                severity="error",
                code="missing_static_instances",
                message="Static assembly export requires a base mesh or at least one placed instance.",
            )
        )
    if model.base_mesh is None and not model.prototypes:
        issues.append(
            ValidationIssue(
                severity="error",
                code="missing_prototypes",
                message="Static assembly export requires at least one prototype payload or a base mesh.",
            )
        )
    if model.base_mesh is not None:
        if not payload_has_face_topology(model.base_mesh, None):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="invalid_base_mesh",
                    message="Static assembly base mesh must contain point and face topology payloads.",
                )
            )
        if payload_point_count(model.base_mesh, None) <= 0 or payload_face_count(model.base_mesh, None) <= 0:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="invalid_base_mesh",
                    message="Static assembly base mesh must contain point and face topology payloads.",
                )
            )
        issues.extend(_validate_mesh_materials(model.base_mesh, material_ids, "Static Assembly Base Mesh"))

    issues.extend(_validate_prototypes(model.prototypes, material_ids))

    prototypes_by_key = {prototype.source_key: prototype for prototype in model.prototypes}
    for part in model.assembly_parts:
        if part.prototype_key not in prototypes_by_key:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="missing_prototype_mesh",
                    message=f"Static assembly instance {part.name} references missing prototype {part.prototype_key}.",
                )
            )

    return issues


def _validate_prototypes(
    prototypes,
    material_ids: set[int],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for prototype in prototypes:
        if prototype.resolution_mode == PrototypeResolutionMode.EXTERNAL_ASSET:
            if not prototype.mesh_asset_path:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="missing_prototype_asset_path",
                        message=f"Prototype {prototype.identity.prim_name} is marked as external but has no Unreal asset path.",
                    )
                )
                continue
            if not is_valid_unreal_asset_path(prototype.mesh_asset_path):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="invalid_prototype_asset_path",
                        message=(
                            f"Prototype {prototype.identity.prim_name} uses invalid Unreal asset path "
                            f"{prototype.mesh_asset_path!r}; expected a /Game/... asset reference."
                        ),
                    )
                )
            continue

        if prototype.mesh is None and prototype.geometry_payload is None:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="missing_prototype_mesh",
                    message=f"Prototype {prototype.identity.prim_name} has no resolved mesh payload.",
                )
            )
            continue

        if not payload_has_face_topology(prototype.mesh, prototype.geometry_payload):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="invalid_prototype_mesh",
                    message=(
                        f"Prototype {prototype.identity.prim_name} must contain point and face topology payloads "
                        "before prototype authoring."
                    ),
                )
            )
            continue
        if payload_point_count(prototype.mesh, prototype.geometry_payload) <= 0 or payload_face_count(
            prototype.mesh, prototype.geometry_payload
        ) <= 0:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="invalid_prototype_mesh",
                    message=(
                        f"Prototype {prototype.identity.prim_name} must contain point and face topology payloads "
                        "before prototype authoring."
                    ),
                )
            )

        issues.extend(
            _validate_payload_materials(
                prototype.mesh,
                prototype.geometry_payload,
                material_ids,
                f"Prototype {prototype.identity.prim_name}",
            )
        )

    return issues


def _resolve_conversion_mode(
    model: CanonicalTreeModel,
    conversion_mode: ConversionMode | str | None,
) -> ConversionMode:
    if conversion_mode is None:
        raw_value = model.metadata.conversion_mode
    else:
        raw_value = conversion_mode
    try:
        return ConversionMode.parse(raw_value)
    except ValueError:
        return ConversionMode.SKELETAL_ASSEMBLY


def _validate_mesh_materials(mesh, material_ids: set[int], label: str) -> list[ValidationIssue]:
    return _validate_payload_materials(mesh, None, material_ids, label)


def _validate_payload_materials(mesh, geometry_payload, material_ids: set[int], label: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    sections = payload_sections(mesh, geometry_payload)
    if not sections:
        return issues
    seen_faces: set[int] = set()
    face_count = payload_face_count(mesh, geometry_payload)
    for section in sections:
        if section.material_id not in material_ids:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="missing_material_definition",
                    message=f"{label} references undefined material id {section.material_id}.",
                )
            )
        invalid_faces = [face_index for face_index in section.face_indices if face_index < 0 or face_index >= face_count]
        if invalid_faces:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="invalid_material_section",
                    message=f"{label} contains out-of-range face indices in material section {section.material_id}.",
                )
            )
        overlap = seen_faces.intersection(section.face_indices)
        if overlap:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="overlapping_material_sections",
                    message=f"{label} has overlapping material sections on faces {sorted(overlap)[:8]}.",
                )
            )
        seen_faces.update(section.face_indices)
    if len(seen_faces) != face_count:
        issues.append(
            ValidationIssue(
                severity="error",
                code="incomplete_material_sections",
                message=f"{label} material sections cover {len(seen_faces)} of {face_count} faces.",
            )
        )
    return issues


def _valid_binding_joint_tokens(model: CanonicalTreeModel) -> set[str]:
    joints_by_name = {joint.name: joint for joint in model.skeleton}
    path_map: dict[str, str] = {}

    def resolve(name: str) -> str:
        if name in path_map:
            return path_map[name]
        joint = joints_by_name[name]
        if joint.parent is None or joint.parent not in joints_by_name:
            path_map[name] = joint.name
        else:
            path_map[name] = f"{resolve(joint.parent)}/{joint.name}"
        return path_map[name]

    tokens = set()
    for joint in model.skeleton:
        tokens.add(joint.name)
        tokens.add(resolve(joint.name))
    return tokens
