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
from xml_to_usda.skeleton_processing import (
    _multiply,
    _rigid_inverse,
    apply_dual_skinning,
    orient_skeleton_x,
    validate_skeleton,
    validate_skinning,
)
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


def test_skeleton_validation_reports_orientation_rest_and_hierarchy_failures() -> None:
    source = _model()
    oriented = orient_skeleton_x(source.skeleton)
    invalid_root = replace(oriented[0], bind_transform=Matrix4d.identity(), rest_transform=Matrix4d.identity())
    invalid_branch = replace(oriented[1], parent="missing", rest_transform=Matrix4d.identity())

    issues = validate_skeleton((invalid_root, invalid_branch))
    codes = {issue.code for issue in issues}

    assert "invalid_bone_x_axis" in codes
    assert "missing_skeleton_parent" in codes
    assert "inconsistent_bone_rest_transform" in codes
    assert any("'branch'" in issue.message for issue in issues)

    cycle_issues = validate_skeleton((replace(oriented[0], parent="branch"), oriented[1]))
    assert any(issue.code == "cyclic_skeleton_hierarchy" for issue in cycle_issues)


def test_skeleton_validation_warns_for_excessive_chain_twist() -> None:
    source = _model()
    root, branch = orient_skeleton_x(source.skeleton)
    x_axis, y_axis, z_axis = branch.bind_transform.rows[:3]
    twisted_z = (-y_axis[0], -y_axis[1], -y_axis[2], 0.0)
    twisted_bind = Matrix4d(rows=(x_axis, z_axis, twisted_z, branch.bind_transform.rows[3]))
    twisted_rest = _multiply(twisted_bind, _rigid_inverse(root.bind_transform))

    issues = validate_skeleton((root, replace(branch, bind_transform=twisted_bind, rest_transform=twisted_rest)))

    assert any(issue.code == "excessive_bone_twist" and issue.severity == "warning" for issue in issues)


def test_skinning_validation_identifies_vertex_weights_and_mixed_binding_widths() -> None:
    model = apply_dual_skinning(_model())
    assert model.base_mesh is not None
    bad_mesh = replace(model.base_mesh, skel_joint_weights=(float("nan"),) + model.base_mesh.skel_joint_weights[1:])
    bad_part = replace(model.repeated_parts[0], binding=InstanceBinding(("branch",), (1.0,)))
    invalid = replace(model, base_mesh=bad_mesh, assembly_parts=(bad_part,) + model.repeated_parts[1:])

    issues = validate_skinning(invalid)

    assert any(issue.code == "invalid_base_mesh_joint_weights" and "vertex 0" in issue.message for issue in issues)
    assert any(issue.code == "inconsistent_dual_skinning_width" and "part_0" in issue.message for issue in issues)
