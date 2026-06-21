"""Collision mesh generation for Fracture Piece Static Mesh Assembly export."""

from __future__ import annotations

import math
from array import array
from dataclasses import dataclass
from enum import Enum
from itertools import combinations

import numpy as np

from .fracture_service import FractureError, FracturePiece
from .geometry_buffers import iter_face_ranges
from .models import CanonicalTreeModel, MeshData, Quaternion, Vector3
from .naming import make_stable_prim_name


_CAPSULE_RADIUS_MODEL_SCALE = 0.5


class FractureCollisionMode(str, Enum):
    CONVEX = "convex"
    CAPSULE = "capsule"
    SPHERE = "sphere"


@dataclass(frozen=True)
class FractureCollisionSettings:
    enabled: bool = False
    mode: FractureCollisionMode = FractureCollisionMode.CONVEX
    include_instance_parts: bool = False
    convex_max_vertices: int = 12
    sphere_radius_scale: float = 1.0
    capsule_simplify: int = 0
    capsule_scale: float = 0.75
    capsule_max_count: int = 64
    capsule_min_radius_ratio: float = 0.05
    capsule_radius_padding: float = 0.0
    ghost_opacity: float = 0.25
    point_sample_limit: int = 4_096


@dataclass(frozen=True)
class CollisionMeshSet:
    piece_index: int
    meshes: tuple[MeshData, ...]


@dataclass(frozen=True)
class _SamplePoint:
    point: Vector3
    joint_token: str = ""


def validated_collision_settings(settings: FractureCollisionSettings | None) -> FractureCollisionSettings:
    resolved = settings or FractureCollisionSettings()
    try:
        mode = FractureCollisionMode(resolved.mode)
    except ValueError as exc:
        raise FractureError(f"Unsupported fracture collision mode: {resolved.mode!r}.") from exc
    if not 4 <= int(resolved.convex_max_vertices) <= 32:
        raise FractureError("Convex collision max vertices must be between 4 and 32.")
    if not 0.5 <= float(resolved.sphere_radius_scale) <= 1.25:
        raise FractureError("Sphere collision radius scale must be between 0.5 and 1.25.")
    if not 0 <= int(resolved.capsule_simplify) <= 100:
        raise FractureError("Capsule collision simplify must be between 0 and 100.")
    if not 0.25 <= float(resolved.capsule_scale) <= 2.0:
        raise FractureError("Capsule collision scale must be between 0.25 and 2.0.")
    if not 1 <= int(resolved.capsule_max_count) <= 128:
        raise FractureError("Capsule collision max count must be between 1 and 128.")
    if not 0.0 <= float(resolved.capsule_min_radius_ratio) <= 0.25:
        raise FractureError("Capsule collision min radius ratio must be between 0 and 0.25.")
    if not 0.0 <= float(resolved.capsule_radius_padding) <= 0.5:
        raise FractureError("Capsule collision radius padding must be between 0 and 0.5.")
    if not 0.05 <= float(resolved.ghost_opacity) <= 0.8:
        raise FractureError("Collision ghost opacity must be between 0.05 and 0.8.")
    if int(resolved.point_sample_limit) <= 0:
        raise FractureError("Collision point sample limit must be greater than zero.")
    return FractureCollisionSettings(
        enabled=bool(resolved.enabled),
        mode=mode,
        include_instance_parts=bool(resolved.include_instance_parts),
        convex_max_vertices=int(resolved.convex_max_vertices),
        sphere_radius_scale=float(resolved.sphere_radius_scale),
        capsule_simplify=int(resolved.capsule_simplify),
        capsule_scale=float(resolved.capsule_scale),
        capsule_max_count=int(resolved.capsule_max_count),
        capsule_min_radius_ratio=float(resolved.capsule_min_radius_ratio),
        capsule_radius_padding=float(resolved.capsule_radius_padding),
        ghost_opacity=float(resolved.ghost_opacity),
        point_sample_limit=int(resolved.point_sample_limit),
    )


def collision_render_mesh_name(piece: FracturePiece) -> str:
    return make_stable_prim_name(f"SM_{piece.name}_BaseMesh", fallback="SM_BaseMesh")


