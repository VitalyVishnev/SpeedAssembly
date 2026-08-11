"""Proxy mesh generation and USDA export service.

Layer: application/domain boundary.

The proxy mesh is a companion asset. It is generated from the resolved
CanonicalTreeModel and written as one static polygonal USDA mesh, separate from
the main vegetation export contract.
"""

from __future__ import annotations

import math
from array import array
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

from .mesh_pruning import DEFAULT_BRANCH_PRUNE_AGGRESSION, select_large_connected_face_indices
from .models import CanonicalTreeModel, GeometryBuffer, MeshData, Prototype, Quaternion, Vector3
from .models import ConversionRequest, CpuProfile, OutputMode
from .naming import make_stable_prim_name
from .output_resolution import ensure_output_path_allowed
from .proxy_source_projection import load_proxy_source_projection, projection_to_tree_asset
from .proxy_collision import (
    ProxyCollisionError,
    ProxyCollisionSource,
    ProxyCollisionSettings,
    build_proxy_collision_meshes,
    build_proxy_collision_meshes_from_source,
    prepare_proxy_collision_source,
)
from .qem_simplification import QemSimplificationError, simplify_geometry_buffer_qem


DEFAULT_PROXY_POLYCOUNT = 5000
BASE_MESH_FUSE_THRESHOLD_METERS = 0.001
MAX_PROXY_DENSITY_RESOLUTION = 512
PROXY_METHOD_DENSITY_FIELD = "density_field"
PROXY_METHOD_INSTANCE_BOUNDS = "instance_bounds"


class ProxyMeshError(ValueError):
    """Raised when a proxy cannot be safely generated from source facts."""


@dataclass(frozen=True)
class ProxyMeshSettings:
    method: str = PROXY_METHOD_DENSITY_FIELD
    final_polycount: int = DEFAULT_PROXY_POLYCOUNT
    bounds_inflation: float = 1.0
    density_resolution: int = 64
    base_mesh_priority: float = 0.33
    fuse_base_mesh_vertices: bool = False
    branch_prune_aggression: float = DEFAULT_BRANCH_PRUNE_AGGRESSION
    collision: ProxyCollisionSettings = field(default_factory=ProxyCollisionSettings)


@dataclass(frozen=True)
class ProxyMeshSourceRequest:
    input_path: str
    output_path: str = ""
    output_mode: OutputMode = OutputMode.SELF_CONTAINED
    cpu_profile: CpuProfile = CpuProfile.BALANCED
    fbx_cache_max_bytes: int = 20 * 1024 * 1024 * 1024
    fbx_cache_max_age_seconds: int = 14 * 24 * 60 * 60

    @classmethod
    def from_conversion_request(cls, request: ConversionRequest) -> "ProxyMeshSourceRequest":
        return cls(
            input_path=_single_input_path(request),
            output_path=request.output_path or "",
            output_mode=request.output_mode,
            cpu_profile=request.cpu_profile,
            fbx_cache_max_bytes=request.fbx_cache_max_bytes,
            fbx_cache_max_age_seconds=request.fbx_cache_max_age_seconds,
        )


def prepare_proxy_mesh_source_request(
    *,
    input_path: str,
    output_path: str = "",
    output_mode: OutputMode = OutputMode.SELF_CONTAINED,
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
    fbx_cache_max_bytes: int = 20 * 1024 * 1024 * 1024,
    fbx_cache_max_age_seconds: int = 14 * 24 * 60 * 60,
) -> ProxyMeshSourceRequest:
    if not input_path.strip():
        raise ValueError("Select a source XML file before generating a proxy mesh.")
    return ProxyMeshSourceRequest(
        input_path=input_path.strip(),
        output_path=output_path.strip(),
        output_mode=output_mode,
        cpu_profile=cpu_profile,
        fbx_cache_max_bytes=fbx_cache_max_bytes,
        fbx_cache_max_age_seconds=fbx_cache_max_age_seconds,
    )


@dataclass(frozen=True)
class ProxyMeshResult:
    mesh: GeometryBuffer
    settings: ProxyMeshSettings
    method: str
    source_instance_count: int
    included_base_mesh: bool
    collision_meshes: tuple[MeshData, ...] = ()
    collision_source: ProxyCollisionSource | None = None


@dataclass(frozen=True)
class ProxyMeshExportResult:
    input_path: str
    output_path: str
    proxy: ProxyMeshResult
    usda_text: str


class ProxyMeshJobResult:
    __slots__ = ("proxy", "export", "collision_meshes", "cancelled", "error_message")

    def __init__(
        self,
        proxy: ProxyMeshResult | None = None,
        export: ProxyMeshExportResult | None = None,
        collision_meshes: tuple[MeshData, ...] | None = None,
        cancelled: bool = False,
        error_message: str | None = None,
    ) -> None:
        self.proxy = proxy
        self.export = export
        self.collision_meshes = collision_meshes
        self.cancelled = cancelled
        self.error_message = error_message


def derive_proxy_usda_output_path(input_path: str, output_path: str) -> Path:
    """Derive the companion proxy USDA path beside the main output or input."""
    if output_path.strip():
        resolved_output = Path(output_path)
        return resolved_output.with_name(f"{resolved_output.stem}_proxy.usda")
    resolved_input = Path(input_path.strip())
    return resolved_input.with_name(f"{resolved_input.stem}_proxy.usda")


