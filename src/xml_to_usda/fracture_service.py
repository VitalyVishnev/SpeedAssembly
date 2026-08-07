"""Fracture planning for destructible tree assemblies.

Layer: domain/application boundary.

This module plans stable static assembly pieces from an authored tree model.
It does not write USD and does not mutate the resolved model.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Callable

from .models import CanonicalTreeModel, Joint, RepeatedPartInstance, ValidationIssue, Vector3


FRACTURE_METHOD_MANUAL_FRACTURING = "manual_fracturing"
_LEGACY_METHODS = {
    "wind_guided_hierarchy",
    "pure_hierarchy",
    "branch_base_greedy",
    "manual_pinned_bones",
}
_MIN_MANUAL_SEGMENT_CUT_SEPARATION = 0.02
_MIN_AUTO_BRANCH_LENGTH = 0.05
DEFAULT_AUTO_BRANCH_CUT_OFFSET = 0.30
MIN_AUTO_BRANCH_CUT_OFFSET = 0.05
MAX_AUTO_BRANCH_CUT_OFFSET = 0.95


class FractureError(ValueError):
    """Raised when a fracture plan cannot be safely derived."""


@dataclass(frozen=True)
class FractureSettings:
    target_piece_count: int = 5
    output_stem: str = "Tree"
    pinned_cut_joint_tokens: tuple[str, ...] = ()
    generate_caps: bool = True
    preserve_trunk_bias: float = 0.5
    force_stump_piece: bool = False
    separate_stems: bool = False
    branch_height_bias: float = 0.0
    auto_branch_cut_offset: float = DEFAULT_AUTO_BRANCH_CUT_OFFSET
    detailed_cuts_enabled: bool = True
    detailed_cut_intensity: float = 20.0
    detailed_cut_scale: float = 0.65
    detailed_cut_density: int = 8
    detailed_cut_max_bend_angle: float = 30.0


@dataclass(frozen=True)
class FractureCutSite:
    joint_token: str
    kind: str
    reason: str
    parent_joint_token: str | None = None
    child_joint_token: str | None = None
    segment_t: float | None = None


@dataclass(frozen=True)
class FracturePiece:
    index: int
    name: str
    is_root_piece: bool
    cut_joint_token: str | None
    joint_tokens: tuple[str, ...]
    base_face_indices: tuple[int, ...]
    repeated_part_indices: tuple[int, ...]
    repeated_part_names: tuple[str, ...]


@dataclass(frozen=True)
class FracturePlan:
    method: str
    requested_piece_count: int
    actual_piece_count: int
    output_stem: str
    main_axis_joint_tokens: tuple[str, ...]
    selected_cut_sites: tuple[FractureCutSite, ...]
    rejected_cut_sites: tuple[FractureCutSite, ...]
    pieces: tuple[FracturePiece, ...]
    diagnostics: tuple[ValidationIssue, ...] = ()


@dataclass(frozen=True)
class _SkeletonGraph:
    joints: tuple[Joint, ...]
    joint_by_name: dict[str, Joint]
    index_by_name: dict[str, int]
    children_by_name: dict[str, tuple[str, ...]]
    roots: tuple[str, ...]
    depth_by_name: dict[str, int]
    preorder_by_name: dict[str, int]
    subtree_end_by_name: dict[str, int]


@dataclass(frozen=True)
class _FracturePlanCache:
    graph: _SkeletonGraph
    base_face_owner_by_index: tuple[str | None, ...]
    base_face_auto_children_by_index: tuple[frozenset[str], ...]
    subtree_base_face_counts: dict[str, int]
    main_axis: tuple[str, ...]
    stem_axes: tuple[tuple[str, ...], ...]
    subtree_max_path_lengths: dict[str, float]
    skeleton_min_y: float
    skeleton_max_y: float


def format_manual_segment_cut_token(parent_joint_token: str, child_joint_token: str, segment_t: float) -> str:
    parent = parent_joint_token.strip()
    child = child_joint_token.strip()
    if not parent or not child:
        raise FractureError("Manual segment cut requires non-empty parent and child joint tokens.")
    t = float(segment_t)
    if t <= 0.0 or t >= 1.0:
        raise FractureError(f"Manual segment cut position must be between 0 and 1, got {segment_t}.")
    return f"{parent}->{child}@{t:.3f}"


def source_bone_segment_positions(joint: Joint, parent: Joint | None) -> tuple[Vector3, Vector3]:
    """Return the physical source bone, not its hierarchy connector."""
    end = joint.bind_end_translate
    if end is not None:
        return joint.bind_translate, end
    if parent is not None:
        return parent.bind_translate, joint.bind_translate
    return joint.bind_translate, joint.bind_translate


def base_face_owner_tokens(model: CanonicalTreeModel) -> tuple[str | None, ...]:
    """Return the planner's dominant skeleton owner for each Base Mesh face."""
    _validate_fracture_source(model)
    owners, _auto_children = _base_face_bindings_by_index(model, _build_skeleton_graph(model.skeleton))
    return owners