def build_fracture_collision_mesh_sets(
    model: CanonicalTreeModel,
    pieces: tuple[FracturePiece, ...],
    settings: FractureCollisionSettings | None,
) -> tuple[CollisionMeshSet, ...]:
    resolved = validated_collision_settings(settings)
    if not resolved.enabled:
        return ()
    return tuple(
        CollisionMeshSet(
            piece_index=piece.index,
            meshes=build_fracture_collision_meshes(
                model,
                piece,
                resolved,
                render_mesh_name=collision_render_mesh_name(piece),
            ),
        )
        for piece in pieces
    )


def build_fracture_collision_meshes(
    model: CanonicalTreeModel,
    piece: FracturePiece,
    settings: FractureCollisionSettings | None,
    *,
    render_mesh_name: str,
) -> tuple[MeshData, ...]:
    resolved = validated_collision_settings(settings)
    if not resolved.enabled:
        return ()
    samples = _sample_piece_points(model, piece, resolved)
    if not samples:
        raise FractureError(f"Fracture collision for {piece.name} has no geometry points.")
    points = tuple(sample.point for sample in samples)
    if resolved.mode == FractureCollisionMode.SPHERE:
        center, radius = _minimal_enclosing_sphere(points)
        return (_sphere_mesh(f"USP_{render_mesh_name}_00", center, radius * resolved.sphere_radius_scale),)
    if resolved.mode == FractureCollisionMode.CAPSULE:
        return _capsule_meshes(model, piece, samples, render_mesh_name, resolved)
    return (_convex_mesh(f"UCX_{render_mesh_name}_00", points, resolved.convex_max_vertices),)


def _sample_piece_points(
    model: CanonicalTreeModel,
    piece: FracturePiece,
    settings: FractureCollisionSettings,
) -> tuple[_SamplePoint, ...]:
    if model.base_mesh is None:
        raise FractureError("Fracture collision requires a base mesh.")
    base_count = _base_face_point_count(model.base_mesh, piece.base_face_indices)
    repeated_count = _repeated_part_point_count(model, piece) if settings.include_instance_parts else 0
    total_count = base_count + repeated_count
    if total_count <= 0:
        return ()
    limit = min(settings.point_sample_limit, total_count)
    base_limit = min(base_count, max(1, round(limit * base_count / total_count))) if base_count else 0
    repeated_limit = max(0, limit - base_limit)
    return (
        *_base_face_points(model.base_mesh, piece.base_face_indices, model.skeleton, limit=base_limit, total_count=base_count),
        *(
            _repeated_part_points(model, piece, limit=repeated_limit, total_count=repeated_count)
            if settings.include_instance_parts and repeated_limit > 0
            else ()
        ),
    )


def _base_face_point_count(mesh: MeshData, face_indices: tuple[int, ...]) -> int:
    face_set = set(face_indices)
    return sum(end - start for face_index, start, end in iter_face_ranges(mesh.face_vertex_counts) if face_index in face_set)


def _base_face_points(
    mesh: MeshData,
    face_indices: tuple[int, ...],
    skeleton,
    *,
    limit: int,
    total_count: int,
) -> tuple[_SamplePoint, ...]:
    joint_names = tuple(joint.name for joint in skeleton)
    face_set = set(face_indices)
    samples: list[_SamplePoint] = []
    ordinal = 0
    for face_index, start, end in iter_face_ranges(mesh.face_vertex_counts):
        if face_index not in face_set:
            continue
        for vertex_index in mesh.face_vertex_indices[start:end]:
            if not _take_sample(ordinal, total_count, limit):
                ordinal += 1
                continue
            point = mesh.points[int(vertex_index)]
            joint_token = _point_joint_token(mesh, int(vertex_index), joint_names)
            samples.append(_SamplePoint(point, joint_token))
            ordinal += 1
    return tuple(samples)


def _point_joint_token(mesh: MeshData, point_index: int, joint_names: tuple[str, ...]) -> str:
    if mesh.skel_element_size <= 0:
        return ""
    offset = point_index * mesh.skel_element_size
    if offset >= len(mesh.skel_joint_indices):
        return ""
    joint_index = int(mesh.skel_joint_indices[offset])
    return joint_names[joint_index] if 0 <= joint_index < len(joint_names) else ""


