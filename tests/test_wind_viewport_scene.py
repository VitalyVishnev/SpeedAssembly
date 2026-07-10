from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from xml_to_usda.canonical_loader import load_source_tree_model
from xml_to_usda.dynamic_wind import build_dynamic_wind_data
from xml_to_usda.models import (
    Color4,
    ExportMetadata,
    InstanceBinding,
    Joint,
    Matrix4d,
    MeshData,
    Prototype,
    PrototypeIdentity,
    Quaternion,
    RepeatedPartInstance,
    TreeAsset,
    Vector3,
)
from xml_to_usda.wind_preview_service import generate_wind_preview_from_request
from xml_to_usda.wind_viewport_scene import (
    SELECTED_ALPHA,
    MUTED_ALPHA,
    WindViewportSelection,
    build_auto_wind_viewport_data,
    build_wind_viewport_groups,
    build_wind_viewport_scene,
    subtree_root_from_pick_token,
)


def test_wind_viewport_scene_uses_xml_wind_groups_for_base_and_instances() -> None:
    model = _tree_model()
    dynamic_wind = build_dynamic_wind_data(model.skeleton)

    groups = build_wind_viewport_groups(dynamic_wind)
    scene = build_wind_viewport_scene(model, dynamic_wind)

    assert [group.group_index for group in groups] == [0, 1, 2]
    assert [group.branch_order for group in groups] == [0, 1, 2]
    assert groups[1].joint_tokens == ("bone_001",)
    assert [draw.draw_id for draw in scene.draw_calls] == [
        "wind:base:bone_001:draw",
        "wind:base:root:draw",
        "wind:instance:leaf_001",
    ]
    assert [segment.segment_id for segment in scene.bone_segments] == [
        "bone:root->root",
        "bone:root->bone_001",
        "bone:bone_001->bone_002",
    ]
    assert scene.stats.uploaded_triangles == 3
    assert scene.stats.logical_triangles == 3
    assert scene.stats.instance_count == 1


def test_wind_viewport_scene_accepts_skeleton_only_external_preview() -> None:
    model = replace(_tree_model(), base_mesh=None, assembly_parts=(), prototypes=())
    dynamic_wind = build_auto_wind_viewport_data(model.skeleton, group_count=3)

    scene = build_wind_viewport_scene(model, dynamic_wind)

    assert scene.mesh_batches == ()
    assert scene.draw_calls == ()
    assert [segment.child_token for segment in scene.bone_segments] == ["root", "bone_001", "bone_002"]
    assert scene.stats.logical_triangles == 0


def test_wind_viewport_selection_highlights_group_without_mutating_membership() -> None:
    model = _tree_model()
    dynamic_wind = build_dynamic_wind_data(model.skeleton)

    scene = build_wind_viewport_scene(model, dynamic_wind, selection=WindViewportSelection(group_index=2))

    alpha_by_draw = {draw.draw_id: draw.tint.a for draw in scene.draw_calls if draw.tint is not None}
    assert alpha_by_draw["wind:instance:leaf_001"] == pytest.approx(SELECTED_ALPHA)
    assert alpha_by_draw["wind:base:root:draw"] == pytest.approx(MUTED_ALPHA)
    assert alpha_by_draw["wind:base:bone_001:draw"] == pytest.approx(MUTED_ALPHA)
    assert [assignment.simulation_group_index for assignment in dynamic_wind.joint_assignments] == [0, 1, 2]


def test_auto_wind_viewport_groups_follow_trunk_then_first_branch_order() -> None:
    model = _tree_model()

    one_group = build_auto_wind_viewport_data(model.skeleton, group_count=1)
    two_groups = build_auto_wind_viewport_data(model.skeleton, group_count=2)

    assert [assignment.simulation_group_index for assignment in one_group.joint_assignments] == [0, 0, 0]
    assert [assignment.simulation_group_index for assignment in two_groups.joint_assignments] == [0, 0, 0]
    assert [group.group_index for group in build_wind_viewport_groups(two_groups, label_kind="Hierarchy level")] == [0]


def test_auto_wind_viewport_groups_ignore_generator_levels() -> None:
    model = _tree_model()
    skeleton = (
        replace(model.skeleton[0], generator_level=2, generator_label="Branches_2"),
        replace(model.skeleton[1], generator_level=1, generator_label="Branches_1"),
        replace(model.skeleton[2], generator_level=0, generator_label="Trunk"),
    )

    auto_groups = build_auto_wind_viewport_data(skeleton, group_count=3)

    assert [assignment.simulation_group_index for assignment in auto_groups.joint_assignments] == [0, 0, 0]
    assert auto_groups.simulation_groups[0].is_trunk_group is True


