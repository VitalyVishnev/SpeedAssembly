from __future__ import annotations

import gc
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, replace

from . import source_extraction
from .naming import build_prototype_identities
from .models import (
    BaseTreePart,
    Bounds,
    BranchSegment,
    CanonicalTreeModel,
    Color4,
    ExportMetadata,
    Joint,
    MaterialSpec,
    MeshData,
    MeshLibraryEntry,
    MeshSection,
    ObservedXmlSchemaReport,
    Prototype,
    PrototypeStrategy,
    RepeatedPartInstance,
    SkeletalSupportPrimvars,
    SourceObject,
    SpineCurve,
    Vector2,
    Vector3,
)
from .skeleton_rules import joint_name_from_bone_id
from .source_transform import SourceTransform, build_source_transform
from .xml_reader import SourceNodeIndex


PRIMARY_MATERIAL_ID = 1
LEAVES_MATERIAL_ID = 2


@dataclass(frozen=True)
class _ObjectExtractionResult:
    source_objects: tuple[SourceObject, ...]
    assembly_parts: tuple[RepeatedPartInstance, ...]


def normalize_to_canonical(
    document,
    report: ObservedXmlSchemaReport,
    *,
    source_nodes: SourceNodeIndex | None = None,
) -> CanonicalTreeModel:
    # The canonical model is acyclic; cyclic-GC scans only add overhead while its many immutable values are built.
    gc_was_enabled = gc.isenabled()
    if gc_was_enabled:
        gc.disable()
    try:
        return _normalize_to_canonical(document, report, source_nodes=source_nodes)
    finally:
        if gc_was_enabled:
            gc.enable()


def _normalize_to_canonical(
    document,
    report: ObservedXmlSchemaReport,
    *,
    source_nodes: SourceNodeIndex | None = None,
) -> CanonicalTreeModel:
    root = document.tree.getroot()
    data_messages: list[str] = []
    # Stage metadata alone is not enough. Every spatial payload must be remapped into stage space here.
    mesh_nodes = source_nodes.meshes if source_nodes is not None else None
    source_transform = build_source_transform(root, report.units_hint, report.up_axis_hint, mesh_nodes)
    if source_nodes is None:
        source_nodes = SourceNodeIndex(
            materials=tuple(root.findall(".//Materials/Material")),
            objects=tuple(root.findall(".//Object")),
            meshes=tuple(root.findall(".//Meshes/Mesh")),
            bones=tuple(root.findall(".//Bones/Bone")),
        )
    materials = tuple(_extract_materials(source_nodes.materials))
    material_ids = {material.source_id for material in materials}

    skeleton = source_extraction.normalize_source_skeleton(source_nodes.bones, source_transform, data_messages)
    joint_index_by_source_id = {
        joint.source_id: index for index, joint in enumerate(skeleton) if joint.source_id is not None
    }
    object_extraction = _extract_object_records(
        source_nodes.objects,
        data_messages,
        joint_index_by_source_id,
        source_transform,
        material_ids,
    )
    source_objects = object_extraction.source_objects
    mesh_library = tuple(_extract_mesh_library(source_nodes.meshes, data_messages, source_transform, material_ids))
    base_mesh, base_tree_parts = _build_base_mesh(source_objects)
    # The project contract treats LeafReferences as the source of repeated Parts.
    assembly_parts = object_extraction.assembly_parts
    joint_names = {joint.name for joint in skeleton}
    branch_segments = tuple(_extract_branch_segments(source_objects, joint_names))
    prototypes = tuple(_build_prototypes(assembly_parts, mesh_library, material_ids, data_messages))
    skeletal_support_primvars = _build_skeletal_support_primvars(skeleton)
    spines = tuple(source_object.spine for source_object in source_objects if source_object.spine is not None)

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


