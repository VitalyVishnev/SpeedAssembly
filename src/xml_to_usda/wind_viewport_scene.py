"""Wind Preview adapter for the Qt-free viewport scene contract."""

from __future__ import annotations

from array import array
from dataclasses import dataclass

from .dynamic_wind import default_group_settings
from .geometry_buffers import geometry_buffer_from_mesh
from .models import (
    CanonicalTreeModel,
    Color4,
    DynamicWindData,
    DynamicWindJointAssignment,
    GeometryBuffer,
    Joint,
    MeshData,
    Prototype,
    Vector3,
)
from .viewport_scene import (
    ViewportBoneSegment,
    ViewportBounds,
    ViewportDrawCall,
    ViewportMeshBatch,
    ViewportScene,
    ViewportStats,
    geometry_triangle_count,
    transformed_draw_bounds,
)


NORMAL_ALPHA = 0.88
SELECTED_ALPHA = 1.0
MUTED_ALPHA = 0.14
AUTO_WIND_GROUP_MIN_COUNT = 1
AUTO_WIND_GROUP_MAX_COUNT = 10
AUTO_CONTINUATION_EPSILON = 1e-5


@dataclass(frozen=True)
class WindViewportGroup:
    group_index: int
    branch_order: int
    label: str
    color: Color4
    joint_tokens: tuple[str, ...]


@dataclass(frozen=True)
class WindViewportSelection:
    group_index: int | None = None
    subtree_root_token: str | None = None


def build_wind_viewport_groups(
    dynamic_wind: DynamicWindData,
    *,
    label_kind: str = "Generator level",
) -> tuple[WindViewportGroup, ...]:
    assignments_by_group: dict[int, list[str]] = {}
    for assignment in dynamic_wind.joint_assignments:
        assignments_by_group.setdefault(assignment.simulation_group_index, []).append(assignment.joint_name)
    groups: list[WindViewportGroup] = []
    for group in sorted(dynamic_wind.simulation_groups, key=lambda item: item.group_index):
        groups.append(
            WindViewportGroup(
                group_index=group.group_index,
                branch_order=group.branch_order,
                label=f"Group {group.group_index} ({label_kind} {group.branch_order})",
                color=_group_color(group.group_index),
                joint_tokens=tuple(assignments_by_group.get(group.group_index, ())),
            )
        )
    return tuple(groups)


def build_auto_wind_viewport_data(
    skeleton: tuple[Joint, ...],
    group_count: int,
    *,
    continuous_branch_orders: frozenset[int] | set[int] | tuple[int, ...] = (),
) -> DynamicWindData:
    if not skeleton:
        return DynamicWindData(joint_assignments=(), simulation_groups=())
    clamped_group_count = max(AUTO_WIND_GROUP_MIN_COUNT, min(AUTO_WIND_GROUP_MAX_COUNT, int(group_count)))
    branch_orders = _auto_branch_order_depths(skeleton, continuous_branch_orders=frozenset(continuous_branch_orders))
    effective_group_count = min(clamped_group_count, max(branch_orders.values(), default=0) + 1)
    joint_assignments = tuple(
        DynamicWindJointAssignment(
            joint_name=joint.name,
            simulation_group_index=min(branch_orders[joint.name], effective_group_count - 1),
            branch_order=min(branch_orders[joint.name], effective_group_count - 1),
        )
        for joint in skeleton
    )
    return DynamicWindData(
        joint_assignments=joint_assignments,
        simulation_groups=default_group_settings(tuple(range(effective_group_count))),
    )


