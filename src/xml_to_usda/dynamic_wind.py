from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from collections import defaultdict

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

    branch_orders = _resolve_branch_orders(skeleton)
    used_branch_orders = tuple(sorted({branch_orders[joint.name] for joint in skeleton}))
    group_index_by_branch_order = {branch_order: index for index, branch_order in enumerate(used_branch_orders)}
    trunk_group_indices = set() if is_ground_cover else {0}

    joint_assignments = tuple(
        DynamicWindJointAssignment(
            joint_name=joint.name,
            simulation_group_index=group_index_by_branch_order[branch_orders[joint.name]],
            branch_order=branch_orders[joint.name],
        )
        for joint in skeleton
    )
    simulation_groups = _resolve_simulation_groups(used_branch_orders, group_settings, trunk_group_indices)
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


def default_group_settings(group_count: int) -> tuple[DynamicWindSimulationGroup, ...]:
    return tuple(
        DynamicWindSimulationGroup(
            group_index=index,
            branch_order=index,
            influence=DEFAULT_TRUNK_INFLUENCE if index == 0 else DEFAULT_BRANCH_INFLUENCE,
            shift_top=DEFAULT_TRUNK_SHIFT_TOP if index == 0 else DEFAULT_BRANCH_SHIFT_TOP,
            is_trunk_group=index == 0,
        )
        for index in range(group_count)
    )


def _resolve_branch_orders(skeleton: tuple[Joint, ...]) -> dict[str, int]:
    index_by_name = {joint.name: index for index, joint in enumerate(skeleton)}
    children_by_parent: dict[str | None, list[str]] = defaultdict(list)
    for joint in skeleton:
        children_by_parent[joint.parent].append(joint.name)

    roots = [joint.name for joint in skeleton if joint.parent is None or joint.parent not in index_by_name]
    roots.sort(key=lambda joint_name: index_by_name[joint_name])
    if not roots:
        return {}

    branch_orders: dict[str, int] = {}
    root_set = set(roots)

    def assign_branch_orders(joint_name: str, branch_order: int) -> None:
        if joint_name in branch_orders:
            branch_orders[joint_name] = min(branch_orders[joint_name], branch_order)
        else:
            branch_orders[joint_name] = branch_order

        child_names = children_by_parent.get(joint_name, [])
        if not child_names:
            return

        # Groups advance only when the hierarchy branches.
        # Linear continuation stays on the same wind layer so sibling stems do not fracture into separate groups.
        next_branch_order = branch_order if joint_name in root_set or len(child_names) == 1 else branch_order + 1
        for child_name in child_names:
            assign_branch_orders(child_name, next_branch_order)

    for root_name in roots:
        assign_branch_orders(root_name, 0)
    return branch_orders


def _resolve_simulation_groups(
    branch_orders: tuple[int, ...],
    group_settings: tuple[DynamicWindSimulationGroup, ...],
    trunk_group_indices: set[int],
) -> tuple[DynamicWindSimulationGroup, ...]:
    defaults = default_group_settings(len(branch_orders))
    if not group_settings:
        return tuple(
            replace(defaults[index], branch_order=branch_order, is_trunk_group=index in trunk_group_indices)
            for index, branch_order in enumerate(branch_orders)
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
