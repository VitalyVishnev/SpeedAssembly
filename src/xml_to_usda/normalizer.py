from __future__ import annotations

import math
import xml.etree.ElementTree as ET

from .models import (
    Bounds,
    BranchSegment,
    CanonicalTreeModel,
    ExportMetadata,
    Joint,
    LeafInstance,
    MeshData,
    MeshLibraryEntry,
    ObservedXmlSchemaReport,
    Quaternion,
    SourceObject,
    SpineCurve,
    Vector3,
)


def normalize_to_canonical(document, report: ObservedXmlSchemaReport) -> CanonicalTreeModel:
    root = document.tree.getroot()
    data_messages: list[str] = []

    source_objects = tuple(_extract_source_objects(root, data_messages))
    skeleton = tuple(_extract_skeleton(root))
    mesh_library = tuple(_extract_mesh_library(root, data_messages))
    trunk_mesh = _extract_trunk_mesh(source_objects)
    leaf_instances = tuple(_extract_leaf_instances(root, skeleton, data_messages))
    branch_segments = tuple(_extract_branch_segments(source_objects, skeleton))
    spines = tuple(source_object.spine for source_object in source_objects if source_object.spine is not None)

    metadata = ExportMetadata(
        source_path=document.source_path,
        source_version=report.version,
        meters_per_unit=0.01,
        up_axis="Z",
        warnings=tuple(_metadata_warnings(report) + data_messages),
        unknown_sections=report.unknown_sections,
    )

    return CanonicalTreeModel(
        metadata=metadata,
        source_objects=source_objects,
        trunk_mesh=trunk_mesh,
        skeleton=skeleton,
        leaf_instances=leaf_instances,
        branch_segments=branch_segments,
        mesh_library=mesh_library,
        spines=spines,
    )


def _metadata_warnings(report: ObservedXmlSchemaReport) -> list[str]:
    warnings: list[str] = []
    if report.units_hint and report.units_hint not in {"cm", "centimeter", "centimeters"}:
        warnings.append(f"Non-default units hint detected: {report.units_hint}")
    if report.up_axis_hint and report.up_axis_hint.upper() != "Z":
        warnings.append(f"Non-default up-axis hint detected: {report.up_axis_hint}")
    if report.unknown_sections:
        warnings.append(f"Unknown XML sections detected: {', '.join(report.unknown_sections)}")
    if report.object_class_counts.get("total", 0) == 0:
        warnings.append("missing_object_hierarchy: XML does not contain any Object nodes")
    if report.leaf_binding_distribution and not report.leaf_mesh_distribution:
        warnings.append("missing_leaf_binding: Leaf references are present without mesh ids")
    return warnings


def _extract_trunk_mesh(source_objects: tuple[SourceObject, ...]) -> MeshData | None:
    for source_object in source_objects:
        if source_object.name == "Trunk" and source_object.mesh is not None:
            return source_object.mesh
    for source_object in source_objects:
        if source_object.mesh is not None and source_object.name.lower() != "leaves":
            return source_object.mesh
    return None


def _extract_source_objects(root: ET.Element, messages: list[str]) -> list[SourceObject]:
    source_objects: list[SourceObject] = []
    for obj in root.findall(".//Object"):
        object_id = obj.attrib.get("ID")
        if object_id is None:
            continue
        mesh = _extract_object_mesh(obj, messages)
        leaf_count = _count_packed_values(obj.find("LeafReferences"), "X")
        spine = _extract_spine(obj, object_id, messages)
        source_objects.append(
            SourceObject(
                object_id=object_id,
                parent_id=obj.attrib.get("ParentID"),
                name=obj.attrib.get("Name", f"Object_{object_id}"),
                abs_translate=_vector_from_named_attributes(obj, ("AbsX", "AbsY", "AbsZ")),
                rel_translate=_vector_from_named_attributes(obj, ("RelX", "RelY", "RelZ")),
                bounds=_extract_bounds(obj),
                mesh=mesh,
                leaf_instance_count=leaf_count,
                spine=spine,
            )
        )
    return source_objects


def _extract_mesh_library(root: ET.Element, messages: list[str]) -> list[MeshLibraryEntry]:
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
        mesh_data = _build_library_mesh_data(mesh.attrib.get("Name", f"Mesh_{mesh_id}"), vertices, lod, messages)
        if mesh_data is not None:
            entries.append(MeshLibraryEntry(mesh_id=int(mesh_id), name=mesh_data.name, mesh=mesh_data))
    return entries