def plan_fracture(
    model: CanonicalTreeModel,
    settings: FractureSettings | None = None,
    *,
    analysis_cache: _FracturePlanCache | None = None,
    excluded_cut_tokens: frozenset[str] = frozenset(),
    candidate_validator: Callable[[FractureCutSite], bool] | None = None,
) -> FracturePlan:
    resolved_settings = settings or FractureSettings()
    _validate_settings(resolved_settings)
    _validate_fracture_source(model)

    if analysis_cache is not None and analysis_cache.graph.joints != model.skeleton:
        analysis_cache = None
    if analysis_cache is None:
        analysis_cache = _build_fracture_plan_cache(model)

    graph = analysis_cache.graph
    base_face_owner_by_index = analysis_cache.base_face_owner_by_index
    base_face_auto_children_by_index = analysis_cache.base_face_auto_children_by_index
    subtree_base_face_counts = analysis_cache.subtree_base_face_counts
    main_axis = analysis_cache.main_axis
    stem_cut_sites, branch_cut_sites, candidate_diagnostics = _candidate_cut_sites(
        graph,
        subtree_base_face_counts,
        main_axis=main_axis,
        stem_axes=analysis_cache.stem_axes,
        subtree_max_path_lengths=analysis_cache.subtree_max_path_lengths,
        skeleton_min_y=analysis_cache.skeleton_min_y,
        skeleton_max_y=analysis_cache.skeleton_max_y,
        separate_stems=resolved_settings.separate_stems,
        branch_height_bias=resolved_settings.branch_height_bias,
        auto_branch_cut_offset=resolved_settings.auto_branch_cut_offset,
    )

    selected: list[FractureCutSite] = _manual_cut_sites(resolved_settings, graph, subtree_base_face_counts)
    rejected: list[FractureCutSite] = []
    stump_cut_sites = (
        _stump_cut_sites(
            graph,
            subtree_base_face_counts,
            stem_axes=analysis_cache.stem_axes,
        )
        if resolved_settings.force_stump_piece
        else ()
    )
    face_centroids = (
        _base_face_centroids(model)
        if any(
            cut_site.segment_t is not None
            for cut_site in (
                *selected,
                *stump_cut_sites,
                *stem_cut_sites,
                *(branch_cut_sites if resolved_settings.target_piece_count else ()),
            )
        )
        else ()
    )
    pieces = _build_pieces(
        model,
        graph,
        base_face_owner_by_index,
        base_face_auto_children_by_index,
        _ordered_cut_sites_for_settings(selected, graph),
        output_stem=resolved_settings.output_stem,
        face_centroids=face_centroids,
    )
    _raise_for_empty_manual_cut_pieces(selected, pieces)

    if resolved_settings.force_stump_piece:
        for stump_cut in stump_cut_sites:
            if stump_cut.joint_token in excluded_cut_tokens:
                rejected.append(stump_cut)
                continue
            if any(_cut_site_anchor(cut) == _cut_site_anchor(stump_cut) for cut in selected):
                continue
            if candidate_validator is not None and not candidate_validator(stump_cut):
                rejected.append(stump_cut)
                continue
            trial_selected = _ordered_cut_sites_for_settings(selected + [stump_cut], graph)
            trial_pieces = _build_pieces(
                model,
                graph,
                base_face_owner_by_index,
                base_face_auto_children_by_index,
                trial_selected,
                output_stem=resolved_settings.output_stem,
                face_centroids=face_centroids,
            )
            if len(trial_pieces) == len(selected) + 2 and all(piece.base_face_indices for piece in trial_pieces):
                selected = trial_selected
                pieces = trial_pieces
            else:
                rejected.append(stump_cut)

    for cut_site in stem_cut_sites:
        if cut_site.joint_token in excluded_cut_tokens:
            rejected.append(cut_site)
            continue
        if any(_cut_site_anchor(existing) == _cut_site_anchor(cut_site) for existing in selected):
            continue
        if candidate_validator is not None and not candidate_validator(cut_site):
            rejected.append(cut_site)
            continue
        trial_selected = _ordered_cut_sites_for_settings(selected + [cut_site], graph)
        trial_pieces = _build_pieces(
            model,
            graph,
            base_face_owner_by_index,
            base_face_auto_children_by_index,
            trial_selected,
            output_stem=resolved_settings.output_stem,
            face_centroids=face_centroids,
        )
        if (
            len(trial_pieces) == len(selected) + 2
            and all(piece.base_face_indices for piece in trial_pieces)
        ):
            selected = trial_selected
            pieces = trial_pieces
        else:
            rejected.append(cut_site)

    automatic_branch_count = 0
    for cut_site in branch_cut_sites:
        if cut_site.joint_token in excluded_cut_tokens:
            rejected.append(cut_site)
            continue
        if any(_cut_site_anchor(existing) == _cut_site_anchor(cut_site) for existing in selected):
            continue
        if automatic_branch_count >= resolved_settings.target_piece_count:
            break
        if candidate_validator is not None and not candidate_validator(cut_site):
            rejected.append(cut_site)
            continue
        trial_selected = _ordered_cut_sites_for_settings(selected + [cut_site], graph)
        trial_pieces = _build_pieces(
            model,
            graph,
            base_face_owner_by_index,
            base_face_auto_children_by_index,
            trial_selected,
            output_stem=resolved_settings.output_stem,
            face_centroids=face_centroids,
        )
        if (
            len(trial_pieces) == len(selected) + 2
            and all(piece.base_face_indices for piece in trial_pieces)
        ):
            selected = trial_selected
            pieces = trial_pieces
            automatic_branch_count += 1
        else:
            rejected.append(cut_site)

    diagnostics = candidate_diagnostics + _manual_piece_count_diagnostics(resolved_settings, pieces)
    selected_stump_count = sum(cut.reason == "stump_piece" for cut in selected)
    if selected_stump_count < len(stump_cut_sites):
        diagnostics += (
            ValidationIssue(
                severity="warning",
                code="fracture_stump_count_clamped",
                message=(
                    "Fracture stump count was clamped because a requested stem cut did not satisfy geometry, "
                    "topology, cap, or Repeated Part ownership invariants: "
                    f"requested {len(stump_cut_sites)}, actual {selected_stump_count}."
                ),
            ),
        )
    selected_stem_count = sum(cut.reason == "auto_stem_length" for cut in selected)
    if selected_stem_count < len(stem_cut_sites):
        diagnostics += (
            ValidationIssue(
                severity="warning",
                code="fracture_stem_count_clamped",
                message=(
                    "Fracture stem separation was clamped because a requested stem cut did not satisfy geometry, "
                    "topology, cap, or Repeated Part ownership invariants: "
                    f"requested {len(stem_cut_sites)}, actual {selected_stem_count}."
                ),
            ),
        )
    if automatic_branch_count < resolved_settings.target_piece_count:
        diagnostics += (
            ValidationIssue(
                severity="warning",
                code="fracture_branch_count_clamped",
                message=(
                    "Fracture branch count was clamped because no remaining branch cut "
                    "satisfied geometry, topology, and Repeated Part ownership invariants: "
                    f"requested {resolved_settings.target_piece_count}, actual {automatic_branch_count}."
                ),
            ),
        )

    return FracturePlan(
        method=FRACTURE_METHOD_MANUAL_FRACTURING,
        requested_piece_count=resolved_settings.target_piece_count,
        actual_piece_count=len(pieces),
        output_stem=resolved_settings.output_stem,
        main_axis_joint_tokens=main_axis,
        selected_cut_sites=tuple(selected),
        rejected_cut_sites=tuple(rejected),
        pieces=pieces,
        diagnostics=diagnostics,
    )


def _build_fracture_plan_cache(model: CanonicalTreeModel) -> _FracturePlanCache:
    graph = _build_skeleton_graph(model.skeleton)
    base_face_owner_by_index, base_face_auto_children_by_index = _base_face_bindings_by_index(model, graph)
    subtree_base_face_counts = _subtree_base_face_counts(graph, base_face_owner_by_index)
    main_axis = _select_main_axis(graph)
    ys = tuple(joint.rest_translate.y for joint in graph.joints)
    return _FracturePlanCache(
        graph=graph,
        base_face_owner_by_index=base_face_owner_by_index,
        base_face_auto_children_by_index=base_face_auto_children_by_index,
        subtree_base_face_counts=subtree_base_face_counts,
        main_axis=main_axis,
        stem_axes=_select_stem_axes(graph, subtree_base_face_counts),
        subtree_max_path_lengths=_subtree_max_path_lengths(graph),
        skeleton_min_y=min(ys) if ys else 0.0,
        skeleton_max_y=max(ys) if ys else 0.0,
    )


