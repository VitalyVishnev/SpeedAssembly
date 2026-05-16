from __future__ import annotations

from .models import ValidationIssue


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


def metadata_warning_issues(warnings: tuple[str, ...]) -> list[ValidationIssue]:
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
