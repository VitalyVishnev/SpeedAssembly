from __future__ import annotations

from dataclasses import replace

from xml_to_usda.fracture_collision import (
    FractureCollisionMode,
    FractureCollisionSettings,
    build_fracture_collision_meshes,
)
from xml_to_usda.fracture_service import FracturePiece
from xml_to_usda.models import (
    ExportMetadata,
    InstanceBinding,
    MeshData,
    Prototype,
    PrototypeIdentity,
    Quaternion,
    RepeatedPartInstance,
    TreeAsset,
    Vector3,
)
from xml_to_usda.models import Joint, Matrix4d


def _mesh() -> MeshData:
    return MeshData(
        name="Base",
        points=(
            Vector3(-1.0, 0.0, 0.0),
            Vector3(1.0, 0.0, 0.0),
            Vector3(0.0, 2.0, 0.0),
            Vector3(0.0, 0.0, 2.0),
        ),
        face_vertex_counts=(3, 3, 3, 3),
        face_vertex_indices=(0, 1, 2, 0, 1, 3, 0, 2, 3, 1, 2, 3),
    )


def _tree() -> TreeAsset:
    return TreeAsset(
        metadata=ExportMetadata(source_path="tree.xml", source_version=None),
        materials=(),
        source_objects=(),
        base_mesh=_mesh(),
        skeleton=(),
        assembly_parts=(),
    )


def _piece() -> FracturePiece:
    return FracturePiece(
        index=0,
        name="Tree_Piece_00",
        is_root_piece=True,
        cut_joint_token=None,
        joint_tokens=(),
        base_face_indices=(0, 1, 2, 3),
        repeated_part_indices=(),
        repeated_part_names=(),
    )


def _capsule_tree() -> TreeAsset:
    mesh = MeshData(
        name="Base",
        points=(
            Vector3(0.0, 0.0, 0.0),
            Vector3(0.2, 0.0, 0.0),
            Vector3(0.0, 0.2, 0.0),
            Vector3(0.0, 1.0, 0.0),
            Vector3(0.2, 1.0, 0.0),
            Vector3(0.0, 1.2, 0.0),
            Vector3(0.0, 2.0, 0.0),
            Vector3(0.2, 2.0, 0.0),
            Vector3(0.0, 2.2, 0.0),
        ),
        face_vertex_counts=(3, 3, 3),
        face_vertex_indices=(0, 1, 2, 3, 4, 5, 6, 7, 8),
        skel_joint_indices=(1, 1, 1, 2, 2, 2, 3, 3, 3),
        skel_joint_weights=(1.0,) * 9,
        skel_element_size=1,
    )
    skeleton = (
        Joint("root", bind_transform=Matrix4d.from_translation(Vector3(0.0, 0.0, 0.0))),
        Joint("bone_1", parent="root", bind_transform=Matrix4d.from_translation(Vector3(0.0, 1.0, 0.0))),
        Joint("bone_2", parent="bone_1", bind_transform=Matrix4d.from_translation(Vector3(0.0, 2.0, 0.0))),
        Joint("bone_3", parent="bone_2", bind_transform=Matrix4d.from_translation(Vector3(0.0, 3.0, 0.0))),
    )
    return TreeAsset(
        metadata=ExportMetadata(source_path="tree.xml", source_version=None),
        materials=(),
        source_objects=(),
        base_mesh=mesh,
        skeleton=skeleton,
        assembly_parts=(),
    )


def _capsule_piece() -> FracturePiece:
    return FracturePiece(
        index=0,
        name="Tree_Piece_00",
        is_root_piece=True,
        cut_joint_token=None,
        joint_tokens=("root", "bone_1", "bone_2", "bone_3"),
        base_face_indices=(0, 1, 2),
        repeated_part_indices=(),
        repeated_part_names=(),
    )


def _capsule_tree_with_bone_end() -> TreeAsset:
    tree = _capsule_tree()
    tip = Vector3(0.0, 4.0, 0.0)
    skeleton = tuple(
        replace(joint, bind_end_transform=Matrix4d.from_translation(tip)) if joint.name == "bone_3" else joint
        for joint in tree.skeleton
    )
    return replace(
        tree,
        skeleton=skeleton,
    )


