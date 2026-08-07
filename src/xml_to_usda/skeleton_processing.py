"""Bone-frame construction and skeletal influence processing."""

from __future__ import annotations

import math
from dataclasses import replace

from .models import CanonicalTreeModel, InstanceBinding, Joint, Matrix4d, MeshData, RepeatedPartInstance, Vector3


_EPSILON = 1.0e-8


def apply_dual_skinning(model: CanonicalTreeModel) -> CanonicalTreeModel:
    """Blend base vertices and repeated parts between parent/current bones."""
    skeleton = model.skeleton
    base_mesh = model.base_mesh
    if base_mesh is not None:
        base_mesh = _apply_mesh_dual_skinning(base_mesh, skeleton)
    joint_by_name = {joint.name: joint for joint in skeleton}
    repeated_parts = tuple(_apply_part_dual_skinning(part, joint_by_name) for part in model.repeated_parts)
    return replace(model, base_mesh=base_mesh, assembly_parts=repeated_parts)


def orient_skeleton_x(skeleton: tuple[Joint, ...]) -> tuple[Joint, ...]:
    oriented: list[Joint] = []
    absolute_by_name: dict[str, Matrix4d] = {}
    for joint in skeleton:
        end = joint.bind_end_translate
        if end is None:
            oriented.append(joint)
            absolute_by_name[joint.name] = joint.bind_transform
            continue
        x_axis = _normalize(_subtract(end, joint.bind_translate), joint.name)
        parent_transform = absolute_by_name.get(joint.parent) if joint.parent is not None else None
        if joint.parent is not None and parent_transform is None:
            raise ValueError(f"Cannot orient bone {joint.name!r}: parent {joint.parent!r} precedes no authored joint.")

        preferred_y = _matrix_axis(parent_transform, 1) if parent_transform is not None else Vector3(0.0, 1.0, 0.0)
        y_axis = _project_perpendicular(preferred_y, x_axis)
        if _length_squared(y_axis) <= _EPSILON:
            fallback = _matrix_axis(parent_transform, 2) if parent_transform is not None else Vector3(0.0, 0.0, 1.0)
            y_axis = _project_perpendicular(fallback, x_axis)
        if _length_squared(y_axis) <= _EPSILON:
            fallback = min(
                (Vector3(1.0, 0.0, 0.0), Vector3(0.0, 1.0, 0.0), Vector3(0.0, 0.0, 1.0)),
                key=lambda axis: abs(_dot(axis, x_axis)),
            )
            y_axis = _project_perpendicular(fallback, x_axis)
        y_axis = _normalize(y_axis, joint.name)
        z_axis = _normalize(_cross(x_axis, y_axis), joint.name)
        y_axis = _normalize(_cross(z_axis, x_axis), joint.name)

        absolute = _transform(x_axis, y_axis, z_axis, joint.bind_translate)
        rest = absolute if parent_transform is None else _multiply(absolute, _rigid_inverse(parent_transform))
        oriented_joint = replace(joint, bind_transform=absolute, rest_transform=rest)
        oriented.append(oriented_joint)
        absolute_by_name[joint.name] = absolute
    return tuple(oriented)


def _apply_part_dual_skinning(part: RepeatedPartInstance, joint_by_name: dict[str, Joint]) -> RepeatedPartInstance:
    if part.binding.element_size != 1:
        raise ValueError(f"Dual Skinning requires one normalized joint binding for repeated part {part.name!r}.")
    joint = joint_by_name.get(part.binding.joint_tokens[0])
    if joint is None:
        raise ValueError(f"Dual Skinning cannot resolve repeated part {part.name!r} joint binding.")
    parent = joint_by_name.get(joint.parent) if joint.parent is not None else None
    blend = _bone_blend(part.position, joint)
    if parent is None or blend is None:
        binding = InstanceBinding(joint_tokens=(joint.name, joint.name), weights=(1.0, 0.0))
    else:
        binding = InstanceBinding(joint_tokens=(joint.name, parent.name), weights=(blend, 1.0 - blend))
    return replace(part, binding=binding)