def generate_proxy_mesh(model: CanonicalTreeModel, settings: ProxyMeshSettings | None = None) -> ProxyMeshResult:
    """Generate one proxy mesh from resolved base and repeated-part geometry."""
    resolved_settings = settings or ProxyMeshSettings()
    if resolved_settings.method not in {PROXY_METHOD_DENSITY_FIELD, PROXY_METHOD_INSTANCE_BOUNDS}:
        raise ProxyMeshError(f"Unsupported proxy mesh method: {resolved_settings.method}")
    if resolved_settings.final_polycount <= 0:
        raise ProxyMeshError("Proxy final polycount must be greater than zero.")
    if resolved_settings.bounds_inflation <= 0:
        raise ProxyMeshError("Proxy bounds inflation must be greater than zero.")
    if resolved_settings.density_resolution <= 0:
        raise ProxyMeshError("Proxy density resolution must be greater than zero.")
    if resolved_settings.density_resolution > MAX_PROXY_DENSITY_RESOLUTION:
        raise ProxyMeshError(f"Proxy density resolution must be between 1 and {MAX_PROXY_DENSITY_RESOLUTION}.")
    if not 0.0 <= resolved_settings.base_mesh_priority <= 1.0:
        raise ProxyMeshError("Proxy base mesh priority must be between zero and one.")
    if not 0.0 <= resolved_settings.branch_prune_aggression <= 1.0:
        raise ProxyMeshError("Proxy branch prune aggression must be between zero and one.")
    if resolved_settings.method == PROXY_METHOD_INSTANCE_BOUNDS:
        source_boxes, included_base = _collect_source_boxes(model, resolved_settings)
        if not source_boxes:
            raise ProxyMeshError("Proxy mesh requires base geometry or at least one repeated part instance.")
        mesh = _build_instance_bounds_mesh(source_boxes, resolved_settings)
    else:
        sources = _collect_density_field_sources(model, resolved_settings)
        if sources.base_mesh is None and not sources.foliage_instances:
            raise ProxyMeshError("Proxy mesh requires base geometry or at least one repeated part instance.")
        included_base = sources.base_mesh is not None
        mesh = _build_density_field_mesh(sources, resolved_settings)

    collision_source = None
    collision_meshes: tuple[MeshData, ...] = ()
    if (
        resolved_settings.collision.enabled
        and resolved_settings.collision.height_multiplier > 0.0
        and resolved_settings.collision.width_multiplier > 0.0
    ):
        try:
            collision_source = prepare_proxy_collision_source(model)
            collision_meshes = build_proxy_collision_meshes_from_source(
                collision_source,
                resolved_settings.collision,
            )
        except ProxyCollisionError as exc:
            raise ProxyMeshError(str(exc)) from exc
    return ProxyMeshResult(
        mesh=mesh,
        settings=resolved_settings,
        method=resolved_settings.method,
        source_instance_count=len(model.repeated_parts),
        included_base_mesh=included_base,
        collision_meshes=collision_meshes,
        collision_source=collision_source,
    )


def generate_proxy_collision_meshes(
    model: CanonicalTreeModel,
    settings: ProxyCollisionSettings | None,
) -> tuple[MeshData, ...]:
    """Fit Proxy collision without generating or simplifying the render mesh."""
    try:
        return build_proxy_collision_meshes(model, settings)
    except ProxyCollisionError as exc:
        raise ProxyMeshError(str(exc)) from exc


def update_proxy_collision(
    proxy: ProxyMeshResult,
    settings: ProxyMeshSettings,
    collision_meshes: tuple[MeshData, ...] | None = None,
) -> ProxyMeshResult:
    """Reuse a generated Proxy Mesh while replacing only its collision state."""
    if replace(proxy.settings, collision=settings.collision) != settings:
        raise ProxyMeshError("Cannot reuse Proxy Mesh after non-collision settings changed.")
    resolved_collision_meshes = collision_meshes
    if resolved_collision_meshes is None:
        same_fit = replace(proxy.settings.collision, enabled=settings.collision.enabled) == settings.collision
        if same_fit or proxy.collision_source is None:
            resolved_collision_meshes = proxy.collision_meshes
        else:
            try:
                resolved_collision_meshes = build_proxy_collision_meshes_from_source(
                    proxy.collision_source,
                    replace(settings.collision, enabled=True),
                )
            except ProxyCollisionError as exc:
                raise ProxyMeshError(str(exc)) from exc
    return replace(
        proxy,
        settings=settings,
        collision_meshes=resolved_collision_meshes,
    )


def _collect_source_boxes(
    model: CanonicalTreeModel,
    settings: ProxyMeshSettings,
) -> tuple[tuple["_Bounds", ...], bool]:
    boxes: list[_Bounds] = []
    included_base = False
    if model.base_mesh is not None:
        boxes.append(_inflate_bounds(_mesh_bounds(model.base_mesh), settings.bounds_inflation))
        included_base = True

    prototypes = {prototype.source_key: prototype for prototype in model.prototypes}
    prototype_bounds: dict[str, _Bounds] = {}
    for instance in model.repeated_parts:
        prototype = prototypes.get(instance.prototype_key)
        if prototype is None:
            raise ProxyMeshError(
                f"Missing resolved prototype for repeated part {instance.name} ({instance.prototype_key})."
            )
        local_bounds = prototype_bounds.get(instance.prototype_key)
        if local_bounds is None:
            payload = _prototype_payload(prototype)
            if payload is None:
                raise ProxyMeshError(
                    f"Prototype {prototype.source_name or prototype.source_key} has no resolved polygon payload."
                )
            local_bounds = _mesh_bounds(payload)
            prototype_bounds[instance.prototype_key] = local_bounds
        boxes.append(
            _inflate_bounds(
                _transformed_bounds(
                    local_bounds,
                    translate=instance.position,
                    orientation=instance.orientation,
                    scale=instance.scale,
                ),
                settings.bounds_inflation,
            )
        )
    return tuple(boxes), included_base


@dataclass(frozen=True)
class _DensityFieldSources:
    base_mesh: GeometryBuffer | None
    foliage_instances: tuple["_PreparedFoliageKernel", ...]


@dataclass(frozen=True)
class _PreparedFoliageKernel:
    name: str
    world_bounds: "_Bounds"
    position: Vector3
    inverse_orientation: Quaternion
    inverse_scale: Vector3
    local_center: Vector3
    local_half_extent: Vector3


def _collect_density_field_sources(
    model: CanonicalTreeModel,
    settings: ProxyMeshSettings,
) -> _DensityFieldSources:
    prototypes = {prototype.source_key: prototype for prototype in model.prototypes}
    prototype_bounds: dict[str, _Bounds] = {}
    foliage_instances: list[_PreparedFoliageKernel] = []

    for instance in model.repeated_parts:
        prototype = prototypes.get(instance.prototype_key)
        if prototype is None:
            raise ProxyMeshError(
                f"Missing resolved prototype for repeated part {instance.name} ({instance.prototype_key})."
            )
        local_bounds = prototype_bounds.get(instance.prototype_key)
        if local_bounds is None:
            payload = _prototype_payload(prototype)
            if payload is None:
                raise ProxyMeshError(
                    f"Prototype {prototype.source_name or prototype.source_key} has no resolved polygon payload."
                )
            local_bounds = _inflate_bounds(_mesh_bounds(payload), settings.bounds_inflation)
            prototype_bounds[instance.prototype_key] = local_bounds
        foliage_instances.append(
            _prepare_foliage_kernel(
                name=instance.name,
                local_bounds=local_bounds,
                position=instance.position,
                orientation=_validated_quaternion(instance.orientation, label=f"repeated part {instance.name}"),
                scale=instance.scale,
            )
        )
    base_mesh = (
        _base_proxy_geometry_buffer(model, settings=settings, has_foliage=bool(foliage_instances))
        if model.base_mesh is not None
        else None
    )
    return _DensityFieldSources(base_mesh=base_mesh, foliage_instances=tuple(foliage_instances))


def _build_instance_bounds_mesh(boxes: tuple["_Bounds", ...], settings: ProxyMeshSettings) -> GeometryBuffer:
    builder = _ProxyMeshBuilder()
    for box in boxes:
        builder.add_box(box, name="Box")
    return builder.build("ProxyMesh")


