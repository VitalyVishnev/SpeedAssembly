from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import replace

from .dynamic_wind import build_dynamic_wind_data
from .naming import build_prototype_identities
from .models import (
    AssemblyPartInstance,
    BaseTreePart,
    Bounds,
    BranchSegment,
    CanonicalTreeModel,
    Color4,
    ExportMetadata,
    InstanceBinding,
    Joint,
    MaterialSpec,
    Matrix4d,
    MeshData,
    MeshLibraryEntry,
    MeshSection,
    ObservedXmlSchemaReport,
    Prototype,
    PrototypeStrategy,
    Quaternion,
    SkeletalSupportPrimvars,
    SourceObject,
    SpineCurve,
    Vector2,
    Vector3,
)
from .source_transform import SourceTransform, build_source_transform


PRIMARY_MATERIAL_ID = 1
LEAVES_MATERIAL_ID = 2


def normalize_to_canonical(document, report: ObservedXmlSchemaReport) -> CanonicalTreeModel:
    root = document.tree.getroot()
    data_messages: list[str] = []
    # Stage metadata alone is not enough. Every spatial payload must be remapped into stage space here.
    source_transform = build_source_transform(root, report.units_hint, report.up_axis_hint)
    materials = tuple(_extract_materials(root))
    material_ids = {material.source_id for material in materials}

    skeleton = tuple(_extract_skeleton(root, data_messages, source_transform))
    joint_index_by_source_id = {
        joint.source_id: index for index, joint in enumerate(skeleton) if joint.source_id is not None
    }
    source_objects = tuple(
        _extract_source_objects(root, data_messages, joint_index_by_source_id, source_transform, material_ids)
    )
    mesh_library = tuple(_extract_mesh_library(root, data_messages, source_transform, material_ids))
    base_mesh, base_tree_parts = _build_base_mesh(source_objects)
    # The project contract treats LeafReferences as the source of repeated Assembly Parts.
    assembly_parts = tuple(
        _extract_assembly_parts_from_leaf_references(root, data_messages, source_transform, material_ids)
    )
    assembly_parts, mesh_library = _rebalance_assembly_part_prototype_scales(assembly_parts, mesh_library)
    branch_segments = tuple(_extract_branch_segments(source_objects, skeleton))
    prototypes = tuple(_build_prototypes(assembly_parts, mesh_library, data_messages))
    skeletal_support_primvars = _build_skeletal_support_primvars(skeleton)
    spines = tuple(source_object.spine for source_object in source_objects if source_object.spine is not None)
    dynamic_wind = build_dynamic_wind_data(skeleton, source_objects=source_objects)

    metadata = ExportMetadata(
        source_path=document.source_path,
        source_version=report.version,
        meters_per_unit=source_transform.target_meters_per_unit,
        up_axis=source_transform.target_up_axis,
        warnings=tuple(_metadata_warnings(report) + data_messages),
        unknown_sections=report.unknown_sections,
    )

    return CanonicalTreeModel(
        metadata=metadata,
        materials=materials,
        source_objects=source_objects,
        base_mesh=base_mesh,
        skeleton=skeleton,
        assembly_parts=assembly_parts,
        base_tree_parts=base_tree_parts,
        branch_segments=branch_segments,
        mesh_library=mesh_library,
        prototypes=prototypes,
        prototype_strategy=PrototypeStrategy.INLINE_SKELETAL_PART,
        skeletal_support_primvars=skeletal_support_primvars,
        spines=spines,
        dynamic_wind=dynamic_wind,
    )


def _metadata_warnings(report: ObservedXmlSchemaReport) -> list[str]:
    warnings: list[str] = []
    if report.units_hint and report.units_hint.lower() not in {"cm", "centimeter", "centimeters", "m", "meter", "meters"}:
        warnings.append(f"Unsupported units hint detected: {report.units_hint}")
    if report.up_axis_hint and report.up_axis_hint.upper() not in {"Y", "Z"}:
        warnings.append(f"Unsupported up-axis hint detected: {report.up_axis_hint}")
    if report.unknown_sections:
        warnings.append(f"Unknown XML sections detected: {', '.join(report.unknown_sections)}")
    if report.object_class_counts.get("total", 0) == 0:
        warnings.append("missing_object_hierarchy: XML does not contain any Object nodes")
    if report.leaf_binding_distribution and not report.leaf_mesh_distribution:
        warnings.append("missing_leaf_binding: Leaf references are present without mesh ids")
    return warnings


def _extract_materials(root: ET.Element) -> list[MaterialSpec]:
    materials: list[MaterialSpec] = []
    for material_node in root.findall(".//Materials/Material"):
        source_id = material_node.attrib.get("ID")
        if source_id is None or not source_id.lstrip("-").isdigit():
            continue
        maps: list[tuple[str, tuple[tuple[str, str], ...]]] = []
        for map_node in material_node.findall("Map"):
            map_name = map_node.attrib.get("Name", "Map")
            payload = tuple(sorted((key, value) for key, value in map_node.attrib.items() if key != "Name"))
            maps.append((map_name, payload))
        materials.append(
            MaterialSpec(
                source_id=int(source_id),
                name=material_node.attrib.get("Name", f"Material_{source_id}"),
                two_sided=material_node.attrib.get("TwoSided") == "1",
                maps=tuple(maps),
            )
        )
    return materials