@pytest.mark.parametrize(
    "sample_path",
    (
        Path("samples/speedtree/simple_tree/variants/SimpleTree_01.xml"),
        Path("samples/speedtree/simple_tree/variants/SimpleTree_02_three_trunks.xml"),
    ),
)
def test_auto_wind_viewport_groups_match_simple_tree_xml_generator_levels(sample_path: Path) -> None:
    _document, model, _diagnostics = load_source_tree_model(sample_path)
    xml_groups = build_dynamic_wind_data(model.skeleton)
    skeleton_without_wind_labels = tuple(
        replace(joint, generator_level=None, generator_label=None)
        for joint in model.skeleton
    )

    auto_groups = build_auto_wind_viewport_data(skeleton_without_wind_labels, group_count=10)

    assert auto_groups.joint_assignments == xml_groups.joint_assignments
    assert [group.group_index for group in auto_groups.simulation_groups] == [
        group.group_index for group in xml_groups.simulation_groups
    ]


def test_auto_wind_viewport_groups_advance_at_branch_forks_not_each_bone() -> None:
    skeleton = (
        _joint("root", None, 0.0, 0.0, 0.0, level=0),
        _joint("trunk_1", "root", 0.0, 1.0, 0.0),
        _joint("trunk_2", "trunk_1", 0.0, 2.0, 0.0),
        _joint("branch_a_1", "trunk_1", 1.0, 1.0, 0.0),
        _joint("branch_a_2", "branch_a_1", 2.0, 2.0, 0.0),
        _joint("branch_a_side", "branch_a_1", 1.0, 2.0, 0.0),
        _joint("branch_a_side_tip", "branch_a_side", 1.0, 3.0, 0.0),
        _joint("branch_b_1", "trunk_1", -1.0, 1.0, 0.0),
        _joint("branch_b_2", "branch_b_1", -2.0, 2.0, 0.0),
    )

    auto_groups = build_auto_wind_viewport_data(skeleton, group_count=3)

    assert {assignment.joint_name: assignment.simulation_group_index for assignment in auto_groups.joint_assignments} == {
        "root": 0,
        "trunk_1": 0,
        "trunk_2": 0,
        "branch_a_1": 1,
        "branch_a_2": 1,
        "branch_a_side": 2,
        "branch_a_side_tip": 2,
        "branch_b_1": 1,
        "branch_b_2": 1,
    }


def test_auto_wind_viewport_groups_can_continue_selected_levels_by_endpoint() -> None:
    skeleton = (
        _joint("root", None, 0.0, 0.0, 0.0, end=(0.0, 1.0, 0.0)),
        _joint("trunk_1", "root", 0.0, 1.0, 0.0, end=(0.0, 2.0, 0.0)),
        _joint("branch_a", "root", 1.0, 0.0, 0.0, end=(2.0, 0.0, 0.0)),
        _joint("branch_b", "trunk_1", -1.0, 2.0, 0.0, end=(-2.0, 2.0, 0.0)),
        _joint("branch_a_cont", "branch_a", 2.0, 0.0, 0.0, end=(3.0, 0.0, 0.0)),
        _joint("upper_trunk", "trunk_1", 0.0, 2.0, 0.0, end=(0.0, 3.0, 0.0)),
    )

    strict_groups = build_auto_wind_viewport_data(skeleton, group_count=3)
    continuous_groups = build_auto_wind_viewport_data(
        skeleton,
        group_count=3,
        continuous_branch_orders=frozenset({0, 1}),
    )

    strict_by_joint = {assignment.joint_name: assignment.simulation_group_index for assignment in strict_groups.joint_assignments}
    continuous_by_joint = {assignment.joint_name: assignment.simulation_group_index for assignment in continuous_groups.joint_assignments}
    assert strict_by_joint["upper_trunk"] == 1
    assert strict_by_joint["branch_a_cont"] == 2
    assert continuous_by_joint["upper_trunk"] == 0
    assert continuous_by_joint["branch_a_cont"] == 1


def test_auto_wind_viewport_groups_can_keep_simple_tree_tip_continuation_in_trunk() -> None:
    _document, model, _diagnostics = load_source_tree_model(Path("samples/speedtree/simple_tree/variants/SimpleTree_01.xml"))
    skeleton_without_wind_labels = tuple(
        replace(joint, generator_level=None, generator_label=None)
        for joint in model.skeleton
    )

    auto_groups = build_auto_wind_viewport_data(
        skeleton_without_wind_labels,
        group_count=10,
        continuous_branch_orders=frozenset({0}),
    )

    by_joint = {assignment.joint_name: assignment.simulation_group_index for assignment in auto_groups.joint_assignments}
    assert by_joint["bone_086"] == 0
    assert by_joint["bone_087"] == 0
    assert by_joint["bone_088"] == 0
    assert by_joint["bone_101"] == 1


