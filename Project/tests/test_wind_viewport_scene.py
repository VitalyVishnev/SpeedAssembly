from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json

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
from xml_to_usda.wind_tree_hierarchy import (
    TreeHierarchySettings, analyze_tree_hierarchy, prepare_tree_hierarchy, classify_tree_hierarchy,
)
from xml_to_usda.wind_viewport_scene import (
    SELECTED_ALPHA,
    MUTED_ALPHA,
    WindViewportSelection,
    build_auto_wind_viewport_data,
    build_wind_viewport_groups,
    build_wind_viewport_scene,
    recolor_wind_viewport_scene,
    subtree_root_from_pick_token,
)


def test_wind_viewport_scene_uses_xml_wind_groups_for_base_and_omits_repeated_parts(monkeypatch) -> None:
    model = _tree_model()
    dynamic_wind = build_dynamic_wind_data(model.skeleton)
    range_calls = 0
    from xml_to_usda import wind_viewport_scene

    original_face_ranges = wind_viewport_scene._face_ranges

    def counted_face_ranges(face_vertex_counts):
        nonlocal range_calls
        range_calls += 1
        return original_face_ranges(face_vertex_counts)

    monkeypatch.setattr(wind_viewport_scene, "_face_ranges", counted_face_ranges)

    groups = build_wind_viewport_groups(dynamic_wind)
    scene = build_wind_viewport_scene(model, dynamic_wind)

    assert [group.group_index for group in groups] == [0, 1, 2]
    assert [group.branch_order for group in groups] == [0, 1, 2]
    assert groups[1].joint_tokens == ("bone_001",)
    assert [draw.draw_id for draw in scene.draw_calls] == [
        "wind:base:bone_001:draw",
        "wind:base:root:draw",
    ]
    assert [segment.segment_id for segment in scene.bone_segments] == [
        "bone:root->root",
        "bone:root->bone_001",
        "bone:bone_001->bone_002",
    ]
    assert scene.stats.uploaded_triangles == 2
    assert scene.stats.logical_triangles == 2
    assert scene.stats.instance_count == 0
    assert range_calls == 1


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
    assert alpha_by_draw["wind:base:root:draw"] == pytest.approx(MUTED_ALPHA)
    assert alpha_by_draw["wind:base:bone_001:draw"] == pytest.approx(MUTED_ALPHA)
    assert [assignment.simulation_group_index for assignment in dynamic_wind.joint_assignments] == [0, 1, 2]


def test_wind_viewport_scene_can_recolor_compact_preview_without_source_geometry() -> None:
    model = _tree_model()
    dynamic_wind = build_dynamic_wind_data(model.skeleton)
    scene = build_wind_viewport_scene(model, dynamic_wind)
    compact_model = replace(model, base_mesh=None, prototypes=())
    selection = WindViewportSelection(group_index=2)

    recolored = recolor_wind_viewport_scene(scene, compact_model, dynamic_wind, selection=selection)
    rebuilt = build_wind_viewport_scene(model, dynamic_wind, selection=selection)

    assert [draw.tint for draw in recolored.draw_calls] == [draw.tint for draw in rebuilt.draw_calls]
    assert recolored.mesh_batches is scene.mesh_batches
    assert recolored.bone_segments == rebuilt.bone_segments


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