def build_wind_viewport_scene(
    model: CanonicalTreeModel,
    dynamic_wind: DynamicWindData,
    *,
    selection: WindViewportSelection | None = None,
) -> ViewportScene:
    groups = build_wind_viewport_groups(dynamic_wind)
    group_by_joint = _group_by_joint(dynamic_wind)
    color_by_group = {group.group_index: group.color for group in groups}
    selected_joints = _selected_joint_tokens(model.skeleton, group_by_joint, selection)

    batches: list[ViewportMeshBatch] = []
    draw_calls: list[ViewportDrawCall] = []
    uploaded_triangles = 0
    logical_triangles = 0

    if model.base_mesh is not None:
        for joint_token, face_indices in sorted(_base_faces_by_joint(model.base_mesh, model.skeleton).items()):
            if not face_indices:
                continue
            group_index = _require_group(group_by_joint, joint_token)
            mesh = _slice_mesh_faces(model.base_mesh, tuple(face_indices), name=f"WindBase_{joint_token}")
            batch_id = f"wind:base:{joint_token}"
            batches.append(
                ViewportMeshBatch(
                    batch_id=batch_id,
                    name=mesh.name,
                    mesh=mesh,
                    color=_selection_color(color_by_group[group_index], selection, group_index, joint_token, selected_joints),
                    selectable_id=f"wind:joint:{joint_token}",
                )
            )
            draw_calls.append(
                ViewportDrawCall(
                    draw_id=f"{batch_id}:draw",
                    batch_id=batch_id,
                    tint=_selection_color(color_by_group[group_index], selection, group_index, joint_token, selected_joints),
                    selectable_id=f"wind:joint:{joint_token}",
                    visibility_group="base_mesh",
                )
            )
            triangle_count = geometry_triangle_count(mesh)
            uploaded_triangles += triangle_count
            logical_triangles += triangle_count

    prototype_batches: set[str] = set()
    prototype_triangles: dict[str, int] = {}
    prototypes = {prototype.source_key: prototype for prototype in model.prototypes}
    visible_instance_count = 0
    for instance in sorted(model.repeated_parts, key=lambda item: item.name):
        joint_token = _instance_joint_token(instance.name, instance.binding.joint_tokens)
        group_index = _require_group(group_by_joint, joint_token)
        prototype = prototypes.get(instance.prototype_key)
        if prototype is None:
            raise ValueError(f"wind_preview_missing_prototype: repeated part {instance.name} references {instance.prototype_key}")
        batch_id = f"wind:prototype:{prototype.source_key}"
        if batch_id not in prototype_batches:
            prototype_batches.add(batch_id)
            prototype_mesh = _prototype_geometry(prototype)
            triangle_count = geometry_triangle_count(prototype_mesh)
            if triangle_count <= 0:
                raise ValueError(f"wind_preview_empty_prototype: prototype {prototype.source_name or prototype.source_key} has no faces")
            batches.append(
                ViewportMeshBatch(
                    batch_id=batch_id,
                    name=prototype.source_name or prototype.source_key,
                    mesh=prototype_mesh,
                    selectable_id=batch_id,
                )
            )
            prototype_triangles[prototype.source_key] = triangle_count
            uploaded_triangles += triangle_count
        color = _selection_color(color_by_group[group_index], selection, group_index, joint_token, selected_joints)
        draw_calls.append(
            ViewportDrawCall(
                draw_id=f"wind:instance:{instance.name}",
                batch_id=batch_id,
                translate=instance.position,
                orientation=instance.orientation,
                scale=instance.scale,
                tint=color,
                selectable_id=f"wind:instance:{instance.name}",
                visibility_group="repeated_parts",
            )
        )
        visible_instance_count += 1
        logical_triangles += prototype_triangles[prototype.source_key]

    bone_segments = _bone_segments(model.skeleton, group_by_joint, color_by_group, selection, selected_joints)
    if not draw_calls and not bone_segments:
        raise ValueError("wind_preview_empty_skeleton: wind preview requires geometry or skeleton bone segments.")
    return ViewportScene(
        scene_id=f"{model.metadata.source_path}:wind_preview",
        mesh_batches=tuple(batches),
        draw_calls=tuple(draw_calls),
        bounds=_bounds(tuple(batches), tuple(draw_calls), bone_segments),
        stats=ViewportStats(
            uploaded_triangles=uploaded_triangles,
            logical_triangles=logical_triangles,
            instance_count=visible_instance_count,
            batch_count=len(batches),
            draw_call_count=len(draw_calls),
        ),
        bone_segments=bone_segments,
    )


def build_wind_viewport_bone_segments(
    model: CanonicalTreeModel,
    dynamic_wind: DynamicWindData,
    *,
    selection: WindViewportSelection | None = None,
) -> tuple[ViewportBoneSegment, ...]:
    groups = build_wind_viewport_groups(dynamic_wind)
    group_by_joint = _group_by_joint(dynamic_wind)
    color_by_group = {group.group_index: group.color for group in groups}
    selected_joints = _selected_joint_tokens(model.skeleton, group_by_joint, selection)
    return _bone_segments(model.skeleton, group_by_joint, color_by_group, selection, selected_joints)


def subtree_root_from_pick_token(pick_token: str) -> str:
    token = pick_token.strip()
    if "->" in token and "@" in token:
        edge, _raw_t = token.rsplit("@", 1)
        _parent, child = edge.split("->", 1)
        return child.strip()
    return token


