"""Deterministic Wind Preview group stack rules.

Layer: application/domain.

This module owns the editable Wind Preview stack: base Dynamic Wind groups at
the bottom, manual override layers above them, and one flattened Dynamic Wind
result for viewport coloring and JSON export.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .dynamic_wind import default_group_settings
from .models import DynamicWindData, DynamicWindJointAssignment, Joint


EDIT_MODE_SUBTREE = "subtree"
EDIT_MODE_BONES = "bones"


@dataclass(frozen=True, slots=True)
class WindManualGroup:
    layer_id: int
    name: str
    joint_tokens: frozenset[str] = frozenset()
    edit_mode: str = EDIT_MODE_SUBTREE


@dataclass(frozen=True, slots=True)
class WindFlattenedGroup:
    source_key: str
    source_layer_id: int | None
    source_group_index: int | None
    final_group_index: int
    name: str
    joint_tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WindFlattenResult:
    dynamic_wind: DynamicWindData
    groups: tuple[WindFlattenedGroup, ...]


def make_manual_group(layer_id: int, *, joint_tokens: frozenset[str] = frozenset()) -> WindManualGroup:
    return WindManualGroup(layer_id=int(layer_id), name=f"Manual group {int(layer_id)}", joint_tokens=frozenset(joint_tokens))


def next_manual_layer_id(groups: tuple[WindManualGroup, ...]) -> int:
    return max((group.layer_id for group in groups), default=-1) + 1


def add_tokens_to_manual_group(group: WindManualGroup, tokens: set[str] | frozenset[str]) -> WindManualGroup:
    return replace(group, joint_tokens=group.joint_tokens | frozenset(tokens))


def remove_tokens_from_manual_group(group: WindManualGroup, tokens: set[str] | frozenset[str]) -> WindManualGroup:
    return replace(group, joint_tokens=group.joint_tokens - frozenset(tokens))


def flatten_wind_group_stack(
    base_dynamic_wind: DynamicWindData,
    manual_groups_bottom_to_top: tuple[WindManualGroup, ...] = (),
    *,
    all_joint_tokens: tuple[str, ...] | None = None,
) -> WindFlattenResult:
    expected_tokens = tuple(all_joint_tokens) if all_joint_tokens is not None else tuple(
        assignment.joint_name for assignment in base_dynamic_wind.joint_assignments
    )
    expected_token_set = set(expected_tokens)
    if len(expected_tokens) != len(expected_token_set):
        raise ValueError("wind_group_stack_duplicate_joint: duplicate joint token in coverage set.")

    layers = _base_layers(base_dynamic_wind) + _manual_layers(manual_groups_bottom_to_top, expected_token_set)
    owner_by_token: dict[str, int] = {}
    for layer_index, layer in enumerate(layers):
        for token in layer.joint_tokens:
            owner_by_token[token] = layer_index

    missing = sorted(expected_token_set - set(owner_by_token))
    if missing:
        sample = ", ".join(missing[:8])
        raise ValueError(f"wind_group_stack_unassigned_joints: {len(missing)} unassigned joint(s): {sample}")

    visible_layers: list[_StackLayer] = []
    visible_tokens_by_layer: list[list[str]] = []
    for layer_index, layer in enumerate(layers):
        tokens = sorted(token for token in expected_tokens if owner_by_token.get(token) == layer_index)
        if not tokens:
            continue
        visible_layers.append(layer)
        visible_tokens_by_layer.append(tokens)

    assignments: list[DynamicWindJointAssignment] = []
    final_groups: list[WindFlattenedGroup] = []
    for final_index, (layer, tokens) in enumerate(zip(visible_layers, visible_tokens_by_layer)):
        for token in tokens:
            assignments.append(
                DynamicWindJointAssignment(
                    joint_name=token,
                    simulation_group_index=final_index,
                    branch_order=final_index,
                )
            )
        final_groups.append(
            WindFlattenedGroup(
                source_key=layer.source_key,
                source_layer_id=layer.manual_layer_id,
                source_group_index=layer.base_group_index,
                final_group_index=final_index,
                name=layer.name,
                joint_tokens=tuple(tokens),
            )
        )

    return WindFlattenResult(
        dynamic_wind=DynamicWindData(
            joint_assignments=tuple(assignments),
            simulation_groups=default_group_settings(tuple(range(len(final_groups)))),
            is_ground_cover=base_dynamic_wind.is_ground_cover,
            gust_attenuation=base_dynamic_wind.gust_attenuation,
        ),
        groups=tuple(final_groups),
    )


def subtree_joint_tokens(skeleton: tuple[Joint, ...], root_token: str) -> frozenset[str]:
    joints_by_name = {joint.name: joint for joint in skeleton}
    if root_token not in joints_by_name:
        raise ValueError(f"wind_group_stack_unknown_subtree_root: {root_token}")
    children_by_parent: dict[str, list[str]] = {}
    for joint in skeleton:
        if joint.parent is not None:
            children_by_parent.setdefault(joint.parent, []).append(joint.name)
    selected: set[str] = set()
    pending = [root_token]
    while pending:
        token = pending.pop()
        if token in selected:
            continue
        selected.add(token)
        pending.extend(children_by_parent.get(token, ()))
    return frozenset(selected)


def skeleton_fingerprint(skeleton: tuple[Joint, ...]) -> tuple[tuple[str, str | None], ...]:
    return tuple((joint.name, joint.parent) for joint in skeleton)


@dataclass(frozen=True, slots=True)
class _StackLayer:
    source_key: str
    name: str
    joint_tokens: frozenset[str]
    base_group_index: int | None = None
    manual_layer_id: int | None = None


def _base_layers(dynamic_wind: DynamicWindData) -> tuple[_StackLayer, ...]:
    tokens_by_group: dict[int, set[str]] = {}
    for assignment in dynamic_wind.joint_assignments:
        tokens_by_group.setdefault(assignment.simulation_group_index, set()).add(assignment.joint_name)
    return tuple(
        _StackLayer(
            source_key=f"base:{group.group_index}",
            name=f"Base group {group.group_index}",
            joint_tokens=frozenset(tokens_by_group.get(group.group_index, set())),
            base_group_index=group.group_index,
        )
        for group in sorted(dynamic_wind.simulation_groups, key=lambda item: item.group_index)
    )


def _manual_layers(groups: tuple[WindManualGroup, ...], valid_tokens: set[str]) -> tuple[_StackLayer, ...]:
    layers: list[_StackLayer] = []
    for group in groups:
        unknown = sorted(group.joint_tokens - valid_tokens)
        if unknown:
            sample = ", ".join(unknown[:8])
            raise ValueError(f"wind_group_stack_unknown_manual_joints: {len(unknown)} unknown joint(s): {sample}")
        layers.append(
            _StackLayer(
                source_key=f"manual:{group.layer_id}",
                name=group.name,
                joint_tokens=frozenset(group.joint_tokens),
                manual_layer_id=group.layer_id,
            )
        )
    return tuple(layers)