def _manual_piece_count_diagnostics(
    settings: FractureSettings,
    pieces: tuple[FracturePiece, ...],
) -> tuple[ValidationIssue, ...]:
    return ()


def _validate_settings(settings: FractureSettings) -> None:
    legacy_method = getattr(settings, "method", None)
    if legacy_method is not None:
        if legacy_method in _LEGACY_METHODS:
            raise FractureError(f"Legacy fracture method is no longer supported: {legacy_method}")
        raise FractureError(f"Unsupported fracture method: {legacy_method}")
    legacy_auto_fill = getattr(settings, "manual_auto_fill_method", None)
    if legacy_auto_fill is not None:
        raise FractureError("Legacy manual fracture auto-fill methods are no longer supported.")
    if not isinstance(settings.target_piece_count, int):
        raise FractureError(
            "Fracture branch count must be an integer, "
            f"got {type(settings.target_piece_count).__name__}."
        )
    if settings.target_piece_count < 0:
        raise FractureError("Fracture branch count must be zero or greater.")
    if not isinstance(settings.output_stem, str):
        raise FractureError(f"Fracture output stem must be a string, got {type(settings.output_stem).__name__}.")
    if not settings.output_stem.strip():
        raise FractureError("Fracture output stem must not be empty.")
    if isinstance(settings.pinned_cut_joint_tokens, str) or not isinstance(settings.pinned_cut_joint_tokens, tuple):
        raise FractureError(
            "Manual fracture pinned cut joint tokens must be a tuple of strings, "
            f"got {type(settings.pinned_cut_joint_tokens).__name__}."
        )
    for token in settings.pinned_cut_joint_tokens:
        if not isinstance(token, str):
            raise FractureError(
                "Manual fracture pinned cut joint tokens must be strings, "
                f"got {type(token).__name__}."
            )
    if not isinstance(settings.generate_caps, bool):
        raise FractureError(f"Fracture generate_caps must be a bool, got {type(settings.generate_caps).__name__}.")
    if not isinstance(settings.detailed_cuts_enabled, bool):
        raise FractureError(
            "Fracture detailed_cuts_enabled must be a bool, "
            f"got {type(settings.detailed_cuts_enabled).__name__}."
        )
    if not 0.0 <= float(settings.detailed_cut_intensity) <= 100.0:
        raise FractureError("Fracture detailed cut intensity must be between 0 and 100.")
    if not 0.1 <= float(settings.detailed_cut_scale) <= 2.0:
        raise FractureError("Fracture detailed cut scale must be between 0.1 and 2.")
    if not isinstance(settings.detailed_cut_density, int) or not 4 <= settings.detailed_cut_density <= 64:
        raise FractureError("Fracture detailed cut density must be an integer from 4 to 64.")
    if not 0.0 < float(settings.detailed_cut_max_bend_angle) <= 180.0:
        raise FractureError("Fracture detailed cut bend limit must be greater than 0 and at most 180 degrees.")
    if not 0.0 <= float(settings.preserve_trunk_bias) <= 1.0:
        raise FractureError("Fracture preserve_trunk_bias must be between 0 and 1.")
    if not isinstance(settings.force_stump_piece, bool):
        raise FractureError(
            f"Fracture force_stump_piece must be a bool, got {type(settings.force_stump_piece).__name__}."
        )
    if not isinstance(settings.separate_stems, bool):
        raise FractureError(f"Fracture separate_stems must be a bool, got {type(settings.separate_stems).__name__}.")
    if not -1.0 <= float(settings.branch_height_bias) <= 1.0:
        raise FractureError("Fracture branch_height_bias must be between -1 and 1.")
    if not MIN_AUTO_BRANCH_CUT_OFFSET <= float(settings.auto_branch_cut_offset) <= MAX_AUTO_BRANCH_CUT_OFFSET:
        raise FractureError(
            "Fracture automatic branch cut offset must be between "
            f"{MIN_AUTO_BRANCH_CUT_OFFSET:.2f} and {MAX_AUTO_BRANCH_CUT_OFFSET:.2f}."
        )


def _manual_cut_sites(
    settings: FractureSettings,
    graph: _SkeletonGraph,
    subtree_base_face_counts: dict[str, int],
) -> list[FractureCutSite]:
    cut_sites: list[FractureCutSite] = []
    seen: set[str] = set()
    segment_t_by_edge: dict[tuple[str, str], list[float]] = {}
    for token in settings.pinned_cut_joint_tokens:
        cut_site = _manual_cut_site_from_token(token, graph)
        if cut_site.kind == "manual_segment":
            _raise_for_closely_spaced_manual_segment_cut(cut_site, segment_t_by_edge)
        if cut_site.joint_token in seen:
            continue
        seen.add(cut_site.joint_token)
        if cut_site.kind == "joint":
            if cut_site.joint_token in graph.roots:
                raise FractureError(f"Manual fracture cut site {cut_site.joint_token} cannot be a skeleton root.")
            if subtree_base_face_counts.get(cut_site.joint_token, 0) <= 0:
                raise FractureError(
                    f"Manual fracture cut site {cut_site.joint_token} cannot produce a Fracture Piece with base mesh faces."
                )
        cut_sites.append(cut_site)
    return sorted(cut_sites, key=lambda cut_site: _cut_site_sort_key(cut_site, graph))


def _raise_for_closely_spaced_manual_segment_cut(
    cut_site: FractureCutSite,
    segment_t_by_edge: dict[tuple[str, str], list[float]],
) -> None:
    parent = cut_site.parent_joint_token
    child = cut_site.child_joint_token
    segment_t = cut_site.segment_t
    if parent is None or child is None or segment_t is None:
        raise FractureError(f"Manual fracture segment cut token is incomplete: {cut_site.joint_token}.")
    edge = (parent, child)
    for existing_t in segment_t_by_edge.setdefault(edge, []):
        if abs(segment_t - existing_t) < _MIN_MANUAL_SEGMENT_CUT_SEPARATION:
            raise FractureError(
                "Manual fracture segment cuts on the same skeleton edge must be at least "
                f"{_MIN_MANUAL_SEGMENT_CUT_SEPARATION:.2f} apart: {cut_site.joint_token} is too close to "
                f"{format_manual_segment_cut_token(parent, child, existing_t)}."
            )
    segment_t_by_edge[edge].append(segment_t)