def _build_base_mesh(source_objects: tuple[SourceObject, ...]) -> tuple[MeshData | None, tuple[BaseTreePart, ...]]:
    # Base Skeletal Tree coverage is driven by mesh-bearing objects in the regular hierarchy.
    # The source naming varies across SpeedTree exports, so we do not gate this on a narrow prefix list.
    candidates = [source_object for source_object in source_objects if source_object.mesh is not None]
    if not candidates:
        return None, ()

    merged_points: list[Vector3] = []
    merged_face_counts: list[int] = []
    merged_face_indices: list[int] = []
    merged_uv_coords: list[Vector2] = []
    merged_joint_indices: list[int] = []
    merged_joint_weights: list[float] = []
    merged_sections: dict[int, list[int]] = defaultdict(list)
    merged_parts: list[BaseTreePart] = []

    for source_object in candidates:
        mesh = source_object.mesh
        if mesh is None:
            continue
        point_offset = len(merged_points)
        face_offset = len(merged_face_counts)
        translated_points = tuple(_translate_point(point, source_object.abs_translate) for point in mesh.points)
        merged_points.extend(translated_points)
        merged_face_counts.extend(mesh.face_vertex_counts)
        merged_face_indices.extend(index + point_offset for index in mesh.face_vertex_indices)
        merged_uv_coords.extend(mesh.uv_coords)
        merged_joint_indices.extend(mesh.skel_joint_indices)
        merged_joint_weights.extend(mesh.skel_joint_weights)
        for section in mesh.sections:
            merged_sections[section.material_id].extend(face_offset + face_index for face_index in section.face_indices)
        merged_parts.append(
            BaseTreePart(
                object_id=source_object.object_id,
                parent_id=source_object.parent_id,
                name=source_object.name,
                translate=source_object.abs_translate,
                point_offset=point_offset,
                point_count=len(mesh.points),
                face_offset=face_offset,
                face_count=len(mesh.face_vertex_counts),
            )
        )

    return (
        MeshData(
            name="TreeBaseMesh",
            points=tuple(merged_points),
            face_vertex_counts=tuple(merged_face_counts),
            face_vertex_indices=tuple(merged_face_indices),
            uv_coords=tuple(merged_uv_coords),
            sections=_ordered_sections(merged_sections),
            skel_joint_indices=tuple(merged_joint_indices),
            skel_joint_weights=tuple(merged_joint_weights),
            skel_element_size=1 if merged_joint_indices else 0,
        ),
        tuple(merged_parts),
    )


def _extract_source_objects(
    root: ET.Element,
    messages: list[str],
    joint_index_by_source_id: dict[int, int],
    source_transform: SourceTransform,
    material_ids: set[int],
) -> list[SourceObject]:
    source_objects: list[SourceObject] = []
    for obj in root.findall(".//Object"):
        object_id = obj.attrib.get("ID")
        if object_id is None:
            continue
        mesh = _extract_object_mesh(obj, messages, joint_index_by_source_id, source_transform, material_ids)
        leaf_count = _count_packed_values(obj.find("LeafReferences"), "X")
        spine = _extract_spine(obj, object_id, messages, source_transform)
        source_objects.append(
            SourceObject(
                object_id=object_id,
                parent_id=obj.attrib.get("ParentID"),
                name=obj.attrib.get("Name", f"Object_{object_id}"),
                abs_translate=_vector_from_named_attributes(obj, ("AbsX", "AbsY", "AbsZ"), source_transform),
                rel_translate=_vector_from_named_attributes(obj, ("RelX", "RelY", "RelZ"), source_transform),
                bounds=_extract_bounds(obj, source_transform),
                mesh=mesh,
                assembly_part_reference_count=leaf_count,
                spine=spine,
            )
        )
    return source_objects


def _extract_mesh_library(
    root: ET.Element,
    messages: list[str],
    source_transform: SourceTransform,
    material_ids: set[int],
) -> list[MeshLibraryEntry]:
    entries: list[MeshLibraryEntry] = []
    for mesh in root.findall(".//Meshes/Mesh"):
        mesh_id = mesh.attrib.get("ID")
        if mesh_id is None or not mesh_id.isdigit():
            continue
        lod = _select_primary_lod(mesh)
        if lod is None:
            messages.append(f"packed_array_error: mesh {mesh.attrib.get('Name', mesh.tag)} missing LOD payload")
            continue
        vertices = lod.find("Vertices")
        if vertices is None:
            messages.append(f"packed_array_error: mesh {mesh.attrib.get('Name', mesh.tag)} missing vertices payload")
            continue
        mesh_data = _build_library_mesh_data(
            mesh.attrib.get("Name", f"Mesh_{mesh_id}"),
            vertices,
            lod,
            messages,
            source_transform,
            material_ids,
        )
        if mesh_data is not None:
            entries.append(
                MeshLibraryEntry(
                    mesh_id=int(mesh_id),
                    name=mesh_data.name,
                    mesh=mesh_data,
                    original_scale=_read_positive_float(lod.attrib.get("OriginalScale")),
                )
            )
    return entries


def _extract_object_mesh(
    obj: ET.Element,
    messages: list[str],
    joint_index_by_source_id: dict[int, int],
    source_transform: SourceTransform,
    material_ids: set[int],
) -> MeshData | None:
    points_node = obj.find("Points")
    triangles_node = obj.find("Triangles")
    if points_node is None or triangles_node is None:
        return None
    vertices_node = obj.find("Vertices")
    return _build_mesh_data(
        obj.attrib.get("Name", obj.tag),
        points_node,
        triangles_node,
        vertices_node,
        joint_index_by_source_id,
        messages,
        source_transform,
        material_ids,
    )


def _build_mesh_data(
    name: str,
    points_node: ET.Element,
    triangles_node: ET.Element,
    vertices_node: ET.Element | None,
    joint_index_by_source_id: dict[int, int],
    messages: list[str],
    source_transform: SourceTransform,
    material_ids: set[int],
) -> MeshData | None:
    points = _extract_packed_points(points_node, f"{name}.points", messages, source_transform)
    face_counts, face_indices, vertex_indices, sections = _extract_packed_triangles(
        triangles_node,
        f"{name}.triangles",
        messages,
        material_ids,
    )
    if not points or not face_counts or not face_indices:
        return None
    joint_indices, joint_weights = _extract_vertex_skinning(
        vertices_node,
        face_indices,
        vertex_indices,
        len(points),
        joint_index_by_source_id,
        f"{name}.vertices",
        messages,
    )
    uv_coords = _extract_face_varying_uvs(
        vertices_node,
        vertex_indices,
        face_indices,
        f"{name}.vertices",
        messages,
        allow_point_index_fallback=False,
    )
    return _build_mesh_from_faces(
        name,
        points,
        face_counts,
        face_indices,
        sections,
        uv_coords,
        joint_indices=joint_indices,
        joint_weights=joint_weights,
    )


