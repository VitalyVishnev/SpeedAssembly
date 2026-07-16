"""Geometry helpers shared by fracture export and preview.

Layer: domain/application boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import math
import struct

import numpy as np

from .fracture_service import (
    FractureError,
    FracturePiece,
    FracturePlan,
    FractureSettings,
    format_manual_segment_cut_token,
    plan_fracture,
)
from .geometry_buffers import iter_face_ranges
from .models import CanonicalTreeModel, Color4, MeshData, MeshSection, ValidationIssue, Vector2, Vector3


_CUT_EPSILON = 1e-8
_NOISE_AMPLITUDE_RATIO = 0.35
_AUTO_BRANCH_CUT_OFFSETS = (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80)
_NOISE_ATTENUATION_FACTORS = (1.0, 0.75, 0.5, 0.25, 0.0)


@dataclass(frozen=True)
class CapSourceContext:
    face_ranges: tuple[tuple[int, int, int], ...]
    source_edge_faces: dict[tuple[int, int], tuple[int, ...]]
    material_by_source_face: dict[int, int]


@dataclass(frozen=True)
class CutSurface:
    token: str
    parent_piece_index: int
    child_piece_index: int
    origin: Vector3
    normal: Vector3
    tangent: Vector3
    bitangent: Vector3
    radius: float
    amplitude: float
    wavelength: float
    seed: int
    one_sided: bool = False

    def signed_distance(self, point: Vector3) -> float:
        offset = _subtract(point, self.origin)
        axial = _dot(offset, self.normal)
        if self.amplitude <= 0.0:
            return axial
        u = _dot(offset, self.tangent) / self.wavelength
        v = _dot(offset, self.bitangent) / (self.wavelength * 2.5)
        noise = _value_noise(u, v, self.seed)
        if self.one_sided:
            noise = (noise + 1.0) * 0.5
        return axial - self.amplitude * noise


@dataclass(frozen=True)
class FractureGeometryPiece:
    piece: FracturePiece
    base_mesh: MeshData


@dataclass(frozen=True)
class FractureGeometryResult:
    plan: FracturePlan
    pieces: tuple[FractureGeometryPiece, ...]
    cut_surfaces: tuple[CutSurface, ...]


class _AutomaticCutGeometryError(FractureError):
    def __init__(self, cut_token: str, message: str) -> None:
        super().__init__(message)
        self.cut_token = cut_token


@dataclass(frozen=True)
class _Vertex:
    point: Vector3
    uv: Vector2 | None
    secondary_uv: Vector2 | None
    color: Color4 | None
    joint_indices: tuple[int, ...]
    joint_weights: tuple[float, ...]


@dataclass(frozen=True)
class _Polygon:
    vertices: tuple[_Vertex, ...]
    material_id: int
    source_face_index: int


@dataclass(frozen=True)
class _CapSegment:
    surface_token: str
    start: _Vertex
    end: _Vertex
    material_id: int


@dataclass(frozen=True)
class _GeometryContext:
    source_polygons: tuple[_Polygon, ...] | None
    base_points_array: np.ndarray
    face_vertex_indices_array: np.ndarray
    face_vertex_starts_array: np.ndarray
    base_face_indices_by_subtree: dict[str, frozenset[int]]
    base_face_indices_by_joint: dict[str, frozenset[int]]
    source_seed: bytes


def build_fracture_geometry(
    model: CanonicalTreeModel,
    plan: FracturePlan,
    settings: FractureSettings,
    *,
    cap_material_id: int | None = None,
    geometry_context: _GeometryContext | None = None,
) -> FractureGeometryResult:
    """Build authoritative per-piece Base Mesh geometry for preview and export."""
    mesh = model.base_mesh
    if mesh is None:
        raise FractureError("Fracture geometry requires a base mesh.")
    if not settings.noisy_cut_enabled:
        pieces = tuple(
            FractureGeometryPiece(
                piece=piece,
                base_mesh=slice_mesh_faces(
                    mesh,
                    piece.base_face_indices,
                    name=f"{piece.name}_BaseMesh",
                    generate_caps=settings.generate_caps,
                    cap_material_id=cap_material_id,
                ),
            )
            for piece in plan.pieces
        )
        return FractureGeometryResult(plan=plan, pieces=pieces, cut_surfaces=())
    if not plan.selected_cut_sites:
        pieces = tuple(
            FractureGeometryPiece(
                piece=piece,
                base_mesh=slice_mesh_faces(
                    mesh,
                    piece.base_face_indices,
                    name=f"{piece.name}_BaseMesh",
                    generate_caps=False,
                ),
            )
            for piece in plan.pieces
        )
        return FractureGeometryResult(plan=plan, pieces=pieces, cut_surfaces=())

    context = geometry_context or _build_geometry_context(model)
    source_polygons = context.source_polygons or _source_polygons(mesh)
    polygons_by_piece = _source_polygons_by_piece(plan, source_polygons)
    surfaces: list[CutSurface] = []
    geometry_diagnostics: list[ValidationIssue] = []
    cap_segments_by_piece: dict[int, list[_CapSegment]] = {piece.index: [] for piece in plan.pieces}
    piece_index_by_cut = {piece.cut_joint_token: piece.index for piece in plan.pieces if piece.cut_joint_token}
    joint_by_name = {joint.name: joint for joint in model.skeleton}
    source_seed = context.source_seed

    for cut_site in plan.selected_cut_sites:
        parent_token = cut_site.parent_joint_token
        child_token = cut_site.child_joint_token or cut_site.joint_token
        parent_joint = joint_by_name.get(parent_token or "")
        child_joint = joint_by_name.get(child_token)
        if child_joint is None:
            raise FractureError(f"Fracture cut {cut_site.joint_token} references missing child joint {child_token}.")
        if parent_joint is None:
            parent_token = child_joint.parent
            parent_joint = joint_by_name.get(parent_token or "")
        is_independent_stem = parent_joint is None and cut_site.reason == "auto_stem_length"
        if parent_joint is None and not is_independent_stem:
            raise FractureError(f"Fracture cut {cut_site.joint_token} has no valid parent joint.")
        child_piece_index = piece_index_by_cut.get(cut_site.joint_token)
        if child_piece_index is None:
            raise FractureError(f"Fracture cut {cut_site.joint_token} has no Fracture Piece.")
        parent_piece_index = 0 if is_independent_stem else _piece_index_for_joint(plan.pieces, parent_joint.name)
        parent_candidates = polygons_by_piece[parent_piece_index]
        child_candidates = polygons_by_piece[child_piece_index]
        candidates = parent_candidates + child_candidates
        local_source_faces = context.base_face_indices_by_subtree.get(child_joint.name, frozenset())
        if (
            cut_site.kind == "manual_segment"
            or cut_site.reason in ("stump_piece", "auto_stem_length")
        ) and parent_joint is not None:
            local_source_faces |= context.base_face_indices_by_joint.get(parent_joint.name, frozenset())
        candidate_source_indices = {
            polygon.source_face_index
            for polygon in candidates
            if polygon.source_face_index >= 0 and polygon.source_face_index in local_source_faces
        }
        offset_candidates: tuple[float | None, ...] = (
            _AUTO_BRANCH_CUT_OFFSETS
            if cut_site.reason == "auto_branch_length"
            else (None,)
        )
        last_cut_error: _AutomaticCutGeometryError | None = None
        for auto_branch_offset in offset_candidates:
            origin, normal = _cut_origin_and_normal(
                cut_site,
                parent_joint,
                child_joint,
                auto_branch_offset=auto_branch_offset,
            )
            tangent, bitangent = _stable_basis(normal)
            flat_crossing_faces, axial_face_mins, axial_face_maxs = _flat_crossing_faces(
                context,
                origin,
                normal,
                candidate_source_indices,
            )
            radius_polygons = [
                polygon
                for polygon in candidates
                if polygon.source_face_index < 0 or polygon.source_face_index in flat_crossing_faces
            ]
            try:
                radius = _cut_radius(radius_polygons, origin, normal, cut_site.joint_token)
                requested_surface = CutSurface(
                    token=cut_site.joint_token,
                    parent_piece_index=parent_piece_index,
                    child_piece_index=child_piece_index,
                    origin=origin,
                    normal=normal,
                    tangent=tangent,
                    bitangent=bitangent,
                    radius=radius,
                    amplitude=radius * _NOISE_AMPLITUDE_RATIO * float(settings.noisy_cut_intensity),
                    wavelength=max(radius * float(settings.noisy_cut_scale), _CUT_EPSILON),
                    seed=_cut_seed(source_seed, cut_site.joint_token),
                    one_sided=cut_site.kind != "manual_segment",
                )
                surface, affected_source_faces = _resolve_safe_cut_surface(
                    requested_surface,
                    candidates,
                    candidate_source_indices,
                    axial_face_mins,
                    axial_face_maxs,
                    generate_caps=settings.generate_caps,
                )
            except _AutomaticCutGeometryError as exc:
                last_cut_error = exc
                continue
            requested_amplitude = requested_surface.amplitude
            if auto_branch_offset is not None and auto_branch_offset != _AUTO_BRANCH_CUT_OFFSETS[0]:
                geometry_diagnostics.append(
                    ValidationIssue(
                        severity="warning",
                        code="fracture_auto_cut_shifted",
                        message=(
                            f"Automatic cut {surface.token} moved to {auto_branch_offset:.0%} of its first child bone "
                            "to use a safely separable mesh cross-section."
                        ),
                    )
                )
            break
        else:
            raise last_cut_error or _AutomaticCutGeometryError(
                cut_site.joint_token,
                f"Fracture cut {cut_site.joint_token} has no safe cross-section.",
            )
        if surface.amplitude < requested_amplitude - _CUT_EPSILON:
            factor = 0.0 if requested_amplitude <= _CUT_EPSILON else surface.amplitude / requested_amplitude
            geometry_diagnostics.append(
                ValidationIssue(
                    severity="warning",
                    code="fracture_noise_attenuated",
                    message=(
                        f"Noisy cut {surface.token} used {factor:.0%} of the requested Cut Intensity "
                        "to preserve a safely separable mesh cross-section."
                    ),
                )
            )
        parent_polygons: list[_Polygon] = []
        child_polygons: list[_Polygon] = []
        crossing_count = 0
        for original_piece_index, polygon in (
            *((parent_piece_index, polygon) for polygon in parent_candidates),
            *((child_piece_index, polygon) for polygon in child_candidates),
        ):
            if polygon.source_face_index >= 0 and polygon.source_face_index not in affected_source_faces:
                (parent_polygons if original_piece_index == parent_piece_index else child_polygons).append(polygon)
                continue
            negative, positive, intersections = _split_polygon(polygon, surface)
            if negative is not None:
                parent_polygons.append(negative)
            if positive is not None:
                child_polygons.append(positive)
            if intersections:
                crossing_count += 1
                start, end = intersections
                cap_segments_by_piece[parent_piece_index].append(
                    _CapSegment(
                        surface_token=surface.token,
                        start=start,
                        end=end,
                        material_id=polygon.material_id,
                    )
                )
                cap_segments_by_piece[child_piece_index].append(
                    _CapSegment(
                        surface_token=surface.token,
                        start=end,
                        end=start,
                        material_id=polygon.material_id,
                    )
                )
        if crossing_count == 0:
            raise _AutomaticCutGeometryError(
                cut_site.joint_token,
                f"Fracture cut {cut_site.joint_token} does not intersect geometry owned by its parent/child subtree.",
            )
        polygons_by_piece[parent_piece_index] = parent_polygons
        polygons_by_piece[child_piece_index] = child_polygons
        surfaces.append(surface)

    result_pieces: list[FractureGeometryPiece] = []
    for piece in plan.pieces:
        polygons = list(polygons_by_piece[piece.index])
        if not polygons:
            raise FractureError(f"Fracture piece {piece.name} has no clipped Base Mesh polygons.")
        if settings.generate_caps:
            polygons.extend(
                _cap_polygons(
                    cap_segments_by_piece[piece.index],
                    tuple(surface for surface in surfaces if piece.index in (surface.parent_piece_index, surface.child_piece_index)),
                    piece_index=piece.index,
                    cap_material_id=cap_material_id,
                )
            )
        result_pieces.append(
            FractureGeometryPiece(
                piece=piece,
                base_mesh=_mesh_from_polygons(f"{piece.name}_BaseMesh", polygons, mesh.skel_element_size),
            )
        )
    if geometry_diagnostics:
        plan = replace(plan, diagnostics=plan.diagnostics + tuple(geometry_diagnostics))
    return FractureGeometryResult(plan=plan, pieces=tuple(result_pieces), cut_surfaces=tuple(surfaces))


def _resolve_safe_cut_surface(
    requested_surface: CutSurface,
    candidates: list[_Polygon],
    candidate_source_indices: set[int],
    axial_face_mins: np.ndarray,
    axial_face_maxs: np.ndarray,
    *,
    generate_caps: bool,
) -> tuple[CutSurface, set[int]]:
    """Reduce only the cut shape when noise cannot split this fixed fracture site safely."""
    last_error: FractureError | None = None
    for factor in _NOISE_ATTENUATION_FACTORS:
        surface = replace(requested_surface, amplitude=requested_surface.amplitude * factor)
        minimum_axial = 0.0 if surface.one_sided else -surface.amplitude
        affected_source_faces = {
            int(face_index)
            for face_index in np.flatnonzero(
                (axial_face_mins <= surface.amplitude) & (axial_face_maxs >= minimum_axial)
            )
            if int(face_index) in candidate_source_indices
        }
        segments: list[_CapSegment] = []
        crossing_count = 0
        try:
            for polygon in candidates:
                if polygon.source_face_index >= 0 and polygon.source_face_index not in affected_source_faces:
                    continue
                _negative, _positive, intersections = _split_polygon(polygon, surface)
                if intersections:
                    crossing_count += 1
                    start, end = intersections
                    segments.append(
                        _CapSegment(
                            surface_token=surface.token,
                            start=start,
                            end=end,
                            material_id=polygon.material_id,
                        )
                    )
            if crossing_count == 0:
                raise _AutomaticCutGeometryError(
                    surface.token,
                    f"Fracture cut {surface.token} does not intersect geometry owned by its parent/child subtree.",
                )
            if generate_caps:
                for loop in _cap_loops(segments, surface):
                    projected = tuple(_project_to_surface(vertex.point, surface) for vertex in loop)
                    _raise_for_self_intersection(projected, surface.token)
                    _triangulate_loop(projected, surface.token)
        except FractureError as exc:
            last_error = exc
            continue
        return surface, affected_source_faces
    if isinstance(last_error, _AutomaticCutGeometryError):
        raise last_error
    raise _AutomaticCutGeometryError(
        requested_surface.token,
        str(last_error or f"Fracture cut {requested_surface.token} has no safe cross-section."),
    )


def prepare_fracture_geometry(
    model: CanonicalTreeModel,
    settings: FractureSettings,
    *,
    analysis_cache=None,
    cap_material_id: int | None = None,
) -> FractureGeometryResult:
    """Build authoritative geometry without changing the planner's cut structure."""
    context = _build_geometry_context(model, analysis_cache=analysis_cache)
    if settings.generate_caps:
        context = replace(context, source_polygons=_source_polygons(model.base_mesh))
    plan = plan_fracture(model, settings, analysis_cache=analysis_cache)
    if plan.selected_cut_sites and context.source_polygons is None:
        context = replace(context, source_polygons=_source_polygons(model.base_mesh))
    try:
        return build_fracture_geometry(
            model,
            plan,
            settings,
            cap_material_id=cap_material_id,
            geometry_context=context,
        )
    except _AutomaticCutGeometryError as exc:
        failed_cut = next((cut for cut in plan.selected_cut_sites if cut.joint_token == exc.cut_token), None)
        if failed_cut is None or failed_cut.reason != "manual_pinned_segment":
            raise FractureError(str(exc)) from exc
        snapped = _snap_manual_segment_cut(
            model,
            settings,
            failed_cut,
            cap_material_id=cap_material_id,
            analysis_cache=analysis_cache,
            geometry_context=context,
        )
        if snapped is None:
            raise FractureError(
                f"Manual cut {failed_cut.joint_token} has no closed Base Mesh cross-section near the selected point. "
                "Choose a different skeleton segment."
            ) from exc
        return snapped


