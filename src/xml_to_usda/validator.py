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

    if not model.skeleton:
        issues.append(
            ValidationIssue(
                severity="error",
                code="missing_skeleton",
                message="Skeleton data is required for skeletal nanite assembly export.",
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
