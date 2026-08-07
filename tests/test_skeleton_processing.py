from __future__ import annotations

import pytest
from dataclasses import replace

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
from xml_to_usda.skeleton_processing import _multiply, apply_dual_skinning, orient_skeleton_x
from xml_to_usda.usda_authoring import _render_base_animation


def _model() -> TreeAsset:
    root = Joint(
        name="root",
        bind_transform=Matrix4d.from_translation(Vector3(0.0, 0.0, 0.0)),
        rest_transform=Matrix4d.from_translation(Vector3(0.0, 0.0, 0.0)),
        bind_end_transform=Matrix4d.from_translation(Vector3(0.0, 2.0, 0.0)),
    )
    branch = Joint(
        name="branch",
        parent="root",
        bind_transform=Matrix4d.from_translation(Vector3(0.0, 2.0, 0.0)),
        rest_transform=Matrix4d.from_translation(Vector3(0.0, 2.0, 0.0)),
        bind_end_transform=Matrix4d.from_translation(Vector3(2.0, 4.0, 0.0)),
    )
    mesh = MeshData(
        name="Base",
        points=(Vector3(0.0, 2.0, 0.0), Vector3(1.0, 3.0, 0.0), Vector3(2.0, 4.0, 0.0)),
        face_vertex_counts=(3,),
        face_vertex_indices=(0, 1, 2),
        skel_joint_indices=(1, 1, 1),
        skel_joint_weights=(1.0, 1.0, 1.0),
        skel_element_size=1,
    )
    parts = tuple(
        RepeatedPartInstance(
            name=f"part_{index}",
            prototype_key="leaf",
            position=position,
            orientation=Quaternion(1.0, 0.0, 0.0, 0.0),
            scale=Vector3(1.0, 1.0, 1.0),
            binding=InstanceBinding(("branch",), (1.0,)),
            source_object_id="1",
            source_mesh_id=1,
        )
        for index, position in enumerate(mesh.points)
    )
    return TreeAsset(
        metadata=ExportMetadata(source_path="tree.xml", source_version=None),
        materials=(),
        source_objects=(),
        base_mesh=mesh,
        skeleton=(root, branch),
        assembly_parts=parts,
    )


def test_x_oriented_bones_point_local_x_from_start_to_end_and_author_animation_rotation() -> None:
    source = _model()
    result = replace(source, skeleton=orient_skeleton_x(source.skeleton))

    root_x = result.skeleton[0].bind_transform.rows[0][:3]
    branch_x = result.skeleton[1].bind_transform.rows[0][:3]
    assert root_x == pytest.approx((0.0, 1.0, 0.0))
    assert branch_x == pytest.approx((2**-0.5, 2**-0.5, 0.0))
    reconstructed = _multiply(result.skeleton[1].rest_transform, result.skeleton[0].bind_transform)
    for actual_row, expected_row in zip(reconstructed.rows, result.skeleton[1].bind_transform.rows, strict=True):
        assert actual_row == pytest.approx(expected_row)
    assert "quath[] rotations = [(1, 0, 0, 0), (1, 0, 0, 0)]" not in _render_base_animation(
        result, "Animation", None
    )


def test_dual_skinning_blends_parent_to_current_joint_along_bone_segment() -> None:
    result = apply_dual_skinning(_model())

    assert result.base_mesh is not None
    assert result.base_mesh.skel_element_size == 2
    assert result.base_mesh.skel_joint_indices == (0, 1, 0, 1, 0, 1)
    assert result.base_mesh.skel_joint_weights == pytest.approx((1.0, 0.0, 0.5, 0.5, 0.0, 1.0))
    assert tuple(part.binding.joint_tokens for part in result.repeated_parts) == (("branch", "root"),) * 3
    assert tuple(weight for part in result.repeated_parts for weight in part.binding.weights) == pytest.approx(
        (0.0, 1.0, 0.5, 0.5, 1.0, 0.0)
    )
