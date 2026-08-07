"""Fast source projection for Proxy Mesh generation.

Layer: application/domain boundary.

This module extracts only the source facts Proxy Mesh needs. It deliberately
does not build a full CanonicalTreeModel or resolved authoring model.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .models import (
    ExportMetadata,
    InstanceBinding,
    Joint,
    Matrix4d,
    MeshData,
    MeshLibraryEntry,
    MeshSection,
    Prototype,
    PrototypeIdentity,
    Quaternion,
    RepeatedPartInstance,
    TreeAsset,
    Vector3,
)
from .normalizer import (
    _binding_from_bone_id,
    _build_leaf_reference_instance,
    _extract_lod_faces,
    _extract_packed_points,
    _extract_packed_triangle_blocks,
    _extract_skeleton,
    _extract_vertex_skinning,
    _leaf_reference_position_offset,
    _mesh_with_original_scale,
    _object_abs_translate,
    _parse_float_value,
    _read_leaf_reference_payload,
    _select_primary_lod,
)
from .skeleton_processing import orient_skeleton_x
from .source_transform import build_source_transform
from .xml_reader import packaged_xml_parser_adapter_enabled, read_source_xml


PROXY_SOURCE_PROJECTION_CACHE_SCHEMA_VERSION = 3


@dataclass(frozen=True)
class ProxySourceProjection:
    source_path: str
    base_mesh: MeshData | None
    prototypes: tuple[Prototype, ...]
    repeated_parts: tuple[RepeatedPartInstance, ...]
    skeleton: tuple[Joint, ...] = ()


@dataclass(frozen=True)
class _ProxyObjectProjection:
    base_mesh: MeshData | None
    repeated_parts: tuple[RepeatedPartInstance, ...]


def load_proxy_source_projection(input_path: str) -> ProxySourceProjection:
    cache_path = _proxy_projection_cache_path(input_path)
    cached = _read_proxy_projection_cache(cache_path)
    if cached is not None:
        return cached
    document = read_source_xml(input_path)
    root = document.tree.getroot()
    object_nodes = tuple(root.findall(".//Object"))
    mesh_nodes = tuple(root.findall(".//Meshes/Mesh"))
    bone_nodes = tuple(root.findall(".//Bones/Bone"))
    source_transform = build_source_transform(
        root,
        _find_first_attr(root, "units"),
        _find_first_attr(root, "upAxis") or _find_first_attr(root, "up_axis"),
        mesh_nodes,
    )
    messages: list[str] = []
    material_ids: set[int] = set()
    skeleton = orient_skeleton_x(tuple(_extract_skeleton(bone_nodes, messages, source_transform)))
    joint_index_by_source_id = {
        joint.source_id: index for index, joint in enumerate(skeleton) if joint.source_id is not None
    }
    object_projection = _extract_proxy_objects(
        object_nodes,
        messages,
        source_transform,
        material_ids,
        joint_index_by_source_id,
    )
    repeated_parts = object_projection.repeated_parts
    mesh_library = _extract_proxy_mesh_library(mesh_nodes, messages, source_transform, material_ids)
    projection = ProxySourceProjection(
        source_path=document.source_path,
        base_mesh=object_projection.base_mesh,
        prototypes=_build_proxy_prototypes(repeated_parts, mesh_library),
        repeated_parts=repeated_parts,
        skeleton=skeleton,
    )
    _write_proxy_projection_cache(cache_path, projection)
    return projection


def projection_to_tree_asset(projection: ProxySourceProjection) -> TreeAsset:
    return TreeAsset(
        metadata=ExportMetadata(source_path=projection.source_path, source_version=None),
        materials=(),
        source_objects=(),
        base_mesh=projection.base_mesh,
        skeleton=projection.skeleton,
        assembly_parts=projection.repeated_parts,
        prototypes=projection.prototypes,
    )


def _extract_proxy_objects(
    object_nodes: tuple[ET.Element, ...],
    messages: list[str],
    source_transform,
    material_ids: set[int],
    joint_index_by_source_id: dict[int, int],
) -> _ProxyObjectProjection:
    merged_points: list[Vector3] = []
    merged_face_counts: list[int] = []
    merged_face_indices: list[int] = []
    merged_sections: dict[int, list[int]] = defaultdict(list)
    merged_joint_indices: list[int] = []
    merged_joint_weights: list[float] = []
    repeated_parts: list[RepeatedPartInstance] = []

    for obj in object_nodes:
        object_id = obj.attrib.get("ID")
        points_node: ET.Element | None = None
        triangles_nodes: list[ET.Element] = []
        vertices_node: ET.Element | None = None
        leaf_ref_nodes: list[ET.Element] = []
        for child in obj:
            if child.tag == "Points" and points_node is None:
                points_node = child
            elif child.tag == "Triangles":
                triangles_nodes.append(child)
            elif child.tag == "Vertices" and vertices_node is None:
                vertices_node = child
            elif child.tag == "LeafReferences":
                leaf_ref_nodes.append(child)
        if object_id is not None and points_node is not None and triangles_nodes:
            points = _extract_packed_points(points_node, f"{obj.attrib.get('Name', obj.tag)}.points", messages, source_transform)
            face_counts, face_indices, vertex_indices, sections = _extract_packed_triangle_blocks(
                tuple(triangles_nodes),
                f"{obj.attrib.get('Name', obj.tag)}.triangles",
                messages,
                material_ids,
            )
            if points and face_counts and face_indices:
                joint_indices, joint_weights = _extract_vertex_skinning(
                    vertices_node,
                    face_indices,
                    vertex_indices,
                    len(points),
                    joint_index_by_source_id,
                    f"{obj.attrib.get('Name', obj.tag)}.vertices",
                    messages,
                )
                point_offset = len(merged_points)
                face_offset = len(merged_face_counts)
                translate = _object_abs_translate(obj, source_transform)
                merged_points.extend(
                    Vector3(point.x + translate.x, point.y + translate.y, point.z + translate.z)
                    for point in points
                )
                merged_face_counts.extend(face_counts)
                merged_face_indices.extend(index + point_offset for index in face_indices)
                merged_joint_indices.extend(joint_indices)
                merged_joint_weights.extend(joint_weights)
                for section in sections:
                    merged_sections[section.material_id].extend(
                        face_offset + face_index for face_index in section.face_indices
                    )
        if not leaf_ref_nodes:
            continue
        position_offset = _leaf_reference_position_offset(
            obj,
            source_transform,
            has_mesh_payload=points_node is not None and bool(triangles_nodes),
        )
        for leaf_ref_node in leaf_ref_nodes:
            payload = _read_leaf_reference_payload(obj, leaf_ref_node, messages, material_ids, source_transform)
            if payload.count == 0:
                continue
            for index in range(payload.count):
                repeated_parts.append(
                    _build_leaf_reference_instance(
                        payload,
                        index,
                        name=f"AssemblyPart_{len(repeated_parts):04d}",
                        source_object_id=object_id,
                        source_transform=source_transform,
                        position_offset=position_offset,
                    )
                )

    base_mesh = (
        MeshData(
            name="TreeBaseMesh",
            points=tuple(merged_points),
            face_vertex_counts=tuple(merged_face_counts),
            face_vertex_indices=tuple(merged_face_indices),
            sections=_ordered_sections(merged_sections),
            skel_joint_indices=tuple(merged_joint_indices),
            skel_joint_weights=tuple(merged_joint_weights),
            skel_element_size=1 if merged_joint_indices else 0,
        )
        if merged_points and merged_face_counts and merged_face_indices
        else None
    )
    return _ProxyObjectProjection(base_mesh=base_mesh, repeated_parts=tuple(repeated_parts))


def _extract_proxy_mesh_library(
    mesh_nodes: tuple[ET.Element, ...],
    messages: list[str],
    source_transform,
    material_ids: set[int],
) -> tuple[MeshLibraryEntry, ...]:
    entries: list[MeshLibraryEntry] = []
    for mesh in mesh_nodes:
        mesh_id = mesh.attrib.get("ID")
        if mesh_id is None or not mesh_id.isdigit():
            continue
        lod = _select_primary_lod(mesh)
        if lod is None:
            continue
        vertices = lod.find("Vertices")
        if vertices is None:
            continue
        points = _extract_packed_points(vertices, f"{mesh.attrib.get('Name', f'Mesh_{mesh_id}')}.points", messages, source_transform)
        face_counts, face_indices, sections = _extract_lod_faces(lod, mesh.attrib.get("Name", f"Mesh_{mesh_id}"), messages, material_ids)
        if not points or not face_counts or not face_indices:
            continue
        entries.append(
            MeshLibraryEntry(
                mesh_id=int(mesh_id),
                name=mesh.attrib.get("Name", f"Mesh_{mesh_id}"),
                mesh=MeshData(
                    name=mesh.attrib.get("Name", f"Mesh_{mesh_id}"),
                    points=tuple(points),
                    face_vertex_counts=tuple(face_counts),
                    face_vertex_indices=tuple(face_indices),
                    sections=sections,
                ),
                original_scale=_read_positive_float(lod.attrib.get("OriginalScale")),
            )
        )
    return tuple(entries)


def _build_proxy_prototypes(
    repeated_parts: tuple[RepeatedPartInstance, ...],
    mesh_library: tuple[MeshLibraryEntry, ...],
) -> tuple[Prototype, ...]:
    if not repeated_parts:
        return ()
    source_keys = tuple(dict.fromkeys(part.prototype_key for part in repeated_parts))
    meshes_by_key = {f"Mesh_{entry.mesh_id}": entry for entry in mesh_library}
    prototypes: list[Prototype] = []
    for source_key in source_keys:
        entry = meshes_by_key.get(source_key)
        prototypes.append(
            Prototype(
                identity=PrototypeIdentity(source_key=source_key, prim_name=source_key),
                mesh=_mesh_with_original_scale(entry) if entry is not None else None,
                source_key=source_key,
                source_mesh_id=entry.mesh_id if entry is not None else None,
                source_name=entry.name if entry is not None else source_key,
            )
        )
    return tuple(prototypes)


def _find_first_attr(root: ET.Element, attr_name: str) -> str | None:
    for elem in root.iter():
        if attr_name in elem.attrib:
            return elem.attrib[attr_name]
    return None


def _read_positive_float(raw: str | None) -> float | None:
    value = _parse_float_value(raw)
    return value if value is not None and value > 0.0 else None


def _ordered_sections(sections_by_material: dict[int, list[int]]) -> tuple[MeshSection, ...]:
    return tuple(
        MeshSection(material_id=material_id, face_indices=tuple(sorted(face_indices)))
        for material_id, face_indices in sorted(sections_by_material.items())
        if face_indices
    )


def _proxy_projection_cache_path(input_path: str) -> Path:
    xml_path = Path(input_path)
    try:
        stat_result = xml_path.stat()
    except OSError:
        return _proxy_projection_cache_root() / "unavailable.npz"
    signature = "|".join(
        (
            str(PROXY_SOURCE_PROJECTION_CACHE_SCHEMA_VERSION),
            _proxy_projection_parser_key(),
            os.path.normcase(str(xml_path.resolve(strict=False))),
            str(stat_result.st_size),
            str(stat_result.st_mtime_ns),
        )
    )
    return _proxy_projection_cache_root() / f"{hashlib.sha256(signature.encode('utf-8')).hexdigest()}.npz"


def _proxy_projection_cache_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    candidate = (
        Path(local_app_data) / "XMLtoUSDAConverter" / "cache" / "proxy_source_projections"
        if local_app_data
        else None
    )
    fallback = Path(tempfile.gettempdir()) / "XMLtoUSDAConverter" / "cache" / "proxy_source_projections"
    for root in (candidate, fallback):
        if root is None:
            continue
        try:
            root.mkdir(parents=True, exist_ok=True)
            return root
        except OSError:
            continue
    return fallback


def _proxy_projection_parser_key() -> str:
    return "packaged-et-explicit" if packaged_xml_parser_adapter_enabled() else "defused"


def _read_proxy_projection_cache(cache_path: Path) -> ProxySourceProjection | None:
    if not cache_path.exists():
        return None
    try:
        import numpy as np

        with np.load(cache_path, allow_pickle=False) as data:
            schema_version = int(data["schema_version"][0])
            if schema_version != PROXY_SOURCE_PROJECTION_CACHE_SCHEMA_VERSION:
                raise ValueError("Proxy Source Projection cache schema mismatch.")
            return _projection_from_arrays(data)
    except Exception:
        with contextlib.suppress(Exception):
            cache_path.unlink(missing_ok=True)
        return None


def _write_proxy_projection_cache(cache_path: Path, projection: ProxySourceProjection) -> None:
    temp_path = cache_path.with_name(f"{cache_path.name}.tmp")
    try:
        import numpy as np

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = _projection_to_arrays(projection, np)
        with temp_path.open("wb") as handle:
            np.savez(handle, **payload)
        temp_path.replace(cache_path)
    except Exception:
        with contextlib.suppress(Exception):
            temp_path.unlink(missing_ok=True)
        with contextlib.suppress(Exception):
            cache_path.unlink(missing_ok=True)


def _projection_to_arrays(projection: ProxySourceProjection, np) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": np.asarray([PROXY_SOURCE_PROJECTION_CACHE_SCHEMA_VERSION], dtype=np.int32),
        "source_path": np.asarray([projection.source_path]),
    }
    base = projection.base_mesh
    payload["base_present"] = np.asarray([1 if base is not None else 0], dtype=np.int8)
    if base is None:
        payload["base_points"] = np.empty((0, 3), dtype=np.float64)
        payload["base_face_counts"] = np.empty((0,), dtype=np.int32)
        payload["base_face_indices"] = np.empty((0,), dtype=np.int32)
        payload["base_joint_indices"] = np.empty((0,), dtype=np.int32)
        payload["base_joint_weights"] = np.empty((0,), dtype=np.float64)
        payload["base_skel_element_size"] = np.asarray([0], dtype=np.int32)
    else:
        payload["base_points"] = _mesh_points_array(base, np)
        payload["base_face_counts"] = np.asarray(base.face_vertex_counts, dtype=np.int32)
        payload["base_face_indices"] = np.asarray(base.face_vertex_indices, dtype=np.int32)
        payload["base_joint_indices"] = np.asarray(base.skel_joint_indices, dtype=np.int32)
        payload["base_joint_weights"] = np.asarray(base.skel_joint_weights, dtype=np.float64)
        payload["base_skel_element_size"] = np.asarray([base.skel_element_size], dtype=np.int32)

    skeleton = projection.skeleton
    payload["skeleton_names"] = np.asarray([joint.name for joint in skeleton])
    payload["skeleton_source_ids"] = np.asarray(
        [joint.source_id if joint.source_id is not None else -1 for joint in skeleton],
        dtype=np.int64,
    )
    payload["skeleton_parents"] = np.asarray([joint.parent or "" for joint in skeleton])
    payload["skeleton_generator_labels"] = np.asarray([joint.generator_label or "" for joint in skeleton])
    payload["skeleton_generator_levels"] = np.asarray(
        [joint.generator_level if joint.generator_level is not None else -1 for joint in skeleton],
        dtype=np.int32,
    )
    payload["skeleton_bind_transforms"] = np.asarray([joint.bind_transform.rows for joint in skeleton], dtype=np.float64)
    payload["skeleton_rest_transforms"] = np.asarray([joint.rest_transform.rows for joint in skeleton], dtype=np.float64)
    payload["skeleton_bind_end_present"] = np.asarray(
        [1 if joint.bind_end_transform is not None else 0 for joint in skeleton],
        dtype=np.int8,
    )
    payload["skeleton_bind_end_transforms"] = np.asarray(
        [(joint.bind_end_transform or Matrix4d.identity()).rows for joint in skeleton],
        dtype=np.float64,
    )

    payload["prototype_count"] = np.asarray([len(projection.prototypes)], dtype=np.int32)
    payload["prototype_keys"] = np.asarray([prototype.source_key for prototype in projection.prototypes])
    payload["prototype_names"] = np.asarray([prototype.source_name for prototype in projection.prototypes])
    payload["prototype_mesh_ids"] = np.asarray(
        [prototype.source_mesh_id if prototype.source_mesh_id is not None else -1 for prototype in projection.prototypes],
        dtype=np.int64,
    )
    payload["prototype_present"] = np.asarray([1 if prototype.mesh is not None else 0 for prototype in projection.prototypes], dtype=np.int8)
    for index, prototype in enumerate(projection.prototypes):
        mesh = prototype.mesh
        if mesh is None:
            payload[f"prototype_{index}_points"] = np.empty((0, 3), dtype=np.float64)
            payload[f"prototype_{index}_face_counts"] = np.empty((0,), dtype=np.int32)
            payload[f"prototype_{index}_face_indices"] = np.empty((0,), dtype=np.int32)
            continue
        payload[f"prototype_{index}_points"] = _mesh_points_array(mesh, np)
        payload[f"prototype_{index}_face_counts"] = np.asarray(mesh.face_vertex_counts, dtype=np.int32)
        payload[f"prototype_{index}_face_indices"] = np.asarray(mesh.face_vertex_indices, dtype=np.int32)

    repeated_parts = projection.repeated_parts
    payload["repeated_names"] = np.asarray([part.name for part in repeated_parts])
    payload["repeated_prototype_keys"] = np.asarray([part.prototype_key for part in repeated_parts])
    payload["repeated_positions"] = np.asarray([(part.position.x, part.position.y, part.position.z) for part in repeated_parts], dtype=np.float64)
    payload["repeated_orientations"] = np.asarray(
        [(part.orientation.real, part.orientation.i, part.orientation.j, part.orientation.k) for part in repeated_parts],
        dtype=np.float64,
    )
    payload["repeated_scales"] = np.asarray([(part.scale.x, part.scale.y, part.scale.z) for part in repeated_parts], dtype=np.float64)
    payload["repeated_source_object_ids"] = np.asarray([part.source_object_id or "" for part in repeated_parts])
    payload["repeated_source_mesh_ids"] = np.asarray(
        [part.source_mesh_id if part.source_mesh_id is not None else -1 for part in repeated_parts],
        dtype=np.int64,
    )
    payload["repeated_source_material_ids"] = np.asarray(
        [part.source_material_id if part.source_material_id is not None else -1 for part in repeated_parts],
        dtype=np.int64,
    )
    payload["repeated_source_bone_ids"] = np.asarray(
        [part.source_bone_id if part.source_bone_id is not None else -1 for part in repeated_parts],
        dtype=np.int64,
    )
    payload["repeated_mesh_lods"] = np.asarray([part.mesh_lod if part.mesh_lod is not None else -1 for part in repeated_parts], dtype=np.int64)
    return payload


def _projection_from_arrays(data) -> ProxySourceProjection:
    base_mesh = None
    if int(data["base_present"][0]):
        base_mesh = _mesh_from_arrays(
            "TreeBaseMesh",
            data["base_points"],
            data["base_face_counts"],
            data["base_face_indices"],
            joint_indices=data["base_joint_indices"],
            joint_weights=data["base_joint_weights"],
            skel_element_size=int(data["base_skel_element_size"][0]),
        )

    skeleton_names = data["skeleton_names"].astype(str).tolist()
    skeleton_source_ids = data["skeleton_source_ids"].astype(int).tolist()
    skeleton_parents = data["skeleton_parents"].astype(str).tolist()
    skeleton_generator_labels = data["skeleton_generator_labels"].astype(str).tolist()
    skeleton_generator_levels = data["skeleton_generator_levels"].astype(int).tolist()
    bind_transforms = data["skeleton_bind_transforms"]
    rest_transforms = data["skeleton_rest_transforms"]
    bind_end_present = data["skeleton_bind_end_present"].astype(int).tolist()
    bind_end_transforms = data["skeleton_bind_end_transforms"]
    skeleton = tuple(
        Joint(
            name=skeleton_names[index],
            source_id=skeleton_source_ids[index] if skeleton_source_ids[index] >= 0 else None,
            parent=skeleton_parents[index] or None,
            generator_label=skeleton_generator_labels[index] or None,
            generator_level=skeleton_generator_levels[index] if skeleton_generator_levels[index] >= 0 else None,
            bind_transform=_matrix_from_array(bind_transforms[index]),
            rest_transform=_matrix_from_array(rest_transforms[index]),
            bind_end_transform=_matrix_from_array(bind_end_transforms[index]) if bind_end_present[index] else None,
        )
        for index in range(len(skeleton_names))
    )

    prototype_keys = data["prototype_keys"].astype(str).tolist()
    prototype_names = data["prototype_names"].astype(str).tolist()
    prototype_mesh_ids = data["prototype_mesh_ids"].astype(int).tolist()
    prototype_present = data["prototype_present"].astype(int).tolist()
    prototypes: list[Prototype] = []
    for index, source_key in enumerate(prototype_keys):
        mesh = None
        if prototype_present[index]:
            mesh = _mesh_from_arrays(
                prototype_names[index],
                data[f"prototype_{index}_points"],
                data[f"prototype_{index}_face_counts"],
                data[f"prototype_{index}_face_indices"],
            )
        prototypes.append(
            Prototype(
                identity=PrototypeIdentity(source_key=source_key, prim_name=source_key),
                mesh=mesh,
                source_key=source_key,
                source_mesh_id=prototype_mesh_ids[index] if prototype_mesh_ids[index] >= 0 else None,
                source_name=prototype_names[index],
            )
        )

    names = data["repeated_names"].astype(str).tolist()
    prototype_refs = data["repeated_prototype_keys"].astype(str).tolist()
    positions = data["repeated_positions"]
    orientations = data["repeated_orientations"]
    scales = data["repeated_scales"]
    source_object_ids = data["repeated_source_object_ids"].astype(str).tolist()
    source_mesh_ids = data["repeated_source_mesh_ids"].astype(int).tolist()
    source_material_ids = data["repeated_source_material_ids"].astype(int).tolist()
    source_bone_ids = data["repeated_source_bone_ids"].astype(int).tolist()
    mesh_lods = data["repeated_mesh_lods"].astype(int).tolist()
    repeated_parts = tuple(
        RepeatedPartInstance(
            name=names[index],
            prototype_key=prototype_refs[index],
            position=Vector3(float(positions[index][0]), float(positions[index][1]), float(positions[index][2])),
            orientation=_quaternion_from_row(orientations[index]),
            scale=Vector3(float(scales[index][0]), float(scales[index][1]), float(scales[index][2])),
            binding=_binding_from_cache_bone_id(source_bone_ids[index]),
            source_object_id=source_object_ids[index] or None,
            source_mesh_id=source_mesh_ids[index] if source_mesh_ids[index] >= 0 else None,
            source_material_id=source_material_ids[index] if source_material_ids[index] >= 0 else None,
            source_bone_ids=(source_bone_ids[index],) if source_bone_ids[index] >= 0 else (),
            mesh_lod=mesh_lods[index] if mesh_lods[index] >= 0 else None,
        )
        for index in range(len(names))
    )
    return ProxySourceProjection(
        source_path=str(data["source_path"].astype(str).tolist()[0]),
        base_mesh=base_mesh,
        prototypes=tuple(prototypes),
        repeated_parts=repeated_parts,
        skeleton=skeleton,
    )


def _mesh_points_array(mesh: MeshData, np):
    return np.asarray([(point.x, point.y, point.z) for point in mesh.points], dtype=np.float64)


def _mesh_from_arrays(
    name: str,
    points,
    face_counts,
    face_indices,
    *,
    joint_indices=(),
    joint_weights=(),
    skel_element_size: int = 0,
) -> MeshData:
    return MeshData(
        name=name,
        points=tuple(Vector3(float(point[0]), float(point[1]), float(point[2])) for point in points),
        face_vertex_counts=tuple(int(value) for value in face_counts),
        face_vertex_indices=tuple(int(value) for value in face_indices),
        skel_joint_indices=tuple(int(value) for value in joint_indices),
        skel_joint_weights=tuple(float(value) for value in joint_weights),
        skel_element_size=int(skel_element_size),
    )


def _matrix_from_array(values) -> Matrix4d:
    return Matrix4d(tuple(tuple(float(value) for value in row) for row in values))


def _quaternion_from_row(row) -> Quaternion:
    return Quaternion(float(row[0]), float(row[1]), float(row[2]), float(row[3]))


def _binding_from_cache_bone_id(source_bone_id: int) -> InstanceBinding:
    if source_bone_id < 0:
        return InstanceBinding(joint_tokens=(), weights=())
    return _binding_from_bone_id(source_bone_id)
