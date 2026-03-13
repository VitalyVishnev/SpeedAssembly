from __future__ import annotations

import math
import xml.etree.ElementTree as ET

from .models import CanonicalTreeModel, ExportMetadata, Joint, LeafReference, MeshData, ObservedXmlSchemaReport, Quaternion, Vector3


def normalize_to_canonical(document, report: ObservedXmlSchemaReport) -> CanonicalTreeModel:
    root = document.tree.getroot()
    metadata = ExportMetadata(
        source_path=document.source_path,
        source_version=report.version,
        meters_per_unit=0.01,
        up_axis="Z",
        warnings=tuple(_metadata_warnings(report)),
        unknown_sections=report.unknown_sections,
    )

    trunk_mesh = _extract_trunk_mesh(root)
    skeleton = tuple(_extract_skeleton(root))
    leaf_references = tuple(_extract_leaf_references(root, skeleton))

    return CanonicalTreeModel(
        metadata=metadata,
        trunk_mesh=trunk_mesh,
        skeleton=skeleton,
        leaf_references=leaf_references,
    )


def _metadata_warnings(report: ObservedXmlSchemaReport) -> list[str]:
    warnings: list[str] = []
    if report.units_hint and report.units_hint not in {"cm", "centimeter", "centimeters"}:
        warnings.append(f"Non-default units hint detected: {report.units_hint}")
    if report.up_axis_hint and report.up_axis_hint.upper() != "Z":
        warnings.append(f"Non-default up-axis hint detected: {report.up_axis_hint}")
    if report.unknown_sections:
        warnings.append(f"Unknown XML sections detected: {', '.join(report.unknown_sections)}")
    return warnings


def _extract_trunk_mesh(root: ET.Element) -> MeshData | None:
    object_mesh = _extract_object_mesh(root)
    if object_mesh is not None:
        return object_mesh

    mesh_candidates = [
        elem for elem in root.iter()
        if "mesh" in elem.tag.lower() or "geometry" in elem.tag.lower() or "trunk" in elem.tag.lower()
    ]
    for candidate in mesh_candidates:
        points = _extract_points(candidate)
        face_counts, face_indices = _extract_faces(candidate)
        if points and face_counts and face_indices:
            return MeshData(
                name=candidate.attrib.get("name", candidate.tag),
                points=tuple(points),
                face_vertex_counts=tuple(face_counts),
                face_vertex_indices=tuple(face_indices),
            )
    return None


def _extract_object_mesh(root: ET.Element) -> MeshData | None:
    for obj in root.findall(".//Object"):
        name = obj.attrib.get("Name", "")
        if name.lower() == "leaves":
            continue
        points_node = obj.find("Points")
        triangles_node = obj.find("Triangles")
        if points_node is None or triangles_node is None:
            continue

        points = _extract_packed_points(points_node)
        face_counts, face_indices = _extract_packed_triangles(triangles_node)
        if points and face_counts and face_indices:
            return MeshData(
                name=name or obj.tag,
                points=tuple(points),
                face_vertex_counts=tuple(face_counts),
                face_vertex_indices=tuple(face_indices),
            )
    return None


def _extract_points(node: ET.Element) -> list[Vector3]:
    points: list[Vector3] = []
    vertex_nodes = [
        elem for elem in node.iter()
        if elem.tag.lower() in {"vertex", "point", "v"} or "vertex" in elem.tag.lower()
    ]
    for vertex in vertex_nodes:
        point = _vector_from_attributes(vertex)
        if point is not None:
            points.append(point)
    return points


def _extract_faces(node: ET.Element) -> tuple[list[int], list[int]]:
    counts: list[int] = []
    indices: list[int] = []
    face_nodes = [
        elem for elem in node.iter()
        if elem.tag.lower() in {"face", "triangle", "polygon"} or "face" in elem.tag.lower()
    ]
    for face in face_nodes:
        raw = (
            face.attrib.get("indices")
            or face.attrib.get("verts")
            or face.text
            or ""
        )
        ints = [int(part) for part in raw.replace(",", " ").split() if part.strip().lstrip("-").isdigit()]
        if ints:
            counts.append(len(ints))
            indices.extend(ints)
    return counts, indices


