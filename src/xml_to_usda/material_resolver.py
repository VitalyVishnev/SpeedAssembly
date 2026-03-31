from __future__ import annotations

from array import array
from dataclasses import replace

from .geometry_buffers import replace_payload_sections, single_material_sections
from .models import (
    CanonicalTreeModel,
    CompactMeshSection,
    CpuProfile,
    FbxMaterialMode,
    GeometryBuffer,
    MaterialPolicy,
    MaterialSpec,
    MeshData,
    MeshSection,
    PrototypeSourceMode,
)
from .payload_partition import partition_fbx_material_faces


BASELINE_BARK_MATERIAL_ID = 1
BASELINE_LEAVES_MATERIAL_ID = 2


def resolve_prototype_materials(
    model: CanonicalTreeModel,
    *,
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
    cancel_event=None,
) -> CanonicalTreeModel:
    prototypes = []
    warnings: list[str] = []
    for prototype in model.prototypes:
        geometry_payload = prototype.geometry_payload
        if prototype.source_mode == PrototypeSourceMode.FBX_FILE and geometry_payload is not None:
            sections = _resolve_fbx_material_sections(
                prototype,
                cpu_profile=cpu_profile,
                cancel_event=cancel_event,
                warnings=warnings,
            )
            prototypes.append(replace(prototype, geometry_payload=replace_payload_sections(geometry_payload, sections)))
            continue
        prototypes.append(prototype)
    metadata = model.metadata
    if warnings:
        metadata = replace(metadata, warnings=metadata.warnings + tuple(warnings))
    return replace(model, prototypes=tuple(prototypes), metadata=metadata)


def apply_material_policy(
    model: CanonicalTreeModel,
    material_policy: MaterialPolicy,
    bark_material_path: str | None,
    leaves_material_path: str | None,
    single_material_path: str | None,
    normalize_asset_path,
) -> CanonicalTreeModel:
    if material_policy == MaterialPolicy.LEGACY_ROLE_IDS:
        return _apply_legacy_material_policy(model, bark_material_path, leaves_material_path, normalize_asset_path)
    if material_policy == MaterialPolicy.SINGLE_MATERIAL:
        return _apply_single_material_policy(model, single_material_path, normalize_asset_path)
    if material_policy == MaterialPolicy.VERTEX_COLOR_SPLIT:
        return _apply_vertex_color_split_policy(model, bark_material_path, leaves_material_path, normalize_asset_path)
    raise ValueError(f"Unsupported material policy: {material_policy}")


def _apply_legacy_material_policy(
    model: CanonicalTreeModel,
    bark_material_path: str | None,
    leaves_material_path: str | None,
    normalize_asset_path,
) -> CanonicalTreeModel:
    if not bark_material_path and not leaves_material_path:
        return model
    overrides = {
        BASELINE_BARK_MATERIAL_ID: bark_material_path,
        BASELINE_LEAVES_MATERIAL_ID: leaves_material_path,
    }
    materials = tuple(_apply_material_override(material, overrides, normalize_asset_path) for material in model.materials)
    return replace(model, materials=materials)


def _apply_material_override(material: MaterialSpec, overrides: dict[int, str | None], normalize_asset_path) -> MaterialSpec:
    ue_asset_path = overrides.get(material.source_id)
    if not ue_asset_path:
        return material
    return replace(material, ue_asset_path=normalize_asset_path(ue_asset_path))


def _apply_single_material_policy(
    model: CanonicalTreeModel,
    single_material_path: str | None,
    normalize_asset_path,
) -> CanonicalTreeModel:
    source_material_ids = tuple(sorted(set(_source_material_ids(model))))
    single_material = MaterialSpec(
        source_id=BASELINE_BARK_MATERIAL_ID,
        name="SingleMaterial",
        ue_asset_path=normalize_asset_path(single_material_path) if single_material_path else None,
        source_material_ids=source_material_ids,
    )
    base_mesh = _remap_mesh_to_single_material(model.base_mesh, BASELINE_BARK_MATERIAL_ID)
    prototypes = tuple(
        _replace_prototype_materials_to_single_material(prototype, BASELINE_BARK_MATERIAL_ID)
        for prototype in model.prototypes
    )
    return replace(model, materials=(single_material,), base_mesh=base_mesh, prototypes=prototypes)