def _extract_materials(material_nodes: tuple[ET.Element, ...]) -> list[MaterialSpec]:
    materials: list[MaterialSpec] = []
    for material_node in material_nodes:
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
                source_material_ids=(int(source_id),),
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
    merged_normals: list[Vector3] = []
    merged_uv_coords: list[Vector2] = []
    merged_vertex_colors: list[Color4] = []
    merged_joint_indices: list[int] = []
    merged_joint_weights: list[float] = []
    merged_sections: dict[int, list[int]] = defaultdict(list)
    merged_parts: list[BaseTreePart] = []
    preserve_vertex_colors = True
    preserve_normals = True
    normal_interpolation: str | None = None

    for source_object in candidates:
        mesh = source_object.mesh
        if mesh is None:
            continue
        point_offset = len(merged_points)
        face_offset = len(merged_face_counts)
        translate = source_object.abs_translate
        tx = translate.x
        ty = translate.y
        tz = translate.z
        merged_points.extend(Vector3(point.x + tx, point.y + ty, point.z + tz) for point in mesh.points)
        merged_face_counts.extend(mesh.face_vertex_counts)
        merged_face_indices.extend(index + point_offset for index in mesh.face_vertex_indices)
        if preserve_normals:
            mesh_normal_interpolation = (
                "vertex"
                if len(mesh.normals) == len(mesh.points)
                else ("faceVarying" if len(mesh.normals) == len(mesh.face_vertex_indices) else None)
            )
            if mesh_normal_interpolation is not None and normal_interpolation in (None, mesh_normal_interpolation):
                normal_interpolation = mesh_normal_interpolation
                merged_normals.extend(mesh.normals)
            else:
                preserve_normals = False
                merged_normals.clear()
        merged_uv_coords.extend(mesh.uv_coords)
        if preserve_vertex_colors:
            if len(mesh.vertex_colors) == len(mesh.points):
                merged_vertex_colors.extend(mesh.vertex_colors)
            else:
                preserve_vertex_colors = False
                merged_vertex_colors.clear()
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
            normals=tuple(merged_normals if preserve_normals else ()),
            uv_coords=tuple(merged_uv_coords),
            vertex_colors=tuple(merged_vertex_colors if preserve_vertex_colors else ()),
            sections=source_extraction.ordered_sections(merged_sections),
            skel_joint_indices=tuple(merged_joint_indices),
            skel_joint_weights=tuple(merged_joint_weights),
            skel_element_size=1 if merged_joint_indices else 0,
        ),
        tuple(merged_parts),
    )


def _extract_source_objects(
    object_nodes: tuple[ET.Element, ...],
    messages: list[str],
    joint_index_by_source_id: dict[int, int],
    source_transform: SourceTransform,
    material_ids: set[int],
) -> list[SourceObject]:
    return list(
        _extract_object_records(
            object_nodes,
            messages,
            joint_index_by_source_id,
            source_transform,
            material_ids,
        ).source_objects
    )


def _extract_object_records(
    object_nodes: tuple[ET.Element, ...],
    messages: list[str],
    joint_index_by_source_id: dict[int, int],
    source_transform: SourceTransform,
    material_ids: set[int],
) -> _ObjectExtractionResult:
    source_objects: list[SourceObject] = []
    assembly_parts: list[RepeatedPartInstance] = []
    for obj in object_nodes:
        attrib = obj.attrib
        object_id = attrib.get("ID")
        points_node: ET.Element | None = None
        triangles_nodes: list[ET.Element] = []
        vertices_node: ET.Element | None = None
        leaf_ref_nodes: list[ET.Element] = []
        spine_node: ET.Element | None = None
        for child in obj:
            tag = child.tag
            if tag == "Points" and points_node is None:
                points_node = child
            elif tag == "Triangles":
                triangles_nodes.append(child)
            elif tag == "Vertices" and vertices_node is None:
                vertices_node = child
            elif tag == "LeafReferences":
                leaf_ref_nodes.append(child)
            elif tag == "Spine" and spine_node is None:
                spine_node = child
        abs_translate = source_extraction.object_abs_translate(obj, source_transform)
        has_mesh_payload = points_node is not None and bool(triangles_nodes)
        if object_id is not None:
            parent_id = attrib.get("ParentID")
            to_stage = source_transform.point_components_to_stage
            rel_x = source_extraction.parse_float_value(attrib.get("RelX"))
            rel_y = source_extraction.parse_float_value(attrib.get("RelY"))
            rel_z = source_extraction.parse_float_value(attrib.get("RelZ"))
            mesh = source_extraction.extract_object_mesh(
                attrib.get("Name", obj.tag), points_node, tuple(triangles_nodes), vertices_node,
                joint_index_by_source_id, messages, source_transform, material_ids,
            )
            leaf_count = sum(len(source_extraction.read_float_list(leaf_ref_node.findtext("X"))) for leaf_ref_node in leaf_ref_nodes)
            spine = _extract_spine(
                obj,
                object_id,
                messages,
                source_transform,
                spine_node=spine_node,
            )
            source_objects.append(
                SourceObject(
                    object_id=object_id,
                    parent_id=parent_id,
                    name=attrib.get("Name", f"Object_{object_id}"),
                    abs_translate=abs_translate,
                    rel_translate=to_stage(
                        rel_x if rel_x is not None else 0.0,
                        rel_y if rel_y is not None else 0.0,
                        rel_z if rel_z is not None else 0.0,
                    ),
                    bounds=_extract_bounds(obj, source_transform),
                    mesh=mesh,
                    assembly_part_reference_count=leaf_count,
                    spine=spine,
                )
            )
        if not leaf_ref_nodes:
            continue

        assembly_parts.extend(source_extraction.extract_repeated_parts(
            obj, tuple(leaf_ref_nodes), messages, source_transform, material_ids,
            first_instance_index=len(assembly_parts), has_mesh_payload=has_mesh_payload,
            abs_translate=abs_translate,
        ))
    return _ObjectExtractionResult(
        source_objects=tuple(source_objects),
        assembly_parts=tuple(assembly_parts),
    )