def _extract_skeleton(root: ET.Element) -> list[Joint]:
    bones = _extract_bones(root)
    if bones:
        return bones

    joints: list[Joint] = []
    for elem in root.iter():
        tag = elem.tag.lower()
        if tag in {"joint", "bone"} or "joint" in tag or "bone" in tag:
            name = elem.attrib.get("name") or elem.attrib.get("id")
            if not name:
                continue
            parent = elem.attrib.get("parent")
            bind_translate = _vector_from_attributes(elem) or Vector3(0.0, 0.0, 0.0)
            joints.append(Joint(name=name, parent=parent, bind_translate=bind_translate))
    return _dedupe_joints(joints)


def _extract_bones(root: ET.Element) -> list[Joint]:
    joints: list[Joint] = []
    bone_nodes = root.findall(".//Bones/Bone")
    if not bone_nodes:
        return joints

    for bone in bone_nodes:
        bone_id = bone.attrib.get("ID")
        if bone_id is None:
            continue
        bone_name = "root" if bone_id == "0" else f"bone_{int(bone_id):03d}"
        parent_id = bone.attrib.get("ParentID")
        parent_name = None
        if parent_id not in {None, "", "-1"}:
            parent_name = "root" if parent_id == "0" else f"bone_{int(parent_id):03d}"

        bind_translate = Vector3(
            _find_float(bone, ("EndX",), default=0.0) or 0.0,
            _find_float(bone, ("EndY",), default=0.0) or 0.0,
            _find_float(bone, ("EndZ",), default=0.0) or 0.0,
        )
        joints.append(Joint(name=bone_name, parent=parent_name, bind_translate=bind_translate))
    return joints


def _dedupe_joints(joints: list[Joint]) -> list[Joint]:
    seen: dict[str, Joint] = {}
    for joint in joints:
        seen[joint.name] = joint
    return [seen[name] for name in sorted(seen.keys())]


def _extract_leaf_references(root: ET.Element, skeleton: tuple[Joint, ...]) -> list[LeafReference]:
    packed_leaves = _extract_packed_leaf_references(root, skeleton)
    if packed_leaves:
        return packed_leaves

    default_joint = skeleton[0].name if skeleton else "root"
    leaves: list[LeafReference] = []
    for elem in root.iter():
        tag = elem.tag.lower()
        if "leaf" not in tag:
            continue
        if tag in {"leafreferences", "leaves", "leafcontainer"}:
            continue
        is_explicit_leaf_ref = tag in {"leafreference", "leafref"} or "leafreference" in tag
        is_reference_marked = elem.attrib.get("kind", "").lower() == "reference"
        if not is_explicit_leaf_ref and not is_reference_marked:
            continue
        position = _vector_from_attributes(elem) or Vector3(0.0, 0.0, 0.0)
        orientation = _quaternion_from_attributes(elem)
        scale = _scale_from_attributes(elem)
        name = elem.attrib.get("name") or elem.attrib.get("id") or f"LeafRef_{len(leaves)}"
        prototype_key = elem.attrib.get("prototype") or elem.attrib.get("mesh") or "LeafPrototype"
        bind_joint = elem.attrib.get("joint") or elem.attrib.get("bone") or default_joint
        leaves.append(
            LeafReference(
                name=name,
                prototype_key=prototype_key,
                position=position,
                orientation=orientation,
                scale=scale,
                bind_joint=bind_joint,
            )
        )
    return leaves


def _extract_packed_leaf_references(root: ET.Element, skeleton: tuple[Joint, ...]) -> list[LeafReference]:
    leaf_ref_node = root.find(".//LeafReferences")
    if leaf_ref_node is None:
        return []

    xs = _read_float_list(leaf_ref_node.findtext("X"))
    ys = _read_float_list(leaf_ref_node.findtext("Y"))
    zs = _read_float_list(leaf_ref_node.findtext("Z"))
    scales = _read_float_list(leaf_ref_node.findtext("Scale"))
    axis_x = _read_float_list(leaf_ref_node.findtext("RotAxisX"))
    axis_y = _read_float_list(leaf_ref_node.findtext("RotAxisY"))
    axis_z = _read_float_list(leaf_ref_node.findtext("RotAxisZ"))
    angles = _read_float_list(leaf_ref_node.findtext("RotAngle"))
    mesh_ids = _read_int_list(leaf_ref_node.findtext("MeshID"))

    count = min(len(xs), len(ys), len(zs))
    if count == 0:
        return []

    mesh_lookup = _extract_mesh_library(root)
    bones = root.findall(".//Bones/Bone")
    leaves: list[LeafReference] = []
    for index in range(count):
        position = Vector3(xs[index], ys[index], zs[index])
        uniform_scale = scales[index] if index < len(scales) else 1.0
        orientation = _quaternion_from_axis_angle(
            axis_x[index] if index < len(axis_x) else 0.0,
            axis_y[index] if index < len(axis_y) else 0.0,
            axis_z[index] if index < len(axis_z) else 1.0,
            angles[index] if index < len(angles) else 0.0,
        )
        mesh_id = mesh_ids[index] if index < len(mesh_ids) else 0
        prototype_key = mesh_lookup.get(mesh_id, f"Mesh_{mesh_id}")
        bind_joint = _find_nearest_bone_name(position, bones)
        if bind_joint is None:
            bind_joint = skeleton[0].name if skeleton else "root"

        leaves.append(
            LeafReference(
                name=f"LeafRef_{index:04d}",
                prototype_key=prototype_key,
                position=position,
                orientation=orientation,
                scale=Vector3(uniform_scale, uniform_scale, uniform_scale),
                bind_joint=bind_joint,
            )
        )
    return leaves