def _repeated_part_point_count(model: CanonicalTreeModel, piece: FracturePiece) -> int:
    prototypes = {prototype.source_key: prototype for prototype in model.prototypes}
    total = 0
    for part_index in piece.repeated_part_indices:
        part = model.repeated_parts[part_index]
        prototype = prototypes.get(part.prototype_key)
        if prototype is not None and prototype.mesh is not None:
            total += len(prototype.mesh.points)
    return total


def _repeated_part_points(
    model: CanonicalTreeModel,
    piece: FracturePiece,
    *,
    limit: int,
    total_count: int,
) -> tuple[_SamplePoint, ...]:
    prototypes = {prototype.source_key: prototype for prototype in model.prototypes}
    samples: list[_SamplePoint] = []
    ordinal = 0
    for part_index in piece.repeated_part_indices:
        part = model.repeated_parts[part_index]
        prototype = prototypes.get(part.prototype_key)
        if prototype is None or prototype.mesh is None:
            continue
        joint_token = part.bind_joint
        for point in prototype.mesh.points:
            if not _take_sample(ordinal, total_count, limit):
                ordinal += 1
                continue
            samples.append(_SamplePoint(_transform_point(point, part.position, part.orientation, part.scale), joint_token))
            ordinal += 1
    return tuple(samples)


