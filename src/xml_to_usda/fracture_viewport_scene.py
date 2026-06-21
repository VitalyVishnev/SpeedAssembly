"""Fracture Preview adapter for the Qt-free viewport scene contract."""

from __future__ import annotations

import math

from .fracture_preview_service import FracturePreviewResult
from .fracture_service import FractureCutSite
from .models import Color4, Vector3
from .viewport_scene import (
    ViewportBoneSegment,
    ViewportDrawCall,
    ViewportLabel,
    ViewportMarker,
    ViewportMeshBatch,
    ViewportScene,
    ViewportStats,
    geometry_triangle_count,
    transformed_draw_bounds,
)


CUT_MARKER_COLOR = Color4(1.0, 0.92, 0.52, 1.0)
COLLISION_COLOR = Color4(0.35, 0.86, 1.0, 0.25)


def build_fracture_viewport_scene(
    preview: FracturePreviewResult,
    *,
    include_repeated_parts: bool = True,
) -> ViewportScene:
    batches: list[ViewportMeshBatch] = []
    draw_calls: list[ViewportDrawCall] = []
    uploaded_triangles = 0
    logical_triangles = 0
    repeated_batch_ids: set[str] = set()
    prototype_triangle_counts: dict[str, int] = {}
    piece_centers = {
        piece.piece.index: _mesh_center(piece.base_mesh)
        for piece in preview.pieces
    }
    global_center = _average_vector(tuple(piece_centers.values()))
    explode_directions = {
        piece_index: _explode_direction(center, global_center)
        for piece_index, center in piece_centers.items()
    }

    for piece in sorted(preview.pieces, key=lambda item: item.piece.index):
        triangle_count = geometry_triangle_count(piece.base_mesh)
        if triangle_count <= 0:
            continue
        batch_id = f"fracture:piece:{piece.piece.index:02d}:base"
        batches.append(
            ViewportMeshBatch(
                batch_id=batch_id,
                name=piece.piece.name,
                mesh=piece.base_mesh,
                color=piece.color,
                selectable_id=f"fracture:piece:{piece.piece.index:02d}",
            )
        )
        draw_calls.append(
            ViewportDrawCall(
                draw_id=f"{batch_id}:draw",
                batch_id=batch_id,
                tint=piece.color,
                explode_direction=explode_directions.get(piece.piece.index, Vector3(0.0, 0.0, 0.0)),
                selectable_id=f"fracture:piece:{piece.piece.index:02d}",
                visibility_group="base_mesh",
            )
        )
        uploaded_triangles += triangle_count
        logical_triangles += triangle_count

    visible_instance_count = 0
    if include_repeated_parts:
        for instance in sorted(preview.instances, key=lambda item: (item.piece_index, item.prototype_key, item.name)):
            prototype = preview.prototypes[instance.prototype_key]
            batch_id = f"fracture:piece:{instance.piece_index:02d}:prototype:{instance.prototype_key}"
            triangle_count = prototype_triangle_counts.get(instance.prototype_key)
            if triangle_count is None:
                triangle_count = geometry_triangle_count(prototype.mesh)
                prototype_triangle_counts[instance.prototype_key] = triangle_count
            if triangle_count <= 0:
                continue
            if batch_id not in repeated_batch_ids:
                repeated_batch_ids.add(batch_id)
                batches.append(
                    ViewportMeshBatch(
                        batch_id=batch_id,
                        name=f"{prototype.source_name}_piece_{instance.piece_index:02d}",
                        mesh=prototype.mesh,
                        color=instance.color,
                        selectable_id=batch_id,
                    )
                )
                uploaded_triangles += triangle_count
            draw_calls.append(
                ViewportDrawCall(
                    draw_id=f"fracture:instance:{instance.name}",
                    batch_id=batch_id,
                    translate=instance.position,
                    orientation=instance.orientation,
                    scale=instance.scale,
                    tint=instance.color,
                    explode_direction=explode_directions.get(instance.piece_index, Vector3(0.0, 0.0, 0.0)),
                    selectable_id=f"fracture:instance:{instance.name}",
                    visibility_group="repeated_parts",
                )
            )
            visible_instance_count += 1
            logical_triangles += triangle_count

    bone_segments = tuple(
        ViewportBoneSegment(
            segment_id=f"bone:{segment.parent_joint_token}->{segment.child_joint_token}",
            parent_token=segment.parent_joint_token,
            child_token=segment.child_joint_token,
            start=segment.parent_position,
            end=segment.child_position,
            color=segment.color,
            selected=segment.is_selected_cut,
            selectable_id=f"bone:{segment.parent_joint_token}->{segment.child_joint_token}",
        )
        for segment in preview.bone_segments
    )
    markers = tuple(_cut_marker(site, bone_segments) for site in preview.plan.selected_cut_sites)
    labels = tuple(
        ViewportLabel(
            label_id=f"label:{marker.marker_id}",
            text=marker.label,
            position=marker.position,
            color=marker.color,
        )
        for marker in markers
        if marker.label
    )
    collision_color = Color4(COLLISION_COLOR.r, COLLISION_COLOR.g, COLLISION_COLOR.b, preview.collision_opacity)
    for index, mesh in enumerate(preview.collision_meshes):
        triangle_count = geometry_triangle_count(mesh)
        if triangle_count <= 0:
            continue
        piece_index = preview.collision_piece_indices[index] if index < len(preview.collision_piece_indices) else -1
        batch_id = f"fracture:collision:{index:02d}"
        batches.append(
            ViewportMeshBatch(
                batch_id=batch_id,
                name=mesh.name,
                mesh=mesh,
                color=collision_color,
                selectable_id=batch_id,
            )
        )
        draw_calls.append(
            ViewportDrawCall(
                draw_id=f"{batch_id}:draw",
                batch_id=batch_id,
                tint=collision_color,
                explode_direction=explode_directions.get(piece_index, Vector3(0.0, 0.0, 0.0)),
                visibility_group="collision",
            )
        )
        uploaded_triangles += triangle_count
        logical_triangles += triangle_count
    return ViewportScene(
        scene_id=f"{preview.plan.output_stem}_fracture_preview",
        mesh_batches=tuple(batches),
        draw_calls=tuple(draw_calls),
        bounds=transformed_draw_bounds(tuple(batches), tuple(draw_calls)),
        stats=ViewportStats(
            uploaded_triangles=uploaded_triangles,
            logical_triangles=logical_triangles,
            instance_count=visible_instance_count,
            batch_count=len(batches),
            draw_call_count=len(draw_calls),
        ),
        bone_segments=bone_segments,
        markers=markers,
        labels=labels,
    )


