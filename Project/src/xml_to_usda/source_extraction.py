"""SpeedTree source interpretation shared by canonical and Proxy projections.

Decode geometry, skinning and Repeated Part placement without choosing prototype
identity, projection composition, cache policy or an authoring mode. Surface
attributes are optional because Proxy intentionally needs geometry/skinning only.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from .models import (
    Color4,
    InstanceBinding,
    Joint,
    Matrix4d,
    MeshData,
    MeshLibraryEntry,
    MeshSection,
    Quaternion,
    RepeatedPartInstance,
    Vector2,
    Vector3,
)
from .skeleton_rules import joint_name_from_bone_id, parse_generator_label
from .skeleton_processing import orient_skeleton_x
from .source_transform import SourceTransform

if TYPE_CHECKING:
    from .xml_reader import SourceNodeIndex


@dataclass(frozen=True)
class SourceBoneSection:
    source_id: int
    parent_id: int | None
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    radius: float | None


@dataclass(frozen=True)
class SourceSpineSection:
    source_id: int
    parent_id: int | None
    samples: tuple[tuple[float, float, float, float], ...]


@dataclass(frozen=True)
class SourceStructure:
    """One source snapshot; consumers retain their own fallback policies."""

    _nodes: SourceNodeIndex
    _transform: SourceTransform

    def authored_skeleton(self) -> tuple[Joint, ...]:
        return extract_authored_wind_joints(self._nodes.bones)

    def bones(self, *, skip_invalid: bool = False) -> tuple[SourceBoneSection, ...]:
        sections = []
        for node in self._nodes.bones:
            try:
                start = self._transform.point_to_stage(_structure_point(node, "Start"))
                end = self._transform.point_to_stage(_structure_point(node, "End"))
                radius = node.get("Radius")
                sections.append(SourceBoneSection(
                    int(node.attrib["ID"]), _structure_parent(node),
                    (start.x, start.y, start.z), (end.x, end.y, end.z),
                    float(radius) * self._transform.linear_scale if radius is not None else None,
                ))
            except (KeyError, ValueError) as exc:
                if not skip_invalid:
                    raise ValueError(f"Bone {node.get('ID', '<missing>')}: {exc}") from exc
        return tuple(sections)

    def spines(self) -> tuple[SourceSpineSection, ...]:
        spine_objects = [(obj, spine) for obj in self._nodes.objects if (spine := obj.find("Spine")) is not None]
        if not spine_objects:
            raise ValueError("No Spine curves in the XML.")
        try:
            spine_ids = {int(obj.attrib["ID"]) for obj, _ in spine_objects}
            containers = {
                int(obj.attrib["ID"]) for obj in self._nodes.objects
                if "ID" in obj.attrib and _structure_parent(obj) is None and obj.find("Points") is None
            }
        except (KeyError, ValueError) as exc:
            raise ValueError(f"Invalid object hierarchy: {exc}") from exc
        sections = []
        for obj, spine in spine_objects:
            try:
                parent = _structure_parent(obj)
                if parent is not None and parent not in spine_ids:
                    if parent not in containers:
                        raise ValueError(f"parent object {parent} has no Spine")
                    parent = None
                columns = [list(map(float, (spine.findtext(key) or "").split())) for key in ("X", "Y", "Z", "Radius")]
                if len(columns[0]) < 2 or len({len(col) for col in columns}) != 1:
                    raise ValueError("Spine point and radius counts do not match or have fewer than two samples")
                if int(spine.get("Count", len(columns[0]))) != len(columns[0]):
                    raise ValueError("Spine Count does not match its samples")
                origin = _structure_point(obj, "Abs")
                samples = []
                for x, y, z, radius in zip(*columns, strict=True):
                    p = self._transform.point_components_to_stage(x + origin.x, y + origin.y, z + origin.z)
                    samples.append((p.x, p.y, p.z, radius * self._transform.linear_scale))
                sections.append(SourceSpineSection(int(obj.attrib["ID"]), parent, tuple(samples)))
            except (KeyError, ValueError) as exc:
                raise ValueError(f"Object {obj.get('ID', '<missing>')}: {exc}") from exc
        return tuple(sections)


def _structure_point(node: ET.Element, prefix: str) -> Vector3:
    return Vector3(*(float(node.attrib[f"{prefix}{axis}"]) for axis in "XYZ"))


def _structure_parent(node: ET.Element) -> int | None:
    value = int(node.get("ParentID", "-1"))
    return value if value >= 0 else None


def extract_authored_wind_joints(elements) -> tuple[Joint, ...]:
    joints: list[Joint] = []
    for elem in elements:
        if elem.tag != "Bone":
            continue
        raw_bone_id = elem.attrib.get("ID")
        if raw_bone_id is None or not raw_bone_id.lstrip("-").isdigit():
            continue
        bone_id = int(raw_bone_id)
        raw_parent_id = elem.attrib.get("ParentID")
        parsed_parent_id = None
        if raw_parent_id not in {None, "", "-1"} and raw_parent_id.lstrip("-").isdigit():
            parsed_parent_id = int(raw_parent_id)
        generator_label, generator_level = parse_generator_label(elem.attrib.get("Generator"), bone_id)
        joints.append(Joint(
            name=joint_name_from_bone_id(bone_id),
            source_id=bone_id,
            parent=joint_name_from_bone_id(parsed_parent_id) if parsed_parent_id is not None else None,
            generator_label=generator_label,
            generator_level=generator_level,
        ))
    return tuple(joints)


@dataclass(frozen=True)
class _LeafReferencePayload:
    xs: list[float]
    ys: list[float]
    zs: list[float]
    scales: list[float]
    axis_x: list[float]
    axis_y: list[float]
    axis_z: list[float]
    angles: list[float]
    mesh_ids: list[int]
    mesh_lods: list[int]
    bone_ids: list[int]
    source_material_id: int | None
    count: int


def normalize_source_skeleton(
    bone_nodes: tuple[ET.Element, ...], source_transform: SourceTransform,
    messages: list[str] | None = None,
) -> tuple[Joint, ...]:
    """Normalize the authored skeleton without constructing mesh payloads."""
    return orient_skeleton_x(tuple(_extract_skeleton(
        bone_nodes, messages if messages is not None else [], source_transform)))


def count_source_part_instances(
    object_nodes: tuple[ET.Element, ...], source_transform: SourceTransform,
) -> int:
    """Count instances with canonical array semantics, without building transforms."""
    count = 0
    for obj in object_nodes:
        leaf_refs = tuple(child for child in obj if child.tag == "LeafReferences")
        if not leaf_refs:
            continue
        # Full normalization rejects ambiguous placement before building parts;
        # opening must retain that structural guard even without geometry.
        _leaf_reference_position_offset(
            obj, source_transform,
            has_mesh_payload=obj.find("Points") is not None and obj.find("Triangles") is not None,
        )
        count += sum(_read_leaf_reference_payload(
            obj, child, [], set(), source_transform).count for child in leaf_refs)
    return count


def validate_source_part_hosts(object_nodes, source_transform: SourceTransform) -> None:
    """Validate placement space without expanding the native instance-count projection."""
    for obj in object_nodes:
        if obj.find("LeafReferences") is not None:
            _leaf_reference_position_offset(
                obj, source_transform,
                has_mesh_payload=obj.find("Points") is not None and obj.find("Triangles") is not None,
            )


def extract_repeated_parts(
    obj: ET.Element,
    leaf_ref_nodes: tuple[ET.Element, ...],
    messages: list[str],
    source_transform: SourceTransform,
    material_ids: set[int],
    *,
    first_instance_index: int,
    has_mesh_payload: bool,
    abs_translate: Vector3 | None = None,
) -> list[RepeatedPartInstance]:
    """Decode one host in traversal order, retaining global instance names."""
    if not leaf_ref_nodes:
        return []
    offset = _leaf_reference_position_offset(
        obj, source_transform, has_mesh_payload=has_mesh_payload, abs_translate=abs_translate,
    )
    parts: list[RepeatedPartInstance] = []
    for node in leaf_ref_nodes:
        payload = _read_leaf_reference_payload(obj, node, messages, material_ids, source_transform)
        for index in range(payload.count):
            parts.append(_build_leaf_reference_instance(
                payload, index, name=f"AssemblyPart_{first_instance_index + len(parts):04d}",
                source_object_id=obj.attrib.get("ID"), source_transform=source_transform,
                position_offset=offset,
            ))
    return parts


def extract_object_mesh(
    name: str,
    points_node: ET.Element | None,
    triangles_nodes: tuple[ET.Element, ...],
    vertices_node: ET.Element | None,
    joint_index_by_source_id: dict[int, int],
    messages: list[str],
    source_transform: SourceTransform,
    material_ids: set[int],
    *,
    include_surface_attributes: bool = True,
) -> MeshData | None:
    if points_node is None or not triangles_nodes:
        return None
    points = _extract_packed_points(points_node, f"{name}.points", messages, source_transform)
    face_counts, face_indices, vertex_indices, sections = _extract_packed_triangle_blocks(
        triangles_nodes,
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
    if not include_surface_attributes:
        return _build_mesh_from_faces(
            name, points, face_counts, face_indices, sections,
            joint_indices=joint_indices, joint_weights=joint_weights,
        )
    uv_coords = _extract_face_varying_uvs(
        vertices_node,
        vertex_indices,
        face_indices,
        f"{name}.vertices",
        messages,
        allow_point_index_fallback=False,
    )
    normals = _extract_face_varying_normals(
        vertices_node,
        vertex_indices,
        face_indices,
        f"{name}.vertices",
        messages,
        source_transform,
    )
    return _build_mesh_from_faces(
        name,
        points,
        face_counts,
        face_indices,
        sections,
        uv_coords,
        normals=normals,
        joint_indices=joint_indices,
        joint_weights=joint_weights,
    )


def extract_prototype_mesh(
    name: str,
    points_node: ET.Element,
    lod_node: ET.Element,
    messages: list[str],
    source_transform: SourceTransform,
    material_ids: set[int],
    *,
    include_surface_attributes: bool = True,
) -> MeshData | None:
    points = _extract_packed_points(points_node, f"{name}.points", messages, source_transform)
    face_counts, face_indices, sections = _extract_lod_faces(lod_node, name, messages, material_ids)
    if not points or not face_counts or not face_indices:
        return None
    if not include_surface_attributes:
        return _build_mesh_from_faces(name, points, face_counts, face_indices, sections)
    vertex_indices = _extract_lod_vertex_indices(lod_node, face_indices, name, messages)
    uv_coords = _extract_face_varying_uvs(
        points_node,
        vertex_indices,
        face_indices,
        f"{name}.vertices",
        messages,
        allow_point_index_fallback=True,
    )
    normals = _extract_face_varying_normals(
        points_node,
        vertex_indices,
        face_indices,
        f"{name}.vertices",
        messages,
        source_transform,
        allow_point_index_fallback=True,
    )
    vertex_colors = _extract_vertex_colors(
        points_node,
        f"{name}.vertices",
        messages,
    )
    return _build_mesh_from_faces(
        name,
        points,
        face_counts,
        face_indices,
        sections,
        uv_coords,
        normals=normals,
        vertex_colors=vertex_colors,
    )


def _build_mesh_from_faces(
    name: str,
    points: list[Vector3],
    face_counts: list[int],
    face_indices: list[int],
    sections: tuple[MeshSection, ...],
    uv_coords: list[Vector2] | None = None,
    normals: list[Vector3] | None = None,
    vertex_colors: list[Color4] | None = None,
    joint_indices: list[int] | None = None,
    joint_weights: list[float] | None = None,
) -> MeshData:
    return MeshData(
        name=name,
        points=tuple(points),
        face_vertex_counts=tuple(face_counts),
        face_vertex_indices=tuple(face_indices),
        normals=tuple(normals or ()),
        uv_coords=tuple(uv_coords or ()),
        vertex_colors=tuple(vertex_colors or ()),
        sections=sections,
        skel_joint_indices=tuple(joint_indices or ()),
        skel_joint_weights=tuple(joint_weights or ()),
        skel_element_size=1 if joint_indices else 0,
    )


def select_primary_lod(mesh: ET.Element) -> ET.Element | None:
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


def _extract_skeleton(bones: tuple[ET.Element, ...], messages: list[str], source_transform: SourceTransform) -> list[Joint]:
    if not bones:
        return []

    raw_bones: list[tuple[int, int | None, Vector3, Vector3 | None, str | None, int | None]] = []
    for bone in bones:
        bone_id = bone.attrib.get("ID")
        if bone_id is None or not bone_id.lstrip("-").isdigit():
            continue
        parent_id = bone.attrib.get("ParentID")
        start_x = _find_float(bone, ("StartX",), default=None)
        start_y = _find_float(bone, ("StartY",), default=None)
        start_z = _find_float(bone, ("StartZ",), default=None)
        end_x = _find_float(bone, ("EndX",), default=None)
        end_y = _find_float(bone, ("EndY",), default=None)
        end_z = _find_float(bone, ("EndZ",), default=None)
        if start_x is None or start_y is None or start_z is None:
            messages.append(
                f"missing_skeleton_transform: bone {bone_id} is missing StartX/StartY/StartZ required for rest pose authoring"
            )
            continue
        parsed_parent_id = None
        if parent_id not in {None, "", "-1"} and parent_id.lstrip("-").isdigit():
            parsed_parent_id = int(parent_id)
        generator_label, generator_level = parse_generator_label(bone.attrib.get("Generator"), int(bone_id))
        end = (
            source_transform.point_components_to_stage(end_x, end_y, end_z)
            if end_x is not None and end_y is not None and end_z is not None
            else None
        )
        raw_bones.append(
            (
                int(bone_id),
                parsed_parent_id,
                source_transform.point_components_to_stage(start_x, start_y, start_z),
                end,
                generator_label,
                generator_level,
            )
        )

    start_by_id = {bone_id: start for bone_id, _, start, _, _, _ in raw_bones}
    child_starts_by_parent: dict[int, list[Vector3]] = defaultdict(list)
    for _bone_id, parent_id, start, _end, _label, _level in raw_bones:
        if parent_id is not None:
            child_starts_by_parent[parent_id].append(start)
    joints: list[Joint] = []
    for bone_id, parsed_parent_id, start, end, generator_label, generator_level in raw_bones:
        if end is None:
            direction_start = start_by_id.get(parsed_parent_id) if parsed_parent_id is not None else None
            if direction_start is None:
                direction_start = next((child for child in child_starts_by_parent.get(bone_id, ()) if child != start), None)
                inferred_end = direction_start
            else:
                inferred_end = Vector3(
                    start.x + start.x - direction_start.x,
                    start.y + start.y - direction_start.y,
                    start.z + start.z - direction_start.z,
                )
            if inferred_end is not None and inferred_end != start:
                end = inferred_end
                messages.append(f"inferred_skeleton_end: bone {bone_id} has no EndX/EndY/EndZ; direction was inferred from hierarchy")
            else:
                messages.append(f"missing_skeleton_orientation: bone {bone_id} has no usable direction for +X orientation")
        parent = joint_name_from_bone_id(parsed_parent_id) if parsed_parent_id is not None else None
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
                name=joint_name_from_bone_id(bone_id),
                source_id=bone_id,
                parent=parent,
                generator_label=generator_label,
                generator_level=generator_level,
                bind_transform=Matrix4d.from_translation(start),
                rest_transform=Matrix4d.from_translation(rest_translate),
                bind_end_transform=Matrix4d.from_translation(end) if end is not None else None,
            )
        )
    return joints


def _read_leaf_reference_payload(
    obj: ET.Element,
    leaf_ref_node: ET.Element,
    messages: list[str],
    material_ids: set[int],
    source_transform: SourceTransform,
) -> _LeafReferencePayload:
    context = f"LeafReferences[{obj.attrib.get('Name', obj.attrib.get('ID', '?'))}]"
    xs_raw = ys_raw = zs_raw = None
    scales_raw = axis_x_raw = axis_y_raw = axis_z_raw = None
    angles_raw = mesh_ids_raw = mesh_lods_raw = bone_ids_raw = None
    for child in leaf_ref_node:
        tag = child.tag
        text = child.text
        if tag == "X":
            xs_raw = text
        elif tag == "Y":
            ys_raw = text
        elif tag == "Z":
            zs_raw = text
        elif tag == "Scale":
            scales_raw = text
        elif tag == "RotAxisX":
            axis_x_raw = text
        elif tag == "RotAxisY":
            axis_y_raw = text
        elif tag == "RotAxisZ":
            axis_z_raw = text
        elif tag == "RotAngle":
            angles_raw = text
        elif tag == "MeshID":
            mesh_ids_raw = text
        elif tag == "MeshLOD":
            mesh_lods_raw = text
        elif tag == "BoneID":
            bone_ids_raw = text

    xs = read_float_list(xs_raw)
    ys = read_float_list(ys_raw)
    zs = read_float_list(zs_raw)
    scales = read_float_list(scales_raw)
    axis_x = read_float_list(axis_x_raw)
    axis_y = read_float_list(axis_y_raw)
    axis_z = read_float_list(axis_z_raw)
    angles = read_float_list(angles_raw)
    mesh_ids = read_int_list(mesh_ids_raw)
    mesh_lods = read_int_list(mesh_lods_raw)
    bone_ids = read_int_list(bone_ids_raw)
    source_material_id = _read_material_id(leaf_ref_node, context, messages, material_ids)
    count = consistent_count(
        context,
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
    return _LeafReferencePayload(
        xs=xs,
        ys=ys,
        zs=zs,
        scales=scales,
        axis_x=axis_x,
        axis_y=axis_y,
        axis_z=axis_z,
        angles=angles,
        mesh_ids=mesh_ids,
        mesh_lods=mesh_lods,
        bone_ids=bone_ids,
        source_material_id=source_material_id,
        count=count,
    )


def _build_leaf_reference_instance(
    payload: _LeafReferencePayload,
    index: int,
    *,
    name: str,
    source_object_id: str | None,
    source_transform: SourceTransform,
    position_offset: Vector3,
) -> RepeatedPartInstance:
    source_bone_id = (
        _normalize_source_bone_id(payload.bone_ids[index])
        if index < len(payload.bone_ids)
        else None
    )
    source_mesh_id = payload.mesh_ids[index] if index < len(payload.mesh_ids) else None
    prototype_key = f"Mesh_{source_mesh_id}" if source_mesh_id is not None else "LeafPrototype"
    uniform_scale = payload.scales[index] if index < len(payload.scales) else 1.0
    local_position = source_transform.point_components_to_stage(
        payload.xs[index],
        payload.ys[index],
        payload.zs[index],
    )
    return RepeatedPartInstance(
        name=name,
        prototype_key=prototype_key,
        position=Vector3(
            local_position.x + position_offset.x,
            local_position.y + position_offset.y,
            local_position.z + position_offset.z,
        ),
        orientation=_leaf_reference_orientation_to_stage(
            source_transform,
            Vector3(
                payload.axis_x[index] if index < len(payload.axis_x) else 0.0,
                payload.axis_y[index] if index < len(payload.axis_y) else 0.0,
                payload.axis_z[index] if index < len(payload.axis_z) else 1.0,
            ),
            payload.angles[index] if index < len(payload.angles) else 0.0,
        ),
        scale=Vector3(uniform_scale, uniform_scale, uniform_scale),
        binding=binding_from_bone_id(source_bone_id),
        source_object_id=source_object_id,
        source_mesh_id=source_mesh_id,
        source_material_id=payload.source_material_id,
        source_bone_ids=(source_bone_id,) if source_bone_id is not None else (),
        mesh_lod=payload.mesh_lods[index] if index < len(payload.mesh_lods) else None,
    )


def object_abs_translate(obj: ET.Element, source_transform: SourceTransform) -> Vector3:
    return source_transform.point_components_to_stage(
        parse_float_value(obj.attrib.get("AbsX")) or 0.0,
        parse_float_value(obj.attrib.get("AbsY")) or 0.0,
        parse_float_value(obj.attrib.get("AbsZ")) or 0.0,
    )


def _leaf_reference_position_offset(
    obj: ET.Element,
    source_transform: SourceTransform,
    *,
    has_mesh_payload: bool,
    abs_translate: Vector3 | None = None,
) -> Vector3:
    offset = abs_translate if abs_translate is not None else object_abs_translate(obj, source_transform)
    if offset == Vector3(0.0, 0.0, 0.0):
        return offset
    if has_mesh_payload:
        return offset
    object_name = obj.attrib.get("Name", obj.attrib.get("ID", "?"))
    raise ValueError(
        f"LeafReferences[{object_name}] has a non-zero Object Abs transform but no sibling "
        "Points/Triangles payload; its position space cannot be determined safely."
    )


def _leaf_reference_orientation_to_stage(
    source_transform: SourceTransform,
    axis: Vector3,
    angle_degrees: float,
) -> Quaternion:
    # Axis remaps into stage space, but the authored rotation sense stays the same.
    stage_axis = source_transform.axis_to_stage(axis)
    return _quaternion_from_axis_angle(stage_axis, angle_degrees)


def mesh_with_original_scale(entry: MeshLibraryEntry) -> MeshData:
    if entry.original_scale is None or entry.original_scale == 1.0:
        return entry.mesh
    scale_factor = entry.original_scale
    if not isinstance(scale_factor, (int, float)):
        raise TypeError(
            f"MeshLibraryEntry {entry.name} (mesh_id={entry.mesh_id}) has invalid original_scale "
            f"{scale_factor!r} of type {type(scale_factor).__name__}."
        )
    return replace(
        entry.mesh,
        points=tuple(
            Vector3(
                _scaled_point_component(point, "x", scale_factor, entry),
                _scaled_point_component(point, "y", scale_factor, entry),
                _scaled_point_component(point, "z", scale_factor, entry),
            )
            for point in entry.mesh.points
        ),
    )


def _scaled_point_component(point, axis_name: str, scale_factor: float, entry: MeshLibraryEntry) -> float:
    if not isinstance(point, Vector3):
        raise TypeError(
            f"MeshLibraryEntry {entry.name} (mesh_id={entry.mesh_id}) contains invalid point payload "
            f"{point!r} of type {type(point).__name__}; expected Vector3 before applying original_scale."
        )
    value = getattr(point, axis_name)
    if not isinstance(value, (int, float)):
        raise TypeError(
            f"MeshLibraryEntry {entry.name} (mesh_id={entry.mesh_id}) contains invalid point.{axis_name} "
            f"{value!r} of type {type(value).__name__}; expected numeric coordinate before applying original_scale."
        )
    return value * scale_factor


def binding_from_bone_id(source_bone_id: int | None) -> InstanceBinding:
    if source_bone_id is None:
        return InstanceBinding(joint_tokens=(), weights=())
    token = joint_name_from_bone_id(source_bone_id)
    return InstanceBinding(joint_tokens=(token,), weights=(1.0,))


def _normalize_source_bone_id(source_bone_id: int) -> int:
    return 0 if source_bone_id == -1 else source_bone_id


def _find_float(elem: ET.Element, names: tuple[str, ...], default: float | None = None) -> float | None:
    for name in names:
        if name in elem.attrib:
            value = parse_float_value(elem.attrib[name])
            return value if value is not None else default
    return default


def _extract_packed_points(
    node: ET.Element,
    context: str,
    messages: list[str],
    source_transform: SourceTransform,
) -> list[Vector3]:
    xs = read_float_list(node.findtext("X"))
    ys = read_float_list(node.findtext("Y"))
    zs = read_float_list(node.findtext("Z"))
    count = consistent_count(context, messages, required=[("X", xs), ("Y", ys), ("Z", zs)])
    return source_transform.points_components_to_stage(xs[:count], ys[:count], zs[:count])


def _extract_packed_normals(
    node: ET.Element,
    context: str,
    messages: list[str],
    source_transform: SourceTransform,
) -> list[Vector3]:
    xs = read_float_list(node.findtext("NormalX"))
    ys = read_float_list(node.findtext("NormalY"))
    zs = read_float_list(node.findtext("NormalZ"))
    if not xs and not ys and not zs:
        return []
    count = consistent_count(
        f"{context}.normals",
        messages,
        required=[("NormalX", xs), ("NormalY", ys), ("NormalZ", zs)],
    )
    return source_transform.axes_components_to_stage(xs[:count], ys[:count], zs[:count])


def _extract_packed_triangles(
    node: ET.Element,
    context: str,
    messages: list[str],
    material_ids: set[int],
) -> tuple[list[int], list[int], list[int], tuple[MeshSection, ...]]:
    point_indices = read_int_list(node.findtext("PointIndices") or node.findtext("TriangleIndices"))
    vertex_indices = read_int_list(node.findtext("VertexIndices"))
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
    sections = single_material_sections(material_id, len(counts))
    return counts, indices, vertex_indices, sections


def _extract_packed_triangle_blocks(
    nodes: tuple[ET.Element, ...],
    context: str,
    messages: list[str],
    material_ids: set[int],
) -> tuple[list[int], list[int], list[int], tuple[MeshSection, ...]]:
    face_counts: list[int] = []
    point_indices: list[int] = []
    vertex_indices: list[int] = []
    sections_by_material: dict[int, list[int]] = defaultdict(list)
    face_offset = 0

    for node in nodes:
        counts, block_point_indices, block_vertex_indices, sections = _extract_packed_triangles(
            node,
            context,
            messages,
            material_ids,
        )
        if not counts or not block_point_indices:
            continue
        face_counts.extend(counts)
        point_indices.extend(block_point_indices)
        vertex_indices.extend(block_vertex_indices)
        for section in sections:
            sections_by_material[section.material_id].extend(
                face_offset + face_index for face_index in section.face_indices
            )
        face_offset += len(counts)

    return face_counts, point_indices, vertex_indices, ordered_sections(sections_by_material)


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
        triangle_indices = read_int_list(triangles_node.findtext("PointIndices") or triangles_node.findtext("TriangleIndices"))
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

    quad_indices = read_int_list(node.findtext("QuadIndices"))
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
        triangle_indices = read_int_list(node.findtext("TriangleIndices"))
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

    return face_counts, face_indices, ordered_sections(sections_by_material)


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
    source_bone_ids = read_int_list(vertices_node.findtext("BoneID"))
    if not source_bone_ids:
        messages.append(f"packed_array_error: {context} missing BoneID payload for skeletal base mesh")
        return [], []

    point_index_count = len(point_indices)
    bone_count = len(source_bone_ids)
    joint_index_get = joint_index_by_source_id.get

    if vertex_indices and len(vertex_indices) != point_index_count:
        messages.append(
            f"packed_array_error: {context} point index count {point_index_count} does not match vertex index count {len(vertex_indices)}"
        )
    point_vertex_pairs = zip(point_indices, vertex_indices or point_indices, strict=False)

    resolved_joint_indices = [0] * point_count
    resolved_joint_weights = [1.0] * point_count
    assigned_points = bytearray(point_count)

    for point_index, vertex_index in point_vertex_pairs:
        if point_index < 0 or point_index >= point_count:
            messages.append(f"packed_array_error: {context} point index {point_index} exceeds point count {point_count}")
            continue
        if vertex_index < 0 or vertex_index >= bone_count:
            messages.append(f"packed_array_error: {context} vertex index {vertex_index} exceeds BoneID count {bone_count}")
            continue
        source_bone_id = _normalize_source_bone_id(source_bone_ids[vertex_index])
        if source_bone_id < 0:
            messages.append(f"packed_array_error: {context} BoneID {source_bone_id} is not a valid skeletal binding")
            continue
        joint_index = joint_index_get(source_bone_id)
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
        assigned_points[point_index] = 1

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
    u_coords = read_float_list(vertices_node.findtext("TexcoordU"))
    v_coords = read_float_list(vertices_node.findtext("TexcoordV"))
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
    face_vertex_count = len(face_indices)
    if vertex_indices:
        authored_indices = vertex_indices
    elif allow_point_index_fallback:
        authored_indices = face_indices
    else:
        if uv_count != face_vertex_count:
            messages.append(
                f"packed_array_error: {context} UV count {uv_count} requires VertexIndices for face-varying authoring with {face_vertex_count} face vertices"
            )
            return []
        authored_indices = range(uv_count)
    authored_count = len(authored_indices)
    if authored_count != face_vertex_count:
        messages.append(
            f"packed_array_error: {context} vertex index count {authored_count} does not match face vertex count {face_vertex_count} for UV authoring"
        )
    limit = min(authored_count, face_vertex_count)
    source_uvs = [Vector2(u, v) for u, v in zip(u_coords, v_coords)]
    if isinstance(authored_indices, range):
        return source_uvs
    if limit == face_vertex_count and authored_indices:
        if min(authored_indices) >= 0 and max(authored_indices) < uv_count:
            return [source_uvs[vertex_index] for vertex_index in authored_indices]
        uv_coords: list[Vector2] = []
        has_invalid_index = False
        for vertex_index in authored_indices:
            if vertex_index < 0 or vertex_index >= uv_count:
                messages.append(f"packed_array_error: {context} UV vertex index {vertex_index} exceeds texcoord count {uv_count}")
                has_invalid_index = True
                continue
            uv_coords.append(source_uvs[vertex_index])
        if not has_invalid_index:
            return uv_coords
        if len(uv_coords) != face_vertex_count:
            messages.append(
                f"packed_array_error: {context} authored UV count {len(uv_coords)} does not match face vertex count {len(face_indices)}"
            )
            return []
    uv_coords: list[Vector2] = []
    for vertex_index in authored_indices[:limit]:
        if vertex_index < 0 or vertex_index >= uv_count:
            messages.append(f"packed_array_error: {context} UV vertex index {vertex_index} exceeds texcoord count {uv_count}")
            continue
        uv_coords.append(source_uvs[vertex_index])
    if len(uv_coords) != len(face_indices):
        messages.append(
            f"packed_array_error: {context} authored UV count {len(uv_coords)} does not match face vertex count {len(face_indices)}"
        )
        return []
    return uv_coords


def _extract_face_varying_normals(
    vertices_node: ET.Element | None,
    vertex_indices: list[int],
    face_indices: list[int],
    context: str,
    messages: list[str],
    source_transform: SourceTransform,
    *,
    allow_point_index_fallback: bool = False,
) -> list[Vector3]:
    if vertices_node is None:
        return []
    source_normals = _extract_packed_normals(vertices_node, context, messages, source_transform)
    if not source_normals:
        return []
    if vertex_indices:
        authored_indices = vertex_indices
    elif allow_point_index_fallback:
        authored_indices = face_indices
    elif len(source_normals) == len(face_indices):
        authored_indices = list(range(len(source_normals)))
    else:
        messages.append(
            f"packed_array_error: {context} normal count {len(source_normals)} requires VertexIndices "
            f"for {len(face_indices)} face vertices"
        )
        return []
    if len(authored_indices) != len(face_indices):
        messages.append(
            f"packed_array_error: {context} normal index count {len(authored_indices)} does not match "
            f"face vertex count {len(face_indices)}"
        )
        return []
    if authored_indices and (min(authored_indices) < 0 or max(authored_indices) >= len(source_normals)):
        messages.append(f"packed_array_error: {context} normal vertex index exceeds normal count")
        return []
    return [source_normals[index] for index in authored_indices]


def _extract_vertex_colors(
    vertices_node: ET.Element | None,
    context: str,
    messages: list[str],
) -> list[Color4]:
    if vertices_node is None:
        return []
    red = read_float_list(vertices_node.findtext("VertexColorR"))
    green = read_float_list(vertices_node.findtext("VertexColorG"))
    blue = read_float_list(vertices_node.findtext("VertexColorB"))
    alpha = read_float_list(vertices_node.findtext("VertexColorA"))
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
        indices = read_int_list(triangles_node.findtext("VertexIndices"))
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


def single_material_sections(material_id: int | None, face_count: int) -> tuple[MeshSection, ...]:
    if material_id is None or face_count <= 0:
        return ()
    return (MeshSection(material_id=material_id, face_indices=tuple(range(face_count))),)


def ordered_sections(sections_by_material: dict[int, list[int]]) -> tuple[MeshSection, ...]:
    return tuple(
        MeshSection(material_id=material_id, face_indices=tuple(sorted(face_indices)))
        for material_id, face_indices in sorted(sections_by_material.items())
        if face_indices
    )


def consistent_count(
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


def read_float_list(raw: str | None) -> list[float]:
    if not raw:
        return []
    if "," not in raw:
        tokens = raw.split()
        if len(tokens) == 1:
            try:
                return [float(tokens[0])]
            except ValueError:
                return []
        try:
            return [float(token) for token in tokens]
        except ValueError:
            values: list[float] = []
            append = values.append
            for token in tokens:
                try:
                    append(float(token))
                except ValueError:
                    continue
            return values

    values: list[float] = []
    append = values.append
    for token in raw.split():
        if "," not in token:
            try:
                append(float(token))
            except ValueError:
                continue
            continue

        normalized = token.strip()
        if normalized.count(",") > 1 and "." not in normalized and "e" not in normalized.lower():
            for chunk in normalized.split(","):
                try:
                    append(float(chunk))
                except ValueError:
                    continue
            continue

        if "." not in normalized:
            normalized = normalized.replace(",", ".")
        try:
            append(float(normalized))
        except ValueError:
            continue
    return values


def read_int_list(raw: str | None) -> list[int]:
    if not raw:
        return []
    if "," not in raw:
        tokens = raw.split()
        if len(tokens) == 1:
            try:
                return [int(tokens[0])]
            except ValueError:
                return []
        try:
            return [int(token) for token in tokens]
        except ValueError:
            values: list[int] = []
            append = values.append
            for token in tokens:
                try:
                    append(int(token))
                except ValueError:
                    continue
            return values

    tokens = raw.replace(",", " ").split()
    try:
        return [int(token) for token in tokens]
    except ValueError:
        values: list[int] = []
        append = values.append
        for token in tokens:
            try:
                append(int(token))
            except ValueError:
                continue
        return values


def read_positive_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    value = parse_float_value(raw)
    if value is None:
        return None
    return value if math.isfinite(value) and value > 0.0 else None


def parse_float_value(raw: str | None) -> float | None:
    if raw is None:
        return None
    normalized = raw.strip()
    if not normalized:
        return None
    if "," in normalized and "." not in normalized:
        normalized = normalized.replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return None


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
