from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from .models import DynamicWindData, DynamicWindJointAssignment, DynamicWindSimulationGroup, Joint, SourceObject


DEFAULT_TRUNK_INFLUENCE = 0.2
DEFAULT_TRUNK_SHIFT_TOP = 0.0
DEFAULT_BRANCH_INFLUENCE = 1.0
DEFAULT_BRANCH_SHIFT_TOP = 0.0


def build_dynamic_wind_data(
    skeleton: tuple[Joint, ...],
    source_objects: tuple[SourceObject, ...] = (),
    group_settings: tuple[DynamicWindSimulationGroup, ...] = (),
    gust_attenuation: float = 0.0,
    is_ground_cover: bool = False,
) -> DynamicWindData:
    if not skeleton:
        return DynamicWindData(
            joint_assignments=(),
            simulation_groups=(),
            is_ground_cover=is_ground_cover,
            gust_attenuation=gust_attenuation,
        )

    generator_levels = _resolve_generator_levels(skeleton)
    used_generator_levels = tuple(sorted({generator_levels[joint.name] for joint in skeleton}))
    group_index_by_generator_level = {generator_level: index for index, generator_level in enumerate(used_generator_levels)}
    trunk_group_indices = set() if is_ground_cover else {0}

    joint_assignments = tuple(
        DynamicWindJointAssignment(
            joint_name=joint.name,
            simulation_group_index=group_index_by_generator_level[generator_levels[joint.name]],
            branch_order=generator_levels[joint.name],
        )
        for joint in skeleton
    )
    simulation_groups = _resolve_simulation_groups(used_generator_levels, group_settings, trunk_group_indices)
    return DynamicWindData(
        joint_assignments=joint_assignments,
        simulation_groups=simulation_groups,
        is_ground_cover=is_ground_cover,
        gust_attenuation=gust_attenuation,
    )


def write_dynamic_wind_json(dynamic_wind: DynamicWindData, output_path: str | Path) -> Path:
    resolved_output = Path(output_path)
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_output.write_text(json.dumps(render_dynamic_wind_payload(dynamic_wind), indent=4), encoding="utf-8")
    return resolved_output


def render_dynamic_wind_payload(dynamic_wind: DynamicWindData) -> dict:
    return {
        "Joints": [
            {
                "JointName": assignment.joint_name,
                "SimulationGroupIndex": assignment.simulation_group_index,
            }
            for assignment in dynamic_wind.joint_assignments
        ],
        "SimulationGroups": [
            {
                "bUseDualInfluence": group.use_dual_influence,
                "Influence": group.influence,
                "MinInfluence": group.min_influence,
                "MaxInfluence": group.max_influence,
                "ShiftTop": group.shift_top,
                "bIsTrunkGroup": group.is_trunk_group,
            }
            for group in dynamic_wind.simulation_groups
        ],
        "bIsGroundCover": dynamic_wind.is_ground_cover,
        "GustAttenuation": dynamic_wind.gust_attenuation,
    }


def default_group_settings(branch_orders: tuple[int, ...]) -> tuple[DynamicWindSimulationGroup, ...]:
    return tuple(
        DynamicWindSimulationGroup(
            group_index=index,
            branch_order=branch_order,
            influence=DEFAULT_TRUNK_INFLUENCE if index == 0 else DEFAULT_BRANCH_INFLUENCE,
            shift_top=DEFAULT_TRUNK_SHIFT_TOP if index == 0 else DEFAULT_BRANCH_SHIFT_TOP,
            is_trunk_group=index == 0,
        )
        for index, branch_order in enumerate(branch_orders)
    )


def _resolve_generator_levels(skeleton: tuple[Joint, ...]) -> dict[str, int]:
    generator_levels: dict[str, int] = {}
    missing: list[str] = []
    invalid: list[str] = []

    for joint in skeleton:
        if joint.generator_level is None:
            if joint.generator_label is None:
                missing.append(joint.name)
            else:
                invalid.append(f"{joint.name}={joint.generator_label!r}")
            continue
        generator_levels[joint.name] = joint.generator_level

    if missing or invalid:
        detail_parts: list[str] = []
        if missing:
            detail_parts.append(f"missing Generator on joints: {', '.join(missing)}")
        if invalid:
            detail_parts.append(f"malformed Generator labels: {', '.join(invalid)}")
        raise ValueError("missing_generator_level: " + "; ".join(detail_parts))

    return generator_levels


def _resolve_simulation_groups(
    branch_orders: tuple[int, ...],
    group_settings: tuple[DynamicWindSimulationGroup, ...],
    trunk_group_indices: set[int],
) -> tuple[DynamicWindSimulationGroup, ...]:
    defaults = default_group_settings(branch_orders)
    if not group_settings:
        return tuple(
            replace(defaults[index], is_trunk_group=index in trunk_group_indices)
            for index in range(len(branch_orders))
        )

    explicit_by_index = {group.group_index: group for group in group_settings}
    resolved: list[DynamicWindSimulationGroup] = []
    last_explicit_group = None
    for index, branch_order in enumerate(branch_orders):
        explicit_group = explicit_by_index.get(index)
        if explicit_group is not None:
            last_explicit_group = explicit_group
            source = explicit_group
        elif last_explicit_group is not None:
            source = last_explicit_group
        else:
            source = defaults[index]
        resolved.append(
            DynamicWindSimulationGroup(
                group_index=index,
                branch_order=branch_order,
                influence=source.influence,
                shift_top=source.shift_top,
                is_trunk_group=index in trunk_group_indices,
                use_dual_influence=source.use_dual_influence,
                min_influence=source.min_influence,
                max_influence=source.max_influence,
            )
        )
    return tuple(resolved)
