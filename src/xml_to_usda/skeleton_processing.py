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
    Quaternion,
    RepeatedPartInstance,
    SkinningQuality,
    ValidationIssue,
    Vector3,
)


_EPSILON = 1.0e-8
_TRANSFORM_TOLERANCE = 1.0e-4
_TWIST_WARNING_DEGREES = 75.0
_DENSE_VERTEX_CHUNK_SIZE = 262_144
_SOFT_ATTACHMENT_COLLAR_FRACTION = 0.2
_DYNAMIC_WIND_TILT_RADIANS = math.radians(1.0)
_VERTICAL_AXIS_EPSILON = 1.0e-8


def strictly_vertical_joint_names(skeleton: tuple[Joint, ...] | None) -> tuple[str, ...]:
    """Return joints whose authored forward axis is parallel to Stage +Y/-Y."""
    names: list[str] = []
    for joint in skeleton or ():
        axis = _matrix_axis(joint.bind_transform, 0)
        if (
            abs(axis.y) > 1.0 - _VERTICAL_AXIS_EPSILON
            and axis.x * axis.x + axis.z * axis.z <= _VERTICAL_AXIS_EPSILON * _VERTICAL_AXIS_EPSILON
        ):
            names.append(joint.name)
    return tuple(names)


def tilt_tree_for_dynamic_wind(model: CanonicalTreeModel) -> CanonicalTreeModel:
    """Bake a deterministic 1-degree whole-asset tilt around the skeleton pivot."""
    if not strictly_vertical_joint_names(model.skeleton):
        return model
    root = next((joint for joint in model.skeleton if joint.parent is None), model.skeleton[0])
    pivot = root.bind_translate
    sine = math.sin(_DYNAMIC_WIND_TILT_RADIANS)
    cosine = math.cos(_DYNAMIC_WIND_TILT_RADIANS)

    def rotate_vector(value: Vector3) -> Vector3:
        return Vector3(
            cosine * value.x - sine * value.y,
            sine * value.x + cosine * value.y,
            value.z,
        )

    def rotate_point(value: Vector3) -> Vector3:
        offset = rotate_vector(_subtract(value, pivot))
        return Vector3(pivot.x + offset.x, pivot.y + offset.y, pivot.z + offset.z)

    def rotate_matrix(value: Matrix4d) -> Matrix4d:
        return _transform(
            rotate_vector(_matrix_axis(value, 0)),
            rotate_vector(_matrix_axis(value, 1)),
            rotate_vector(_matrix_axis(value, 2)),
            rotate_point(value.translation),
        )

    absolute_skeleton = tuple(
        replace(
            joint,
            bind_transform=rotate_matrix(joint.bind_transform),
            bind_end_transform=(
                rotate_matrix(joint.bind_end_transform)
                if joint.bind_end_transform is not None
                else None
            ),
        )
        for joint in model.skeleton
    )
    absolute_by_name = {joint.name: joint.bind_transform for joint in absolute_skeleton}
    skeleton = tuple(
        replace(
            joint,
            rest_transform=(
                joint.bind_transform
                if joint.parent is None
                else _multiply(joint.bind_transform, _rigid_inverse(absolute_by_name[joint.parent]))
            ),
        )
        for joint in absolute_skeleton
    )
    rotation = Quaternion(
        math.cos(_DYNAMIC_WIND_TILT_RADIANS * 0.5),
        0.0,
        0.0,
        math.sin(_DYNAMIC_WIND_TILT_RADIANS * 0.5),
    )

    def rotate_mesh(mesh: MeshData) -> MeshData:
        return replace(
            mesh,
            points=tuple(rotate_point(point) for point in mesh.points),
            normals=tuple(rotate_vector(normal) for normal in mesh.normals),
        )

    def rotate_orientation(orientation: Quaternion) -> Quaternion:
        return _multiply_quaternions(rotation, orientation)

    return replace(
        model,
        base_mesh=rotate_mesh(model.base_mesh) if model.base_mesh is not None else None,
        skeleton=skeleton,
        assembly_parts=tuple(
            replace(
                part,
                position=rotate_point(part.position),
                orientation=rotate_orientation(part.orientation),
            )
            for part in model.repeated_parts
        ),
        static_collision_meshes=tuple(rotate_mesh(mesh) for mesh in model.static_collision_meshes),
        static_collision_primitives=tuple(
            replace(
                primitive,
                center=rotate_point(primitive.center),
                orientation=rotate_orientation(primitive.orientation),
            )
            for primitive in model.static_collision_primitives
        ),
    )


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
    """Validate authored skinning influences for the base mesh and repeated Parts."""
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
        if width not in {1, 2, 3, 4}:
            issues.append(_error("invalid_part_binding_width", f"Repeated Part {part.name!r} has {width} influences; expected one to four."))
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

    base_width = mesh.skel_element_size if mesh is not None else 0
    if base_width and any(width != base_width for label, width in widths if label != "base mesh"):
        detail = ", ".join(
            f"{label}: {width}"
            for label, width in widths
            if label != "base mesh" and width != base_width
        )
        issues.append(
            _error(
                "inconsistent_skinning_quality_width",
                f"Skinning Quality requires {base_width} influences for every repeated Part; found {detail}.",
            )
        )
    return tuple(issues)