def _group_by_joint(dynamic_wind: DynamicWindData) -> dict[str, int]:
    return {
        assignment.joint_name: assignment.simulation_group_index
        for assignment in dynamic_wind.joint_assignments
    }


def _selected_joint_tokens(
    skeleton: tuple[Joint, ...],
    group_by_joint: dict[str, int],
    selection: WindViewportSelection | None,
) -> set[str]:
    if selection is None:
        return set()
    if selection.subtree_root_token:
        return _descendant_joint_tokens(skeleton, selection.subtree_root_token)
    if selection.group_index is not None:
        return {
            joint_token
            for joint_token, group_index in group_by_joint.items()
            if group_index == selection.group_index
        }
    return set()


def _descendant_joint_tokens(skeleton: tuple[Joint, ...], root_token: str) -> set[str]:
    joints_by_name = {joint.name: joint for joint in skeleton}
    if root_token not in joints_by_name:
        raise ValueError(f"wind_preview_unknown_subtree_root: {root_token}")
    children_by_parent: dict[str, list[str]] = {}
    for joint in skeleton:
        if joint.parent is not None:
            children_by_parent.setdefault(joint.parent, []).append(joint.name)
    selected: set[str] = set()
    pending = [root_token]
    while pending:
        token = pending.pop()
        if token in selected:
            continue
        selected.add(token)
        pending.extend(children_by_parent.get(token, ()))
    return selected


def _auto_branch_order_depths(
    skeleton: tuple[Joint, ...],
    *,
    continuous_branch_orders: frozenset[int] = frozenset(),
) -> dict[str, int]:
    joints_by_name = {joint.name: joint for joint in skeleton}
    joint_names = set(joints_by_name)
    children_by_parent: dict[str | None, list[str]] = {}
    for joint in skeleton:
        if joint.parent is not None and joint.parent not in joint_names:
            raise ValueError(f"wind_preview_auto_invalid_skeleton: joint {joint.name} references missing parent {joint.parent}.")
        children_by_parent.setdefault(joint.parent, []).append(joint.name)

    skeleton_order = {joint.name: index for index, joint in enumerate(skeleton)}
    root_tokens = tuple(
        joint.name
        for joint in sorted(skeleton, key=lambda item: skeleton_order[item.name])
        if joint.parent is None
    )
    if not root_tokens:
        raise ValueError("wind_preview_auto_no_trunk: automatic grouping needs at least one root or trunk joint.")

    depths: dict[str, int] = {}
    for root_token in root_tokens:
        _assign_branch_order(root_token, 0, children_by_parent, skeleton_order, joints_by_name, continuous_branch_orders, depths)

    missing = tuple(joint.name for joint in skeleton if joint.name not in depths)
    if missing:
        raise ValueError("wind_preview_auto_unreachable_joints: " + ", ".join(missing))
    return depths


def _assign_branch_order(
    joint_token: str,
    branch_order: int,
    children_by_parent: dict[str | None, list[str]],
    skeleton_order: dict[str, int],
    joints_by_name: dict[str, Joint],
    continuous_branch_orders: frozenset[int],
    depths: dict[str, int],
) -> None:
    current: str | None = joint_token
    while current is not None and current not in depths:
        depths[current] = branch_order
        children = sorted(children_by_parent.get(current, ()), key=lambda token: skeleton_order[token])
        if not children:
            return
        continuation = _branch_continuation_child(
            current,
            branch_order,
            children,
            skeleton_order,
            joints_by_name,
            continuous_branch_orders,
        )
        for side_child in children:
            if side_child == continuation:
                continue
            _assign_branch_order(
                side_child,
                branch_order + 1,
                children_by_parent,
                skeleton_order,
                joints_by_name,
                continuous_branch_orders,
                depths,
            )
        current = continuation


def _branch_continuation_child(
    joint_token: str,
    branch_order: int,
    children: list[str],
    skeleton_order: dict[str, int],
    joints_by_name: dict[str, Joint],
    continuous_branch_orders: frozenset[int],
) -> str | None:
    ordered_continuation = children[0] if skeleton_order[children[0]] == skeleton_order[joint_token] + 1 else None
    if ordered_continuation is not None or branch_order not in continuous_branch_orders:
        return ordered_continuation
    parent = joints_by_name[joint_token]
    for child_token in children:
        if _starts_at_parent_end(parent, joints_by_name[child_token]):
            return child_token
    return None