def _manual_cut_site_from_token(token: str, graph: _SkeletonGraph) -> FractureCutSite:
    if "->" not in token and "@" not in token:
        if token not in graph.joint_by_name:
            raise FractureError(f"Manual fracture cut site references missing skeleton joint {token}.")
        return FractureCutSite(joint_token=token, kind="joint", reason="manual_pinned")
    try:
        edge, raw_t = token.rsplit("@", 1)
        parent, child = edge.split("->", 1)
        normalized = format_manual_segment_cut_token(parent, child, float(raw_t))
    except ValueError as exc:
        raise FractureError(f"Manual fracture segment cut token is invalid: {token}") from exc
    parent = parent.strip()
    child = child.strip()
    if parent not in graph.joint_by_name:
        raise FractureError(f"Manual fracture segment cut references missing parent joint {parent}.")
    if child not in graph.joint_by_name:
        raise FractureError(f"Manual fracture segment cut references missing child joint {child}.")
    if graph.joint_by_name[child].parent != parent:
        raise FractureError(f"Manual fracture segment cut {normalized} is not a parent-child skeleton edge.")
    return FractureCutSite(
        joint_token=normalized,
        kind="manual_segment",
        reason="manual_pinned_segment",
        parent_joint_token=parent,
        child_joint_token=child,
        segment_t=float(raw_t),
    )


def _ordered_cut_sites_for_settings(
    cut_sites: list[FractureCutSite],
    graph: _SkeletonGraph,
) -> list[FractureCutSite]:
    return sorted(cut_sites, key=lambda cut_site: _cut_site_sort_key(cut_site, graph))


def _cut_site_sort_key(cut_site: FractureCutSite, graph: _SkeletonGraph) -> tuple[int, float, str]:
    anchor = _cut_site_anchor(cut_site)
    return (graph.index_by_name.get(anchor, len(graph.joints)), cut_site.segment_t or -1.0, cut_site.joint_token)


def _cut_site_anchor(cut_site: FractureCutSite) -> str:
    return cut_site.child_joint_token or cut_site.joint_token


def _validate_fracture_source(model: CanonicalTreeModel) -> None:
    if model.base_mesh is None:
        raise FractureError("Fracture planning requires a base mesh.")
    _validate_materialized_base_mesh_topology(model.base_mesh)
    if not model.skeleton:
        raise FractureError("Fracture planning requires a skeleton hierarchy.")
    if model.base_mesh.skel_element_size <= 0 or not model.base_mesh.skel_joint_indices:
        raise FractureError("Fracture planning requires base mesh skinning indices.")


def _validate_materialized_base_mesh_topology(mesh) -> None:
    for field_name in ("points", "face_vertex_counts", "face_vertex_indices"):
        value = getattr(mesh, field_name, None)
        if not isinstance(value, tuple):
            raise FractureError(
                f"Base mesh {field_name} must be a materialized tuple for fracture planning, "
                f"got {type(value).__name__}."
            )


def _build_skeleton_graph(skeleton: tuple[Joint, ...]) -> _SkeletonGraph:
    joint_by_name: dict[str, Joint] = {}
    index_by_name: dict[str, int] = {}
    for index, joint in enumerate(skeleton):
        if joint.name in joint_by_name:
            raise FractureError(f"Duplicate skeleton joint token in fracture source: {joint.name}")
        joint_by_name[joint.name] = joint
        index_by_name[joint.name] = index

    children: dict[str, list[str]] = {joint.name: [] for joint in skeleton}
    roots: list[str] = []
    for joint in skeleton:
        if joint.parent is None:
            roots.append(joint.name)
            continue
        if joint.parent not in joint_by_name:
            raise FractureError(f"Skeleton joint {joint.name} references missing parent {joint.parent}.")
        children[joint.parent].append(joint.name)

    children_by_name = {name: tuple(sorted(child_names)) for name, child_names in children.items()}
    depth_by_name: dict[str, int] = {}

    def resolve_depth(name: str, visiting: frozenset[str] = frozenset()) -> int:
        if name in depth_by_name:
            return depth_by_name[name]
        if name in visiting:
            raise FractureError(f"Skeleton hierarchy contains a cycle at joint {name}.")
        parent = joint_by_name[name].parent
        depth = 0 if parent is None else resolve_depth(parent, visiting | {name}) + 1
        depth_by_name[name] = depth
        return depth

    for joint in skeleton:
        resolve_depth(joint.name)

    if not roots:
        raise FractureError("Skeleton hierarchy has no root joint.")

    preorder_by_name: dict[str, int] = {}
    subtree_end_by_name: dict[str, int] = {}

    def index_subtree(name: str) -> None:
        preorder_by_name[name] = len(preorder_by_name)
        for child_name in children_by_name[name]:
            index_subtree(child_name)
        subtree_end_by_name[name] = len(preorder_by_name)

    sorted_roots = tuple(sorted(roots))
    for root in sorted_roots:
        index_subtree(root)

    return _SkeletonGraph(
        joints=skeleton,
        joint_by_name=joint_by_name,
        index_by_name=index_by_name,
        children_by_name=children_by_name,
        roots=sorted_roots,
        depth_by_name=depth_by_name,
        preorder_by_name=preorder_by_name,
        subtree_end_by_name=subtree_end_by_name,
    )


def _select_main_axis(graph: _SkeletonGraph) -> tuple[str, ...]:
    paths = _root_to_leaf_paths(graph)
    if not paths:
        return graph.roots[:1]
    return max(paths, key=lambda path: (_path_length(graph, path), len(path), tuple(reversed(path))))


def _select_stem_axes(
    graph: _SkeletonGraph,
    subtree_base_face_counts: dict[str, int],
) -> tuple[tuple[str, ...], ...]:
    roots_with_faces = tuple(root for root in graph.roots if subtree_base_face_counts.get(root, 0) > 0)
    if len(roots_with_faces) > 1:
        return tuple(_select_axis_from(graph, root) for root in roots_with_faces)
    if len(roots_with_faces) == 1:
        root = roots_with_faces[0]
        root_level = graph.joint_by_name[root].generator_level
        stem_children = tuple(
            child
            for child in graph.children_by_name[root]
            if subtree_base_face_counts.get(child, 0) > 0
            and graph.joint_by_name[child].generator_level == root_level
        )
        if len(stem_children) > 1:
            return tuple(_select_axis_from(graph, child) for child in stem_children)
        return (_select_axis_from(graph, root),)
    return ()