def _take_sample(ordinal: int, total_count: int, limit: int) -> bool:
    if limit <= 0:
        return False
    if total_count <= limit:
        return True
    return ((ordinal + 1) * limit // total_count) > (ordinal * limit // total_count)


def _transform_point(point: Vector3, translate: Vector3, orientation: Quaternion, scale: Vector3) -> Vector3:
    scaled = Vector3(point.x * scale.x, point.y * scale.y, point.z * scale.z)
    rotated = _rotate_vector(scaled, orientation)
    return Vector3(rotated.x + translate.x, rotated.y + translate.y, rotated.z + translate.z)


def _rotate_vector(vector: Vector3, q: Quaternion) -> Vector3:
    w, x, y, z = float(q.real), float(q.i), float(q.j), float(q.k)
    length = math.sqrt(w * w + x * x + y * y + z * z)
    if length <= 0.0:
        raise FractureError("Fracture collision encountered a zero-length orientation quaternion.")
    w, x, y, z = w / length, x / length, y / length, z / length
    vx, vy, vz = vector.x, vector.y, vector.z
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return Vector3(
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )


def _convex_mesh(name: str, points: tuple[Vector3, ...], max_vertices: int) -> MeshData:
    source = _np_points(points)
    support = _convex_support_points(source, max_vertices)
    hull_points, faces = _convex_hull_faces(support)
    inflated = _inflate_to_cover(hull_points, source)
    return _mesh_from_faces(name, tuple(_vector3(point) for point in inflated), faces)


def _convex_support_points(points: np.ndarray, max_vertices: int) -> np.ndarray:
    center = points.mean(axis=0)
    centered = points - center
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    dirs = [axis for axis in vh]
    dirs += [-axis for axis in vh]
    dirs += [np.array((sx, sy, sz), dtype=float) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    indexes: list[int] = []
    for direction in dirs:
        if len(indexes) >= max_vertices:
            break
        norm = np.linalg.norm(direction)
        if norm <= 0.0:
            continue
        idx = int(np.argmax(points @ (direction / norm)))
        if idx not in indexes:
            indexes.append(idx)
    if len(indexes) < 4:
        order = np.argsort(np.linalg.norm(centered, axis=1))[::-1]
        for idx in order:
            if int(idx) not in indexes:
                indexes.append(int(idx))
            if len(indexes) >= 4:
                break
    return points[indexes[:max_vertices]]


def _convex_hull_faces(points: np.ndarray) -> tuple[np.ndarray, tuple[tuple[int, ...], ...]]:
    unique = _unique_rows(points)
    if len(unique) < 4 or np.linalg.matrix_rank(unique - unique.mean(axis=0), tol=1e-8) < 3:
        return _box_hull(unique)
    center = unique.mean(axis=0)
    planes: dict[tuple[float, float, float, float], set[int]] = {}
    eps = 1e-8
    for i, j, k in combinations(range(len(unique)), 3):
        normal = np.cross(unique[j] - unique[i], unique[k] - unique[i])
        length = np.linalg.norm(normal)
        if length <= eps:
            continue
        normal = normal / length
        distances = (unique - unique[i]) @ normal
        if not (np.all(distances >= -eps) or np.all(distances <= eps)):
            continue
        if (center - unique[i]) @ normal > 0.0:
            normal = -normal
            distances = -distances
        d = -float(unique[i] @ normal)
        key = (*_rounded_plane_normal(normal), round(d, 8))
        planes.setdefault(key, set()).update(
            int(index) for index, distance in enumerate(distances) if abs(float(distance)) <= 1e-7
        )
    faces = tuple(_face_polygon(unique, tuple(sorted(indexes))) for indexes in planes.values() if len(indexes) >= 3)
    faces = tuple(face for face in faces if len(face) >= 3)
    if not faces:
        return _box_hull(unique)
    used = sorted({index for face in faces for index in face})
    remap = {old: new for new, old in enumerate(used)}
    return unique[used], tuple(tuple(remap[index] for index in face) for face in faces)


def _unique_rows(points: np.ndarray) -> np.ndarray:
    seen: set[tuple[float, float, float]] = set()
    rows = []
    for point in points:
        key = (round(float(point[0]), 9), round(float(point[1]), 9), round(float(point[2]), 9))
        if key in seen:
            continue
        seen.add(key)
        rows.append(point)
    return np.asarray(rows, dtype=float)


def _rounded_plane_normal(normal: np.ndarray) -> tuple[float, float, float]:
    return (round(float(normal[0]), 8), round(float(normal[1]), 8), round(float(normal[2]), 8))


def _face_polygon(points: np.ndarray, indexes: tuple[int, ...]) -> tuple[int, ...]:
    face_points = points[list(indexes)]
    center = face_points.mean(axis=0)
    _, _, vh = np.linalg.svd(face_points - center, full_matrices=False)
    u, v = vh[0], vh[1]
    projected = tuple(
        (float((point - center) @ u), float((point - center) @ v), index)
        for point, index in zip(face_points, indexes)
    )
    hull = _convex_hull_2d(projected)
    normal = np.cross(points[hull[1]] - points[hull[0]], points[hull[2]] - points[hull[0]])
    if np.linalg.norm(normal) > 0.0 and (points.mean(axis=0) - points[hull[0]]) @ normal > 0.0:
        hull = tuple(reversed(hull))
    return hull


def _convex_hull_2d(points: tuple[tuple[float, float, int], ...]) -> tuple[int, ...]:
    ordered = sorted(points, key=lambda item: (item[0], item[1], item[2]))

    def cross(o, a, b) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float, int]] = []
    for point in ordered:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 1e-10:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float, int]] = []
    for point in reversed(ordered):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 1e-10:
            upper.pop()
        upper.append(point)
    return tuple(point[2] for point in lower[:-1] + upper[:-1])


def _box_hull(points: np.ndarray) -> tuple[np.ndarray, tuple[tuple[int, ...], ...]]:
    minimum = points.min(axis=0)
    maximum = points.max(axis=0)
    diagonal = float(np.linalg.norm(maximum - minimum))
    pad = max(diagonal * 0.005, 0.001)
    minimum = minimum - pad
    maximum = maximum + pad
    x0, y0, z0 = minimum
    x1, y1, z1 = maximum
    box = np.asarray(
        (
            (x0, y0, z0),
            (x1, y0, z0),
            (x1, y1, z0),
            (x0, y1, z0),
            (x0, y0, z1),
            (x1, y0, z1),
            (x1, y1, z1),
            (x0, y1, z1),
        ),
        dtype=float,
    )
    faces = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
    return box, faces


def _inflate_to_cover(hull_points: np.ndarray, source_points: np.ndarray) -> np.ndarray:
    center = hull_points.mean(axis=0)
    hull_radius = max(float(np.linalg.norm(point - center)) for point in hull_points)
    source_radius = max(float(np.linalg.norm(point - center)) for point in source_points)
    if hull_radius <= 0.0 or source_radius <= hull_radius:
        return hull_points
    scale = (source_radius / hull_radius) * 1.001
    return center + (hull_points - center) * scale