def _starts_at_parent_end(parent: Joint, child: Joint) -> bool:
    if parent.bind_end_translate is None:
        return False
    return _points_close(parent.bind_end_translate, child.bind_translate)


def _points_close(left: Vector3, right: Vector3) -> bool:
    return (
        abs(left.x - right.x) <= AUTO_CONTINUATION_EPSILON
        and abs(left.y - right.y) <= AUTO_CONTINUATION_EPSILON
        and abs(left.z - right.z) <= AUTO_CONTINUATION_EPSILON
    )


def _selection_color(
    base_color: Color4,
    selection: WindViewportSelection | None,
    group_index: int,
    joint_token: str,
    selected_joints: set[str],
) -> Color4:
    if selection is None or (selection.group_index is None and selection.subtree_root_token is None):
        return _with_alpha(base_color, NORMAL_ALPHA)
    if selection.group_index is not None and group_index == selection.group_index:
        return _with_alpha(base_color, SELECTED_ALPHA)
    if selection.subtree_root_token is not None and joint_token in selected_joints:
        return _with_alpha(base_color, SELECTED_ALPHA)
    return _with_alpha(base_color, MUTED_ALPHA)


def _base_faces_by_joint(mesh: MeshData, skeleton: tuple[Joint, ...]) -> dict[str, list[int]]:
    element_size = int(mesh.skel_element_size)
    if element_size <= 0 or not mesh.skel_joint_indices:
        raise ValueError("wind_preview_missing_base_binding: base mesh has no skeleton binding.")
    expected_indices = len(mesh.points) * element_size
    if len(mesh.skel_joint_indices) < expected_indices:
        raise ValueError("wind_preview_invalid_base_binding: base mesh skeleton indices do not match point count.")
    has_weights = len(mesh.skel_joint_weights) >= expected_indices
    by_joint: dict[str, list[int]] = {}
    offset = 0
    for face_index, count in enumerate(mesh.face_vertex_counts):
        scores: dict[str, float] = {}
        for slot in range(count):
            point_index = mesh.face_vertex_indices[offset + slot]
            if point_index < 0 or point_index >= len(mesh.points):
                raise ValueError(f"wind_preview_invalid_base_face: face {face_index} references point {point_index}.")
            for element in range(element_size):
                binding_index = point_index * element_size + element
                joint_index = mesh.skel_joint_indices[binding_index]
                if joint_index < 0 or joint_index >= len(skeleton):
                    raise ValueError(f"wind_preview_invalid_base_binding: point {point_index} references joint {joint_index}.")
                weight = mesh.skel_joint_weights[binding_index] if has_weights else 1.0
                joint_token = skeleton[joint_index].name
                scores[joint_token] = scores.get(joint_token, 0.0) + float(weight)
        offset += count
        if not scores:
            raise ValueError(f"wind_preview_invalid_base_binding: face {face_index} has no skeleton owner.")
        owner = min(scores, key=lambda token: (-scores[token], token))
        by_joint.setdefault(owner, []).append(face_index)
    return by_joint


def _slice_mesh_faces(mesh: MeshData, face_indices: tuple[int, ...], *, name: str) -> GeometryBuffer:
    original_to_new_point: dict[int, int] = {}
    points = array("f")
    face_counts = array("i")
    face_vertex_indices = array("i")
    ranges = _face_ranges(mesh.face_vertex_counts)
    for face_index in face_indices:
        start, end = ranges[face_index]
        face_counts.append(end - start)
        for slot in range(start, end):
            original_point_index = mesh.face_vertex_indices[slot]
            new_point_index = original_to_new_point.get(original_point_index)
            if new_point_index is None:
                point = mesh.points[original_point_index]
                new_point_index = len(original_to_new_point)
                original_to_new_point[original_point_index] = new_point_index
                points.extend((point.x, point.y, point.z))
            face_vertex_indices.append(new_point_index)
    return GeometryBuffer(
        name=name,
        point_components=points,
        face_vertex_counts=face_counts,
        face_vertex_indices=face_vertex_indices,
    )


def _face_ranges(face_vertex_counts: tuple[int, ...]) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    offset = 0
    for count in face_vertex_counts:
        end = offset + int(count)
        ranges.append((offset, end))
        offset = end
    return tuple(ranges)


def _prototype_geometry(prototype: Prototype) -> GeometryBuffer:
    if prototype.geometry_payload is not None:
        return prototype.geometry_payload
    if prototype.mesh is not None:
        return geometry_buffer_from_mesh(prototype.mesh)
    raise ValueError(f"wind_preview_empty_prototype: prototype {prototype.source_name or prototype.source_key} has no mesh payload.")


