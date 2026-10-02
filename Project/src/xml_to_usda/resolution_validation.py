from __future__ import annotations

from .asset_paths import is_valid_unreal_asset_path
from .models import (
    PrototypeResolutionMode,
    PrototypeSourceMode,
    ResolvedAssemblyModel,
    ValidationIssue,
)
from .validation_common import metadata_warning_issues


def validate_resolution(resolved: ResolvedAssemblyModel) -> tuple[ValidationIssue, ...]:
    """Validate Source Facts plus Operator Intent."""
    issues: list[ValidationIssue] = []
    source_warnings = set(resolved.source_model.metadata.warnings)
    resolution_warnings = tuple(
        warning for warning in resolved.authoring_model.metadata.warnings if warning not in source_warnings
    )
    issues.extend(metadata_warning_issues(resolution_warnings))

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
