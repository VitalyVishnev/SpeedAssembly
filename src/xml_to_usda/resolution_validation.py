from __future__ import annotations

from .asset_paths import is_valid_unreal_asset_path
from .geometry_buffers import payload_sections
from .models import (
    PrototypeResolutionMode,
    PrototypeSourceMode,
    ResolvedAssemblyModel,
    UdimMode,
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
    issues.extend(_validate_udim_settings_match_inline_materials(resolved))

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


def _validate_udim_settings_match_inline_materials(resolved: ResolvedAssemblyModel) -> list[ValidationIssue]:
    active_material_ids = {
        setting.material_id
        for setting in resolved.udim_material_settings
        if UdimMode.parse(setting.mode) != UdimMode.OFF
    }
    if not active_material_ids:
        return []

    inline_material_ids = set()
    if resolved.authoring_model.base_mesh is not None:
        inline_material_ids.update(section.material_id for section in resolved.authoring_model.base_mesh.sections)
    for prototype in resolved.authoring_model.prototypes:
        if prototype.resolution_mode == PrototypeResolutionMode.EXTERNAL_ASSET:
            continue
        inline_material_ids.update(
            section.material_id
            for section in payload_sections(prototype.mesh, prototype.geometry_payload)
        )

    missing = sorted(active_material_ids - inline_material_ids)
    return [
        ValidationIssue(
            severity="error",
            code="unmatched_udim_material",
            message=(
                "UDIM settings target material ids that do not exist on authored inline geometry: "
                + ", ".join(str(material_id) for material_id in missing)
            ),
        )
    ] if missing else []