def _uneven_capsule_tree() -> TreeAsset:
    tree = _capsule_tree()
    skeleton = (
        Joint("root", bind_transform=Matrix4d.from_translation(Vector3(0.0, 0.0, 0.0))),
        Joint("short", parent="root", bind_transform=Matrix4d.from_translation(Vector3(0.0, 1.0, 0.0))),
        Joint("long", parent="short", bind_transform=Matrix4d.from_translation(Vector3(0.0, 4.0, 0.0))),
    )
    return replace(tree, skeleton=skeleton)


def _uneven_capsule_piece() -> FracturePiece:
    return replace(_capsule_piece(), joint_tokens=("root", "short", "long"))


def _y_capsule_tree() -> TreeAsset:
    mesh = MeshData(
        name="Base",
        points=(
            Vector3(0.0, 0.0, 0.0),
            Vector3(0.1, 0.0, 0.0),
            Vector3(0.0, 0.2, 0.0),
            Vector3(0.0, 1.0, 0.0),
            Vector3(0.1, 1.0, 0.0),
            Vector3(0.0, 1.2, 0.0),
            Vector3(0.0, 2.0, 0.0),
            Vector3(0.1, 2.0, 0.0),
            Vector3(0.0, 2.2, 0.0),
            Vector3(-1.0, 3.0, 0.0),
            Vector3(-0.9, 3.0, 0.0),
            Vector3(-1.0, 3.2, 0.0),
            Vector3(1.0, 3.0, 0.0),
            Vector3(1.1, 3.0, 0.0),
            Vector3(1.0, 3.2, 0.0),
        ),
        face_vertex_counts=(3, 3, 3, 3, 3),
        face_vertex_indices=(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14),
        skel_joint_indices=(0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4),
        skel_joint_weights=(1.0,) * 15,
        skel_element_size=1,
    )
    skeleton = (
        Joint("root", bind_transform=Matrix4d.from_translation(Vector3(0.0, 0.0, 0.0))),
        Joint("trunk", parent="root", bind_transform=Matrix4d.from_translation(Vector3(0.0, 1.0, 0.0))),
        Joint("fork", parent="trunk", bind_transform=Matrix4d.from_translation(Vector3(0.0, 2.0, 0.0))),
        Joint("left", parent="fork", bind_transform=Matrix4d.from_translation(Vector3(-1.0, 3.0, 0.0))),
        Joint("right", parent="fork", bind_transform=Matrix4d.from_translation(Vector3(1.0, 3.0, 0.0))),
    )
    return TreeAsset(
        metadata=ExportMetadata(source_path="tree.xml", source_version=None),
        materials=(),
        source_objects=(),
        base_mesh=mesh,
        skeleton=skeleton,
        assembly_parts=(),
    )


def _y_capsule_piece() -> FracturePiece:
    return FracturePiece(
        index=0,
        name="Tree_Piece_00",
        is_root_piece=True,
        cut_joint_token=None,
        joint_tokens=("root", "trunk", "fork", "left", "right"),
        base_face_indices=(0, 1, 2, 3, 4),
        repeated_part_indices=(),
        repeated_part_names=(),
    )


def test_sphere_collision_scales_radius_after_fit() -> None:
    meshes = build_fracture_collision_meshes(
        _tree(),
        _piece(),
        FractureCollisionSettings(
            enabled=True,
            mode=FractureCollisionMode.SPHERE,
            sphere_radius_scale=0.5,
        ),
        render_mesh_name="SM_Tree_Piece_00_BaseMesh",
    )

    assert len(meshes) == 1
    assert meshes[0].name == "USP_SM_Tree_Piece_00_BaseMesh_00"
    ys = [point.y for point in meshes[0].points]
    assert max(ys) - min(ys) < 3.0