def _capsule_meshes(
    model: CanonicalTreeModel,
    piece: FracturePiece,
    samples: tuple[_SamplePoint, ...],
    render_mesh_name: str,
    settings: FractureCollisionSettings,
) -> tuple[MeshData, ...]:
    segments = _piece_segments(model, piece)
    if settings.capsule_simplify >= 100 or not segments:
        start, end, radius = _pca_capsule(tuple(sample.point for sample in samples))
        radius = max(radius, _distance(start, end) * settings.capsule_min_radius_ratio)
        return (_capsule_mesh(f"UCP_{render_mesh_name}_00", start, end, _padded_radius(radius, settings)),)
    ranked = sorted(
        ((_segment_score(segment, samples, settings), segment) for segment in segments),
        key=lambda item: (item[0], item[1][0]),
        reverse=True,
    )
    target = max(1, round(len(ranked) * (100 - settings.capsule_simplify) / 100))
    target = min(settings.capsule_max_count, target)
    selected = _refit_selected_segments(tuple(segment for _score, segment in ranked[:target]), samples, settings)
    return tuple(
        _capsule_mesh(f"UCP_{render_mesh_name}_{index:02d}", start, end, radius)
        for index, (start, end, radius, _score) in enumerate(selected)
    )


def _piece_segments(model: CanonicalTreeModel, piece: FracturePiece) -> tuple[tuple[str, Vector3, Vector3], ...]:
    owned = set(piece.joint_tokens)
    joints = {joint.name: joint for joint in model.skeleton}
    segments = []
    for token in piece.joint_tokens:
        joint = joints.get(token)
        parent = joints.get(joint.parent) if joint is not None and joint.parent else None
        if joint is None or parent is None or parent.name not in owned:
            continue
        segments.append((token, parent.bind_translate, joint.bind_translate))
    return tuple(segments)


def _segment_score(
    segment: tuple[str, Vector3, Vector3],
    samples: tuple[_SamplePoint, ...],
    settings: FractureCollisionSettings,
) -> float:
    token, start, end = segment
    points = tuple(sample.point for sample in samples if sample.joint_token == token)
    if not points:
        points = (start, end)
    length = _distance(start, end)
    radius = _bounded_segment_radius(points, start, end, settings)
    radius = max(radius, length * settings.capsule_min_radius_ratio, 0.001)
    return max(1.0, len(points)) * radius * max(length, 0.001)


def _refit_selected_segments(
    segments: tuple[tuple[str, Vector3, Vector3], ...],
    samples: tuple[_SamplePoint, ...],
    settings: FractureCollisionSettings,
) -> tuple[tuple[Vector3, Vector3, float, float], ...]:
    buckets: dict[str, list[Vector3]] = {token: [] for token, _start, _end in segments}
    selected_tokens = set(buckets)
    for sample in samples:
        if sample.joint_token in selected_tokens:
            buckets[sample.joint_token].append(sample.point)
    fitted = []
    for token, start, end in segments:
        points = tuple(buckets[token]) or (start, end)
        length = _distance(start, end)
        radius = _bounded_segment_radius(points, start, end, settings)
        radius = max(radius, length * settings.capsule_min_radius_ratio, 0.001)
        radius = _padded_radius(radius, settings)
        fitted.append((start, end, radius, max(1.0, len(points)) * radius * max(length, 0.001)))
    return tuple(fitted)


def _bounded_segment_radius(
    points: tuple[Vector3, ...],
    start: Vector3,
    end: Vector3,
    settings: FractureCollisionSettings,
) -> float:
    length = _distance(start, end)
    distances = sorted(_distance_to_segment(point, start, end) for point in points)
    if not distances:
        return max(length * settings.capsule_min_radius_ratio, 0.001)
    percentile_index = min(len(distances) - 1, max(0, round((len(distances) - 1) * 0.82)))
    radius = distances[percentile_index]
    max_radius = max(length * 0.32, length * settings.capsule_min_radius_ratio, 0.001)
    return min(radius, max_radius)


def _padded_radius(radius: float, settings: FractureCollisionSettings) -> float:
    return radius * _CAPSULE_RADIUS_MODEL_SCALE * settings.capsule_scale * (1.0 + settings.capsule_radius_padding)