def _extract_mesh_library(root: ET.Element) -> dict[int, str]:
    mesh_lookup: dict[int, str] = {}
    for mesh in root.findall(".//Meshes/Mesh"):
        mesh_id = mesh.attrib.get("ID")
        if mesh_id is None:
            continue
        mesh_lookup[int(mesh_id)] = mesh.attrib.get("Name", f"Mesh_{mesh_id}")
    return mesh_lookup


def _vector_from_attributes(elem: ET.Element) -> Vector3 | None:
    x = _find_float(elem, ("x", "tx", "px"))
    y = _find_float(elem, ("y", "ty", "py"))
    z = _find_float(elem, ("z", "tz", "pz"))
    if x is None or y is None or z is None:
        return None
    return Vector3(x, y, z)


def _quaternion_from_attributes(elem: ET.Element) -> Quaternion:
    return Quaternion(
        real=_find_float(elem, ("qw", "w"), default=1.0),
        i=_find_float(elem, ("qx", "i"), default=0.0),
        j=_find_float(elem, ("qy", "j"), default=0.0),
        k=_find_float(elem, ("qz", "k"), default=0.0),
    )


def _scale_from_attributes(elem: ET.Element) -> Vector3:
    uniform = _find_float(elem, ("scale", "s"))
    if uniform is not None:
        return Vector3(uniform, uniform, uniform)
    return Vector3(
        _find_float(elem, ("sx",), default=1.0),
        _find_float(elem, ("sy",), default=1.0),
        _find_float(elem, ("sz",), default=1.0),
    )


def _find_float(elem: ET.Element, names: tuple[str, ...], default: float | None = None) -> float | None:
    for name in names:
        if name in elem.attrib:
            try:
                return float(elem.attrib[name])
            except ValueError:
                return default
    return default


def _extract_packed_points(node: ET.Element) -> list[Vector3]:
    xs = _read_float_list(node.findtext("X"))
    ys = _read_float_list(node.findtext("Y"))
    zs = _read_float_list(node.findtext("Z"))
    count = min(len(xs), len(ys), len(zs))
    return [Vector3(xs[index], ys[index], zs[index]) for index in range(count)]


def _extract_packed_triangles(node: ET.Element) -> tuple[list[int], list[int]]:
    indices = _read_int_list(node.findtext("PointIndices") or node.findtext("VertexIndices") or node.findtext("TriangleIndices"))
    if not indices:
        return [], []
    if len(indices) % 3 != 0:
        indices = indices[: len(indices) - (len(indices) % 3)]
    counts = [3] * (len(indices) // 3)
    return counts, indices


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


def _find_nearest_bone_name(position: Vector3, bones: list[ET.Element]) -> str | None:
    nearest_name: str | None = None
    nearest_distance = float("inf")
    for bone in bones:
        bone_id = bone.attrib.get("ID")
        if bone_id is None:
            continue
        endpoint = Vector3(
            _find_float(bone, ("EndX",), default=0.0) or 0.0,
            _find_float(bone, ("EndY",), default=0.0) or 0.0,
            _find_float(bone, ("EndZ",), default=0.0) or 0.0,
        )
        distance = (
            (position.x - endpoint.x) ** 2
            + (position.y - endpoint.y) ** 2
            + (position.z - endpoint.z) ** 2
        )
        if distance < nearest_distance:
            nearest_distance = distance
            nearest_name = "root" if bone_id == "0" else f"bone_{int(bone_id):03d}"
    return nearest_name