def _snap_manual_segment_cut(
    model: CanonicalTreeModel,
    settings: FractureSettings,
    failed_cut,
    *,
    cap_material_id: int | None,
    analysis_cache,
    geometry_context: _GeometryContext,
) -> FractureGeometryResult | None:
    requested_t = float(failed_cut.segment_t)
    candidates = sorted((value / 10.0 for value in range(1, 10)), key=lambda value: (abs(value - requested_t), value))
    for candidate_t in candidates:
        if abs(candidate_t - requested_t) <= 1e-6:
            continue
        candidate_token = format_manual_segment_cut_token(
            failed_cut.parent_joint_token,
            failed_cut.child_joint_token,
            candidate_t,
        )
        candidate_tokens = tuple(
            candidate_token if token == failed_cut.joint_token else token
            for token in settings.pinned_cut_joint_tokens
        )
        candidate_settings = replace(settings, pinned_cut_joint_tokens=candidate_tokens)
        validation_settings = replace(
            candidate_settings,
            target_piece_count=0,
            force_stump_piece=False,
            separate_stems=False,
            pinned_cut_joint_tokens=(candidate_token,),
        )
        try:
            validation_plan = plan_fracture(model, validation_settings, analysis_cache=analysis_cache)
            build_fracture_geometry(
                model,
                validation_plan,
                validation_settings,
                cap_material_id=cap_material_id,
                geometry_context=geometry_context,
            )
            candidate_plan = plan_fracture(model, candidate_settings, analysis_cache=analysis_cache)
            result = build_fracture_geometry(
                model,
                candidate_plan,
                candidate_settings,
                cap_material_id=cap_material_id,
                geometry_context=geometry_context,
            )
        except FractureError:
            continue
        diagnostic = ValidationIssue(
            severity="warning",
            code="fracture_manual_cut_snapped",
            message=(
                f"Manual cut {failed_cut.joint_token} was snapped to {candidate_token}, "
                "the nearest tested position with a closed Base Mesh cross-section."
            ),
        )
        return replace(result, plan=replace(result.plan, diagnostics=result.plan.diagnostics + (diagnostic,)))
    return None


