from __future__ import annotations

from .dynamic_wind import build_dynamic_wind_data, write_dynamic_wind_json
from .models import ConversionMode, DynamicWindData, DynamicWindSimulationGroup, Joint, ScatteredRigMode, WindJsonResult
from .skeleton_rules import joint_name_from_bone_id, parse_generator_label
from .xml_reader import iterparse_source_xml


def inspect_wind_data(
    input_path: str,
    is_ground_cover: bool = False,
    scattered_rig_mode: ScatteredRigMode | str = ScatteredRigMode.PER_CLUSTER_SKINNED,
    orient_scattered_bones_from_instances: bool = False,
) -> DynamicWindData:
    skeleton = _load_wind_skeleton(
        input_path,
        scattered_rig_mode=scattered_rig_mode,
        orient_scattered_bones_from_instances=orient_scattered_bones_from_instances,
    )
    return build_dynamic_wind_data(
        skeleton,
        is_ground_cover=is_ground_cover,
    )


def generate_wind_json(
    input_path: str,
    output_path: str,
    group_settings: tuple[DynamicWindSimulationGroup, ...] = (),
    gust_attenuation: float = 0.0,
    is_ground_cover: bool = False,
    scattered_rig_mode: ScatteredRigMode | str = ScatteredRigMode.PER_CLUSTER_SKINNED,
    orient_scattered_bones_from_instances: bool = False,
) -> WindJsonResult:
    skeleton = _load_wind_skeleton(
        input_path,
        scattered_rig_mode=scattered_rig_mode,
        orient_scattered_bones_from_instances=orient_scattered_bones_from_instances,
    )
    dynamic_wind = build_dynamic_wind_data(
        skeleton,
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
) -> tuple[Joint, ...]:
    joints: list[Joint] = []
    for _event, elem in iterparse_source_xml(input_path, events=("end",)):
        if elem.tag != "Bone":
            continue
        raw_bone_id = elem.attrib.get("ID")
        if raw_bone_id is None or not raw_bone_id.lstrip("-").isdigit():
            elem.clear()
            continue
        bone_id = int(raw_bone_id)
        raw_parent_id = elem.attrib.get("ParentID")
        parsed_parent_id = None
        if raw_parent_id not in {None, "", "-1"} and raw_parent_id.lstrip("-").isdigit():
            parsed_parent_id = int(raw_parent_id)
        generator_label, generator_level = parse_generator_label(elem.attrib.get("Generator"), bone_id)
        joints.append(
            Joint(
                name=joint_name_from_bone_id(bone_id),
                source_id=bone_id,
                parent=joint_name_from_bone_id(parsed_parent_id) if parsed_parent_id is not None else None,
                generator_label=generator_label,
                generator_level=generator_level,
            )
        )
        elem.clear()
    if joints:
        return tuple(joints)

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
