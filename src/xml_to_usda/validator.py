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
                message="Object hierarchy data is required for SimpleTree_01 normalization.",
            )
        )

    if model.trunk_mesh is None:
        issues.append(
            ValidationIssue(
                severity="error",
                code="missing_trunk_mesh",
                message="Tree profile requires trunk/base geometry for skeletal assembly import.",
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
                message="No leaf references found; converter will emit a trunk-only diagnostic USDA.",
            )
        )

    if model.leaf_instances and any(leaf.source_bone_id is None for leaf in model.leaf_instances):
        issues.append(
            ValidationIssue(
                severity="error",
                code="missing_leaf_binding",
                message="Leaf instances must carry explicit BoneID bindings from the XML export.",
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
