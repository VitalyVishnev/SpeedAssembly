from __future__ import annotations

from .dynamic_wind import build_dynamic_wind_data, write_dynamic_wind_json
from .models import ConversionMode, DynamicWindData, DynamicWindSimulationGroup, Joint, ScatteredRigMode, WindJsonResult
from .opening_xml import read_authored_wind_skeleton, read_source_structure
from .source_extraction import SourceStructure
from .wind_profiles import FORCE_BASED, LEGACY


def inspect_wind_data(
    input_path: str,
    is_ground_cover: bool = False,
    scattered_rig_mode: ScatteredRigMode | str = ScatteredRigMode.PER_CLUSTER_SKINNED,
    orient_scattered_bones_from_instances: bool = False,
    profile: str = LEGACY,
) -> DynamicWindData:
    structure = read_source_structure(input_path) if profile == FORCE_BASED else None
    skeleton = _load_wind_skeleton(
        input_path,
        scattered_rig_mode=scattered_rig_mode,
        orient_scattered_bones_from_instances=orient_scattered_bones_from_instances,
        source_structure=structure,
    )
    data = build_dynamic_wind_data(skeleton, is_ground_cover=is_ground_cover)
    if profile == FORCE_BASED:
        from dataclasses import replace
        from .wind_authoring import with_wind_structure
        return with_wind_structure(replace(data, profile=profile), skeleton, source_structure=structure)
    return data


def generate_wind_json(
    input_path: str,
    output_path: str,
    group_settings: tuple[DynamicWindSimulationGroup, ...] = (),
    gust_attenuation: float = 0.0,
    is_ground_cover: bool = False,
    scattered_rig_mode: ScatteredRigMode | str = ScatteredRigMode.PER_CLUSTER_SKINNED,
    orient_scattered_bones_from_instances: bool = False,
    profile: str = LEGACY,
    root_name: str | None = None,
    data: DynamicWindData | None = None,
) -> WindJsonResult:
    structure = read_source_structure(input_path) if profile == FORCE_BASED else None
    skeleton = _load_wind_skeleton(
        input_path,
        scattered_rig_mode=scattered_rig_mode,
        orient_scattered_bones_from_instances=orient_scattered_bones_from_instances,
        source_structure=structure,
    )
    from .wind_authoring import prepare_wind_export
    dynamic_wind = prepare_wind_export(
        skeleton,
        profile=profile,
        data=data,
        input_path=input_path,
        root_name=root_name,
        source_structure=structure,
        group_settings=group_settings,
        gust_attenuation=gust_attenuation,
        is_ground_cover=is_ground_cover,
    )
    if not dynamic_wind.joint_assignments:
        raise ValueError("missing_skeleton: wind JSON generation requires a normalized skeleton.")
    resolved_output = write_dynamic_wind_json(dynamic_wind, output_path)
    return WindJsonResult(
        input_path=input_path,
        output_path=str(resolved_output),
        dynamic_wind=dynamic_wind,
    )


def _load_wind_skeleton(
    input_path: str,
    *,
    scattered_rig_mode: ScatteredRigMode | str = ScatteredRigMode.PER_CLUSTER_SKINNED,
    orient_scattered_bones_from_instances: bool = False,
    source_structure: SourceStructure | None = None,
) -> tuple[Joint, ...]:
    joints = (
        source_structure.authored_skeleton()
        if source_structure is not None
        else read_authored_wind_skeleton(input_path)
    )
    if joints:
        return joints

    from .canonical_loader import load_resolved_assembly_model, load_source_tree_model
    from .scattered_parts import analyze_scattered_parts

    _report, source_model, _diagnostics = load_source_tree_model(input_path)
    if not analyze_scattered_parts(source_model).eligible:
        return ()
    _report, resolved = load_resolved_assembly_model(
        input_path,
        conversion_mode=ConversionMode.SKELETAL_ASSEMBLY,
        scattered_rig_mode=scattered_rig_mode,
        orient_scattered_bones_from_instances=orient_scattered_bones_from_instances,
    )
    return resolved.authoring_model.skeleton