def _extract_mesh_library(
    mesh_nodes: tuple[ET.Element, ...],
    messages: list[str],
    source_transform: SourceTransform,
    material_ids: set[int],
) -> list[MeshLibraryEntry]:
    entries: list[MeshLibraryEntry] = []
    for mesh in mesh_nodes:
        mesh_id = mesh.attrib.get("ID")
        if mesh_id is None or not mesh_id.isdigit():
            continue
        lod = source_extraction.select_primary_lod(mesh)
        if lod is None:
            messages.append(f"packed_array_error: mesh {mesh.attrib.get('Name', mesh.tag)} missing LOD payload")
            continue
        vertices = lod.find("Vertices")
        if vertices is None:
            messages.append(f"packed_array_error: mesh {mesh.attrib.get('Name', mesh.tag)} missing vertices payload")
            continue
        mesh_data = source_extraction.extract_prototype_mesh(
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
                    original_scale=source_extraction.read_positive_float(lod.attrib.get("OriginalScale")),
                )
            )
    return entries


def _extract_assembly_parts_from_leaf_references(
    object_nodes: tuple[ET.Element, ...],
    messages: list[str],
    source_transform: SourceTransform,
    material_ids: set[int],
) -> list[RepeatedPartInstance]:
    return list(
        _extract_object_records(
            object_nodes,
            messages,
            {},
            source_transform,
            material_ids,
        ).assembly_parts
    )


def _extract_branch_segments(source_objects: tuple[SourceObject, ...], joint_names: set[str]) -> list[BranchSegment]:
    segments: list[BranchSegment] = []
    for source_object in source_objects:
        if source_object.mesh is None:
            continue
        candidate_joint = _resolve_source_object_joint_name(source_object, joint_names)
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


def _resolve_source_object_joint_name(source_object: SourceObject, joint_names: set[str]) -> str | None:
    if source_object.object_id.isdigit():
        numeric_id = int(source_object.object_id)
        candidate_joint = joint_name_from_bone_id(numeric_id)
        if candidate_joint in joint_names:
            return candidate_joint
    return None


def _build_prototypes(
    assembly_parts: tuple[RepeatedPartInstance, ...],
    mesh_library: tuple[MeshLibraryEntry, ...],
    material_ids: set[int],
    messages: list[str],
) -> list[Prototype]:
    if not assembly_parts:
        return []
    source_keys = tuple(dict.fromkeys(part.prototype_key for part in assembly_parts))
    meshes_by_key = {f"Mesh_{entry.mesh_id}": entry for entry in mesh_library}
    display_names = [meshes_by_key[key].name if key in meshes_by_key else key for key in source_keys]
    identities = build_prototype_identities(list(source_keys), display_names)
    fallback_material_counts: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for part in assembly_parts:
        if part.source_material_id is not None:
            fallback_material_counts[part.prototype_key][part.source_material_id] += 1
    prototypes: list[Prototype] = []
    for identity in identities:
        entry = meshes_by_key.get(identity.source_key)
        mesh = source_extraction.mesh_with_original_scale(entry) if entry is not None else None
        if mesh is not None:
            mesh = _resolve_prototype_material_sections(
                mesh,
                identity.source_key,
                fallback_material_counts.get(identity.source_key, {}),
                material_ids,
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
    fallback_material_counts: dict[int, int],
    material_ids: set[int],
    messages: list[str],
) -> MeshData:
    primary_material_id, leaves_material_id = _resolve_role_material_ids(fallback_material_counts, material_ids)
    vertex_color_sections = _vertex_color_material_sections(
        mesh,
        primary_material_id=primary_material_id,
        leaves_material_id=leaves_material_id,
    )
    if vertex_color_sections is not None:
        authored_material_ids = {section.material_id for section in mesh.sections}
        resolved_material_ids = {section.material_id for section in vertex_color_sections}
        if authored_material_ids and authored_material_ids != resolved_material_ids:
            messages.append(
                f"material_conflict: prototype {prototype_key} uses vertex-color-derived material ids "
                f"{sorted(resolved_material_ids)} over mesh-authored material ids {sorted(authored_material_ids)}"
            )
        return replace(mesh, sections=vertex_color_sections)

    return _apply_fallback_material_sections(mesh, prototype_key, fallback_material_counts, messages)


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
    *,
    spine_node: ET.Element | None = None,
) -> SpineCurve | None:
    if spine_node is None:
        return None
    xs_raw = ys_raw = zs_raw = radii_raw = None
    for child in spine_node:
        tag = child.tag
        text = child.text
        if tag == "X":
            xs_raw = text
        elif tag == "Y":
            ys_raw = text
        elif tag == "Z":
            zs_raw = text
        elif tag == "Radius":
            radii_raw = text
    xs = source_extraction.read_float_list(xs_raw)
    ys = source_extraction.read_float_list(ys_raw)
    zs = source_extraction.read_float_list(zs_raw)
    radii = source_extraction.read_float_list(radii_raw)
    count = source_extraction.consistent_count(
        f"Spine[{obj.attrib.get('Name', object_id)}]",
        messages,
        required=[("X", xs), ("Y", ys), ("Z", zs)],
        optional=[("Radius", radii)],
    )
    if count == 0:
        return None
    points = tuple(source_transform.points_components_to_stage(xs[:count], ys[:count], zs[:count]))
    usable_radii = tuple(radii[:count]) if radii else ()
    return SpineCurve(source_object_id=object_id, points=points, radii=usable_radii)


