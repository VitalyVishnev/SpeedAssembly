"""Bone-frame construction and skeletal influence processing."""

from __future__ import annotations

import math
from dataclasses import replace

from .models import (
    CanonicalTreeModel,
    InstanceBinding,
    Joint,
    Matrix4d,
    MeshData,
    RepeatedPartInstance,
    ValidationIssue,
    Vector3,
)


_EPSILON = 1.0e-8
_TRANSFORM_TOLERANCE = 1.0e-4
_TWIST_WARNING_DEGREES = 75.0


def validate_skeleton(skeleton: tuple[Joint, ...] | None) -> tuple[ValidationIssue, ...]:
    """Validate hierarchy, +X frames, rigid bases, and local rest reconstruction."""
    if not skeleton:
        return ()
    issues: list[ValidationIssue] = []
    joints_by_name = {joint.name: joint for joint in skeleton}
    if len(joints_by_name) != len(skeleton):
        issues.append(_error("duplicate_skeleton_joint", "Skeleton contains duplicate joint names."))

    for joint in skeleton:
        if joint.parent is not None and joint.parent not in joints_by_name:
            issues.append(
                _error(
                    "missing_skeleton_parent",
                    f"Bone {joint.name!r} references missing parent {joint.parent!r}.",
                )
            )
    cycle = _first_hierarchy_cycle(skeleton, joints_by_name)
    if cycle:
        issues.append(_error("cyclic_skeleton_hierarchy", f"Skeleton hierarchy contains a cycle at bone {cycle!r}."))

    for joint in skeleton:
        bind = joint.bind_transform
        rest = joint.rest_transform
        if not _matrix_has_shape(bind) or not _matrix_has_shape(rest):
            issues.append(_error("invalid_bone_transform_shape", f"Bone {joint.name!r} bind/rest transform is not a 4x4 matrix."))
            continue
        if not _matrix_is_finite(bind) or not _matrix_is_finite(rest):
            issues.append(_error("non_finite_bone_transform", f"Bone {joint.name!r} contains a non-finite bind/rest transform."))
            continue
        if not _is_rigid_basis(bind) or not _is_rigid_basis(rest):
            issues.append(_error("invalid_bone_basis", f"Bone {joint.name!r} bind/rest basis is not orthonormal and right-handed."))
            continue

        end = joint.bind_end_translate
        if end is None:
            issues.append(_warning("missing_bone_direction", f"Bone {joint.name!r} has no endpoint for +X validation."))
        else:
            direction = _subtract(end, joint.bind_translate)
            if _length_squared(direction) <= _EPSILON:
                issues.append(_error("zero_length_bone", f"Bone {joint.name!r} has coincident start and end positions."))
            elif _dot(_matrix_axis(bind, 0), _normalize(direction, joint.name)) < 1.0 - _TRANSFORM_TOLERANCE:
                issues.append(_error("invalid_bone_x_axis", f"Bone {joint.name!r} local +X does not point from Bone.Start to Bone.End."))

        parent = joints_by_name.get(joint.parent) if joint.parent is not None else None
        if parent is not None and (
            not _matrix_has_shape(parent.bind_transform) or not _matrix_is_finite(parent.bind_transform)
        ):
            continue
        reconstructed = rest if parent is None else _multiply(rest, parent.bind_transform)
        if not _matrices_close(reconstructed, bind):
            issues.append(
                _error(
                    "inconsistent_bone_rest_transform",
                    f"Bone {joint.name!r} local rest transform does not reconstruct its absolute bind transform.",
                )
            )
        if parent is not None:
            twist = _transported_twist_degrees(parent.bind_transform, bind)
            if twist is not None and twist > _TWIST_WARNING_DEGREES:
                issues.append(
                    _warning(
                        "excessive_bone_twist",
                        f"Bone {joint.name!r} rolls {twist:.1f} degrees from its parent frame; expected at most {_TWIST_WARNING_DEGREES:g}.",
                    )
                )
    return tuple(issues)


def validate_skinning(model: CanonicalTreeModel) -> tuple[ValidationIssue, ...]:
    """Validate authored single/dual influences for the base mesh and repeated Parts."""
    issues: list[ValidationIssue] = []
    skeleton = model.skeleton or ()
    widths: list[tuple[str, int]] = []
    mesh = model.base_mesh
    if mesh is not None and (mesh.skel_joint_indices or mesh.skel_joint_weights):
        widths.append(("base mesh", mesh.skel_element_size))
        issues.extend(_validate_mesh_influences(mesh, len(skeleton)))

    valid_joints = {joint.name for joint in skeleton}
    for part in model.repeated_parts:
        width = part.binding.element_size
        widths.append((f"Part {part.name!r}", width))
        if width not in {1, 2}:
            issues.append(_error("invalid_part_binding_width", f"Repeated Part {part.name!r} has {width} influences; expected one or two."))
            continue
        if len(part.binding.weights) != width:
            issues.append(_error("invalid_binding_shape", f"Repeated Part {part.name!r} has mismatched joint and weight counts."))
            continue
        invalid_token = next((token for token in part.binding.joint_tokens if token not in valid_joints), None)
        if invalid_token is not None:
            issues.append(_error("invalid_binding_joint", f"Repeated Part {part.name!r} references missing bone {invalid_token!r}."))
        weight_issue = _weight_issue(part.binding.weights)
        if weight_issue:
            issues.append(_error("invalid_part_binding_weights", f"Repeated Part {part.name!r} {weight_issue}."))

    active_widths = {width for _label, width in widths if width > 0}
    if 2 in active_widths and active_widths != {2}:
        detail = ", ".join(f"{label}: {width}" for label, width in widths if width != 2)
        issues.append(_error("inconsistent_dual_skinning_width", f"Dual Skinning requires two influences everywhere; found {detail}."))
    return tuple(issues)


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


