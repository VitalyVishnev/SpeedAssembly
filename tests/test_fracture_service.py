from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

import xml_to_usda.fracture_service as fracture_service
from xml_to_usda.fracture_service import (
    FRACTURE_METHOD_MANUAL_FRACTURING,
    FractureCutSite,
    FractureError,
    FractureSettings,
    format_manual_segment_cut_token,
    plan_fracture,
)


def test_selected_cut_owners_resolve_by_single_parent_walk() -> None:
    joints = (
        _joint("root", 0, None, 0.0, 0),
        _joint("branch", 1, "root", 1.0, 1),
        _joint("twig", 2, "branch", 2.0, 2),
        _joint("tip", 3, "twig", 3.0, 3),
    )
    graph = fracture_service._build_skeleton_graph(joints)
    owners = fracture_service._selected_cut_owner_by_joint(
        graph,
        [
            FractureCutSite("branch", "joint", "test"),
            FractureCutSite("tip", "joint", "test"),
        ],
    )

    assert owners == {"root": None, "branch": "branch", "twig": "branch", "tip": "tip"}
from xml_to_usda.models import (
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


def _base_mesh_for_joint_faces(
    joint_indices: tuple[int, ...],
    *,
    face_ys: tuple[float, ...] | None = None,
) -> MeshData:
    points: list[Vector3] = []
    face_vertex_counts: list[int] = []
    face_vertex_indices: list[int] = []
    skel_joint_indices: list[int] = []
    for face_index, joint_index in enumerate(joint_indices):
        first_point = len(points)
        x = float(face_index)
        y = 0.0 if face_ys is None else face_ys[face_index]
        points.extend(
            (
                Vector3(x, y, 0.0),
                Vector3(x + 0.4, y, 0.0),
                Vector3(x, y + 0.4, 0.0),
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


def _vertical_strip_mesh(face_ys: tuple[float, ...], joint_index: int) -> MeshData:
    points: list[Vector3] = []
    face_vertex_counts: list[int] = []
    face_vertex_indices: list[int] = []
    skel_joint_indices: list[int] = []
    for y in face_ys:
        first_point = len(points)
        points.extend(
            (
                Vector3(-0.2, y, 0.0),
                Vector3(0.2, y, 0.0),
                Vector3(-0.2, y + 0.2, 0.0),
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


def _repeated_part_at(name: str, joint_token: str, x: float, *, prototype_key: str = "Mesh_1") -> RepeatedPartInstance:
    return RepeatedPartInstance(
        name=name,
        prototype_key=prototype_key,
        position=Vector3(x, 0.0, 0.0),
        orientation=Quaternion(1.0, 0.0, 0.0, 0.0),
        scale=Vector3(1.0, 1.0, 1.0),
        binding=InstanceBinding(joint_tokens=(joint_token,), weights=(1.0,)),
        source_object_id=None,
        source_mesh_id=1,
    )


def _box_prototype(source_key: str = "Mesh_1", *, half_extent: float = 0.1) -> Prototype:
    mesh = MeshData(
        name=source_key,
        points=(
            Vector3(-half_extent, -half_extent, -half_extent),
            Vector3(half_extent, half_extent, half_extent),
        ),
        face_vertex_counts=(),
        face_vertex_indices=(),
    )
    return Prototype(
        identity=PrototypeIdentity(source_key=source_key, prim_name=source_key),
        mesh=mesh,
        source_key=source_key,
        source_mesh_id=1,
        source_name=source_key,
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
        base_mesh=_base_mesh_for_joint_faces((0, 1, 2, 3, 4), face_ys=(0.0, 1.0, 2.0, 1.1, 1.5)),
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


def _simple_segment_trunk() -> TreeAsset:
    skeleton = (
        _joint("root", 0, None, 0.0, 0),
        _joint("top", 1, "root", 10.0, 0),
    )
    return TreeAsset(
        metadata=ExportMetadata(source_path="trunk.xml", source_version=None),
        materials=(),
        source_objects=(),
        base_mesh=_vertical_strip_mesh((1.0, 3.0, 6.0, 8.0), joint_index=0),
        skeleton=skeleton,
        assembly_parts=(),
    )


def _automatic_branch_segment_tree() -> TreeAsset:
    skeleton = (
        _joint("root", 0, None, 0.0, 0),
        _joint("trunk", 1, "root", 20.0, 0),
        _joint("branch", 2, "root", 10.0, 1),
    )
    return TreeAsset(
        metadata=ExportMetadata(source_path="automatic_branch.xml", source_version=None),
        materials=(),
        source_objects=(),
        base_mesh=_base_mesh_for_joint_faces((0, 2, 2, 2), face_ys=(0.0, 2.0, 5.0, 8.0)),
        skeleton=skeleton,
        assembly_parts=(),
    )


def test_auto_branch_cut_offset_changes_flat_piece_ownership() -> None:
    tree = _automatic_branch_segment_tree()

    near_start = plan_fracture(tree, FractureSettings(target_piece_count=1, auto_branch_cut_offset=0.30))
    near_end = plan_fracture(tree, FractureSettings(target_piece_count=1, auto_branch_cut_offset=0.70))

    assert near_start.selected_cut_sites[0].kind == "auto_segment"
    assert near_start.selected_cut_sites[0].segment_t == 0.30
    assert tuple(piece.base_face_indices for piece in near_start.pieces) == ((0, 1), (2, 3))
    assert tuple(piece.base_face_indices for piece in near_end.pieces) == ((0, 1, 2), (3,))


def test_manual_fracturing_auto_fill_keeps_root_first_and_assigns_repeated_parts_by_skeleton_owner() -> None:
    plan = plan_fracture(
        _tree(),
        FractureSettings(
            target_piece_count=2,
            output_stem="Oak",
        ),
    )

    assert plan.method == FRACTURE_METHOD_MANUAL_FRACTURING
    assert tuple(piece.name for piece in plan.pieces) == ("Oak_fracture_00", "Oak_fracture_01", "Oak_fracture_02")
    assert plan.pieces[0].is_root_piece is True
    assert plan.pieces[0].base_face_indices
    assert plan.pieces[1].cut_joint_token == "bone_003"
    assert plan.pieces[2].cut_joint_token == "bone_004"
    assert plan.pieces[0].repeated_part_names == ("TopLeaves",)
    assert plan.pieces[2].repeated_part_names == ("BranchLeaves",)
    assert all(piece.base_face_indices for piece in plan.pieces)
    assert plan.actual_piece_count == 3


def test_fracture_clamps_branch_count_when_hierarchy_has_no_safe_branch_base() -> None:
    plan = plan_fracture(
        _single_root_trunk(10),
        FractureSettings(target_piece_count=2, output_stem="Trunk"),
    )

    assert plan.actual_piece_count == 1
    assert tuple(piece.base_face_indices for piece in plan.pieces) == (tuple(range(10)),)
    assert not plan.selected_cut_sites
    assert any(issue.code == "fracture_branch_count_clamped" for issue in plan.diagnostics)


def test_fracture_does_not_synthetic_split_repeated_parts_without_safe_branch_base() -> None:
    tree = replace(
        _single_root_trunk(4),
        assembly_parts=(
            _repeated_part_at("LeftLeaves", "root", 0.5),
            _repeated_part_at("RightLeaves", "root", 3.0),
        ),
        prototypes=(_box_prototype(),),
    )

    plan = plan_fracture(tree, FractureSettings(target_piece_count=2, output_stem="Trunk"))

    assert tuple(piece.base_face_indices for piece in plan.pieces) == ((0, 1, 2, 3),)
    assert tuple(piece.repeated_part_names for piece in plan.pieces) == (("LeftLeaves", "RightLeaves"),)
    assert any(issue.code == "fracture_branch_count_clamped" for issue in plan.diagnostics)


def test_fracture_refines_existing_cut_order_when_target_count_grows() -> None:
    one_branch_plan = plan_fracture(_tree(), FractureSettings(target_piece_count=1, output_stem="Oak"))
    two_branch_plan = plan_fracture(_tree(), FractureSettings(target_piece_count=2, output_stem="Oak"))

    assert tuple(cut.joint_token for cut in one_branch_plan.selected_cut_sites) == ("bone_003",)
    assert tuple(cut.joint_token for cut in two_branch_plan.selected_cut_sites) == ("bone_003", "bone_004")
    assert "bone_003" in tuple(piece.cut_joint_token for piece in two_branch_plan.pieces)


def test_legacy_fracture_method_ids_fail_loudly() -> None:
    tree = _tree()
    legacy_settings = SimpleNamespace(
        method="pure_hierarchy",
        target_piece_count=3,
        output_stem="Oak",
        pinned_cut_joint_tokens=(),
        generate_caps=False,
        preserve_trunk_bias=0.5,
        force_stump_piece=False,
    )

    with pytest.raises(FractureError, match="Legacy fracture method is no longer supported"):
        plan_fracture(tree, legacy_settings)  # type: ignore[arg-type]


def test_fracture_clamps_down_instead_of_emitting_pieces_without_base_faces() -> None:
    plan = plan_fracture(_tree(), FractureSettings(target_piece_count=20, output_stem="Oak"))

    assert plan.actual_piece_count == 3
    assert all(piece.base_face_indices for piece in plan.pieces)
    assert any(issue.code == "fracture_branch_count_clamped" for issue in plan.diagnostics)


def test_fracture_skips_empty_source_faces_before_piece_planning() -> None:
    tree = _tree()
    base_mesh = tree.base_mesh
    mesh_with_empty_face = replace(
        base_mesh,
        face_vertex_counts=base_mesh.face_vertex_counts[:2] + (0,) + base_mesh.face_vertex_counts[2:],
    )

    plan = plan_fracture(
        replace(tree, base_mesh=mesh_with_empty_face),
        FractureSettings(target_piece_count=3, output_stem="Oak"),
    )

    assert plan.actual_piece_count == 3
    assert all(piece.base_face_indices for piece in plan.pieces)
    assert all(2 not in piece.base_face_indices for piece in plan.pieces)
    assert any(3 in piece.base_face_indices for piece in plan.pieces)


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


def test_fracture_fails_loudly_when_base_mesh_topology_is_not_materialized() -> None:
    tree = _tree()
    broken_base_mesh = replace(tree.base_mesh)
    object.__setattr__(broken_base_mesh, "face_vertex_counts", (count for count in tree.base_mesh.face_vertex_counts))

    with pytest.raises(FractureError, match="Base mesh face_vertex_counts must be a materialized tuple"):
        plan_fracture(replace(tree, base_mesh=broken_base_mesh), FractureSettings(target_piece_count=2))


def test_auto_fracture_prefers_branch_bases_without_trunk_midpoint() -> None:
    plan = plan_fracture(
        _tree(),
        FractureSettings(target_piece_count=2, output_stem="Oak", preserve_trunk_bias=1.0),
    )

    assert plan.actual_piece_count == 3
    assert tuple(cut.reason for cut in plan.selected_cut_sites) == ("auto_branch_length", "auto_branch_length")
    assert tuple(piece.cut_joint_token for piece in plan.pieces[1:]) == ("bone_003", "bone_004")


def test_preserve_trunk_bias_no_longer_enables_main_axis_auto_cuts() -> None:
    plan = plan_fracture(
        _tree(),
        FractureSettings(target_piece_count=2, output_stem="Oak", preserve_trunk_bias=0.0),
    )

    assert plan.actual_piece_count == 3
    assert tuple(cut.reason for cut in plan.selected_cut_sites) == ("auto_branch_length", "auto_branch_length")
    assert "bone_001" not in tuple(piece.cut_joint_token for piece in plan.pieces)


def test_manual_pinned_cuts_apply_first_and_allow_nested_fracture_pieces() -> None:
    plan = plan_fracture(
        _tree(),
        FractureSettings(
            target_piece_count=3,
            output_stem="Oak",
            pinned_cut_joint_tokens=("bone_001", "bone_003"),
        ),
    )

    assert plan.actual_piece_count == 4
    assert tuple(cut.joint_token for cut in plan.selected_cut_sites) == ("bone_001", "bone_003", "bone_004")
    assert tuple(cut.reason for cut in plan.selected_cut_sites) == (
        "manual_pinned",
        "manual_pinned",
        "auto_branch_length",
    )
    assert tuple(piece.cut_joint_token for piece in plan.pieces[1:]) == ("bone_001", "bone_003", "bone_004")
    assert plan.pieces[1].joint_tokens == ("bone_001", "bone_002")
    assert plan.pieces[2].joint_tokens == ("bone_003",)
    assert plan.pieces[3].joint_tokens == ("bone_004",)


def test_manual_segment_cut_splits_base_faces_between_joints_by_cut_position() -> None:
    plan = plan_fracture(
        _simple_segment_trunk(),
        FractureSettings(
            target_piece_count=2,
            output_stem="Trunk",
            pinned_cut_joint_tokens=(format_manual_segment_cut_token("root", "top", 0.5),),
        ),
    )

    assert plan.actual_piece_count == 2
    assert tuple(cut.kind for cut in plan.selected_cut_sites) == ("manual_segment",)
    assert tuple(piece.base_face_indices for piece in plan.pieces) == ((0, 1), (2, 3))
    assert plan.pieces[1].cut_joint_token == "root->top@0.500"
    assert plan.pieces[1].joint_tokens == ("top",)


def test_manual_segment_face_ownership_uses_physical_child_bone() -> None:
    root = _joint("root", 0, None, 0.0, 0)
    child = Joint(
        name="branch",
        source_id=1,
        parent="root",
        bind_transform=Matrix4d.from_translation(Vector3(1.0, 2.0, 0.0)),
        rest_transform=Matrix4d.from_translation(Vector3(1.0, 2.0, 0.0)),
        bind_end_transform=Matrix4d.from_translation(Vector3(1.0, 10.0, 0.0)),
    )
    sibling = Joint(
        name="sibling",
        source_id=2,
        parent="root",
        bind_transform=Matrix4d.from_translation(Vector3(-1.0, 2.0, 0.0)),
        rest_transform=Matrix4d.from_translation(Vector3(-1.0, 2.0, 0.0)),
        bind_end_transform=Matrix4d.from_translation(Vector3(-1.0, 10.0, 0.0)),
    )
    mesh = _vertical_strip_mesh((3.0, 5.0, 7.0, 9.0, 9.0), joint_index=0)
    mesh = replace(mesh, skel_joint_indices=mesh.skel_joint_indices[:-3] + (2, 2, 2))
    tree = TreeAsset(
        metadata=ExportMetadata(source_path="connector.xml", source_version=None),
        materials=(),
        source_objects=(),
        base_mesh=mesh,
        skeleton=(root, child, sibling),
        assembly_parts=(),
    )

    plan = plan_fracture(
        tree,
        FractureSettings(
            target_piece_count=0,
            pinned_cut_joint_tokens=(format_manual_segment_cut_token("root", "branch", 0.5),),
        ),
    )

    assert tuple(piece.base_face_indices for piece in plan.pieces) == ((0, 1, 4), (2, 3))


def test_auto_branch_cut_only_claims_parent_faces_influenced_by_its_child_subtree() -> None:
    root = _joint("root", 0, None, 0.0, 0)
    branch = Joint(
        name="branch",
        source_id=1,
        parent="root",
        generator_level=1,
        bind_transform=Matrix4d.from_translation(Vector3(0.0, 1.0, 0.0)),
        rest_transform=Matrix4d.from_translation(Vector3(0.0, 10.0, 0.0)),
        bind_end_transform=Matrix4d.from_translation(Vector3(0.0, 10.0, 0.0)),
    )
    sibling = Joint(
        name="sibling",
        source_id=2,
        parent="root",
        generator_level=1,
        bind_transform=Matrix4d.from_translation(Vector3(4.0, 1.0, 0.0)),
        rest_transform=Matrix4d.from_translation(Vector3(4.0, 8.0, 0.0)),
        bind_end_transform=Matrix4d.from_translation(Vector3(4.0, 8.0, 0.0)),
    )
    mesh = _vertical_strip_mesh((1.0, 7.0, 8.0, 7.0, 8.0), joint_index=0)
    face_influences = (
        ((0, 0), (1.0, 0.0)),
        ((0, 1), (0.6, 0.4)),
        ((1, 1), (1.0, 0.0)),
        ((0, 2), (0.6, 0.4)),
        ((2, 2), (1.0, 0.0)),
    )
    mesh = replace(
        mesh,
        skel_joint_indices=tuple(
            joint
            for (joints, _weights) in face_influences
            for _point in range(3)
            for joint in joints
        ),
        skel_joint_weights=tuple(
            weight
            for (_joints, weights) in face_influences
            for _point in range(3)
            for weight in weights
        ),
        skel_element_size=2,
    )
    tree = TreeAsset(
        metadata=ExportMetadata(source_path="sibling-collars.xml", source_version=None),
        materials=(),
        source_objects=(),
        base_mesh=mesh,
        skeleton=(root, branch, sibling),
        assembly_parts=(),
    )

    plan = plan_fracture(
        tree,
        FractureSettings(target_piece_count=1, auto_branch_cut_offset=0.5),
    )

    assert tuple(cut.child_joint_token for cut in plan.selected_cut_sites) == ("sibling",)
    assert tuple(piece.base_face_indices for piece in plan.pieces) == ((0, 1, 2), (3, 4))


def test_manual_segment_cuts_on_same_edge_must_not_be_too_close() -> None:
    with pytest.raises(FractureError, match="same skeleton edge must be at least 0.02 apart"):
        plan_fracture(
            _simple_segment_trunk(),
            FractureSettings(
                target_piece_count=3,
                output_stem="Trunk",
                pinned_cut_joint_tokens=(
                    format_manual_segment_cut_token("root", "top", 0.50),
                    format_manual_segment_cut_token("root", "top", 0.51),
                ),
            ),
        )


def test_separated_manual_segment_cuts_on_same_edge_remain_valid() -> None:
    plan = plan_fracture(
        _simple_segment_trunk(),
        FractureSettings(
            target_piece_count=3,
            output_stem="Trunk",
            pinned_cut_joint_tokens=(
                format_manual_segment_cut_token("root", "top", 0.30),
                format_manual_segment_cut_token("root", "top", 0.70),
            ),
        ),
    )

    assert plan.actual_piece_count == 3
    assert tuple(piece.base_face_indices for piece in plan.pieces) == ((0,), (1, 2), (3,))


def test_stump_piece_uses_first_main_axis_child_joint_not_lowest_face_centroid() -> None:
    skeleton = (
        _joint("root", 0, None, 0.0, 0),
        _joint("top", 1, "root", 10.0, 0),
    )
    tree = TreeAsset(
        metadata=ExportMetadata(source_path="trunk.xml", source_version=None),
        materials=(),
        source_objects=(),
        base_mesh=_vertical_strip_mesh((1.0, 3.0, 6.0, 8.0), joint_index=0),
        skeleton=skeleton,
        assembly_parts=(),
    )
    base_mesh = replace(tree.base_mesh)
    object.__setattr__(base_mesh, "skel_joint_indices", (0,) * 6 + (1,) * 6)
    plan = plan_fracture(
        replace(tree, base_mesh=base_mesh),
        FractureSettings(
            target_piece_count=2,
            output_stem="Trunk",
            force_stump_piece=True,
        ),
    )

    assert plan.actual_piece_count == 2
    assert plan.selected_cut_sites[0].reason == "stump_piece"
    assert plan.selected_cut_sites[0].kind == "joint"
    assert plan.selected_cut_sites[0].joint_token == "top"
    assert tuple(piece.base_face_indices for piece in plan.pieces) == ((0, 1), (2, 3))


def test_automatic_branch_cuts_use_segment_ownership() -> None:
    plan = plan_fracture(
        _tree(),
        FractureSettings(
            target_piece_count=3,
            output_stem="Oak",
            force_stump_piece=True,
        ),
    )

    assert plan.actual_piece_count == 4
    assert all(cut.kind == "auto_segment" for cut in plan.selected_cut_sites[1:])


def test_manual_pinned_cuts_use_skeleton_order_and_auto_fill_after_pins() -> None:
    first = plan_fracture(
        _tree(),
        FractureSettings(
            target_piece_count=3,
            output_stem="Oak",
            pinned_cut_joint_tokens=("bone_003",),
        ),
    )
    second = plan_fracture(
        _tree(),
        FractureSettings(
            target_piece_count=3,
            output_stem="Oak",
            pinned_cut_joint_tokens=("bone_003", "bone_001"),
        ),
    )
    third = plan_fracture(
        _tree(),
        FractureSettings(
            target_piece_count=3,
            output_stem="Oak",
            pinned_cut_joint_tokens=("bone_001", "bone_003"),
        ),
    )

    assert tuple(piece.cut_joint_token for piece in first.pieces) == (None, "bone_003", "bone_004")
    assert tuple(piece.cut_joint_token for piece in second.pieces) == tuple(piece.cut_joint_token for piece in third.pieces)


def test_manual_pinned_cuts_preserve_manual_pieces_when_target_is_lower() -> None:
    plan = plan_fracture(
        _tree(),
        FractureSettings(
            target_piece_count=2,
            output_stem="Oak",
            pinned_cut_joint_tokens=("bone_001", "bone_003"),
        ),
    )

    assert plan.requested_piece_count == 2
    assert plan.actual_piece_count == 4
    assert tuple(piece.cut_joint_token for piece in plan.pieces) == (None, "bone_001", "bone_003", "bone_004")
    assert not any(issue.code == "fracture_manual_piece_count_exceeds_target" for issue in plan.diagnostics)


def test_manual_pinned_cuts_fail_loudly_for_missing_or_empty_cut_sites() -> None:
    tree = _tree()
    tree_with_empty_joint = replace(
        tree,
        skeleton=tree.skeleton + (_joint("bone_empty", 5, "bone_004", 2.4, 2),),
    )

    with pytest.raises(FractureError, match="missing skeleton joint bone_missing"):
        plan_fracture(
            tree,
            FractureSettings(
                target_piece_count=2,
                pinned_cut_joint_tokens=("bone_missing",),
            ),
        )

    with pytest.raises(FractureError, match="cannot produce a Fracture Piece with base mesh faces"):
        plan_fracture(
            tree_with_empty_joint,
            FractureSettings(
                target_piece_count=2,
                pinned_cut_joint_tokens=("bone_empty",),
            ),
        )


def test_fracture_settings_fail_loudly_for_invalid_manual_token_payload() -> None:
    with pytest.raises(FractureError, match="pinned cut joint tokens must be a tuple of strings"):
        plan_fracture(
            _tree(),
            FractureSettings(
                pinned_cut_joint_tokens=[].append,  # type: ignore[arg-type]
            ),
        )