def apply_skinning_quality(
    model: CanonicalTreeModel,
    *,
    skinning_quality: SkinningQuality | int = SkinningQuality.ONE_WEIGHT,
) -> CanonicalTreeModel:
    """Apply the selected one-to-four-weight skinning contract."""
    quality = SkinningQuality.parse(skinning_quality)
    if quality == SkinningQuality.ONE_WEIGHT:
        return model
    skeleton = model.skeleton
    joint_index = {joint.name: index for index, joint in enumerate(skeleton)}
    base_mesh = model.base_mesh
    if quality >= SkinningQuality.THREE_WEIGHTS:
        max_influences = int(quality)
        starts, segments, inverse_lengths_squared, parent_indices = _joint_geometry(skeleton, joint_index)
        start_distributions = _inherited_start_distributions(
            skeleton,
            max_influences,
            starts=starts,
            segments=segments,
            inverse_lengths_squared=inverse_lengths_squared,
            parent_indices=parent_indices,
        )
        candidate_indices, candidate_weights, candidate_counts = _inherited_candidate_tables(
            start_distributions,
            max_influences,
        )
        if base_mesh is not None:
            base_mesh = _apply_mesh_inherited_skinning(
                base_mesh,
                skeleton,
                max_influences=max_influences,
                start_distributions=start_distributions,
                starts=starts,
                segments=segments,
                inverse_lengths_squared=inverse_lengths_squared,
                candidate_indices=candidate_indices,
                candidate_weights=candidate_weights,
                candidate_counts=candidate_counts,
            )
        repeated_parts = _apply_parts_inherited_skinning(
            model.repeated_parts,
            skeleton,
            joint_index,
            max_influences=max_influences,
            starts=starts,
            segments=segments,
            inverse_lengths_squared=inverse_lengths_squared,
            candidate_indices=candidate_indices,
            candidate_weights=candidate_weights,
            candidate_counts=candidate_counts,
        )
    else:
        starts, segments, inverse_lengths_squared, parent_indices = _joint_geometry(skeleton, joint_index)
        if base_mesh is not None:
            base_mesh = _apply_mesh_two_weight_skinning(
                base_mesh,
                skeleton,
                starts=starts,
                segments=segments,
                inverse_lengths_squared=inverse_lengths_squared,
                parent_indices=parent_indices,
            )
        repeated_parts = _apply_parts_two_weight_skinning(
            model.repeated_parts,
            skeleton,
            joint_index,
            starts=starts,
            segments=segments,
            inverse_lengths_squared=inverse_lengths_squared,
            parent_indices=parent_indices,
        )
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


