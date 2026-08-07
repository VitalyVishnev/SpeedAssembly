"""Proxy Mesh Preview adapter for the Qt-free viewport scene contract."""

from __future__ import annotations

from .geometry_buffers import geometry_buffer_from_mesh
from .models import Color4, Vector3
from .proxy_mesh_service import ProxyMeshResult
from .viewport_scene import (
    ViewportDrawCall,
    ViewportMeshBatch,
    ViewportScene,
    ViewportStats,
    geometry_triangle_count,
    transformed_draw_bounds,
)


_COLLISION_COLOR = Color4(0.35, 0.86, 1.0, 0.25)


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
