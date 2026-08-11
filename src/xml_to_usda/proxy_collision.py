"""Trunk collision fitting for Proxy Mesh assets."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

import numpy as np

from .collision_primitives import build_box_collision_mesh, build_capsule_collision_mesh, collision_axis_basis
from .fracture_service import FractureError, select_skeleton_stem_axes
from .models import CanonicalTreeModel, Joint, MeshData, Vector3


_SelectedAxis = tuple[tuple[Vector3, ...], frozenset[str], float]


class ProxyCollisionMode(str, Enum):
    BOX = "box"
    CAPSULE = "capsule"


@dataclass(frozen=True)
class ProxyCollisionSettings:
    enabled: bool = True
    mode: ProxyCollisionMode = ProxyCollisionMode.BOX
    height_multiplier: float = 0.5
    width_multiplier: float = 1.0
    one_per_stem: bool = False


@dataclass(frozen=True)
class ProxyCollisionSource:
    skeleton: tuple[Joint, ...]
    stem_axes: tuple[tuple[str, ...], ...]
    points: tuple[Vector3, ...]
    point_joint_indices: tuple[int, ...]


class ProxyCollisionError(ValueError):
    """Raised when one safe trunk collision primitive cannot be fitted."""


def validated_proxy_collision_settings(settings: ProxyCollisionSettings | None) -> ProxyCollisionSettings:
    resolved = settings or ProxyCollisionSettings()
    try:
        mode = ProxyCollisionMode(resolved.mode)
    except ValueError as exc:
        raise ProxyCollisionError(f"Unsupported proxy collision mode: {resolved.mode!r}.") from exc
    height = float(resolved.height_multiplier)
    width = float(resolved.width_multiplier)
    if not 0.0 <= height <= 1.0:
        raise ProxyCollisionError("Proxy collision height multiplier must be between 0 and 1.")
    if not 0.0 <= width <= 10.0:
        raise ProxyCollisionError("Proxy collision width multiplier must be between 0 and 10.")
    return ProxyCollisionSettings(
        enabled=bool(resolved.enabled),
        mode=mode,
        height_multiplier=height,
        width_multiplier=width,
        one_per_stem=bool(resolved.one_per_stem),
    )


def build_proxy_collision_meshes(
    model: CanonicalTreeModel,
    settings: ProxyCollisionSettings | None,
    *,
    render_mesh_name: str = "ProxyMesh",
) -> tuple[MeshData, ...]:
    resolved = validated_proxy_collision_settings(settings)
    if not resolved.enabled or resolved.height_multiplier == 0.0 or resolved.width_multiplier == 0.0:
        return ()
    return _build_proxy_collision_meshes_from_source(
        prepare_proxy_collision_source(model),
        resolved,
        render_mesh_name=render_mesh_name,
    )


def prepare_proxy_collision_source(model: CanonicalTreeModel) -> ProxyCollisionSource:
    if not model.skeleton:
        raise ProxyCollisionError("Proxy collision requires a skeleton.")
    if model.base_mesh is None:
        raise ProxyCollisionError("Proxy collision requires a base mesh.")

    try:
        stem_axes = select_skeleton_stem_axes(model)
    except FractureError as exc:
        raise ProxyCollisionError(f"Proxy collision could not resolve the main skeleton axis: {exc}") from exc
    if not stem_axes or not all(stem_axes):
        raise ProxyCollisionError("Proxy collision could not resolve a skeleton stem axis.")

    joint_by_name = {joint.name: joint for joint in model.skeleton}
    primary_axes = tuple(_primary_stem_axis(axis, joint_by_name) for axis in stem_axes)
    stem_joint_indices = tuple(
        index
        for index, joint in enumerate(model.skeleton)
        if any(joint.name in axis for axis in primary_axes)
    )
    source_index_by_model_index = {
        model_index: source_index for source_index, model_index in enumerate(stem_joint_indices)
    }
    points, point_joint_indices = _stem_mesh_points(model, source_index_by_model_index)
    return ProxyCollisionSource(
        skeleton=tuple(model.skeleton[index] for index in stem_joint_indices),
        stem_axes=primary_axes,
        points=points,
        point_joint_indices=point_joint_indices,
    )


def build_proxy_collision_meshes_from_source(
    source: ProxyCollisionSource,
    settings: ProxyCollisionSettings | None,
    *,
    render_mesh_name: str = "ProxyMesh",
) -> tuple[MeshData, ...]:
    resolved = validated_proxy_collision_settings(settings)
    if not resolved.enabled or resolved.height_multiplier == 0.0 or resolved.width_multiplier == 0.0:
        return ()
    return _build_proxy_collision_meshes_from_source(source, resolved, render_mesh_name=render_mesh_name)


def _build_proxy_collision_meshes_from_source(
    source: ProxyCollisionSource,
    settings: ProxyCollisionSettings,
    *,
    render_mesh_name: str,
) -> tuple[MeshData, ...]:
    if not source.skeleton or not source.stem_axes:
        raise ProxyCollisionError("Proxy collision source has no skeleton stem axes.")
    joint_by_name = {joint.name: joint for joint in source.skeleton}
    selected_axes = tuple(
        _selected_axis(tuple(joint_by_name[token] for token in tokens if token in joint_by_name), settings.height_multiplier)
        for tokens in source.stem_axes
    )
    groups = tuple((selected_axis,) for selected_axis in selected_axes) if settings.one_per_stem else (selected_axes,)
    return tuple(
        _build_collision_for_axes(source, group, settings, render_mesh_name=render_mesh_name, primitive_index=index)
        for index, group in enumerate(groups)
    )


def _build_collision_for_axes(
    source: ProxyCollisionSource,
    selected_axes: tuple[_SelectedAxis, ...],
    settings: ProxyCollisionSettings,
    *,
    render_mesh_name: str,
    primitive_index: int,
) -> MeshData:
    selected_points = tuple(point for points, _tokens, _length in selected_axes for point in points)
    selected_tokens = frozenset(token for _points, tokens, _length in selected_axes for token in tokens)
    expected_direction = Vector3(
        sum(points[-1].x - points[0].x for points, _tokens, _length in selected_axes),
        sum(points[-1].y - points[0].y for points, _tokens, _length in selected_axes),
        sum(points[-1].z - points[0].z for points, _tokens, _length in selected_axes),
    )
    fit_points = selected_points
    if len(selected_axes) > 1:
        fit_points = tuple(
            Vector3(point.x - points[0].x, point.y - points[0].y, point.z - points[0].z)
            for points, _tokens, _length in selected_axes
            for point in points
        )
    direction = _fitted_axis(fit_points, expected_direction)
    if len(selected_axes) == 1:
        start = selected_axes[0][0][0]
        selected_length = selected_axes[0][2]
        end = Vector3(
            start.x + direction.x * selected_length,
            start.y + direction.y * selected_length,
            start.z + direction.z * selected_length,
        )
    else:
        start, end = _fitted_span(selected_points, direction)
    width_tokens = selected_tokens
    if len(source.stem_axes) > 1 and len(selected_axes) == 1 and len(selected_tokens) > 1:
        # A shared multistem root may own base vertices from every stem.
        width_tokens = selected_tokens - {source.stem_axes[primitive_index][0]}
    trunk_points = _trunk_mesh_points(source, width_tokens)
    auto_width, transverse_offset = _transverse_aabb_width(trunk_points, start, direction)
    if len(selected_axes) > 1:
        start = _add(start, transverse_offset)
        end = _add(end, transverse_offset)
    width = auto_width * settings.width_multiplier
    if width <= 1e-8:
        raise ProxyCollisionError("Proxy collision trunk AABB has zero transverse width.")

    if settings.mode == ProxyCollisionMode.CAPSULE:
        return build_capsule_collision_mesh(
            f"UCP_{render_mesh_name}_{primitive_index:02d}", start, end, width * 0.5
        )
    return build_box_collision_mesh(f"UBX_{render_mesh_name}_{primitive_index:02d}", start, end, width)


def _selected_axis(
    joints: tuple[Joint, ...],
    height_multiplier: float,
) -> _SelectedAxis:
    if not joints:
        raise ProxyCollisionError("Proxy collision main skeleton axis is empty.")
    points = [joints[0].bind_translate]
    edge_tokens: list[str] = []
    for joint in joints[1:]:
        _append_axis_point(points, edge_tokens, joint.bind_translate, joint.name)
    terminal_end = joints[-1].bind_end_translate
    if terminal_end is not None:
        _append_axis_point(points, edge_tokens, terminal_end, joints[-1].name)
    if len(points) < 2:
        raise ProxyCollisionError("Proxy collision main skeleton axis has no measurable length.")

    lengths = tuple(_distance(points[index], points[index + 1]) for index in range(len(points) - 1))
    full_length = sum(lengths)
    selected_length = full_length * height_multiplier
    if selected_length <= 1e-8:
        raise ProxyCollisionError("Proxy collision selected skeleton height has no measurable length.")

    selected = [points[0]]
    selected_tokens = {joints[0].name}
    remaining = selected_length
    for index, edge_length in enumerate(lengths):
        if edge_length <= 1e-8:
            continue
        selected_tokens.add(edge_tokens[index])
        if remaining >= edge_length:
            selected.append(points[index + 1])
            remaining -= edge_length
            continue
        ratio = remaining / edge_length
        selected.append(_lerp(points[index], points[index + 1], ratio))
        remaining = 0.0
        break
    if len(selected) < 2:
        raise ProxyCollisionError("Proxy collision selected skeleton height has no measurable segment.")
    return tuple(selected), frozenset(selected_tokens), selected_length


def _append_axis_point(points: list[Vector3], edge_tokens: list[str], point: Vector3, token: str) -> None:
    if _distance(points[-1], point) <= 1e-8:
        return
    points.append(point)
    edge_tokens.append(token)


def _fitted_axis(points: tuple[Vector3, ...], expected_direction: Vector3) -> Vector3:
    values = np.asarray([(point.x, point.y, point.z) for point in points], dtype=float)
    centered = values - values.mean(axis=0)
    try:
        _eigenvalues, eigenvectors = np.linalg.eigh(centered.T @ centered)
    except np.linalg.LinAlgError as exc:
        raise ProxyCollisionError("Proxy collision could not fit a stable trunk axis.") from exc
    axis = eigenvectors[:, -1]
    expected = np.asarray((expected_direction.x, expected_direction.y, expected_direction.z), dtype=float)
    if float(np.dot(axis, expected)) < 0.0:
        axis = -axis
    length = float(np.linalg.norm(axis))
    if length <= 1e-12 or not np.isfinite(axis).all():
        raise ProxyCollisionError("Proxy collision could not fit a stable trunk axis.")
    return Vector3(float(axis[0] / length), float(axis[1] / length), float(axis[2] / length))


def _primary_stem_axis(axis: tuple[str, ...], joint_by_name: dict[str, Joint]) -> tuple[str, ...]:
    joints = tuple(joint_by_name[token] for token in axis if token in joint_by_name)
    if not joints:
        raise ProxyCollisionError("Proxy collision main skeleton axis is empty.")
    generator_level = joints[0].generator_level
    if generator_level is None:
        return tuple(joint.name for joint in joints)
    primary: list[str] = []
    for joint in joints:
        if joint.generator_level != generator_level:
            break
        primary.append(joint.name)
    return tuple(primary) or (joints[0].name,)


def _stem_mesh_points(
    model: CanonicalTreeModel,
    source_index_by_model_index: dict[int, int],
) -> tuple[tuple[Vector3, ...], tuple[int, ...]]:
    mesh = model.base_mesh
    assert mesh is not None
    element_size = int(mesh.skel_element_size)
    expected = len(mesh.points) * element_size
    if element_size <= 0 or len(mesh.skel_joint_indices) < expected or len(mesh.skel_joint_weights) < expected:
        raise ProxyCollisionError("Proxy collision requires complete base-mesh skin binding data.")
    selected_points: list[Vector3] = []
    selected_joint_indices: list[int] = []
    for point_index, point in enumerate(mesh.points):
        offset = point_index * element_size
        influence = (
            0
            if element_size == 1
            else max(range(element_size), key=lambda slot: float(mesh.skel_joint_weights[offset + slot]))
        )
        joint_index = int(mesh.skel_joint_indices[offset + influence])
        if not 0 <= joint_index < len(model.skeleton):
            raise ProxyCollisionError(f"Proxy collision base-mesh point {point_index} references invalid joint {joint_index}.")
        source_joint_index = source_index_by_model_index.get(joint_index)
        if source_joint_index is not None:
            selected_points.append(point)
            selected_joint_indices.append(source_joint_index)
    if not selected_points:
        raise ProxyCollisionError("Proxy collision found no base-mesh vertices owned by the skeleton stems.")
    return tuple(selected_points), tuple(selected_joint_indices)


def _trunk_mesh_points(source: ProxyCollisionSource, selected_tokens: frozenset[str]) -> tuple[Vector3, ...]:
    selected_joint_indices = {
        index for index, joint in enumerate(source.skeleton) if joint.name in selected_tokens
    }
    selected = tuple(
        point
        for point, joint_index in zip(source.points, source.point_joint_indices, strict=True)
        if joint_index in selected_joint_indices
    )
    if not selected:
        raise ProxyCollisionError("Proxy collision found no base-mesh vertices owned by the selected trunk segment.")
    return selected


def _fitted_span(points: tuple[Vector3, ...], axis: Vector3) -> tuple[Vector3, Vector3]:
    origin = Vector3(
        sum(point.x for point in points) / len(points),
        sum(point.y for point in points) / len(points),
        sum(point.z for point in points) / len(points),
    )
    projections = tuple(_dot(Vector3(point.x - origin.x, point.y - origin.y, point.z - origin.z), axis) for point in points)
    return (
        _add(origin, _scale(axis, min(projections))),
        _add(origin, _scale(axis, max(projections))),
    )


def _transverse_aabb_width(
    points: tuple[Vector3, ...],
    origin: Vector3,
    axis: Vector3,
) -> tuple[float, Vector3]:
    u, v = collision_axis_basis(axis)
    u_values = []
    v_values = []
    for point in points:
        offset = Vector3(point.x - origin.x, point.y - origin.y, point.z - origin.z)
        u_values.append(_dot(offset, u))
        v_values.append(_dot(offset, v))
    u_min, u_max = min(u_values), max(u_values)
    v_min, v_max = min(v_values), max(v_values)
    offset = _add(_scale(u, (u_min + u_max) * 0.5), _scale(v, (v_min + v_max) * 0.5))
    return max(u_max - u_min, v_max - v_min), offset


def _distance(a: Vector3, b: Vector3) -> float:
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def _lerp(a: Vector3, b: Vector3, value: float) -> Vector3:
    return Vector3(a.x + (b.x - a.x) * value, a.y + (b.y - a.y) * value, a.z + (b.z - a.z) * value)


def _dot(a: Vector3, b: Vector3) -> float:
    return a.x * b.x + a.y * b.y + a.z * b.z


def _add(a: Vector3, b: Vector3) -> Vector3:
    return Vector3(a.x + b.x, a.y + b.y, a.z + b.z)


def _scale(value: Vector3, factor: float) -> Vector3:
    return Vector3(value.x * factor, value.y * factor, value.z * factor)