def _build_library_mesh_data(
    name: str,
    points_node: ET.Element,
    lod_node: ET.Element,
    messages: list[str],
    source_transform: SourceTransform,
    material_ids: set[int],
) -> MeshData | None:
    points = _extract_packed_points(points_node, f"{name}.points", messages, source_transform)
    face_counts, face_indices, sections = _extract_lod_faces(lod_node, name, messages, material_ids)
    if not points or not face_counts or not face_indices:
        return None
    vertex_indices = _extract_lod_vertex_indices(lod_node, face_indices, name, messages)
    uv_coords = _extract_face_varying_uvs(
        points_node,
        vertex_indices,
        face_indices,
        f"{name}.vertices",
        messages,
        allow_point_index_fallback=True,
    )
    vertex_colors = _extract_vertex_colors(
        points_node,
        f"{name}.vertices",
        messages,
    )
    return _build_mesh_from_faces(name, points, face_counts, face_indices, sections, uv_coords, vertex_colors=vertex_colors)


def _build_mesh_from_faces(
    name: str,
    points: list[Vector3],
    face_counts: list[int],
    face_indices: list[int],
    sections: tuple[MeshSection, ...],
    uv_coords: list[Vector2] | None = None,
    vertex_colors: list[Color4] | None = None,
    joint_indices: list[int] | None = None,
    joint_weights: list[float] | None = None,
) -> MeshData:
    return MeshData(
        name=name,
        points=tuple(points),
        face_vertex_counts=tuple(face_counts),
        face_vertex_indices=tuple(face_indices),
        uv_coords=tuple(uv_coords or ()),
        vertex_colors=tuple(vertex_colors or ()),
        sections=sections,
        skel_joint_indices=tuple(joint_indices or ()),
        skel_joint_weights=tuple(joint_weights or ()),
        skel_element_size=1 if joint_indices else 0,
    )


def _translate_point(point: Vector3, translate: Vector3) -> Vector3:
    return Vector3(point.x + translate.x, point.y + translate.y, point.z + translate.z)


def _select_primary_lod(mesh: ET.Element) -> ET.Element | None:
    lods = mesh.findall("LOD")
    if not lods:
        return None
    for lod in lods:
        if lod.attrib.get("Level") == "0" and lod.find("Vertices") is not None:
            return lod
    for lod in lods:
        if lod.find("Vertices") is not None:
            return lod
    return lods[0]


def _extract_skeleton(root: ET.Element, messages: list[str], source_transform: SourceTransform) -> list[Joint]:
    bones = root.findall(".//Bones/Bone")
    if not bones:
        return []

    raw_bones: list[tuple[int, int | None, Vector3]] = []
    for bone in bones:
        bone_id = bone.attrib.get("ID")
        if bone_id is None or not bone_id.lstrip("-").isdigit():
            continue
        parent_id = bone.attrib.get("ParentID")
        start_x = _find_float(bone, ("StartX",), default=None)
        start_y = _find_float(bone, ("StartY",), default=None)
        start_z = _find_float(bone, ("StartZ",), default=None)
        if start_x is None or start_y is None or start_z is None:
            messages.append(
                f"missing_skeleton_transform: bone {bone_id} is missing StartX/StartY/StartZ required for rest pose authoring"
            )
            continue
        parsed_parent_id = None
        if parent_id not in {None, "", "-1"} and parent_id.lstrip("-").isdigit():
            parsed_parent_id = int(parent_id)
        raw_bones.append(
            (
                int(bone_id),
                parsed_parent_id,
                source_transform.point_to_stage(Vector3(start_x, start_y, start_z)),
            )
        )

    start_by_id = {bone_id: start for bone_id, _, start in raw_bones}
    joints: list[Joint] = []
    for bone_id, parsed_parent_id, start in raw_bones:
        parent = _joint_name_from_bone_id(parsed_parent_id) if parsed_parent_id is not None else None
        if parsed_parent_id is None or parsed_parent_id not in start_by_id:
            rest_translate = start
        else:
            parent_start = start_by_id[parsed_parent_id]
            rest_translate = Vector3(
                start.x - parent_start.x,
                start.y - parent_start.y,
                start.z - parent_start.z,
            )
        joints.append(
            Joint(
                name=_joint_name_from_bone_id(bone_id),
                source_id=bone_id,
                parent=parent,
                bind_transform=Matrix4d.from_translation(start),
                rest_transform=Matrix4d.from_translation(rest_translate),
            )
        )
    return joints