def _source_polygons_by_piece(
    plan: FracturePlan,
    source_polygons: tuple[_Polygon, ...],
) -> dict[int, list[_Polygon]]:
    owner_by_face: dict[int, int] = {}
    for piece in plan.pieces:
        for face_index in piece.base_face_indices:
            if face_index in owner_by_face:
                raise FractureError(f"Base Mesh face {face_index} belongs to more than one Fracture Piece.")
            owner_by_face[face_index] = piece.index
    polygons_by_piece = {piece.index: [] for piece in plan.pieces}
    for face_index, polygon in enumerate(source_polygons):
        owner = owner_by_face.get(face_index)
        if owner is None:
            raise FractureError(f"Base Mesh face {face_index} has no Fracture Piece ownership.")
        polygons_by_piece[owner].append(polygon)
    return polygons_by_piece


def _source_polygons(mesh: MeshData) -> tuple[_Polygon, ...]:
    _validate_slice_mesh_shape(mesh)
    material_by_face = _material_by_source_face(mesh)
    use_uvs = len(mesh.uv_coords) == len(mesh.face_vertex_indices)
    use_secondary_uvs = len(mesh.secondary_uv_coords) == len(mesh.face_vertex_indices)
    use_colors = len(mesh.vertex_colors) == len(mesh.face_vertex_indices)
    polygons: list[_Polygon] = []
    for face_index, start, end in iter_face_ranges(mesh.face_vertex_counts):
        vertices: list[_Vertex] = []
        for slot in range(start, end):
            point_index = int(mesh.face_vertex_indices[slot])
            if point_index < 0 or point_index >= len(mesh.points):
                raise FractureError(f"Base Mesh face {face_index} references point {point_index} outside the mesh.")
            joint_start = point_index * mesh.skel_element_size
            joint_end = joint_start + mesh.skel_element_size
            vertices.append(
                _Vertex(
                    point=mesh.points[point_index],
                    uv=mesh.uv_coords[slot] if use_uvs else None,
                    secondary_uv=mesh.secondary_uv_coords[slot] if use_secondary_uvs else None,
                    color=mesh.vertex_colors[slot] if use_colors else None,
                    joint_indices=tuple(int(value) for value in mesh.skel_joint_indices[joint_start:joint_end]),
                    joint_weights=tuple(float(value) for value in mesh.skel_joint_weights[joint_start:joint_end]),
                )
            )
        if len(vertices) < 3:
            raise FractureError(f"Base Mesh face {face_index} has fewer than three vertices.")
        polygons.append(
            _Polygon(
                vertices=tuple(vertices),
                material_id=material_by_face.get(face_index, 0),
                source_face_index=face_index,
            )
        )
    return tuple(polygons)


def _build_geometry_context(model: CanonicalTreeModel, *, analysis_cache=None) -> _GeometryContext:
    if model.base_mesh is None:
        raise FractureError("Fracture geometry requires a base mesh.")
    parent_by_joint = {joint.name: joint.parent for joint in model.skeleton}
    point_joint_tokens: list[str] = []
    mesh = model.base_mesh
    if mesh.skel_element_size > 0 and mesh.skel_joint_indices:
        joint_names = tuple(joint.name for joint in model.skeleton)
        for point_index in range(len(mesh.points)):
            slot = point_index * mesh.skel_element_size
            if slot >= len(mesh.skel_joint_indices):
                break
            joint_index = int(mesh.skel_joint_indices[slot])
            token = joint_names[joint_index] if 0 <= joint_index < len(joint_names) else ""
            point_joint_tokens.append(token)
    base_face_indices_by_joint: dict[str, list[int]] = {}
    cached_owners = getattr(analysis_cache, "base_face_owner_by_index", None)
    if cached_owners is not None and len(cached_owners) == len(mesh.face_vertex_counts):
        for face_index, owner in enumerate(cached_owners):
            if owner:
                base_face_indices_by_joint.setdefault(owner, []).append(face_index)
    else:
        for face_index, start, end in iter_face_ranges(mesh.face_vertex_counts):
            tokens = tuple(point_joint_tokens[int(mesh.face_vertex_indices[slot])] for slot in range(start, end))
            if not tokens:
                continue
            counts: dict[str, int] = {}
            for token in tokens:
                counts[token] = counts.get(token, 0) + 1
            owner = min(counts, key=lambda token: (-counts[token], token))
            base_face_indices_by_joint.setdefault(owner, []).append(face_index)
    base_face_indices_by_subtree = _indices_by_subtree(parent_by_joint, base_face_indices_by_joint)
    return _GeometryContext(
        source_polygons=None,
        base_points_array=np.asarray(
            [(point.x, point.y, point.z) for point in model.base_mesh.points],
            dtype=np.float64,
        ),
        face_vertex_indices_array=np.asarray(model.base_mesh.face_vertex_indices, dtype=np.int64),
        face_vertex_starts_array=np.concatenate(
            (
                np.asarray((0,), dtype=np.int64),
                np.cumsum(np.asarray(model.base_mesh.face_vertex_counts[:-1], dtype=np.int64)),
            )
        ),
        base_face_indices_by_subtree={
            token: frozenset(indices) for token, indices in base_face_indices_by_subtree.items()
        },
        base_face_indices_by_joint={
            token: frozenset(indices) for token, indices in base_face_indices_by_joint.items()
        },
        source_seed=_model_seed(model),
    )


