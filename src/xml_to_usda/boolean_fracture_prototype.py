"""Connectivity-first Boolean fracture used by preview, export, and diagnostics.

The one-cut and multi-cut prototype sessions remain available as inspection
surfaces, while production Detailed Cuts adapt the same result contract.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import math
import time

import numpy as np

from .fracture_service import (
    FractureCutSite,
    FracturePlan,
    FractureError,
    FractureSettings,
    _build_fracture_plan_cache,
    plan_fracture,
    source_bone_segment_positions,
)
from .fracture_geometry import FractureGeometryPiece, FractureGeometryResult, slice_mesh_faces
from .models import (
    CanonicalTreeModel,
    Color4,
    ExportMetadata,
    Joint,
    MaterialSpec,
    Matrix4d,
    MeshData,
    MeshSection,
    TreeAsset,
    Vector2,
    Vector3,
)


_EPSILON = 1e-8
_MAX_CUTTER_TRIANGLES = 250_000
_SOURCE_COLOR = Color4(0.18, 0.55, 0.92, 1.0)
_PARENT_COLOR = Color4(0.95, 0.32, 0.18, 1.0)
_ORIGINAL_COLOR = Color4(0.72, 0.76, 0.80, 1.0)
_CLOSURE_COLOR = Color4(0.94, 0.55, 0.12, 1.0)
_CUTTER_COLOR = Color4(0.72, 0.24, 0.84, 1.0)
_BOOLEAN_CAP_COLOR = Color4(0.15, 0.88, 0.70, 1.0)
_PIECE_COLORS = (
    Color4(0.95, 0.34, 0.20, 1.0),
    Color4(0.18, 0.63, 0.96, 1.0),
    Color4(0.22, 0.78, 0.45, 1.0),
    Color4(0.96, 0.72, 0.18, 1.0),
    Color4(0.68, 0.36, 0.94, 1.0),
    Color4(0.18, 0.84, 0.82, 1.0),
)


@dataclass(frozen=True, slots=True)
class BooleanCutPrototypeSettings:
    cut_token: str
    intensity: float = 0.35
    chip_scale: float = 0.65
    remesh_density: int = 24
    max_bend_angle_degrees: float = 30.0
    cap_material_id: int | None = None

    def validated(self) -> "BooleanCutPrototypeSettings":
        if not self.cut_token.strip():
            raise FractureError("Boolean prototype cut token must not be empty.")
        if not math.isfinite(float(self.intensity)) or float(self.intensity) < 0.0:
            raise FractureError("Boolean prototype intensity must be finite and non-negative.")
        if float(self.chip_scale) <= 0.0:
            raise FractureError("Boolean prototype chip scale must be greater than zero.")
        if not isinstance(self.remesh_density, int) or not 4 <= self.remesh_density <= 64:
            raise FractureError("Boolean prototype remesh density must be an integer from 4 to 64.")
        if not math.isfinite(float(self.max_bend_angle_degrees)) or not 0.0 < float(self.max_bend_angle_degrees) <= 180.0:
            raise FractureError("Boolean prototype max bend angle must be greater than 0 and at most 180 degrees.")
        return self


@dataclass(frozen=True, slots=True)
class PrototypeStageDiagnostics:
    face_count: int
    boundary_count: int
    volume: float | None


@dataclass(frozen=True, slots=True)
class BooleanCutPrototypeDiagnostics:
    selected_component_index: int
    source_component_count: int
    source_face_count: int
    closure_face_count: int
    cutter_triangle_count: int
    cap_vertex_count: int
    cut_origin: Vector3
    requested_amplitude: float
    effective_amplitude: float
    amplitude_limit_distance: float
    amplitude_limit_reason: str
    amplitude_limit_joint_token: str
    stages: tuple[tuple[str, PrototypeStageDiagnostics], ...]


@dataclass(frozen=True, slots=True)
class BooleanCutPrototypeResult:
    original_shell: MeshData
    closed_solid: MeshData
    cutter_surface: MeshData
    parent_result: MeshData
    child_result: MeshData
    diagnostics: BooleanCutPrototypeDiagnostics
    stage_timings: tuple[tuple[str, float], ...]


@dataclass(frozen=True, slots=True)
class BooleanMultiPrototypeSettings:
    auto_branch_count: int = 5
    output_stem: str = "Tree"
    intensity: float = 0.35
    chip_scale: float = 0.65
    remesh_density: int = 24
    max_bend_angle_degrees: float = 30.0
    force_stump_piece: bool = False
    separate_stems: bool = False
    branch_height_bias: float = 0.0
    pinned_cut_joint_tokens: tuple[str, ...] = ()
    cap_material_id: int | None = None

    def validated(self) -> "BooleanMultiPrototypeSettings":
        if not isinstance(self.auto_branch_count, int) or not 0 <= self.auto_branch_count <= 64:
            raise FractureError("Boolean multi prototype branch count must be an integer from 0 to 64.")
        if not isinstance(self.output_stem, str) or not self.output_stem.strip():
            raise FractureError("Boolean multi prototype output stem must be a non-empty string.")
        BooleanCutPrototypeSettings(
            cut_token="validation",
            intensity=self.intensity,
            chip_scale=self.chip_scale,
            remesh_density=self.remesh_density,
            max_bend_angle_degrees=self.max_bend_angle_degrees,
        ).validated()
        if not -1.0 <= float(self.branch_height_bias) <= 1.0:
            raise FractureError("Boolean multi prototype branch height bias must be between -1 and 1.")
        if isinstance(self.pinned_cut_joint_tokens, str) or not isinstance(self.pinned_cut_joint_tokens, tuple):
            raise FractureError("Boolean multi prototype pinned cuts must be a tuple of tokens.")
        if any(not isinstance(token, str) or not token.strip() for token in self.pinned_cut_joint_tokens):
            raise FractureError("Boolean multi prototype pinned cut tokens must be non-empty strings.")
        return self


@dataclass(frozen=True, slots=True)
class BooleanMultiPrototypePiece:
    index: int
    name: str
    cut_token: str | None
    meshes: tuple[MeshData, ...]
    color: Color4


@dataclass(frozen=True, slots=True)
class BooleanMultiPrototypeResult:
    plan: FracturePlan
    pieces: tuple[BooleanMultiPrototypePiece, ...]
    cut_sites: tuple[FractureCutSite, ...]
    cuts: tuple[BooleanCutPrototypeResult, ...]
    stage_timings: tuple[tuple[str, float], ...]


@dataclass(slots=True)
class BooleanFractureSourceContext:
    model: CanonicalTreeModel
    mesh: MeshData
    analysis_cache: object
    vertices: np.ndarray
    triangles: np.ndarray
    source_face_indices: np.ndarray
    source_corner_slots: np.ndarray
    components: tuple[np.ndarray, ...]
    preparation_timings: tuple[tuple[str, float], ...]


SYNTHETIC_CYLINDER_CUT_TOKEN = "root->bone_001@0.500"


def build_synthetic_boolean_cylinder_model(
    *,
    radius: float = 0.35,
    length: float = 4.0,
    radial_segments: int = 24,
    axial_segments: int = 8,
) -> CanonicalTreeModel:
    """Return an uncapped skinned cylinder for interactive Boolean debugging."""
    if radius <= 0.0 or length <= 0.0:
        raise ValueError("Synthetic cylinder radius and length must be positive.")
    if radial_segments < 3 or axial_segments < 2:
        raise ValueError("Synthetic cylinder needs at least 3 radial and 2 axial segments.")
    points: list[Vector3] = []
    joint_indices: list[int] = []
    joint_weights: list[float] = []
    for axial in range(axial_segments + 1):
        y = -length * 0.5 + length * axial / axial_segments
        owner = 0 if y < 0.0 else 1
        for radial in range(radial_segments):
            angle = math.tau * radial / radial_segments
            points.append(Vector3(radius * math.cos(angle), y, radius * math.sin(angle)))
            joint_indices.append(owner)
            joint_weights.append(1.0)
    triangles: list[int] = []
    material_faces: dict[int, list[int]] = {0: [], 1: []}
    for axial in range(axial_segments):
        row = axial * radial_segments
        following_row = row + radial_segments
        for radial in range(radial_segments):
            following = (radial + 1) % radial_segments
            a = row + radial
            b = row + following
            c = following_row + radial
            d = following_row + following
            triangles.extend((a, c, d, a, d, b))
            material_id = 0 if axial < axial_segments // 2 else 1
            material_faces[material_id].extend((len(triangles) // 3 - 2, len(triangles) // 3 - 1))
    uv_coords: list[Vector2] = []
    secondary_uv_coords: list[Vector2] = []
    vertex_colors: list[Color4] = []
    for start in range(0, len(triangles), 3):
        triangle_uvs = []
        for point_index in triangles[start : start + 3]:
            point = points[point_index]
            triangle_uvs.append([math.atan2(point.z, point.x) / math.tau % 1.0, (point.y + length * 0.5) / length])
        if max(value[0] for value in triangle_uvs) - min(value[0] for value in triangle_uvs) > 0.5:
            for value in triangle_uvs:
                if value[0] < 0.5:
                    value[0] += 1.0
        for point_index, (u, v) in zip(triangles[start : start + 3], triangle_uvs):
            uv_coords.append(Vector2(u, v))
            secondary_uv_coords.append(Vector2(u * 2.0, v * 2.0))
            vertex_colors.append(Color4(v, 0.25, 1.0 - v, 1.0))
    half = length * 0.5
    root_point = Vector3(radius * 2.0, -half, 0.0)
    child_point = Vector3(0.0, -half, 0.0)
    child_end = Vector3(0.0, half, 0.0)
    skeleton = (
        Joint(
            name="root",
            source_id=0,
            parent=None,
            bind_transform=Matrix4d.from_translation(root_point),
            rest_transform=Matrix4d.from_translation(root_point),
        ),
        Joint(
            name="bone_001",
            source_id=1,
            parent="root",
            bind_transform=Matrix4d.from_translation(child_point),
            rest_transform=Matrix4d.from_translation(child_point),
            bind_end_transform=Matrix4d.from_translation(child_end),
        ),
    )
    return TreeAsset(
        metadata=ExportMetadata(source_path="synthetic://open-cylinder", source_version=None),
        materials=(MaterialSpec(0, "SyntheticBarkLower"), MaterialSpec(1, "SyntheticBarkUpper")),
        source_objects=(),
        base_mesh=MeshData(
            name="SyntheticOpenCylinder",
            points=tuple(points),
            face_vertex_counts=(3,) * (len(triangles) // 3),
            face_vertex_indices=tuple(triangles),
            uv_coords=tuple(uv_coords),
            secondary_uv_coords=tuple(secondary_uv_coords),
            vertex_colors=tuple(vertex_colors),
            sections=tuple(
                MeshSection(material_id=material_id, face_indices=tuple(face_indices))
                for material_id, face_indices in material_faces.items()
            ),
            skel_joint_indices=tuple(joint_indices),
            skel_joint_weights=tuple(joint_weights),
            skel_element_size=1,
        ),
        skeleton=skeleton,
        assembly_parts=(),
    )


@dataclass(frozen=True, slots=True)
class _CutFrame:
    origin: np.ndarray
    normal: np.ndarray
    tangent: np.ndarray
    bitangent: np.ndarray


@dataclass(frozen=True, slots=True)
class _NoiseLimit:
    distance: float
    reason: str
    joint_token: str


@dataclass(frozen=True, slots=True)
class _TaggedMesh:
    vertices: np.ndarray
    triangles: np.ndarray
    tags: np.ndarray
    source_triangle_indices: np.ndarray


@dataclass(frozen=True, slots=True)
class _BuiltCutter:
    manifold: object
    surface: _TaggedMesh
    triangle_count: int
    requested_amplitude: float
    effective_amplitude: float
    safe_limit: float
    noise_limit: _NoiseLimit
    seconds: float


@dataclass(frozen=True, slots=True)
class _SequentialComponentBuild:
    cut_results: tuple[BooleanCutPrototypeResult, ...]
    piece_meshes: tuple[tuple[int, MeshData], ...]


@dataclass(slots=True)
class _PreparedBooleanCut:
    model: CanonicalTreeModel
    mesh: MeshData
    cut_token: str
    cut_site: object
    frame: _CutFrame
    vertices: np.ndarray
    triangles: np.ndarray
    source_face_indices: np.ndarray
    source_corner_slots: np.ndarray
    source_component_count: int
    selected_component_index: int
    component_indices: np.ndarray
    component_triangles: np.ndarray
    closed_vertices: np.ndarray
    closure_triangles: np.ndarray
    manifold3d: object
    source_id_start: int
    closure_id: int
    cutter_id: int
    source_volume: float
    original_boundary_count: int
    seed: int
    original: _TaggedMesh
    closed: _TaggedMesh
    original_shell: MeshData
    closed_solid: MeshData
    preparation_timings: tuple[tuple[str, float], ...]


class BooleanCutPrototypeSession:
    """Prepared one-cut source state reused by interactive cutter regeneration."""

    def __init__(self, prepared: _PreparedBooleanCut) -> None:
        self._prepared = prepared
        self._last_settings: BooleanCutPrototypeSettings | None = None
        self._last_result: BooleanCutPrototypeResult | None = None

    @property
    def cut_token(self) -> str:
        return self._prepared.cut_token

    @property
    def selected_component_index(self) -> int:
        return self._prepared.selected_component_index

    def build(
        self,
        settings: BooleanCutPrototypeSettings,
        *,
        include_preparation_timings: bool = False,
    ) -> BooleanCutPrototypeResult:
        settings = settings.validated()
        if not include_preparation_timings and settings == self._last_settings and self._last_result is not None:
            return self._last_result
        result = _build_prepared_boolean_cut(self._prepared, settings, include_preparation_timings)
        if not include_preparation_timings:
            self._last_settings = settings
            self._last_result = result
        return result


def prepare_boolean_fracture_source(
    model: CanonicalTreeModel,
    *,
    analysis_cache: object | None = None,
) -> BooleanFractureSourceContext:
    mesh = model.base_mesh
    if mesh is None:
        raise FractureError("Boolean prototype requires a base mesh.")

    timings: list[tuple[str, float]] = []
    started = time.perf_counter()
    analysis_cache = analysis_cache or _build_fracture_plan_cache(model)
    timings.append(("analyze_source", time.perf_counter() - started))

    started = time.perf_counter()
    vertices, triangles, source_face_indices, source_corner_slots = _triangulated_mesh(mesh)
    timings.append(("triangulate_source", time.perf_counter() - started))

    started = time.perf_counter()
    components = _triangle_components(triangles)
    timings.append(("connectivity", time.perf_counter() - started))
    return BooleanFractureSourceContext(
        model=model,
        mesh=mesh,
        analysis_cache=analysis_cache,
        vertices=vertices,
        triangles=triangles,
        source_face_indices=source_face_indices,
        source_corner_slots=source_corner_slots,
        components=components,
        preparation_timings=tuple(timings),
    )


def prepare_boolean_cut_prototype(
    model: CanonicalTreeModel,
    cut_token: str,
    *,
    source_context: BooleanFractureSourceContext | None = None,
    fracture_plan: FracturePlan | None = None,
) -> BooleanCutPrototypeSession:
    cut_token = cut_token.strip()
    if not cut_token:
        raise FractureError("Boolean prototype cut token must not be empty.")

    context = source_context or prepare_boolean_fracture_source(model)
    if context.model is not model:
        raise FractureError("Boolean prototype source context belongs to a different tree model.")
    mesh = context.mesh

    timings = list(context.preparation_timings) if source_context is None else []
    started = time.perf_counter()
    analysis_cache = context.analysis_cache
    ownership_plan = fracture_plan or plan_fracture(
            model,
            FractureSettings(target_piece_count=0, pinned_cut_joint_tokens=(cut_token,)),
            analysis_cache=analysis_cache,
        )
    child_piece = next((piece for piece in ownership_plan.pieces if piece.cut_joint_token == cut_token), None)
    cut_site = next((cut for cut in ownership_plan.selected_cut_sites if cut.joint_token == cut_token), None)
    if fracture_plan is None and "->" not in cut_token and "@" not in cut_token:
        automatic_plan = plan_fracture(
            model,
            FractureSettings(target_piece_count=min(64, len(model.skeleton))),
            analysis_cache=analysis_cache,
        )
        cut_site = next((cut for cut in automatic_plan.selected_cut_sites if cut.joint_token == cut_token), cut_site)
    if cut_site is None or child_piece is None:
        raise FractureError(f"Boolean prototype cut {cut_token} did not resolve to one child piece.")
    frame = _cut_frame(model, cut_site)
    timings.append(("plan_cut", time.perf_counter() - started))

    vertices = context.vertices
    triangles = context.triangles
    source_face_indices = context.source_face_indices
    source_corner_slots = context.source_corner_slots
    seed = _source_seed(mesh, cut_token)

    started = time.perf_counter()
    components = context.components
    anchor_token = cut_site.child_joint_token or cut_site.joint_token
    anchor_faces = frozenset(
        face_index
        for face_index, owner in enumerate(analysis_cache.base_face_owner_by_index)
        if owner == anchor_token
    )
    selected_component_index = _select_component(
        components,
        triangles,
        source_face_indices,
        frozenset(child_piece.base_face_indices),
        anchor_faces,
        vertices,
        frame,
        cut_token,
    )
    component_indices = components[selected_component_index]
    component_triangles = triangles[component_indices]
    timings.append(("select_component", time.perf_counter() - started))

    started = time.perf_counter()
    loops = _boundary_loops(component_triangles, cut_token)
    closed_vertices, closure_triangles = _close_boundary_loops(vertices, component_triangles, loops)
    closed_triangles = np.vstack((component_triangles, closure_triangles)).astype(np.uint32, copy=False)
    closed_tags = np.concatenate(
        (
            np.zeros(len(component_triangles), dtype=np.uint8),
            np.ones(len(closure_triangles), dtype=np.uint8),
        )
    )
    timings.append(("close_boundaries", time.perf_counter() - started))

    started = time.perf_counter()
    manifold3d = _manifold_module()
    source_id_start = manifold3d.Manifold.reserve_ids(len(component_triangles) + 2)
    closure_id = source_id_start + len(component_triangles)
    cutter_id = closure_id + 1
    source_runs = tuple(
        (index, index + 1, source_id_start + index) for index in range(len(component_triangles))
    )
    branch = _to_manifold(
        manifold3d,
        closed_vertices,
        closed_triangles,
        source_runs + ((len(component_triangles), len(closed_triangles), closure_id),),
        "closed branch solid",
    )
    source_volume = float(branch.volume())
    if source_volume < 0.0:
        raise FractureError("Boolean prototype produced a negatively oriented branch solid.")
    timings.append(("build_branch_solid", time.perf_counter() - started))

    original = _TaggedMesh(
        vertices,
        component_triangles,
        np.zeros(len(component_triangles), dtype=np.uint8),
        component_indices.astype(np.int64, copy=False),
    )
    closed = _TaggedMesh(
        closed_vertices,
        closed_triangles,
        closed_tags,
        np.concatenate(
            (component_indices.astype(np.int64, copy=False), np.full(len(closure_triangles), -1, dtype=np.int64))
        ),
    )
    prepared = _PreparedBooleanCut(
        model=model,
        mesh=mesh,
        cut_token=cut_token,
        cut_site=cut_site,
        frame=frame,
        vertices=vertices,
        triangles=triangles,
        source_face_indices=source_face_indices,
        source_corner_slots=source_corner_slots,
        source_component_count=len(components),
        selected_component_index=selected_component_index,
        component_indices=component_indices,
        component_triangles=component_triangles,
        closed_vertices=closed_vertices,
        closure_triangles=closure_triangles,
        manifold3d=manifold3d,
        source_id_start=source_id_start,
        closure_id=closure_id,
        cutter_id=cutter_id,
        source_volume=source_volume,
        original_boundary_count=_stage_diagnostics(original, None).boundary_count,
        seed=seed,
        original=original,
        closed=closed,
        original_shell=_attributed_mesh_data(
            "BooleanOriginalShell", original, mesh, triangles, source_face_indices, source_corner_slots, frame
        ),
        closed_solid=_mesh_data("BooleanClosedSolid", closed, source_color=_ORIGINAL_COLOR),
        preparation_timings=tuple(timings),
    )
    return BooleanCutPrototypeSession(prepared)


def build_boolean_cut_prototype(
    model: CanonicalTreeModel,
    settings: BooleanCutPrototypeSettings,
) -> BooleanCutPrototypeResult:
    """Build one deterministic Boolean cut without touching production fracture paths."""
    settings = settings.validated()
    return prepare_boolean_cut_prototype(model, settings.cut_token).build(
        settings,
        include_preparation_timings=True,
    )


class BooleanMultiPrototypeSession:
    """Prepared independent cuts and source-piece slices for one Fracture Plan."""

    def __init__(
        self,
        plan: FracturePlan,
        source_context: BooleanFractureSourceContext,
        cut_sites: tuple[FractureCutSite, ...],
        cut_sessions: tuple[BooleanCutPrototypeSession, ...],
        source_meshes_by_piece: tuple[tuple[MeshData, ...], ...],
        parent_piece_indices: tuple[int, ...],
        preparation_timings: tuple[tuple[str, float], ...],
    ) -> None:
        self.plan = plan
        self._source_context = source_context
        self._cut_sites = cut_sites
        self._cut_sessions = cut_sessions
        self._source_meshes_by_piece = source_meshes_by_piece
        self._parent_piece_indices = parent_piece_indices
        self._preparation_timings = preparation_timings
        self._last_settings: BooleanMultiPrototypeSettings | None = None
        self._last_result: BooleanMultiPrototypeResult | None = None

    @property
    def auto_branch_count(self) -> int:
        return self.plan.requested_piece_count

    def build(
        self,
        settings: BooleanMultiPrototypeSettings,
        *,
        include_preparation_timings: bool = False,
    ) -> BooleanMultiPrototypeResult:
        settings = settings.validated()
        if settings.auto_branch_count != self.auto_branch_count:
            raise FractureError(
                f"Prepared Boolean multi plan has {self.auto_branch_count} branches, "
                f"not {settings.auto_branch_count}."
            )
        if not include_preparation_timings and settings == self._last_settings and self._last_result is not None:
            return replace(self._last_result, stage_timings=(("reuse_multi_result", 0.0),))

        timings = list(self._preparation_timings) if include_preparation_timings else [("reuse_prepared_plan", 0.0)]
        started = time.perf_counter()
        meshes_by_piece = [list(meshes) for meshes in self._source_meshes_by_piece]
        piece_index_by_cut = {
            piece.cut_joint_token: piece.index
            for piece in self.plan.pieces
            if piece.cut_joint_token is not None
        }
        cut_results: list[BooleanCutPrototypeResult | None] = [None] * len(self._cut_sessions)
        indices_by_component: dict[int, list[int]] = {}
        for index, session in enumerate(self._cut_sessions):
            indices_by_component.setdefault(session.selected_component_index, []).append(index)
        for indices in indices_by_component.values():
            if len(indices) == 1:
                index = indices[0]
                session = self._cut_sessions[index]
                result = session.build(_multi_cut_settings(settings, session.cut_token))
                cut_results[index] = result
                parent_piece_index = self._parent_piece_indices[index]
                child_piece_index = piece_index_by_cut[self._cut_sites[index].joint_token]
                meshes_by_piece[parent_piece_index].append(result.parent_result)
                meshes_by_piece[child_piece_index].append(result.child_result)
                continue
            entries = tuple(
                (
                    self._cut_sessions[index],
                    self._cut_sites[index],
                    self._parent_piece_indices[index],
                    piece_index_by_cut[self._cut_sites[index].joint_token],
                )
                for index in indices
            )
            nested = _build_sequential_component(entries, settings)
            for index, result in zip(indices, nested.cut_results):
                cut_results[index] = result
            for piece_index, mesh in nested.piece_meshes:
                meshes_by_piece[piece_index].append(mesh)
        timings.append(("build_all_cuts", time.perf_counter() - started))

        started = time.perf_counter()
        resolved_cut_results = tuple(result for result in cut_results if result is not None)
        if len(resolved_cut_results) != len(self._cut_sessions):
            raise FractureError("Boolean multi prototype did not build every selected cut.")
        pieces = tuple(
            BooleanMultiPrototypePiece(
                index=piece.index,
                name=piece.name,
                cut_token=piece.cut_joint_token,
                meshes=tuple(meshes_by_piece[piece.index]),
                color=_PIECE_COLORS[piece.index % len(_PIECE_COLORS)],
            )
            for piece in self.plan.pieces
        )
        timings.append(("assemble_pieces", time.perf_counter() - started))
        result = BooleanMultiPrototypeResult(
            plan=self.plan,
            pieces=pieces,
            cut_sites=self._cut_sites,
            cuts=resolved_cut_results,
            stage_timings=tuple(timings),
        )
        self._last_settings = settings
        self._last_result = result
        return result


def prepare_boolean_multi_prototype(
    model: CanonicalTreeModel,
    settings: BooleanMultiPrototypeSettings,
    *,
    previous_session: BooleanMultiPrototypeSession | None = None,
    source_context: BooleanFractureSourceContext | None = None,
) -> BooleanMultiPrototypeSession:
    settings = settings.validated()
    if previous_session is not None and previous_session._source_context.model is model:
        context = previous_session._source_context
        timings: list[tuple[str, float]] = [("reuse_source_context", 0.0)]
        reusable_sessions = {
            (cut_site.joint_token, cut_site): session
            for cut_site, session in zip(previous_session._cut_sites, previous_session._cut_sessions)
        }
    elif source_context is not None:
        if source_context.model is not model:
            raise FractureError("Boolean multi prototype source context belongs to a different tree model.")
        context = source_context
        timings = [("reuse_source_context", 0.0)]
        reusable_sessions = {}
    else:
        context = prepare_boolean_fracture_source(model)
        timings = list(context.preparation_timings)
        reusable_sessions = {}

    started = time.perf_counter()
    plan = plan_fracture(
        model,
        FractureSettings(
            target_piece_count=settings.auto_branch_count,
            output_stem=settings.output_stem,
            force_stump_piece=settings.force_stump_piece,
            separate_stems=settings.separate_stems,
            branch_height_bias=settings.branch_height_bias,
            pinned_cut_joint_tokens=settings.pinned_cut_joint_tokens,
        ),
        analysis_cache=context.analysis_cache,
    )
    timings.append(("plan_cuts", time.perf_counter() - started))

    started = time.perf_counter()
    boolean_cut_sites = tuple(
        cut_site for cut_site in plan.selected_cut_sites if cut_site.reason != "auto_stem_length"
    )
    sessions = tuple(
        reusable_sessions.get((cut_site.joint_token, cut_site))
        or prepare_boolean_cut_prototype(
                model,
                cut_site.joint_token,
                source_context=context,
                fracture_plan=plan,
            )
        for cut_site in boolean_cut_sites
    )
    reused_session_count = sum(
        session is reusable_sessions.get((cut_site.joint_token, cut_site))
        for cut_site, session in zip(boolean_cut_sites, sessions)
    )
    if reused_session_count:
        timings.append((f"reuse_cut_sessions[{reused_session_count}]", 0.0))
    timings.append(("prepare_cut_sessions", time.perf_counter() - started))

    selected_faces: set[int] = set()
    for session in sessions:
        prepared = session._prepared
        selected_faces.update(int(context.source_face_indices[index]) for index in prepared.component_indices)

    started = time.perf_counter()
    source_meshes_by_piece: list[tuple[MeshData, ...]] = []
    parent_piece_indices: list[int] = []
    for piece in plan.pieces:
        untouched = tuple(face for face in piece.base_face_indices if face not in selected_faces)
        source_meshes_by_piece.append(
            (
                slice_mesh_faces(context.mesh, untouched, name=f"{piece.name}_untouched"),
            )
            if untouched
            else ()
        )
    joint_by_name = {joint.name: joint for joint in model.skeleton}
    for cut_site in boolean_cut_sites:
        child_joint = joint_by_name.get(cut_site.child_joint_token or cut_site.joint_token)
        parent_joint_token = cut_site.parent_joint_token or (child_joint.parent if child_joint is not None else None)
        parent_piece = next(
            (
                piece
                for piece in plan.pieces
                if parent_joint_token is not None and parent_joint_token in piece.joint_tokens
            ),
            None,
        )
        if parent_piece is None:
            raise FractureError(
                f"Boolean multi prototype cut {cut_site.joint_token} has no parent Fracture Piece."
            )
        parent_piece_indices.append(parent_piece.index)
    timings.append(("slice_untouched_faces", time.perf_counter() - started))
    return BooleanMultiPrototypeSession(
        plan,
        context,
        boolean_cut_sites,
        sessions,
        tuple(source_meshes_by_piece),
        tuple(parent_piece_indices),
        tuple(timings),
    )


def boolean_multi_settings_from_fracture(
    settings: FractureSettings,
    *,
    cap_material_id: int | None = None,
) -> BooleanMultiPrototypeSettings:
    """Map the production fracture intent to the Boolean implementation contract."""
    return BooleanMultiPrototypeSettings(
        auto_branch_count=settings.target_piece_count,
        output_stem=settings.output_stem,
        intensity=settings.detailed_cut_intensity,
        chip_scale=settings.detailed_cut_scale,
        remesh_density=settings.detailed_cut_density,
        max_bend_angle_degrees=settings.detailed_cut_max_bend_angle,
        force_stump_piece=settings.force_stump_piece,
        separate_stems=settings.separate_stems,
        branch_height_bias=settings.branch_height_bias,
        pinned_cut_joint_tokens=settings.pinned_cut_joint_tokens,
        cap_material_id=cap_material_id,
    )


def fracture_geometry_from_boolean_multi(result: BooleanMultiPrototypeResult) -> FractureGeometryResult:
    """Adapt Boolean pieces to the geometry contract shared by Preview and Export."""
    plan_pieces = {piece.index: piece for piece in result.plan.pieces}
    return FractureGeometryResult(
        plan=result.plan,
        pieces=tuple(
            FractureGeometryPiece(
                piece=plan_pieces[piece.index],
                base_mesh=_merge_mesh_data(piece.meshes, name=f"{piece.name}_BaseMesh"),
            )
            for piece in result.pieces
        ),
    )


def _merge_mesh_data(meshes: tuple[MeshData, ...], *, name: str) -> MeshData:
    if not meshes:
        raise FractureError(f"Boolean fracture piece {name} has no geometry.")
    meshes = tuple(_with_face_varying_normals(mesh) for mesh in meshes)
    if len(meshes) == 1:
        return replace(meshes[0], name=name)

    has_uvs = any(mesh.uv_coords for mesh in meshes)
    has_secondary_uvs = any(mesh.secondary_uv_coords for mesh in meshes)
    has_colors = any(mesh.vertex_colors for mesh in meshes)
    has_normals = any(mesh.normals for mesh in meshes)
    skin_size = max(mesh.skel_element_size for mesh in meshes)
    if has_uvs and any(len(mesh.uv_coords) != len(mesh.face_vertex_indices) for mesh in meshes):
        raise FractureError(f"Boolean fracture piece {name} has inconsistent primary UVs.")
    if has_secondary_uvs and any(len(mesh.secondary_uv_coords) != len(mesh.face_vertex_indices) for mesh in meshes):
        raise FractureError(f"Boolean fracture piece {name} has inconsistent secondary UVs.")
    if has_colors and any(len(mesh.vertex_colors) not in (len(mesh.points), len(mesh.face_vertex_indices)) for mesh in meshes):
        raise FractureError(f"Boolean fracture piece {name} has inconsistent vertex colors.")
    if has_normals and any(len(mesh.normals) not in (len(mesh.points), len(mesh.face_vertex_indices)) for mesh in meshes):
        raise FractureError(f"Boolean fracture piece {name} has inconsistent normals.")
    if skin_size and any(mesh.skel_element_size != skin_size for mesh in meshes):
        raise FractureError(f"Boolean fracture piece {name} has inconsistent skin element sizes.")

    points: list[Vector3] = []
    counts: list[int] = []
    indices: list[int] = []
    uvs: list[Vector2] = []
    secondary_uvs: list[Vector2] = []
    colors: list[Color4] = []
    normals: list[Vector3] = []
    joint_indices: list[int] = []
    joint_weights: list[float] = []
    sections_by_material: dict[int, list[int]] = {}
    point_offset = 0
    face_offset = 0
    for mesh in meshes:
        points.extend(mesh.points)
        counts.extend(mesh.face_vertex_counts)
        indices.extend(point_offset + int(index) for index in mesh.face_vertex_indices)
        uvs.extend(mesh.uv_coords)
        secondary_uvs.extend(mesh.secondary_uv_coords)
        colors.extend(mesh.vertex_colors)
        normals.extend(mesh.normals)
        joint_indices.extend(mesh.skel_joint_indices)
        joint_weights.extend(mesh.skel_joint_weights)
        for section in mesh.sections:
            sections_by_material.setdefault(section.material_id, []).extend(
                face_offset + int(index) for index in section.face_indices
            )
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
            for material_id, face_indices in sorted(sections_by_material.items())
        ),
        skel_joint_indices=tuple(joint_indices),
        skel_joint_weights=tuple(joint_weights),
        skel_element_size=skin_size,
    )


def _with_face_varying_normals(mesh: MeshData) -> MeshData:
    """Ensure mixed untouched/Boolean chunks share one explicit normal contract."""
    if len(mesh.normals) in (len(mesh.points), len(mesh.face_vertex_indices)):
        return mesh
    if mesh.normals:
        raise FractureError(
            f"Boolean fracture mesh {mesh.name} has {len(mesh.normals)} normals for "
            f"{len(mesh.points)} points and {len(mesh.face_vertex_indices)} face vertices."
        )

    normals: list[Vector3] = []
    cursor = 0
    for face_index, vertex_count in enumerate(mesh.face_vertex_counts):
        face_indices = mesh.face_vertex_indices[cursor : cursor + vertex_count]
        cursor += vertex_count
        if vertex_count < 3 or len(face_indices) != vertex_count:
            raise FractureError(f"Boolean fracture mesh {mesh.name} face {face_index} is not a valid polygon.")
        points = np.asarray(
            [(mesh.points[index].x, mesh.points[index].y, mesh.points[index].z) for index in face_indices],
            dtype=np.float64,
        )
        face_normal = _normal_vector3(_newell_normal(points))
        normals.extend((face_normal,) * vertex_count)
    if cursor != len(mesh.face_vertex_indices):
        raise FractureError(f"Boolean fracture mesh {mesh.name} has trailing face vertex indices.")
    return replace(mesh, normals=tuple(normals))


def _build_prepared_boolean_cut(
    prepared: _PreparedBooleanCut,
    settings: BooleanCutPrototypeSettings,
    include_preparation_timings: bool,
) -> BooleanCutPrototypeResult:
    settings = settings.validated()
    if settings.cut_token != prepared.cut_token:
        raise FractureError(
            f"Prepared Boolean cut {prepared.cut_token} cannot build different cut {settings.cut_token}."
        )
    timings = list(prepared.preparation_timings) if include_preparation_timings else [("reuse_prepared_cut", 0.0)]

    built_cutter = _build_prepared_cutter(prepared, settings)
    timings.append(("build_cutter", built_cutter.seconds))

    started = time.perf_counter()
    branch = _prepared_branch_manifold(prepared)
    parent, child = branch.split(built_cutter.manifold)
    _require_valid_manifold(parent, "parent intersection")
    _require_valid_manifold(child, "detached child difference")
    weld_tolerance = max(float(np.ptp(prepared.closed_vertices, axis=0).max()) * 1e-7, 1e-9)
    parent = parent.simplify(weld_tolerance)
    child = child.simplify(weld_tolerance)
    timings.append(("boolean", time.perf_counter() - started))

    started = time.perf_counter()
    id_to_tag = {prepared.closure_id: 1, prepared.cutter_id: 2}
    parent_tagged = _from_manifold(
        parent,
        source_id_start=prepared.source_id_start,
        source_triangle_indices=prepared.component_indices,
        id_to_tag=id_to_tag,
    )
    child_tagged = _from_manifold(
        child,
        source_id_start=prepared.source_id_start,
        source_triangle_indices=prepared.component_indices,
        id_to_tag=id_to_tag,
    )
    child_tagged = _canonicalize_child_cap(parent_tagged, child_tagged, cap_tag=2)
    parent_open = _drop_tag(parent_tagged, 1)
    child_open = _drop_tag(child_tagged, 1)
    _validate_triangle_quality(parent_open, "parent result")
    _validate_triangle_quality(child_open, "detached child result")
    cap_vertex_count = _validate_matching_caps(parent_open, child_open, cap_tag=2)
    result_boundary_count = (
        _stage_diagnostics(parent_open, None).boundary_count
        + _stage_diagnostics(child_open, None).boundary_count
    )
    if result_boundary_count != prepared.original_boundary_count:
        raise FractureError(
            "Boolean prototype cap canonicalization created a seam or a new hole: "
            f"source boundary edges={prepared.original_boundary_count}, result boundary edges={result_boundary_count}."
        )
    result_volume = float(parent.volume() + child.volume())
    tolerance = max(1e-9, abs(prepared.source_volume) * 1e-5)
    if abs(prepared.source_volume - result_volume) > tolerance:
        raise FractureError(
            "Boolean prototype volume conservation failed: "
            f"source={prepared.source_volume:.9g}, results={result_volume:.9g}, tolerance={tolerance:.3g}."
        )
    timings.append(("validate_results", time.perf_counter() - started))

    cutter_stage = built_cutter.surface
    stages = (
        ("Original Shell", _stage_diagnostics(prepared.original, None)),
        ("Closed Solid", _stage_diagnostics(prepared.closed, prepared.source_volume)),
        ("Cutter Surface", _stage_diagnostics(cutter_stage, None)),
        ("Parent Stub", _stage_diagnostics(parent_open, float(parent.volume()))),
        ("Detached Branch", _stage_diagnostics(child_open, float(child.volume()))),
    )

    started = time.perf_counter()
    parent_result = _attributed_mesh_data(
        "BooleanParentStub",
        parent_open,
        prepared.mesh,
        prepared.triangles,
        prepared.source_face_indices,
        prepared.source_corner_slots,
        prepared.frame,
        cap_material_id=settings.cap_material_id,
    )
    child_result = _attributed_mesh_data(
        "BooleanDetachedBranch",
        child_open,
        prepared.mesh,
        prepared.triangles,
        prepared.source_face_indices,
        prepared.source_corner_slots,
        prepared.frame,
        cap_material_id=settings.cap_material_id,
    )
    timings.append(("transfer_attributes", time.perf_counter() - started))
    return BooleanCutPrototypeResult(
        original_shell=prepared.original_shell,
        closed_solid=prepared.closed_solid,
        cutter_surface=_mesh_data("BooleanCutterSurface", cutter_stage),
        parent_result=parent_result,
        child_result=child_result,
        diagnostics=BooleanCutPrototypeDiagnostics(
            selected_component_index=prepared.selected_component_index,
            source_component_count=prepared.source_component_count,
            source_face_count=len(prepared.component_triangles),
            closure_face_count=len(prepared.closure_triangles),
            cutter_triangle_count=built_cutter.triangle_count,
            cap_vertex_count=cap_vertex_count,
            cut_origin=Vector3(
                float(prepared.frame.origin[0]),
                float(prepared.frame.origin[1]),
                float(prepared.frame.origin[2]),
            ),
            requested_amplitude=built_cutter.requested_amplitude,
            effective_amplitude=built_cutter.effective_amplitude,
            amplitude_limit_distance=built_cutter.safe_limit,
            amplitude_limit_reason=built_cutter.noise_limit.reason,
            amplitude_limit_joint_token=built_cutter.noise_limit.joint_token,
            stages=stages,
        ),
        stage_timings=tuple(timings),
    )


def _build_prepared_cutter(
    prepared: _PreparedBooleanCut,
    settings: BooleanCutPrototypeSettings,
) -> _BuiltCutter:
    started = time.perf_counter()
    noise_limit = _forward_noise_limit(
        prepared.model,
        prepared.cut_site,
        prepared.frame,
        settings.max_bend_angle_degrees,
    )
    cutter_vertices, cutter_triangles, cutter_top_count, requested_amplitude, effective_amplitude, safe_limit = (
        _build_cutter(
            prepared.closed_vertices,
            prepared.component_triangles,
            prepared.frame,
            settings,
            prepared.seed,
            noise_limit.distance,
        )
    )
    cutter = _to_manifold(
        prepared.manifold3d,
        cutter_vertices,
        cutter_triangles,
        ((0, len(cutter_triangles), prepared.cutter_id),),
        "Boolean cutter",
    )
    surface = _TaggedMesh(
        cutter_vertices,
        cutter_triangles[:cutter_top_count],
        np.full(cutter_top_count, 3, dtype=np.uint8),
        np.full(cutter_top_count, -1, dtype=np.int64),
    )
    return _BuiltCutter(
        manifold=cutter,
        surface=surface,
        triangle_count=len(cutter_triangles),
        requested_amplitude=requested_amplitude,
        effective_amplitude=effective_amplitude,
        safe_limit=safe_limit,
        noise_limit=noise_limit,
        seconds=time.perf_counter() - started,
    )


def _multi_cut_settings(
    settings: BooleanMultiPrototypeSettings,
    cut_token: str,
) -> BooleanCutPrototypeSettings:
    return BooleanCutPrototypeSettings(
        cut_token=cut_token,
        intensity=settings.intensity,
        chip_scale=settings.chip_scale,
        remesh_density=settings.remesh_density,
        max_bend_angle_degrees=settings.max_bend_angle_degrees,
        cap_material_id=settings.cap_material_id,
    )


def _build_sequential_component(
    entries: tuple[tuple[BooleanCutPrototypeSession, FractureCutSite, int, int], ...],
    settings: BooleanMultiPrototypeSettings,
) -> _SequentialComponentBuild:
    base = entries[0][0]._prepared
    if any(
        session.selected_component_index != base.selected_component_index
        or not np.array_equal(session._prepared.component_indices, base.component_indices)
        for session, _cut_site, _parent_piece, _child_piece in entries[1:]
    ):
        raise FractureError("Boolean nested cuts do not reference one identical source component.")

    region_by_piece: dict[int, object] = {entries[0][2]: _prepared_branch_manifold(base)}
    built_cutters: list[_BuiltCutter] = []
    boolean_seconds: list[float] = []
    cap_tag_by_cutter_id: dict[int, int] = {}
    weld_tolerance = max(float(np.ptp(base.closed_vertices, axis=0).max()) * 1e-7, 1e-9)
    for local_index, (session, cut_site, parent_piece_index, child_piece_index) in enumerate(entries):
        region = region_by_piece.get(parent_piece_index)
        if region is None:
            raise FractureError(
                f"Boolean nested cut {cut_site.joint_token} must follow the cut that creates "
                f"parent piece {parent_piece_index}."
            )
        prepared = session._prepared
        built = _build_prepared_cutter(prepared, _multi_cut_settings(settings, session.cut_token))
        started = time.perf_counter()
        parent, child = region.split(built.manifold)
        _require_valid_manifold(parent, f"nested parent {cut_site.joint_token}")
        _require_valid_manifold(child, f"nested child {cut_site.joint_token}")
        parent = parent.simplify(weld_tolerance)
        child = child.simplify(weld_tolerance)
        boolean_seconds.append(time.perf_counter() - started)
        region_by_piece[parent_piece_index] = parent
        if child_piece_index in region_by_piece:
            raise FractureError(
                f"Boolean nested cut {cut_site.joint_token} would overwrite piece {child_piece_index}."
            )
        region_by_piece[child_piece_index] = child
        built_cutters.append(built)
        cap_tag_by_cutter_id[prepared.cutter_id] = 2 + local_index

    result_volume = sum(float(region.volume()) for region in region_by_piece.values())
    volume_tolerance = max(1e-9, abs(base.source_volume) * 1e-5)
    if abs(base.source_volume - result_volume) > volume_tolerance:
        raise FractureError(
            "Boolean nested cuts failed volume conservation: "
            f"source={base.source_volume:.9g}, results={result_volume:.9g}, tolerance={volume_tolerance:.3g}."
        )

    id_to_tag = {base.closure_id: 1, **cap_tag_by_cutter_id}
    tagged_by_piece = {
        piece_index: _drop_tag(
            _from_manifold(
                region,
                source_id_start=base.source_id_start,
                source_triangle_indices=base.component_indices,
                id_to_tag=id_to_tag,
            ),
            1,
        )
        for piece_index, region in region_by_piece.items()
    }
    cap_vertex_counts: list[int] = []
    cap_frames: dict[int, _CutFrame] = {}
    for local_index, (session, cut_site, parent_piece_index, child_piece_index) in enumerate(entries):
        cap_tag = 2 + local_index
        parent_tagged = tagged_by_piece[parent_piece_index]
        child_tagged = _canonicalize_child_cap(parent_tagged, tagged_by_piece[child_piece_index], cap_tag)
        tagged_by_piece[child_piece_index] = child_tagged
        cap_vertex_counts.append(_validate_matching_caps(parent_tagged, child_tagged, cap_tag))
        cap_frames[cap_tag] = session._prepared.frame

    for piece_index, tagged in tagged_by_piece.items():
        _validate_triangle_quality(tagged, f"nested piece {piece_index}")
    boundary_count = sum(_stage_diagnostics(tagged, None).boundary_count for tagged in tagged_by_piece.values())
    if boundary_count != base.original_boundary_count:
        raise FractureError(
            "Boolean nested cuts created a seam or new hole: "
            f"source boundaries={base.original_boundary_count}, result boundaries={boundary_count}."
        )

    transfer_started = time.perf_counter()
    mesh_by_piece = {
        piece_index: _attributed_mesh_data(
            f"BooleanNestedPiece{piece_index:02d}",
            tagged,
            base.mesh,
            base.triangles,
            base.source_face_indices,
            base.source_corner_slots,
            base.frame,
            cap_frames=cap_frames,
            cap_material_id=settings.cap_material_id,
        )
        for piece_index, tagged in tagged_by_piece.items()
    }
    transfer_seconds = time.perf_counter() - transfer_started

    cut_results: list[BooleanCutPrototypeResult] = []
    for local_index, ((session, _cut_site, parent_piece_index, child_piece_index), built) in enumerate(
        zip(entries, built_cutters)
    ):
        prepared = session._prepared
        parent_tagged = tagged_by_piece[parent_piece_index]
        child_tagged = tagged_by_piece[child_piece_index]
        cut_results.append(
            BooleanCutPrototypeResult(
                original_shell=prepared.original_shell,
                closed_solid=prepared.closed_solid,
                cutter_surface=_mesh_data("BooleanCutterSurface", built.surface),
                parent_result=mesh_by_piece[parent_piece_index],
                child_result=mesh_by_piece[child_piece_index],
                diagnostics=BooleanCutPrototypeDiagnostics(
                    selected_component_index=prepared.selected_component_index,
                    source_component_count=prepared.source_component_count,
                    source_face_count=len(prepared.component_triangles),
                    closure_face_count=len(base.closure_triangles),
                    cutter_triangle_count=built.triangle_count,
                    cap_vertex_count=cap_vertex_counts[local_index],
                    cut_origin=Vector3(
                        float(prepared.frame.origin[0]),
                        float(prepared.frame.origin[1]),
                        float(prepared.frame.origin[2]),
                    ),
                    requested_amplitude=built.requested_amplitude,
                    effective_amplitude=built.effective_amplitude,
                    amplitude_limit_distance=built.safe_limit,
                    amplitude_limit_reason=built.noise_limit.reason,
                    amplitude_limit_joint_token=built.noise_limit.joint_token,
                    stages=(
                        ("Original Shell", _stage_diagnostics(prepared.original, None)),
                        ("Closed Solid", _stage_diagnostics(prepared.closed, base.source_volume)),
                        ("Cutter Surface", _stage_diagnostics(built.surface, None)),
                        (
                            "Parent Stub",
                            _stage_diagnostics(parent_tagged, float(region_by_piece[parent_piece_index].volume())),
                        ),
                        (
                            "Detached Branch",
                            _stage_diagnostics(child_tagged, float(region_by_piece[child_piece_index].volume())),
                        ),
                    ),
                ),
                stage_timings=(
                    ("build_cutter", built.seconds),
                    ("boolean", boolean_seconds[local_index]),
                    ("transfer_component_attributes", transfer_seconds / len(entries)),
                ),
            )
        )
    return _SequentialComponentBuild(
        cut_results=tuple(cut_results),
        piece_meshes=tuple(sorted(mesh_by_piece.items())),
    )


def _manifold_module():
    try:
        import manifold3d
    except ImportError as exc:
        raise FractureError("Boolean prototype requires manifold3d>=3.5,<4.") from exc
    return manifold3d


def _triangulated_mesh(mesh: MeshData) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    vertices = np.asarray([(point.x, point.y, point.z) for point in mesh.points], dtype=np.float64)
    triangles: list[tuple[int, int, int]] = []
    source_faces: list[int] = []
    source_corner_slots: list[tuple[int, int, int]] = []
    cursor = 0
    for face_index, count in enumerate(mesh.face_vertex_counts):
        polygon = mesh.face_vertex_indices[cursor : cursor + count]
        cursor += count
        if count < 3:
            raise FractureError(f"Boolean prototype source face {face_index} has fewer than three vertices.")
        for offset in range(1, count - 1):
            triangles.append((polygon[0], polygon[offset], polygon[offset + 1]))
            source_faces.append(face_index)
            source_corner_slots.append((cursor - count, cursor - count + offset, cursor - count + offset + 1))
    if cursor != len(mesh.face_vertex_indices):
        raise FractureError("Boolean prototype source mesh has trailing face indices.")
    return (
        vertices,
        np.asarray(triangles, dtype=np.uint32),
        np.asarray(source_faces, dtype=np.uint32),
        np.asarray(source_corner_slots, dtype=np.uint32),
    )


def _triangle_components(triangles: np.ndarray) -> tuple[np.ndarray, ...]:
    edge_faces: dict[tuple[int, int], list[int]] = {}
    for face_index, tri in enumerate(triangles):
        first, second, third = tri.tolist()
        for start, end in ((first, second), (second, third), (third, first)):
            edge = (start, end) if start < end else (end, start)
            edge_faces.setdefault(edge, []).append(face_index)
    neighbors: list[list[int]] = [[] for _ in range(len(triangles))]
    for faces in edge_faces.values():
        for face in faces[1:]:
            neighbors[faces[0]].append(face)
            neighbors[face].append(faces[0])
    unseen = set(range(len(triangles)))
    components: list[np.ndarray] = []
    while unseen:
        root = min(unseen)
        unseen.remove(root)
        stack = [root]
        faces: list[int] = []
        while stack:
            face = stack.pop()
            faces.append(face)
            for neighbor in neighbors[face]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    stack.append(neighbor)
        components.append(np.asarray(sorted(faces), dtype=np.uint32))
    return tuple(components)


def _select_component(
    components: tuple[np.ndarray, ...],
    triangles: np.ndarray,
    source_face_indices: np.ndarray,
    child_faces: frozenset[int],
    anchor_faces: frozenset[int],
    vertices: np.ndarray,
    frame: _CutFrame,
    cut_token: str,
) -> int:
    candidates: list[tuple[int, int]] = []
    descriptions: list[str] = []
    for index, component in enumerate(components):
        owned = sum(int(source_face_indices[face]) in child_faces for face in component)
        anchored = sum(int(source_face_indices[face]) in anchor_faces for face in component)
        signed = (vertices[triangles[component]] - frame.origin) @ frame.normal
        crosses = bool(np.any((np.min(signed, axis=1) <= _EPSILON) & (np.max(signed, axis=1) >= -_EPSILON)))
        evidence = anchored if anchor_faces else owned
        if evidence and crosses:
            candidates.append((evidence, index))
        if anchored or owned or crosses:
            descriptions.append(
                f"{index}(faces={len(component)}, anchor_faces={anchored}, child_faces={owned}, crosses={crosses})"
            )
    if candidates:
        strongest = max(evidence for evidence, _index in candidates)
        winners = [index for evidence, index in candidates if evidence == strongest]
    else:
        winners = []
    if len(winners) != 1:
        detail = ", ".join(descriptions) or "none"
        raise FractureError(
            f"Boolean prototype cut {cut_token} requires one dominant child component crossing the cut plane; "
            f"found {len(winners)} strongest candidates. Relevant components: {detail}."
        )
    return winners[0]


def _boundary_loops(triangles: np.ndarray, cut_token: str) -> tuple[tuple[int, ...], ...]:
    directed_by_key: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for tri in triangles:
        first, second, third = tri.tolist()
        for start, end in ((first, second), (second, third), (third, first)):
            edge = (start, end) if start < end else (end, start)
            directed_by_key.setdefault(edge, []).append((start, end))
    nonmanifold = [key for key, edges in directed_by_key.items() if len(edges) > 2]
    if nonmanifold:
        raise FractureError(f"Boolean prototype cut {cut_token} source component has non-manifold edges: {nonmanifold[:12]}.")
    boundary = [edges[0] for edges in directed_by_key.values() if len(edges) == 1]
    outgoing: dict[int, list[int]] = {}
    incoming: dict[int, list[int]] = {}
    for start, end in boundary:
        outgoing.setdefault(start, []).append(end)
        incoming.setdefault(end, []).append(start)
    bad = sorted(vertex for vertex in set(outgoing) | set(incoming) if len(outgoing.get(vertex, ())) != 1 or len(incoming.get(vertex, ())) != 1)
    if bad:
        degrees = [(vertex, len(incoming.get(vertex, ())) + len(outgoing.get(vertex, ()))) for vertex in bad[:12]]
        raise FractureError(
            f"Boolean prototype cut {cut_token} has broken or intersecting boundary loops; expected degree 2: {degrees}."
        )
    unvisited = set(outgoing)
    loops: list[tuple[int, ...]] = []
    while unvisited:
        start = min(unvisited)
        loop = [start]
        current = start
        while True:
            unvisited.discard(current)
            current = outgoing[current][0]
            if current == start:
                break
            if current in loop:
                raise FractureError(f"Boolean prototype cut {cut_token} boundary loop self-intersects at vertex {current}.")
            loop.append(current)
        if len(loop) < 3:
            raise FractureError(f"Boolean prototype cut {cut_token} has a boundary loop shorter than three vertices.")
        loops.append(tuple(loop))
    return tuple(loops)


def _close_boundary_loops(
    vertices: np.ndarray,
    source_triangles: np.ndarray,
    loops: tuple[tuple[int, ...], ...],
) -> tuple[np.ndarray, np.ndarray]:
    manifold3d = _manifold_module()
    closure: list[tuple[int, int, int]] = []
    for source_loop in loops:
        loop = tuple(reversed(source_loop))
        points = vertices[np.asarray(loop, dtype=np.uint32)]
        normal = _newell_normal(points)
        tangent, bitangent = _basis(normal)
        projected = np.column_stack((points @ tangent, points @ bitangent))
        if _signed_area(projected) < 0.0:
            projected[:, 1] *= -1.0
        local_triangles = np.asarray(manifold3d.triangulate([projected], allow_convex=False), dtype=np.uint32)
        if len(local_triangles) != len(loop) - 2:
            raise FractureError(
                f"Boolean prototype boundary triangulation returned {len(local_triangles)} triangles for {len(loop)} vertices."
            )
        for tri in local_triangles:
            closure.append(tuple(loop[int(index)] for index in tri))
    result = np.asarray(closure, dtype=np.uint32)
    _validate_closed_topology(np.vstack((source_triangles, result)))
    return vertices, result


def _validate_closed_topology(triangles: np.ndarray) -> None:
    counts: dict[tuple[int, int], int] = {}
    orientation: dict[tuple[int, int], int] = {}
    for tri in triangles:
        for start, end in ((int(tri[0]), int(tri[1])), (int(tri[1]), int(tri[2])), (int(tri[2]), int(tri[0]))):
            key = (min(start, end), max(start, end))
            counts[key] = counts.get(key, 0) + 1
            orientation[key] = orientation.get(key, 0) + (1 if start < end else -1)
    invalid = [key for key, count in counts.items() if count != 2 or orientation[key] != 0]
    if invalid:
        raise FractureError(f"Boolean prototype temporary solid is not an oriented 2-manifold at edges {invalid[:12]}.")


def _build_cutter(
    vertices: np.ndarray,
    component_triangles: np.ndarray,
    frame: _CutFrame,
    settings: BooleanCutPrototypeSettings,
    seed: int,
    amplitude_limit_distance: float,
) -> tuple[np.ndarray, np.ndarray, int, float, float, float]:
    component_vertex_indices = np.unique(component_triangles)
    points = vertices[component_vertex_indices]
    offsets = points - frame.origin
    uv = np.column_stack((offsets @ frame.tangent, offsets @ frame.bitangent))
    axial = offsets @ frame.normal
    tri_signed = (vertices[component_triangles] - frame.origin) @ frame.normal
    crossing = component_triangles[(np.min(tri_signed, axis=1) <= _EPSILON) & (np.max(tri_signed, axis=1) >= -_EPSILON)]
    if not len(crossing):
        raise FractureError(f"Boolean prototype cut {settings.cut_token} has no source triangles crossing its plane.")
    crossing_points = vertices[np.unique(crossing)] - frame.origin
    crossing_uv = np.column_stack((crossing_points @ frame.tangent, crossing_points @ frame.bitangent))
    diameter = max(float(np.ptp(crossing_uv[:, 0])), float(np.ptp(crossing_uv[:, 1])))
    if diameter <= _EPSILON:
        raise FractureError(f"Boolean prototype cut {settings.cut_token} has zero local branch diameter.")
    radius = diameter * 0.5
    edge = diameter / settings.remesh_density
    row_height = edge * math.sqrt(3.0) * 0.5
    u_min, v_min = np.min(uv, axis=0) - edge
    u_max, v_max = np.max(uv, axis=0) + edge
    columns = max(2, int(math.ceil((u_max - u_min) / edge)) + 1)
    rows = max(2, int(math.ceil((v_max - v_min) / row_height)) + 1)
    top_tri_count = 2 * (columns - 1) * (rows - 1)
    total_tri_count = top_tri_count * 2 + 4 * (columns + rows - 2)
    if total_tri_count > _MAX_CUTTER_TRIANGLES:
        raise FractureError(
            f"Boolean prototype cutter needs {total_tri_count} triangles, above {_MAX_CUTTER_TRIANGLES}; "
            f"component projection={u_max-u_min:.6g}x{v_max-v_min:.6g}, density={settings.remesh_density}."
        )
    requested_amplitude = radius * 0.35 * float(settings.intensity)
    safe_limit = max(0.0, float(amplitude_limit_distance) - edge)
    amplitude = min(requested_amplitude, safe_limit)
    wavelength = radius * float(settings.chip_scale)
    top_local: list[tuple[float, float, float]] = []
    for row in range(rows):
        v = v_min + row * row_height
        shift = 0.5 * edge if row % 2 else 0.0
        for column in range(columns):
            u = u_min + column * edge + shift
            height = amplitude * _fractal_perlin(u / wavelength, v / wavelength, seed)
            top_local.append((u, v, height))
    bottom_height = float(np.min(axial) - max(diameter, float(np.ptp(axial)) * 0.05))
    local = np.asarray(top_local + [(u, v, bottom_height) for u, v, _ in top_local], dtype=np.float64)
    world = (
        frame.origin
        + local[:, 0:1] * frame.tangent
        + local[:, 1:2] * frame.bitangent
        + local[:, 2:3] * frame.normal
    )
    triangles: list[tuple[int, int, int]] = []
    for row in range(rows - 1):
        for column in range(columns - 1):
            a = row * columns + column
            b = a + 1
            c = a + columns
            d = c + 1
            triangles.extend(((a, b, d), (a, d, c)))
    top_triangles = list(triangles)
    bottom_offset = rows * columns
    triangles.extend(
        (c + bottom_offset, b + bottom_offset, a + bottom_offset)
        for a, b, c in top_triangles
    )
    perimeter = (
        list(range(columns))
        + [row * columns + columns - 1 for row in range(1, rows)]
        + list(range((rows - 1) * columns + columns - 2, (rows - 1) * columns - 1, -1))
        + [row * columns for row in range(rows - 2, 0, -1)]
    )
    for index, top_a in enumerate(perimeter):
        top_b = perimeter[(index + 1) % len(perimeter)]
        bottom_a = top_a + bottom_offset
        bottom_b = top_b + bottom_offset
        triangles.extend(((top_b, top_a, bottom_a), (top_b, bottom_a, bottom_b)))
    triangle_array = np.asarray(triangles, dtype=np.uint32)
    _validate_closed_topology(triangle_array)
    return world, triangle_array, len(top_triangles), requested_amplitude, amplitude, safe_limit


def _to_manifold(manifold3d, vertices, triangles, runs, label: str):
    run_index = [0]
    run_ids = []
    for start, end, original_id in runs:
        if start != run_index[-1] // 3:
            raise FractureError(f"Boolean prototype {label} provenance runs are not contiguous.")
        run_index.append(end * 3)
        run_ids.append(original_id)
    mesh = manifold3d.Mesh(
        np.asarray(vertices, dtype=np.float32, order="C"),
        np.asarray(triangles, dtype=np.uint32, order="C"),
        run_index=np.asarray(run_index, dtype=np.uint32),
        run_original_id=np.asarray(run_ids, dtype=np.uint32),
    )
    result = manifold3d.Manifold(mesh)
    _require_valid_manifold(result, label)
    return result


def _prepared_branch_manifold(prepared: _PreparedBooleanCut):
    source_triangle_count = len(prepared.component_triangles)
    source_runs = tuple(
        (index, index + 1, prepared.source_id_start + index)
        for index in range(source_triangle_count)
    )
    return _to_manifold(
        prepared.manifold3d,
        prepared.closed_vertices,
        prepared.closed.triangles,
        source_runs + ((source_triangle_count, len(prepared.closed.triangles), prepared.closure_id),),
        "closed branch solid",
    )


def _require_valid_manifold(manifold, label: str) -> None:
    status = manifold.status()
    if str(status).split(".")[-1] != "NoError":
        raise FractureError(f"Boolean prototype {label} failed Manifold validation: {status}.")
    if manifold.is_empty():
        raise FractureError(f"Boolean prototype {label} is empty.")


def _from_manifold(
    manifold,
    *,
    source_id_start: int,
    source_triangle_indices: np.ndarray,
    id_to_tag: dict[int, int],
) -> _TaggedMesh:
    mesh = manifold.to_mesh()
    # manifold3d exposes NumPy views owned by the temporary Mesh.  Retaining
    # those views after this function returns is a native use-after-free.
    triangles = np.array(mesh.tri_verts, dtype=np.uint32, order="C", copy=True)
    vertices = np.array(mesh.vert_properties[:, :3], dtype=np.float64, order="C", copy=True)
    tags = np.empty(len(triangles), dtype=np.uint8)
    provenance = np.full(len(triangles), -1, dtype=np.int64)
    run_index = list(mesh.run_index)
    for run, original_id in enumerate(mesh.run_original_id):
        original_id = int(original_id)
        start = run_index[run] // 3
        end = run_index[run + 1] // 3
        source_offset = original_id - source_id_start
        if 0 <= source_offset < len(source_triangle_indices):
            tags[start:end] = 0
            provenance[start:end] = int(source_triangle_indices[source_offset])
            continue
        tag = id_to_tag.get(original_id)
        if tag is None:
            raise FractureError(f"Boolean prototype result contains unknown provenance id {original_id}.")
        tags[start:end] = tag
    return _TaggedMesh(vertices, triangles, tags, provenance)


def _drop_tag(mesh: _TaggedMesh, tag: int) -> _TaggedMesh:
    keep = mesh.tags != tag
    return _TaggedMesh(mesh.vertices, mesh.triangles[keep], mesh.tags[keep], mesh.source_triangle_indices[keep])


def _canonicalize_child_cap(parent: _TaggedMesh, child: _TaggedMesh, cap_tag: int) -> _TaggedMesh:
    """Use one shared cap triangulation; Manifold otherwise remeshes each side independently."""
    parent_caps = parent.triangles[parent.tags == cap_tag]
    if not len(parent_caps):
        raise FractureError("Boolean prototype parent result has no cutter-derived cap to canonicalize.")
    scale = max(float(np.ptp(parent.vertices, axis=0).max()), 1.0)
    tolerance = scale * 1e-6

    def key(point: np.ndarray) -> tuple[int, int, int]:
        return tuple(int(round(float(value) / tolerance)) for value in point)

    vertices = [np.array(point, copy=True) for point in child.vertices]
    child_index_by_position: dict[tuple[int, int, int], int] = {}
    for index, point in enumerate(vertices):
        child_index_by_position.setdefault(key(point), index)
    parent_to_child: dict[int, int] = {}
    for parent_index in np.unique(parent_caps):
        point = parent.vertices[int(parent_index)]
        position_key = key(point)
        child_index = child_index_by_position.get(position_key)
        if child_index is None:
            child_index = len(vertices)
            vertices.append(np.array(point, copy=True))
            child_index_by_position[position_key] = child_index
        parent_to_child[int(parent_index)] = child_index
    keep = child.tags != cap_tag
    triangles = [tuple(int(index) for index in tri) for tri in child.triangles[keep]]
    tags = [int(tag) for tag in child.tags[keep]]
    provenance = [int(index) for index in child.source_triangle_indices[keep]]
    for tri in parent_caps:
        triangles.append(
            (
                parent_to_child[int(tri[0])],
                parent_to_child[int(tri[2])],
                parent_to_child[int(tri[1])],
            )
        )
        tags.append(cap_tag)
        provenance.append(-1)
    return _TaggedMesh(
        np.asarray(vertices, dtype=np.float64),
        np.asarray(triangles, dtype=np.uint32),
        np.asarray(tags, dtype=np.uint8),
        np.asarray(provenance, dtype=np.int64),
    )


def _validate_matching_caps(parent: _TaggedMesh, child: _TaggedMesh, cap_tag: int) -> int:
    parent_caps = parent.triangles[parent.tags == cap_tag]
    child_caps = child.triangles[child.tags == cap_tag]
    if not len(parent_caps) or not len(child_caps):
        raise FractureError("Boolean prototype did not produce cutter-derived caps on both results.")
    scale = max(float(np.ptp(parent.vertices, axis=0).max()), 1.0)
    tolerance = scale * 1e-6

    def key(point):
        return tuple(int(round(float(value) / tolerance)) for value in point)

    parent_points = {key(parent.vertices[index]) for index in np.unique(parent_caps)}
    child_points = {key(child.vertices[index]) for index in np.unique(child_caps)}
    if parent_points != child_points:
        raise FractureError(
            "Boolean prototype parent/child cap vertex sets differ: "
            f"parent={len(parent_points)}, child={len(child_points)}, shared={len(parent_points & child_points)}."
        )
    parent_oriented = {
        tuple(key(parent.vertices[index]) for index in tri)
        for tri in parent_caps
    }
    child_reversed = {
        tuple(key(child.vertices[index]) for index in (tri[0], tri[2], tri[1]))
        for tri in child_caps
    }
    if parent_oriented != child_reversed:
        raise FractureError(
            "Boolean prototype parent/child caps do not have identical triangulation with opposite winding."
        )
    return len(parent_points)


def _validate_triangle_quality(mesh: _TaggedMesh, label: str) -> None:
    points = mesh.vertices[mesh.triangles]
    doubled_areas = np.linalg.norm(
        np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0]),
        axis=1,
    )
    scale = max(float(np.ptp(mesh.vertices, axis=0).max()), 1.0)
    degenerate = np.flatnonzero(doubled_areas <= scale * scale * 1e-12)
    if len(degenerate):
        raise FractureError(
            f"Boolean prototype {label} contains degenerate triangles: {degenerate[:12].tolist()}."
        )


def _stage_diagnostics(mesh: _TaggedMesh, volume: float | None) -> PrototypeStageDiagnostics:
    edge_counts: dict[tuple[int, int], int] = {}
    for tri in mesh.triangles:
        first, second, third = tri.tolist()
        for start, end in ((first, second), (second, third), (third, first)):
            key = (start, end) if start < end else (end, start)
            edge_counts[key] = edge_counts.get(key, 0) + 1
    boundary_edges = [edge for edge, count in edge_counts.items() if count == 1]
    boundary_neighbors: dict[int, set[int]] = {}
    for start, end in boundary_edges:
        boundary_neighbors.setdefault(start, set()).add(end)
        boundary_neighbors.setdefault(end, set()).add(start)
    unseen = set(boundary_neighbors)
    boundary_loops = 0
    while unseen:
        boundary_loops += 1
        stack = [unseen.pop()]
        while stack:
            for neighbor in boundary_neighbors[stack.pop()]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    stack.append(neighbor)
    return PrototypeStageDiagnostics(
        face_count=len(mesh.triangles),
        boundary_count=boundary_loops,
        volume=volume,
    )


def _mesh_data(name: str, mesh: _TaggedMesh, *, source_color: Color4 = _SOURCE_COLOR) -> MeshData:
    expanded_points = mesh.vertices[mesh.triangles.reshape(-1)]
    indices = tuple(range(len(expanded_points)))
    palette = (source_color, _CLOSURE_COLOR, _BOOLEAN_CAP_COLOR, _CUTTER_COLOR)
    colors = tuple(palette[int(tag)] for tag in mesh.tags for _ in range(3))
    return MeshData(
        name=name,
        points=tuple(Vector3(float(x), float(y), float(z)) for x, y, z in expanded_points),
        face_vertex_counts=(3,) * len(mesh.triangles),
        face_vertex_indices=indices,
        vertex_colors=colors,
    )


def _attributed_mesh_data(
    name: str,
    result: _TaggedMesh,
    source: MeshData,
    source_triangles: np.ndarray,
    source_face_indices: np.ndarray,
    source_corner_slots: np.ndarray,
    frame: _CutFrame,
    *,
    source_color: Color4 = _SOURCE_COLOR,
    cap_frames: dict[int, _CutFrame] | None = None,
    cap_material_id: int | None = None,
) -> MeshData:
    expanded_points = result.vertices[result.triangles.reshape(-1)]
    point_count = len(expanded_points)
    use_uvs = len(source.uv_coords) == len(source.face_vertex_indices)
    use_secondary_uvs = len(source.secondary_uv_coords) == len(source.face_vertex_indices)
    face_varying_colors = len(source.vertex_colors) == len(source.face_vertex_indices)
    point_colors = len(source.vertex_colors) == len(source.points)
    use_colors = face_varying_colors or point_colors
    point_normals = len(source.normals) == len(source.points)
    face_varying_normals = len(source.normals) == len(source.face_vertex_indices)
    skin_size = source.skel_element_size
    use_skinning = (
        skin_size > 0
        and len(source.skel_joint_indices) >= len(source.points) * skin_size
        and len(source.skel_joint_weights) >= len(source.points) * skin_size
    )
    material_by_face = {
        int(face_index): int(section.material_id)
        for section in source.sections
        for face_index in section.face_indices
    }
    default_material = 0 if source.sections else -1

    resolved_cap_frames = cap_frames or {2: frame}
    cap_tags = frozenset(resolved_cap_frames)
    scale = max(float(np.ptp(result.vertices, axis=0).max()), 1.0)
    position_tolerance = scale * 1e-6

    def position_key(point: np.ndarray) -> tuple[int, int, int]:
        return tuple(int(round(float(value) / position_tolerance)) for value in point)

    cap_keys_by_tag = {
        cap_tag: {
            position_key(result.vertices[int(index)])
            for index in np.unique(result.triangles[result.tags == cap_tag])
        }
        for cap_tag in cap_tags
    }
    uvs: list[Vector2 | None] = [None] * point_count
    secondary_uvs: list[Vector2 | None] = [None] * point_count
    colors: list[Color4 | None] = [None] * point_count
    normals: list[Vector3 | None] = [None] * point_count
    skinning: list[tuple[tuple[int, ...], tuple[float, ...]] | None] = [None] * point_count
    face_materials = [default_material] * len(result.triangles)
    boundary_attributes_by_tag: dict[
        int,
        dict[
            tuple[int, int, int],
            tuple[np.ndarray, Color4 | None, tuple[tuple[int, ...], tuple[float, ...]] | None, int],
        ],
    ] = {cap_tag: {} for cap_tag in cap_tags}

    for face_index, (triangle, tag, source_triangle_index) in enumerate(
        zip(result.triangles, result.tags, result.source_triangle_indices)
    ):
        if int(tag) != 0:
            continue
        source_triangle_index = int(source_triangle_index)
        if not 0 <= source_triangle_index < len(source_triangles):
            raise FractureError(f"Boolean prototype source face {face_index} has no source-triangle provenance.")
        source_point_indices = source_triangles[source_triangle_index]
        source_points = np.asarray(
            [
                (source.points[int(index)].x, source.points[int(index)].y, source.points[int(index)].z)
                for index in source_point_indices
            ],
            dtype=np.float64,
        )
        corner_slots = source_corner_slots[source_triangle_index]
        source_face = int(source_face_indices[source_triangle_index])
        material_id = material_by_face.get(source_face, default_material)
        face_materials[face_index] = material_id
        result_face_normal = _triangle_normal(result.vertices[triangle])
        for local_corner, result_vertex_index in enumerate(triangle):
            expanded_index = face_index * 3 + local_corner
            point = result.vertices[int(result_vertex_index)]
            barycentric = _barycentric_coordinates(point, source_points, source_triangle_index)
            if use_uvs:
                uvs[expanded_index] = _interpolate_vector2(
                    tuple(source.uv_coords[int(slot)] for slot in corner_slots),
                    barycentric,
                )
            if use_secondary_uvs:
                secondary_uvs[expanded_index] = _interpolate_vector2(
                    tuple(source.secondary_uv_coords[int(slot)] for slot in corner_slots),
                    barycentric,
                )
            if use_colors:
                source_colors = (
                    tuple(source.vertex_colors[int(slot)] for slot in corner_slots)
                    if face_varying_colors
                    else tuple(source.vertex_colors[int(index)] for index in source_point_indices)
                )
                colors[expanded_index] = _interpolate_color(source_colors, barycentric)
            if point_normals or face_varying_normals:
                source_normals = (
                    tuple(source.normals[int(slot)] for slot in corner_slots)
                    if face_varying_normals
                    else tuple(source.normals[int(index)] for index in source_point_indices)
                )
                normals[expanded_index] = _interpolate_normal(source_normals, barycentric)
            else:
                normals[expanded_index] = result_face_normal
            if use_skinning:
                skinning[expanded_index] = _interpolate_skinning(source, source_point_indices, barycentric)
            key = position_key(point)
            for cap_tag, cap_keys in cap_keys_by_tag.items():
                boundary_attributes = boundary_attributes_by_tag[cap_tag]
                if key in cap_keys and key not in boundary_attributes:
                    boundary_attributes[key] = (
                        point,
                        colors[expanded_index],
                        skinning[expanded_index],
                        material_id,
                    )

    for cap_tag, cap_frame in resolved_cap_frames.items():
        cap_faces = np.flatnonzero(result.tags == cap_tag)
        boundary_attributes = boundary_attributes_by_tag[cap_tag]
        if len(cap_faces) and (use_colors or use_skinning or source.sections) and not boundary_attributes:
            raise FractureError(f"Boolean prototype {name} cap {cap_tag} has no attributed boundary ring.")
        boundary_values = tuple(boundary_attributes.values())
        boundary_points = (
            np.asarray([value[0] for value in boundary_values], dtype=np.float64)
            if boundary_values
            else np.empty((0, 3), dtype=np.float64)
        )
        boundary_materials = [value[3] for value in boundary_values if value[3] >= 0]
        cap_material = (
            int(cap_material_id)
            if cap_material_id is not None
            else (_mode_int(boundary_materials) if boundary_materials else default_material)
        )
        for face_index in cap_faces:
            face_materials[int(face_index)] = cap_material
            for local_corner, result_vertex_index in enumerate(result.triangles[int(face_index)]):
                expanded_index = int(face_index) * 3 + local_corner
                point = result.vertices[int(result_vertex_index)]
                planar_uv = Vector2(
                    float((point - cap_frame.origin) @ cap_frame.tangent),
                    float((point - cap_frame.origin) @ cap_frame.bitangent),
                )
                if use_uvs:
                    uvs[expanded_index] = planar_uv
                if use_secondary_uvs:
                    secondary_uvs[expanded_index] = planar_uv
                if len(boundary_points):
                    boundary_index = int(np.argmin(np.sum((boundary_points - point) ** 2, axis=1)))
                    _boundary_point, boundary_color, boundary_skinning, _material = boundary_values[boundary_index]
                    if use_colors:
                        colors[expanded_index] = boundary_color
                    if use_skinning:
                        skinning[expanded_index] = boundary_skinning

    for expanded_index, normal in _cap_corner_normals(result, cap_tags).items():
        normals[expanded_index] = normal

    if use_uvs and any(value is None for value in uvs):
        raise FractureError(f"Boolean prototype {name} did not assign every primary UV.")
    if use_secondary_uvs and any(value is None for value in secondary_uvs):
        raise FractureError(f"Boolean prototype {name} did not assign every secondary UV.")
    if use_colors and any(value is None for value in colors):
        raise FractureError(f"Boolean prototype {name} did not assign every vertex color.")
    if use_skinning and any(value is None for value in skinning):
        raise FractureError(f"Boolean prototype {name} did not assign every skin weight.")
    if any(value is None for value in normals):
        raise FractureError(f"Boolean prototype {name} did not assign every normal.")

    sections_by_material: dict[int, list[int]] = {}
    for face_index, material_id in enumerate(face_materials):
        if material_id >= 0:
            sections_by_material.setdefault(material_id, []).append(face_index)
    joint_indices: list[int] = []
    joint_weights: list[float] = []
    if use_skinning:
        for value in skinning:
            assert value is not None
            joint_indices.extend(value[0])
            joint_weights.extend(value[1])
    return MeshData(
        name=name,
        points=tuple(Vector3(float(x), float(y), float(z)) for x, y, z in expanded_points),
        face_vertex_counts=(3,) * len(result.triangles),
        face_vertex_indices=tuple(range(point_count)),
        normals=tuple(value for value in normals if value is not None),
        uv_coords=tuple(value for value in uvs if value is not None),
        secondary_uv_coords=tuple(value for value in secondary_uvs if value is not None),
        vertex_colors=tuple(value for value in colors if value is not None) if use_colors else (),
        sections=tuple(
            MeshSection(material_id=material_id, face_indices=tuple(face_indices))
            for material_id, face_indices in sorted(sections_by_material.items())
        ),
        skel_joint_indices=tuple(joint_indices),
        skel_joint_weights=tuple(joint_weights),
        skel_element_size=skin_size if use_skinning else 0,
    )


def _barycentric_coordinates(point: np.ndarray, triangle: np.ndarray, source_triangle_index: int) -> np.ndarray:
    edge_0 = triangle[1] - triangle[0]
    edge_1 = triangle[2] - triangle[0]
    offset = point - triangle[0]
    dot_00 = float(edge_0 @ edge_0)
    dot_01 = float(edge_0 @ edge_1)
    dot_11 = float(edge_1 @ edge_1)
    dot_20 = float(offset @ edge_0)
    dot_21 = float(offset @ edge_1)
    denominator = dot_00 * dot_11 - dot_01 * dot_01
    if abs(denominator) <= _EPSILON * _EPSILON:
        raise FractureError(f"Boolean prototype source triangle {source_triangle_index} is degenerate.")
    second = (dot_11 * dot_20 - dot_01 * dot_21) / denominator
    third = (dot_00 * dot_21 - dot_01 * dot_20) / denominator
    weights = np.asarray((1.0 - second - third, second, third), dtype=np.float64)
    if float(np.min(weights)) < -1e-4 or float(np.max(weights)) > 1.0001:
        raise FractureError(
            f"Boolean prototype result point escaped source triangle {source_triangle_index}: {weights.tolist()}."
        )
    weights = np.clip(weights, 0.0, 1.0)
    return weights / float(np.sum(weights))


def _interpolate_vector2(values: tuple[Vector2, Vector2, Vector2], weights: np.ndarray) -> Vector2:
    return Vector2(
        sum(value.x * float(weight) for value, weight in zip(values, weights)),
        sum(value.y * float(weight) for value, weight in zip(values, weights)),
    )


def _interpolate_color(values: tuple[Color4, Color4, Color4], weights: np.ndarray) -> Color4:
    return Color4(
        sum(value.r * float(weight) for value, weight in zip(values, weights)),
        sum(value.g * float(weight) for value, weight in zip(values, weights)),
        sum(value.b * float(weight) for value, weight in zip(values, weights)),
        sum(value.a * float(weight) for value, weight in zip(values, weights)),
    )


def _interpolate_normal(values: tuple[Vector3, Vector3, Vector3], weights: np.ndarray) -> Vector3:
    vector = np.asarray(
        (
            sum(value.x * float(weight) for value, weight in zip(values, weights)),
            sum(value.y * float(weight) for value, weight in zip(values, weights)),
            sum(value.z * float(weight) for value, weight in zip(values, weights)),
        ),
        dtype=np.float64,
    )
    return _normal_vector3(vector)


def _triangle_normal(points: np.ndarray) -> Vector3:
    return _normal_vector3(np.cross(points[1] - points[0], points[2] - points[0]))


def _normal_vector3(vector: np.ndarray) -> Vector3:
    length = float(np.linalg.norm(vector))
    if length <= 1e-15:
        raise FractureError("Boolean fracture produced a zero-length normal.")
    x, y, z = vector / length
    return Vector3(float(x), float(y), float(z))


def _cap_corner_normals(result: _TaggedMesh, cap_tags: frozenset[int]) -> dict[int, Vector3]:
    cap_face_indices = np.flatnonzero(np.isin(result.tags, tuple(cap_tags)))
    if not len(cap_face_indices):
        return {}
    cap_triangles = result.triangles[cap_face_indices]
    points = result.vertices[cap_triangles]
    face_normals = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    lengths = np.linalg.norm(face_normals, axis=1)
    invalid = np.flatnonzero(lengths <= 1e-15)
    if len(invalid):
        raise FractureError(
            f"Boolean cap face {int(cap_face_indices[int(invalid[0])])} has a zero-length normal."
        )
    face_normals /= lengths[:, None]
    local_face_by_result_face = {
        int(result_face): local_face for local_face, result_face in enumerate(cap_face_indices)
    }
    corners_by_vertex: dict[int, list[tuple[int, int]]] = {}
    for face_index, triangle in zip(cap_face_indices, cap_triangles):
        for local_corner, vertex_index in enumerate(triangle):
            corners_by_vertex.setdefault(int(vertex_index), []).append((int(face_index), local_corner))

    resolved: dict[int, Vector3] = {}
    for corners in corners_by_vertex.values():
        incident = face_normals[
            np.asarray([local_face_by_result_face[face_index] for face_index, _corner in corners], dtype=np.int64)
        ]
        smoothed = (incident @ incident.T > 0.0).astype(np.float64) @ incident
        smoothed /= np.linalg.norm(smoothed, axis=1)[:, None]
        for (face_index, local_corner), normal in zip(corners, smoothed):
            resolved[face_index * 3 + local_corner] = Vector3(*(float(value) for value in normal))
    return resolved


def _interpolate_skinning(
    source: MeshData,
    source_point_indices: np.ndarray,
    barycentric: np.ndarray,
) -> tuple[tuple[int, ...], tuple[float, ...]]:
    influence_weights: dict[int, float] = {}
    for point_index, point_weight in zip(source_point_indices, barycentric):
        start = int(point_index) * source.skel_element_size
        for slot in range(source.skel_element_size):
            joint_index = int(source.skel_joint_indices[start + slot])
            weight = float(source.skel_joint_weights[start + slot]) * float(point_weight)
            influence_weights[joint_index] = influence_weights.get(joint_index, 0.0) + weight
    ranked = sorted(influence_weights.items(), key=lambda item: (-item[1], item[0]))[: source.skel_element_size]
    total = sum(weight for _joint, weight in ranked)
    if total <= 0.0:
        raise FractureError("Boolean prototype interpolated zero total skin weight.")
    indices = [joint for joint, _weight in ranked]
    weights = [weight / total for _joint, weight in ranked]
    while len(indices) < source.skel_element_size:
        indices.append(indices[0])
        weights.append(0.0)
    return tuple(indices), tuple(weights)


def _mode_int(values: list[int]) -> int:
    counts: dict[int, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return min(counts, key=lambda value: (-counts[value], value))


def _forward_noise_limit(
    model: CanonicalTreeModel,
    cut_site,
    frame: _CutFrame,
    max_bend_angle_degrees: float,
) -> _NoiseLimit:
    joints = {joint.name: joint for joint in model.skeleton}
    children: dict[str, list[Joint]] = {joint.name: [] for joint in model.skeleton}
    for joint in model.skeleton:
        if joint.parent in children:
            children[joint.parent].append(joint)
    for values in children.values():
        values.sort(key=lambda joint: joint.name)

    token = cut_site.child_joint_token or cut_site.joint_token
    current = joints.get(token)
    if current is None:
        raise FractureError(f"Boolean prototype cut {cut_site.joint_token} references missing child joint {token}.")
    while True:
        parent = joints.get(current.parent or "")
        start_value, end_value = source_bone_segment_positions(current, parent)
        start = _vector(start_value)
        end = _vector(end_value)
        direction = _unit(end - start, current.name)
        next_joints = children[current.name]
        distance = max(0.0, float((end - frame.origin) @ frame.normal))
        if not next_joints:
            return _NoiseLimit(distance, "terminal", current.name)
        if len(next_joints) > 1:
            return _NoiseLimit(distance, "branch", current.name)

        following = next_joints[0]
        following_start_value, following_end_value = source_bone_segment_positions(following, current)
        following_direction = _unit(
            _vector(following_end_value) - _vector(following_start_value),
            following.name,
        )
        angle = math.degrees(math.acos(float(np.clip(direction @ following_direction, -1.0, 1.0))))
        if angle > max_bend_angle_degrees:
            return _NoiseLimit(distance, "bend", following.name)
        current = following


def _cut_frame(model: CanonicalTreeModel, cut_site) -> _CutFrame:
    joints = {joint.name: joint for joint in model.skeleton}
    child_token = cut_site.child_joint_token or cut_site.joint_token
    child = joints.get(child_token)
    if child is None:
        raise FractureError(f"Boolean prototype cut {cut_site.joint_token} references missing child joint {child_token}.")
    parent = joints.get(cut_site.parent_joint_token or child.parent or "")
    if parent is None:
        raise FractureError(f"Boolean prototype cut {cut_site.joint_token} has no parent joint.")
    parent_point = _vector(parent.bind_translate)
    child_point = _vector(child.bind_translate)
    if cut_site.segment_t is not None:
        segment_start_value, segment_end_value = source_bone_segment_positions(child, parent)
        segment_start = _vector(segment_start_value)
        segment_end = _vector(segment_end_value)
        origin = segment_start + (segment_end - segment_start) * float(cut_site.segment_t)
        normal = _unit(segment_end - segment_start, cut_site.joint_token)
    else:
        bind_end = child.bind_end_translate
        if bind_end is not None and np.linalg.norm(_vector(bind_end) - child_point) > _EPSILON:
            end = _vector(bind_end)
            offset = 0.30 if cut_site.reason == "auto_branch_length" else 0.02
            origin = child_point + (end - child_point) * offset
            normal = _unit(end - child_point, cut_site.joint_token)
        else:
            origin = child_point
            normal = _unit(child_point - parent_point, cut_site.joint_token)
    tangent, bitangent = _basis(normal)
    return _CutFrame(origin, normal, tangent, bitangent)


def _vector(value: Vector3) -> np.ndarray:
    return np.asarray((value.x, value.y, value.z), dtype=np.float64)


def _unit(value: np.ndarray, label: str) -> np.ndarray:
    length = float(np.linalg.norm(value))
    if length <= _EPSILON:
        raise FractureError(f"Boolean prototype {label} has a zero-length direction.")
    return value / length


def _basis(normal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    helper = np.eye(3)[int(np.argmin(np.abs(normal)))]
    tangent = _unit(np.cross(normal, helper), "cut basis")
    return tangent, _unit(np.cross(normal, tangent), "cut basis")


def _newell_normal(points: np.ndarray) -> np.ndarray:
    normal = np.zeros(3, dtype=np.float64)
    for index, current in enumerate(points):
        following = points[(index + 1) % len(points)]
        normal += (
            (current[1] - following[1]) * (current[2] + following[2]),
            (current[2] - following[2]) * (current[0] + following[0]),
            (current[0] - following[0]) * (current[1] + following[1]),
        )
    return _unit(normal, "boundary loop")


def _signed_area(points: np.ndarray) -> float:
    return 0.5 * sum(
        points[index, 0] * points[(index + 1) % len(points), 1]
        - points[(index + 1) % len(points), 0] * points[index, 1]
        for index in range(len(points))
    )


def _source_seed(mesh: MeshData, cut_token: str) -> int:
    digest = hashlib.sha256()
    digest.update(cut_token.encode("utf-8"))
    for point in mesh.points:
        digest.update(np.asarray((point.x, point.y, point.z), dtype="<f8").tobytes())
    digest.update(np.asarray(mesh.face_vertex_indices, dtype="<u4").tobytes())
    return int.from_bytes(digest.digest()[:8], "little")


def _fractal_perlin(x: float, y: float, seed: int) -> float:
    total = 0.0
    amplitude = 1.0
    frequency = 1.0
    amplitude_sum = 0.0
    for octave in range(4):
        total += amplitude * _perlin(x * frequency, y * frequency, seed + octave * 0x9E3779B9)
        amplitude_sum += amplitude
        frequency *= 2.0
        amplitude *= 0.5
    return max(0.0, min(1.0, 0.5 + 0.5 * total / amplitude_sum))


def _perlin(x: float, y: float, seed: int) -> float:
    x0 = math.floor(x)
    y0 = math.floor(y)
    tx = x - x0
    ty = y - y0
    fade_x = tx * tx * tx * (tx * (tx * 6.0 - 15.0) + 10.0)
    fade_y = ty * ty * ty * (ty * (ty * 6.0 - 15.0) + 10.0)

    def gradient(ix: int, iy: int) -> tuple[float, float]:
        value = (seed ^ (ix * 0x9E3779B185EBCA87) ^ (iy * 0xC2B2AE3D27D4EB4F)) & 0xFFFFFFFFFFFFFFFF
        value ^= value >> 30
        value = (value * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        value ^= value >> 27
        angle = (value / 0xFFFFFFFFFFFFFFFF) * math.tau
        return math.cos(angle), math.sin(angle)

    def dot(ix: int, iy: int, dx: float, dy: float) -> float:
        gx, gy = gradient(ix, iy)
        return gx * dx + gy * dy

    n00 = dot(x0, y0, tx, ty)
    n10 = dot(x0 + 1, y0, tx - 1.0, ty)
    n01 = dot(x0, y0 + 1, tx, ty - 1.0)
    n11 = dot(x0 + 1, y0 + 1, tx - 1.0, ty - 1.0)
    nx0 = n00 + (n10 - n00) * fade_x
    nx1 = n01 + (n11 - n01) * fade_x
    return (nx0 + (nx1 - nx0) * fade_y) * math.sqrt(2.0)