def _apply_parts_two_weight_skinning(
    parts: tuple[RepeatedPartInstance, ...],
    skeleton: tuple[Joint, ...],
    joint_index: dict[str, int],
    *,
    starts,
    segments,
    inverse_lengths_squared,
    parent_indices,
) -> tuple[RepeatedPartInstance, ...]:
    import numpy as np

    if not parts:
        return ()
    current_indices, positions = _part_inputs(parts, joint_index, "Two-weight skinning")
    inverse = inverse_lengths_squared[current_indices]
    current_parents = parent_indices[current_indices]
    active = (current_parents >= 0) & (inverse > 0.0)
    blend = np.ones(len(parts), dtype=np.float64)
    blend[active] = np.clip(
        np.sum((positions[active] - starts[current_indices[active]]) * segments[current_indices[active]], axis=1)
        * inverse[active],
        0.0,
        1.0,
    )
    names = tuple(joint.name for joint in skeleton)
    return tuple(
        replace(
            part,
            binding=InstanceBinding(
                joint_tokens=(names[current], names[parent] if is_active else names[current]),
                weights=(float(parameter), float(1.0 - parameter) if is_active else 0.0),
            ),
        )
        for part, current, parent, parameter, is_active in zip(
            parts, current_indices, current_parents, blend, active, strict=True
        )
    )


def _apply_parts_inherited_skinning(
    parts: tuple[RepeatedPartInstance, ...],
    skeleton: tuple[Joint, ...],
    joint_index: dict[str, int],
    *,
    max_influences: int,
    starts,
    segments,
    inverse_lengths_squared,
    candidate_indices,
    candidate_weights,
    candidate_counts,
) -> tuple[RepeatedPartInstance, ...]:
    if not parts:
        return ()
    current_indices, positions = _part_inputs(parts, joint_index, "Inherited skinning")
    indices, weights = _evaluate_inherited_influences(
        current_indices,
        positions,
        max_influences=max_influences,
        starts=starts,
        segments=segments,
        inverse_lengths_squared=inverse_lengths_squared,
        candidate_indices=candidate_indices,
        candidate_weights=candidate_weights,
        candidate_counts=candidate_counts,
        pad_with_current=False,
    )
    names = tuple(joint.name for joint in skeleton)
    return tuple(
        replace(
            part,
            binding=InstanceBinding(
                joint_tokens=tuple(names[int(index)] for index in part_indices),
                weights=tuple(float(weight) for weight in part_weights),
            ),
        )
        for part, part_indices, part_weights in zip(parts, indices, weights, strict=True)
    )