def _build_density_field_mesh(sources: _DensityFieldSources, settings: ProxyMeshSettings) -> GeometryBuffer:
    buffers: list[GeometryBuffer] = []
    remaining_budget = settings.final_polycount

    if sources.base_mesh is not None:
        base_budget = _base_mesh_budget(
            sources.base_mesh,
            settings=settings,
            has_foliage=bool(sources.foliage_instances),
        )
        base_mesh = _simplify_polygon_mesh(
            sources.base_mesh,
            target_triangle_count=base_budget,
            method=settings.method,
        )
        buffers.append(base_mesh)
        remaining_budget -= base_mesh.face_count

    if sources.foliage_instances:
        foliage_mesh = _build_foliage_density_field_mesh(
            sources.foliage_instances,
            settings=settings,
            target_triangle_count=max(1, remaining_budget),
        )
        buffers.append(foliage_mesh)

    if not buffers:
        raise ProxyMeshError("Proxy method density_field produced no geometry.")
    if len(buffers) == 1:
        return _renamed_geometry_buffer(buffers[0], "ProxyMesh")
    return _combine_geometry_buffers("ProxyMesh", tuple(buffers))


def _base_mesh_budget(mesh: GeometryBuffer, *, settings: ProxyMeshSettings, has_foliage: bool) -> int:
    source_triangle_count = max(1, _triangulated_face_count(mesh))
    if not has_foliage:
        return max(1, settings.final_polycount)
    available_for_base = max(1, settings.final_polycount - 6)
    weighted_budget = int(round(available_for_base * settings.base_mesh_priority))
    return max(1, min(source_triangle_count, weighted_budget, available_for_base))


def _triangulated_face_count(mesh: GeometryBuffer) -> int:
    return sum(max(0, int(count) - 2) for count in mesh.face_vertex_counts)


def _base_proxy_geometry_buffer(
    model: CanonicalTreeModel,
    *,
    settings: ProxyMeshSettings,
    has_foliage: bool,
) -> GeometryBuffer:
    mesh = model.base_mesh
    if mesh is None:
        raise ProxyMeshError("Proxy base mesh is missing.")
    if has_foliage:
        face_indices = select_large_connected_face_indices(
            mesh,
            aggression=settings.branch_prune_aggression,
        )
        if face_indices is not None:
            mesh = _mesh_faces_to_mesh_data(mesh, face_indices, name="BaseProxyMesh")
    if settings.fuse_base_mesh_vertices:
        mesh = _fuse_mesh_vertices(mesh, threshold=BASE_MESH_FUSE_THRESHOLD_METERS)
    return _mesh_to_geometry_buffer(mesh, name="BaseProxyMesh")


def _fuse_mesh_vertices(mesh: MeshData, *, threshold: float) -> MeshData:
    """Weld nearby base-mesh points without changing the canonical source mesh."""
    if threshold <= 0.0:
        raise ProxyMeshError("Proxy base mesh fuse threshold must be greater than zero.")

    inverse_threshold = 1.0 / threshold
    threshold_squared = threshold * threshold
    cells: dict[tuple[int, int, int], list[int]] = {}
    fused_points: list[Vector3] = []
    source_to_fused: list[int] = []

    for point in mesh.points:
        if not all(math.isfinite(value) for value in (point.x, point.y, point.z)):
            raise ProxyMeshError(f"Mesh {mesh.name} contains non-finite point coordinates.")
        cell = (
            math.floor(point.x * inverse_threshold),
            math.floor(point.y * inverse_threshold),
            math.floor(point.z * inverse_threshold),
        )
        fused_index: int | None = None
        for x_offset in (-1, 0, 1):
            for y_offset in (-1, 0, 1):
                for z_offset in (-1, 0, 1):
                    neighbor = (cell[0] + x_offset, cell[1] + y_offset, cell[2] + z_offset)
                    for candidate_index in cells.get(neighbor, ()):
                        candidate = fused_points[candidate_index]
                        distance_squared = (
                            (point.x - candidate.x) ** 2
                            + (point.y - candidate.y) ** 2
                            + (point.z - candidate.z) ** 2
                        )
                        if distance_squared <= threshold_squared and (
                            fused_index is None or candidate_index < fused_index
                        ):
                            fused_index = candidate_index
        if fused_index is None:
            fused_index = len(fused_points)
            fused_points.append(point)
            cells.setdefault(cell, []).append(fused_index)
        source_to_fused.append(fused_index)

    fused_face_counts: list[int] = []
    fused_face_indices: list[int] = []
    source_offset = 0
    source_point_count = len(mesh.points)
    for face_index, count in enumerate(mesh.face_vertex_counts):
        count = int(count)
        end = source_offset + count
        if count < 0 or end > len(mesh.face_vertex_indices):
            raise ProxyMeshError(f"Mesh {mesh.name} face {face_index} has invalid vertex indices.")
        face: list[int] = []
        for source_index in mesh.face_vertex_indices[source_offset:end]:
            source_index = int(source_index)
            if source_index < 0 or source_index >= source_point_count:
                raise ProxyMeshError(
                    f"Mesh {mesh.name} face {face_index} references point {source_index} outside the mesh."
                )
            fused_index = source_to_fused[source_index]
            if not face or face[-1] != fused_index:
                face.append(fused_index)
        if len(face) > 1 and face[0] == face[-1]:
            face.pop()
        if len(set(face)) >= 3:
            fused_face_counts.append(len(face))
            fused_face_indices.extend(face)
        source_offset = end
    if source_offset != len(mesh.face_vertex_indices):
        raise ProxyMeshError(f"Mesh {mesh.name} has trailing face vertex indices.")

    return MeshData(
        name=mesh.name,
        points=tuple(fused_points),
        face_vertex_counts=tuple(fused_face_counts),
        face_vertex_indices=tuple(fused_face_indices),
    )


def _mesh_faces_to_mesh_data(mesh: MeshData, face_indices: tuple[int, ...], *, name: str) -> MeshData:
    points: list[Vector3] = []
    face_counts: list[int] = []
    face_vertex_indices: list[int] = []
    original_to_new_point: dict[int, int] = {}
    face_set = set(face_indices)
    offset = 0
    for face_index, count in enumerate(mesh.face_vertex_counts):
        end = offset + int(count)
        if face_index not in face_set:
            offset = end
            continue
        face_counts.append(int(count))
        for source_point_index in mesh.face_vertex_indices[offset:end]:
            source_point_index = int(source_point_index)
            new_point_index = original_to_new_point.get(source_point_index)
            if new_point_index is None:
                point = mesh.points[source_point_index]
                new_point_index = len(points)
                original_to_new_point[source_point_index] = new_point_index
                points.append(point)
            face_vertex_indices.append(new_point_index)
        offset = end
    return MeshData(
        name=name,
        points=tuple(points),
        face_vertex_counts=tuple(face_counts),
        face_vertex_indices=tuple(face_vertex_indices),
    )


