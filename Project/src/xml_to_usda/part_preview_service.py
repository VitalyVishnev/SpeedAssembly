"""Instanced Geometry prototype preview projection.

Layer: application.

The module loads one Resolved Prototype from the normal conversion seams and
projects it into a viewport payload. It does not own Qt widgets, OpenGL, or
Persisted Operator Settings.
"""

from __future__ import annotations

import hashlib
from array import array
from dataclasses import dataclass, replace
from enum import Enum

from .canonical_loader import load_resolved_assembly_model
from .fbx_adapter import load_fbx_geometry
from .fbx_payload_cache import FbxPayloadCacheOptions, load_fbx_payload_from_cache, store_fbx_payload_in_cache
from .geometry_buffers import geometry_buffer_from_mesh
from .models import (
    Color4,
    CompactMeshSection,
    ConversionMode,
    CpuProfile,
    GeometryBuffer,
    MaterialSpec,
    MaterialPolicy,
    OutputMode,
    PrototypeSourceConfig,
    PrototypeSourceMode,
)
from .prototype_sources import fbx_import_read_options_for_material_mode
from .prototype_simplification import predicted_simplified_triangle_count, simplify_geometry_buffer
from .viewport_scene import geometry_triangle_count


MAX_PART_PREVIEW_DISPLAY_FACES = 50_000


class PartPreviewDisplayMode(str, Enum):
    DEFAULT = "default"
    VERTEX_COLORS = "vertex_colors"
    MATERIAL_COLORS = "material_colors"


@dataclass(frozen=True)
class PartPrototypePreviewRequest:
    input_path: str
    source_key: str
    source_name: str
    prototype_source_config: PrototypeSourceConfig
    cpu_profile: CpuProfile = CpuProfile.BALANCED
    fbx_cache_max_bytes: int = 20 * 1024 * 1024 * 1024
    fbx_cache_max_age_seconds: int = 14 * 24 * 60 * 60


@dataclass(frozen=True)
class PartPrototypePreviewSettings:
    display_mode: PartPreviewDisplayMode = PartPreviewDisplayMode.DEFAULT


@dataclass(frozen=True)
class PartMaterialPreviewColor:
    material_id: int
    label: str
    color: Color4


@dataclass(frozen=True)
class PartPrototypePreviewResult:
    source_key: str
    source_name: str
    source_mode: PrototypeSourceMode
    mesh: GeometryBuffer | None
    source_triangle_count: int = 0
    displayed_triangle_count: int = 0
    predicted_export_triangle_count: int = 0
    source_section_triangle_counts: tuple[int, ...] = ()
    material_colors: tuple[PartMaterialPreviewColor, ...] = ()
    preview_limited: bool = False


def build_part_prototype_preview(
    request: PartPrototypePreviewRequest,
    settings: PartPrototypePreviewSettings,
    *,
    telemetry_callback=None,
    cancel_event=None,
) -> PartPrototypePreviewResult:
    config = request.prototype_source_config
    if config.mode == PrototypeSourceMode.UNREAL_ASSET:
        return PartPrototypePreviewResult(
            source_key=request.source_key,
            source_name=request.source_name,
            source_mode=config.mode,
            mesh=None,
        )
    if config.mode == PrototypeSourceMode.FBX_FILE:
        return _build_fbx_part_preview(request, settings, cancel_event=cancel_event)

    load_config = replace(config, simplification_percent=100)
    _report, resolved = load_resolved_assembly_model(
        request.input_path,
        output_mode=OutputMode.SELF_CONTAINED,
        material_policy=MaterialPolicy.SOURCE_MATERIALS,
        cpu_profile=request.cpu_profile,
        use_explicit_material_contract=_uses_explicit_material_contract(config),
        prototype_source_configs=(load_config,),
        conversion_mode=ConversionMode.SKELETAL_ASSEMBLY,
        fbx_cache_max_bytes=request.fbx_cache_max_bytes,
        fbx_cache_max_age_seconds=request.fbx_cache_max_age_seconds,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
    )
    prototype = _find_prototype(resolved.authoring_model.prototypes, request.source_key, request.source_name)
    if prototype is None:
        raise ValueError(f"Part preview could not find prototype {request.source_name or request.source_key}.")
    source_payload = prototype.geometry_payload or (geometry_buffer_from_mesh(prototype.mesh) if prototype.mesh is not None else None)
    if source_payload is None:
        return PartPrototypePreviewResult(
            source_key=request.source_key,
            source_name=request.source_name,
            source_mode=prototype.source_mode,
            mesh=None,
        )
    return _preview_result_from_payload(
        request,
        source_mode=prototype.source_mode,
        source_payload=source_payload,
        material_specs=getattr(resolved.authoring_model, "materials", ()),
        cancel_event=cancel_event,
    )