def _apply_mesh_dual_skinning(mesh: MeshData, skeleton: tuple[Joint, ...]) -> MeshData:
    if mesh.skel_element_size != 1:
        raise ValueError("Dual Skinning requires the normalized single-influence base mesh.")
    if len(mesh.skel_joint_indices) != len(mesh.points):
        raise ValueError("Dual Skinning requires one normalized joint index per base-mesh point.")

    joint_index = {joint.name: index for index, joint in enumerate(skeleton)}
    indices: list[int] = []
    weights: list[float] = []
    for point, current_index in zip(mesh.points, mesh.skel_joint_indices, strict=True):
        joint = skeleton[current_index]
        parent_index = joint_index.get(joint.parent) if joint.parent is not None else None
        blend = _bone_blend(point, joint)
        if parent_index is None or blend is None:
            indices.extend((current_index, current_index))
            weights.extend((1.0, 0.0))
            continue
        indices.extend((parent_index, current_index))
        weights.extend((1.0 - blend, blend))
    return replace(
        mesh,
        skel_joint_indices=tuple(indices),
        skel_joint_weights=tuple(weights),
        skel_element_size=2,
    )


def _bone_blend(position: Vector3, joint: Joint) -> float | None:
    end = joint.bind_end_translate
    if end is None:
        return None
    segment = _subtract(end, joint.bind_translate)
    length_squared = _length_squared(segment)
    if length_squared <= _EPSILON:
        return None
    return max(0.0, min(1.0, _dot(_subtract(position, joint.bind_translate), segment) / length_squared))


def _transform(x_axis: Vector3, y_axis: Vector3, z_axis: Vector3, translate: Vector3) -> Matrix4d:
    return Matrix4d(rows=(
        (x_axis.x, x_axis.y, x_axis.z, 0.0),
        (y_axis.x, y_axis.y, y_axis.z, 0.0),
        (z_axis.x, z_axis.y, z_axis.z, 0.0),
        (translate.x, translate.y, translate.z, 1.0),
    ))


def _multiply(left: Matrix4d, right: Matrix4d) -> Matrix4d:
    return Matrix4d(
        rows=tuple(
            tuple(sum(left.rows[row][k] * right.rows[k][column] for k in range(4)) for column in range(4))
            for row in range(4)
        )
    )


def _rigid_inverse(matrix: Matrix4d) -> Matrix4d:
    rotation = matrix.rows
    translation = matrix.translation
    inverse_translation = (
        -_dot(translation, Vector3(rotation[0][0], rotation[0][1], rotation[0][2])),
        -_dot(translation, Vector3(rotation[1][0], rotation[1][1], rotation[1][2])),
        -_dot(translation, Vector3(rotation[2][0], rotation[2][1], rotation[2][2])),
    )
    return Matrix4d(rows=(
        (rotation[0][0], rotation[1][0], rotation[2][0], 0.0),
        (rotation[0][1], rotation[1][1], rotation[2][1], 0.0),
        (rotation[0][2], rotation[1][2], rotation[2][2], 0.0),
        (*inverse_translation, 1.0),
    ))


def _matrix_axis(matrix: Matrix4d, index: int) -> Vector3:
    row = matrix.rows[index]
    return Vector3(row[0], row[1], row[2])


def _subtract(left: Vector3, right: Vector3) -> Vector3:
    return Vector3(left.x - right.x, left.y - right.y, left.z - right.z)


def _dot(left: Vector3, right: Vector3) -> float:
    return left.x * right.x + left.y * right.y + left.z * right.z


def _cross(left: Vector3, right: Vector3) -> Vector3:
    return Vector3(left.y * right.z - left.z * right.y, left.z * right.x - left.x * right.z, left.x * right.y - left.y * right.x)


def _project_perpendicular(vector: Vector3, normal: Vector3) -> Vector3:
    projection = _dot(vector, normal)
    return Vector3(
        vector.x - normal.x * projection,
        vector.y - normal.y * projection,
        vector.z - normal.z * projection,
    )


def _length_squared(vector: Vector3) -> float:
    return _dot(vector, vector)


def _normalize(vector: Vector3, joint_name: str) -> Vector3:
    length_squared = _length_squared(vector)
    if length_squared <= _EPSILON:
        raise ValueError(f"Cannot orient bone {joint_name!r}: Bone.Start and Bone.End are coincident.")
    inverse_length = 1.0 / math.sqrt(length_squared)
    return Vector3(vector.x * inverse_length, vector.y * inverse_length, vector.z * inverse_length)
