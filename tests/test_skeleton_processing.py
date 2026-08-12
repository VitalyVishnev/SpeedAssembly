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
    SkinningQuality,
    TreeAsset,
    Vector3,
)
from xml_to_usda.skeleton_processing import (
    _multiply,
    _rigid_inverse,
    apply_skinning_quality,
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


def test_two_weight_skinning_blends_parent_to_current_joint_along_bone_segment() -> None:
    result = apply_skinning_quality(_model(), skinning_quality=SkinningQuality.TWO_WEIGHTS)

    assert result.base_mesh is not None
    assert result.base_mesh.skel_element_size == 2
    assert result.base_mesh.skel_joint_indices == (0, 1, 0, 1, 0, 1)
    assert result.base_mesh.skel_joint_weights == pytest.approx((1.0, 0.0, 0.5, 0.5, 0.0, 1.0))
    assert tuple(part.binding.joint_tokens for part in result.repeated_parts) == (("branch", "root"),) * 3
    assert tuple(weight for part in result.repeated_parts for weight in part.binding.weights) == pytest.approx(
        (0.0, 1.0, 0.5, 0.5, 1.0, 0.0)
    )


def test_one_weight_quality_preserves_normalized_rigid_bindings() -> None:
    source = _model()

    assert apply_skinning_quality(source, skinning_quality=SkinningQuality.ONE_WEIGHT) is source


def test_inherited_attachment_skinning_propagates_parent_deformation_with_selected_cap() -> None:
    source = _model()
    root, branch = source.skeleton
    child = Joint(
        name="child",
        parent="branch",
        bind_transform=Matrix4d.from_translation(Vector3(1.0, 3.0, 0.0)),
        rest_transform=Matrix4d.from_translation(Vector3(1.0, 3.0, 0.0)),
        bind_end_transform=Matrix4d.from_translation(Vector3(3.0, 3.0, 0.0)),
    )
    grandchild = Joint(
        name="grandchild",
        parent="child",
        bind_transform=Matrix4d.from_translation(Vector3(2.0, 3.0, 0.0)),
        rest_transform=Matrix4d.from_translation(Vector3(2.0, 3.0, 0.0)),
        bind_end_transform=Matrix4d.from_translation(Vector3(2.0, 5.0, 0.0)),
    )
    mesh = replace(
        source.base_mesh,
        points=(Vector3(2.0, 3.0, 0.0), Vector3(2.0, 4.0, 0.0), Vector3(2.0, 5.0, 0.0)),
        skel_joint_indices=(3, 3, 3),
    )
    parts = (
        RepeatedPartInstance(
            name="inherited_part",
            prototype_key="leaf",
            position=Vector3(2.0, 4.0, 0.0),
            orientation=Quaternion(1.0, 0.0, 0.0, 0.0),
            scale=Vector3(1.0, 1.0, 1.0),
            binding=InstanceBinding(("grandchild",), (1.0,)),
            source_object_id="1",
            source_mesh_id=1,
        ),
    )
    source = replace(
        source,
        skeleton=(root, branch, child, grandchild),
        base_mesh=mesh,
        assembly_parts=parts,
    )

    max_four = apply_skinning_quality(source, skinning_quality=SkinningQuality.FOUR_WEIGHTS)
    max_three = apply_skinning_quality(source, skinning_quality=SkinningQuality.THREE_WEIGHTS)

    assert max_four.base_mesh.skel_element_size == 4
    midpoint = slice(4, 8)
    midpoint_weights = dict(zip(
        max_four.base_mesh.skel_joint_indices[midpoint],
        max_four.base_mesh.skel_joint_weights[midpoint],
        strict=True,
    ))
    assert midpoint_weights == pytest.approx({0: 0.125, 1: 0.125, 2: 0.25, 3: 0.5})
    assert max_three.base_mesh.skel_element_size == 3
    assert sum(max_three.base_mesh.skel_joint_weights[3:6]) == pytest.approx(1.0)
    assert set(max_three.base_mesh.skel_joint_indices[3:6]) == {0, 2, 3}
    assert max_four.repeated_parts[0].binding.element_size == 4
    assert max_four.repeated_parts[0].binding.joint_tokens == ("grandchild", "child", "root", "branch")
    assert max_four.repeated_parts[0].binding.weights == pytest.approx((0.5, 0.25, 0.125, 0.125))
    assert max_three.repeated_parts[0].binding.element_size == 3
    assert max_three.repeated_parts[0].binding.joint_tokens == ("grandchild", "child", "root")
    assert max_three.repeated_parts[0].binding.weights == pytest.approx((4 / 7, 2 / 7, 1 / 7))
    assert not validate_skinning(max_four)
    assert not validate_skinning(max_three)


def test_soft_attachment_skinning_adds_two_weight_collar_to_child_without_changing_parent() -> None:
    source = _model()
    child = Joint(
        name="child",
        parent="branch",
        bind_transform=Matrix4d.from_translation(Vector3(1.0, 3.0, 0.0)),
        rest_transform=Matrix4d.from_translation(Vector3(1.0, 3.0, 0.0)),
        bind_end_transform=Matrix4d.from_translation(Vector3(1.0, 5.0, 0.0)),
    )
    mesh = replace(
        source.base_mesh,
        points=(
            Vector3(1.0, 3.0, 0.0),
            Vector3(1.0, 3.0, 0.0),
            Vector3(1.0, 3.2, 0.0),
            Vector3(1.0, 3.4, 0.0),
            Vector3(1.0, 4.2, 0.0),
            Vector3(1.0, 5.0, 0.0),
        ),
        skel_joint_indices=(1, 2, 2, 2, 2, 2),
        skel_joint_weights=(1.0,) * 6,
    )
    source = replace(source, skeleton=source.skeleton + (child,), base_mesh=mesh)

    result = apply_skinning_quality(source, skinning_quality=SkinningQuality.TWO_WEIGHTS)

    assert result.base_mesh.skel_element_size == 2
    assert result.base_mesh.skel_joint_indices == (
        0, 1,
        0, 1,
        0, 1,
        0, 1,
        1, 2,
        1, 2,
    )
    assert result.base_mesh.skel_joint_weights == pytest.approx((
        0.5, 0.5,
        0.5, 0.5,
        0.25, 0.75,
        0.0, 1.0,
        0.5, 0.5,
        0.0, 1.0,
    ))
    assert all(part.binding.element_size == 2 for part in result.repeated_parts)


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
    model = apply_skinning_quality(_model(), skinning_quality=SkinningQuality.TWO_WEIGHTS)
    assert model.base_mesh is not None
    bad_mesh = replace(model.base_mesh, skel_joint_weights=(float("nan"),) + model.base_mesh.skel_joint_weights[1:])
    bad_part = replace(model.repeated_parts[0], binding=InstanceBinding(("branch",), (1.0,)))
    invalid = replace(model, base_mesh=bad_mesh, assembly_parts=(bad_part,) + model.repeated_parts[1:])

    issues = validate_skinning(invalid)

    assert any(issue.code == "invalid_base_mesh_joint_weights" and "vertex 0" in issue.message for issue in issues)
    assert any(issue.code == "inconsistent_skinning_quality_width" and "part_0" in issue.message for issue in issues)


def test_skinning_validation_preserves_first_vertex_and_joint_before_weight_error_order() -> None:
    model = apply_skinning_quality(_model(), skinning_quality=SkinningQuality.TWO_WEIGHTS)
    assert model.base_mesh is not None
    bad_weights = replace(
        model.base_mesh,
        skel_joint_indices=model.base_mesh.skel_joint_indices[:2] + (99,) + model.base_mesh.skel_joint_indices[3:],
        skel_joint_weights=(0.25, 0.25) + model.base_mesh.skel_joint_weights[2:],
    )

    first_issue = validate_skinning(replace(model, base_mesh=bad_weights))[0]

    assert first_issue.code == "invalid_base_mesh_joint_weights"
    assert "vertex 0" in first_issue.message

    same_vertex = replace(
        bad_weights,
        skel_joint_indices=(99,) + bad_weights.skel_joint_indices[1:],
        skel_joint_weights=(float("nan"),) + bad_weights.skel_joint_weights[1:],
    )
    first_issue = validate_skinning(replace(model, base_mesh=same_vertex))[0]

    assert first_issue.code == "invalid_base_mesh_joint_index"
    assert "vertex 0" in first_issue.message