def _build_foliage_density_field_mesh(
    instances: tuple[_PreparedFoliageKernel, ...],
    *,
    settings: ProxyMeshSettings,
    target_triangle_count: int,
) -> GeometryBuffer:
    instance_bounds = tuple(instance.world_bounds for instance in instances)
    overall = _non_degenerate_bounds(_combine_bounds(instance_bounds))
    occupied, cell_size, grid_minimum = _occupied_foliage_density_cells(
        instances,
        overall,
        settings.density_resolution,
    )
    return _simplify_polygon_mesh(
        _mesh_from_occupied_cells(occupied, cell_size, grid_minimum),
        target_triangle_count=target_triangle_count,
        method=settings.method,
    )


def _simplify_polygon_mesh(
    mesh: GeometryBuffer,
    *,
    target_triangle_count: int,
    method: str,
) -> GeometryBuffer:
    try:
        return simplify_geometry_buffer_qem(mesh, target_triangle_count=target_triangle_count)
    except QemSimplificationError as exc:
        raise ProxyMeshError(f"Proxy method {method} QEM simplification failed: {exc}") from exc


def _mesh_to_geometry_buffer(mesh: MeshData | GeometryBuffer, *, name: str) -> GeometryBuffer:
    if isinstance(mesh, GeometryBuffer):
        return GeometryBuffer(
            name=name,
            point_components=array("f", mesh.point_components),
            face_vertex_counts=array("i", mesh.face_vertex_counts),
            face_vertex_indices=array("i", mesh.face_vertex_indices),
        )
    point_components = array("f")
    for point in mesh.points:
        point_components.extend((point.x, point.y, point.z))
    return GeometryBuffer(
        name=name,
        point_components=point_components,
        face_vertex_counts=array("i", mesh.face_vertex_counts),
        face_vertex_indices=array("i", mesh.face_vertex_indices),
    )


def _renamed_geometry_buffer(mesh: GeometryBuffer, name: str) -> GeometryBuffer:
    return GeometryBuffer(
        name=name,
        point_components=array("f", mesh.point_components),
        face_vertex_counts=array("i", mesh.face_vertex_counts),
        face_vertex_indices=array("i", mesh.face_vertex_indices),
    )


def _combine_geometry_buffers(name: str, buffers: tuple[GeometryBuffer, ...]) -> GeometryBuffer:
    points = array("f")
    face_counts = array("i")
    face_indices = array("i")
    point_offset = 0
    for mesh in buffers:
        points.extend(mesh.point_components)
        face_counts.extend(mesh.face_vertex_counts)
        face_indices.extend(point_offset + int(index) for index in mesh.face_vertex_indices)
        point_offset += mesh.point_count
    return GeometryBuffer(
        name=name,
        point_components=points,
        face_vertex_counts=face_counts,
        face_vertex_indices=face_indices,
    )


def export_proxy_usda(
    model: CanonicalTreeModel,
    *,
    input_path: str,
    output_path: str,
    settings: ProxyMeshSettings | None = None,
) -> ProxyMeshExportResult:
    """Generate and write the companion proxy USDA file."""
    proxy_path = derive_proxy_usda_output_path(input_path, output_path)
    ensure_output_path_allowed(proxy_path)
    proxy = generate_proxy_mesh(model, settings)
    root_name = make_stable_prim_name(proxy_path.stem, fallback="Proxy")
    usda_text = render_proxy_usda(proxy, root_name=root_name)
    proxy_path.parent.mkdir(parents=True, exist_ok=True)
    proxy_path.write_text(usda_text, encoding="utf-8")
    return ProxyMeshExportResult(
        input_path=input_path,
        output_path=str(proxy_path),
        proxy=proxy,
        usda_text=usda_text,
    )


def export_generated_proxy_usda(
    proxy: ProxyMeshResult,
    *,
    input_path: str,
    output_path: str,
) -> ProxyMeshExportResult:
    """Write an already generated proxy mesh without rebuilding it."""
    proxy_path = derive_proxy_usda_output_path(input_path, output_path)
    ensure_output_path_allowed(proxy_path)
    root_name = make_stable_prim_name(proxy_path.stem, fallback="Proxy")
    usda_text = render_proxy_usda(proxy, root_name=root_name)
    proxy_path.parent.mkdir(parents=True, exist_ok=True)
    proxy_path.write_text(usda_text, encoding="utf-8")
    return ProxyMeshExportResult(
        input_path=input_path,
        output_path=str(proxy_path),
        proxy=proxy,
        usda_text=usda_text,
    )


def generate_proxy_mesh_from_source_request(
    request: ProxyMeshSourceRequest,
    settings: ProxyMeshSettings | None = None,
) -> ProxyMeshResult:
    """Generate a proxy from source-normalized XML facts, without operator FBX replacement."""
    _input_path, model = _load_proxy_source_projection(request)
    return generate_proxy_mesh(model, settings)


def generate_proxy_preview_from_source_request(
    request: ProxyMeshSourceRequest,
    settings: ProxyMeshSettings | None = None,
) -> ProxyMeshResult:
    """Generate Preview once and retain a hidden collision fit for instant On/Off toggles."""
    resolved = settings or ProxyMeshSettings()
    preview_settings = replace(
        resolved,
        collision=replace(resolved.collision, enabled=True),
    )
    proxy = generate_proxy_mesh_from_source_request(request, preview_settings)
    return replace(proxy, settings=resolved)


def generate_proxy_collision_meshes_from_source_request(
    request: ProxyMeshSourceRequest,
    settings: ProxyCollisionSettings | None,
) -> tuple[MeshData, ...]:
    """Fit collision from cached Proxy Source Projection without rebuilding Proxy Mesh."""
    _input_path, model = _load_proxy_source_projection(request)
    return generate_proxy_collision_meshes(model, settings)


def export_proxy_usda_from_source_request(
    request: ProxyMeshSourceRequest,
    settings: ProxyMeshSettings | None = None,
) -> ProxyMeshExportResult:
    """Generate and write the proxy companion from source-normalized XML facts."""
    input_path, model = _load_proxy_source_projection(request)
    return export_proxy_usda(
        model,
        input_path=input_path,
        output_path=request.output_path,
        settings=settings,
    )


def export_generated_proxy_usda_from_source_request(
    request: ProxyMeshSourceRequest,
    proxy: ProxyMeshResult,
) -> ProxyMeshExportResult:
    """Write a preview-generated proxy companion for the same source request."""
    return export_generated_proxy_usda(
        proxy,
        input_path=request.input_path,
        output_path=request.output_path,
    )