def _build_fbx_part_preview(
    request: PartPrototypePreviewRequest,
    _settings: PartPrototypePreviewSettings,
    *,
    cancel_event=None,
) -> PartPrototypePreviewResult:
    config = request.prototype_source_config
    if not config.fbx_path:
        raise ValueError("Choose an FBX file before previewing an FBX prototype.")
    read_options = fbx_import_read_options_for_material_mode(config.fbx_material_mode)
    cache_options = FbxPayloadCacheOptions(
        read_vertex_colors=read_options.read_vertex_colors,
        read_material_slots=read_options.read_material_slots,
        strict_vertex_colors=read_options.strict_vertex_colors,
    )
    cached = load_fbx_payload_from_cache(config.fbx_path, cache_options)
    source_payload = cached.payload
    if source_payload is None:
        source_payload = load_fbx_geometry(
            config.fbx_path,
            request.source_name or request.source_key,
            cpu_profile=request.cpu_profile,
            strict_vertex_colors=read_options.strict_vertex_colors,
            read_vertex_colors=read_options.read_vertex_colors,
            read_material_slots=read_options.read_material_slots,
        )
        store_fbx_payload_in_cache(
            config.fbx_path,
            cache_options,
            source_payload,
            max_bytes=request.fbx_cache_max_bytes,
            max_age_seconds=request.fbx_cache_max_age_seconds,
        )
    else:
        source_payload = replace(source_payload, name=request.source_name or request.source_key)
    return _preview_result_from_payload(
        request,
        source_mode=config.mode,
        source_payload=source_payload,
        material_specs=(),
        cancel_event=cancel_event,
    )


def _preview_result_from_payload(
    request: PartPrototypePreviewRequest,
    *,
    source_mode: PrototypeSourceMode,
    source_payload: GeometryBuffer,
    material_specs: tuple[MaterialSpec, ...],
    cancel_event=None,
) -> PartPrototypePreviewResult:
    config = request.prototype_source_config
    source_triangle_count = geometry_triangle_count(source_payload)
    source_section_triangle_counts = _section_triangle_counts(source_payload)
    predicted_export_triangle_count = _predicted_export_triangle_count(
        source_payload,
        config.simplification_percent,
        source_triangle_count=source_triangle_count,
    )
    preview_limited = source_payload.face_count > MAX_PART_PREVIEW_DISPLAY_FACES
    if preview_limited:
        payload = _sample_geometry_faces(
            source_payload,
            max_faces=min(MAX_PART_PREVIEW_DISPLAY_FACES, max(1, predicted_export_triangle_count)),
            cancel_event=cancel_event,
        )
    elif config.simplification_percent < 100:
        payload = simplify_geometry_buffer(
            source_payload,
            config.simplification_percent,
            cancel_event=cancel_event,
        )
    else:
        payload = source_payload
    material_colors = _material_color_legend(payload, material_specs)
    return PartPrototypePreviewResult(
        source_key=request.source_key,
        source_name=request.source_name,
        source_mode=source_mode,
        mesh=payload,
        source_triangle_count=source_triangle_count,
        displayed_triangle_count=geometry_triangle_count(payload),
        predicted_export_triangle_count=predicted_export_triangle_count,
        source_section_triangle_counts=source_section_triangle_counts,
        material_colors=material_colors,
        preview_limited=preview_limited,
    )


def part_preview_display_mesh(
    result: PartPrototypePreviewResult,
    display_mode: PartPreviewDisplayMode,
) -> GeometryBuffer | None:
    """Project an already loaded preview payload into one visual mode."""
    source_mesh = result.mesh
    if source_mesh is None:
        return None
    if PartPreviewDisplayMode(display_mode) == PartPreviewDisplayMode.MATERIAL_COLORS:
        return _material_color_display_mesh(source_mesh, result.material_colors)
    return source_mesh


def _predicted_export_triangle_count(
    mesh: GeometryBuffer,
    percent: int,
    *,
    source_triangle_count: int,
) -> int:
    if mesh.face_count <= MAX_PART_PREVIEW_DISPLAY_FACES:
        return predicted_simplified_triangle_count(mesh, percent)
    if source_triangle_count <= 0:
        return 0
    resolved_percent = max(0, min(100, int(percent)))
    if resolved_percent >= 100:
        return source_triangle_count
    return max(1, round(source_triangle_count * resolved_percent / 100.0))