def _indices_by_subtree(
    parent_by_joint: dict[str, str | None],
    direct_indices: dict[str, list[int]],
) -> dict[str, list[int]]:
    depths: dict[str, int] = {}

    def depth(token: str) -> int:
        cached = depths.get(token)
        if cached is not None:
            return cached
        parent = parent_by_joint.get(token)
        value = 0 if parent is None else depth(parent) + 1
        depths[token] = value
        return value

    accumulated = {token: list(direct_indices.get(token, ())) for token in parent_by_joint}
    for token in sorted(parent_by_joint, key=lambda item: (-depth(item), item)):
        parent = parent_by_joint[token]
        if parent is not None:
            accumulated[parent].extend(accumulated[token])
    return {token: sorted(indices) for token, indices in accumulated.items() if indices}


def _flat_crossing_faces(
    context: _GeometryContext,
    origin: Vector3,
    normal: Vector3,
    candidate_source_indices: set[int],
) -> tuple[set[int], np.ndarray, np.ndarray]:
    origin_array = np.asarray((origin.x, origin.y, origin.z), dtype=np.float64)
    normal_array = np.asarray((normal.x, normal.y, normal.z), dtype=np.float64)
    point_distances = (context.base_points_array - origin_array) @ normal_array
    corner_distances = point_distances[context.face_vertex_indices_array]
    face_mins = np.minimum.reduceat(corner_distances, context.face_vertex_starts_array)
    face_maxs = np.maximum.reduceat(corner_distances, context.face_vertex_starts_array)
    crossing = {
        int(face_index)
        for face_index in np.flatnonzero((face_mins <= 0.0) & (face_maxs >= 0.0))
        if int(face_index) in candidate_source_indices
    }
    return crossing, face_mins, face_maxs


def _piece_index_for_joint(pieces: tuple[FracturePiece, ...], joint_token: str) -> int:
    matches = tuple(piece.index for piece in pieces if joint_token in piece.joint_tokens)
    if len(matches) != 1:
        raise FractureError(
            f"Fracture parent joint {joint_token} must belong to exactly one Fracture Piece, got {len(matches)}."
        )
    return matches[0]


def _cut_radius(polygons: list[_Polygon], origin: Vector3, normal: Vector3, token: str) -> float:
    radial_distances: list[float] = []
    for polygon in polygons:
        vertices = polygon.vertices
        distances = tuple(_dot(_subtract(vertex.point, origin), normal) for vertex in vertices)
        for index, start in enumerate(vertices):
            end = vertices[(index + 1) % len(vertices)]
            d0 = distances[index]
            d1 = distances[(index + 1) % len(vertices)]
            if d0 * d1 > 0.0:
                continue
            if abs(d0 - d1) <= _CUT_EPSILON:
                point = start.point
            else:
                point = _lerp(start.point, end.point, d0 / (d0 - d1))
            offset = _subtract(point, origin)
            axial = _scale(normal, _dot(offset, normal))
            radial_distances.append(_length(_subtract(offset, axial)))
    radius = max(radial_distances, default=0.0)
    if radius <= _CUT_EPSILON:
        raise _AutomaticCutGeometryError(
            token,
            f"Fracture cut {token} has no non-degenerate Base Mesh intersection.",
        )
    return radius


def _split_polygon(
    polygon: _Polygon,
    surface: CutSurface,
) -> tuple[_Polygon | None, _Polygon | None, tuple[_Vertex, _Vertex] | ()]:
    distances = tuple(surface.signed_distance(vertex.point) for vertex in polygon.vertices)
    has_negative = any(distance < -_CUT_EPSILON for distance in distances)
    has_positive = any(distance > _CUT_EPSILON for distance in distances)
    edge_intersections: dict[int, _Vertex] = {}
    for index, start in enumerate(polygon.vertices):
        end = polygon.vertices[(index + 1) % len(polygon.vertices)]
        roots = _edge_surface_roots(start, end, surface)
        if len(roots) > 1:
            raise _AutomaticCutGeometryError(
                surface.token,
                f"Fracture cut {surface.token} intersects source face {polygon.source_face_index} "
                f"edge {index} more than once.",
            )
        if roots:
            edge_intersections[index] = _interpolate_vertex(start, end, roots[0])
    if not has_negative:
        if edge_intersections and has_positive:
            raise _AutomaticCutGeometryError(
                surface.token,
                f"Fracture cut {surface.token} touches source face {polygon.source_face_index} "
                "without a safely separable negative side.",
            )
        return None, polygon, ()
    if not has_positive:
        if edge_intersections and has_negative:
            raise _AutomaticCutGeometryError(
                surface.token,
                f"Fracture cut {surface.token} touches source face {polygon.source_face_index} "
                "without a safely separable positive side.",
            )
        return polygon, None, ()

    negative_vertices = _clip_polygon_vertices(
        polygon.vertices,
        distances,
        edge_intersections,
        keep_positive=False,
    )
    positive_vertices = _clip_polygon_vertices(
        polygon.vertices,
        distances,
        edge_intersections,
        keep_positive=True,
    )
    intersections = _unique_vertices(list(edge_intersections.values()))
    if len(intersections) != 2:
        raise _AutomaticCutGeometryError(
            surface.token,
            f"Fracture cut {surface.token} intersects source face {polygon.source_face_index} in "
            f"{len(intersections)} points; exactly two are required.",
        )
    negative = (
        _Polygon(tuple(negative_vertices), polygon.material_id, polygon.source_face_index)
        if len(negative_vertices) >= 3
        else None
    )
    positive = (
        _Polygon(tuple(positive_vertices), polygon.material_id, polygon.source_face_index)
        if len(positive_vertices) >= 3
        else None
    )
    return negative, positive, (intersections[0], intersections[1])


def _clip_polygon_vertices(
    vertices: tuple[_Vertex, ...],
    distances: tuple[float, ...],
    edge_intersections: dict[int, _Vertex],
    *,
    keep_positive: bool,
) -> list[_Vertex]:
    output: list[_Vertex] = []
    for index, current in enumerate(vertices):
        previous_index = (index - 1) % len(vertices)
        previous = vertices[previous_index]
        current_distance = distances[index]
        previous_distance = distances[previous_index]
        current_inside = current_distance >= -_CUT_EPSILON if keep_positive else current_distance <= _CUT_EPSILON
        previous_inside = previous_distance >= -_CUT_EPSILON if keep_positive else previous_distance <= _CUT_EPSILON
        if current_inside != previous_inside:
            intersection = edge_intersections.get(previous_index)
            if intersection is None:
                raise FractureError("Fracture edge changes side without one resolved surface intersection.")
            output.append(intersection)
        if current_inside:
            output.append(current)
    return _unique_vertices(output)


def _unique_vertices(vertices: list[_Vertex]) -> list[_Vertex]:
    unique: list[_Vertex] = []
    for vertex in vertices:
        if unique and _distance(unique[-1].point, vertex.point) <= _CUT_EPSILON:
            continue
        unique.append(vertex)
    if len(unique) > 1 and _distance(unique[0].point, unique[-1].point) <= _CUT_EPSILON:
        unique.pop()
    return unique


