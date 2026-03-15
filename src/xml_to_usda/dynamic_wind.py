from __future__ import annotations

import json
from collections import defaultdict
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
        return DynamicWindData(joint_assignments=(), simulation_groups=(), is_ground_cover=is_ground_cover, gust_attenuation=gust_attenuation)

    branch_orders = _resolve_branch_orders(skeleton)
    logical_depth_hints = _resolve_logical_depth_hints(source_objects, skeleton)
    for joint_name, logical_depth in logical_depth_hints.items():
        branch_orders[joint_name] = max(branch_orders.get(joint_name, 0), logical_depth)
    used_branch_orders = tuple(sorted({branch_orders[joint.name] for joint in skeleton}))
    group_index_by_branch_order = {branch_order: index for index, branch_order in enumerate(used_branch_orders)}

    joint_assignments = tuple(
        DynamicWindJointAssignment(
            joint_name=joint.name,
            simulation_group_index=group_index_by_branch_order[branch_orders[joint.name]],
            branch_order=branch_orders[joint.name],
        )
        for joint in skeleton
    )
    simulation_groups = _resolve_simulation_groups(used_branch_orders, group_settings)
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

    subtree_depths: dict[str, int] = {}

    def compute_depth(joint_name: str) -> int:
        cached = subtree_depths.get(joint_name)
        if cached is not None:
            return cached
        children = children_by_parent.get(joint_name, [])
        if not children:
            subtree_depths[joint_name] = 0
            return 0
        depth = 1 + max(compute_depth(child_name) for child_name in children)
        subtree_depths[joint_name] = depth
        return depth

    def main_child_for(joint_name: str) -> str | None:
        children = children_by_parent.get(joint_name, [])
        if not children:
            return None
        return min(children, key=lambda child_name: index_by_name[child_name])

    roots = [joint.name for joint in skeleton if joint.parent is None or joint.parent not in index_by_name]
    roots.sort(key=lambda joint_name: index_by_name[joint_name])
    if not roots:
        return {}

    branch_orders: dict[str, int] = {}

    def assign_branch_orders(joint_name: str, branch_order: int) -> None:
        if joint_name in branch_orders:
            branch_orders[joint_name] = min(branch_orders[joint_name], branch_order)
            return
        branch_orders[joint_name] = branch_order
        main_child = main_child_for(joint_name)
        for child_name in children_by_parent.get(joint_name, []):
            child_branch_order = branch_order if child_name == main_child else branch_order + 1
            assign_branch_orders(child_name, child_branch_order)

    primary_root = min(roots, key=lambda joint_name: (-compute_depth(joint_name), index_by_name[joint_name]))
    assign_branch_orders(primary_root, 0)
    for root_name in roots:
        if root_name != primary_root:
            assign_branch_orders(root_name, 0)
    return branch_orders


def _resolve_logical_depth_hints(
    source_objects: tuple[SourceObject, ...],
    skeleton: tuple[Joint, ...],
) -> dict[str, int]:
    if not source_objects or not skeleton:
        return {}

    joint_names = {joint.name for joint in skeleton}
    skeleton_depths = _resolve_skeleton_depths(skeleton)
    source_objects_by_id = {source_object.object_id: source_object for source_object in source_objects}
    logical_depth_by_object_id: dict[str, int] = {}

    def resolve_object_depth(object_id: str) -> int:
        cached = logical_depth_by_object_id.get(object_id)
        if cached is not None:
            return cached
        source_object = source_objects_by_id[object_id]
        parent_id = source_object.parent_id
        if parent_id is None or parent_id not in source_objects_by_id:
            logical_depth_by_object_id[object_id] = 0
        else:
            logical_depth_by_object_id[object_id] = resolve_object_depth(parent_id) + 1
        return logical_depth_by_object_id[object_id]

    hints: dict[str, int] = {}
    for source_object in source_objects:
        if source_object.mesh is None or not source_object.mesh.skel_joint_indices:
            continue
        logical_depth = resolve_object_depth(source_object.object_id)
        anchor_joint_index = _resolve_source_object_anchor_joint_index(
            source_object.mesh.skel_joint_indices,
            skeleton,
            skeleton_depths,
        )
        if anchor_joint_index is None:
            continue
        joint_name = skeleton[anchor_joint_index].name
        if joint_name in joint_names:
            hints[joint_name] = max(hints.get(joint_name, 0), logical_depth)
    return hints


def _resolve_skeleton_depths(skeleton: tuple[Joint, ...]) -> dict[str, int]:
    joints_by_name = {joint.name: joint for joint in skeleton}
    depths: dict[str, int] = {}

    def resolve_depth(joint_name: str) -> int:
        cached = depths.get(joint_name)
        if cached is not None:
            return cached
        parent_name = joints_by_name[joint_name].parent
        if parent_name is None or parent_name not in joints_by_name:
            depths[joint_name] = 0
        else:
            depths[joint_name] = resolve_depth(parent_name) + 1
        return depths[joint_name]

    for joint in skeleton:
        resolve_depth(joint.name)
    return depths


def _resolve_source_object_anchor_joint_index(
    skel_joint_indices: tuple[int, ...],
    skeleton: tuple[Joint, ...],
    skeleton_depths: dict[str, int],
) -> int | None:
    joint_counts: dict[int, int] = defaultdict(int)
    for joint_index in skel_joint_indices:
        if 0 <= joint_index < len(skeleton):
            joint_counts[joint_index] += 1
    if not joint_counts:
        return None
    return max(
        joint_counts,
        key=lambda joint_index: (
            joint_counts[joint_index],
            skeleton_depths.get(skeleton[joint_index].name, 0),
            joint_index,
        ),
    )


def _resolve_simulation_groups(
    branch_orders: tuple[int, ...],
    group_settings: tuple[DynamicWindSimulationGroup, ...],
) -> tuple[DynamicWindSimulationGroup, ...]:
    defaults = default_group_settings(len(branch_orders))
    if not group_settings:
        return tuple(replace(defaults[index], branch_order=branch_order) for index, branch_order in enumerate(branch_orders))

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
                is_trunk_group=index == 0,
                use_dual_influence=source.use_dual_influence,
                min_influence=source.min_influence,
                max_influence=source.max_influence,
            )
        )
    return tuple(resolved)
