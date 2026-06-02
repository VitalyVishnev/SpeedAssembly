from __future__ import annotations

from dataclasses import replace

import pytest

from xml_to_usda.fracture_service import (
    FRACTURE_METHOD_BRANCH_BASE_GREEDY,
    FRACTURE_METHOD_PURE_HIERARCHY,
    FRACTURE_METHOD_WIND_GUIDED_HIERARCHY,
    FractureError,
    FractureSettings,
    plan_fracture,
)
from xml_to_usda.models import (
    ExportMetadata,
    InstanceBinding,
    Joint,
    Matrix4d,
    MeshData,
    Quaternion,
    RepeatedPartInstance,
    TreeAsset,
    Vector3,
)


def _joint(name: str, source_id: int, parent: str | None, y: float, group: int) -> Joint:
    return Joint(
        name=name,
        source_id=source_id,
        parent=parent,
        generator_label=f"Group_{group}",
        generator_level=group,
        bind_transform=Matrix4d.from_translation(Vector3(0.0, y, 0.0)),
        rest_transform=Matrix4d.from_translation(Vector3(0.0, y, 0.0)),
    )


def _base_mesh_for_joint_faces(joint_indices: tuple[int, ...]) -> MeshData:
    points: list[Vector3] = []
    face_vertex_counts: list[int] = []
    face_vertex_indices: list[int] = []
    skel_joint_indices: list[int] = []
    for face_index, joint_index in enumerate(joint_indices):
        first_point = len(points)
        x = float(face_index)
        points.extend(
            (
                Vector3(x, 0.0, 0.0),
                Vector3(x + 0.4, 0.0, 0.0),
                Vector3(x, 0.4, 0.0),
            )
        )
        face_vertex_counts.append(3)
        face_vertex_indices.extend((first_point, first_point + 1, first_point + 2))
        skel_joint_indices.extend((joint_index, joint_index, joint_index))
    return MeshData(
        name="Base",
        points=tuple(points),
        face_vertex_counts=tuple(face_vertex_counts),
        face_vertex_indices=tuple(face_vertex_indices),
        skel_joint_indices=tuple(skel_joint_indices),
        skel_joint_weights=(1.0,) * len(skel_joint_indices),
        skel_element_size=1,
    )


def _repeated_part(name: str, joint_token: str) -> RepeatedPartInstance:
    return RepeatedPartInstance(
        name=name,
        prototype_key="Mesh_1",
        position=Vector3(0.0, 0.0, 0.0),
        orientation=Quaternion(1.0, 0.0, 0.0, 0.0),
        scale=Vector3(1.0, 1.0, 1.0),
        binding=InstanceBinding(joint_tokens=(joint_token,), weights=(1.0,)),
        source_object_id=None,
        source_mesh_id=1,
    )


def _tree() -> TreeAsset:
    skeleton = (
        _joint("root", 0, None, 0.0, 0),
        _joint("bone_001", 1, "root", 1.0, 0),
        _joint("bone_002", 2, "bone_001", 2.0, 0),
        _joint("bone_003", 3, "bone_001", 1.4, 1),
        _joint("bone_004", 4, "bone_003", 1.8, 2),
    )
    return TreeAsset(
        metadata=ExportMetadata(source_path="tree.xml", source_version=None),
        materials=(),
        source_objects=(),
        base_mesh=_base_mesh_for_joint_faces((0, 1, 2, 3, 4)),
        skeleton=skeleton,
        assembly_parts=(
            _repeated_part("TopLeaves", "bone_002"),
            _repeated_part("BranchLeaves", "bone_004"),
        ),
    )


def _single_root_trunk(face_count: int) -> TreeAsset:
    skeleton = (_joint("root", 0, None, 0.0, 0),)
    return TreeAsset(
        metadata=ExportMetadata(source_path="trunk.xml", source_version=None),
        materials=(),
        source_objects=(),
        base_mesh=_base_mesh_for_joint_faces((0,) * face_count),
        skeleton=skeleton,
        assembly_parts=(),
    )


def test_wind_guided_fracture_keeps_root_first_and_assigns_repeated_parts_by_skeleton_owner() -> None:
    plan = plan_fracture(
        _tree(),
        FractureSettings(
            method=FRACTURE_METHOD_WIND_GUIDED_HIERARCHY,
            target_piece_count=3,
            output_stem="Oak",
        ),
    )

    assert tuple(piece.name for piece in plan.pieces) == ("Oak_fracture_00", "Oak_fracture_01", "Oak_fracture_02")
    assert plan.pieces[0].is_root_piece is True
    assert plan.pieces[0].base_face_indices
    assert plan.pieces[1].cut_joint_token == "bone_001"
    assert plan.pieces[2].cut_joint_token == "bone_003"
    assert plan.pieces[1].repeated_part_names == ("TopLeaves",)
    assert plan.pieces[2].repeated_part_names == ("BranchLeaves",)
    assert all(piece.base_face_indices for piece in plan.pieces)
    assert plan.actual_piece_count == 3