def generate_proxy_mesh_from_request(
    request: ConversionRequest,
    settings: ProxyMeshSettings | None = None,
) -> ProxyMeshResult:
    return generate_proxy_mesh_from_source_request(
        ProxyMeshSourceRequest.from_conversion_request(request),
        settings,
    )


def export_proxy_usda_from_request(
    request: ConversionRequest,
    settings: ProxyMeshSettings | None = None,
) -> ProxyMeshExportResult:
    return export_proxy_usda_from_source_request(
        ProxyMeshSourceRequest.from_conversion_request(request),
        settings,
    )


def export_generated_proxy_usda_from_request(
    request: ConversionRequest,
    proxy: ProxyMeshResult,
) -> ProxyMeshExportResult:
    return export_generated_proxy_usda_from_source_request(
        ProxyMeshSourceRequest.from_conversion_request(request),
        proxy,
    )


def render_proxy_usda(proxy: ProxyMeshResult, *, root_name: str) -> str:
    """Render one proxy mesh and its optional simple-collision sibling."""
    safe_root_name = make_stable_prim_name(root_name, fallback="Proxy")
    mesh = proxy.mesh
    lines = [
        "#usda 1.0",
        "(",
        f'    defaultPrim = "{safe_root_name}"',
        "    metersPerUnit = 1",
        '    upAxis = "Y"',
        ")",
        "",
        f'def Xform "{safe_root_name}"',
        "{",
        '    def Mesh "ProxyMesh"',
        "    {",
        '        uniform token orientation = "rightHanded"',
        _render_array("point3f[] points", _point_strings(mesh), indent="        "),
        _render_array("int[] faceVertexCounts", (str(value) for value in mesh.face_vertex_counts), indent="        "),
        _render_array("int[] faceVertexIndices", (str(value) for value in mesh.face_vertex_indices), indent="        "),
        "    }",
    ]
    for collision in proxy.collision_meshes if proxy.settings.collision.enabled else ():
        lines.extend(
            (
                f'    def Mesh "{collision.name}"',
                "    {",
                '        uniform token purpose = "guide"',
                '        uniform token subdivisionScheme = "none"',
                '        uniform token orientation = "rightHanded"',
                _render_array("point3f[] points", _mesh_point_strings(collision), indent="        "),
                _render_array("int[] faceVertexCounts", (str(value) for value in collision.face_vertex_counts), indent="        "),
                _render_array("int[] faceVertexIndices", (str(value) for value in collision.face_vertex_indices), indent="        "),
                "    }",
            )
        )
    lines.extend(("}", ""))
    return "\n".join(lines)


@dataclass(frozen=True)
class _Bounds:
    minimum: Vector3
    maximum: Vector3


class _ProxyMeshBuilder:
    def __init__(self) -> None:
        self._points = array("f")
        self._face_counts = array("i")
        self._face_indices = array("i")
        self.box_count = 0

    @property
    def face_count(self) -> int:
        return len(self._face_counts)

    def add_box(
        self,
        bounds: _Bounds,
        *,
        name: str,
        translate: Vector3 = Vector3(0.0, 0.0, 0.0),
        orientation: Quaternion = Quaternion(1.0, 0.0, 0.0, 0.0),
        scale: Vector3 = Vector3(1.0, 1.0, 1.0),
        inflation: float = 1.0,
    ) -> None:
        del name
        corners = _box_corners(bounds, inflation=inflation)
        base_index = len(self._points) // 3
        for corner in corners:
            scaled = Vector3(corner.x * scale.x, corner.y * scale.y, corner.z * scale.z)
            rotated = _rotate_vector(orientation, scaled)
            point = Vector3(rotated.x + translate.x, rotated.y + translate.y, rotated.z + translate.z)
            self._points.extend((point.x, point.y, point.z))
        for face in (
            (0, 1, 3, 2),
            (4, 6, 7, 5),
            (0, 4, 5, 1),
            (2, 3, 7, 6),
            (0, 2, 6, 4),
            (1, 5, 7, 3),
        ):
            self._face_counts.append(4)
            self._face_indices.extend(base_index + index for index in face)
        self.box_count += 1

    def build(self, name: str) -> GeometryBuffer:
        return GeometryBuffer(
            name=name,
            point_components=self._points,
            face_vertex_counts=self._face_counts,
            face_vertex_indices=self._face_indices,
        )


def _prototype_payload(prototype: Prototype) -> MeshData | GeometryBuffer | None:
    return prototype.geometry_payload or prototype.mesh


def _mesh_bounds(mesh: MeshData | GeometryBuffer) -> _Bounds:
    iterator = _iter_points(mesh)
    try:
        first = next(iterator)
    except StopIteration as exc:
        raise ProxyMeshError(f"Mesh {mesh.name} has no points.") from exc
    min_x = max_x = first.x
    min_y = max_y = first.y
    min_z = max_z = first.z
    for point in iterator:
        min_x = min(min_x, point.x)
        min_y = min(min_y, point.y)
        min_z = min(min_z, point.z)
        max_x = max(max_x, point.x)
        max_y = max(max_y, point.y)
        max_z = max(max_z, point.z)
    return _Bounds(Vector3(min_x, min_y, min_z), Vector3(max_x, max_y, max_z))


def _combine_bounds(bounds: tuple[_Bounds, ...]) -> _Bounds:
    first = bounds[0]
    min_x = first.minimum.x
    min_y = first.minimum.y
    min_z = first.minimum.z
    max_x = first.maximum.x
    max_y = first.maximum.y
    max_z = first.maximum.z
    for item in bounds[1:]:
        min_x = min(min_x, item.minimum.x)
        min_y = min(min_y, item.minimum.y)
        min_z = min(min_z, item.minimum.z)
        max_x = max(max_x, item.maximum.x)
        max_y = max(max_y, item.maximum.y)
        max_z = max(max_z, item.maximum.z)
    return _Bounds(Vector3(min_x, min_y, min_z), Vector3(max_x, max_y, max_z))


