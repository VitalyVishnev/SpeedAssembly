from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

from .models import DynamicWindData, DynamicWindJointAssignment, DynamicWindSimulationGroup, Joint, SourceObject


DEFAULT_TRUNK_INFLUENCE = 0.2
DEFAULT_TRUNK_SHIFT_TOP = 0.5
DEFAULT_BRANCH_INFLUENCE = 1.0
DEFAULT_BRANCH_SHIFT_TOP = 0.5
DEFAULT_DUAL_MIN_INFLUENCE = 0.5
DEFAULT_DUAL_MAX_INFLUENCE = 1.0


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
    if is_ground_cover:
        trunk_group_indices: set[int] = set()
    elif group_settings:
        explicit_trunk_groups = {group.group_index for group in group_settings if group.is_trunk_group}
        trunk_group_indices = explicit_trunk_groups or {0}
    else:
        trunk_group_indices = {0}

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
    validate_dynamic_wind_data(dynamic_wind)
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
                "Influence": 0.0 if group.use_dual_influence else group.influence,
                "MinInfluence": group.min_influence if group.use_dual_influence else 0.0,
                "MaxInfluence": group.max_influence if group.use_dual_influence else 0.0,
                "ShiftTop": group.shift_top if group.use_dual_influence else 0.0,
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
            use_dual_influence=True,
            min_influence=DEFAULT_DUAL_MIN_INFLUENCE,
            max_influence=DEFAULT_DUAL_MAX_INFLUENCE,
        )
        for index, branch_order in enumerate(branch_orders)
    )


def _resolve_generator_levels(skeleton: tuple[Joint, ...]) -> dict[str, int]:
    generator_levels: dict[str, int] = {
        joint.name: joint.generator_level
        for joint in skeleton
        if joint.generator_level is not None
    }
    joints_by_name = {joint.name: joint for joint in skeleton}
    child_names_by_parent: dict[str | None, list[str]] = {}
    for joint in skeleton:
        child_names_by_parent.setdefault(joint.parent, []).append(joint.name)

    unresolved_joint_names = {
        joint.name
        for joint in skeleton
        if joint.generator_level is None
    }
    progress = True
    while unresolved_joint_names and progress:
        progress = False
        for joint_name in tuple(unresolved_joint_names):
            joint = joints_by_name[joint_name]
            parent_level = generator_levels.get(joint.parent) if joint.parent is not None else None
            if parent_level is not None:
                generator_levels[joint_name] = parent_level
                unresolved_joint_names.remove(joint_name)
                progress = True
                continue

            child_levels = [
                generator_levels[child_name]
                for child_name in child_names_by_parent.get(joint_name, ())
                if child_name in generator_levels
            ]
            if child_levels:
                generator_levels[joint_name] = max(min(child_levels) - 1, 0)
                unresolved_joint_names.remove(joint_name)
                progress = True

    missing: list[str] = []
    invalid: list[str] = []
    for joint in skeleton:
        if joint.name not in generator_levels:
            if joint.generator_label is None:
                missing.append(joint.name)
            else:
                invalid.append(f"{joint.name}={joint.generator_label!r}")

    if missing or invalid:
        detail_parts: list[str] = []
        if missing:
            detail_parts.append(f"missing Generator on joints: {', '.join(missing)}")
        if invalid:
            detail_parts.append(f"malformed Generator labels: {', '.join(invalid)}")
        raise ValueError("missing_generator_level: " + "; ".join(detail_parts))
    return generator_levels


def validate_dynamic_wind_data(
    dynamic_wind: DynamicWindData,
    *,
    skeleton: tuple[Joint, ...] = (),
    require_linear_groups: bool = False,
) -> None:
    """Reject Dynamic Wind data that Unreal accepts but cannot simulate as intended."""
    groups = tuple(sorted(dynamic_wind.simulation_groups, key=lambda group: group.group_index))
    expected_group_indices = tuple(range(len(groups)))
    actual_group_indices = tuple(group.group_index for group in groups)
    if actual_group_indices != expected_group_indices:
        raise ValueError("dynamic_wind_group_indices: Simulation groups must use each contiguous index from zero exactly once.")
    for group in groups:
        _validate_wind_group_values(group)
    if not math.isfinite(dynamic_wind.gust_attenuation):
        raise ValueError("dynamic_wind_gust_attenuation: Gust Attenuation must be finite.")
    for assignment in dynamic_wind.joint_assignments:
        if assignment.simulation_group_index not in expected_group_indices:
            raise ValueError(f"dynamic_wind_unknown_group: joint {assignment.joint_name!r} references group {assignment.simulation_group_index}.")
    if not skeleton:
        return

    expected_names = tuple(joint.name for joint in skeleton)
    if len(set(expected_names)) != len(expected_names):
        raise ValueError("dynamic_wind_duplicate_skeleton_joint: RefSkeleton joint names must be unique.")
    assignments_by_name: dict[str, DynamicWindJointAssignment] = {}
    duplicate_names: list[str] = []
    for assignment in dynamic_wind.joint_assignments:
        if assignment.joint_name in assignments_by_name:
            duplicate_names.append(assignment.joint_name)
        assignments_by_name[assignment.joint_name] = assignment
    if duplicate_names:
        raise ValueError("dynamic_wind_duplicate_joint: " + ", ".join(sorted(set(duplicate_names))))
    expected_name_set = set(expected_names)
    unknown = sorted(set(assignments_by_name) - expected_name_set)
    if unknown:
        raise ValueError("dynamic_wind_unknown_joint: " + ", ".join(unknown))
    missing = [name for name in expected_names if name not in assignments_by_name]
    if missing:
        raise ValueError("dynamic_wind_unassigned_joint: " + ", ".join(missing))
    if require_linear_groups:
        _validate_linear_group_chains(skeleton, assignments_by_name)


def _validate_wind_group_values(group: DynamicWindSimulationGroup) -> None:
    values = {
        "Influence": group.influence,
        "Min Influence": group.min_influence,
        "Max Influence": group.max_influence,
        "Shift Top": group.shift_top,
    }
    for label, value in values.items():
        if not math.isfinite(value):
            raise ValueError(f"dynamic_wind_group_value: group {group.group_index} {label} must be finite.")
    if group.use_dual_influence and group.min_influence > group.max_influence:
        raise ValueError(f"dynamic_wind_dual_range: group {group.group_index} Min Influence cannot exceed Max Influence.")


def _validate_linear_group_chains(
    skeleton: tuple[Joint, ...],
    assignments_by_name: dict[str, DynamicWindJointAssignment],
) -> None:
    children_by_parent: dict[str, list[str]] = {}
    for joint in skeleton:
        if joint.parent is not None:
            children_by_parent.setdefault(joint.parent, []).append(joint.name)
    forks: list[str] = []
    for parent, children in children_by_parent.items():
        parent_group = assignments_by_name[parent].simulation_group_index
        matching_children = [
            child for child in children
            if assignments_by_name[child].simulation_group_index == parent_group
        ]
        if len(matching_children) > 1:
            forks.append(f"group {parent_group}: {parent} -> {', '.join(sorted(matching_children))}")
    if forks:
        raise ValueError("dynamic_wind_same_group_fork: " + "; ".join(forks))


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