def test_tree_hierarchy_proposes_reference_groups_from_bare_format_independent_rigs() -> None:
    cases = json.loads(Path("tests/fixtures/wind_hierarchy/curated_trees.json").read_text(encoding="utf-8"))
    total = wrong = 0
    for case in cases:
        skeleton = tuple(
            Joint(f"joint_{i}", parent=f"joint_{parent}" if parent >= 0 else None, bind_transform=Matrix4d(tuple(tuple(row) for row in matrix)))
            for i, (parent, matrix, _group) in enumerate(case["joints"])
        )
        expected = {f"joint_{i}": group for i, (_parent, _matrix, group) in enumerate(case["joints"]) if group is not None}
        count = max(expected.values()) + 1
        # Preserve the measured previous rule as an explicit comparison mode.
        previous = TreeHierarchySettings(equivalent_forks="continuation")
        analysis = analyze_tree_hierarchy(skeleton, previous)
        data = build_auto_wind_viewport_data(skeleton, count, method="tree", tree_analysis=analysis)
        predicted = {assignment.joint_name: assignment.simulation_group_index for assignment in data.joint_assignments}
        mismatch = sum(predicted[name] != group for name, group in expected.items())
        # This is a calibrated proposal, not a claim to recover every generator
        # boundary. Keep the whole curated corpus useful and prevent a bad tree
        # family from disappearing inside a pooled accuracy number.
        assert mismatch / len(expected) <= 0.30, case["reference"]
        total += len(expected)
        wrong += mismatch
        if count == 1:
            assert all(joint.branch_order == 0 for joint in analysis), case["reference"]

        names = {joint.name: f"renamed_{len(skeleton) - i}" for i, joint in enumerate(skeleton)}
        rotation = ((0.36, 0.48, -0.8), (-0.8, 0.6, 0.0), (0.48, 0.64, 0.6))
        transformed = []
        for joint in skeleton:
            rows = []
            for i, row in enumerate(joint.bind_transform.rows):
                rotated = tuple(sum(row[k] * rotation[k][column] for k in range(3)) for column in range(3))
                if i == 3:
                    rotated = tuple(value * 1000 + shift for value, shift in zip(rotated, (42, -13, 5)))
                rows.append((*rotated, row[3]))
            transformed.append(replace(
                joint, name=names[joint.name], parent=names.get(joint.parent), bind_transform=Matrix4d(tuple(rows)),
                generator_level=99, generator_label="Ignored", source_id=99,
                bind_end_transform=Matrix4d.from_translation(Vector3(9999, 9999, 9999)),
            ))
        rotated = analyze_tree_hierarchy(tuple(reversed(transformed)), previous)
        assert {j.name: j.branch_order for j in rotated} == {names[j.name]: j.branch_order for j in analysis}, case["reference"]
        default = analyze_tree_hierarchy(skeleton)
        default_rotated = analyze_tree_hierarchy(tuple(reversed(transformed)))
        assert {j.name: j.branch_order for j in default_rotated} == {names[j.name]: j.branch_order for j in default}, case["reference"]
    assert wrong / total <= 0.05

    # A symmetric bare fork contains no evidence for selecting either child.
    symmetric = (_joint("root", None, 0, 0, 0), _joint("left", "root", -1, 1, 0), _joint("right", "root", 1, 1, 0))
    ambiguous = analyze_tree_hierarchy(symmetric)
    assert ambiguous[0].ambiguous
    assert ambiguous[0].equivalent
    assert [j.branch_order for j in ambiguous] == [0, 0, 0]
    prepared = prepare_tree_hierarchy(symmetric)
    advanced = classify_tree_hierarchy(prepared, TreeHierarchySettings(equivalent_forks="advance"))
    assert [j.branch_order for j in advanced] == [0, 1, 1]
    previous = classify_tree_hierarchy(prepared, TreeHierarchySettings(equivalent_forks="continuation"))
    assert [j.branch_order for j in previous] == [0, 1, 1]
    bind_override = classify_tree_hierarchy(prepared, TreeHierarchySettings(direction_mode="bind"))
    assert [j.display_end for j in bind_override] == [j.display_end for j in ambiguous]


def test_tree_equivalent_daughters_keep_a_branch_level_and_obey_length_threshold() -> None:
    # A side branch forks symmetrically. Neither daughter deserves a deeper
    # level until there is sufficient directional/structural evidence.
    def oriented(name, parent, position, angle):
        from math import cos, sin, radians
        c, s = cos(radians(angle)), sin(radians(angle))
        return Joint(name, parent=parent, bind_transform=Matrix4d((
            (c, s, 0, 0), (-s, c, 0, 0), (0, 0, 1, 0), (*position, 1),
        )))

    skeleton = (
        oriented("root", None, (0, 0, 0), 90),
        oriented("fork", "root", (1, 0, 0), 0),
        oriented("left", "fork", (2, 0, 0), 45),
        oriented("right", "fork", (2, 0, 0), -45),
        oriented("left_tip", "left", (3, 1, 0), 45),
        oriented("right_tip", "right", (3, -1, 0), -45),
    )
    prepared = prepare_tree_hierarchy(skeleton)
    keep = classify_tree_hierarchy(prepared)
    assert keep[1].equivalent
    assert [j.branch_order for j in keep] == [0, 1, 1, 1, 1, 1]
    advance = classify_tree_hierarchy(prepared, TreeHierarchySettings(equivalent_forks="advance"))
    assert [j.branch_order for j in advance] == [0, 1, 2, 2, 2, 2]
    longer = (*skeleton[:-2], replace(skeleton[-2], bind_transform=Matrix4d.from_translation(Vector3(8, 6, 0))), skeleton[-1])
    prepared = prepare_tree_hierarchy(longer)
    assert not classify_tree_hierarchy(prepared)[1].equivalent
    relaxed = classify_tree_hierarchy(prepared, TreeHierarchySettings(equivalent_length=0))
    assert relaxed[1].equivalent
    assert relaxed[2].branch_order == relaxed[3].branch_order == 1