def test_convex_collision_builds_single_ucx_mesh_without_external_qhull() -> None:
    meshes = build_fracture_collision_meshes(
        _tree(),
        _piece(),
        FractureCollisionSettings(enabled=True, mode=FractureCollisionMode.CONVEX, convex_max_vertices=4),
        render_mesh_name="SM_Tree_Piece_00_BaseMesh",
    )

    assert len(meshes) == 1
    assert meshes[0].name == "UCX_SM_Tree_Piece_00_BaseMesh_00"
    assert len(meshes[0].points) <= 8
    assert meshes[0].face_vertex_counts


def test_capsule_collision_simplify_zero_builds_one_capsule_per_skeleton_edge() -> None:
    meshes = build_fracture_collision_meshes(
        _capsule_tree(),
        _capsule_piece(),
        FractureCollisionSettings(
            enabled=True,
            mode=FractureCollisionMode.CAPSULE,
            capsule_simplify=0,
        ),
        render_mesh_name="SM_Tree_Piece_00_BaseMesh",
    )

    assert len(meshes) == 3
    assert meshes[0].name == "UCP_SM_Tree_Piece_00_BaseMesh_00"


def test_capsule_collision_extends_terminal_joint_to_bone_end() -> None:
    meshes = build_fracture_collision_meshes(
        _capsule_tree_with_bone_end(),
        _capsule_piece(),
        FractureCollisionSettings(
            enabled=True,
            mode=FractureCollisionMode.CAPSULE,
            capsule_simplify=100,
            capsule_scale=0.5,
        ),
        render_mesh_name="SM_Tree_Piece_00_BaseMesh",
    )

    assert max(point.y for mesh in meshes for point in mesh.points) > 3.9


def test_capsule_collision_mesh_has_rounded_caps() -> None:
    mesh = build_fracture_collision_meshes(
        _capsule_tree(),
        _capsule_piece(),
        FractureCollisionSettings(
            enabled=True,
            mode=FractureCollisionMode.CAPSULE,
            capsule_simplify=100,
            capsule_scale=0.5,
        ),
        render_mesh_name="SM_Tree_Piece_00_BaseMesh",
    )[0]

    ys = [point.y for point in mesh.points]

    assert len(mesh.points) > 30
    assert min(ys) < 0.0
    assert max(ys) > 2.2


def test_capsule_collision_falls_back_to_one_capsule_without_piece_joints() -> None:
    meshes = build_fracture_collision_meshes(
        _tree(),
        _piece(),
        FractureCollisionSettings(
            enabled=True,
            mode=FractureCollisionMode.CAPSULE,
        ),
        render_mesh_name="SM_Tree_Piece_00_BaseMesh",
    )

    assert len(meshes) == 1
    assert meshes[0].name == "UCP_SM_Tree_Piece_00_BaseMesh_00"
    assert meshes[0].points


def test_capsule_simplify_uses_ordered_skeleton_paths() -> None:
    meshes = build_fracture_collision_meshes(
        _y_capsule_tree(),
        _y_capsule_piece(),
        FractureCollisionSettings(
            enabled=True,
            mode=FractureCollisionMode.CAPSULE,
            capsule_simplify=100,
            capsule_scale=0.75,
        ),
        render_mesh_name="SM_Tree_Piece_00_BaseMesh",
    )

    axes = [
        (
            abs(mesh.points[-1].x - mesh.points[0].x),
            abs(mesh.points[-1].y - mesh.points[0].y),
        )
        for mesh in meshes
    ]

    assert len(meshes) == 2
    assert axes[0][0] > 0.8
    assert axes[0][1] > 2.8
    assert axes[1][0] > 0.8
    assert axes[1][1] > 0.8