def _select_axis_from(graph: _SkeletonGraph, root_token: str) -> tuple[str, ...]:
    paths = _root_to_leaf_paths_from(graph, root_token)
    if not paths:
        return (root_token,)
    return max(paths, key=lambda path: (_path_length(graph, path), len(path), tuple(reversed(path))))


def _candidate_cut_sites(
    graph: _SkeletonGraph,
    subtree_base_face_counts: dict[str, int],
    *,
    main_axis: tuple[str, ...],
    stem_axes: tuple[tuple[str, ...], ...],
    subtree_max_path_lengths: dict[str, float],
    skeleton_min_y: float,
    skeleton_max_y: float,
    separate_stems: bool,
    branch_height_bias: float,
    auto_branch_cut_offset: float,
) -> tuple[tuple[FractureCutSite, ...], tuple[FractureCutSite, ...], tuple[ValidationIssue, ...]]:
    stem_cut_sites = _stem_cut_sites(
        graph,
        subtree_base_face_counts,
        stem_axes,
        enabled=separate_stems,
    )
    branch_cut_sites = _length_ranked_branch_base_candidates(
        graph,
        subtree_base_face_counts,
        stem_axes,
        subtree_max_path_lengths,
        skeleton_min_y=skeleton_min_y,
        skeleton_max_y=skeleton_max_y,
        branch_height_bias=branch_height_bias,
        auto_branch_cut_offset=auto_branch_cut_offset,
    )
    return stem_cut_sites, branch_cut_sites, ()


def _stem_cut_sites(
    graph: _SkeletonGraph,
    subtree_base_face_counts: dict[str, int],
    stem_axes: tuple[tuple[str, ...], ...],
    *,
    enabled: bool,
) -> tuple[FractureCutSite, ...]:
    if not enabled:
        return ()
    stems = tuple(axis[0] for axis in stem_axes if axis and subtree_base_face_counts.get(axis[0], 0) > 0)
    if len(stems) <= 1:
        return ()
    primary_stem = max(
        stems,
        key=lambda token: (_path_length(graph, _select_axis_from(graph, token)), subtree_base_face_counts[token], token),
    )
    return tuple(
        FractureCutSite(joint_token=token, kind="joint", reason="auto_stem_length")
        for token in sorted(
            (token for token in stems if token != primary_stem),
            key=lambda token: (-_path_length(graph, _select_axis_from(graph, token)), token),
        )
    )


def _length_ranked_branch_base_candidates(
    graph: _SkeletonGraph,
    subtree_base_face_counts: dict[str, int],
    stem_axes: tuple[tuple[str, ...], ...],
    subtree_max_path_lengths: dict[str, float],
    *,
    skeleton_min_y: float,
    skeleton_max_y: float,
    branch_height_bias: float,
    auto_branch_cut_offset: float,
) -> tuple[FractureCutSite, ...]:
    stem_axis_tokens = {token for axis in stem_axes for token in axis}
    candidates = [
        token
        for token in graph.joint_by_name
        if token not in graph.roots
        and token not in stem_axis_tokens
        and subtree_base_face_counts.get(token, 0) > 0
        and _branch_physical_length(graph, token, subtree_max_path_lengths) >= _MIN_AUTO_BRANCH_LENGTH
        and _is_branch_base_candidate(graph, token, stem_axis_tokens)
    ]
    candidates.sort(
        key=lambda token: (
            -_branch_priority_score(
                graph,
                token,
                subtree_max_path_lengths,
                skeleton_min_y=skeleton_min_y,
                skeleton_max_y=skeleton_max_y,
                branch_height_bias=branch_height_bias,
            ),
            token,
        )
    )
    return tuple(
        FractureCutSite(
            joint_token=token,
            kind="auto_segment",
            reason="auto_branch_length",
            parent_joint_token=graph.joint_by_name[token].parent,
            child_joint_token=token,
            segment_t=auto_branch_cut_offset,
        )
        for token in candidates
    )


def _is_branch_base_candidate(graph: _SkeletonGraph, token: str, stem_axis_tokens: set[str]) -> bool:
    parent = graph.joint_by_name[token].parent
    if parent is None:
        return False
    if parent in stem_axis_tokens:
        return True
    parent_level = graph.joint_by_name[parent].generator_level
    token_level = graph.joint_by_name[token].generator_level
    return parent_level is not None and token_level is not None and token_level > parent_level


def _branch_priority_score(
    graph: _SkeletonGraph,
    token: str,
    subtree_max_path_lengths: dict[str, float],
    *,
    skeleton_min_y: float,
    skeleton_max_y: float,
    branch_height_bias: float,
) -> float:
    length = _branch_physical_length(graph, token, subtree_max_path_lengths)
    height_factor = _height_bias_factor(
        graph.joint_by_name[token].rest_translate.y,
        skeleton_min_y=skeleton_min_y,
        skeleton_max_y=skeleton_max_y,
        branch_height_bias=branch_height_bias,
    )
    return length * height_factor


def _branch_physical_length(
    graph: _SkeletonGraph,
    token: str,
    subtree_max_path_lengths: dict[str, float],
) -> float:
    parent = graph.joint_by_name[token].parent
    base_edge = _edge_length(graph, parent, token) if parent is not None else 0.0
    return base_edge + subtree_max_path_lengths.get(token, 0.0)


def _height_bias_factor(
    y: float,
    *,
    skeleton_min_y: float,
    skeleton_max_y: float,
    branch_height_bias: float,
) -> float:
    bias = max(-1.0, min(1.0, float(branch_height_bias)))
    if abs(bias) <= 0.0001:
        return 1.0
    span = skeleton_max_y - skeleton_min_y
    normalized = 0.5 if span <= 0.0 else max(0.0, min(1.0, (float(y) - skeleton_min_y) / span))
    direction = normalized if bias > 0.0 else 1.0 - normalized
    return 1.0 + abs(bias) * direction


def _stump_cut_sites(
    graph: _SkeletonGraph,
    subtree_base_face_counts: dict[str, int],
    *,
    stem_axes: tuple[tuple[str, ...], ...],
) -> tuple[FractureCutSite, ...]:
    cut_sites: list[FractureCutSite] = []
    multi_stem = len(stem_axes) > 1
    for axis in stem_axes:
        if len(axis) < 2:
            continue
        root_token, child_token = axis[:2]
        child = graph.joint_by_name[child_token]
        if child.parent != root_token:
            continue
        total_faces = subtree_base_face_counts.get(root_token, 0)
        child_faces = subtree_base_face_counts.get(child_token, 0)
        if child_faces <= 0:
            continue
        if multi_stem:
            segment_t = 0.95
            cut_sites.append(
                FractureCutSite(
                    joint_token=format_manual_segment_cut_token(root_token, child_token, segment_t),
                    kind="manual_segment",
                    reason="stump_piece",
                    parent_joint_token=root_token,
                    child_joint_token=child_token,
                    segment_t=segment_t,
                )
            )
            continue
        if total_faces - child_faces <= 0:
            continue
        cut_sites.append(
            FractureCutSite(
                joint_token=child_token,
                kind="joint",
                reason="stump_piece",
                parent_joint_token=root_token,
                child_joint_token=child_token,
            )
        )
    return tuple(cut_sites)


