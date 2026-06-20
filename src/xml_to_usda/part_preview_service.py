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
from .geometry_buffers import geometry_buffer_from_mesh
from .models import (
    Color4,
    ConversionMode,
    CpuProfile,
    GeometryBuffer,
    MaterialSpec,
    MaterialPolicy,
    OutputMode,
    PrototypeSourceConfig,
    PrototypeSourceMode,
)
from .prototype_simplification import predicted_simplified_triangle_count, simplify_geometry_buffer
from .viewport_scene import geometry_triangle_count


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

    source_triangle_count = geometry_triangle_count(source_payload)
    source_section_triangle_counts = _section_triangle_counts(source_payload)
    payload = (
        simplify_geometry_buffer(source_payload, config.simplification_percent, cancel_event=cancel_event)
        if config.simplification_percent < 100
        else source_payload
    )
    material_colors = _material_color_legend(payload, getattr(resolved.authoring_model, "materials", ()))
    display_mode = PartPreviewDisplayMode(settings.display_mode)
    if display_mode == PartPreviewDisplayMode.MATERIAL_COLORS:
        display_mesh = _material_color_display_mesh(payload, material_colors)
    elif display_mode == PartPreviewDisplayMode.VERTEX_COLORS:
        display_mesh = payload
    else:
        display_mesh = _without_vertex_colors(payload)
    return PartPrototypePreviewResult(
        source_key=request.source_key,
        source_name=request.source_name,
        source_mode=prototype.source_mode,
        mesh=display_mesh,
        source_triangle_count=source_triangle_count,
        displayed_triangle_count=geometry_triangle_count(display_mesh),
        predicted_export_triangle_count=predicted_simplified_triangle_count(
            source_payload,
            config.simplification_percent,
        ),
        source_section_triangle_counts=source_section_triangle_counts,
        material_colors=material_colors,
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


def _without_vertex_colors(mesh: GeometryBuffer) -> GeometryBuffer:
    if not mesh.vertex_color_components:
        return mesh
    return GeometryBuffer(
        name=mesh.name,
        point_components=array("f", mesh.point_components),
        face_vertex_counts=array("i", mesh.face_vertex_counts),
        face_vertex_indices=array("i", mesh.face_vertex_indices),
        uv_components=array("f", mesh.uv_components),
        secondary_uv_components=array("f", mesh.secondary_uv_components),
        vertex_color_warning=mesh.vertex_color_warning,
        fbx_material_slots=mesh.fbx_material_slots,
        sections=mesh.sections,
        skel_joint_indices=array("i", mesh.skel_joint_indices),
        skel_joint_weights=array("f", mesh.skel_joint_weights),
        skel_element_size=mesh.skel_element_size,
    )


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