def _apply_mesh_two_weight_skinning(
    mesh: MeshData,
    skeleton: tuple[Joint, ...],
    *,
    starts,
    segments,
    inverse_lengths_squared,
    parent_indices,
) -> MeshData:
    import numpy as np

    if mesh.skel_element_size != 1:
        raise ValueError("Two-weight skinning requires the normalized single-influence base mesh.")
    if len(mesh.skel_joint_indices) != len(mesh.points):
        raise ValueError("Two-weight skinning requires one normalized joint index per base-mesh point.")

    joint_count = len(skeleton)
    attachment_parent_blends = np.full(joint_count, np.nan, dtype=np.float64)
    grandparent_indices = np.full(joint_count, -1, dtype=np.int64)
    current_indices = np.arange(joint_count)
    has_parent = parent_indices >= 0
    grandparent_indices[has_parent] = parent_indices[parent_indices[has_parent]]
    collar_candidates = (grandparent_indices >= 0) & (inverse_lengths_squared[parent_indices] > 0.0)
    if np.any(collar_candidates):
        collar_indices = current_indices[collar_candidates]
        collar_parents = parent_indices[collar_candidates]
        parameters = np.clip(
            np.sum(
                (starts[collar_indices] - starts[collar_parents]) * segments[collar_parents],
                axis=1,
            ) * inverse_lengths_squared[collar_parents],
            0.0,
            1.0,
        )
        interior = (_EPSILON < parameters) & (parameters < 1.0 - _EPSILON)
        attachment_parent_blends[collar_indices[interior]] = parameters[interior]
        grandparent_indices[collar_indices[~interior]] = -1

    indices: list[int] = []
    weights: list[float] = []
    point_count = len(mesh.points)
    for start_index in range(0, point_count, _DENSE_VERTEX_CHUNK_SIZE):
        end_index = min(point_count, start_index + _DENSE_VERTEX_CHUNK_SIZE)
        chunk_count = end_index - start_index
        current_indices = np.asarray(mesh.skel_joint_indices[start_index:end_index], dtype=np.int64)
        points = np.fromiter(
            (
                coordinate
                for point in mesh.points[start_index:end_index]
                for coordinate in (point.x, point.y, point.z)
            ),
            dtype=np.float64,
            count=chunk_count * 3,
        ).reshape((chunk_count, 3))

        point_segments = segments[current_indices]
        relative_points = points - starts[current_indices]
        numerators = (
            relative_points[:, 0] * point_segments[:, 0]
            + relative_points[:, 1] * point_segments[:, 1]
            + relative_points[:, 2] * point_segments[:, 2]
        )
        current_parents = parent_indices[current_indices]
        blended = (inverse_lengths_squared[current_indices] > 0.0) & (current_parents >= 0)

        chunk_indices = np.column_stack((current_indices, current_indices))
        chunk_weights = np.empty((chunk_count, 2), dtype=np.float64)
        chunk_weights[:, 0] = 1.0
        chunk_weights[:, 1] = 0.0
        if np.any(blended):
            blend = np.clip(
                numerators[blended] * inverse_lengths_squared[current_indices[blended]],
                0.0,
                1.0,
            )
            chunk_indices[blended, 0] = current_parents[blended]
            chunk_weights[blended, 0] = 1.0 - blend
            chunk_weights[blended, 1] = blend

            blended_rows = np.flatnonzero(blended)
            blended_current_indices = current_indices[blended]
            attachment_blends = attachment_parent_blends[blended_current_indices]
            has_collar = np.isfinite(attachment_blends)
            if np.any(has_collar):
                collar_rows = blended_rows[has_collar]
                collar_parameters = blend[has_collar]
                collar_attachment_blends = attachment_blends[has_collar]
                collar_current_indices = blended_current_indices[has_collar]
                collar_parent_indices = parent_indices[collar_current_indices]
                inside_collar = collar_parameters <= _SOFT_ATTACHMENT_COLLAR_FRACTION

                if np.any(inside_collar):
                    progress = collar_parameters[inside_collar] / _SOFT_ATTACHMENT_COLLAR_FRACTION
                    progress = progress * progress * (3.0 - 2.0 * progress)
                    grandparent_weight = (1.0 - collar_attachment_blends[inside_collar]) * (1.0 - progress)
                    rows = collar_rows[inside_collar]
                    chunk_indices[rows, 0] = grandparent_indices[collar_current_indices[inside_collar]]
                    chunk_indices[rows, 1] = collar_parent_indices[inside_collar]
                    chunk_weights[rows, 0] = grandparent_weight
                    chunk_weights[rows, 1] = 1.0 - grandparent_weight

                after_collar = ~inside_collar
                if np.any(after_collar):
                    progress = (
                        collar_parameters[after_collar] - _SOFT_ATTACHMENT_COLLAR_FRACTION
                    ) / (1.0 - _SOFT_ATTACHMENT_COLLAR_FRACTION)
                    rows = collar_rows[after_collar]
                    chunk_indices[rows, 0] = collar_parent_indices[after_collar]
                    chunk_indices[rows, 1] = collar_current_indices[after_collar]
                    chunk_weights[rows, 0] = 1.0 - progress
                    chunk_weights[rows, 1] = progress

        indices.extend(chunk_indices.ravel().tolist())
        weights.extend(chunk_weights.ravel().tolist())
    return replace(
        mesh,
        skel_joint_indices=tuple(indices),
        skel_joint_weights=tuple(weights),
        skel_element_size=2,
    )