def _pca_capsule(points: tuple[Vector3, ...]) -> tuple[Vector3, Vector3, float]:
    arr = _np_points(points)
    center = arr.mean(axis=0)
    centered = arr - center
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    axis = vh[0]
    projections = centered @ axis
    start = center + axis * float(projections.min())
    end = center + axis * float(projections.max())
    radius = max(float(np.linalg.norm(point - (start + axis * np.clip((point - start) @ axis, 0.0, np.linalg.norm(end - start))))) for point in arr)
    return _vector3(start), _vector3(end), max(radius, 0.001)


def _minimal_enclosing_sphere(points: tuple[Vector3, ...]) -> tuple[Vector3, float]:
    arr = _np_points(points)
    first = arr[0]
    p0 = arr[int(np.argmax(np.linalg.norm(arr - first, axis=1)))]
    p1 = arr[int(np.argmax(np.linalg.norm(arr - p0, axis=1)))]
    center = (p0 + p1) * 0.5
    radius = float(np.linalg.norm(p1 - center))
    for point in arr:
        distance = float(np.linalg.norm(point - center))
        if distance <= radius:
            continue
        new_radius = (radius + distance) * 0.5
        center = center + (point - center) * ((new_radius - radius) / distance)
        radius = new_radius
    return _vector3(center), radius


def _sphere_mesh(name: str, center: Vector3, radius: float) -> MeshData:
    rings = 8
    segments = 12
    points = [Vector3(center.x, center.y + radius, center.z)]
    for ring in range(1, rings):
        phi = math.pi * ring / rings
        y = center.y + math.cos(phi) * radius
        r = math.sin(phi) * radius
        for segment in range(segments):
            theta = 2.0 * math.pi * segment / segments
            points.append(Vector3(center.x + math.cos(theta) * r, y, center.z + math.sin(theta) * r))
    points.append(Vector3(center.x, center.y - radius, center.z))
    bottom = len(points) - 1
    faces: list[tuple[int, ...]] = []
    for segment in range(segments):
        faces.append((0, 1 + segment, 1 + ((segment + 1) % segments)))
    for ring in range(rings - 2):
        row = 1 + ring * segments
        next_row = row + segments
        for segment in range(segments):
            faces.append((row + segment, next_row + segment, next_row + ((segment + 1) % segments), row + ((segment + 1) % segments)))
    last_row = 1 + (rings - 2) * segments
    for segment in range(segments):
        faces.append((last_row + ((segment + 1) % segments), last_row + segment, bottom))
    return _mesh_from_faces(name, tuple(points), tuple(faces))


def _capsule_mesh(name: str, start: Vector3, end: Vector3, radius: float) -> MeshData:
    axis = _normalize(Vector3(end.x - start.x, end.y - start.y, end.z - start.z))
    u, v = _basis(axis)
    segments = 12
    hemisphere_steps = 4
    rings: list[tuple[Vector3, ...]] = []
    for step in range(1, hemisphere_steps + 1):
        phi = -math.pi * 0.5 + step * (math.pi * 0.5 / hemisphere_steps)
        center = Vector3(
            start.x + axis.x * math.sin(phi) * radius,
            start.y + axis.y * math.sin(phi) * radius,
            start.z + axis.z * math.sin(phi) * radius,
        )
        ring_radius = math.cos(phi) * radius
        rings.append(
            tuple(
                Vector3(
                    center.x + (math.cos(theta) * u.x + math.sin(theta) * v.x) * ring_radius,
                    center.y + (math.cos(theta) * u.y + math.sin(theta) * v.y) * ring_radius,
                    center.z + (math.cos(theta) * u.z + math.sin(theta) * v.z) * ring_radius,
                )
                for theta in (2.0 * math.pi * segment / segments for segment in range(segments))
            )
        )
    for step in range(0, hemisphere_steps):
        phi = step * (math.pi * 0.5 / hemisphere_steps)
        center = Vector3(
            end.x + axis.x * math.sin(phi) * radius,
            end.y + axis.y * math.sin(phi) * radius,
            end.z + axis.z * math.sin(phi) * radius,
        )
        ring_radius = math.cos(phi) * radius
        rings.append(
            tuple(
                Vector3(
                    center.x + (math.cos(theta) * u.x + math.sin(theta) * v.x) * ring_radius,
                    center.y + (math.cos(theta) * u.y + math.sin(theta) * v.y) * ring_radius,
                    center.z + (math.cos(theta) * u.z + math.sin(theta) * v.z) * ring_radius,
                )
                for theta in (2.0 * math.pi * segment / segments for segment in range(segments))
            )
        )
    bottom = Vector3(start.x - axis.x * radius, start.y - axis.y * radius, start.z - axis.z * radius)
    top = Vector3(end.x + axis.x * radius, end.y + axis.y * radius, end.z + axis.z * radius)
    points = [bottom, *(point for ring in rings for point in ring), top]
    top_index = len(points) - 1
    faces: list[tuple[int, ...]] = []
    for segment in range(segments):
        nxt = (segment + 1) % segments
        faces.append((0, 1 + segment, 1 + nxt))
    for ring_index in range(len(rings) - 1):
        row = 1 + ring_index * segments
        next_row = row + segments
        for segment in range(segments):
            nxt = (segment + 1) % segments
            faces.append((row + segment, row + nxt, next_row + nxt, next_row + segment))
    last_row = 1 + (len(rings) - 1) * segments
    for segment in range(segments):
        nxt = (segment + 1) % segments
        faces.append((top_index, last_row + nxt, last_row + segment))
    return _mesh_from_faces(name, tuple(points), tuple(faces))