def _extract_assembly_parts_from_leaf_references(
    root: ET.Element,
    messages: list[str],
    source_transform: SourceTransform,
    material_ids: set[int],
) -> list[AssemblyPartInstance]:
    assembly_parts: list[AssemblyPartInstance] = []
    for obj in root.findall(".//Object"):
        leaf_ref_node = obj.find("LeafReferences")
        if leaf_ref_node is None:
            continue

        xs = _read_float_list(leaf_ref_node.findtext("X"))
        ys = _read_float_list(leaf_ref_node.findtext("Y"))
        zs = _read_float_list(leaf_ref_node.findtext("Z"))
        scales = _read_float_list(leaf_ref_node.findtext("Scale"))
        axis_x = _read_float_list(leaf_ref_node.findtext("RotAxisX"))
        axis_y = _read_float_list(leaf_ref_node.findtext("RotAxisY"))
        axis_z = _read_float_list(leaf_ref_node.findtext("RotAxisZ"))
        angles = _read_float_list(leaf_ref_node.findtext("RotAngle"))
        mesh_ids = _read_int_list(leaf_ref_node.findtext("MeshID"))
        mesh_lods = _read_int_list(leaf_ref_node.findtext("MeshLOD"))
        bone_ids = _read_int_list(leaf_ref_node.findtext("BoneID"))
        source_material_id = _read_material_id(leaf_ref_node, f"LeafReferences[{obj.attrib.get('Name', obj.attrib.get('ID', '?'))}]", messages, material_ids)

        count = _consistent_count(
            f"LeafReferences[{obj.attrib.get('Name', obj.attrib.get('ID', '?'))}]",
            messages,
            required=[("X", xs), ("Y", ys), ("Z", zs)],
            optional=[
                ("Scale", scales),
                ("RotAxisX", axis_x),
                ("RotAxisY", axis_y),
                ("RotAxisZ", axis_z),
                ("RotAngle", angles),
                ("MeshID", mesh_ids),
                ("MeshLOD", mesh_lods),
                ("BoneID", bone_ids),
            ],
        )
        if count == 0:
            continue

        for index in range(count):
            source_bone_id = bone_ids[index] if index < len(bone_ids) else None
            source_mesh_id = mesh_ids[index] if index < len(mesh_ids) else None
            prototype_key = f"Mesh_{source_mesh_id}" if source_mesh_id is not None else "LeafPrototype"
            uniform_scale = scales[index] if index < len(scales) else 1.0
            binding = _binding_from_bone_id(source_bone_id)
            assembly_parts.append(
                AssemblyPartInstance(
                    name=f"AssemblyPart_{len(assembly_parts):04d}",
                    prototype_key=prototype_key,
                    position=source_transform.point_to_stage(Vector3(xs[index], ys[index], zs[index])),
                    orientation=_leaf_reference_orientation_to_stage(
                        source_transform,
                        Vector3(
                            axis_x[index] if index < len(axis_x) else 0.0,
                            axis_y[index] if index < len(axis_y) else 0.0,
                            axis_z[index] if index < len(axis_z) else 1.0,
                        ),
                        angles[index] if index < len(angles) else 0.0,
                    ),
                    scale=Vector3(uniform_scale, uniform_scale, uniform_scale),
                    binding=binding,
                    source_object_id=obj.attrib.get("ID"),
                    source_mesh_id=source_mesh_id,
                    source_material_id=source_material_id,
                    source_bone_ids=(source_bone_id,) if source_bone_id is not None else (),
                    mesh_lod=mesh_lods[index] if index < len(mesh_lods) else None,
                )
            )
    return assembly_parts


def _extract_branch_segments(source_objects: tuple[SourceObject, ...], skeleton: tuple[Joint, ...]) -> list[BranchSegment]:
    segments: list[BranchSegment] = []
    for source_object in source_objects:
        if source_object.mesh is None:
            continue
        candidate_joint = _resolve_source_object_joint_name(source_object, skeleton)
        segments.append(
            BranchSegment(
                object_id=source_object.object_id,
                parent_id=source_object.parent_id,
                name=source_object.name,
                mesh=source_object.mesh,
                spine=source_object.spine,
                source_joint=candidate_joint,
            )
    )
    return segments


def _resolve_source_object_joint_name(source_object: SourceObject, skeleton: tuple[Joint, ...]) -> str | None:
    joint_names = {joint.name for joint in skeleton}
    if source_object.object_id.isdigit():
        numeric_id = int(source_object.object_id)
        candidate_joint = _joint_name_from_bone_id(numeric_id)
        if candidate_joint in joint_names:
            return candidate_joint
    return None


def _rebalance_assembly_part_prototype_scales(
    assembly_parts: tuple[AssemblyPartInstance, ...],
    mesh_library: tuple[MeshLibraryEntry, ...],
) -> tuple[tuple[AssemblyPartInstance, ...], tuple[MeshLibraryEntry, ...]]:
    # Preserve prototype geometry as authored, but fold mesh-library OriginalScale into the instance scale.
    # This keeps the instance contract explicit while still honoring the source part size reported by SpeedTree.
    original_scale_by_mesh_id = {
        entry.mesh_id: entry.original_scale
        for entry in mesh_library
        if entry.original_scale is not None and entry.original_scale > 0.0
    }
    if not original_scale_by_mesh_id:
        return assembly_parts, mesh_library

    rebased_parts: list[AssemblyPartInstance] = []
    for part in assembly_parts:
        scale_factor = original_scale_by_mesh_id.get(part.source_mesh_id)
        if scale_factor is None:
            rebased_parts.append(part)
            continue
        rebased_parts.append(
            replace(
                part,
                scale=Vector3(
                    part.scale.x * scale_factor,
                    part.scale.y * scale_factor,
                    part.scale.z * scale_factor,
                ),
            )
        )
    return tuple(rebased_parts), mesh_library


def _leaf_reference_orientation_to_stage(
    source_transform: SourceTransform,
    axis: Vector3,
    angle_degrees: float,
) -> Quaternion:
    # Axis remaps into stage space, but the authored rotation sense stays the same.
    stage_axis = source_transform.axis_to_stage(axis)
    return _quaternion_from_axis_angle(stage_axis, angle_degrees)