def _apply_vertex_color_split_policy(
    model: CanonicalTreeModel,
    bark_material_path: str | None,
    leaves_material_path: str | None,
    normalize_asset_path,
) -> CanonicalTreeModel:
    warnings: list[str] = []
    source_material_ids = tuple(sorted(set(_source_material_ids(model))))
    materials = (
        MaterialSpec(
            source_id=BASELINE_BARK_MATERIAL_ID,
            name="PrimaryMaterial",
            ue_asset_path=normalize_asset_path(bark_material_path) if bark_material_path else None,
            source_material_ids=source_material_ids,
        ),
        MaterialSpec(
            source_id=BASELINE_LEAVES_MATERIAL_ID,
            name="SecondaryMaterial",
            ue_asset_path=normalize_asset_path(leaves_material_path) if leaves_material_path else None,
            source_material_ids=source_material_ids,
        ),
    )
    base_mesh = _remap_mesh_by_vertex_color(model.base_mesh, "Base Skeletal Tree", warnings)
    prototypes = tuple(_remap_prototype_by_vertex_color(prototype, warnings) for prototype in model.prototypes)
    metadata = model.metadata
    if warnings:
        metadata = replace(metadata, warnings=metadata.warnings + tuple(warnings))
    return replace(model, materials=materials, base_mesh=base_mesh, prototypes=prototypes, metadata=metadata)


def _source_material_ids(model: CanonicalTreeModel) -> tuple[int, ...]:
    if model.materials:
        return tuple(
            material_id
            for material in model.materials
            for material_id in (material.source_material_ids or (material.source_id,))
        )
    return tuple(
        material_id
        for material_id in (
            [section.material_id for section in model.base_mesh.sections] if model.base_mesh is not None else []
        )
    )


def _remap_mesh_to_single_material(mesh: MeshData | None, material_id: int) -> MeshData | None:
    if mesh is None:
        return None
    return replace(mesh, sections=_single_material_mesh_sections(material_id, len(mesh.face_vertex_counts)))


def _replace_prototype_materials_to_single_material(prototype, material_id: int):
    if prototype.geometry_payload is not None:
        geometry_payload = replace_payload_sections(
            prototype.geometry_payload,
            single_material_sections(material_id, prototype.geometry_payload.face_count),
        )
        return replace(prototype, geometry_payload=geometry_payload)
    if prototype.mesh is not None:
        return replace(prototype, mesh=_remap_mesh_to_single_material(prototype.mesh, material_id))
    return prototype


def _single_material_mesh_sections(material_id: int, face_count: int) -> tuple[MeshSection, ...]:
    if face_count <= 0:
        return ()
    return (MeshSection(material_id=material_id, face_indices=tuple(range(face_count))),)


def _remap_mesh_by_vertex_color(
    mesh: MeshData | None,
    label: str,
    warnings: list[str],
) -> MeshData | None:
    if mesh is None:
        return None
    sections = _vertex_color_split_sections(mesh)
    if sections is None:
        if mesh.face_vertex_counts:
            warnings.append(
                f"material_policy_warning: vertex_color_split fell back to primary material for {label} because usable vertex colors are missing"
            )
        sections = _single_material_mesh_sections(BASELINE_BARK_MATERIAL_ID, len(mesh.face_vertex_counts))
    return replace(mesh, sections=sections)


def _remap_prototype_by_vertex_color(prototype, warnings: list[str]):
    if prototype.geometry_payload is not None:
        if prototype.source_mode == PrototypeSourceMode.FBX_FILE:
            return prototype
        sections = _vertex_color_split_sections_for_payload(prototype.geometry_payload)
        if sections is None:
            warnings.append(
                f"material_policy_warning: vertex_color_split fell back to primary material for Prototype {prototype.identity.prim_name} because usable vertex colors are missing"
            )
            sections = single_material_sections(BASELINE_BARK_MATERIAL_ID, prototype.geometry_payload.face_count)
        return replace(prototype, geometry_payload=replace_payload_sections(prototype.geometry_payload, sections))
    if prototype.mesh is not None:
        return replace(
            prototype,
            mesh=_remap_mesh_by_vertex_color(
                prototype.mesh,
                f"Prototype {prototype.identity.prim_name}",
                warnings,
            ),
        )
    return prototype


def _vertex_color_split_sections(mesh: MeshData) -> tuple[MeshSection, ...] | None:
    if not mesh.vertex_colors or not mesh.face_vertex_counts or not mesh.face_vertex_indices:
        return None

    sections_by_material: dict[int, list[int]] = {
        BASELINE_BARK_MATERIAL_ID: [],
        BASELINE_LEAVES_MATERIAL_ID: [],
    }
    offset = 0
    for face_index, face_count in enumerate(mesh.face_vertex_counts):
        face_indices = mesh.face_vertex_indices[offset:offset + face_count]
        offset += face_count
        if len(face_indices) != face_count:
            return None
        if any(point_index < 0 or point_index >= len(mesh.vertex_colors) for point_index in face_indices):
            return None
        material_id = (
            BASELINE_BARK_MATERIAL_ID
            if all(mesh.vertex_colors[point_index].is_exact_white() for point_index in face_indices)
            else BASELINE_LEAVES_MATERIAL_ID
        )
        sections_by_material[material_id].append(face_index)
    return tuple(
        MeshSection(material_id=material_id, face_indices=tuple(face_indices))
        for material_id, face_indices in sections_by_material.items()
        if face_indices
    )


