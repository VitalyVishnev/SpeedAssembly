"""Structural detection and synthetic skeletal assembly for leaf-only sources."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .geometry_buffers import geometry_buffer_to_mesh
from .models import (
    CanonicalTreeModel,
    Color4,
    InstanceBinding,
    Joint,
    Matrix4d,
    MeshData,
    MeshSection,
    PrototypeResolutionMode,
    Quaternion,
    RepeatedPartInstance,
    ScatteredRigMode,
    Vector2,
    Vector3,
)
from .skeleton_processing import apply_skinning_quality, orient_skeleton_x


_MIN_BONE_LENGTH = 1.0e-3
_SYNTHETIC_TILT_RADIANS = math.radians(1.0)
_GOLDEN_ANGLE_RADIANS = math.pi * (3.0 - math.sqrt(5.0))


@dataclass(frozen=True, slots=True)
class ScatteredPartsCluster:
    source_object_id: str
    part_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ScatteredPartsAnalysis:
    eligible: bool
    clustered: bool
    instance_count: int
    clusters: tuple[ScatteredPartsCluster, ...] = ()
    reason: str = ""

    @property
    def cluster_count(self) -> int:
        return len(self.clusters)


def analyze_scattered_parts(model: CanonicalTreeModel) -> ScatteredPartsAnalysis:
    """Classify leaf-only repeated geometry without relying on generator names."""
    parts = model.repeated_parts
    if model.base_mesh is not None:
        return ScatteredPartsAnalysis(False, False, len(parts), reason="base mesh is present")
    if model.skeleton:
        return ScatteredPartsAnalysis(False, False, len(parts), reason="skeleton is present")
    if not parts:
        return ScatteredPartsAnalysis(False, False, 0, reason="no repeated parts")
    if not model.prototypes:
        return ScatteredPartsAnalysis(False, False, len(parts), reason="no prototypes")

    objects = {item.object_id: item for item in model.source_objects}
    if any(part.source_object_id not in objects for part in parts):
        return ScatteredPartsAnalysis(False, False, len(parts), reason="part source object is unresolved")

    root_ids = {item.object_id for item in model.source_objects if item.parent_id is None}
    parent_groups: dict[str, list[int]] = {}
    for index, part in enumerate(parts):
        host = objects[part.source_object_id or ""]
        if host.parent_id is None or host.parent_id not in objects:
            return ScatteredPartsAnalysis(False, False, len(parts), reason="part host parent is unresolved")
        parent_groups.setdefault(host.parent_id, []).append(index)

    if len(parent_groups) == 1 and next(iter(parent_groups)) in root_ids:
        return ScatteredPartsAnalysis(True, False, len(parts))

    cluster_ids = tuple(sorted(parent_groups, key=_source_id_sort_key))
    valid_clusters = (
        len(cluster_ids) > 1
        and all(cluster_id not in root_ids for cluster_id in cluster_ids)
        and all(len(parent_groups[cluster_id]) > 1 for cluster_id in cluster_ids)
        and all(
            objects[cluster_id].parent_id in root_ids
            and objects[cluster_id].mesh is None
            and objects[cluster_id].assembly_part_reference_count == 0
            for cluster_id in cluster_ids
        )
    )
    if not valid_clusters:
        return ScatteredPartsAnalysis(True, False, len(parts))
    return ScatteredPartsAnalysis(
        True,
        True,
        len(parts),
        clusters=tuple(
            ScatteredPartsCluster(cluster_id, tuple(parent_groups[cluster_id]))
            for cluster_id in cluster_ids
        ),
    )


def coerce_scattered_rig_mode(
    analysis: ScatteredPartsAnalysis,
    mode: ScatteredRigMode | str | None,
) -> ScatteredRigMode:
    resolved = ScatteredRigMode.parse(mode)
    if not analysis.clustered and resolved in {
        ScatteredRigMode.PER_CLUSTER_RIGID,
        ScatteredRigMode.PER_CLUSTER_SKINNED,
    }:
        return ScatteredRigMode.WHOLE_MESH_SKINNED
    return resolved


def apply_scattered_parts_rig(
    model: CanonicalTreeModel,
    mode: ScatteredRigMode | str | None,
    *,
    orient_bones_from_instances: bool = False,
) -> CanonicalTreeModel:
    """Create the real base geometry and synthetic rig required by Skeletal Assembly."""
    analysis = analyze_scattered_parts(model)
    if not analysis.eligible:
        return model
    resolved_mode = coerce_scattered_rig_mode(analysis, mode)
    parts = model.repeated_parts
    meshes = _resolve_bakeable_meshes(model)
    point_arrays = _mesh_point_arrays(meshes)
    all_indices = tuple(range(len(parts)))
    orientation_weights = (
        _instance_surface_area_weights(parts, meshes)
        if orient_bones_from_instances
        else ()
    )
    global_pivot = _average_position(parts, all_indices)
    global_direction = (
        _average_instance_direction(parts, orientation_weights, all_indices, "whole rig", 0)
        if orient_bones_from_instances
        else None
    )
    global_height = _bone_length(
        parts,
        point_arrays,
        all_indices,
        global_pivot,
        global_direction,
    )

    if resolved_mode == ScatteredRigMode.WHOLE_MESH_SKINNED:
        bones = (("scattered_whole", global_pivot, global_height, global_direction),)
        skeleton = _synthetic_skeleton(
            global_pivot,
            global_height,
            bones,
            root_direction=global_direction,
        )
        base_mesh = _bake_instances(parts, meshes, all_indices, (1,) * len(all_indices), "ScatteredParts_BaseMesh")
        authored = replace(model, base_mesh=base_mesh, skeleton=skeleton, assembly_parts=())
        authored = apply_skinning_quality(authored, skinning_quality=2)
    elif resolved_mode == ScatteredRigMode.PER_CLUSTER_SKINNED:
        if not analysis.clustered:
            raise ValueError("Scattered Parts Per Cluster (Skinned) requires a detected cluster hierarchy.")
        bones = tuple(
            (
                f"scattered_cluster_{cluster_index:04d}",
                pivot,
                _bone_length(
                    parts,
                    point_arrays,
                    cluster.part_indices,
                    pivot,
                    direction,
                ),
                direction,
            )
            for cluster_index, cluster in enumerate(analysis.clusters)
            for pivot in (_average_position(parts, cluster.part_indices),)
            for direction in (
                _average_instance_direction(
                    parts,
                    orientation_weights,
                    cluster.part_indices,
                    f"cluster {cluster_index}",
                    cluster_index + 1,
                )
                if orient_bones_from_instances
                else None,
            )
        )
        skeleton = _synthetic_skeleton(
            global_pivot,
            global_height,
            bones,
            root_direction=global_direction,
        )
        part_indices = tuple(index for cluster in analysis.clusters for index in cluster.part_indices)
        owner_indices = tuple(
            cluster_index + 1
            for cluster_index, cluster in enumerate(analysis.clusters)
            for _index in cluster.part_indices
        )
        base_mesh = _bake_instances(parts, meshes, part_indices, owner_indices, "ScatteredParts_BaseMesh")
        authored = replace(model, base_mesh=base_mesh, skeleton=skeleton, assembly_parts=())
        authored = apply_skinning_quality(authored, skinning_quality=2)
    elif resolved_mode == ScatteredRigMode.PER_CLUSTER_RIGID:
        if not analysis.clustered:
            raise ValueError("Scattered Parts Per Cluster (Rigid) requires a detected cluster hierarchy.")
        bones = tuple(
            (
                f"scattered_cluster_{cluster_index:04d}",
                (pivot := _average_position(parts, cluster.part_indices)),
                _bone_length(
                    parts,
                    point_arrays,
                    cluster.part_indices,
                    pivot,
                    direction,
                ),
                direction,
            )
            for cluster_index, cluster in enumerate(analysis.clusters)
            for direction in (
                _average_instance_direction(
                    parts,
                    orientation_weights,
                    cluster.part_indices,
                    f"cluster {cluster_index}",
                    cluster_index + 1,
                )
                if orient_bones_from_instances
                else None,
            )
        )
        skeleton = _synthetic_skeleton(
            global_pivot,
            global_height,
            bones,
            root_direction=global_direction,
        )
        baked_indices = analysis.clusters[0].part_indices
        base_mesh = _pad_mesh_two(
            _bake_instances(parts, meshes, baked_indices, (1,) * len(baked_indices), "ScatteredParts_BaseMesh")
        )
        baked_index_set = set(baked_indices)
        cluster_by_part = {
            part_index: cluster_index
            for cluster_index, cluster in enumerate(analysis.clusters)
            for part_index in cluster.part_indices
        }
        repeated = tuple(
            _rigid_part_binding(part, skeleton[cluster_by_part[index] + 1].name)
            for index, part in enumerate(parts)
            if index not in baked_index_set
        )
        authored = replace(model, base_mesh=base_mesh, skeleton=skeleton, assembly_parts=repeated)
    else:
        bones = tuple(
            (
                f"scattered_instance_{index:04d}",
                part.position,
                _bone_length(
                    parts,
                    point_arrays,
                    (index,),
                    part.position,
                    direction,
                ),
                direction,
            )
            for index, part in enumerate(parts)
            for direction in (
                _average_instance_direction(
                    parts,
                    orientation_weights,
                    (index,),
                    f"instance {index}",
                    index + 1,
                )
                if orient_bones_from_instances
                else None,
            )
        )
        skeleton = _synthetic_skeleton(
            global_pivot,
            global_height,
            bones,
            root_direction=global_direction,
        )
        base_mesh = _pad_mesh_two(_bake_instances(parts, meshes, (0,), (1,), "ScatteredParts_BaseMesh"))
        repeated = tuple(
            _rigid_part_binding(part, skeleton[index + 1].name)
            for index, part in enumerate(parts)
            if index != 0
        )
        authored = replace(model, base_mesh=base_mesh, skeleton=skeleton, assembly_parts=repeated)

    warning = (
        f"Scattered Parts mode synthesized a skeletal base and rig using {resolved_mode.value}; "
        f"source instances: {analysis.instance_count}, clusters: {analysis.cluster_count}; "
        f"bone orientation: {'average instance direction' if orient_bones_from_instances else 'near-up'}."
    )
    return replace(authored, metadata=replace(authored.metadata, warnings=authored.metadata.warnings + (warning,)))


def _synthetic_skeleton(
    root_pivot: Vector3,
    root_height: float,
    bones: tuple[tuple[str, Vector3, float, Vector3 | None], ...],
    *,
    root_direction: Vector3 | None = None,
) -> tuple[Joint, ...]:
    root = Joint(
        name="root",
        source_id=0,
        generator_label="ScatteredParts",
        generator_level=0,
        bind_transform=Matrix4d.from_translation(root_pivot),
        rest_transform=Matrix4d.from_translation(root_pivot),
        bind_end_transform=Matrix4d.from_translation(
            _bone_end(root_pivot, root_height, root_direction, 0)
        ),
    )
    children: list[Joint] = []
    for source_id, (name, pivot, height, direction) in enumerate(bones, start=1):
        endpoint = _bone_end(pivot, height, direction, source_id)
        children.append(
            Joint(
                name=name,
                source_id=source_id,
                parent="root",
                generator_label="ScatteredParts",
                generator_level=0,
                bind_transform=Matrix4d.from_translation(pivot),
                rest_transform=Matrix4d.from_translation(pivot),
                bind_end_transform=Matrix4d.from_translation(endpoint),
            )
        )
    return orient_skeleton_x((root, *children))


def _resolve_bakeable_meshes(model: CanonicalTreeModel) -> dict[str, MeshData]:
    prototypes = {prototype.source_key: prototype for prototype in model.prototypes}
    meshes: dict[str, MeshData] = {}
    for part in model.repeated_parts:
        if part.prototype_key in meshes:
            continue
        prototype = prototypes.get(part.prototype_key)
        if prototype is None:
            raise ValueError(f"Scattered Parts instance {part.name!r} references missing prototype {part.prototype_key!r}.")
        if prototype.resolution_mode == PrototypeResolutionMode.EXTERNAL_ASSET:
            raise ValueError(
                f"Scattered Parts skeletal modes require bakeable prototype geometry; "
                f"{prototype.source_name!r} is configured as an external Unreal asset."
            )
        mesh = prototype.mesh
        if mesh is None and prototype.geometry_payload is not None:
            mesh = geometry_buffer_to_mesh(prototype.geometry_payload, max_points=prototype.geometry_payload.point_count)
        if mesh is None or not mesh.points or not mesh.face_vertex_counts:
            raise ValueError(f"Scattered Parts prototype {prototype.source_name!r} has no bakeable face geometry.")
        meshes[part.prototype_key] = mesh
    return meshes


def _bake_instances(
    parts: tuple[RepeatedPartInstance, ...],
    meshes: dict[str, MeshData],
    part_indices: tuple[int, ...],
    owner_joint_indices: tuple[int, ...],
    name: str,
) -> MeshData:
    if len(part_indices) != len(owner_joint_indices) or not part_indices:
        raise ValueError("Scattered Parts baking requires one owner joint per source instance.")
    selected_meshes = tuple(meshes[parts[index].prototype_key] for index in part_indices)
    include_normals = all(_valid_attribute(mesh.normals, mesh) for mesh in selected_meshes)
    include_uvs = all(_valid_attribute(mesh.uv_coords, mesh) for mesh in selected_meshes)
    include_secondary_uvs = all(_valid_attribute(mesh.secondary_uv_coords, mesh) for mesh in selected_meshes)
    include_colors = all(_valid_attribute(mesh.vertex_colors, mesh) for mesh in selected_meshes)
    face_normals = {
        key: _as_face_varying(mesh.normals, mesh)
        for key, mesh in meshes.items()
    } if include_normals else {}
    face_uvs = {
        key: _as_face_varying(mesh.uv_coords, mesh)
        for key, mesh in meshes.items()
    } if include_uvs else {}
    face_secondary_uvs = {
        key: _as_face_varying(mesh.secondary_uv_coords, mesh)
        for key, mesh in meshes.items()
    } if include_secondary_uvs else {}
    face_colors = {
        key: _as_face_varying(mesh.vertex_colors, mesh)
        for key, mesh in meshes.items()
    } if include_colors else {}

    points: list[Vector3] = []
    counts: list[int] = []
    indices: list[int] = []
    normals: list[Vector3] = []
    uvs: list[Vector2] = []
    secondary_uvs: list[Vector2] = []
    colors: list[Color4] = []
    joint_indices: list[int] = []
    sections: dict[int, list[int]] = {}
    point_offset = 0
    face_offset = 0
    for part_index, owner_joint_index in zip(part_indices, owner_joint_indices, strict=True):
        part = parts[part_index]
        mesh = meshes[part.prototype_key]
        points.extend(_transform_points(mesh.points, part))
        counts.extend(mesh.face_vertex_counts)
        indices.extend(point_offset + index for index in mesh.face_vertex_indices)
        if include_normals:
            normals.extend(_transform_normals(face_normals[part.prototype_key], part))
        if include_uvs:
            uvs.extend(face_uvs[part.prototype_key])
        if include_secondary_uvs:
            secondary_uvs.extend(face_secondary_uvs[part.prototype_key])
        if include_colors:
            colors.extend(face_colors[part.prototype_key])
        joint_indices.extend([owner_joint_index] * len(mesh.points))
        for section in mesh.sections:
            sections.setdefault(section.material_id, []).extend(face_offset + face for face in section.face_indices)
        point_offset += len(mesh.points)
        face_offset += len(mesh.face_vertex_counts)
    return MeshData(
        name=name,
        points=tuple(points),
        face_vertex_counts=tuple(counts),
        face_vertex_indices=tuple(indices),
        normals=tuple(normals),
        uv_coords=tuple(uvs),
        secondary_uv_coords=tuple(secondary_uvs),
        vertex_colors=tuple(colors),
        sections=tuple(
            MeshSection(material_id=material_id, face_indices=tuple(face_indices))
            for material_id, face_indices in sorted(sections.items())
        ),
        skel_joint_indices=tuple(joint_indices),
        skel_joint_weights=(1.0,) * len(points),
        skel_element_size=1,
    )


def _pad_mesh_two(mesh: MeshData) -> MeshData:
    indices = tuple(value for index in mesh.skel_joint_indices for value in (index, index))
    weights = tuple(value for _index in mesh.skel_joint_indices for value in (1.0, 0.0))
    return replace(mesh, skel_joint_indices=indices, skel_joint_weights=weights, skel_element_size=2)


def _rigid_part_binding(part: RepeatedPartInstance, joint_name: str) -> RepeatedPartInstance:
    return replace(part, binding=InstanceBinding((joint_name, joint_name), (1.0, 0.0)))


def _average_position(parts: tuple[RepeatedPartInstance, ...], indices: tuple[int, ...]) -> Vector3:
    count = len(indices)
    return Vector3(
        sum(parts[index].position.x for index in indices) / count,
        sum(parts[index].position.y for index in indices) / count,
        sum(parts[index].position.z for index in indices) / count,
    )


def _bone_length(
    parts: tuple[RepeatedPartInstance, ...],
    point_arrays: dict[str, object],
    indices: tuple[int, ...],
    pivot: Vector3,
    direction: Vector3 | None,
) -> float:
    maximum = pivot.y if direction is None else 0.0
    minimum = pivot.y if direction is None else 0.0
    for index in indices:
        part = parts[index]
        rows = _scaled_rotation(part.orientation, part.scale)
        if direction is None:
            coefficient_x, coefficient_y, coefficient_z = rows[1]
            offset = part.position.y
        else:
            coefficient_x = direction.x * rows[0][0] + direction.y * rows[1][0] + direction.z * rows[2][0]
            coefficient_y = direction.x * rows[0][1] + direction.y * rows[1][1] + direction.z * rows[2][1]
            coefficient_z = direction.x * rows[0][2] + direction.y * rows[1][2] + direction.z * rows[2][2]
            offset = _dot_direction(part.position, pivot, direction)
        values = point_arrays[part.prototype_key] @ (
            coefficient_x,
            coefficient_y,
            coefficient_z,
        )
        minimum = min(minimum, float(values.min()) + offset)
        maximum = max(maximum, float(values.max()) + offset)
    origin = pivot.y if direction is None else 0.0
    return max(maximum - origin, maximum - minimum, _MIN_BONE_LENGTH)


def _mesh_point_arrays(meshes: dict[str, MeshData]) -> dict[str, object]:
    import numpy as np

    return {
        key: np.fromiter(
            (coordinate for point in mesh.points for coordinate in (point.x, point.y, point.z)),
            dtype=np.float64,
            count=len(mesh.points) * 3,
        ).reshape((-1, 3))
        for key, mesh in meshes.items()
    }


def _transform_points(
    points: tuple[Vector3, ...],
    part: RepeatedPartInstance,
) -> list[Vector3]:
    first, second, third = _scaled_rotation(part.orientation, part.scale)
    px, py, pz = part.position.x, part.position.y, part.position.z
    return [
        Vector3(
            first[0] * point.x + first[1] * point.y + first[2] * point.z + px,
            second[0] * point.x + second[1] * point.y + second[2] * point.z + py,
            third[0] * point.x + third[1] * point.y + third[2] * point.z + pz,
        )
        for point in points
    ]


def _transform_normals(
    normals: tuple[Vector3, ...],
    part: RepeatedPartInstance,
) -> list[Vector3]:
    if abs(part.scale.x) <= 1.0e-12 or abs(part.scale.y) <= 1.0e-12 or abs(part.scale.z) <= 1.0e-12:
        raise ValueError(f"Scattered Parts instance {part.name!r} has a zero scale component.")
    first, second, third = _scaled_rotation(
        part.orientation,
        Vector3(1.0 / part.scale.x, 1.0 / part.scale.y, 1.0 / part.scale.z),
    )
    transformed: list[Vector3] = []
    for normal in normals:
        x = first[0] * normal.x + first[1] * normal.y + first[2] * normal.z
        y = second[0] * normal.x + second[1] * normal.y + second[2] * normal.z
        z = third[0] * normal.x + third[1] * normal.y + third[2] * normal.z
        length = math.sqrt(x * x + y * y + z * z)
        if length <= 1.0e-12:
            raise ValueError(f"Scattered Parts instance {part.name!r} produced a zero-length normal.")
        transformed.append(Vector3(x / length, y / length, z / length))
    return transformed


def _scaled_rotation(
    orientation: Quaternion,
    scale: Vector3,
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    w, x, y, z = orientation.real, orientation.i, orientation.j, orientation.k
    return (
        (
            (1.0 - 2.0 * (y * y + z * z)) * scale.x,
            (2.0 * (x * y - w * z)) * scale.y,
            (2.0 * (x * z + w * y)) * scale.z,
        ),
        (
            (2.0 * (x * y + w * z)) * scale.x,
            (1.0 - 2.0 * (x * x + z * z)) * scale.y,
            (2.0 * (y * z - w * x)) * scale.z,
        ),
        (
            (2.0 * (x * z - w * y)) * scale.x,
            (2.0 * (y * z + w * x)) * scale.y,
            (1.0 - 2.0 * (x * x + y * y)) * scale.z,
        ),
    )


def _rotate_vector(q: Quaternion, point: Vector3) -> Vector3:
    tx = 2.0 * (q.j * point.z - q.k * point.y)
    ty = 2.0 * (q.k * point.x - q.i * point.z)
    tz = 2.0 * (q.i * point.y - q.j * point.x)
    return Vector3(
        point.x + q.real * tx + (q.j * tz - q.k * ty),
        point.y + q.real * ty + (q.k * tx - q.i * tz),
        point.z + q.real * tz + (q.i * ty - q.j * tx),
    )


def _valid_attribute(values: tuple, mesh: MeshData) -> bool:
    return bool(values) and len(values) in {len(mesh.points), len(mesh.face_vertex_indices)}


def _as_face_varying(values: tuple, mesh: MeshData) -> tuple:
    if len(values) == len(mesh.face_vertex_indices):
        return values
    return tuple(values[index] for index in mesh.face_vertex_indices)


def _average_instance_direction(
    parts: tuple[RepeatedPartInstance, ...],
    weights: tuple[float, ...],
    indices: tuple[int, ...],
    label: str,
    direction_index: int,
) -> Vector3:
    directions = tuple(
        (
            _rotate_vector(parts[index].orientation, Vector3(0.0, 1.0, 0.0)),
            weights[index],
        )
        for index in indices
    )
    summed = Vector3(
        sum(direction.x * weight for direction, weight in directions),
        sum(direction.y * weight for direction, weight in directions),
        sum(direction.z * weight for direction, weight in directions),
    )
    length = math.sqrt(summed.x * summed.x + summed.y * summed.y + summed.z * summed.z)
    if not math.isfinite(length) or length <= 1.0e-8:
        raise ValueError(
            f"Scattered Parts cannot compute {label} bone orientation: "
            "member instance directions cancel or are invalid."
        )
    return _dynamic_wind_safe_direction(
        Vector3(summed.x / length, summed.y / length, summed.z / length),
        direction_index,
    )


def _instance_surface_area_weights(
    parts: tuple[RepeatedPartInstance, ...],
    meshes: dict[str, MeshData],
) -> tuple[float, ...]:
    area_facts = {
        key: _surface_area_facts(mesh)
        for key, mesh in meshes.items()
    }
    cached_areas: dict[tuple[str, Vector3], float] = {}
    weights: list[float] = []
    for part in parts:
        cache_key = (part.prototype_key, part.scale)
        area = cached_areas.get(cache_key)
        if area is None:
            area = _scaled_surface_area(*area_facts[part.prototype_key], part.scale)
            cached_areas[cache_key] = area
        if not math.isfinite(area) or area <= 1.0e-12:
            raise ValueError(
                f"Scattered Parts cannot weight instance {part.name!r} orientation: "
                "scaled prototype surface area is zero or invalid."
            )
        weights.append(area)
    return tuple(weights)


def _surface_area_facts(
    mesh: MeshData,
) -> tuple[float, tuple[tuple[float, float, float], ...]]:
    crosses: list[tuple[float, float, float]] = []
    corner = 0
    for face_size in mesh.face_vertex_counts:
        face_indices = mesh.face_vertex_indices[corner : corner + face_size]
        corner += face_size
        if face_size < 3:
            continue
        origin = mesh.points[face_indices[0]]
        for index in range(1, face_size - 1):
            first = mesh.points[face_indices[index]]
            second = mesh.points[face_indices[index + 1]]
            first_x, first_y, first_z = first.x - origin.x, first.y - origin.y, first.z - origin.z
            second_x, second_y, second_z = second.x - origin.x, second.y - origin.y, second.z - origin.z
            crosses.append((
                first_y * second_z - first_z * second_y,
                first_z * second_x - first_x * second_z,
                first_x * second_y - first_y * second_x,
            ))
    base_area = 0.5 * sum(
        math.sqrt(x * x + y * y + z * z)
        for x, y, z in crosses
    )
    return base_area, tuple(crosses)


def _scaled_surface_area(
    base_area: float,
    crosses: tuple[tuple[float, float, float], ...],
    scale: Vector3,
) -> float:
    sx, sy, sz = abs(scale.x), abs(scale.y), abs(scale.z)
    if sx == sy == sz:
        return base_area * sx * sx
    yz, zx, xy = sy * sz, sz * sx, sx * sy
    return 0.5 * sum(
        math.sqrt((x * yz) ** 2 + (y * zx) ** 2 + (z * xy) ** 2)
        for x, y, z in crosses
    )


def _dynamic_wind_safe_direction(direction: Vector3, direction_index: int) -> Vector3:
    horizontal_length = math.sqrt(direction.x * direction.x + direction.z * direction.z)
    minimum_horizontal = math.sin(_SYNTHETIC_TILT_RADIANS)
    if horizontal_length >= minimum_horizontal:
        return direction
    if horizontal_length > 1.0e-12:
        horizontal_x = direction.x / horizontal_length
        horizontal_z = direction.z / horizontal_length
    else:
        azimuth = (direction_index + 1) * _GOLDEN_ANGLE_RADIANS
        horizontal_x = math.cos(azimuth)
        horizontal_z = math.sin(azimuth)
    return Vector3(
        horizontal_x * minimum_horizontal,
        math.copysign(math.cos(_SYNTHETIC_TILT_RADIANS), direction.y),
        horizontal_z * minimum_horizontal,
    )


def _bone_end(
    point: Vector3,
    length: float,
    direction: Vector3 | None,
    direction_index: int,
) -> Vector3:
    resolved_length = max(length, _MIN_BONE_LENGTH)
    resolved_direction = direction or _dynamic_wind_safe_direction(
        Vector3(0.0, 1.0, 0.0),
        direction_index,
    )
    return Vector3(
        point.x + resolved_direction.x * resolved_length,
        point.y + resolved_direction.y * resolved_length,
        point.z + resolved_direction.z * resolved_length,
    )


def _dot_direction(point: Vector3, pivot: Vector3, direction: Vector3) -> float:
    return (
        (point.x - pivot.x) * direction.x
        + (point.y - pivot.y) * direction.y
        + (point.z - pivot.z) * direction.z
    )


def _source_id_sort_key(value: str) -> tuple[int, int | str]:
    return (0, int(value)) if value.lstrip("-").isdigit() else (1, value)