def _cut_marker(cut_site: FractureCutSite, bone_segments: tuple[ViewportBoneSegment, ...]) -> ViewportMarker:
    position = _cut_site_position(cut_site, bone_segments)
    return ViewportMarker(
        marker_id=f"cut:{cut_site.joint_token}",
        position=position,
        color=CUT_MARKER_COLOR,
        radius=1.0,
        selectable_id=f"cut:{cut_site.joint_token}",
        label=cut_site.joint_token,
    )


def _cut_site_position(cut_site: FractureCutSite, bone_segments: tuple[ViewportBoneSegment, ...]) -> Vector3:
    if cut_site.parent_joint_token and cut_site.child_joint_token:
        segment = _segment_by_edge(bone_segments, cut_site.parent_joint_token, cut_site.child_joint_token)
        if segment is not None:
            t = cut_site.segment_t if cut_site.segment_t is not None else 1.0
            return _lerp(segment.start, segment.end, max(0.0, min(1.0, float(t))))
    for segment in bone_segments:
        if segment.child_token == cut_site.joint_token:
            return segment.end
    return Vector3(0.0, 0.0, 0.0)


def _segment_by_edge(
    bone_segments: tuple[ViewportBoneSegment, ...],
    parent_token: str,
    child_token: str,
) -> ViewportBoneSegment | None:
    for segment in bone_segments:
        if segment.parent_token == parent_token and segment.child_token == child_token:
            return segment
    return None


def _lerp(start: Vector3, end: Vector3, t: float) -> Vector3:
    return Vector3(
        start.x + (end.x - start.x) * t,
        start.y + (end.y - start.y) * t,
        start.z + (end.z - start.z) * t,
    )


def _mesh_center(mesh) -> Vector3:
    components = mesh.point_components
    point_count = len(components) // 3
    if point_count <= 0:
        return Vector3(0.0, 0.0, 0.0)
    return Vector3(
        sum(float(components[index]) for index in range(0, len(components), 3)) / point_count,
        sum(float(components[index]) for index in range(1, len(components), 3)) / point_count,
        sum(float(components[index]) for index in range(2, len(components), 3)) / point_count,
    )


def _average_vector(points: tuple[Vector3, ...]) -> Vector3:
    if not points:
        return Vector3(0.0, 0.0, 0.0)
    scale = 1.0 / len(points)
    return Vector3(
        sum(point.x for point in points) * scale,
        sum(point.y for point in points) * scale,
        sum(point.z for point in points) * scale,
    )


def _explode_direction(center: Vector3, global_center: Vector3) -> Vector3:
    x = center.x - global_center.x
    y = center.y - global_center.y
    z = center.z - global_center.z
    length = math.sqrt(x * x + y * y + z * z)
    if length <= 1e-8:
        return Vector3(0.0, 0.0, 0.0)
    scale = max(0.5, length) / length
    return Vector3(x * scale, y * scale, z * scale)