def _apply_mesh_inherited_skinning(
    mesh: MeshData,
    skeleton: tuple[Joint, ...],
    *,
    max_influences: int,
    start_distributions: tuple[dict[int, float], ...] | None = None,
    starts=None,
    segments=None,
    inverse_lengths_squared=None,
    candidate_indices=None,
    candidate_weights=None,
    candidate_counts=None,
) -> MeshData:
    import numpy as np

    if mesh.skel_element_size != 1:
        raise ValueError("Inherited skinning requires the normalized single-influence base mesh.")
    if len(mesh.skel_joint_indices) != len(mesh.points):
        raise ValueError("Inherited skinning requires one normalized joint index per base-mesh point.")
    if max_influences not in {3, 4}:
        raise ValueError("Inherited skinning supports three or four influences.")

    joint_count = len(skeleton)
    if starts is None or segments is None or inverse_lengths_squared is None:
        starts, segments, inverse_lengths_squared, _parent_indices = _joint_geometry(skeleton)
    if start_distributions is None:
        start_distributions = _inherited_start_distributions(
            skeleton,
            max_influences,
            starts=starts,
            segments=segments,
            inverse_lengths_squared=inverse_lengths_squared,
        )
    if candidate_indices is None or candidate_weights is None or candidate_counts is None:
        candidate_indices, candidate_weights, candidate_counts = _inherited_candidate_tables(
            start_distributions,
            max_influences,
        )

    output_indices: list[int] = []
    output_weights: list[float] = []
    point_count = len(mesh.points)
    for start_index in range(0, point_count, _DENSE_VERTEX_CHUNK_SIZE):
        end_index = min(point_count, start_index + _DENSE_VERTEX_CHUNK_SIZE)
        chunk_count = end_index - start_index
        current_indices = np.asarray(mesh.skel_joint_indices[start_index:end_index], dtype=np.int64)
        invalid = current_indices[(current_indices < 0) | (current_indices >= joint_count)]
        if len(invalid):
            raise ValueError(f"Inherited skinning cannot resolve joint index {int(invalid[0])}.")
        points = np.fromiter(
            (
                coordinate
                for point in mesh.points[start_index:end_index]
                for coordinate in (point.x, point.y, point.z)
            ),
            dtype=np.float64,
            count=chunk_count * 3,
        ).reshape((chunk_count, 3))
        chunk_indices, chunk_weights = _evaluate_inherited_influences(
            current_indices,
            points,
            max_influences=max_influences,
            starts=starts,
            segments=segments,
            inverse_lengths_squared=inverse_lengths_squared,
            candidate_indices=candidate_indices,
            candidate_weights=candidate_weights,
            candidate_counts=candidate_counts,
            pad_with_current=True,
        )

        output_indices.extend(chunk_indices.ravel().tolist())
        output_weights.extend(chunk_weights.ravel().tolist())

    return replace(
        mesh,
        skel_joint_indices=tuple(output_indices),
        skel_joint_weights=tuple(output_weights),
        skel_element_size=max_influences,
    )


def _inherited_start_distributions(
    skeleton: tuple[Joint, ...],
    max_influences: int,
    *,
    starts=None,
    segments=None,
    inverse_lengths_squared=None,
    parent_indices=None,
) -> tuple[dict[int, float], ...]:
    if starts is None or segments is None or inverse_lengths_squared is None or parent_indices is None:
        starts, segments, inverse_lengths_squared, parent_indices = _joint_geometry(skeleton)
    distributions: list[dict[int, float] | None] = [None] * len(skeleton)

    def resolve(index: int, visiting: set[int]) -> dict[int, float]:
        cached = distributions[index]
        if cached is not None:
            return cached
        if index in visiting:
            raise ValueError("Inherited skinning cannot resolve a cyclic skeleton hierarchy.")
        parent_index = parent_indices[index]
        if parent_index < 0:
            distribution = {index: 1.0}
        else:
            visiting.add(index)
            parent_start = resolve(parent_index, visiting)
            visiting.remove(index)
            inverse_length_squared = inverse_lengths_squared[parent_index]
            if inverse_length_squared <= 0.0:
                distribution = {parent_index: 1.0}
            else:
                position = starts[index]
                parent_start_position = starts[parent_index]
                parent_segment = segments[parent_index]
                parameter = max(
                    0.0,
                    min(
                        1.0,
                        (
                            (position[0] - parent_start_position[0]) * parent_segment[0]
                            + (position[1] - parent_start_position[1]) * parent_segment[1]
                            + (position[2] - parent_start_position[2]) * parent_segment[2]
                        ) * inverse_length_squared,
                    ),
                )
                distribution = {
                    joint: weight * (1.0 - parameter)
                    for joint, weight in parent_start.items()
                    if weight * (1.0 - parameter) > _EPSILON
                }
                distribution[parent_index] = distribution.get(parent_index, 0.0) + parameter
            distribution = _truncate_distribution(distribution, max_influences)
        distributions[index] = distribution
        return distribution

    for index in range(len(skeleton)):
        resolve(index, set())
    return tuple(distribution or {} for distribution in distributions)


