"""Proxy Mesh Preview adapter for the Qt-free viewport scene contract."""

from __future__ import annotations

from .geometry_buffers import geometry_buffer_from_mesh
from .models import CanonicalTreeModel, Color4, GeometryBuffer, MeshData, Vector3
from .proxy_mesh_service import ProxyMeshResult
from .viewport_scene import (
    ViewportDrawCall,
    ViewportMeshBatch,
    ViewportScene,
    ViewportStats,
    geometry_triangle_count,
    transformed_draw_bounds,
)


_COLLISION_COLOR = Color4(0.42, 0.95, 1.0, 0.30)


def build_proxy_viewport_scene(proxy: ProxyMeshResult) -> ViewportScene:
    mesh = proxy.mesh
    triangle_count = geometry_triangle_count(mesh)
    batch = ViewportMeshBatch(
        batch_id="proxy:mesh",
        name=mesh.name or "ProxyMesh",
        mesh=mesh,
        selectable_id="proxy:mesh",
    )
    draw_call = ViewportDrawCall(
        draw_id="proxy:mesh:0",
        batch_id=batch.batch_id,
        selectable_id="proxy:mesh",
    )
    batches = [batch]
    draw_calls = [draw_call]
    uploaded_triangles = triangle_count
    for collision_index, collision in enumerate(
        proxy.collision_meshes if proxy.settings.collision.enabled else ()
    ):
        collision_buffer = geometry_buffer_from_mesh(collision)
        collision_triangles = geometry_triangle_count(collision_buffer)
        collision_batch = ViewportMeshBatch(
            batch_id=f"proxy:collision:{collision_index:02d}",
            name=collision.name,
            mesh=collision_buffer,
            color=_COLLISION_COLOR,
            selectable_id=f"proxy:collision:{collision_index:02d}",
        )
        collision_draw = ViewportDrawCall(
            draw_id=f"proxy:collision:{collision_index:02d}:draw",
            batch_id=collision_batch.batch_id,
            tint=_COLLISION_COLOR,
            visibility_group="collision",
        )
        batches.append(collision_batch)
        draw_calls.append(collision_draw)
        uploaded_triangles += collision_triangles
    return ViewportScene(
        scene_id=f"{mesh.name or 'proxy'}:proxy_preview",
        mesh_batches=tuple(batches),
        draw_calls=tuple(draw_calls),
        # Guide collision must not move the camera frame or floor grid away
        # from the Proxy Mesh pivot/base.
        bounds=transformed_draw_bounds((batch,), (draw_call,)),
        stats=ViewportStats(
            uploaded_triangles=uploaded_triangles,
            logical_triangles=uploaded_triangles,
            instance_count=0,
            batch_count=len(batches),
            draw_call_count=len(draw_calls),
        ),
        grid_origin=Vector3(0.0, 0.0, 0.0),
    )


def build_proxy_source_viewport_scene(model: CanonicalTreeModel) -> ViewportScene:
    """Build the original tree scene used only by Proxy silhouette comparison."""
    batches: list[ViewportMeshBatch] = []
    draw_calls: list[ViewportDrawCall] = []
    uploaded_triangles = 0
    logical_triangles = 0

    if model.base_mesh is not None:
        base_mesh = _silhouette_mesh(model.base_mesh)
        base_triangles = geometry_triangle_count(base_mesh)
        if base_triangles > 0:
            batches.append(ViewportMeshBatch(batch_id="proxy:source:base", name=base_mesh.name, mesh=base_mesh))
            draw_calls.append(
                ViewportDrawCall(
                    draw_id="proxy:source:base:draw",
                    batch_id="proxy:source:base",
                    visibility_group="source",
                )
            )
            uploaded_triangles += base_triangles
            logical_triangles += base_triangles

    prototype_batches: dict[str, tuple[str, int]] = {}
    prototypes = {prototype.source_key: prototype for prototype in model.prototypes}
    for instance_index, instance in enumerate(model.repeated_parts):
        batch_entry = prototype_batches.get(instance.prototype_key)
        if batch_entry is None:
            prototype = prototypes.get(instance.prototype_key)
            if prototype is None:
                continue
            payload = prototype.geometry_payload or prototype.mesh
            if payload is None:
                continue
            mesh = _silhouette_mesh(payload)
            triangle_count = geometry_triangle_count(mesh)
            if triangle_count <= 0:
                continue
            batch_id = f"proxy:source:prototype:{instance.prototype_key}"
            prototype_batches[instance.prototype_key] = (batch_id, triangle_count)
            batches.append(ViewportMeshBatch(batch_id=batch_id, name=mesh.name, mesh=mesh))
            uploaded_triangles += triangle_count
            batch_entry = (batch_id, triangle_count)
        batch_id, triangle_count = batch_entry
        draw_calls.append(
            ViewportDrawCall(
                draw_id=f"proxy:source:instance:{instance_index}",
                batch_id=batch_id,
                translate=instance.position,
                orientation=instance.orientation,
                scale=instance.scale,
                visibility_group="source",
            )
        )
        logical_triangles += triangle_count

    resolved_batches = tuple(batches)
    resolved_draws = tuple(draw_calls)
    return ViewportScene(
        scene_id="proxy:source",
        mesh_batches=resolved_batches,
        draw_calls=resolved_draws,
        bounds=transformed_draw_bounds(resolved_batches, resolved_draws),
        stats=ViewportStats(
            uploaded_triangles=uploaded_triangles,
            logical_triangles=logical_triangles,
            instance_count=len(model.repeated_parts),
            batch_count=len(resolved_batches),
            draw_call_count=len(resolved_draws),
        ),
        grid_origin=Vector3(0.0, 0.0, 0.0),
    )


def _silhouette_mesh(mesh: MeshData | GeometryBuffer) -> GeometryBuffer:
    buffer = mesh if isinstance(mesh, GeometryBuffer) else geometry_buffer_from_mesh(mesh)
    return GeometryBuffer(
        name=buffer.name,
        point_components=buffer.point_components,
        face_vertex_counts=buffer.face_vertex_counts,
        face_vertex_indices=buffer.face_vertex_indices,
    )