def _sample_geometry_faces(
    mesh: GeometryBuffer,
    *,
    max_faces: int,
    cancel_event=None,
) -> GeometryBuffer:
    source_face_count = mesh.face_count
    target_face_count = min(source_face_count, max(1, int(max_faces)))
    if target_face_count >= source_face_count:
        return mesh

    selected_faces = tuple(
        index * source_face_count // target_face_count
        for index in range(target_face_count)
    )
    selected_source_to_output: dict[int, int] = {}
    point_map: dict[int, int] = {}
    point_components = array("f")
    face_vertex_counts = array("i")
    face_vertex_indices = array("i")
    normal_components = array("f")
    uv_components = array("f")
    secondary_uv_components = array("f")
    vertex_color_components = array("f")
    skel_joint_indices = array("i")
    skel_joint_weights = array("f")

    source_corner_count = len(mesh.face_vertex_indices)
    normals_by_point = len(mesh.normal_components) == mesh.point_count * 3
    normals_by_corner = len(mesh.normal_components) == source_corner_count * 3
    uvs_by_corner = len(mesh.uv_components) == source_corner_count * 2
    secondary_uvs_by_corner = len(mesh.secondary_uv_components) == source_corner_count * 2
    colors_by_point = len(mesh.vertex_color_components) >= mesh.point_count * 4
    skel_by_point = mesh.skel_element_size > 0 and (
        len(mesh.skel_joint_indices) >= mesh.point_count * mesh.skel_element_size
        and len(mesh.skel_joint_weights) >= mesh.point_count * mesh.skel_element_size
    )

    selected_position = 0
    source_corner_offset = 0
    for source_face_index, raw_count in enumerate(mesh.face_vertex_counts):
        count = int(raw_count)
        if source_face_index % 100_000 == 0 and cancel_event is not None:
            if getattr(cancel_event, "is_set", lambda: False)():
                raise ValueError("Part preview sampling was cancelled.")
        if source_face_index != selected_faces[selected_position]:
            source_corner_offset += count
            continue

        output_face_index = len(face_vertex_counts)
        selected_source_to_output[source_face_index] = output_face_index
        face_vertex_counts.append(count)
        for local_corner in range(count):
            source_corner = source_corner_offset + local_corner
            source_point = int(mesh.face_vertex_indices[source_corner])
            output_point = point_map.get(source_point)
            if output_point is None:
                output_point = len(point_map)
                point_map[source_point] = output_point
                point_offset = source_point * 3
                point_components.extend(mesh.point_components[point_offset:point_offset + 3])
                if normals_by_point:
                    normal_components.extend(mesh.normal_components[point_offset:point_offset + 3])
                if colors_by_point:
                    color_offset = source_point * 4
                    vertex_color_components.extend(mesh.vertex_color_components[color_offset:color_offset + 4])
                if skel_by_point:
                    skel_offset = source_point * mesh.skel_element_size
                    skel_joint_indices.extend(
                        mesh.skel_joint_indices[skel_offset:skel_offset + mesh.skel_element_size]
                    )
                    skel_joint_weights.extend(
                        mesh.skel_joint_weights[skel_offset:skel_offset + mesh.skel_element_size]
                    )
            face_vertex_indices.append(output_point)
            if normals_by_corner:
                normal_offset = source_corner * 3
                normal_components.extend(mesh.normal_components[normal_offset:normal_offset + 3])
            if uvs_by_corner:
                uv_offset = source_corner * 2
                uv_components.extend(mesh.uv_components[uv_offset:uv_offset + 2])
            if secondary_uvs_by_corner:
                uv_offset = source_corner * 2
                secondary_uv_components.extend(mesh.secondary_uv_components[uv_offset:uv_offset + 2])

        source_corner_offset += count
        selected_position += 1
        if selected_position >= target_face_count:
            break

    sections = tuple(
        CompactMeshSection(
            material_id=section.material_id,
            face_indices=array(
                "i",
                (
                    selected_source_to_output[int(source_face)]
                    for source_face in section.face_indices
                    if int(source_face) in selected_source_to_output
                ),
            ),
        )
        for section in mesh.sections
    )
    return GeometryBuffer(
        name=mesh.name,
        point_components=point_components,
        face_vertex_counts=face_vertex_counts,
        face_vertex_indices=face_vertex_indices,
        normal_components=normal_components,
        uv_components=uv_components,
        secondary_uv_components=secondary_uv_components,
        vertex_color_components=vertex_color_components,
        vertex_color_warning=mesh.vertex_color_warning,
        fbx_material_slots=mesh.fbx_material_slots,
        sections=tuple(section for section in sections if section.face_indices),
        skel_joint_indices=skel_joint_indices,
        skel_joint_weights=skel_joint_weights,
        skel_element_size=mesh.skel_element_size if skel_joint_indices else 0,
    )