def _inherited_candidate_tables(
    start_distributions: tuple[dict[int, float], ...],
    max_influences: int,
):
    import numpy as np

    width = max_influences + 1
    indices = np.empty((len(start_distributions), width), dtype=np.int64)
    weights = np.zeros((len(start_distributions), width), dtype=np.float64)
    counts = np.empty(len(start_distributions), dtype=np.int64)
    for current_index, distribution in enumerate(start_distributions):
        candidates = sorted(set(distribution) | {current_index})
        count = len(candidates)
        counts[current_index] = min(count, max_influences)
        indices[current_index, :count] = candidates
        indices[current_index, count:] = current_index
        weights[current_index, :count] = tuple(distribution.get(candidate, 0.0) for candidate in candidates)
    return indices, weights, counts


def _evaluate_inherited_influences(
    current_indices,
    positions,
    *,
    max_influences: int,
    starts,
    segments,
    inverse_lengths_squared,
    candidate_indices,
    candidate_weights,
    candidate_counts,
    pad_with_current: bool,
):
    import numpy as np

    inverse = inverse_lengths_squared[current_indices]
    parameters = np.ones(len(current_indices), dtype=np.float64)
    active = inverse > 0.0
    parameters[active] = np.clip(
        np.sum(
            (positions[active] - starts[current_indices[active]]) * segments[current_indices[active]],
            axis=1,
        ) * inverse[active],
        0.0,
        1.0,
    )
    indices = candidate_indices[current_indices]
    weights = candidate_weights[current_indices] * (1.0 - parameters[:, None])
    current_slots = np.argmax(indices == current_indices[:, None], axis=1)
    weights[np.arange(len(current_indices)), current_slots] += parameters
    if not pad_with_current:
        # Repeated-part bindings historically discard numerically empty influences
        # before sorting and normalization. Preserve that observable token layout.
        weights[weights <= _EPSILON] = 0.0
    order = np.argsort(-weights, axis=1, kind="stable")[:, :max_influences]
    chosen_indices = np.take_along_axis(indices, order, axis=1)
    chosen_weights = np.take_along_axis(weights, order, axis=1)
    chosen_weights /= np.sum(chosen_weights, axis=1, keepdims=True)
    chosen_counts = (
        candidate_counts[current_indices]
        if pad_with_current
        else np.maximum(np.sum(chosen_weights > _EPSILON, axis=1), 1)
    )
    padding = np.arange(max_influences)[None, :] >= chosen_counts[:, None]
    pad_indices = current_indices if pad_with_current else chosen_indices[
        np.arange(len(chosen_indices)), chosen_counts - 1
    ]
    chosen_indices[padding] = np.broadcast_to(pad_indices[:, None], chosen_indices.shape)[padding]
    return chosen_indices, chosen_weights


def _part_inputs(
    parts: tuple[RepeatedPartInstance, ...],
    joint_index: dict[str, int],
    mode: str,
):
    import numpy as np

    current_indices = np.empty(len(parts), dtype=np.int64)
    positions = np.empty((len(parts), 3), dtype=np.float64)
    for index, part in enumerate(parts):
        if part.binding.element_size != 1:
            raise ValueError(f"{mode} requires one normalized joint binding for repeated part {part.name!r}.")
        current_index = joint_index.get(part.binding.joint_tokens[0])
        if current_index is None:
            raise ValueError(f"{mode} cannot resolve repeated part {part.name!r} joint binding.")
        current_indices[index] = current_index
        position = part.position
        positions[index] = (position.x, position.y, position.z)
    return current_indices, positions