def _build_prototypes(
    assembly_parts: tuple[AssemblyPartInstance, ...],
    mesh_library: tuple[MeshLibraryEntry, ...],
    messages: list[str],
) -> list[Prototype]:
    if not assembly_parts:
        return []
    source_keys = tuple(dict.fromkeys(part.prototype_key for part in assembly_parts))
    identities = build_prototype_identities(list(source_keys))
    meshes_by_key = {f"Mesh_{entry.mesh_id}": entry for entry in mesh_library}
    fallback_materials: dict[str, set[int]] = defaultdict(set)
    for part in assembly_parts:
        if part.source_material_id is not None:
            fallback_materials[part.prototype_key].add(part.source_material_id)
    prototypes: list[Prototype] = []
    for identity in identities:
        entry = meshes_by_key.get(identity.source_key)
        mesh = entry.mesh if entry is not None else None
        if mesh is not None:
            mesh = _resolve_prototype_material_sections(
                mesh,
                identity.source_key,
                fallback_materials.get(identity.source_key, set()),
                messages,
            )
        prototypes.append(
            Prototype(
                identity=identity,
                mesh=mesh,
                source_key=identity.source_key,
                source_mesh_id=entry.mesh_id if entry is not None else None,
                source_name=entry.name if entry is not None else identity.source_key,
                prototype_type=identity.prototype_type,
            )
        )
    return prototypes


def _resolve_prototype_material_sections(
    mesh: MeshData,
    prototype_key: str,
    fallback_material_ids: set[int],
    messages: list[str],
) -> MeshData:
    vertex_color_sections = _vertex_color_material_sections(mesh)
    if vertex_color_sections is not None:
        authored_material_ids = {section.material_id for section in mesh.sections}
        resolved_material_ids = {section.material_id for section in vertex_color_sections}
        if authored_material_ids and authored_material_ids != resolved_material_ids:
            messages.append(
                f"material_conflict: prototype {prototype_key} uses vertex-color-derived material ids "
                f"{sorted(resolved_material_ids)} over mesh-authored material ids {sorted(authored_material_ids)}"
            )
        return replace(mesh, sections=vertex_color_sections)

    return _apply_fallback_material_sections(mesh, prototype_key, fallback_material_ids, messages)


def _build_skeletal_support_primvars(skeleton: tuple[Joint, ...]) -> SkeletalSupportPrimvars | None:
    if not skeleton:
        return None
    depth_by_name = _joint_hierarchy_depths(skeleton)
    capture_paths = tuple(_capture_token_from_joint(joint, fallback_index=index) for index, joint in enumerate(skeleton))
    hierarchical_depths = tuple(depth_by_name[joint.name] for joint in skeleton)
    return SkeletalSupportPrimvars(
        capture_paths=capture_paths,
        ue_joint_names=capture_paths,
        hierarchical_depths=hierarchical_depths,
        logical_depths=hierarchical_depths,
    )


def _extract_spine(
    obj: ET.Element,
    object_id: str,
    messages: list[str],
    source_transform: SourceTransform,
) -> SpineCurve | None:
    spine_node = obj.find("Spine")
    if spine_node is None:
        return None
    xs = _read_float_list(spine_node.findtext("X"))
    ys = _read_float_list(spine_node.findtext("Y"))
    zs = _read_float_list(spine_node.findtext("Z"))
    radii = _read_float_list(spine_node.findtext("Radius"))
    count = _consistent_count(
        f"Spine[{obj.attrib.get('Name', object_id)}]",
        messages,
        required=[("X", xs), ("Y", ys), ("Z", zs)],
        optional=[("Radius", radii)],
    )
    if count == 0:
        return None
    points = tuple(
        source_transform.point_to_stage(Vector3(xs[index], ys[index], zs[index]))
        for index in range(count)
    )
    usable_radii = tuple(radii[:count]) if radii else ()
    return SpineCurve(source_object_id=object_id, points=points, radii=usable_radii)


def _extract_bounds(obj: ET.Element, source_transform: SourceTransform) -> Bounds | None:
    min_components = (obj.attrib.get("BoundsMinX"), obj.attrib.get("BoundsMinY"), obj.attrib.get("BoundsMinZ"))
    max_components = (obj.attrib.get("BoundsMaxX"), obj.attrib.get("BoundsMaxY"), obj.attrib.get("BoundsMaxZ"))
    if any(component is None for component in min_components + max_components):
        return None
    return source_transform.bounds_to_stage(Bounds(
        minimum=Vector3(float(min_components[0]), float(min_components[1]), float(min_components[2])),
        maximum=Vector3(float(max_components[0]), float(max_components[1]), float(max_components[2])),
    ))


def _vector_from_named_attributes(
    elem: ET.Element,
    names: tuple[str, str, str],
    source_transform: SourceTransform,
) -> Vector3:
    return source_transform.point_to_stage(Vector3(
        _find_float(elem, (names[0],), default=0.0) or 0.0,
        _find_float(elem, (names[1],), default=0.0) or 0.0,
        _find_float(elem, (names[2],), default=0.0) or 0.0,
    ))


def _joint_name_from_bone_id(bone_id: int | None) -> str:
    if bone_id is None:
        return "root"
    return "root" if bone_id == 0 else f"bone_{bone_id:03d}"


def _capture_token_from_bone_id(bone_id: int | None) -> str:
    return f"Tree_point_{bone_id or 0}"


def _capture_token_from_joint(joint: Joint, fallback_index: int) -> str:
    return _capture_token_from_bone_id(joint.source_id if joint.source_id is not None else fallback_index)


def _binding_from_bone_id(source_bone_id: int | None) -> InstanceBinding:
    if source_bone_id is None:
        return InstanceBinding(joint_tokens=(), weights=())
    token = _joint_name_from_bone_id(source_bone_id)
    return InstanceBinding(joint_tokens=(token,), weights=(1.0,))


def _joint_hierarchy_depths(skeleton: tuple[Joint, ...]) -> dict[str, int]:
    joints_by_name = {joint.name: joint for joint in skeleton}
    depths: dict[str, int] = {}

    def resolve(name: str) -> int:
        if name in depths:
            return depths[name]
        joint = joints_by_name[name]
        if joint.parent is None or joint.parent not in joints_by_name:
            depths[name] = 0
        else:
            depths[name] = resolve(joint.parent) + 1
        return depths[name]

    for joint in skeleton:
        resolve(joint.name)
    return depths