def test_capsule_collision_ignores_mesh_outliers_when_setting_radius() -> None:
    tree = _capsule_tree()
    baseline = build_fracture_collision_meshes(
        tree,
        _capsule_piece(),
        FractureCollisionSettings(
            enabled=True,
            mode=FractureCollisionMode.CAPSULE,
            capsule_scale=0.75,
        ),
        render_mesh_name="SM_Tree_Piece_00_BaseMesh",
    )
    mesh = tree.base_mesh
    assert mesh is not None
    outlier_index = len(mesh.points)
    tree = replace(
        tree,
        base_mesh=replace(
            mesh,
            points=(*mesh.points, Vector3(9.0, 0.5, 0.0)),
            face_vertex_counts=(*mesh.face_vertex_counts, 3),
            face_vertex_indices=(*mesh.face_vertex_indices, outlier_index, 0, 1),
            skel_joint_indices=(*mesh.skel_joint_indices, 1),
            skel_joint_weights=(*mesh.skel_joint_weights, 1.0),
        ),
    )

    meshes = build_fracture_collision_meshes(
        tree,
        replace(_capsule_piece(), base_face_indices=(0, 1, 2, 3)),
        FractureCollisionSettings(
            enabled=True,
            mode=FractureCollisionMode.CAPSULE,
            capsule_scale=0.75,
        ),
        render_mesh_name="SM_Tree_Piece_00_BaseMesh",
    )

    baseline_width = max(point.x for mesh in baseline for point in mesh.points) - min(
        point.x for mesh in baseline for point in mesh.points
    )
    outlier_width = max(point.x for mesh in meshes for point in mesh.points) - min(
        point.x for mesh in meshes for point in mesh.points
    )

    assert outlier_width == baseline_width


def test_capsule_scale_by_length_makes_long_segments_thicker() -> None:
    meshes = build_fracture_collision_meshes(
        _uneven_capsule_tree(),
        _uneven_capsule_piece(),
        FractureCollisionSettings(
            enabled=True,
            mode=FractureCollisionMode.CAPSULE,
            capsule_simplify=0,
            capsule_scale=1.0,
            capsule_scale_by_length=1.0,
        ),
        render_mesh_name="SM_Tree_Piece_00_BaseMesh",
    )

    widths = [
        max(point.x for point in mesh.points) - min(point.x for point in mesh.points)
        for mesh in meshes
    ]

    assert len(widths) == 2
    assert widths[1] > widths[0]


def test_collision_sampling_limits_repeated_part_transforms(monkeypatch) -> None:
    import xml_to_usda.fracture_collision as collision

    repeated_mesh = MeshData(
        name="Leaf",
        points=tuple(Vector3(float(index), 0.0, 0.0) for index in range(10_000)),
        face_vertex_counts=(),
        face_vertex_indices=(),
    )
    tree = TreeAsset(
        metadata=ExportMetadata(source_path="tree.xml", source_version=None),
        materials=(),
        source_objects=(),
        base_mesh=_mesh(),
        skeleton=(),
        assembly_parts=(
            RepeatedPartInstance(
                name="Leaf_0",
                prototype_key="Leaf",
                position=Vector3(0.0, 0.0, 0.0),
                orientation=Quaternion(1.0, 0.0, 0.0, 0.0),
                scale=Vector3(1.0, 1.0, 1.0),
                binding=InstanceBinding(("root",), (1.0,)),
                source_object_id=None,
                source_mesh_id=1,
            ),
        ),
        prototypes=(
            Prototype(
                identity=PrototypeIdentity("Leaf", "Leaf"),
                mesh=repeated_mesh,
                source_key="Leaf",
                source_mesh_id=1,
                source_name="Leaf",
            ),
        ),
    )
    piece = FracturePiece(
        index=0,
        name="Tree_Piece_00",
        is_root_piece=True,
        cut_joint_token=None,
        joint_tokens=(),
        base_face_indices=(0, 1, 2, 3),
        repeated_part_indices=(0,),
        repeated_part_names=("Leaf_0",),
    )
    calls = 0
    original = collision._transform_point

    def counted_transform(*args):
        nonlocal calls
        calls += 1
        return original(*args)

    monkeypatch.setattr(collision, "_transform_point", counted_transform)

    collision.build_fracture_collision_meshes(
        tree,
        piece,
        FractureCollisionSettings(
            enabled=True,
            mode=FractureCollisionMode.SPHERE,
            point_sample_limit=16,
        ),
        render_mesh_name="SM_Tree_Piece_00_BaseMesh",
    )

    assert calls < 16
