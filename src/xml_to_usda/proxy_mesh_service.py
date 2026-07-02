"""Proxy mesh generation and USDA export service.

Layer: application/domain boundary.

The proxy mesh is a companion asset. It is generated from the resolved
CanonicalTreeModel and written as one static polygonal USDA mesh, separate from
the main vegetation export contract.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass
from pathlib import Path

from .mesh_pruning import DEFAULT_BRANCH_PRUNE_AGGRESSION, select_large_connected_face_indices
from .models import CanonicalTreeModel, GeometryBuffer, MeshData, Prototype, Quaternion, Vector3
from .models import ConversionRequest, CpuProfile, OutputMode
from .naming import make_stable_prim_name
from .output_resolution import ensure_output_path_allowed
from .proxy_source_projection import load_proxy_source_projection, projection_to_tree_asset


DEFAULT_PROXY_POLYCOUNT = 5000
MAX_PROXY_DENSITY_RESOLUTION = 256
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
    branch_prune_aggression: float = DEFAULT_BRANCH_PRUNE_AGGRESSION


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


@dataclass(frozen=True)
class ProxyMeshExportResult:
    input_path: str
    output_path: str
    proxy: ProxyMeshResult
    usda_text: str


class ProxyMeshJobResult:
    __slots__ = ("proxy", "export", "cancelled", "error_message")

    def __init__(
        self,
        proxy: ProxyMeshResult | None = None,
        export: ProxyMeshExportResult | None = None,
        cancelled: bool = False,
        error_message: str | None = None,
    ) -> None:
        self.proxy = proxy
        self.export = export
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

    return ProxyMeshResult(
        mesh=mesh,
        settings=resolved_settings,
        method=resolved_settings.method,
        source_instance_count=len(model.repeated_parts),
        included_base_mesh=included_base,
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
    if not has_foliage:
        return _mesh_to_geometry_buffer(mesh, name="BaseProxyMesh")
    face_indices = select_large_connected_face_indices(
        mesh,
        aggression=settings.branch_prune_aggression,
    )
    if face_indices is None:
        return _mesh_to_geometry_buffer(mesh, name="BaseProxyMesh")
    return _mesh_faces_to_geometry_buffer(mesh, face_indices, name="BaseProxyMesh")


def _mesh_faces_to_geometry_buffer(mesh: MeshData, face_indices: tuple[int, ...], *, name: str) -> GeometryBuffer:
    points = array("f")
    face_counts = array("i")
    face_vertex_indices = array("i")
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
                new_point_index = len(points) // 3
                original_to_new_point[source_point_index] = new_point_index
                points.extend((point.x, point.y, point.z))
            face_vertex_indices.append(new_point_index)
        offset = end
    return GeometryBuffer(
        name=name,
        point_components=points,
        face_vertex_counts=face_counts,
        face_vertex_indices=face_vertex_indices,
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
    points, triangles = _triangulated_mesh_arrays(mesh)
    if len(triangles) == 0:
        raise ProxyMeshError(f"Proxy method {method} produced no surface triangles.")
    target_triangle_count = max(1, int(target_triangle_count))
    if len(triangles) <= target_triangle_count:
        return _geometry_buffer_from_triangles(points, triangles, name=mesh.name)
    try:
        import fast_simplification
    except ImportError as exc:
        raise ProxyMeshError("Proxy QEM simplification requires the fast-simplification package.") from exc
    try:
        simplified_points, simplified_triangles = fast_simplification.simplify(
            points,
            triangles,
            target_count=target_triangle_count,
        )
    except Exception as exc:
        raise ProxyMeshError(f"Proxy QEM simplification failed: {exc}") from exc
    if len(simplified_points) == 0 or len(simplified_triangles) == 0:
        return _geometry_buffer_from_triangles(points, triangles, name=mesh.name)
    _validate_triangle_arrays(simplified_points, simplified_triangles, name=mesh.name)
    return _geometry_buffer_from_triangles(simplified_points, simplified_triangles, name=mesh.name)


def _triangulated_mesh_arrays(mesh: GeometryBuffer):
    import numpy as np

    if len(mesh.point_components) % 3 != 0:
        raise ProxyMeshError(f"Proxy mesh {mesh.name} point component count must be divisible by 3.")
    points = np.asarray(mesh.point_components, dtype=np.float64).reshape((-1, 3))
    if len(points) == 0:
        raise ProxyMeshError(f"Proxy mesh {mesh.name} has no points.")
    if not bool(np.isfinite(points).all()):
        raise ProxyMeshError(f"Proxy mesh {mesh.name} contains non-finite point coordinates.")
    triangles: list[tuple[int, int, int]] = []
    offset = 0
    point_count = len(points)
    for face_index, count in enumerate(mesh.face_vertex_counts):
        count = int(count)
        if count < 0:
            raise ProxyMeshError(f"Proxy mesh {mesh.name} face {face_index} has a negative vertex count.")
        if offset + count > len(mesh.face_vertex_indices):
            raise ProxyMeshError(f"Proxy mesh {mesh.name} face {face_index} is missing vertex indices.")
        face_indices = [int(mesh.face_vertex_indices[offset + index]) for index in range(count)]
        offset += count
        for point_index in face_indices:
            if point_index < 0 or point_index >= point_count:
                raise ProxyMeshError(
                    f"Proxy mesh {mesh.name} face {face_index} references point {point_index} outside the mesh."
                )
        if count < 3:
            continue
        anchor = face_indices[0]
        for index in range(1, count - 1):
            triangles.append((anchor, face_indices[index], face_indices[index + 1]))
    if offset != len(mesh.face_vertex_indices):
        raise ProxyMeshError(f"Proxy mesh {mesh.name} has trailing face vertex indices.")
    triangle_array = np.asarray(triangles, dtype=np.int32)
    _validate_triangle_arrays(points, triangle_array, name=mesh.name)
    return points, triangle_array


def _validate_triangle_arrays(points, triangles, *, name: str) -> None:
    import numpy as np

    if len(points) == 0:
        raise ProxyMeshError(f"Proxy mesh {name} has no points.")
    if not bool(np.isfinite(points).all()):
        raise ProxyMeshError(f"Proxy mesh {name} contains non-finite point coordinates.")
    if len(triangles) == 0:
        return
    if triangles.ndim != 2 or triangles.shape[1] != 3:
        raise ProxyMeshError(f"Proxy mesh {name} simplification produced invalid triangle topology.")
    if int(triangles.min()) < 0 or int(triangles.max()) >= len(points):
        raise ProxyMeshError(f"Proxy mesh {name} simplification produced triangle indices outside the mesh.")


def _geometry_buffer_from_triangles(points, triangles, *, name: str) -> GeometryBuffer:
    point_components = array("f")
    for point in points:
        point_components.extend((float(point[0]), float(point[1]), float(point[2])))
    face_counts = array("i", [3 for _ in range(len(triangles))])
    face_indices = array("i")
    for triangle in triangles:
        face_indices.extend((int(triangle[0]), int(triangle[1]), int(triangle[2])))
    return GeometryBuffer(
        name=name,
        point_components=point_components,
        face_vertex_counts=face_counts,
        face_vertex_indices=face_indices,
    )


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
    """Render one geometry-only USDA document for a generated proxy mesh."""
    safe_root_name = make_stable_prim_name(root_name, fallback="Proxy")
    mesh = proxy.mesh
    return "\n".join(
        (
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
            "}",
            "",
        )
    )


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
) -> tuple[set[tuple[int, int, int]], float, Vector3]:
    import numpy as np

    extent_x = overall.maximum.x - overall.minimum.x
    extent_y = overall.maximum.y - overall.minimum.y
    extent_z = overall.maximum.z - overall.minimum.z
    max_extent = max(extent_x, extent_y, extent_z, 1e-6)
    cell_size = max_extent / max(1, resolution)
    nx = max(1, int((extent_x / cell_size) + 0.999999))
    ny = max(1, int((extent_y / cell_size) + 0.999999))
    nz = max(1, int((extent_z / cell_size) + 0.999999))
    occupied: set[tuple[int, int, int]] = set()
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

    if not occupied:
        raise ProxyMeshError("Proxy method density_field produced no occupied foliage cells.")
    return occupied, cell_size, overall.minimum


def _mark_occupied_kernel_cells(
    occupied: set[tuple[int, int, int]],
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
        if not bool(mask.any()):
            continue
        local_i, local_j, local_k = np.nonzero(mask)
        occupied.update(
            zip(
                i_indices[local_i].astype(int).tolist(),
                j_indices[local_j].astype(int).tolist(),
                k_indices[local_k].astype(int).tolist(),
            )
        )


def _prepared_kernel_mask(x_values, y_values, z_values, instance: _PreparedFoliageKernel):
    x = x_values[:, None, None] - instance.position.x
    y = y_values[None, :, None] - instance.position.y
    z = z_values[None, None, :] - instance.position.z
    q = instance.inverse_orientation
    tx = 2.0 * (q.j * z - q.k * y)
    ty = 2.0 * (q.k * x - q.i * z)
    tz = 2.0 * (q.i * y - q.j * x)
    local_x = (x + q.real * tx + (q.j * tz - q.k * ty)) * instance.inverse_scale.x
    local_y = (y + q.real * ty + (q.k * tx - q.i * tz)) * instance.inverse_scale.y
    local_z = (z + q.real * tz + (q.i * ty - q.j * tx)) * instance.inverse_scale.z
    dx = (local_x - instance.local_center.x) / instance.local_half_extent.x
    dy = (local_y - instance.local_center.y) / instance.local_half_extent.y
    dz = (local_z - instance.local_center.z) / instance.local_half_extent.z
    return dx * dx + dy * dy + dz * dz <= 1.0


def _clamp_cell_index(value: int, count: int) -> int:
    return max(0, min(count - 1, value))


def _mesh_from_occupied_cells(
    occupied: set[tuple[int, int, int]],
    cell_size: float,
    grid_minimum: Vector3,
) -> GeometryBuffer:
    points = array("f")
    face_counts = array("i")
    face_indices = array("i")
    vertex_indices: dict[tuple[int, int, int], int] = {}
    directions = (
        ((1, 0, 0), ((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1))),
        ((-1, 0, 0), ((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0))),
        ((0, 1, 0), ((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0))),
        ((0, -1, 0), ((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1))),
        ((0, 0, 1), ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))),
        ((0, 0, -1), ((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0))),
    )
    for i, j, k in sorted(occupied):
        for direction, corners in directions:
            neighbor = (i + direction[0], j + direction[1], k + direction[2])
            if neighbor in occupied:
                continue
            face = []
            for corner in corners:
                vertex_key = (i + corner[0], j + corner[1], k + corner[2])
                vertex_index = vertex_indices.get(vertex_key)
                if vertex_index is None:
                    vertex_index = len(points) // 3
                    vertex_indices[vertex_key] = vertex_index
                    points.extend(
                        (
                            grid_minimum.x + vertex_key[0] * cell_size,
                            grid_minimum.y + vertex_key[1] * cell_size,
                            grid_minimum.z + vertex_key[2] * cell_size,
                        )
                    )
                face.append(vertex_index)
            face_counts.append(4)
            face_indices.extend(face)
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