def _joint_geometry(
    skeleton: tuple[Joint, ...],
    joint_index: dict[str, int] | None = None,
):
    import numpy as np

    if joint_index is None:
        joint_index = {joint.name: index for index, joint in enumerate(skeleton)}
    starts = np.empty((len(skeleton), 3), dtype=np.float64)
    segments = np.zeros((len(skeleton), 3), dtype=np.float64)
    inverse_lengths_squared = np.zeros(len(skeleton), dtype=np.float64)
    parent_indices = np.full(len(skeleton), -1, dtype=np.int64)
    for index, joint in enumerate(skeleton):
        start = joint.bind_transform.rows[3]
        starts[index] = start[:3]
        end_transform = joint.bind_end_transform
        if end_transform is not None:
            end = end_transform.rows[3]
            segment = (end[0] - start[0], end[1] - start[1], end[2] - start[2])
            segments[index] = segment
            length_squared = segment[0] * segment[0] + segment[1] * segment[1] + segment[2] * segment[2]
            if length_squared > _EPSILON:
                inverse_lengths_squared[index] = 1.0 / length_squared
        if joint.parent is not None:
            parent_indices[index] = joint_index.get(joint.parent, -1)
    return starts, segments, inverse_lengths_squared, parent_indices


def _truncate_distribution(distribution: dict[int, float], max_influences: int) -> dict[int, float]:
    ordered = sorted(distribution.items(), key=lambda item: (-item[1], item[0]))[:max_influences]
    total = sum(weight for _joint, weight in ordered)
    if total <= _EPSILON:
        raise ValueError("Skinning influence distribution has no positive weight.")
    return {joint: weight / total for joint, weight in ordered}


def _transform(x_axis: Vector3, y_axis: Vector3, z_axis: Vector3, translate: Vector3) -> Matrix4d:
    return Matrix4d(rows=(
        (x_axis.x, x_axis.y, x_axis.z, 0.0),
        (y_axis.x, y_axis.y, y_axis.z, 0.0),
        (z_axis.x, z_axis.y, z_axis.z, 0.0),
        (translate.x, translate.y, translate.z, 1.0),
    ))


def _multiply_quaternions(left: Quaternion, right: Quaternion) -> Quaternion:
    return Quaternion(
        left.real * right.real - left.i * right.i - left.j * right.j - left.k * right.k,
        left.real * right.i + left.i * right.real + left.j * right.k - left.k * right.j,
        left.real * right.j - left.i * right.k + left.j * right.real + left.k * right.i,
        left.real * right.k + left.i * right.j - left.j * right.i + left.k * right.real,
    )


