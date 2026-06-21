from __future__ import annotations

from dataclasses import replace

from xml_to_usda.fracture_collision import (
    FractureCollisionMode,
    FractureCollisionSettings,
    build_fracture_collision_meshes,
)
from xml_to_usda.fracture_service import FracturePiece
from xml_to_usda.models import ExportMetadata, InstanceBinding, MeshData, Prototype, PrototypeIdentity, Quaternion, RepeatedPartInstance, TreeAsset, Vector3
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


def test_capsule_collision_respects_temporary_max_count_knob() -> None:
    meshes = build_fracture_collision_meshes(
        _capsule_tree(),
        _capsule_piece(),
        FractureCollisionSettings(
            enabled=True,
            mode=FractureCollisionMode.CAPSULE,
            capsule_max_count=1,
            capsule_min_radius_ratio=0.1,
            capsule_radius_padding=0.2,
        ),
        render_mesh_name="SM_Tree_Piece_00_BaseMesh",
    )

    assert len(meshes) == 1
    assert meshes[0].name == "UCP_SM_Tree_Piece_00_BaseMesh_00"


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


def test_capsule_collision_ignores_single_wide_outlier_when_fitting_radius() -> None:
    tree = _capsule_tree()
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
            capsule_min_radius_ratio=0.05,
            capsule_radius_padding=0.0,
        ),
        render_mesh_name="SM_Tree_Piece_00_BaseMesh",
    )

    xs = [point.x for mesh in meshes for point in mesh.points]

    assert max(xs) - min(xs) < 1.0


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