def _edge_surface_roots(start: _Vertex, end: _Vertex, surface: CutSurface) -> tuple[float, ...]:
    if surface.amplitude <= 0.0:
        d0 = surface.signed_distance(start.point)
        d1 = surface.signed_distance(end.point)
        if abs(d0) <= _CUT_EPSILON:
            return (0.0,)
        if abs(d1) <= _CUT_EPSILON:
            return (1.0,)
        if d0 * d1 >= 0.0:
            return ()
        return (d0 / (d0 - d1),)

    start_u, start_v = _project_to_surface(start.point, surface)
    end_u, end_v = _project_to_surface(end.point, surface)
    wavelength_spans = max(
        abs(end_u - start_u) / surface.wavelength,
        abs(end_v - start_v) / (surface.wavelength * 2.5),
    )
    steps = max(16, math.ceil(wavelength_spans * 16.0))
    if steps > 4096:
        raise FractureError(
            f"Fracture cut {surface.token} edge spans {wavelength_spans:g} noise wavelengths; "
            "safe root isolation would exceed 4096 intervals."
        )
    roots: list[float] = []
    previous_t = 0.0
    previous_distance = surface.signed_distance(start.point)
    if abs(previous_distance) <= _CUT_EPSILON:
        roots.append(0.0)
    for step in range(1, steps + 1):
        current_t = step / steps
        current_distance = surface.signed_distance(_lerp(start.point, end.point, current_t))
        if previous_distance * current_distance < 0.0:
            roots.append(
                _bisect_surface_root(
                    start.point,
                    end.point,
                    surface,
                    previous_t,
                    current_t,
                    previous_distance,
                )
            )
        elif abs(current_distance) <= _CUT_EPSILON:
            roots.append(current_t)
        previous_t = current_t
        previous_distance = current_distance
    unique: list[float] = []
    for root in roots:
        if not unique or abs(root - unique[-1]) > 1e-7:
            unique.append(root)
    return tuple(unique)


def _bisect_surface_root(
    start: Vector3,
    end: Vector3,
    surface: CutSurface,
    lower_t: float,
    upper_t: float,
    lower_distance: float,
) -> float:
    for _ in range(48):
        middle_t = (lower_t + upper_t) * 0.5
        middle_distance = surface.signed_distance(_lerp(start, end, middle_t))
        if abs(middle_distance) <= _CUT_EPSILON:
            return middle_t
        if lower_distance * middle_distance <= 0.0:
            upper_t = middle_t
        else:
            lower_t = middle_t
            lower_distance = middle_distance
    return (lower_t + upper_t) * 0.5


def _interpolate_vertex(start: _Vertex, end: _Vertex, t: float) -> _Vertex:
    resolved_t = max(0.0, min(1.0, float(t)))
    joint_indices, joint_weights = _interpolated_joint_binding(start, end, resolved_t)
    return _Vertex(
        point=_lerp(start.point, end.point, resolved_t),
        uv=_lerp_vector2(start.uv, end.uv, resolved_t),
        secondary_uv=_lerp_vector2(start.secondary_uv, end.secondary_uv, resolved_t),
        color=_lerp_color(start.color, end.color, resolved_t),
        joint_indices=joint_indices,
        joint_weights=joint_weights,
    )


def _interpolated_joint_binding(start: _Vertex, end: _Vertex, t: float) -> tuple[tuple[int, ...], tuple[float, ...]]:
    width = max(len(start.joint_indices), len(end.joint_indices))
    if width == 0:
        return (), ()
    weights_by_joint: dict[int, float] = {}
    for joint, weight in zip(start.joint_indices, start.joint_weights or (1.0,) * len(start.joint_indices)):
        weights_by_joint[joint] = weights_by_joint.get(joint, 0.0) + float(weight) * (1.0 - t)
    for joint, weight in zip(end.joint_indices, end.joint_weights or (1.0,) * len(end.joint_indices)):
        weights_by_joint[joint] = weights_by_joint.get(joint, 0.0) + float(weight) * t
    ranked = sorted(weights_by_joint.items(), key=lambda item: (-item[1], item[0]))[:width]
    total = sum(weight for _joint, weight in ranked)
    if total <= _CUT_EPSILON:
        fallback = min(weights_by_joint)
        ranked = [(fallback, 1.0)]
        total = 1.0
    indices = tuple(joint for joint, _weight in ranked)
    weights = tuple(weight / total for _joint, weight in ranked)
    if len(indices) < width:
        indices += (indices[-1],) * (width - len(indices))
        weights += (0.0,) * (width - len(weights))
    return indices, weights


def _mesh_from_polygons(name: str, polygons: list[_Polygon], skel_element_size: int) -> MeshData:
    points: list[Vector3] = []
    counts: list[int] = []
    indices: list[int] = []
    uvs: list[Vector2] = []
    secondary_uvs: list[Vector2] = []
    colors: list[Color4] = []
    joint_indices: list[int] = []
    joint_weights: list[float] = []
    faces_by_material: dict[int, list[int]] = {}
    use_uvs = all(vertex.uv is not None for polygon in polygons for vertex in polygon.vertices)
    use_secondary_uvs = all(vertex.secondary_uv is not None for polygon in polygons for vertex in polygon.vertices)
    use_colors = all(vertex.color is not None for polygon in polygons for vertex in polygon.vertices)
    for face_index, polygon in enumerate(polygons):
        counts.append(len(polygon.vertices))
        faces_by_material.setdefault(polygon.material_id, []).append(face_index)
        for vertex in polygon.vertices:
            point_index = len(points)
            points.append(vertex.point)
            indices.append(point_index)
            if use_uvs:
                uvs.append(vertex.uv or Vector2(0.0, 0.0))
            if use_secondary_uvs:
                secondary_uvs.append(vertex.secondary_uv or Vector2(0.0, 0.0))
            if use_colors:
                colors.append(vertex.color or Color4(1.0, 1.0, 1.0, 1.0))
            if skel_element_size > 0:
                if len(vertex.joint_indices) != skel_element_size or len(vertex.joint_weights) != skel_element_size:
                    raise FractureError(f"Fracture geometry vertex in {name} has invalid skinning width.")
                joint_indices.extend(vertex.joint_indices)
                joint_weights.extend(vertex.joint_weights)
    return MeshData(
        name=name,
        points=tuple(points),
        face_vertex_counts=tuple(counts),
        face_vertex_indices=tuple(indices),
        uv_coords=tuple(uvs),
        secondary_uv_coords=tuple(secondary_uvs),
        vertex_colors=tuple(colors),
        sections=tuple(
            MeshSection(material_id=material_id, face_indices=tuple(face_indices))
            for material_id, face_indices in sorted(faces_by_material.items())
        ),
        skel_joint_indices=tuple(joint_indices),
        skel_joint_weights=tuple(joint_weights),
        skel_element_size=skel_element_size if joint_indices else 0,
    )


def _cap_polygons(
    segments: list[_CapSegment],
    surfaces: tuple[CutSurface, ...],
    *,
    piece_index: int,
    cap_material_id: int | None,
) -> list[_Polygon]:
    polygons: list[_Polygon] = []
    surface_by_token = {surface.token: surface for surface in surfaces}
    for token in sorted({segment.surface_token for segment in segments}):
        surface = surface_by_token.get(token)
        if surface is None:
            raise FractureError(f"Fracture cap references missing cut surface {token}.")
        surface_segments = [segment for segment in segments if segment.surface_token == token]
        try:
            for loop in _cap_loops(surface_segments, surface):
                projected = tuple(_project_to_surface(vertex.point, surface) for vertex in loop)
                _raise_for_self_intersection(projected, token)
                triangles = _triangulate_loop(projected, token)
                reverse = piece_index == surface.child_piece_index
                material_id = cap_material_id
                if material_id is None:
                    material_id = min(segment.material_id for segment in surface_segments)
                cap_vertices = tuple(_cap_vertex(vertex) for vertex in loop)
                for triangle in triangles:
                    ordered = tuple(reversed(triangle)) if reverse else triangle
                    polygons.append(
                        _Polygon(
                            vertices=tuple(cap_vertices[index] for index in ordered),
                            material_id=material_id,
                            source_face_index=-1,
                        )
                    )
        except FractureError as exc:
            raise _AutomaticCutGeometryError(token, str(exc)) from exc
    return polygons