def _extract_object_mesh(obj: ET.Element, messages: list[str]) -> MeshData | None:
    points_node = obj.find("Points")
    triangles_node = obj.find("Triangles")
    if points_node is None or triangles_node is None:
        return None
    return _build_mesh_data(obj.attrib.get("Name", obj.tag), points_node, triangles_node, messages)


def _build_mesh_data(name: str, points_node: ET.Element, triangles_node: ET.Element, messages: list[str]) -> MeshData | None:
    points = _extract_packed_points(points_node, f"{name}.points", messages)
    face_counts, face_indices = _extract_packed_triangles(triangles_node, f"{name}.triangles", messages)
    if not points or not face_counts or not face_indices:
        return None
    return _build_mesh_from_faces(name, points, face_counts, face_indices)


def _build_library_mesh_data(name: str, points_node: ET.Element, lod_node: ET.Element, messages: list[str]) -> MeshData | None:
    points = _extract_packed_points(points_node, f"{name}.points", messages)
    face_counts, face_indices = _extract_lod_faces(lod_node, name, messages)
    if not points or not face_counts or not face_indices:
        return None
    return _build_mesh_from_faces(name, points, face_counts, face_indices)


def _build_mesh_from_faces(name: str, points: list[Vector3], face_counts: list[int], face_indices: list[int]) -> MeshData:
    return MeshData(
        name=name,
        points=tuple(points),
        face_vertex_counts=tuple(face_counts),
        face_vertex_indices=tuple(face_indices),
    )


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


def _extract_skeleton(root: ET.Element) -> list[Joint]:
    bones = root.findall(".//Bones/Bone")
    if not bones:
        return []

    joints: list[Joint] = []
    for bone in bones:
        bone_id = bone.attrib.get("ID")
        if bone_id is None or not bone_id.lstrip("-").isdigit():
            continue
        parent_id = bone.attrib.get("ParentID")
        name = _joint_name_from_bone_id(int(bone_id))
        parent = None
        if parent_id not in {None, "", "-1"} and parent_id.lstrip("-").isdigit():
            parent = _joint_name_from_bone_id(int(parent_id))
        joints.append(
            Joint(
                name=name,
                parent=parent,
                bind_translate=Vector3(
                    _find_float(bone, ("EndX",), default=0.0) or 0.0,
                    _find_float(bone, ("EndY",), default=0.0) or 0.0,
                    _find_float(bone, ("EndZ",), default=0.0) or 0.0,
                ),
            )
        )
    return joints


def _extract_leaf_instances(root: ET.Element, skeleton: tuple[Joint, ...], messages: list[str]) -> list[LeafInstance]:
    leaf_instances: list[LeafInstance] = []
    default_joint = skeleton[0].name if skeleton else "root"
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
            bind_joint = _joint_name_from_bone_id(source_bone_id) if source_bone_id is not None else default_joint
            source_mesh_id = mesh_ids[index] if index < len(mesh_ids) else None
            prototype_key = f"Mesh_{source_mesh_id}" if source_mesh_id is not None else "LeafPrototype"
            uniform_scale = scales[index] if index < len(scales) else 1.0
            leaf_instances.append(
                LeafInstance(
                    name=f"LeafRef_{len(leaf_instances):04d}",
                    prototype_key=prototype_key,
                    position=Vector3(xs[index], ys[index], zs[index]),
                    orientation=_quaternion_from_axis_angle(
                        axis_x[index] if index < len(axis_x) else 0.0,
                        axis_y[index] if index < len(axis_y) else 0.0,
                        axis_z[index] if index < len(axis_z) else 1.0,
                        angles[index] if index < len(angles) else 0.0,
                    ),
                    scale=Vector3(uniform_scale, uniform_scale, uniform_scale),
                    bind_joint=bind_joint,
                    source_object_id=obj.attrib.get("ID"),
                    source_mesh_id=source_mesh_id,
                    source_bone_id=source_bone_id,
                    mesh_lod=mesh_lods[index] if index < len(mesh_lods) else None,
                )
            )
    return leaf_instances


def _extract_branch_segments(source_objects: tuple[SourceObject, ...], skeleton: tuple[Joint, ...]) -> list[BranchSegment]:
    joint_names = {joint.name for joint in skeleton}
    segments: list[BranchSegment] = []
    for source_object in source_objects:
        if not source_object.name.startswith("Branches") or source_object.mesh is None:
            continue
        candidate_joint = None
        if source_object.object_id.isdigit():
            numeric_id = int(source_object.object_id)
            branch_joint_name = _joint_name_from_bone_id(numeric_id)
            if branch_joint_name in joint_names:
                candidate_joint = branch_joint_name
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