def _mesh_from_triangles(name: str, points: np.ndarray, triangles: np.ndarray) -> MeshData:
    return _mesh_from_faces(
        name,
        tuple(_vector3(point) for point in points),
        tuple(tuple(int(value) for value in triangle) for triangle in triangles),
    )


def _mesh_from_faces(name: str, points: tuple[Vector3, ...], faces: tuple[tuple[int, ...], ...]) -> MeshData:
    counts = array("i", (len(face) for face in faces))
    indices = array("i")
    for face in faces:
        indices.extend(face)
    return MeshData(
        name=make_stable_prim_name(name, fallback="Collision"),
        points=points,
        face_vertex_counts=tuple(counts),
        face_vertex_indices=tuple(indices),
    )


def _distance_to_segment(point: Vector3, start: Vector3, end: Vector3) -> float:
    ax, ay, az = point.x - start.x, point.y - start.y, point.z - start.z
    bx, by, bz = end.x - start.x, end.y - start.y, end.z - start.z
    denom = bx * bx + by * by + bz * bz
    if denom <= 0.0:
        return _distance(point, start)
    t = max(0.0, min(1.0, (ax * bx + ay * by + az * bz) / denom))
    closest = Vector3(start.x + bx * t, start.y + by * t, start.z + bz * t)
    return _distance(point, closest)


def _distance(a: Vector3, b: Vector3) -> float:
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def _normalize(vector: Vector3) -> Vector3:
    length = math.sqrt(vector.x * vector.x + vector.y * vector.y + vector.z * vector.z)
    if length <= 0.0:
        return Vector3(0.0, 1.0, 0.0)
    return Vector3(vector.x / length, vector.y / length, vector.z / length)


def _basis(axis: Vector3) -> tuple[Vector3, Vector3]:
    helper = Vector3(1.0, 0.0, 0.0) if abs(axis.x) < 0.8 else Vector3(0.0, 1.0, 0.0)
    u = _normalize(_cross(axis, helper))
    return u, _normalize(_cross(axis, u))


def _cross(a: Vector3, b: Vector3) -> Vector3:
    return Vector3(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x)


def _np_points(points: tuple[Vector3, ...]) -> np.ndarray:
    return np.asarray([(point.x, point.y, point.z) for point in points], dtype=float)


def _vector3(values) -> Vector3:
    return Vector3(float(values[0]), float(values[1]), float(values[2]))


__all__ = [
    "CollisionMeshSet",
    "FractureCollisionMode",
    "FractureCollisionSettings",
    "build_fracture_collision_mesh_sets",
    "build_fracture_collision_meshes",
    "collision_render_mesh_name",
    "validated_collision_settings",
]
