"""Application-facing Wind Preview service."""

from __future__ import annotations

from dataclasses import dataclass

from .canonical_loader import load_resolved_assembly_model, load_source_tree_model
from .dynamic_wind import build_dynamic_wind_data
from .models import CanonicalTreeModel, ConversionMode, DynamicWindData, ScatteredRigMode, ValidationIssue
from .scattered_parts import analyze_scattered_parts
from .wind_viewport_scene import WindViewportGroup, build_auto_wind_viewport_data, build_wind_viewport_groups, build_wind_viewport_scene
from .viewport_scene import ViewportScene


class WindPreviewError(ValueError):
    """Raised when Wind Preview cannot be built safely from XML source facts."""


@dataclass(frozen=True)
class WindPreviewRequest:
    input_path: str
    scattered_rig_mode: ScatteredRigMode = ScatteredRigMode.PER_CLUSTER_SKINNED
    orient_scattered_bones_from_instances: bool = False


@dataclass(frozen=True)
class WindPreviewResult:
    input_path: str
    source_model: CanonicalTreeModel
    dynamic_wind: DynamicWindData
    groups: tuple[WindViewportGroup, ...]
    diagnostics: tuple[ValidationIssue, ...]
    viewport_scene: ViewportScene
    xml_groups_available: bool = True
    preferred_grouping_mode: str = "xml"


def prepare_wind_preview_request(
    *,
    input_path: str,
    scattered_rig_mode: ScatteredRigMode | str = ScatteredRigMode.PER_CLUSTER_SKINNED,
    orient_scattered_bones_from_instances: bool = False,
) -> WindPreviewRequest:
    if not input_path.strip():
        raise WindPreviewError("Select a source XML file before previewing wind groups.")
    return WindPreviewRequest(
        input_path=input_path.strip(),
        scattered_rig_mode=ScatteredRigMode.parse(scattered_rig_mode),
        orient_scattered_bones_from_instances=bool(orient_scattered_bones_from_instances),
    )


def generate_wind_preview_from_request(request: WindPreviewRequest) -> WindPreviewResult:
    input_path = request.input_path.strip()
    if not input_path:
        raise WindPreviewError("Wind Preview requires a source XML path.")
    _report, source_model, diagnostics = load_source_tree_model(
        input_path,
        source_cache_enabled=False,
    )
    if analyze_scattered_parts(source_model).eligible:
        _report, resolved = load_resolved_assembly_model(
            input_path,
            conversion_mode=ConversionMode.SKELETAL_ASSEMBLY,
            scattered_rig_mode=request.scattered_rig_mode,
            orient_scattered_bones_from_instances=request.orient_scattered_bones_from_instances,
            source_cache_enabled=False,
        )
        source_model = resolved.authoring_model
        diagnostics = resolved.diagnostics
    _validate_wind_preview_skeleton(source_model)
    xml_groups_available, warning = _xml_wind_groups_available(source_model)
    if xml_groups_available:
        dynamic_wind = build_dynamic_wind_data(source_model.skeleton)
        groups = build_wind_viewport_groups(dynamic_wind)
        preferred_grouping_mode = "xml"
    else:
        dynamic_wind = build_auto_wind_viewport_data(source_model.skeleton, group_count=3)
        groups = build_wind_viewport_groups(dynamic_wind, label_kind="Hierarchy level")
        diagnostics = diagnostics + (warning,)
        preferred_grouping_mode = "auto"
    viewport_scene = build_wind_viewport_scene(source_model, dynamic_wind)
    preview_source_model = CanonicalTreeModel(
        metadata=source_model.metadata,
        materials=(),
        source_objects=(),
        base_mesh=None,
        skeleton=source_model.skeleton,
        assembly_parts=(),
    )
    return WindPreviewResult(
        input_path=input_path,
        source_model=preview_source_model,
        dynamic_wind=dynamic_wind,
        groups=groups,
        diagnostics=diagnostics,
        viewport_scene=viewport_scene,
        xml_groups_available=xml_groups_available,
        preferred_grouping_mode=preferred_grouping_mode,
    )


def _validate_wind_preview_skeleton(model: CanonicalTreeModel) -> None:
    if not model.skeleton:
        raise WindPreviewError("wind_preview_missing_skeleton: Wind Preview requires XML skeleton data.")


def _xml_wind_groups_available(model: CanonicalTreeModel) -> tuple[bool, ValidationIssue]:
    missing = []
    malformed = []
    for joint in model.skeleton:
        if joint.generator_label is None:
            missing.append(joint.name)
        elif joint.generator_level is None:
            malformed.append(f"{joint.name}={joint.generator_label!r}")
    if not missing and not malformed:
        return True, ValidationIssue("info", "wind_preview_xml_groups_available", "XML wind generator labels are available.")
    details = []
    if missing:
        details.append(f"missing Generator on joints: {', '.join(missing)}")
    if malformed:
        details.append(f"malformed Generator labels: {', '.join(malformed)}")
    return False, ValidationIssue(
        "warning",
        "wind_preview_xml_groups_unavailable",
        "XML Generator Groups disabled; using Auto Hierarchy because " + "; ".join(details),
    )