def _cap_loops(segments: list[_CapSegment], surface: CutSurface) -> tuple[tuple[_Vertex, ...], ...]:
    tolerance = max(surface.radius * 1e-2, 1e-6)
    vertex_by_key: dict[tuple[int, int, int], _Vertex] = {}
    adjacency: dict[tuple[int, int, int], list[tuple[int, int, int]]] = {}
    edges: set[tuple[tuple[int, int, int], tuple[int, int, int]]] = set()
    for segment in segments:
        start_key = _point_key(segment.start.point, tolerance)
        end_key = _point_key(segment.end.point, tolerance)
        if start_key == end_key:
            # Quantized coincident intersections contribute no boundary edge.
            continue
        edge = tuple(sorted((start_key, end_key)))
        if edge in edges:
            raise FractureError(f"Fracture cap {surface.token} contains a duplicate boundary segment.")
        edges.add(edge)
        vertex_by_key.setdefault(start_key, segment.start)
        vertex_by_key.setdefault(end_key, segment.end)
        adjacency.setdefault(start_key, []).append(end_key)
        adjacency.setdefault(end_key, []).append(start_key)
    invalid = sorted(key for key, neighbors in adjacency.items() if len(neighbors) != 2)
    if invalid:
        degree = len(adjacency[invalid[0]])
        raise FractureError(
            f"Fracture cap {surface.token} is open or non-manifold at boundary vertex {invalid[0]} "
            f"with degree {degree} (weld tolerance {tolerance:g})."
        )

    remaining = set(edges)
    loops: list[tuple[_Vertex, ...]] = []
    while remaining:
        seed_edge = min(remaining)
        start, current = seed_edge
        previous = start
        keys = [start]
        while current != start:
            keys.append(current)
            choices = sorted(neighbor for neighbor in adjacency[current] if neighbor != previous)
            if len(choices) != 1:
                raise FractureError(f"Fracture cap {surface.token} cannot resolve a unique boundary loop.")
            next_key = choices[0]
            edge = tuple(sorted((current, next_key)))
            if edge not in remaining and next_key != start:
                raise FractureError(f"Fracture cap {surface.token} boundary loop reuses an edge.")
            remaining.discard(tuple(sorted((previous, current))))
            previous, current = current, next_key
            if len(keys) > len(edges) + 1:
                raise FractureError(f"Fracture cap {surface.token} boundary loop does not close.")
        remaining.discard(tuple(sorted((previous, start))))
        if len(keys) < 3:
            raise FractureError(f"Fracture cap {surface.token} boundary loop has fewer than three vertices.")
        loops.append(tuple(vertex_by_key[key] for key in keys))
    return tuple(loops)


def _triangulate_loop(points: tuple[tuple[float, float], ...], token: str) -> tuple[tuple[int, int, int], ...]:
    area = _signed_area(points)
    if abs(area) <= _CUT_EPSILON:
        raise FractureError(f"Fracture cap {token} has a degenerate projected boundary loop.")
    order = list(range(len(points)))
    if area < 0.0:
        order.reverse()
    triangles: list[tuple[int, int, int]] = []
    while len(order) > 3:
        ear_index = None
        for index in range(len(order)):
            previous = order[index - 1]
            current = order[index]
            following = order[(index + 1) % len(order)]
            if _cross2(points[previous], points[current], points[following]) <= _CUT_EPSILON:
                continue
            if any(
                _point_in_triangle(points[candidate], points[previous], points[current], points[following])
                for candidate in order
                if candidate not in (previous, current, following)
            ):
                continue
            ear_index = index
            triangles.append((previous, current, following))
            break
        if ear_index is None:
            raise FractureError(f"Fracture cap {token} boundary loop cannot be triangulated safely.")
        order.pop(ear_index)
    triangles.append(tuple(order))
    return tuple(triangles)


def _raise_for_self_intersection(points: tuple[tuple[float, float], ...], token: str) -> None:
    count = len(points)
    for first in range(count):
        a0 = points[first]
        a1 = points[(first + 1) % count]
        for second in range(first + 1, count):
            if second in (first, (first + 1) % count) or (second + 1) % count in (first, (first + 1) % count):
                continue
            if _segments_intersect(a0, a1, points[second], points[(second + 1) % count]):
                raise FractureError(f"Fracture cap {token} has a self-intersecting boundary loop.")


def _model_seed(model: CanonicalTreeModel) -> bytes:
    digest = hashlib.sha256()
    digest.update(model.metadata.source_path.encode("utf-8", errors="surrogatepass"))
    if model.base_mesh is not None:
        for point in model.base_mesh.points:
            digest.update(struct.pack("<ddd", point.x, point.y, point.z))
        digest.update(struct.pack("<QQ", len(model.base_mesh.face_vertex_counts), len(model.base_mesh.face_vertex_indices)))
    for joint in model.skeleton:
        digest.update(joint.name.encode("utf-8", errors="surrogatepass"))
        digest.update(struct.pack("<ddd", joint.bind_translate.x, joint.bind_translate.y, joint.bind_translate.z))
    return digest.digest()


def _cut_seed(source_seed: bytes, token: str) -> int:
    digest = hashlib.sha256(source_seed + token.encode("utf-8", errors="surrogatepass")).digest()
    return int.from_bytes(digest[:8], "little", signed=False)


def _value_noise(x: float, y: float, seed: int) -> float:
    x0 = math.floor(x)
    y0 = math.floor(y)
    tx = x - x0
    ty = y - y0
    sx = tx * tx * (3.0 - 2.0 * tx)
    sy = ty * ty * (3.0 - 2.0 * ty)
    n00 = _noise_corner(x0, y0, seed)
    n10 = _noise_corner(x0 + 1, y0, seed)
    n01 = _noise_corner(x0, y0 + 1, seed)
    n11 = _noise_corner(x0 + 1, y0 + 1, seed)
    nx0 = n00 + (n10 - n00) * sx
    nx1 = n01 + (n11 - n01) * sx
    return nx0 + (nx1 - nx0) * sy