def _build_pieces(
    model: CanonicalTreeModel,
    graph: _SkeletonGraph,
    base_face_owner_by_index: tuple[str | None, ...],
    base_face_auto_children_by_index: tuple[frozenset[str], ...],
    selected_cut_sites: list[FractureCutSite],
    *,
    output_stem: str,
    face_centroids: tuple[Vector3 | None, ...],
) -> tuple[FracturePiece, ...]:
    selected_tokens = tuple(cut_site.joint_token for cut_site in selected_cut_sites)
    owner_by_joint = _selected_cut_owner_by_joint(graph, selected_cut_sites)
    joint_tokens_by_owner: dict[str | None, list[str]] = {None: []}
    face_indices_by_owner: dict[str | None, list[int]] = {None: []}
    repeated_indices_by_owner: dict[str | None, list[int]] = {None: []}
    repeated_names_by_owner: dict[str | None, list[str]] = {None: []}

    for token in selected_tokens:
        joint_tokens_by_owner[token] = []
        face_indices_by_owner[token] = []
        repeated_indices_by_owner[token] = []
        repeated_names_by_owner[token] = []

    for joint in graph.joints:
        joint_tokens_by_owner[owner_by_joint[joint.name]].append(joint.name)

    segment_cut_sites = [cut_site for cut_site in selected_cut_sites if cut_site.segment_t is not None]
    segment_cut_by_token = {cut_site.joint_token: cut_site for cut_site in segment_cut_sites}
    segment_projection_by_token = {
        cut_site.joint_token: _segment_projection_data(
            *source_bone_segment_positions(
                graph.joint_by_name[cut_site.child_joint_token],
                graph.joint_by_name[cut_site.parent_joint_token],
            )
        )
        for cut_site in segment_cut_sites
        if cut_site.child_joint_token is not None and cut_site.parent_joint_token is not None
    }
    segment_cuts_by_face_binding: dict[tuple[str, frozenset[str]], tuple[FractureCutSite, ...]] = {}
    owner_depth_by_token = {
        owner: _owner_anchor_depth(graph, owner, selected_cut_sites)
        for owner in (None, *selected_tokens)
    }
    for face_index, joint_token in enumerate(base_face_owner_by_index):
        if joint_token is None:
            continue
        owner = owner_by_joint[joint_token]
        segment_owner = None
        if segment_cut_sites:
            face_centroid = face_centroids[face_index]
            if face_centroid is None:
                continue
            owner = _segment_parent_side_owner(
                face_centroid,
                owner,
                segment_cut_by_token,
                segment_projection_by_token,
                owner_by_joint,
            )
            auto_children = base_face_auto_children_by_index[face_index]
            binding_key = (joint_token, auto_children)
            if binding_key not in segment_cuts_by_face_binding:
                segment_cuts_by_face_binding[binding_key] = tuple(
                    cut_site
                    for cut_site in segment_cut_sites
                    if cut_site.child_joint_token is not None
                    and (
                        _is_ancestor_or_self(graph, cut_site.child_joint_token, joint_token)
                        or (
                            cut_site.parent_joint_token == joint_token
                            and (
                                cut_site.reason != "auto_branch_length"
                                or cut_site.child_joint_token in auto_children
                            )
                        )
                    )
                )
            segment_owner = _spatial_segment_cut_owner(
                graph,
                face_centroid,
                owner_depth_by_token[owner],
                segment_cuts_by_face_binding[binding_key],
                segment_projection_by_token,
            )
        face_indices_by_owner[segment_owner or owner].append(face_index)

    for part_index, part in enumerate(model.repeated_parts):
        joint_token = _repeated_part_joint_token(part, graph)
        owner = owner_by_joint[joint_token]
        while owner is not None:
            parent_side_owner = _segment_parent_side_owner(
                part.position,
                owner,
                segment_cut_by_token,
                segment_projection_by_token,
                owner_by_joint,
            )
            if parent_side_owner == owner:
                break
            owner = parent_side_owner
        repeated_indices_by_owner[owner].append(part_index)
        repeated_names_by_owner[owner].append(part.name)

    pieces: list[FracturePiece] = [
        FracturePiece(
            index=0,
            name=f"{output_stem}_fracture_00",
            is_root_piece=True,
            cut_joint_token=None,
            joint_tokens=tuple(joint_tokens_by_owner[None]),
            base_face_indices=tuple(face_indices_by_owner[None]),
            repeated_part_indices=tuple(repeated_indices_by_owner[None]),
            repeated_part_names=tuple(repeated_names_by_owner[None]),
        )
    ]
    for index, cut_site in enumerate(selected_cut_sites, start=1):
        pieces.append(
            FracturePiece(
                index=index,
                name=f"{output_stem}_fracture_{index:02d}",
                is_root_piece=False,
                cut_joint_token=cut_site.joint_token,
                joint_tokens=tuple(joint_tokens_by_owner[cut_site.joint_token]),
                base_face_indices=tuple(face_indices_by_owner[cut_site.joint_token]),
                repeated_part_indices=tuple(repeated_indices_by_owner[cut_site.joint_token]),
                repeated_part_names=tuple(repeated_names_by_owner[cut_site.joint_token]),
            )
        )
    return tuple(pieces)


def _segment_parent_side_owner(
    position: Vector3,
    current_owner: str | None,
    segment_cut_by_token: dict[str, FractureCutSite],
    segment_projection_by_token: dict[str, tuple[float, float, float, float, float, float, float]],
    owner_by_joint: dict[str, str | None],
) -> str | None:
    cut_site = segment_cut_by_token.get(current_owner or "")
    if cut_site is None:
        return current_owner
    parent = cut_site.parent_joint_token
    child = cut_site.child_joint_token
    segment_t = cut_site.segment_t
    if parent is None or child is None or segment_t is None:
        return current_owner
    projected_t = _project_point_with_data(position, segment_projection_by_token[cut_site.joint_token])
    if projected_t < segment_t:
        return owner_by_joint[parent]
    return current_owner


