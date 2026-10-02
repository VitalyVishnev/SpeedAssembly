from __future__ import annotations

import pytest

from xml_to_usda.dynamic_wind import build_dynamic_wind_data
from xml_to_usda.models import Joint, Matrix4d, Vector3
from xml_to_usda.wind_group_stack import (
    add_tokens_to_manual_group,
    flatten_wind_group_stack,
    make_manual_group,
    remove_tokens_from_manual_group,
    skeleton_fingerprint,
    subtree_joint_tokens,
)


def test_wind_group_stack_flattens_manual_layers_over_base_groups() -> None:
    base = build_dynamic_wind_data(_skeleton())
    lower_manual = make_manual_group(0, joint_tokens=frozenset({"branch_a"}))
    top_manual = make_manual_group(1, joint_tokens=frozenset({"branch_a", "branch_b"}))

    result = flatten_wind_group_stack(base, (lower_manual, top_manual))

    assert [(group.name, group.joint_tokens) for group in result.groups] == [
        ("Base group 0", ("root",)),
        ("Manual group 1", ("branch_a", "branch_b")),
    ]
    assert {assignment.joint_name: assignment.simulation_group_index for assignment in result.dynamic_wind.joint_assignments} == {
        "root": 0,
        "branch_a": 1,
        "branch_b": 1,
    }


def test_wind_group_stack_remove_reveals_lower_assignment() -> None:
    base = build_dynamic_wind_data(_skeleton())
    manual = make_manual_group(0, joint_tokens=frozenset({"branch_a", "branch_b"}))

    edited = remove_tokens_from_manual_group(manual, {"branch_a"})
    result = flatten_wind_group_stack(base, (edited,))

    assert [(group.name, group.joint_tokens) for group in result.groups] == [
        ("Base group 0", ("root",)),
        ("Base group 1", ("branch_a",)),
        ("Manual group 0", ("branch_b",)),
    ]


def test_wind_group_stack_rejects_missing_coverage() -> None:
    base = build_dynamic_wind_data(())

    with pytest.raises(ValueError, match="wind_group_stack_unassigned_joints"):
        flatten_wind_group_stack(base, (), all_joint_tokens=("root",))


def test_wind_group_stack_rejects_unknown_manual_joints() -> None:
    base = build_dynamic_wind_data(_skeleton())

    with pytest.raises(ValueError, match="wind_group_stack_unknown_manual_joints"):
        flatten_wind_group_stack(base, (make_manual_group(0, joint_tokens=frozenset({"ghost"})),))


def test_wind_group_stack_subtree_and_fingerprint_are_joint_name_based() -> None:
    skeleton = _skeleton()
    manual = add_tokens_to_manual_group(make_manual_group(0), subtree_joint_tokens(skeleton, "branch_a"))

    assert manual.joint_tokens == frozenset({"branch_a", "branch_b"})
    assert skeleton_fingerprint(skeleton) == (
        ("root", None),
        ("branch_a", "root"),
        ("branch_b", "branch_a"),
    )


def _skeleton() -> tuple[Joint, ...]:
    return (
        _joint("root", None, 0),
        _joint("branch_a", "root", 1),
        _joint("branch_b", "branch_a", 2),
    )


def _joint(name: str, parent: str | None, level: int) -> Joint:
    return Joint(
        name=name,
        parent=parent,
        generator_label=f"Group_{level}",
        generator_level=level,
        bind_transform=Matrix4d.from_translation(Vector3(0.0, float(level), 0.0)),
    )