@pytest.mark.parametrize("physical_segments", (False, True))
def test_pve_hierarchy_groups_whole_branches_by_geometry_beyond_three_levels(physical_segments) -> None:
    skeleton = [_joint("root", None, 0.0, 0.0, 0.0), _joint("fork_0", "root", 0.0, 1.0, 0.0)]
    expected = {"root": 0, "fork_0": 0}
    position = (0.0, 1.0, 0.0)
    direction = (0.0, 1.0, 0.0)
    for depth in range(6):
        parent = f"fork_{depth}"
        side_direction = (-direction[1], direction[0], 0.0)
        side_position = tuple(a + b for a, b in zip(position, side_direction))
        continuation = tuple(a + b for a, b in zip(position, direction))
        tip = tuple(a + 100 * b for a, b in zip(continuation, direction))
        if physical_segments:
            skeleton[-1] = replace(skeleton[-1], bind_end_transform=Matrix4d.from_translation(Vector3(*continuation)))
        # Both candidates exist independently of their generator labels or file order.
        skeleton.extend((
            _joint(f"fork_{depth + 1}", parent, *side_position),
            _joint(f"continuation_{depth}", parent, *continuation, end=tip if physical_segments else None),
            _joint(f"tip_{depth}", f"continuation_{depth}", *tip),
        ))
        expected.update({f"fork_{depth + 1}": depth + 1, f"continuation_{depth}": depth, f"tip_{depth}": depth})
        position, direction = side_position, side_direction
        # Move the next fork to the end to allow the next physical segment to be set.
        skeleton.append(skeleton.pop(-3))

    skeleton = tuple(skeleton)
    # Length must also affect the decision: a much longer turned path wins
    # over a short straight path, with the same PVE sum of both scores.
    skeleton += (
        _joint("other_root", None, 0.0, 0.0, 2.0),
        _joint("other_fork", "other_root", 0.0, 1.0, 2.0, end=(0.0, 2.0, 2.0) if physical_segments else None),
        _joint("short", "other_fork", 0.0, 2.0, 2.0, end=(0.0, 3.0, 2.0) if physical_segments else None),
        _joint("short_tip", "short", 0.0, 3.0, 2.0),
        _joint("long", "other_fork", 1.0, 1.0, 2.0, end=(11.0, 1.0, 2.0) if physical_segments else None),
        _joint("long_tip", "long", 11.0, 1.0, 2.0),
    )
    expected.update(other_root=0, other_fork=0, short=1, short_tip=1, long=0, long_tip=0)
    geometric = build_auto_wind_viewport_data(skeleton, 10, method="pve")
    by_name = {item.joint_name: item.simulation_group_index for item in geometric.joint_assignments}
    assert by_name == expected
    assert len(geometric.simulation_groups) == 7
    assert geometric == build_auto_wind_viewport_data(skeleton, 10, method="pve")
    reordered = (skeleton[0], *reversed(skeleton[1:]))
    assert {
        item.joint_name: item.simulation_group_index
        for item in build_auto_wind_viewport_data(reordered, 10, method="pve").joint_assignments
    } == expected
    merged = build_auto_wind_viewport_data(skeleton, 4, method="pve")
    assert {item.joint_name: item.simulation_group_index for item in merged.joint_assignments} == {
        name: min(level, 3) for name, level in expected.items()
    }
    assert {
        item.joint_name: item.simulation_group_index
        for item in build_auto_wind_viewport_data(reordered, 10).joint_assignments
    } != expected


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

    assert result.source_model.base_mesh is None
    assert result.source_model.prototypes == ()
    assert result.source_model.repeated_parts == ()
    assert result.xml_groups_available is False
    assert result.preferred_grouping_mode == "auto_tree"
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
