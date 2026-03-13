from __future__ import annotations

from .models import CanonicalTreeModel, ValidationIssue


ERROR_MARKERS = {
    "packed_array_error:": "inconsistent_packed_arrays",
    "missing_object_hierarchy:": "missing_object_hierarchy",
    "missing_leaf_binding:": "missing_leaf_binding",
    "skeleton_object_mismatch:": "skeleton_object_mismatch",
}


def validate_model(model: CanonicalTreeModel) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []

    if not model.source_objects:
        issues.append(
            ValidationIssue(
                severity="error",
                code="missing_object_hierarchy",
                message="Object hierarchy data is required for skeletal assembly normalization.",
            )
        )

    if model.base_mesh is None:
        issues.append(
            ValidationIssue(
                severity="error",
                code="missing_trunk_mesh",
                message="Tree asset requires trunk/base geometry for skeletal assembly import.",
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
        if len(model.base_mesh.skel_joint_indices) != len(model.base_mesh.face_vertex_indices):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="invalid_base_mesh_skinning_shape",
                    message="Base skeletal mesh joint index payload must match face-varying topology exactly.",
                )
            )
        if len(model.base_mesh.skel_joint_weights) != len(model.base_mesh.face_vertex_indices):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="invalid_base_mesh_skinning_shape",
                    message="Base skeletal mesh joint weight payload must match face-varying topology exactly.",
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

    if not model.leaf_instances:
        issues.append(
            ValidationIssue(
                severity="warning",
                code="missing_leaf_references",
                message="No reusable part references found; converter will emit a base-geometry-only USDA.",
            )
        )

    if model.leaf_instances and any(not leaf.binding.joint_tokens for leaf in model.leaf_instances):
        issues.append(
            ValidationIssue(
                severity="error",
                code="missing_leaf_binding",
                message="Reusable instances must carry explicit skeletal binding data derived from the XML export.",
            )
        )
    if model.leaf_instances:
        prototypes_by_key = {prototype.source_key: prototype for prototype in model.prototypes}
        for leaf in model.leaf_instances:
            prototype = prototypes_by_key.get(leaf.prototype_key)
            if prototype is None:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="missing_prototype_mesh",
                        message=f"Instance {leaf.name} references missing prototype {leaf.prototype_key}.",
                    )
                )
                continue
            if prototype.mesh is None:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="missing_prototype_mesh",
                        message=f"Prototype {prototype.identity.prim_name} has no resolved mesh payload.",
                    )
                )

    for leaf in model.leaf_instances:
        if len(leaf.binding.joint_tokens) != len(leaf.binding.weights):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="invalid_binding_shape",
                    message=f"Instance {leaf.name} has mismatched joint and weight counts.",
                )
            )
        if leaf.binding.weights and abs(sum(leaf.binding.weights) - 1.0) > 1e-4:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="non_normalized_binding_weights",
                    message=f"Instance {leaf.name} binding weights sum to {sum(leaf.binding.weights):g} instead of 1.",
                )
            )

    if model.branch_segments and model.skeleton and not any(segment.source_joint for segment in model.branch_segments):
        issues.append(
            ValidationIssue(
                severity="warning",
                code="skeleton_object_mismatch",
                message="Branch segments were extracted, but none could be associated with a skeleton joint directly.",
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

    for warning in model.metadata.warnings:
        matched_code = None
        for marker, code in ERROR_MARKERS.items():
            if warning.startswith(marker):
                matched_code = code
                issues.append(
                    ValidationIssue(
                        severity="error" if code != "skeleton_object_mismatch" else "warning",
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

    return tuple(issues)