def _find_float(elem: ET.Element, names: tuple[str, ...], default: float | None = None) -> float | None:
    for name in names:
        if name in elem.attrib:
            try:
                return float(elem.attrib[name])
            except ValueError:
                return default
    return default


def _extract_packed_points(
    node: ET.Element,
    context: str,
    messages: list[str],
    source_transform: SourceTransform,
) -> list[Vector3]:
    xs = _read_float_list(node.findtext("X"))
    ys = _read_float_list(node.findtext("Y"))
    zs = _read_float_list(node.findtext("Z"))
    count = _consistent_count(context, messages, required=[("X", xs), ("Y", ys), ("Z", zs)])
    return [source_transform.point_to_stage(Vector3(xs[index], ys[index], zs[index])) for index in range(count)]


def _extract_packed_triangles(
    node: ET.Element,
    context: str,
    messages: list[str],
    material_ids: set[int],
) -> tuple[list[int], list[int], list[int], tuple[MeshSection, ...]]:
    point_indices = _read_int_list(node.findtext("PointIndices") or node.findtext("TriangleIndices"))
    vertex_indices = _read_int_list(node.findtext("VertexIndices"))
    indices = point_indices or vertex_indices
    if not indices:
        messages.append(f"packed_array_error: {context} does not contain triangle indices")
        return [], [], [], ()
    if len(indices) % 3 != 0:
        messages.append(f"packed_array_error: {context} index count {len(indices)} is not divisible by 3")
        indices = indices[: len(indices) - (len(indices) % 3)]
    if vertex_indices:
        if len(vertex_indices) % 3 != 0:
            messages.append(f"packed_array_error: {context} vertex index count {len(vertex_indices)} is not divisible by 3")
            vertex_indices = vertex_indices[: len(vertex_indices) - (len(vertex_indices) % 3)]
        if len(vertex_indices) != len(indices):
            messages.append(
                f"packed_array_error: {context} point index count {len(indices)} does not match vertex index count {len(vertex_indices)}"
            )
            limit = min(len(indices), len(vertex_indices))
            indices = indices[:limit]
            vertex_indices = vertex_indices[:limit]
    counts = [3] * (len(indices) // 3)
    material_id = _read_material_id(node, context, messages, material_ids)
    sections = _single_material_sections(material_id, len(counts))
    return counts, indices, vertex_indices, sections


def _extract_lod_faces(
    node: ET.Element,
    mesh_name: str,
    messages: list[str],
    material_ids: set[int],
) -> tuple[list[int], list[int], tuple[MeshSection, ...]]:
    face_counts: list[int] = []
    face_indices: list[int] = []
    sections_by_material: dict[int, list[int]] = defaultdict(list)
    face_offset = 0

    for triangles_node in node.findall("Triangles"):
        triangle_indices = _read_int_list(triangles_node.findtext("PointIndices") or triangles_node.findtext("TriangleIndices"))
        if not triangle_indices:
            continue
        if len(triangle_indices) % 3 != 0:
            messages.append(
                f"packed_array_error: {mesh_name}.Triangles index count {len(triangle_indices)} is not divisible by 3"
            )
            triangle_indices = triangle_indices[: len(triangle_indices) - (len(triangle_indices) % 3)]
        triangle_count = len(triangle_indices) // 3
        face_counts.extend([3] * triangle_count)
        face_indices.extend(triangle_indices)
        material_id = _read_material_id(triangles_node, f"{mesh_name}.Triangles", messages, material_ids)
        if material_id is not None:
            sections_by_material[material_id].extend(range(face_offset, face_offset + triangle_count))
        face_offset += triangle_count

    quad_indices = _read_int_list(node.findtext("QuadIndices"))
    if quad_indices:
        if len(quad_indices) % 4 != 0:
            messages.append(f"packed_array_error: {mesh_name}.QuadIndices index count {len(quad_indices)} is not divisible by 4")
            quad_indices = quad_indices[: len(quad_indices) - (len(quad_indices) % 4)]
        quad_count = len(quad_indices) // 4
        face_counts.extend([4] * quad_count)
        face_indices.extend(quad_indices)
        material_id = _read_material_id(node, f"{mesh_name}.QuadIndices", messages, material_ids)
        if material_id is not None:
            sections_by_material[material_id].extend(range(face_offset, face_offset + quad_count))
        face_offset += quad_count

    if not face_indices:
        triangle_indices = _read_int_list(node.findtext("TriangleIndices"))
        if triangle_indices:
            if len(triangle_indices) % 3 != 0:
                messages.append(
                    f"packed_array_error: {mesh_name}.TriangleIndices index count {len(triangle_indices)} is not divisible by 3"
                )
                triangle_indices = triangle_indices[: len(triangle_indices) - (len(triangle_indices) % 3)]
            triangle_count = len(triangle_indices) // 3
            face_counts.extend([3] * triangle_count)
            face_indices.extend(triangle_indices)
            material_id = _read_material_id(node, f"{mesh_name}.TriangleIndices", messages, material_ids)
            if material_id is not None:
                sections_by_material[material_id].extend(range(face_offset, face_offset + triangle_count))
            face_offset += triangle_count

    if not face_indices:
        messages.append(f"packed_array_error: mesh {mesh_name} does not contain any triangle or quad indices")
        return [], [], ()

    return face_counts, face_indices, _ordered_sections(sections_by_material)


def _extract_vertex_skinning(
    vertices_node: ET.Element | None,
    point_indices: list[int],
    vertex_indices: list[int],
    point_count: int,
    joint_index_by_source_id: dict[int, int],
    context: str,
    messages: list[str],
) -> tuple[list[int], list[float]]:
    if vertices_node is None or not point_indices:
        return [], []
    source_bone_ids = _read_int_list(vertices_node.findtext("BoneID"))
    if not source_bone_ids:
        messages.append(f"packed_array_error: {context} missing BoneID payload for skeletal base mesh")
        return [], []

    if vertex_indices and len(vertex_indices) != len(point_indices):
        messages.append(
            f"packed_array_error: {context} point index count {len(point_indices)} does not match vertex index count {len(vertex_indices)}"
        )
    point_vertex_pairs = zip(point_indices, vertex_indices or point_indices, strict=False)

    resolved_joint_indices = [0] * point_count
    resolved_joint_weights = [1.0] * point_count
    assigned_points = [False] * point_count

    for point_index, vertex_index in point_vertex_pairs:
        if point_index < 0 or point_index >= point_count:
            messages.append(f"packed_array_error: {context} point index {point_index} exceeds point count {point_count}")
            continue
        if vertex_index < 0 or vertex_index >= len(source_bone_ids):
            messages.append(f"packed_array_error: {context} vertex index {vertex_index} exceeds BoneID count {len(source_bone_ids)}")
            continue
        source_bone_id = source_bone_ids[vertex_index]
        if source_bone_id == -1:
            source_bone_id = 0
        elif source_bone_id < 0:
            messages.append(f"packed_array_error: {context} BoneID {source_bone_id} is not a valid skeletal binding")
            continue
        joint_index = joint_index_by_source_id.get(source_bone_id)
        if joint_index is None:
            messages.append(f"packed_array_error: {context} BoneID {source_bone_id} does not resolve to a skeleton joint")
            continue

        if assigned_points[point_index] and resolved_joint_indices[point_index] != joint_index:
            messages.append(
                f"packed_array_error: {context} point {point_index} resolves to conflicting skeletal joints "
                f"{resolved_joint_indices[point_index]} and {joint_index}"
            )
            continue

        resolved_joint_indices[point_index] = joint_index
        resolved_joint_weights[point_index] = 1.0
        assigned_points[point_index] = True

    for point_index, assigned in enumerate(assigned_points):
        if not assigned:
            messages.append(f"packed_array_error: {context} point {point_index} did not resolve to any skeletal binding")

    return resolved_joint_indices, resolved_joint_weights


def _extract_face_varying_uvs(
    vertices_node: ET.Element | None,
    vertex_indices: list[int],
    face_indices: list[int],
    context: str,
    messages: list[str],
    allow_point_index_fallback: bool = False,
) -> list[Vector2]:
    if vertices_node is None:
        return []
    u_coords = _read_float_list(vertices_node.findtext("TexcoordU"))
    v_coords = _read_float_list(vertices_node.findtext("TexcoordV"))
    if not u_coords and not v_coords:
        return []
    if not u_coords or not v_coords:
        messages.append(f"packed_array_error: {context} UV payload is incomplete")
        return []
    if len(u_coords) != len(v_coords):
        messages.append(
            f"packed_array_error: {context} TexcoordU count {len(u_coords)} does not match TexcoordV count {len(v_coords)}"
        )
    uv_count = min(len(u_coords), len(v_coords))
    if uv_count == 0:
        return []
    if vertex_indices:
        authored_indices = vertex_indices
    elif allow_point_index_fallback:
        authored_indices = face_indices
    else:
        if uv_count != len(face_indices):
            messages.append(
                f"packed_array_error: {context} UV count {uv_count} requires VertexIndices for face-varying authoring with {len(face_indices)} face vertices"
            )
            return []
        authored_indices = list(range(uv_count))
    if len(authored_indices) != len(face_indices):
        messages.append(
            f"packed_array_error: {context} vertex index count {len(authored_indices)} does not match face vertex count {len(face_indices)} for UV authoring"
        )
    limit = min(len(authored_indices), len(face_indices))
    uv_coords: list[Vector2] = []
    for vertex_index in authored_indices[:limit]:
        if vertex_index < 0 or vertex_index >= uv_count:
            messages.append(f"packed_array_error: {context} UV vertex index {vertex_index} exceeds texcoord count {uv_count}")
            continue
        uv_coords.append(Vector2(u_coords[vertex_index], v_coords[vertex_index]))
    if len(uv_coords) != len(face_indices):
        messages.append(
            f"packed_array_error: {context} authored UV count {len(uv_coords)} does not match face vertex count {len(face_indices)}"
        )
        return []
    return uv_coords


def _extract_vertex_colors(
    vertices_node: ET.Element | None,
    context: str,
    messages: list[str],
) -> list[Color4]:
    if vertices_node is None:
        return []
    red = _read_float_list(vertices_node.findtext("VertexColorR"))
    green = _read_float_list(vertices_node.findtext("VertexColorG"))
    blue = _read_float_list(vertices_node.findtext("VertexColorB"))
    alpha = _read_float_list(vertices_node.findtext("VertexColorA"))
    if not red and not green and not blue and not alpha:
        return []
    if not red or not green or not blue:
        messages.append(f"packed_array_error: {context} vertex color payload is incomplete")
        return []
    if len({len(red), len(green), len(blue)}) != 1:
        messages.append(
            f"packed_array_error: {context} vertex color counts do not match: "
            f"R={len(red)}, G={len(green)}, B={len(blue)}"
        )
    count = min(len(red), len(green), len(blue))
    if alpha and len(alpha) != count:
        messages.append(f"packed_array_error: {context} VertexColorA count {len(alpha)} does not match RGB count {count}")
    return [
        Color4(red[index], green[index], blue[index], alpha[index] if index < len(alpha) else 1.0)
        for index in range(count)
    ]


def _extract_lod_vertex_indices(
    node: ET.Element,
    face_indices: list[int],
    mesh_name: str,
    messages: list[str],
) -> list[int]:
    vertex_indices: list[int] = []
    for triangles_node in node.findall("Triangles"):
        indices = _read_int_list(triangles_node.findtext("VertexIndices"))
        if not indices:
            continue
        if len(indices) % 3 != 0:
            messages.append(
                f"packed_array_error: {mesh_name}.Triangles vertex index count {len(indices)} is not divisible by 3"
            )
            indices = indices[: len(indices) - (len(indices) % 3)]
        vertex_indices.extend(indices)
    if vertex_indices and len(vertex_indices) != len(face_indices):
        messages.append(
            f"packed_array_error: {mesh_name}.Triangles vertex index count {len(vertex_indices)} does not match face vertex count {len(face_indices)}"
        )
    return vertex_indices[: len(face_indices)]


def _read_material_id(
    node: ET.Element,
    context: str,
    messages: list[str],
    material_ids: set[int],
) -> int | None:
    raw_material_id = node.attrib.get("Material")
    if raw_material_id is None:
        return None
    if not raw_material_id.lstrip("-").isdigit():
        messages.append(f"invalid_material_id: {context} uses non-numeric material id {raw_material_id!r}")
        return None
    material_id = int(raw_material_id)
    if material_id not in material_ids:
        messages.append(f"missing_material_definition: {context} references undefined material id {material_id}")
    return material_id


def _single_material_sections(material_id: int | None, face_count: int) -> tuple[MeshSection, ...]:
    if material_id is None or face_count <= 0:
        return ()
    return (MeshSection(material_id=material_id, face_indices=tuple(range(face_count))),)


def _ordered_sections(sections_by_material: dict[int, list[int]]) -> tuple[MeshSection, ...]:
    return tuple(
        MeshSection(material_id=material_id, face_indices=tuple(sorted(face_indices)))
        for material_id, face_indices in sorted(sections_by_material.items())
        if face_indices
    )


def _vertex_color_material_sections(mesh: MeshData) -> tuple[MeshSection, ...] | None:
    if not mesh.vertex_colors or not mesh.face_vertex_counts or not mesh.face_vertex_indices:
        return None

    sections_by_material: dict[int, list[int]] = defaultdict(list)
    offset = 0
    for face_index, face_count in enumerate(mesh.face_vertex_counts):
        face_indices = mesh.face_vertex_indices[offset:offset + face_count]
        offset += face_count
        if len(face_indices) != face_count:
            return None
        if any(point_index < 0 or point_index >= len(mesh.vertex_colors) for point_index in face_indices):
            return None
        material_id = (
            LEAVES_MATERIAL_ID
            if all(mesh.vertex_colors[point_index].is_exact_black() for point_index in face_indices)
            else PRIMARY_MATERIAL_ID
        )
        sections_by_material[material_id].append(face_index)

    return _ordered_sections(sections_by_material)


def _apply_fallback_material_sections(
    mesh: MeshData,
    prototype_key: str,
    fallback_material_ids: set[int],
    messages: list[str],
) -> MeshData:
    if mesh.sections:
        if fallback_material_ids and {section.material_id for section in mesh.sections} != fallback_material_ids:
            messages.append(
                f"material_conflict: prototype {prototype_key} uses mesh-authored material ids "
                f"{sorted(section.material_id for section in mesh.sections)} over LeafReferences ids {sorted(fallback_material_ids)}"
            )
        return mesh
    if not fallback_material_ids:
        return mesh
    if len(fallback_material_ids) > 1:
        messages.append(
            f"material_conflict: prototype {prototype_key} has multiple LeafReferences material ids {sorted(fallback_material_ids)} without mesh-authored sections"
        )
    chosen_material_id = LEAVES_MATERIAL_ID if LEAVES_MATERIAL_ID in fallback_material_ids else PRIMARY_MATERIAL_ID
    return replace(mesh, sections=_single_material_sections(chosen_material_id, len(mesh.face_vertex_counts)))


def _consistent_count(
    context: str,
    messages: list[str],
    required: list[tuple[str, list[float] | list[int]]],
    optional: list[tuple[str, list[float] | list[int]]] | None = None,
) -> int:
    optional = optional or []
    required_lengths = [len(values) for _, values in required]
    if not required_lengths or min(required_lengths) == 0:
        return 0
    if len(set(required_lengths)) != 1:
        messages.append(
            f"packed_array_error: {context} required arrays have inconsistent lengths: "
            + ", ".join(f"{name}={len(values)}" for name, values in required)
        )
    count = min(required_lengths)
    for name, values in optional:
        if values and len(values) not in {count}:
            messages.append(f"packed_array_error: {context} optional array {name} has length {len(values)} expected {count}")
    return count


def _count_packed_values(node: ET.Element | None, tag_name: str) -> int:
    if node is None:
        return 0
    return len(_read_float_list(node.findtext(tag_name)))


def _read_float_list(raw: str | None) -> list[float]:
    if not raw:
        return []
    values: list[float] = []
    for token in raw.replace(",", " ").split():
        try:
            values.append(float(token))
        except ValueError:
            continue
    return values


def _read_int_list(raw: str | None) -> list[int]:
    if not raw:
        return []
    values: list[int] = []
    for token in raw.replace(",", " ").split():
        try:
            values.append(int(token))
        except ValueError:
            continue
    return values


def _read_positive_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if math.isfinite(value) and value > 0.0 else None


def _quaternion_from_axis_angle(axis: Vector3, angle_degrees: float) -> Quaternion:
    length = math.sqrt(axis.x * axis.x + axis.y * axis.y + axis.z * axis.z)
    if length == 0.0:
        return Quaternion(1.0, 0.0, 0.0, 0.0)
    half_angle = math.radians(angle_degrees) * 0.5
    sin_half = math.sin(half_angle)
    return Quaternion(
        real=math.cos(half_angle),
        i=(axis.x / length) * sin_half,
        j=(axis.y / length) * sin_half,
        k=(axis.z / length) * sin_half,
    )