def _selected_cut_owner_by_joint(
    graph: _SkeletonGraph,
    selected_cut_sites: list[FractureCutSite],
) -> dict[str, str | None]:
    owner_by_anchor: dict[str, str] = {}
    for cut_site in selected_cut_sites:
        anchor = cut_site.child_joint_token or cut_site.joint_token
        owner_by_anchor.setdefault(anchor, cut_site.joint_token)
    owner_by_joint: dict[str, str | None] = {}
    for joint in graph.joints:
        current: str | None = joint.name
        while current is not None and current not in owner_by_anchor:
            current = graph.joint_by_name[current].parent
        owner_by_joint[joint.name] = None if current is None else owner_by_anchor[current]
    return owner_by_joint


def _spatial_segment_cut_owner(
    graph: _SkeletonGraph,
    face_centroid: Vector3,
    current_depth: int,
    segment_cut_sites: tuple[FractureCutSite, ...],
    segment_projection_by_token: dict[str, tuple[float, float, float, float, float, float, float]],
) -> str | None:
    best: tuple[int, str] | None = None
    for cut_site in segment_cut_sites:
        parent = cut_site.parent_joint_token
        child = cut_site.child_joint_token
        segment_t = cut_site.segment_t
        if parent is None or child is None or segment_t is None:
            continue
        projected_t = _project_point_with_data(face_centroid, segment_projection_by_token[cut_site.joint_token])
        if projected_t < segment_t:
            continue
        depth = graph.depth_by_name[child]
        if depth < current_depth:
            continue
        candidate = (depth, cut_site.joint_token)
        if best is None or candidate > best:
            best = candidate
    if best is None:
        return None
    return best[1]


def _owner_anchor_depth(
    graph: _SkeletonGraph,
    owner: str | None,
    selected_cut_sites: list[FractureCutSite],
) -> int:
    if owner is None:
        return -1
    for cut_site in selected_cut_sites:
        if cut_site.joint_token == owner:
            anchor = cut_site.child_joint_token or cut_site.joint_token
            return graph.depth_by_name.get(anchor, -1)
    return graph.depth_by_name.get(owner, -1)


def _is_ancestor_or_self(graph: _SkeletonGraph, ancestor: str, joint_token: str) -> bool:
    ancestor_index = graph.preorder_by_name[ancestor]
    joint_index = graph.preorder_by_name[joint_token]
    return ancestor_index <= joint_index < graph.subtree_end_by_name[ancestor]


def _base_face_centroids(model: CanonicalTreeModel) -> tuple[Vector3 | None, ...]:
    mesh = model.base_mesh
    if mesh is None:
        raise FractureError("Fracture planning requires a base mesh.")
    centroids = []
    cursor = 0
    for face_index, vertex_count in enumerate(mesh.face_vertex_counts):
        face_indices = mesh.face_vertex_indices[cursor : cursor + vertex_count]
        cursor += vertex_count
        if not face_indices:
            centroids.append(None)
            continue
        x = sum(mesh.points[index].x for index in face_indices) / len(face_indices)
        y = sum(mesh.points[index].y for index in face_indices) / len(face_indices)
        z = sum(mesh.points[index].z for index in face_indices) / len(face_indices)
        centroids.append(Vector3(x, y, z))
    return tuple(centroids)


def _project_point_to_segment_t(point: Vector3, parent: Vector3, child: Vector3) -> float:
    return _project_point_with_data(point, _segment_projection_data(parent, child))


def _segment_projection_data(
    parent: Vector3,
    child: Vector3,
) -> tuple[float, float, float, float, float, float, float]:
    dx = child.x - parent.x
    dy = child.y - parent.y
    dz = child.z - parent.z
    length_squared = dx * dx + dy * dy + dz * dz
    if length_squared <= 0.0:
        raise FractureError("Manual fracture segment cut references a zero-length skeleton edge.")
    return parent.x, parent.y, parent.z, dx, dy, dz, 1.0 / length_squared


def _project_point_with_data(
    point: Vector3,
    projection: tuple[float, float, float, float, float, float, float],
) -> float:
    parent_x, parent_y, parent_z, dx, dy, dz, inverse_length_squared = projection
    return (
        (point.x - parent_x) * dx
        + (point.y - parent_y) * dy
        + (point.z - parent_z) * dz
    ) * inverse_length_squared


def _raise_for_empty_manual_cut_pieces(
    selected_cut_sites: list[FractureCutSite],
    pieces: tuple[FracturePiece, ...],
) -> None:
    manual_tokens = {
        cut_site.joint_token
        for cut_site in selected_cut_sites
        if cut_site.reason.startswith("manual_pinned")
    }
    for piece in pieces:
        if piece.cut_joint_token in manual_tokens and not piece.base_face_indices:
            raise FractureError(
                f"Manual fracture cut site {piece.cut_joint_token} cannot produce a Fracture Piece with base mesh faces."
            )


def _renumber_pieces(pieces: tuple[FracturePiece, ...], *, output_stem: str) -> tuple[FracturePiece, ...]:
    return tuple(
        FracturePiece(
            index=index,
            name=f"{output_stem}_fracture_{index:02d}",
            is_root_piece=index == 0 and piece.is_root_piece,
            cut_joint_token=piece.cut_joint_token,
            joint_tokens=piece.joint_tokens,
            base_face_indices=piece.base_face_indices,
            repeated_part_indices=piece.repeated_part_indices,
            repeated_part_names=piece.repeated_part_names,
        )
        for index, piece in enumerate(pieces)
    )


