from __future__ import annotations

from .models import CanonicalTreeModel, ValidationIssue


def validate_model(model: CanonicalTreeModel) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []

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

    if not model.leaf_references:
        issues.append(
            ValidationIssue(
                severity="warning",
                code="missing_leaf_references",
                message="No leaf references found; converter will emit a trunk-only diagnostic USDA.",
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
        issues.append(
            ValidationIssue(
                severity="warning",
                code="metadata_warning",
                message=warning,
            )
        )

    return tuple(issues)
