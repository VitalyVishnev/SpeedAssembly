"""Compatibility facade for staged validation entry points."""

from __future__ import annotations

from .authoring_validation import validate_authoring_model
from .models import CanonicalTreeModel, ConversionMode, ValidationIssue
from .resolution_validation import validate_resolution
from .source_validation import validate_source_model


def validate_model(
    model: CanonicalTreeModel,
    conversion_mode: ConversionMode | str | None = None,
) -> tuple[ValidationIssue, ...]:
    """Compatibility wrapper for callers that still validate one final model."""
    return validate_source_model(model) + validate_authoring_model(model, conversion_mode=conversion_mode)