def _uses_explicit_material_contract(config: PrototypeSourceConfig) -> bool:
    if config.mode == PrototypeSourceMode.UNREAL_ASSET:
        return False
    if config.mode == PrototypeSourceMode.FBX_FILE:
        return True
    if config.fbx_material_mode.value != "vertex_color_split":
        return True
    if config.single_material_path or config.black_material_path or config.white_material_path:
        return True
    return config.has_active_udim_settings()


def _find_prototype(prototypes, source_key: str, source_name: str):
    for prototype in prototypes:
        if prototype.source_key == source_key:
            return prototype
    for prototype in prototypes:
        if source_name and prototype.source_name == source_name:
            return prototype
    return None


def _material_color_legend(
    mesh: GeometryBuffer,
    materials: tuple[MaterialSpec, ...] = (),
) -> tuple[PartMaterialPreviewColor, ...]:
    material_by_id = {material.source_id: material for material in materials}
    return tuple(
        PartMaterialPreviewColor(
            material_id=section.material_id,
            label=_material_label(section.material_id, material_by_id),
            color=_stable_material_color(_material_color_key(section.material_id, material_by_id)),
        )
        for section in mesh.sections
    )


def _material_label(material_id: int, material_by_id: dict[int, MaterialSpec]) -> str:
    material = material_by_id.get(material_id)
    if material is not None and material.name:
        return material.name
    return f"Material {material_id}"


def _material_color_key(material_id: int, material_by_id: dict[int, MaterialSpec]) -> str:
    material = material_by_id.get(material_id)
    if material is None:
        return str(material_id)
    return f"{material_id}:{material.name}:{material.ue_asset_path or ''}"


def _section_triangle_counts(mesh: GeometryBuffer) -> tuple[int, ...]:
    face_triangle_counts = tuple(max(0, int(count) - 2) for count in mesh.face_vertex_counts)
    if not mesh.sections:
        total = sum(face_triangle_counts)
        return (total,) if total else ()
    counts: list[int] = []
    for section in mesh.sections:
        total = 0
        for face_index in section.face_indices:
            if 0 <= int(face_index) < len(face_triangle_counts):
                total += face_triangle_counts[int(face_index)]
        if total:
            counts.append(total)
    return tuple(counts)


def _material_color_display_mesh(
    mesh: GeometryBuffer,
    material_colors: tuple[PartMaterialPreviewColor, ...],
) -> GeometryBuffer:
    color_by_id = {entry.material_id: entry.color for entry in material_colors}
    material_by_face: dict[int, int] = {}
    for section in mesh.sections:
        for face_index in section.face_indices:
            material_by_face[int(face_index)] = section.material_id

    source_points = tuple(
        (
            mesh.point_components[index],
            mesh.point_components[index + 1],
            mesh.point_components[index + 2],
        )
        for index in range(0, len(mesh.point_components), 3)
    )
    point_components = array("f")
    face_counts = array("i")
    face_indices = array("i")
    vertex_colors = array("f")
    offset = 0
    next_point = 0
    for face_index, raw_count in enumerate(mesh.face_vertex_counts):
        count = int(raw_count)
        indices = [int(mesh.face_vertex_indices[offset + local]) for local in range(count)]
        offset += count
        if count < 3:
            continue
        color = color_by_id.get(material_by_face.get(face_index), Color4(1.0, 1.0, 1.0, 1.0))
        for triangle_index in range(1, count - 1):
            triangle = (indices[0], indices[triangle_index], indices[triangle_index + 1])
            face_counts.append(3)
            for source_index in triangle:
                point_components.extend(source_points[source_index])
                face_indices.append(next_point)
                vertex_colors.extend((color.r, color.g, color.b, 1.0))
                next_point += 1
    return GeometryBuffer(
        name=mesh.name,
        point_components=point_components,
        face_vertex_counts=face_counts,
        face_vertex_indices=face_indices,
        vertex_color_components=vertex_colors,
    )


def _stable_material_color(key: str) -> Color4:
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    hue = digest[0] / 255.0
    saturation = 0.58 + (digest[1] / 255.0) * 0.28
    value = 0.78 + (digest[2] / 255.0) * 0.18
    red, green, blue = _hsv_to_rgb(hue, saturation, value)
    return Color4(red, green, blue, 1.0)


def _hsv_to_rgb(hue: float, saturation: float, value: float) -> tuple[float, float, float]:
    if saturation <= 0.0:
        return value, value, value
    hue = (hue % 1.0) * 6.0
    sector = int(hue)
    fraction = hue - sector
    p = value * (1.0 - saturation)
    q = value * (1.0 - saturation * fraction)
    t = value * (1.0 - saturation * (1.0 - fraction))
    if sector == 0:
        return value, t, p
    if sector == 1:
        return q, value, p
    if sector == 2:
        return p, value, t
    if sector == 3:
        return p, q, value
    if sector == 4:
        return t, p, value
    return value, p, q