def _noise_corner(x: int, y: int, seed: int) -> float:
    value = (seed ^ (x * 0x9E3779B185EBCA87) ^ (y * 0xC2B2AE3D27D4EB4F)) & 0xFFFFFFFFFFFFFFFF
    value ^= value >> 30
    value = (value * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    value ^= value >> 27
    value = (value * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    value ^= value >> 31
    return (value / 0xFFFFFFFFFFFFFFFF) * 2.0 - 1.0


def _stable_basis(normal: Vector3) -> tuple[Vector3, Vector3]:
    helper = min(
        (Vector3(1.0, 0.0, 0.0), Vector3(0.0, 1.0, 0.0), Vector3(0.0, 0.0, 1.0)),
        key=lambda axis: abs(_dot(normal, axis)),
    )
    tangent = _normalize(_cross(normal, helper), "cut basis")
    return tangent, _normalize(_cross(normal, tangent), "cut basis")


def _cut_origin_and_normal(
    cut_site,
    parent_joint,
    child_joint,
    *,
    auto_branch_offset: float | None = None,
) -> tuple[Vector3, Vector3]:
    if cut_site.segment_t is not None:
        if parent_joint is None:
            raise FractureError(f"Manual fracture cut {cut_site.joint_token} has no parent joint.")
        return (
            _lerp(parent_joint.bind_translate, child_joint.bind_translate, float(cut_site.segment_t)),
            _normalize(
                _subtract(child_joint.bind_translate, parent_joint.bind_translate),
                cut_site.joint_token,
            ),
        )
    bind_end = child_joint.bind_end_translate
    if bind_end is not None and _distance(child_joint.bind_translate, bind_end) > _CUT_EPSILON:
        offset = (
            _AUTO_BRANCH_CUT_OFFSETS[0] if auto_branch_offset is None else auto_branch_offset
        ) if cut_site.reason == "auto_branch_length" else 0.02
        return (
            _lerp(child_joint.bind_translate, bind_end, offset),
            _normalize(_subtract(bind_end, child_joint.bind_translate), cut_site.joint_token),
        )
    if parent_joint is None:
        raise FractureError(f"Fracture stem cut {cut_site.joint_token} has no usable bone direction.")
    return (
        child_joint.bind_translate,
        _normalize(
            _subtract(child_joint.bind_translate, parent_joint.bind_translate),
            cut_site.joint_token,
        ),
    )


def _project_to_surface(point: Vector3, surface: CutSurface) -> tuple[float, float]:
    offset = _subtract(point, surface.origin)
    return _dot(offset, surface.tangent), _dot(offset, surface.bitangent)


def _point_key(point: Vector3, tolerance: float) -> tuple[int, int, int]:
    return (
        round(point.x / tolerance),
        round(point.y / tolerance),
        round(point.z / tolerance),
    )


def _cap_vertex(vertex: _Vertex) -> _Vertex:
    return replace(
        vertex,
        uv=Vector2(0.0, 0.0) if vertex.uv is not None else None,
        secondary_uv=Vector2(0.0, 0.0) if vertex.secondary_uv is not None else None,
        color=Color4(1.0, 1.0, 1.0, 1.0) if vertex.color is not None else None,
    )


def _lerp_vector2(start: Vector2 | None, end: Vector2 | None, t: float) -> Vector2 | None:
    if start is None or end is None:
        return None
    return Vector2(start.x + (end.x - start.x) * t, start.y + (end.y - start.y) * t)


def _lerp_color(start: Color4 | None, end: Color4 | None, t: float) -> Color4 | None:
    if start is None or end is None:
        return None
    return Color4(
        start.r + (end.r - start.r) * t,
        start.g + (end.g - start.g) * t,
        start.b + (end.b - start.b) * t,
        start.a + (end.a - start.a) * t,
    )


def _signed_area(points: tuple[tuple[float, float], ...]) -> float:
    return 0.5 * sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    )


def _cross2(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _point_in_triangle(
    point: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> bool:
    first = _cross2(a, b, point)
    second = _cross2(b, c, point)
    third = _cross2(c, a, point)
    return first >= -_CUT_EPSILON and second >= -_CUT_EPSILON and third >= -_CUT_EPSILON


def _segments_intersect(
    a0: tuple[float, float],
    a1: tuple[float, float],
    b0: tuple[float, float],
    b1: tuple[float, float],
) -> bool:
    c1 = _cross2(a0, a1, b0)
    c2 = _cross2(a0, a1, b1)
    c3 = _cross2(b0, b1, a0)
    c4 = _cross2(b0, b1, a1)
    return ((c1 > _CUT_EPSILON and c2 < -_CUT_EPSILON) or (c1 < -_CUT_EPSILON and c2 > _CUT_EPSILON)) and (
        (c3 > _CUT_EPSILON and c4 < -_CUT_EPSILON) or (c3 < -_CUT_EPSILON and c4 > _CUT_EPSILON)
    )


def _subtract(a: Vector3, b: Vector3) -> Vector3:
    return Vector3(a.x - b.x, a.y - b.y, a.z - b.z)


def _scale(vector: Vector3, scale: float) -> Vector3:
    return Vector3(vector.x * scale, vector.y * scale, vector.z * scale)


def _dot(a: Vector3, b: Vector3) -> float:
    return a.x * b.x + a.y * b.y + a.z * b.z


def _cross(a: Vector3, b: Vector3) -> Vector3:
    return Vector3(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x)


def _length(vector: Vector3) -> float:
    return math.sqrt(_dot(vector, vector))


def _distance(a: Vector3, b: Vector3) -> float:
    return _length(_subtract(a, b))


def _normalize(vector: Vector3, token: str) -> Vector3:
    length = _length(vector)
    if length <= _CUT_EPSILON:
        raise FractureError(f"Fracture cut {token} references a zero-length skeleton edge.")
    return _scale(vector, 1.0 / length)


def _lerp(start: Vector3, end: Vector3, t: float) -> Vector3:
    return Vector3(
        start.x + (end.x - start.x) * t,
        start.y + (end.y - start.y) * t,
        start.z + (end.z - start.z) * t,
    )


def build_cap_source_context(mesh: MeshData) -> CapSourceContext:
    face_ranges = tuple(iter_face_ranges(mesh.face_vertex_counts))
    return CapSourceContext(
        face_ranges=face_ranges,
        source_edge_faces=_source_edge_faces(mesh, face_ranges),
        material_by_source_face=_material_by_source_face(mesh),
    )


def slice_mesh_faces(
    mesh: MeshData,
    face_indices: tuple[int, ...],
    *,
    name: str,
    generate_caps: bool = False,
    cap_material_id: int | None = None,
    cap_context: CapSourceContext | None = None,
) -> MeshData:
    """Return a compact mesh containing only the requested source face indices."""
    if not face_indices:
        raise FractureError(f"Fracture piece {name} has no base mesh faces.")
    _validate_slice_mesh_shape(mesh)

    face_ranges = cap_context.face_ranges if cap_context is not None else tuple(iter_face_ranges(mesh.face_vertex_counts))
    selected = set(face_indices)
    if len(selected) != len(face_indices):
        raise FractureError(f"Fracture piece {name} contains duplicate base mesh face indices.")
    if any(face_index < 0 or face_index >= len(face_ranges) for face_index in face_indices):
        raise FractureError(f"Fracture piece {name} references a base mesh face outside the source mesh.")

    original_to_new_point: dict[int, int] = {}
    new_point_source: list[int | None] = []
    points = []
    face_vertex_counts: list[int] = []
    face_vertex_indices: list[int] = []
    uv_coords = []
    secondary_uv_coords = []
    vertex_colors = []
    original_to_new_face: dict[int, int] = {}

    for new_face_index, original_face_index in enumerate(face_indices):
        _face_index, start, end = face_ranges[original_face_index]
        original_to_new_face[original_face_index] = new_face_index
        face_vertex_counts.append(end - start)
        for face_vertex_slot in range(start, end):
            original_point_index = mesh.face_vertex_indices[face_vertex_slot]
            if original_point_index < 0 or original_point_index >= len(mesh.points):
                raise FractureError(
                    f"Base mesh face {original_face_index} references point {original_point_index} outside the mesh."
                )
            new_point_index = original_to_new_point.get(original_point_index)
            if new_point_index is None:
                new_point_index = len(points)
                original_to_new_point[original_point_index] = new_point_index
                new_point_source.append(original_point_index)
                points.append(mesh.points[original_point_index])
            face_vertex_indices.append(new_point_index)
            if len(mesh.uv_coords) == len(mesh.face_vertex_indices):
                uv_coords.append(mesh.uv_coords[face_vertex_slot])
            if len(mesh.secondary_uv_coords) == len(mesh.face_vertex_indices):
                secondary_uv_coords.append(mesh.secondary_uv_coords[face_vertex_slot])
            if len(mesh.vertex_colors) == len(mesh.face_vertex_indices):
                vertex_colors.append(mesh.vertex_colors[face_vertex_slot])

    sections = _slice_mesh_sections(mesh.sections, original_to_new_face)
    if generate_caps:
        resolved_cap_context = cap_context or build_cap_source_context(mesh)
        sections = _append_boundary_fan_caps(
            mesh,
            resolved_cap_context,
            selected,
            original_to_new_face,
            original_to_new_point,
            new_point_source,
            points,
            face_vertex_counts,
            face_vertex_indices,
            uv_coords,
            secondary_uv_coords,
            vertex_colors,
            sections,
            cap_material_id=cap_material_id,
        )

    skel_joint_indices, skel_joint_weights = _slice_mesh_skinning(mesh, new_point_source)
    return MeshData(
        name=name,
        points=tuple(points),
        face_vertex_counts=tuple(face_vertex_counts),
        face_vertex_indices=tuple(face_vertex_indices),
        uv_coords=tuple(uv_coords),
        secondary_uv_coords=tuple(secondary_uv_coords),
        vertex_colors=tuple(vertex_colors),
        sections=sections,
        skel_joint_indices=skel_joint_indices,
        skel_joint_weights=skel_joint_weights,
        skel_element_size=mesh.skel_element_size if skel_joint_indices else 0,
    )


def _validate_slice_mesh_shape(mesh: MeshData) -> None:
    mesh_name = getattr(mesh, "name", "<unnamed>")
    for field_name in ("points", "face_vertex_counts", "face_vertex_indices"):
        _require_sequence_field(mesh, mesh_name, field_name)


def _require_sequence_field(mesh: MeshData, mesh_name: str, field_name: str) -> None:
    value = getattr(mesh, field_name, None)
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__") or not hasattr(value, "__getitem__"):
        raise FractureError(
            f"Fracture mesh {mesh_name} {field_name} must be a sequence, got {type(value).__name__}."
        )


def _slice_mesh_sections(
    sections: tuple[MeshSection, ...],
    original_to_new_face: dict[int, int],
) -> tuple[MeshSection, ...]:
    sliced_sections: list[MeshSection] = []
    for section in sections:
        face_indices = tuple(
            original_to_new_face[face_index]
            for face_index in section.face_indices
            if face_index in original_to_new_face
        )
        if face_indices:
            sliced_sections.append(MeshSection(material_id=section.material_id, face_indices=face_indices))
    return tuple(sliced_sections)


def _slice_mesh_skinning(
    mesh: MeshData,
    new_point_source: list[int | None],
) -> tuple[tuple[int, ...], tuple[float, ...]]:
    if mesh.skel_element_size <= 0 or not mesh.skel_joint_indices:
        return (), ()

    expected_slots = len(mesh.points) * mesh.skel_element_size
    if len(mesh.skel_joint_indices) < expected_slots:
        raise FractureError("Base mesh skinning index count is smaller than point count.")
    if mesh.skel_joint_weights and len(mesh.skel_joint_weights) < expected_slots:
        raise FractureError("Base mesh skinning weight count is smaller than point count.")

    joint_indices: list[int] = []
    joint_weights: list[float] = []
    fallback_source = next((source for source in new_point_source if source is not None), None)
    for source_point_index in new_point_source:
        original_point_index = source_point_index if source_point_index is not None else fallback_source
        if original_point_index is None:
            continue
        start = original_point_index * mesh.skel_element_size
        end = start + mesh.skel_element_size
        joint_indices.extend(mesh.skel_joint_indices[start:end])
        if mesh.skel_joint_weights:
            joint_weights.extend(mesh.skel_joint_weights[start:end])
    return tuple(joint_indices), tuple(joint_weights)


def _append_boundary_fan_caps(
    mesh: MeshData,
    cap_context: CapSourceContext,
    selected: set[int],
    original_to_new_face: dict[int, int],
    original_to_new_point: dict[int, int],
    new_point_source: list[int | None],
    points: list[Vector3],
    face_vertex_counts: list[int],
    face_vertex_indices: list[int],
    uv_coords: list[Vector2],
    secondary_uv_coords: list[Vector2],
    vertex_colors: list[Color4],
    sections: tuple[MeshSection, ...],
    *,
    cap_material_id: int | None = None,
) -> tuple[MeshSection, ...]:
    selected_boundary_edges: list[tuple[int, int, int]] = []
    for original_face_index in sorted(selected):
        _face_index, start, end = cap_context.face_ranges[original_face_index]
        face_points = mesh.face_vertex_indices[start:end]
        for index, point_a in enumerate(face_points):
            point_b = face_points[(index + 1) % len(face_points)]
            edge_key = _edge_key(point_a, point_b)
            adjacent = cap_context.source_edge_faces.get(edge_key, ())
            if len(adjacent) < 2 or all(face in selected for face in adjacent):
                continue
            selected_boundary_edges.append((point_a, point_b, original_face_index))

    if not selected_boundary_edges:
        return sections

    cap_face_indices_by_material: dict[int, list[int]] = {}
    use_uvs = len(mesh.uv_coords) == len(mesh.face_vertex_indices)
    use_secondary_uvs = len(mesh.secondary_uv_coords) == len(mesh.face_vertex_indices)
    use_vertex_colors = len(mesh.vertex_colors) == len(mesh.face_vertex_indices)

    for boundary_loop in _boundary_loops(selected_boundary_edges):
        loop_point_indices = sorted({point for point_a, point_b, _face in boundary_loop for point in (point_a, point_b)})
        center = _average_points(tuple(points[original_to_new_point[point]] for point in loop_point_indices))
        center_index = len(points)
        points.append(center)
        new_point_source.append(loop_point_indices[0] if loop_point_indices else None)
        for point_a, point_b, original_face_index in boundary_loop:
            new_a = original_to_new_point[point_a]
            new_b = original_to_new_point[point_b]
            new_face_index = len(face_vertex_counts)
            face_vertex_counts.append(3)
            face_vertex_indices.extend((new_b, new_a, center_index))
            if use_uvs:
                uv_coords.extend((Vector2(0.0, 0.0), Vector2(0.0, 0.0), Vector2(0.0, 0.0)))
            if use_secondary_uvs:
                secondary_uv_coords.extend((Vector2(0.0, 0.0), Vector2(0.0, 0.0), Vector2(0.0, 0.0)))
            if use_vertex_colors:
                vertex_colors.extend(
                    (
                        Color4(1.0, 1.0, 1.0, 1.0),
                        Color4(1.0, 1.0, 1.0, 1.0),
                        Color4(1.0, 1.0, 1.0, 1.0),
                    )
                )
            material_id = cap_material_id
            if material_id is None:
                material_id = cap_context.material_by_source_face.get(original_face_index, 0)
            cap_face_indices_by_material.setdefault(material_id, []).append(new_face_index)

    merged_sections = [MeshSection(material_id=section.material_id, face_indices=section.face_indices) for section in sections]
    for material_id in sorted(cap_face_indices_by_material):
        merged_sections.append(MeshSection(material_id=material_id, face_indices=tuple(cap_face_indices_by_material[material_id])))
    return tuple(merged_sections)


def _source_edge_faces(
    mesh: MeshData,
    face_ranges: tuple[tuple[int, int, int], ...] | None = None,
) -> dict[tuple[int, int], tuple[int, ...]]:
    edge_faces: dict[tuple[int, int], list[int]] = {}
    resolved_face_ranges = face_ranges or tuple(iter_face_ranges(mesh.face_vertex_counts))
    for face_index, start, end in resolved_face_ranges:
        face_points = mesh.face_vertex_indices[start:end]
        for index, point_a in enumerate(face_points):
            point_b = face_points[(index + 1) % len(face_points)]
            edge_faces.setdefault(_edge_key(point_a, point_b), []).append(face_index)
    return {edge: tuple(faces) for edge, faces in edge_faces.items()}


def _material_by_source_face(mesh: MeshData) -> dict[int, int]:
    material_by_face: dict[int, int] = {}
    for section in mesh.sections:
        for face_index in section.face_indices:
            material_by_face.setdefault(face_index, section.material_id)
    return material_by_face


def _edge_key(point_a: int, point_b: int) -> tuple[int, int]:
    return (point_a, point_b) if point_a <= point_b else (point_b, point_a)


def _boundary_loops(edges: list[tuple[int, int, int]]) -> tuple[tuple[tuple[int, int, int], ...], ...]:
    remaining = list(edges)
    loops: list[tuple[tuple[int, int, int], ...]] = []
    while remaining:
        seed = remaining.pop(0)
        component = [seed]
        component_points = {seed[0], seed[1]}
        changed = True
        while changed:
            changed = False
            for edge in tuple(remaining):
                if edge[0] in component_points or edge[1] in component_points:
                    remaining.remove(edge)
                    component.append(edge)
                    component_points.update((edge[0], edge[1]))
                    changed = True
        loops.append(tuple(sorted(component, key=lambda item: (item[2], item[0], item[1]))))
    return tuple(loops)


def _average_points(points: tuple[Vector3, ...]) -> Vector3:
    if not points:
        raise FractureError("Cannot generate a fracture cap for an empty boundary loop.")
    scale = 1.0 / len(points)
    return Vector3(
        sum(point.x for point in points) * scale,
        sum(point.y for point in points) * scale,
        sum(point.z for point in points) * scale,
    )
