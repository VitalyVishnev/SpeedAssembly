from __future__ import annotations

from .models import CanonicalTreeModel, ValidationIssue
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
    return tuple(issues)
