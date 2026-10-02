from __future__ import annotations

from .models import CanonicalTreeModel, ValidationIssue
from .skeleton_processing import strictly_vertical_joint_names, validate_skeleton
from .validation_common import metadata_warning_issues


def validate_source_model(model: CanonicalTreeModel) -> tuple[ValidationIssue, ...]:
    """Validate Source Facts before Operator Intent is applied."""
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

    issues.extend(metadata_warning_issues(model.metadata.warnings))
    issues.extend(validate_skeleton(model.skeleton))
    vertical_joints = strictly_vertical_joint_names(model.skeleton)
    if vertical_joints:
        issues.append(
            ValidationIssue(
                severity="warning",
                code="strictly_vertical_skeleton",
                message=(
                    f"Strictly vertical skeleton detected ({len(vertical_joints)} joint(s)). "
                    "Skeletal Assembly conversion will tilt the entire asset by 1 degree around its pivot "
                    "to prevent Dynamic Wind animation failure."
                ),
            )
        )
    return tuple(issues)