def _extract_spine(obj: ET.Element, object_id: str, messages: list[str]) -> SpineCurve | None:
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
    points = tuple(Vector3(xs[index], ys[index], zs[index]) for index in range(count))
    usable_radii = tuple(radii[:count]) if radii else ()
    return SpineCurve(source_object_id=object_id, points=points, radii=usable_radii)


def _extract_bounds(obj: ET.Element) -> Bounds | None:
    min_components = (obj.attrib.get("BoundsMinX"), obj.attrib.get("BoundsMinY"), obj.attrib.get("BoundsMinZ"))
    max_components = (obj.attrib.get("BoundsMaxX"), obj.attrib.get("BoundsMaxY"), obj.attrib.get("BoundsMaxZ"))
    if any(component is None for component in min_components + max_components):
        return None
    return Bounds(
        minimum=Vector3(float(min_components[0]), float(min_components[1]), float(min_components[2])),
        maximum=Vector3(float(max_components[0]), float(max_components[1]), float(max_components[2])),
    )


def _vector_from_named_attributes(elem: ET.Element, names: tuple[str, str, str]) -> Vector3:
    return Vector3(
        _find_float(elem, (names[0],), default=0.0) or 0.0,
        _find_float(elem, (names[1],), default=0.0) or 0.0,
        _find_float(elem, (names[2],), default=0.0) or 0.0,
    )


def _joint_name_from_bone_id(bone_id: int | None) -> str:
    if bone_id is None:
        return "root"
    return "root" if bone_id == 0 else f"bone_{bone_id:03d}"


def _find_float(elem: ET.Element, names: tuple[str, ...], default: float | None = None) -> float | None:
    for name in names:
        if name in elem.attrib:
            try:
                return float(elem.attrib[name])
            except ValueError:
                return default
    return default


def _extract_packed_points(node: ET.Element, context: str, messages: list[str]) -> list[Vector3]:
    xs = _read_float_list(node.findtext("X"))
    ys = _read_float_list(node.findtext("Y"))
    zs = _read_float_list(node.findtext("Z"))
    count = _consistent_count(context, messages, required=[("X", xs), ("Y", ys), ("Z", zs)])
    return [Vector3(xs[index], ys[index], zs[index]) for index in range(count)]


def _extract_packed_triangles(node: ET.Element, context: str, messages: list[str]) -> tuple[list[int], list[int]]:
    indices = _read_int_list(node.findtext("PointIndices") or node.findtext("VertexIndices") or node.findtext("TriangleIndices"))
    if not indices:
        messages.append(f"packed_array_error: {context} does not contain triangle indices")
        return [], []
    if len(indices) % 3 != 0:
        messages.append(f"packed_array_error: {context} index count {len(indices)} is not divisible by 3")
        indices = indices[: len(indices) - (len(indices) % 3)]
    counts = [3] * (len(indices) // 3)
    return counts, indices


def _extract_lod_faces(node: ET.Element, mesh_name: str, messages: list[str]) -> tuple[list[int], list[int]]:
    face_counts: list[int] = []
    face_indices: list[int] = []

    triangle_indices = _read_int_list(node.findtext("TriangleIndices"))
    if triangle_indices:
        if len(triangle_indices) % 3 != 0:
            messages.append(
                f"packed_array_error: {mesh_name}.TriangleIndices index count {len(triangle_indices)} is not divisible by 3"
            )
            triangle_indices = triangle_indices[: len(triangle_indices) - (len(triangle_indices) % 3)]
        face_counts.extend([3] * (len(triangle_indices) // 3))
        face_indices.extend(triangle_indices)

    quad_indices = _read_int_list(node.findtext("QuadIndices"))
    if quad_indices:
        if len(quad_indices) % 4 != 0:
            messages.append(f"packed_array_error: {mesh_name}.QuadIndices index count {len(quad_indices)} is not divisible by 4")
            quad_indices = quad_indices[: len(quad_indices) - (len(quad_indices) % 4)]
        face_counts.extend([4] * (len(quad_indices) // 4))
        face_indices.extend(quad_indices)

    if not face_indices:
        messages.append(f"packed_array_error: mesh {mesh_name} does not contain any triangle or quad indices")
        return [], []

    return face_counts, face_indices


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


def _quaternion_from_axis_angle(x: float, y: float, z: float, angle_degrees: float) -> Quaternion:
    length = math.sqrt(x * x + y * y + z * z)
    if length == 0.0:
        return Quaternion(1.0, 0.0, 0.0, 0.0)
    half_angle = math.radians(angle_degrees) * 0.5
    sin_half = math.sin(half_angle)
    return Quaternion(
        real=math.cos(half_angle),
        i=(x / length) * sin_half,
        j=(y / length) * sin_half,
        k=(z / length) * sin_half,
    )