def _instance_joint_token(instance_name: str, joint_tokens: tuple[str, ...]) -> str:
    if not joint_tokens:
        raise ValueError(f"wind_preview_missing_instance_binding: repeated part {instance_name} has no Attachment joint.")
    return joint_tokens[0]


def _require_group(group_by_joint: dict[str, int], joint_token: str) -> int:
    try:
        return group_by_joint[joint_token]
    except KeyError as exc:
        raise ValueError(f"wind_preview_missing_group_assignment: joint {joint_token} has no wind group.") from exc


def _bone_segments(
    skeleton: tuple[Joint, ...],
    group_by_joint: dict[str, int],
    color_by_group: dict[int, Color4],
    selection: WindViewportSelection | None,
    selected_joints: set[str],
) -> tuple[ViewportBoneSegment, ...]:
    joints_by_name = {joint.name: joint for joint in skeleton}
    segments: list[ViewportBoneSegment] = []
    for joint in skeleton:
        parent = joints_by_name.get(joint.parent or "")
        if joint.parent is not None and parent is None:
            raise ValueError(f"wind_preview_invalid_skeleton: joint {joint.name} references missing parent {joint.parent}.")
        start, end = _bone_segment_positions(joint, parent)
        if start == end:
            continue
        group_index = _require_group(group_by_joint, joint.name)
        color = _selection_color(color_by_group[group_index], selection, group_index, joint.name, selected_joints)
        segments.append(
            ViewportBoneSegment(
                segment_id=f"bone:{parent.name if parent is not None else joint.name}->{joint.name}",
                parent_token=parent.name if parent is not None else joint.name,
                child_token=joint.name,
                start=start,
                end=end,
                color=color,
                selected=joint.name in selected_joints and selection is not None and selection.subtree_root_token is not None,
                selectable_id=f"bone:{parent.name if parent is not None else joint.name}->{joint.name}",
            )
        )
    return tuple(segments)


def _bone_segment_positions(joint: Joint, parent: Joint | None) -> tuple[Vector3, Vector3]:
    if joint.bind_end_translate is not None:
        return joint.bind_translate, joint.bind_end_translate
    if parent is not None:
        return parent.bind_translate, joint.bind_translate
    return joint.bind_translate, joint.bind_translate


def _bounds(
    batches: tuple[ViewportMeshBatch, ...],
    draw_calls: tuple[ViewportDrawCall, ...],
    bone_segments: tuple[ViewportBoneSegment, ...],
) -> ViewportBounds:
    if batches and draw_calls:
        return transformed_draw_bounds(batches, draw_calls)
    if not bone_segments:
        return ViewportBounds(Vector3(0.0, 0.0, 0.0), Vector3(0.0, 0.0, 0.0))
    min_x = min(min(segment.start.x, segment.end.x) for segment in bone_segments)
    min_y = min(min(segment.start.y, segment.end.y) for segment in bone_segments)
    min_z = min(min(segment.start.z, segment.end.z) for segment in bone_segments)
    max_x = max(max(segment.start.x, segment.end.x) for segment in bone_segments)
    max_y = max(max(segment.start.y, segment.end.y) for segment in bone_segments)
    max_z = max(max(segment.start.z, segment.end.z) for segment in bone_segments)
    return ViewportBounds(Vector3(min_x, min_y, min_z), Vector3(max_x, max_y, max_z))


def _group_color(index: int) -> Color4:
    palette = (
        Color4(0.95, 0.34, 0.22, 1.0),
        Color4(0.18, 0.58, 0.92, 1.0),
        Color4(0.25, 0.72, 0.38, 1.0),
        Color4(0.94, 0.68, 0.20, 1.0),
        Color4(0.62, 0.40, 0.84, 1.0),
        Color4(0.16, 0.72, 0.68, 1.0),
        Color4(0.88, 0.36, 0.62, 1.0),
        Color4(0.54, 0.60, 0.22, 1.0),
    )
    if index < len(palette):
        return palette[index]
    value = (index * 2654435761) & 0xFFFFFF
    return Color4(
        0.25 + ((value >> 16) & 0xFF) / 510.0,
        0.25 + ((value >> 8) & 0xFF) / 510.0,
        0.25 + (value & 0xFF) / 510.0,
        1.0,
    )


def _with_alpha(color: Color4, alpha: float) -> Color4:
    return Color4(color.r, color.g, color.b, alpha)
