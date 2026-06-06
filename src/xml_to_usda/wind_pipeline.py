from __future__ import annotations

from .dynamic_wind import build_dynamic_wind_data, write_dynamic_wind_json
from .models import DynamicWindData, DynamicWindSimulationGroup, Joint, WindJsonResult
from .skeleton_rules import joint_name_from_bone_id, parse_generator_label
from .xml_reader import iterparse_source_xml


def inspect_wind_data(input_path: str, is_ground_cover: bool = False) -> DynamicWindData:
    skeleton = _load_wind_skeleton(input_path)
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
) -> WindJsonResult:
    skeleton = _load_wind_skeleton(input_path)
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


def _load_wind_skeleton(input_path: str) -> tuple[Joint, ...]:
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
    return tuple(joints)