def _validate_mesh_influences(mesh: MeshData, skeleton_size: int) -> list[ValidationIssue]:
    width = mesh.skel_element_size
    if width not in {1, 2}:
        return [_error("invalid_base_mesh_skinning_width", f"Base mesh has {width} influences per vertex; expected one or two.")]
    expected = len(mesh.points) * width
    if len(mesh.skel_joint_indices) != expected or len(mesh.skel_joint_weights) != expected:
        return [
            _error(
                "invalid_base_mesh_skinning_shape",
                f"Base mesh has {len(mesh.skel_joint_indices)} indices and {len(mesh.skel_joint_weights)} weights; expected {expected} of each.",
            )
        ]
    for point_index in range(len(mesh.points)):
        start = point_index * width
        indices = mesh.skel_joint_indices[start:start + width]
        invalid_index = next((index for index in indices if index < 0 or index >= skeleton_size), None)
        if invalid_index is not None:
            return [
                _error(
                    "invalid_base_mesh_joint_index",
                    f"Base mesh vertex {point_index} references joint index {invalid_index}; skeleton size is {skeleton_size}.",
                )
            ]
        weight_issue = _weight_issue(mesh.skel_joint_weights[start:start + width])
        if weight_issue:
            return [_error("invalid_base_mesh_joint_weights", f"Base mesh vertex {point_index} {weight_issue}.")]
    return []


def _weight_issue(weights) -> str | None:
    if any(not math.isfinite(weight) for weight in weights):
        return "contains non-finite skinning weights"
    if any(weight < -_TRANSFORM_TOLERANCE or weight > 1.0 + _TRANSFORM_TOLERANCE for weight in weights):
        return "contains skinning weights outside [0, 1]"
    total = sum(weights)
    if abs(total - 1.0) > _TRANSFORM_TOLERANCE:
        return f"has skinning weights summing to {total:g} instead of 1"
    return None


def _first_hierarchy_cycle(skeleton: tuple[Joint, ...], joints_by_name: dict[str, Joint]) -> str | None:
    resolved: set[str] = set()
    for joint in skeleton:
        path: set[str] = set()
        current: str | None = joint.name
        while current in joints_by_name and current not in resolved:
            if current in path:
                return current
            path.add(current)
            current = joints_by_name[current].parent
        resolved.update(path)
    return None


def _matrix_is_finite(matrix: Matrix4d) -> bool:
    return all(math.isfinite(value) for row in matrix.rows for value in row)


def _matrix_has_shape(matrix: Matrix4d) -> bool:
    return len(matrix.rows) == 4 and all(len(row) == 4 for row in matrix.rows)


def _is_rigid_basis(matrix: Matrix4d) -> bool:
    x_axis, y_axis, z_axis = (_matrix_axis(matrix, index) for index in range(3))
    if any(abs(_length_squared(axis) - 1.0) > _TRANSFORM_TOLERANCE for axis in (x_axis, y_axis, z_axis)):
        return False
    if any(abs(value) > _TRANSFORM_TOLERANCE for value in (_dot(x_axis, y_axis), _dot(x_axis, z_axis), _dot(y_axis, z_axis))):
        return False
    if abs(_dot(x_axis, _cross(y_axis, z_axis)) - 1.0) > _TRANSFORM_TOLERANCE:
        return False
    return (
        all(abs(matrix.rows[row][3]) <= _TRANSFORM_TOLERANCE for row in range(3))
        and abs(matrix.rows[3][3] - 1.0) <= _TRANSFORM_TOLERANCE
    )


def _matrices_close(left: Matrix4d, right: Matrix4d) -> bool:
    return all(
        abs(left.rows[row][column] - right.rows[row][column]) <= _TRANSFORM_TOLERANCE
        for row in range(4)
        for column in range(4)
    )


def _transported_twist_degrees(parent: Matrix4d, child: Matrix4d) -> float | None:
    child_x = _matrix_axis(child, 0)
    reference_y = _project_perpendicular(_matrix_axis(parent, 1), child_x)
    if _length_squared(reference_y) <= _EPSILON:
        reference_y = _project_perpendicular(_matrix_axis(parent, 2), child_x)
    if _length_squared(reference_y) <= _EPSILON:
        return None
    reference_y = _normalize(reference_y, "twist reference")
    cosine = max(-1.0, min(1.0, _dot(reference_y, _matrix_axis(child, 1))))
    return math.degrees(math.acos(cosine))


def _error(code: str, message: str) -> ValidationIssue:
    return ValidationIssue(severity="error", code=code, message=message)


def _warning(code: str, message: str) -> ValidationIssue:
    return ValidationIssue(severity="warning", code=code, message=message)


def _normalize(vector: Vector3, joint_name: str) -> Vector3:
    length_squared = _length_squared(vector)
    if length_squared <= _EPSILON:
        raise ValueError(f"Cannot orient bone {joint_name!r}: Bone.Start and Bone.End are coincident.")
    inverse_length = 1.0 / math.sqrt(length_squared)
    return Vector3(vector.x * inverse_length, vector.y * inverse_length, vector.z * inverse_length)