def test_fracture_uses_synthetic_mid_segment_face_split_when_hierarchy_has_no_safe_cut_site() -> None:
    plan = plan_fracture(
        _single_root_trunk(10),
        FractureSettings(target_piece_count=2, output_stem="Trunk"),
    )

    assert plan.actual_piece_count == 2
    assert tuple(piece.base_face_indices for piece in plan.pieces) == (
        (0, 1, 2, 3, 4),
        (5, 6, 7, 8, 9),
    )
    assert plan.selected_cut_sites[-1].kind == "synthetic_mid_segment"
    assert plan.selected_cut_sites[-1].reason == "base_face_midpoint"
    assert not any(issue.code == "fracture_piece_count_clamped" for issue in plan.diagnostics)


def test_fracture_refines_existing_cut_order_when_target_count_grows() -> None:
    two_piece_plan = plan_fracture(_tree(), FractureSettings(target_piece_count=2, output_stem="Oak"))
    three_piece_plan = plan_fracture(_tree(), FractureSettings(target_piece_count=3, output_stem="Oak"))

    assert tuple(cut.joint_token for cut in two_piece_plan.selected_cut_sites) == ("bone_001",)
    assert tuple(cut.joint_token for cut in three_piece_plan.selected_cut_sites[:1]) == ("bone_001",)
    assert three_piece_plan.pieces[1].cut_joint_token == two_piece_plan.pieces[1].cut_joint_token


def test_wind_guided_fracture_falls_back_to_hierarchy_when_group_zero_is_missing() -> None:
    tree = _tree()
    tree_without_wind_groups = replace(
        tree,
        skeleton=tuple(
            replace(joint, generator_label=None, generator_level=None)
            for joint in tree.skeleton
        ),
    )

    plan = plan_fracture(tree_without_wind_groups, FractureSettings(target_piece_count=3, output_stem="Oak"))

    assert plan.actual_piece_count == 3
    assert plan.main_axis_joint_tokens == ("root", "bone_001", "bone_002")
    assert any(issue.code == "fracture_wind_guidance_missing" for issue in plan.diagnostics)


def test_fracture_clamps_down_instead_of_emitting_pieces_without_base_faces() -> None:
    plan = plan_fracture(_tree(), FractureSettings(target_piece_count=20, output_stem="Oak"))

    assert plan.actual_piece_count == 5
    assert all(piece.base_face_indices for piece in plan.pieces)
    assert any(issue.code == "fracture_piece_count_clamped" for issue in plan.diagnostics)


def test_fracture_fails_loudly_without_base_mesh_skinning() -> None:
    tree = _tree()
    broken_base_mesh = replace(
        tree.base_mesh,
        skel_joint_indices=(),
        skel_joint_weights=(),
        skel_element_size=0,
    )

    with pytest.raises(FractureError, match="base mesh skinning"):
        plan_fracture(replace(tree, base_mesh=broken_base_mesh), FractureSettings(target_piece_count=2))


def test_pure_hierarchy_fracture_does_not_require_wind_groups() -> None:
    tree = _tree()
    tree_without_wind_groups = replace(
        tree,
        skeleton=tuple(
            replace(joint, generator_label=None, generator_level=None)
            for joint in tree.skeleton
        ),
    )

    plan = plan_fracture(
        tree_without_wind_groups,
        FractureSettings(method=FRACTURE_METHOD_PURE_HIERARCHY, target_piece_count=3, output_stem="Oak"),
    )

    assert plan.main_axis_joint_tokens == ("root", "bone_001", "bone_002")
    assert tuple(cut.joint_token for cut in plan.selected_cut_sites) == ("bone_001", "bone_003")
    assert not any(issue.code == "fracture_wind_guidance_missing" for issue in plan.diagnostics)


def test_branch_base_greedy_fracture_starts_at_large_branch_roots() -> None:
    plan = plan_fracture(
        _tree(),
        FractureSettings(method=FRACTURE_METHOD_BRANCH_BASE_GREEDY, target_piece_count=2, output_stem="Oak"),
    )

    assert plan.actual_piece_count == 2
    assert tuple(cut.reason for cut in plan.selected_cut_sites) == ("branch_base",)
    assert tuple(piece.cut_joint_token for piece in plan.pieces[1:]) == ("bone_003",)
