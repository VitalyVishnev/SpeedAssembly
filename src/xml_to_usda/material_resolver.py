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
    if material_policy == MaterialPolicy.SOURCE_MATERIAL_ROLES:
        return _apply_source_role_material_policy(model, bark_material_path, leaves_material_path, normalize_asset_path)
    if material_policy == MaterialPolicy.SINGLE_MATERIAL:
        return _apply_single_material_policy(model, single_material_path, normalize_asset_path)
    if material_policy == MaterialPolicy.VERTEX_COLOR_SPLIT:
        return _apply_vertex_color_split_policy(model, bark_material_path, leaves_material_path, normalize_asset_path)
    raise ValueError(f"Unsupported material policy: {material_policy}")


def _apply_source_role_material_policy(
    model: CanonicalTreeModel,
    bark_material_path: str | None,
    leaves_material_path: str | None,
    normalize_asset_path,
) -> CanonicalTreeModel:
    role_map = _source_role_material_id_map(model)
    base_mesh = _remap_mesh_material_ids(model.base_mesh, role_map)
    prototypes = tuple(_remap_prototype_material_ids(prototype, role_map) for prototype in model.prototypes)
    materials = _build_source_role_materials(
        model,
        role_map,
        bark_material_path,
        leaves_material_path,
        normalize_asset_path,
        base_mesh=base_mesh,
        prototypes=prototypes,
    )
    return replace(model, materials=materials, base_mesh=base_mesh, prototypes=prototypes)


def _source_role_material_id_map(model: CanonicalTreeModel) -> dict[int, int]:
    source_material_ids = list(dict.fromkeys(_source_material_ids(model)))
    if not source_material_ids:
        return {}

    role_map: dict[int, int] = {}
    for material_id in source_material_ids:
        if material_id in {BASELINE_BARK_MATERIAL_ID, BASELINE_LEAVES_MATERIAL_ID}:
            role_map[material_id] = material_id

    leaf_reference_material_ids = {
        part.source_material_id
        for part in model.assembly_parts
        if part.source_material_id is not None
    }
    unresolved_ids = [material_id for material_id in source_material_ids if material_id not in role_map]

    if len(leaf_reference_material_ids) == 1:
        leaf_material_id = next(iter(leaf_reference_material_ids))
        if leaf_material_id in source_material_ids:
            role_map[leaf_material_id] = BASELINE_LEAVES_MATERIAL_ID

    for material_id in unresolved_ids:
        role_map.setdefault(material_id, BASELINE_BARK_MATERIAL_ID)
    return role_map


def _build_source_role_materials(
    model: CanonicalTreeModel,
    role_map: dict[int, int],
    bark_material_path: str | None,
    leaves_material_path: str | None,
    normalize_asset_path,
    *,
    base_mesh: MeshData | None,
    prototypes,
) -> tuple[MaterialSpec, ...]:
    original_material_by_id = {material.source_id: material for material in model.materials}
    source_ids_by_role: dict[int, set[int]] = {}
    for source_material_id in _source_material_ids(model):
        role_id = role_map.get(source_material_id, source_material_id)
        source_ids_by_role.setdefault(role_id, set()).add(source_material_id)
    used_role_ids = _used_material_ids(base_mesh, prototypes)

    materials: list[MaterialSpec] = []
    for role_id in sorted(set(source_ids_by_role) | used_role_ids):
        source_material_ids = tuple(sorted(source_ids_by_role.get(role_id, {role_id})))
        representative = next(
            (original_material_by_id[source_id] for source_id in source_material_ids if source_id in original_material_by_id),
            None,
        )
        name = "PrimaryMaterial" if role_id == BASELINE_BARK_MATERIAL_ID else "SecondaryMaterial"
        two_sided = representative.two_sided if representative is not None else False
        maps = representative.maps if representative is not None else ()
        ue_asset_path = None
        if role_id == BASELINE_BARK_MATERIAL_ID and bark_material_path:
            ue_asset_path = normalize_asset_path(bark_material_path)
        elif role_id == BASELINE_LEAVES_MATERIAL_ID and leaves_material_path:
            ue_asset_path = normalize_asset_path(leaves_material_path)
        materials.append(
            MaterialSpec(
                source_id=role_id,
                name=name,
                two_sided=two_sided,
                maps=maps,
                ue_asset_path=ue_asset_path,
                source_material_ids=source_material_ids,
            )
        )
    return tuple(materials)


def _apply_source_role_override(
    material: MaterialSpec,
    role_map: dict[int, int],
    bark_material_path: str | None,
    leaves_material_path: str | None,
    normalize_asset_path,
) -> MaterialSpec:
    role_id = role_map.get(material.source_id)
    if role_id == BASELINE_BARK_MATERIAL_ID and bark_material_path:
        return replace(material, ue_asset_path=normalize_asset_path(bark_material_path))
    if role_id == BASELINE_LEAVES_MATERIAL_ID and leaves_material_path:
        return replace(material, ue_asset_path=normalize_asset_path(leaves_material_path))
    return material


def _apply_material_override(material: MaterialSpec, overrides: dict[int, str | None], normalize_asset_path) -> MaterialSpec:
    ue_asset_path = overrides.get(material.source_id)
    if not ue_asset_path:
        return material
    return replace(material, ue_asset_path=normalize_asset_path(ue_asset_path))


def _remap_mesh_material_ids(mesh: MeshData | None, role_map: dict[int, int]) -> MeshData | None:
    if mesh is None or not mesh.sections:
        return mesh
    return replace(
        mesh,
        sections=tuple(
            MeshSection(
                material_id=role_map.get(section.material_id, section.material_id),
                face_indices=section.face_indices,
            )
            for section in mesh.sections
        ),
    )


def _remap_payload_material_ids(geometry_payload: GeometryBuffer | None, role_map: dict[int, int]) -> GeometryBuffer | None:
    if geometry_payload is None or not geometry_payload.sections:
        return geometry_payload
    return replace_payload_sections(
        geometry_payload,
        tuple(
            CompactMeshSection(
                material_id=role_map.get(section.material_id, section.material_id),
                face_indices=section.face_indices,
            )
            for section in geometry_payload.sections
        ),
    )


def _remap_prototype_material_ids(prototype, role_map: dict[int, int]):
    geometry_payload = _remap_payload_material_ids(prototype.geometry_payload, role_map)
    mesh = _remap_mesh_material_ids(prototype.mesh, role_map)
    if geometry_payload is prototype.geometry_payload and mesh is prototype.mesh:
        return prototype
    return replace(prototype, geometry_payload=geometry_payload, mesh=mesh)


def _used_material_ids(base_mesh: MeshData | None, prototypes) -> set[int]:
    material_ids: set[int] = set()
    if base_mesh is not None:
        material_ids.update(section.material_id for section in base_mesh.sections)
    for prototype in prototypes:
        section_source = prototype.geometry_payload.sections if prototype.geometry_payload is not None else (
            prototype.mesh.sections if prototype.mesh is not None else ()
        )
        material_ids.update(section.material_id for section in section_source)
    return material_ids


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