def _vertex_color_split_sections_for_payload(payload: GeometryBuffer) -> tuple[CompactMeshSection, ...] | None:
    if payload.vertex_color_count == 0 or payload.face_count == 0 or not payload.face_vertex_indices:
        return None
    sections_by_material: dict[int, array] = {
        BASELINE_BARK_MATERIAL_ID: array("i"),
        BASELINE_LEAVES_MATERIAL_ID: array("i"),
    }
    offset = 0
    for face_index, face_count in enumerate(payload.face_vertex_counts):
        face_indices = payload.face_vertex_indices[offset:offset + face_count]
        offset += face_count
        if len(face_indices) != face_count:
            return None
        material_id = BASELINE_BARK_MATERIAL_ID
        for point_index in face_indices:
            color_offset = point_index * 4
            if color_offset + 2 >= len(payload.vertex_color_components):
                return None
            if not (
                payload.vertex_color_components[color_offset] == 1.0
                and payload.vertex_color_components[color_offset + 1] == 1.0
                and payload.vertex_color_components[color_offset + 2] == 1.0
            ):
                material_id = BASELINE_LEAVES_MATERIAL_ID
                break
        sections_by_material[material_id].append(face_index)
    return tuple(
        CompactMeshSection(material_id=material_id, face_indices=face_indices)
        for material_id, face_indices in sections_by_material.items()
        if face_indices
    )


def _fbx_vertex_color_sections(payload: GeometryBuffer) -> tuple[CompactMeshSection, ...] | None:
    if payload.vertex_color_count == 0 or payload.face_count == 0 or not payload.face_vertex_indices:
        return None
    sections_by_material: dict[int, array] = {
        BASELINE_BARK_MATERIAL_ID: array("i"),
        BASELINE_LEAVES_MATERIAL_ID: array("i"),
    }
    offset = 0
    for face_index, face_count in enumerate(payload.face_vertex_counts):
        face_indices = payload.face_vertex_indices[offset:offset + face_count]
        offset += face_count
        if len(face_indices) != face_count:
            return None
        material_id = BASELINE_LEAVES_MATERIAL_ID
        for point_index in face_indices:
            color_offset = point_index * 4
            if color_offset + 2 >= len(payload.vertex_color_components):
                return None
            if not (
                payload.vertex_color_components[color_offset] == 0.0
                and payload.vertex_color_components[color_offset + 1] == 0.0
                and payload.vertex_color_components[color_offset + 2] == 0.0
            ):
                material_id = BASELINE_BARK_MATERIAL_ID
                break
        sections_by_material[material_id].append(face_index)
    return tuple(
        CompactMeshSection(material_id=material_id, face_indices=face_indices)
        for material_id, face_indices in sections_by_material.items()
        if face_indices
    )


def _resolve_fbx_material_sections(
    prototype,
    *,
    cpu_profile: CpuProfile,
    cancel_event,
    warnings: list[str],
) -> tuple[CompactMeshSection, ...]:
    payload = prototype.geometry_payload
    if payload is None:
        return ()
    if prototype.fbx_material_mode == FbxMaterialMode.SINGLE_MATERIAL:
        return single_material_sections(BASELINE_BARK_MATERIAL_ID, payload.face_count)

    sections = partition_fbx_material_faces(
        payload,
        cpu_profile=cpu_profile,
        cancel_event=cancel_event,
    )
    if _has_useful_fbx_material_split(sections):
        return sections or ()

    warning_reason = _describe_fbx_material_fallback_reason(payload, sections)
    if prototype.fbx_material_mode == FbxMaterialMode.VERTEX_COLOR_SPLIT:
        warnings.append(
            "material_policy_warning: "
            f"Prototype {prototype.identity.prim_name} requested FBX vertex_color_split but fell back to primary material because {warning_reason}"
        )
    else:
        warnings.append(
            "material_policy_warning: "
            f"Prototype {prototype.identity.prim_name} uses single material because {warning_reason}"
        )
    return single_material_sections(BASELINE_BARK_MATERIAL_ID, payload.face_count)


def _has_useful_fbx_material_split(sections: tuple[CompactMeshSection, ...] | None) -> bool:
    return sections is not None and len(sections) > 1


def _describe_fbx_material_fallback_reason(
    payload: GeometryBuffer,
    sections: tuple[CompactMeshSection, ...] | None,
) -> str:
    if payload.vertex_color_count == 0:
        return "vertex colors are missing"
    if sections is None:
        return "vertex colors are incomplete or unusable"
    return "vertex colors do not create more than one material bucket"
