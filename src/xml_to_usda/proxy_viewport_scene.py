"""Proxy Mesh Preview adapter for the Qt-free viewport scene contract."""

from __future__ import annotations

from .proxy_mesh_service import ProxyMeshResult
from .viewport_scene import (
    ViewportDrawCall,
    ViewportMeshBatch,
    ViewportScene,
    ViewportStats,
    geometry_triangle_count,
    transformed_draw_bounds,
)


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
    return ViewportScene(
        scene_id=f"{mesh.name or 'proxy'}:proxy_preview",
        mesh_batches=(batch,),
        draw_calls=(draw_call,),
        bounds=transformed_draw_bounds((batch,), (draw_call,)),
        stats=ViewportStats(
            uploaded_triangles=triangle_count,
            logical_triangles=triangle_count,
            instance_count=0,
            batch_count=1,
            draw_call_count=1,
        ),
    )