def _base_face_bindings_by_index(
    model: CanonicalTreeModel,
    graph: _SkeletonGraph,
) -> tuple[tuple[str | None, ...], tuple[frozenset[str], ...]]:
    mesh = model.base_mesh
    if mesh is None:
        raise FractureError("Fracture planning requires a base mesh.")
    if mesh.skel_element_size <= 0:
        raise FractureError("Fracture planning requires base mesh skinning indices.")

    expected_joint_slots = len(mesh.points) * mesh.skel_element_size
    if len(mesh.skel_joint_indices) < expected_joint_slots:
        raise FractureError("Base mesh skinning index count is smaller than point count.")
    if mesh.skel_joint_weights and len(mesh.skel_joint_weights) < expected_joint_slots:
        raise FractureError("Base mesh skinning weight count is smaller than point count.")

    point_bindings = tuple(_point_binding_tokens(model, graph, point_index) for point_index in range(len(mesh.points)))
    face_owner_tokens: list[str | None] = []
    face_auto_children: list[frozenset[str]] = []
    cursor = 0
    for face_index, vertex_count in enumerate(mesh.face_vertex_counts):
        if vertex_count < 0:
            raise FractureError(f"Base mesh face {face_index} has invalid vertex count {vertex_count}.")
        if vertex_count == 0:
            face_owner_tokens.append(None)
            face_auto_children.append(frozenset())
            continue
        face_indices = mesh.face_vertex_indices[cursor : cursor + vertex_count]
        if len(face_indices) != vertex_count:
            raise FractureError(f"Base mesh face {face_index} is missing face vertex indices.")
        cursor += vertex_count
        for point_index in face_indices:
            if point_index < 0 or point_index >= len(point_bindings):
                raise FractureError(f"Base mesh face {face_index} references point {point_index} outside the mesh.")
        owner = _majority_token(tuple(point_bindings[index][0] for index in face_indices), face_index)
        face_owner_tokens.append(owner)
        face_auto_children.append(
            frozenset(
                child
                for index in face_indices
                for token in point_bindings[index][1]
                if (child := _child_below(graph, owner, token)) is not None
            )
        )
    if cursor != len(mesh.face_vertex_indices):
        raise FractureError("Base mesh has trailing face vertex indices that are not referenced by face counts.")
    return tuple(face_owner_tokens), tuple(face_auto_children)


def _point_binding_tokens(
    model: CanonicalTreeModel,
    graph: _SkeletonGraph,
    point_index: int,
) -> tuple[str, frozenset[str]]:
    mesh = model.base_mesh
    if mesh is None:
        raise FractureError("Fracture planning requires a base mesh.")
    start = point_index * mesh.skel_element_size
    best_slot = 0
    influence_tokens: set[str] = set()
    if mesh.skel_joint_weights:
        best_weight = mesh.skel_joint_weights[start]
        for slot in range(mesh.skel_element_size):
            weight = mesh.skel_joint_weights[start + slot]
            if weight > best_weight:
                best_weight = weight
                best_slot = slot
            if weight <= 0.0:
                continue
            joint_index = mesh.skel_joint_indices[start + slot]
            if joint_index < 0 or joint_index >= len(graph.joints):
                raise FractureError(f"Base mesh point {point_index} references skeleton joint index {joint_index}.")
            influence_tokens.add(graph.joints[joint_index].name)
    joint_index = mesh.skel_joint_indices[start + best_slot]
    if joint_index < 0 or joint_index >= len(graph.joints):
        raise FractureError(f"Base mesh point {point_index} references skeleton joint index {joint_index}.")
    owner_token = graph.joints[joint_index].name
    if not mesh.skel_joint_weights:
        influence_tokens.add(owner_token)
    return owner_token, frozenset(influence_tokens)


def _child_below(graph: _SkeletonGraph, ancestor: str, joint_token: str) -> str | None:
    current = joint_token
    while current != ancestor:
        parent = graph.joint_by_name[current].parent
        if parent == ancestor:
            return current
        if parent is None:
            return None
        current = parent
    return None


def _majority_token(tokens: tuple[str, ...], face_index: int) -> str:
    if not tokens:
        raise FractureError(f"Base mesh face {face_index} has no owner tokens.")
    counts: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    for order, token in enumerate(tokens):
        counts[token] = counts.get(token, 0) + 1
        first_seen.setdefault(token, order)
    return min(counts, key=lambda token: (-counts[token], first_seen[token], token))


def _repeated_part_joint_token(part: RepeatedPartInstance, graph: _SkeletonGraph) -> str:
    for source_bone_id in part.source_bone_ids:
        for joint in graph.joints:
            if joint.source_id == source_bone_id:
                return joint.name

    if part.binding.joint_tokens:
        weighted_tokens = tuple(
            zip(
                part.binding.joint_tokens,
                part.binding.weights or (1.0,) * len(part.binding.joint_tokens),
            )
        )
        token = max(weighted_tokens, key=lambda item: item[1])[0]
        if token in graph.joint_by_name:
            return token
        raise FractureError(f"Repeated part {part.name} references missing skeleton joint {token}.")

    raise FractureError(f"Repeated part {part.name} has no skeleton binding for fracture assignment.")


def _root_to_leaf_paths(graph: _SkeletonGraph) -> tuple[tuple[str, ...], ...]:
    paths: list[tuple[str, ...]] = []

    def visit(token: str, path: tuple[str, ...]) -> None:
        next_path = path + (token,)
        children = graph.children_by_name[token]
        if not children:
            paths.append(next_path)
            return
        for child in children:
            visit(child, next_path)

    for root in graph.roots:
        visit(root, ())
    return tuple(paths)


def _root_to_leaf_paths_from(graph: _SkeletonGraph, root_token: str) -> tuple[tuple[str, ...], ...]:
    paths: list[tuple[str, ...]] = []

    def visit(token: str, path: tuple[str, ...]) -> None:
        next_path = path + (token,)
        children = graph.children_by_name[token]
        if not children:
            paths.append(next_path)
            return
        for child in children:
            visit(child, next_path)

    visit(root_token, ())
    return tuple(paths)


def _path_length(graph: _SkeletonGraph, path: tuple[str, ...]) -> float:
    total = 0.0
    for child_token in path[1:]:
        parent_token = graph.joint_by_name[child_token].parent
        if parent_token is None:
            continue
        total += _edge_length(graph, parent_token, child_token)
    return total


def _subtree_max_path_lengths(graph: _SkeletonGraph) -> dict[str, float]:
    lengths: dict[str, float] = {}

    def resolve(token: str) -> float:
        if token in lengths:
            return lengths[token]
        children = graph.children_by_name[token]
        if not children:
            lengths[token] = 0.0
            return 0.0
        length = max(_edge_length(graph, token, child) + resolve(child) for child in children)
        lengths[token] = length
        return length

    for joint in graph.joints:
        resolve(joint.name)
    return lengths


def _edge_length(graph: _SkeletonGraph, parent_token: str, child_token: str) -> float:
    child = graph.joint_by_name[child_token].rest_translate
    parent = graph.joint_by_name[parent_token].rest_translate
    return sqrt((child.x - parent.x) ** 2 + (child.y - parent.y) ** 2 + (child.z - parent.z) ** 2)


def _subtree_base_face_counts(
    graph: _SkeletonGraph,
    base_face_owner_by_index: tuple[str | None, ...],
) -> dict[str, int]:
    counts = {joint.name: 0 for joint in graph.joints}
    for owner_token in base_face_owner_by_index:
        if owner_token is None:
            continue
        current: str | None = owner_token
        while current is not None:
            counts[current] += 1
            current = graph.joint_by_name[current].parent
    return counts