def _multiply(left: Matrix4d, right: Matrix4d) -> Matrix4d:
    right_rows = right.rows
    rows = []
    for left_row in left.rows:
        rows.append(
            (
                left_row[0] * right_rows[0][0]
                + left_row[1] * right_rows[1][0]
                + left_row[2] * right_rows[2][0]
                + left_row[3] * right_rows[3][0],
                left_row[0] * right_rows[0][1]
                + left_row[1] * right_rows[1][1]
                + left_row[2] * right_rows[2][1]
                + left_row[3] * right_rows[3][1],
                left_row[0] * right_rows[0][2]
                + left_row[1] * right_rows[1][2]
                + left_row[2] * right_rows[2][2]
                + left_row[3] * right_rows[3][2],
                left_row[0] * right_rows[0][3]
                + left_row[1] * right_rows[1][3]
                + left_row[2] * right_rows[2][3]
                + left_row[3] * right_rows[3][3],
            )
        )
    return Matrix4d(
        rows=tuple(rows)
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
    import numpy as np

    width = mesh.skel_element_size
    if width not in {1, 2, 3, 4}:
        return [_error("invalid_base_mesh_skinning_width", f"Base mesh has {width} influences per vertex; expected one to four.")]
    expected = len(mesh.points) * width
    if len(mesh.skel_joint_indices) != expected or len(mesh.skel_joint_weights) != expected:
        return [
            _error(
                "invalid_base_mesh_skinning_shape",
                f"Base mesh has {len(mesh.skel_joint_indices)} indices and {len(mesh.skel_joint_weights)} weights; expected {expected} of each.",
            )
        ]
    point_count = len(mesh.points)
    for start_point in range(0, point_count, _DENSE_VERTEX_CHUNK_SIZE):
        end_point = min(point_count, start_point + _DENSE_VERTEX_CHUNK_SIZE)
        start_value = start_point * width
        end_value = end_point * width
        indices = np.asarray(mesh.skel_joint_indices[start_value:end_value], dtype=np.int64).reshape((-1, width))
        weights = np.asarray(mesh.skel_joint_weights[start_value:end_value], dtype=np.float64).reshape((-1, width))
        invalid_joints = np.any((indices < 0) | (indices >= skeleton_size), axis=1)
        invalid_weights = (
            np.any(~np.isfinite(weights), axis=1)
            | np.any((weights < -_TRANSFORM_TOLERANCE) | (weights > 1.0 + _TRANSFORM_TOLERANCE), axis=1)
            | (np.abs(np.sum(weights, axis=1) - 1.0) > _TRANSFORM_TOLERANCE)
        )
        invalid_rows = np.flatnonzero(invalid_joints | invalid_weights)
        if not len(invalid_rows):
            continue

        local_point = int(invalid_rows[0])
        point_index = start_point + local_point
        if invalid_joints[local_point]:
            invalid_index = next(
                index
                for index in mesh.skel_joint_indices[point_index * width:(point_index + 1) * width]
                if index < 0 or index >= skeleton_size
            )
            return [
                _error(
                    "invalid_base_mesh_joint_index",
                    f"Base mesh vertex {point_index} references joint index {invalid_index}; skeleton size is {skeleton_size}.",
                )
            ]
        point_weights = mesh.skel_joint_weights[point_index * width:(point_index + 1) * width]
        return [
            _error(
                "invalid_base_mesh_joint_weights",
                f"Base mesh vertex {point_index} {_weight_issue(point_weights)}.",
            )
        ]
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
    for row in matrix.rows:
        for value in row:
            if not math.isfinite(value):
                return False
    return True


def _matrix_has_shape(matrix: Matrix4d) -> bool:
    rows = matrix.rows
    return (
        len(rows) == 4
        and len(rows[0]) == 4
        and len(rows[1]) == 4
        and len(rows[2]) == 4
        and len(rows[3]) == 4
    )


def _is_rigid_basis(matrix: Matrix4d) -> bool:
    x_axis, y_axis, z_axis = matrix.rows[:3]
    if (
        abs(x_axis[0] * x_axis[0] + x_axis[1] * x_axis[1] + x_axis[2] * x_axis[2] - 1.0)
        > _TRANSFORM_TOLERANCE
        or abs(y_axis[0] * y_axis[0] + y_axis[1] * y_axis[1] + y_axis[2] * y_axis[2] - 1.0)
        > _TRANSFORM_TOLERANCE
        or abs(z_axis[0] * z_axis[0] + z_axis[1] * z_axis[1] + z_axis[2] * z_axis[2] - 1.0)
        > _TRANSFORM_TOLERANCE
    ):
        return False
    if (
        abs(x_axis[0] * y_axis[0] + x_axis[1] * y_axis[1] + x_axis[2] * y_axis[2]) > _TRANSFORM_TOLERANCE
        or abs(x_axis[0] * z_axis[0] + x_axis[1] * z_axis[1] + x_axis[2] * z_axis[2])
        > _TRANSFORM_TOLERANCE
        or abs(y_axis[0] * z_axis[0] + y_axis[1] * z_axis[1] + y_axis[2] * z_axis[2])
        > _TRANSFORM_TOLERANCE
    ):
        return False
    determinant = (
        x_axis[0] * (y_axis[1] * z_axis[2] - y_axis[2] * z_axis[1])
        + x_axis[1] * (y_axis[2] * z_axis[0] - y_axis[0] * z_axis[2])
        + x_axis[2] * (y_axis[0] * z_axis[1] - y_axis[1] * z_axis[0])
    )
    if abs(determinant - 1.0) > _TRANSFORM_TOLERANCE:
        return False
    return (
        all(abs(matrix.rows[row][3]) <= _TRANSFORM_TOLERANCE for row in range(3))
        and abs(matrix.rows[3][3] - 1.0) <= _TRANSFORM_TOLERANCE
    )


def _matrices_close(left: Matrix4d, right: Matrix4d) -> bool:
    for left_row, right_row in zip(left.rows, right.rows):
        for left_value, right_value in zip(left_row, right_row):
            if abs(left_value - right_value) > _TRANSFORM_TOLERANCE:
                return False
    return True


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