def _transformed_bounds(
    bounds: _Bounds,
    *,
    translate: Vector3,
    orientation: Quaternion,
    scale: Vector3,
) -> _Bounds:
    center = Vector3(
        (bounds.minimum.x + bounds.maximum.x) * 0.5 * scale.x,
        (bounds.minimum.y + bounds.maximum.y) * 0.5 * scale.y,
        (bounds.minimum.z + bounds.maximum.z) * 0.5 * scale.z,
    )
    half_x = abs((bounds.maximum.x - bounds.minimum.x) * 0.5 * scale.x)
    half_y = abs((bounds.maximum.y - bounds.minimum.y) * 0.5 * scale.y)
    half_z = abs((bounds.maximum.z - bounds.minimum.z) * 0.5 * scale.z)
    rows = _quaternion_matrix_rows(orientation)
    rotated_center = _rotate_vector(orientation, center)
    world_center = Vector3(
        rotated_center.x + translate.x,
        rotated_center.y + translate.y,
        rotated_center.z + translate.z,
    )
    world_half_x = abs(rows[0][0]) * half_x + abs(rows[0][1]) * half_y + abs(rows[0][2]) * half_z
    world_half_y = abs(rows[1][0]) * half_x + abs(rows[1][1]) * half_y + abs(rows[1][2]) * half_z
    world_half_z = abs(rows[2][0]) * half_x + abs(rows[2][1]) * half_y + abs(rows[2][2]) * half_z
    return _Bounds(
        Vector3(world_center.x - world_half_x, world_center.y - world_half_y, world_center.z - world_half_z),
        Vector3(world_center.x + world_half_x, world_center.y + world_half_y, world_center.z + world_half_z),
    )


def _quaternion_matrix_rows(q: Quaternion) -> tuple[tuple[float, float, float], ...]:
    qw = q.real
    qx = q.i
    qy = q.j
    qz = q.k
    xx = qx * qx
    yy = qy * qy
    zz = qz * qz
    xy = qx * qy
    xz = qx * qz
    yz = qy * qz
    wx = qw * qx
    wy = qw * qy
    wz = qw * qz
    return (
        (1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy)),
        (2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx)),
        (2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy)),
    )


def _bounds_from_points(points: list[Vector3]) -> _Bounds:
    first = points[0]
    min_x = max_x = first.x
    min_y = max_y = first.y
    min_z = max_z = first.z
    for point in points[1:]:
        min_x = min(min_x, point.x)
        min_y = min(min_y, point.y)
        min_z = min(min_z, point.z)
        max_x = max(max_x, point.x)
        max_y = max(max_y, point.y)
        max_z = max(max_z, point.z)
    return _Bounds(Vector3(min_x, min_y, min_z), Vector3(max_x, max_y, max_z))


def _inflate_bounds(bounds: _Bounds, inflation: float) -> _Bounds:
    if inflation == 1.0:
        return _non_degenerate_bounds(bounds)
    center = Vector3(
        (bounds.minimum.x + bounds.maximum.x) * 0.5,
        (bounds.minimum.y + bounds.maximum.y) * 0.5,
        (bounds.minimum.z + bounds.maximum.z) * 0.5,
    )
    half = Vector3(
        (bounds.maximum.x - bounds.minimum.x) * 0.5 * inflation,
        (bounds.maximum.y - bounds.minimum.y) * 0.5 * inflation,
        (bounds.maximum.z - bounds.minimum.z) * 0.5 * inflation,
    )
    return _non_degenerate_bounds(
        _Bounds(
            Vector3(center.x - half.x, center.y - half.y, center.z - half.z),
            Vector3(center.x + half.x, center.y + half.y, center.z + half.z),
        )
    )


def _non_degenerate_bounds(bounds: _Bounds) -> _Bounds:
    extent_x = bounds.maximum.x - bounds.minimum.x
    extent_y = bounds.maximum.y - bounds.minimum.y
    extent_z = bounds.maximum.z - bounds.minimum.z
    max_extent = max(extent_x, extent_y, extent_z, 1.0)
    pad = max_extent * 0.005
    min_x = bounds.minimum.x - (pad if extent_x <= 0.0 else 0.0)
    min_y = bounds.minimum.y - (pad if extent_y <= 0.0 else 0.0)
    min_z = bounds.minimum.z - (pad if extent_z <= 0.0 else 0.0)
    max_x = bounds.maximum.x + (pad if extent_x <= 0.0 else 0.0)
    max_y = bounds.maximum.y + (pad if extent_y <= 0.0 else 0.0)
    max_z = bounds.maximum.z + (pad if extent_z <= 0.0 else 0.0)
    return _Bounds(Vector3(min_x, min_y, min_z), Vector3(max_x, max_y, max_z))


def _prepare_foliage_kernel(
    *,
    name: str,
    local_bounds: _Bounds,
    position: Vector3,
    orientation: Quaternion,
    scale: Vector3,
) -> _PreparedFoliageKernel:
    if abs(scale.x) < 1e-9 or abs(scale.y) < 1e-9 or abs(scale.z) < 1e-9:
        raise ProxyMeshError("Proxy foliage instance has a zero scale component.")
    bounds = local_bounds
    local_center = Vector3(
        (bounds.minimum.x + bounds.maximum.x) * 0.5,
        (bounds.minimum.y + bounds.maximum.y) * 0.5,
        (bounds.minimum.z + bounds.maximum.z) * 0.5,
    )
    local_half_extent = Vector3(
        max((bounds.maximum.x - bounds.minimum.x) * 0.5, 1e-9),
        max((bounds.maximum.y - bounds.minimum.y) * 0.5, 1e-9),
        max((bounds.maximum.z - bounds.minimum.z) * 0.5, 1e-9),
    )
    return _PreparedFoliageKernel(
        name=name,
        world_bounds=_transformed_bounds(
            bounds,
            translate=position,
            orientation=orientation,
            scale=scale,
        ),
        position=position,
        inverse_orientation=_inverse_quaternion(orientation, label=f"repeated part {name}"),
        inverse_scale=Vector3(1.0 / scale.x, 1.0 / scale.y, 1.0 / scale.z),
        local_center=local_center,
        local_half_extent=local_half_extent,
    )