def test_wind_viewport_subtree_selection_uses_descendant_joints() -> None:
    model = _tree_model()
    dynamic_wind = build_dynamic_wind_data(model.skeleton)

    scene = build_wind_viewport_scene(model, dynamic_wind, selection=WindViewportSelection(subtree_root_token="bone_001"))

    alpha_by_draw = {draw.draw_id: draw.tint.a for draw in scene.draw_calls if draw.tint is not None}
    assert alpha_by_draw["wind:base:root:draw"] == pytest.approx(MUTED_ALPHA)
    assert alpha_by_draw["wind:base:bone_001:draw"] == pytest.approx(SELECTED_ALPHA)
    assert alpha_by_draw["wind:instance:leaf_001"] == pytest.approx(SELECTED_ALPHA)
    selected_segments = [segment.child_token for segment in scene.bone_segments if segment.selected]
    assert selected_segments == ["bone_001", "bone_002"]
    assert subtree_root_from_pick_token("root->bone_001@0.500") == "bone_001"


def test_wind_preview_service_falls_back_to_auto_when_xml_generator_labels_are_missing(monkeypatch) -> None:
    model = _tree_model()
    broken = replace(
        model,
        skeleton=(
            replace(model.skeleton[0], generator_label=None, generator_level=None),
            model.skeleton[1],
            model.skeleton[2],
        ),
    )

    monkeypatch.setattr(
        "xml_to_usda.wind_preview_service.load_source_tree_model",
        lambda input_path, source_cache_enabled=False: (None, broken, ()),
    )

    result = generate_wind_preview_from_request(type("Request", (), {"input_path": "tree.xml"})())

    assert result.xml_groups_available is False
    assert result.preferred_grouping_mode == "auto"
    assert result.diagnostics[-1].code == "wind_preview_xml_groups_unavailable"


def _joint(
    name: str,
    parent: str | None,
    x: float,
    y: float,
    z: float,
    *,
    level: int | None = None,
    end: tuple[float, float, float] | None = None,
) -> Joint:
    return Joint(
        name=name,
        parent=parent,
        generator_label=f"Group_{level}" if level is not None else None,
        generator_level=level,
        bind_transform=Matrix4d.from_translation(Vector3(x, y, z)),
        bind_end_transform=Matrix4d.from_translation(Vector3(*end)) if end is not None else None,
    )


def _tree_model() -> TreeAsset:
    skeleton = (
        Joint(
            name="root",
            source_id=0,
            parent=None,
            generator_label="Group_0",
            generator_level=0,
            bind_transform=Matrix4d.from_translation(Vector3(0.0, 0.0, 0.0)),
            bind_end_transform=Matrix4d.from_translation(Vector3(0.0, 1.0, 0.0)),
        ),
        Joint(
            name="bone_001",
            source_id=1,
            parent="root",
            generator_label="Group_1",
            generator_level=1,
            bind_transform=Matrix4d.from_translation(Vector3(0.0, 1.0, 0.0)),
            bind_end_transform=Matrix4d.from_translation(Vector3(0.0, 2.0, 0.0)),
        ),
        Joint(
            name="bone_002",
            source_id=2,
            parent="bone_001",
            generator_label="Group_2",
            generator_level=2,
            bind_transform=Matrix4d.from_translation(Vector3(0.0, 2.0, 0.0)),
            bind_end_transform=Matrix4d.from_translation(Vector3(0.0, 3.0, 0.0)),
        ),
    )
    base_mesh = MeshData(
        name="TreeBaseMesh",
        points=(
            Vector3(0.0, 0.0, 0.0),
            Vector3(1.0, 0.0, 0.0),
            Vector3(0.0, 1.0, 0.0),
            Vector3(0.0, 1.0, 0.0),
            Vector3(1.0, 1.0, 0.0),
            Vector3(0.0, 2.0, 0.0),
        ),
        face_vertex_counts=(3, 3),
        face_vertex_indices=(0, 1, 2, 3, 4, 5),
        skel_joint_indices=(0, 0, 0, 1, 1, 1),
        skel_joint_weights=(1.0,) * 6,
        skel_element_size=1,
    )
    prototype_mesh = MeshData(
        name="Leaf",
        points=(
            Vector3(0.0, 0.0, 0.0),
            Vector3(0.2, 0.0, 0.0),
            Vector3(0.0, 0.2, 0.0),
        ),
        face_vertex_counts=(3,),
        face_vertex_indices=(0, 1, 2),
    )
    prototype = Prototype(
        identity=PrototypeIdentity(source_key="Mesh_7", prim_name="Leaf"),
        mesh=prototype_mesh,
        source_key="Mesh_7",
        source_mesh_id=7,
        source_name="Leaf",
    )
    instance = RepeatedPartInstance(
        name="leaf_001",
        prototype_key="Mesh_7",
        position=Vector3(0.0, 2.0, 0.0),
        orientation=Quaternion(1.0, 0.0, 0.0, 0.0),
        scale=Vector3(1.0, 1.0, 1.0),
        binding=InstanceBinding(joint_tokens=("bone_002",), weights=(1.0,)),
        source_object_id="2",
        source_mesh_id=7,
        source_bone_ids=(2,),
    )
    return TreeAsset(
        metadata=ExportMetadata(source_path="tree.xml", source_version=None),
        materials=(),
        source_objects=(),
        base_mesh=base_mesh,
        skeleton=skeleton,
        assembly_parts=(instance,),
        prototypes=(prototype,),
    )