def _extract_bounds(obj: ET.Element, source_transform: SourceTransform) -> Bounds | None:
    return _bounds_from_attributes(obj.attrib, source_transform)


def _bounds_from_attributes(attrib: dict[str, str], source_transform: SourceTransform) -> Bounds | None:
    bounds_to_stage = source_transform.bounds_to_stage
    min_components = (attrib.get("BoundsMinX"), attrib.get("BoundsMinY"), attrib.get("BoundsMinZ"))
    max_components = (attrib.get("BoundsMaxX"), attrib.get("BoundsMaxY"), attrib.get("BoundsMaxZ"))
    if any(component is None for component in min_components + max_components):
        return None
    minimum = tuple(source_extraction.parse_float_value(component) for component in min_components)
    maximum = tuple(source_extraction.parse_float_value(component) for component in max_components)
    if any(component is None for component in minimum + maximum):
        return None
    return bounds_to_stage(Bounds(
        minimum=Vector3(minimum[0], minimum[1], minimum[2]),
        maximum=Vector3(maximum[0], maximum[1], maximum[2]),
    ))


def _capture_token_from_bone_id(bone_id: int | None) -> str:
    return f"Tree_point_{bone_id or 0}"


def _capture_token_from_joint(joint: Joint, fallback_index: int) -> str:
    return _capture_token_from_bone_id(joint.source_id if joint.source_id is not None else fallback_index)


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


def _vertex_color_material_sections(
    mesh: MeshData,
    *,
    primary_material_id: int = PRIMARY_MATERIAL_ID,
    leaves_material_id: int = LEAVES_MATERIAL_ID,
) -> tuple[MeshSection, ...] | None:
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
            leaves_material_id
            if all(mesh.vertex_colors[point_index].is_exact_black() for point_index in face_indices)
            else primary_material_id
        )
        sections_by_material[material_id].append(face_index)

    return source_extraction.ordered_sections(sections_by_material)


def _resolve_role_material_ids(
    fallback_material_counts: dict[int, int],
    material_ids: set[int],
) -> tuple[int, int]:
    if not material_ids:
        return PRIMARY_MATERIAL_ID, LEAVES_MATERIAL_ID

    ordered_material_ids = sorted(material_ids)
    leaves_material_id = None
    if fallback_material_counts:
        leaves_material_id = min(
            fallback_material_counts,
            key=lambda material_id: (-fallback_material_counts[material_id], material_id),
        )
    if leaves_material_id is None:
        leaves_material_id = ordered_material_ids[-1]

    primary_candidates = [material_id for material_id in ordered_material_ids if material_id != leaves_material_id]
    primary_material_id = primary_candidates[0] if primary_candidates else leaves_material_id
    return primary_material_id, leaves_material_id


def _apply_fallback_material_sections(
    mesh: MeshData,
    prototype_key: str,
    fallback_material_counts: dict[int, int],
    messages: list[str],
) -> MeshData:
    if mesh.sections:
        fallback_material_ids = set(fallback_material_counts)
        if fallback_material_ids and {section.material_id for section in mesh.sections} != fallback_material_ids:
            messages.append(
                f"material_conflict: prototype {prototype_key} uses mesh-authored material ids "
                f"{sorted(section.material_id for section in mesh.sections)} over LeafReferences ids {sorted(fallback_material_ids)}"
            )
        return mesh
    if not fallback_material_counts:
        return mesh
    fallback_material_ids = set(fallback_material_counts)
    if len(fallback_material_ids) > 1:
        messages.append(
            f"material_conflict: prototype {prototype_key} has multiple LeafReferences material ids {sorted(fallback_material_ids)} without mesh-authored sections"
        )
    chosen_material_id = min(
        fallback_material_counts,
        key=lambda material_id: (-fallback_material_counts[material_id], material_id),
    )
    return replace(mesh, sections=source_extraction.single_material_sections(chosen_material_id, len(mesh.face_vertex_counts)))