def _occupied_foliage_density_cells(
    instances: tuple[_PreparedFoliageKernel, ...],
    overall: _Bounds,
    resolution: int,
) -> tuple[np.ndarray, float, Vector3]:
    import numpy as np

    extent_x = overall.maximum.x - overall.minimum.x
    extent_y = overall.maximum.y - overall.minimum.y
    extent_z = overall.maximum.z - overall.minimum.z
    max_extent = max(extent_x, extent_y, extent_z, 1e-6)
    cell_size = max_extent / max(1, resolution)
    nx = max(1, int((extent_x / cell_size) + 0.999999))
    ny = max(1, int((extent_y / cell_size) + 0.999999))
    nz = max(1, int((extent_z / cell_size) + 0.999999))
    occupied = np.zeros((nx, ny, nz), dtype=np.bool_)
    fixed_x = (overall.minimum.x + overall.maximum.x) * 0.5 if extent_x <= cell_size else None
    fixed_y = (overall.minimum.y + overall.maximum.y) * 0.5 if extent_y <= cell_size else None
    fixed_z = (overall.minimum.z + overall.maximum.z) * 0.5 if extent_z <= cell_size else None

    for instance in instances:
        world_bounds = instance.world_bounds
        min_i = _clamp_cell_index(int((world_bounds.minimum.x - overall.minimum.x) // cell_size), nx)
        min_j = _clamp_cell_index(int((world_bounds.minimum.y - overall.minimum.y) // cell_size), ny)
        min_k = _clamp_cell_index(int((world_bounds.minimum.z - overall.minimum.z) // cell_size), nz)
        max_i = _clamp_cell_index(int((world_bounds.maximum.x - overall.minimum.x) // cell_size), nx)
        max_j = _clamp_cell_index(int((world_bounds.maximum.y - overall.minimum.y) // cell_size), ny)
        max_k = _clamp_cell_index(int((world_bounds.maximum.z - overall.minimum.z) // cell_size), nz)
        _mark_occupied_kernel_cells(
            occupied,
            instance=instance,
            i_range=(min_i, max_i),
            j_range=(min_j, max_j),
            k_range=(min_k, max_k),
            grid_minimum=overall.minimum,
            grid_maximum=overall.maximum,
            cell_size=cell_size,
            fixed_x=fixed_x,
            fixed_y=fixed_y,
            fixed_z=fixed_z,
            np=np,
        )

    if not bool(occupied.any()):
        raise ProxyMeshError("Proxy method density_field produced no occupied foliage cells.")
    return occupied, cell_size, overall.minimum


def _mark_occupied_kernel_cells(
    occupied: np.ndarray,
    *,
    instance: _PreparedFoliageKernel,
    i_range: tuple[int, int],
    j_range: tuple[int, int],
    k_range: tuple[int, int],
    grid_minimum: Vector3,
    grid_maximum: Vector3,
    cell_size: float,
    fixed_x: float | None,
    fixed_y: float | None,
    fixed_z: float | None,
    np,
) -> None:
    j_indices = np.arange(j_range[0], j_range[1] + 1, dtype=np.int32)
    k_indices = np.arange(k_range[0], k_range[1] + 1, dtype=np.int32)
    if j_indices.size == 0 or k_indices.size == 0:
        return
    y_values = (
        np.full(j_indices.shape, fixed_y, dtype=np.float64)
        if fixed_y is not None
        else np.minimum(grid_maximum.y, grid_minimum.y + (j_indices.astype(np.float64) + 0.5) * cell_size)
    )
    z_values = (
        np.full(k_indices.shape, fixed_z, dtype=np.float64)
        if fixed_z is not None
        else np.minimum(grid_maximum.z, grid_minimum.z + (k_indices.astype(np.float64) + 0.5) * cell_size)
    )
    yz_count = max(1, int(j_indices.size) * int(k_indices.size))
    max_cells_per_chunk = 300_000
    i_chunk_size = max(1, max_cells_per_chunk // yz_count)
    min_i, max_i = i_range
    for chunk_start in range(min_i, max_i + 1, i_chunk_size):
        chunk_stop = min(max_i, chunk_start + i_chunk_size - 1)
        i_indices = np.arange(chunk_start, chunk_stop + 1, dtype=np.int32)
        x_values = (
            np.full(i_indices.shape, fixed_x, dtype=np.float64)
            if fixed_x is not None
            else np.minimum(grid_maximum.x, grid_minimum.x + (i_indices.astype(np.float64) + 0.5) * cell_size)
        )
        mask = _prepared_kernel_mask(x_values, y_values, z_values, instance)
        occupied[
            chunk_start : chunk_stop + 1,
            j_range[0] : j_range[1] + 1,
            k_range[0] : k_range[1] + 1,
        ] |= mask


def _prepared_kernel_mask(x_values, y_values, z_values, instance: _PreparedFoliageKernel):
    import numpy as np

    q = instance.inverse_orientation
    rotation = np.asarray(
        (
            _rotate_components(q, 1.0, 0.0, 0.0),
            _rotate_components(q, 0.0, 1.0, 0.0),
            _rotate_components(q, 0.0, 0.0, 1.0),
        ),
        dtype=np.float64,
    ).T
    row_scale = np.asarray(
        (
            instance.inverse_scale.x / instance.local_half_extent.x,
            instance.inverse_scale.y / instance.local_half_extent.y,
            instance.inverse_scale.z / instance.local_half_extent.z,
        ),
        dtype=np.float64,
    )
    transform = rotation * row_scale[:, None]
    center = -np.asarray(
        (
            instance.local_center.x / instance.local_half_extent.x,
            instance.local_center.y / instance.local_half_extent.y,
            instance.local_center.z / instance.local_half_extent.z,
        ),
        dtype=np.float64,
    )
    quadratic = transform.T @ transform
    linear = 2.0 * (transform.T @ center)
    constant = float(center @ center)

    x = x_values - instance.position.x
    y = y_values - instance.position.y
    z = z_values - instance.position.z
    distance_squared = (
        (quadratic[1, 1] * y * y + linear[1] * y)[:, None]
        + (quadratic[2, 2] * z * z + linear[2] * z)[None, :]
        + 2.0 * quadratic[1, 2] * y[:, None] * z[None, :]
        + constant
    )
    distance_squared = (
        distance_squared[None, :, :]
        + (quadratic[0, 0] * x * x + linear[0] * x)[:, None, None]
    )
    distance_squared += 2.0 * quadratic[0, 1] * x[:, None, None] * y[None, :, None]
    distance_squared += 2.0 * quadratic[0, 2] * x[:, None, None] * z[None, None, :]
    return distance_squared <= 1.0


def _clamp_cell_index(value: int, count: int) -> int:
    return max(0, min(count - 1, value))


def _mesh_from_occupied_cells(
    occupied: np.ndarray,
    cell_size: float,
    grid_minimum: Vector3,
) -> GeometryBuffer:
    import numpy as np

    if not bool(occupied.any()):
        return GeometryBuffer(
            name="ProxyMesh",
            point_components=array("f"),
            face_vertex_counts=array("i"),
            face_vertex_indices=array("i"),
        )

    directions = np.asarray(
        ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)),
        dtype=np.int32,
    )
    corners = np.asarray(
        (
            ((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)),
            ((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)),
            ((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)),
            ((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)),
            ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)),
            ((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)),
        ),
        dtype=np.int32,
    )
    interior = occupied.copy()
    interior[:-1] &= occupied[1:]
    interior[-1] = False
    interior[1:] &= occupied[:-1]
    interior[0] = False
    interior[:, :-1] &= occupied[:, 1:]
    interior[:, -1] = False
    interior[:, 1:] &= occupied[:, :-1]
    interior[:, 0] = False
    interior[:, :, :-1] &= occupied[:, :, 1:]
    interior[:, :, -1] = False
    interior[:, :, 1:] &= occupied[:, :, :-1]
    interior[:, :, 0] = False
    np.logical_not(interior, out=interior)
    np.logical_and(interior, occupied, out=interior)
    cells = np.argwhere(interior).astype(np.int32, copy=False)

    present = np.zeros((len(cells), len(directions)), dtype=np.bool_)
    occupied_shape = np.asarray(occupied.shape, dtype=np.int32)
    for direction_index, direction in enumerate(directions):
        neighbor_cells = cells + direction
        valid = np.all((neighbor_cells >= 0) & (neighbor_cells < occupied_shape), axis=1)
        valid_neighbors = neighbor_cells[valid]
        present[valid, direction_index] = occupied[
            valid_neighbors[:, 0],
            valid_neighbors[:, 1],
            valid_neighbors[:, 2],
        ]
    face_cells, face_directions = np.nonzero(~present)
    vertex_keys = cells[face_cells, None, :] + corners[face_directions]
    flat_vertex_keys = vertex_keys.reshape((-1, 3))
    grid_shape = cells.max(axis=0).astype(np.int64) + 2
    strides = np.asarray((grid_shape[1] * grid_shape[2], grid_shape[2], 1), dtype=np.int64)
    vertex_ids = flat_vertex_keys.astype(np.int64) @ strides
    _unique_ids, first_indices, inverse_indices = np.unique(
        vertex_ids,
        return_index=True,
        return_inverse=True,
    )
    first_order = np.argsort(first_indices)
    point_keys = flat_vertex_keys[first_indices[first_order]]
    point_index_by_unique_id = np.empty(len(first_order), dtype=np.int32)
    point_index_by_unique_id[first_order] = np.arange(len(first_order), dtype=np.int32)
    quads = point_index_by_unique_id[inverse_indices].reshape((-1, 4))
    triangles = np.empty((len(quads) * 2, 3), dtype=np.int32)
    triangles[0::2] = quads[:, (0, 1, 2)]
    triangles[1::2] = quads[:, (0, 2, 3)]

    point_values = point_keys.astype(np.float64) * cell_size
    point_values += np.asarray((grid_minimum.x, grid_minimum.y, grid_minimum.z), dtype=np.float64)
    points = array("f")
    points.frombytes(np.asarray(point_values, dtype=np.float32).tobytes())
    face_counts = array("i", (3,)) * len(triangles)
    face_indices = array("i")
    face_indices.frombytes(triangles.tobytes())
    return GeometryBuffer(
        name="ProxyMesh",
        point_components=points,
        face_vertex_counts=face_counts,
        face_vertex_indices=face_indices,
    )


def _iter_points(mesh: MeshData | GeometryBuffer):
    if isinstance(mesh, GeometryBuffer):
        for index in range(0, len(mesh.point_components), 3):
            yield Vector3(mesh.point_components[index], mesh.point_components[index + 1], mesh.point_components[index + 2])
        return
    yield from mesh.points


def _box_corners(bounds: _Bounds, *, inflation: float) -> tuple[Vector3, ...]:
    minimum = bounds.minimum
    maximum = bounds.maximum
    if inflation != 1.0:
        center = Vector3(
            (minimum.x + maximum.x) * 0.5,
            (minimum.y + maximum.y) * 0.5,
            (minimum.z + maximum.z) * 0.5,
        )
        half = Vector3(
            (maximum.x - minimum.x) * 0.5 * inflation,
            (maximum.y - minimum.y) * 0.5 * inflation,
            (maximum.z - minimum.z) * 0.5 * inflation,
        )
        minimum = Vector3(center.x - half.x, center.y - half.y, center.z - half.z)
        maximum = Vector3(center.x + half.x, center.y + half.y, center.z + half.z)
    return (
        Vector3(minimum.x, minimum.y, minimum.z),
        Vector3(maximum.x, minimum.y, minimum.z),
        Vector3(minimum.x, maximum.y, minimum.z),
        Vector3(maximum.x, maximum.y, minimum.z),
        Vector3(minimum.x, minimum.y, maximum.z),
        Vector3(maximum.x, minimum.y, maximum.z),
        Vector3(minimum.x, maximum.y, maximum.z),
        Vector3(maximum.x, maximum.y, maximum.z),
    )


def _rotate_vector(q: Quaternion, value: Vector3) -> Vector3:
    x, y, z = _rotate_components(q, value.x, value.y, value.z)
    return Vector3(x, y, z)


def _rotate_components(q: Quaternion, x: float, y: float, z: float) -> tuple[float, float, float]:
    qw = q.real
    qx = q.i
    qy = q.j
    qz = q.k
    tx = 2.0 * (qy * z - qz * y)
    ty = 2.0 * (qz * x - qx * z)
    tz = 2.0 * (qx * y - qy * x)
    return (
        x + qw * tx + (qy * tz - qz * ty),
        y + qw * ty + (qz * tx - qx * tz),
        z + qw * tz + (qx * ty - qy * tx),
    )


def _validated_quaternion(q: Quaternion, *, label: str) -> Quaternion:
    try:
        real = float(q.real)
        i = float(q.i)
        j = float(q.j)
        k = float(q.k)
    except (TypeError, ValueError) as exc:
        raise ProxyMeshError(f"Proxy {label} has a malformed orientation quaternion: {q}.") from exc
    return Quaternion(real, i, j, k)


def _inverse_quaternion(q: Quaternion, *, label: str) -> Quaternion:
    q = _validated_quaternion(q, label=label)
    squared_length = q.real * q.real + q.i * q.i + q.j * q.j + q.k * q.k
    if squared_length <= 1e-12:
        raise ProxyMeshError(f"Proxy {label} has a zero-length orientation quaternion.")
    inverse_scale = 1.0 / (squared_length ** 0.5)
    return Quaternion(q.real * inverse_scale, -q.i * inverse_scale, -q.j * inverse_scale, -q.k * inverse_scale)


def _point_strings(mesh: GeometryBuffer):
    for index in range(0, len(mesh.point_components), 3):
        yield f"({mesh.point_components[index]:g}, {mesh.point_components[index + 1]:g}, {mesh.point_components[index + 2]:g})"


def _mesh_point_strings(mesh: MeshData):
    for point in mesh.points:
        yield f"({point.x:g}, {point.y:g}, {point.z:g})"


def _render_array(name: str, values, *, indent: str) -> str:
    payload = ", ".join(values)
    return f"{indent}{name} = [{payload}]"


def _single_input_path(request: ConversionRequest) -> str:
    if len(request.input_paths) != 1:
        raise ProxyMeshError("Proxy mesh generation supports exactly one input XML.")
    input_path = request.input_paths[0].strip()
    if not input_path:
        raise ProxyMeshError("Proxy mesh generation requires a source XML path.")
    return input_path


def _load_proxy_source_projection(request: ProxyMeshSourceRequest) -> tuple[str, CanonicalTreeModel]:
    input_path = request.input_path.strip()
    if not input_path:
        raise ProxyMeshError("Proxy mesh generation requires a source XML path.")
    return input_path, projection_to_tree_asset(load_proxy_source_projection(input_path))
