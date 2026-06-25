"""Fracture planning for destructible tree assemblies.

Layer: domain/application boundary.

This module plans stable static assembly pieces from an authored tree model.
It does not write USD and does not mutate the resolved model.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from .models import CanonicalTreeModel, Joint, RepeatedPartInstance, ValidationIssue, Vector3


FRACTURE_METHOD_MANUAL_FRACTURING = "manual_fracturing"
_LEGACY_METHODS = {
    "wind_guided_hierarchy",
    "pure_hierarchy",
    "branch_base_greedy",
    "manual_pinned_bones",
}
_MIN_MANUAL_SEGMENT_CUT_SEPARATION = 0.02


class FractureError(ValueError):
    """Raised when a fracture plan cannot be safely derived."""


@dataclass(frozen=True)
class FractureSettings:
    target_piece_count: int = 5
    output_stem: str = "Tree"
    pinned_cut_joint_tokens: tuple[str, ...] = ()
    generate_caps: bool = False
    preserve_trunk_bias: float = 0.5
    force_stump_piece: bool = False


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


@dataclass(frozen=True)
class _FracturePlanCache:
    graph: _SkeletonGraph
    base_face_owner_by_index: tuple[str | None, ...]
    subtree_base_face_counts: dict[str, int]
    main_axis: tuple[str, ...]


def format_manual_segment_cut_token(parent_joint_token: str, child_joint_token: str, segment_t: float) -> str:
    parent = parent_joint_token.strip()
    child = child_joint_token.strip()
    if not parent or not child:
        raise FractureError("Manual segment cut requires non-empty parent and child joint tokens.")
    t = float(segment_t)
    if t <= 0.0 or t >= 1.0:
        raise FractureError(f"Manual segment cut position must be between 0 and 1, got {segment_t}.")
    return f"{parent}->{child}@{t:.3f}"


def plan_fracture(
    model: CanonicalTreeModel,
    settings: FractureSettings | None = None,
    *,
    analysis_cache: _FracturePlanCache | None = None,
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
    subtree_base_face_counts = analysis_cache.subtree_base_face_counts
    main_axis = analysis_cache.main_axis
    candidate_cut_sites, candidate_diagnostics = _candidate_cut_sites(
        graph,
        subtree_base_face_counts,
        main_axis=main_axis,
        preserve_trunk_bias=resolved_settings.preserve_trunk_bias,
    )

    selected: list[FractureCutSite] = _manual_cut_sites(resolved_settings, graph, subtree_base_face_counts)
    if resolved_settings.force_stump_piece:
        stump_cut = _stump_cut_site(
            graph,
            subtree_base_face_counts,
            main_axis=main_axis,
        )
        if stump_cut is not None and all(cut.joint_token != stump_cut.joint_token for cut in selected):
            selected.append(stump_cut)
            selected = _ordered_cut_sites_for_settings(selected, graph)
    rejected: list[FractureCutSite] = []
    pieces = _build_pieces(
        model,
        graph,
        base_face_owner_by_index,
        _ordered_cut_sites_for_settings(selected, graph),
        output_stem=resolved_settings.output_stem,
    )
    _raise_for_empty_manual_cut_pieces(selected, pieces)
    for cut_site in candidate_cut_sites:
        if any(existing.joint_token == cut_site.joint_token for existing in selected):
            continue
        if len(pieces) >= resolved_settings.target_piece_count:
            break
        trial_selected = _ordered_cut_sites_for_settings(selected + [cut_site], graph)
        trial_pieces = _build_pieces(
            model,
            graph,
            base_face_owner_by_index,
            trial_selected,
            output_stem=resolved_settings.output_stem,
        )
        if len(trial_pieces) == len(selected) + 2 and all(piece.base_face_indices for piece in trial_pieces):
            selected = trial_selected
            pieces = trial_pieces
        else:
            rejected.append(cut_site)

    if len(pieces) < resolved_settings.target_piece_count:
        pieces, synthetic_cut_sites = _refine_with_synthetic_face_splits(
            model,
            pieces,
            target_piece_count=resolved_settings.target_piece_count,
            output_stem=resolved_settings.output_stem,
        )
        selected.extend(synthetic_cut_sites)
        _raise_for_empty_manual_cut_pieces(selected, pieces)

    diagnostics = candidate_diagnostics + _manual_piece_count_diagnostics(resolved_settings, pieces)
    if len(pieces) < resolved_settings.target_piece_count:
        diagnostics += (
            ValidationIssue(
                severity="warning",
                code="fracture_piece_count_clamped",
                message=(
                    "Fracture target piece count was clamped because no remaining joint cut site "
                    f"could produce a piece with base mesh faces: requested {resolved_settings.target_piece_count}, "
                    f"actual {len(pieces)}."
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
    base_face_owner_by_index = _base_face_owner_by_index(model, graph)
    return _FracturePlanCache(
        graph=graph,
        base_face_owner_by_index=base_face_owner_by_index,
        subtree_base_face_counts=_subtree_base_face_counts(graph, base_face_owner_by_index),
        main_axis=_select_main_axis(graph),
    )


def _manual_piece_count_diagnostics(
    settings: FractureSettings,
    pieces: tuple[FracturePiece, ...],
) -> tuple[ValidationIssue, ...]:
    if len(pieces) <= settings.target_piece_count:
        return ()
    return (
        ValidationIssue(
            severity="warning",
            code="fracture_manual_piece_count_exceeds_target",
            message=(
                "Manual fracture cut sites produced more pieces than the target; "
                f"requested {settings.target_piece_count}, actual {len(pieces)}."
            ),
        ),
    )


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
            "Fracture target piece count must be an integer, "
            f"got {type(settings.target_piece_count).__name__}."
        )
    if settings.target_piece_count <= 0:
        raise FractureError("Fracture target piece count must be greater than zero.")
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
    if not 0.0 <= float(settings.preserve_trunk_bias) <= 1.0:
        raise FractureError("Fracture preserve_trunk_bias must be between 0 and 1.")
    if not isinstance(settings.force_stump_piece, bool):
        raise FractureError(
            f"Fracture force_stump_piece must be a bool, got {type(settings.force_stump_piece).__name__}."
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
    anchor = cut_site.child_joint_token or cut_site.joint_token
    return (graph.index_by_name.get(anchor, len(graph.joints)), cut_site.segment_t or -1.0, cut_site.joint_token)


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

    return _SkeletonGraph(
        joints=skeleton,
        joint_by_name=joint_by_name,
        index_by_name=index_by_name,
        children_by_name=children_by_name,
        roots=tuple(sorted(roots)),
        depth_by_name=depth_by_name,
    )


def _select_main_axis(graph: _SkeletonGraph) -> tuple[str, ...]:
    paths = _root_to_leaf_paths(graph)
    if not paths:
        return graph.roots[:1]
    return max(paths, key=lambda path: (_path_length(graph, path), len(path), tuple(reversed(path))))


def _candidate_cut_sites(
    graph: _SkeletonGraph,
    subtree_base_face_counts: dict[str, int],
    *,
    main_axis: tuple[str, ...],
    preserve_trunk_bias: float,
) -> tuple[tuple[FractureCutSite, ...], tuple[ValidationIssue, ...]]:
    candidates: list[FractureCutSite] = []
    midpoint = _main_axis_midpoint(graph, main_axis, subtree_base_face_counts)
    branch_candidates = list(_branch_base_candidates(graph, subtree_base_face_counts, main_axis))
    if midpoint is not None and preserve_trunk_bias < 0.5:
        candidates.append(FractureCutSite(joint_token=midpoint, kind="joint", reason="main_axis_midpoint"))
    candidates.extend(branch_candidates)
    if midpoint is not None and preserve_trunk_bias >= 0.5:
        candidates.append(FractureCutSite(joint_token=midpoint, kind="joint", reason="main_axis_midpoint"))
    candidates.extend(_remaining_hierarchy_candidates(graph, subtree_base_face_counts, candidates))
    return tuple(_dedupe_cut_sites(candidates)), ()


def _stump_cut_site(
    graph: _SkeletonGraph,
    subtree_base_face_counts: dict[str, int],
    *,
    main_axis: tuple[str, ...],
) -> FractureCutSite | None:
    if len(main_axis) < 2:
        return None
    root_token = main_axis[0]
    child_token = main_axis[1]
    child = graph.joint_by_name[child_token]
    if child.parent != root_token:
        return None
    total_faces = subtree_base_face_counts.get(root_token, 0)
    child_faces = subtree_base_face_counts.get(child_token, 0)
    if child_faces <= 0 or total_faces - child_faces <= 0:
        return None
    return FractureCutSite(
        joint_token=child_token,
        kind="joint",
        reason="stump_piece",
        parent_joint_token=root_token,
        child_joint_token=child_token,
    )


def _branch_base_candidates(
    graph: _SkeletonGraph,
    subtree_base_face_counts: dict[str, int],
    main_axis: tuple[str, ...],
) -> tuple[FractureCutSite, ...]:
    main_axis_set = set(main_axis)
    candidates = [
        token
        for token in graph.joint_by_name
        if token not in graph.roots
        and token not in main_axis_set
        and graph.joint_by_name[token].parent in main_axis_set
        and subtree_base_face_counts.get(token, 0) > 0
    ]
    candidates.sort(
        key=lambda token: (
            _generator_level_sort_key(graph.joint_by_name[token]),
            -subtree_base_face_counts[token],
            graph.depth_by_name[token],
            token,
        )
    )
    return tuple(FractureCutSite(joint_token=token, kind="joint", reason="branch_base") for token in candidates)


def _remaining_hierarchy_candidates(
    graph: _SkeletonGraph,
    subtree_base_face_counts: dict[str, int],
    existing: list[FractureCutSite],
) -> tuple[FractureCutSite, ...]:
    existing_tokens = {cut_site.joint_token for cut_site in existing}
    candidates = [
        token
        for token in graph.joint_by_name
        if token not in graph.roots
        and token not in existing_tokens
        and subtree_base_face_counts.get(token, 0) > 0
    ]
    candidates.sort(
        key=lambda token: (
            -subtree_base_face_counts[token],
            graph.depth_by_name[token],
            token,
        )
    )
    return tuple(FractureCutSite(joint_token=token, kind="joint", reason="hierarchy_refinement") for token in candidates)


def _main_axis_midpoint(
    graph: _SkeletonGraph,
    main_axis: tuple[str, ...],
    subtree_base_face_counts: dict[str, int],
) -> str | None:
    candidates = [
        token
        for token in main_axis[1:]
        if subtree_base_face_counts.get(token, 0) > 0
    ]
    if not candidates:
        return None
    return candidates[(len(candidates) - 1) // 2]


def _dedupe_cut_sites(cut_sites: list[FractureCutSite]) -> tuple[FractureCutSite, ...]:
    seen: set[str] = set()
    deduped: list[FractureCutSite] = []
    for cut_site in cut_sites:
        if cut_site.joint_token in seen:
            continue
        seen.add(cut_site.joint_token)
        deduped.append(cut_site)
    return tuple(deduped)


def _build_pieces(
    model: CanonicalTreeModel,
    graph: _SkeletonGraph,
    base_face_owner_by_index: tuple[str | None, ...],
    selected_cut_sites: list[FractureCutSite],
    *,
    output_stem: str,
) -> tuple[FracturePiece, ...]:
    selected_tokens = tuple(cut_site.joint_token for cut_site in selected_cut_sites)
    owner_by_joint = {
        joint.name: _deepest_selected_cut_owner(graph, joint.name, selected_cut_sites)
        for joint in graph.joints
    }
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

    segment_cut_sites = [cut_site for cut_site in selected_cut_sites if cut_site.kind == "manual_segment"]
    face_centroids = _base_face_centroids(model) if segment_cut_sites else ()
    for face_index, joint_token in enumerate(base_face_owner_by_index):
        if joint_token is None:
            continue
        owner = owner_by_joint[joint_token]
        segment_owner = None
        if segment_cut_sites:
            face_centroid = face_centroids[face_index]
            if face_centroid is None:
                continue
            segment_owner = _spatial_segment_cut_owner(
                graph,
                face_centroid,
                joint_token,
                owner,
                segment_cut_sites,
            )
        face_indices_by_owner[segment_owner or owner].append(face_index)

    for part_index, part in enumerate(model.repeated_parts):
        joint_token = _repeated_part_joint_token(part, graph)
        owner = owner_by_joint[joint_token]
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


def _deepest_selected_cut_owner(
    graph: _SkeletonGraph,
    joint_token: str,
    selected_cut_sites: list[FractureCutSite],
) -> str | None:
    best_owner: str | None = None
    best_depth = -1
    for cut_site in selected_cut_sites:
        anchor = cut_site.child_joint_token or cut_site.joint_token
        if not _is_ancestor_or_self(graph, anchor, joint_token):
            continue
        depth = graph.depth_by_name[anchor]
        if depth > best_depth:
            best_owner = cut_site.joint_token
            best_depth = depth
    return best_owner


def _spatial_segment_cut_owner(
    graph: _SkeletonGraph,
    face_centroid,
    face_owner_joint_token: str,
    current_owner: str | None,
    selected_cut_sites: list[FractureCutSite],
) -> str | None:
    current_depth = _owner_anchor_depth(graph, current_owner, selected_cut_sites)
    best: tuple[int, str] | None = None
    for cut_site in selected_cut_sites:
        if cut_site.kind != "manual_segment":
            continue
        parent = cut_site.parent_joint_token
        child = cut_site.child_joint_token
        segment_t = cut_site.segment_t
        if parent is None or child is None or segment_t is None:
            continue
        if not (
            _is_ancestor_or_self(graph, parent, face_owner_joint_token)
            or _is_ancestor_or_self(graph, face_owner_joint_token, parent)
        ):
            continue
        projected_t = _project_point_to_segment_t(
            face_centroid,
            graph.joint_by_name[parent].bind_translate,
            graph.joint_by_name[child].bind_translate,
        )
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
    current: str | None = joint_token
    while current is not None:
        if current == ancestor:
            return True
        current = graph.joint_by_name[current].parent
    return False


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
    dx = child.x - parent.x
    dy = child.y - parent.y
    dz = child.z - parent.z
    length_squared = dx * dx + dy * dy + dz * dz
    if length_squared <= 0.0:
        raise FractureError("Manual fracture segment cut references a zero-length skeleton edge.")
    return ((point.x - parent.x) * dx + (point.y - parent.y) * dy + (point.z - parent.z) * dz) / length_squared


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


def _refine_with_synthetic_face_splits(
    model: CanonicalTreeModel,
    pieces: tuple[FracturePiece, ...],
    *,
    target_piece_count: int,
    output_stem: str,
) -> tuple[tuple[FracturePiece, ...], tuple[FractureCutSite, ...]]:
    refined = list(pieces)
    synthetic_cut_sites: list[FractureCutSite] = []
    face_centroids = _base_face_centroids(model)
    prototype_bounds_by_key = _prototype_bounds_by_key(model)
    while len(refined) < target_piece_count:
        split_index = _synthetic_split_piece_index(refined)
        if split_index is None:
            break
        piece = refined[split_index]
        split = _split_piece_spatially(piece, face_centroids, model, prototype_bounds_by_key)
        if split is None:
            break
        left_faces, right_faces, left_repeated, right_repeated = split
        if not left_faces or not right_faces:
            break
        left_repeated_names = tuple(model.repeated_parts[index].name for index in left_repeated)
        right_repeated_names = tuple(model.repeated_parts[index].name for index in right_repeated)
        cut_token = f"{piece.cut_joint_token or 'root'}#face_split_{len(synthetic_cut_sites) + 1:02d}"
        refined[split_index] = FracturePiece(
            index=piece.index,
            name=piece.name,
            is_root_piece=piece.is_root_piece,
            cut_joint_token=piece.cut_joint_token,
            joint_tokens=piece.joint_tokens,
            base_face_indices=left_faces,
            repeated_part_indices=left_repeated,
            repeated_part_names=left_repeated_names,
        )
        refined.insert(
            split_index + 1,
            FracturePiece(
                index=0,
                name="",
                is_root_piece=False,
                cut_joint_token=cut_token,
                joint_tokens=piece.joint_tokens,
                base_face_indices=right_faces,
                repeated_part_indices=right_repeated,
                repeated_part_names=right_repeated_names,
            ),
        )
        synthetic_cut_sites.append(
            FractureCutSite(
                joint_token=cut_token,
                kind="synthetic_mid_segment",
                reason="base_face_midpoint",
            )
        )
        refined = list(_renumber_pieces(tuple(refined), output_stem=output_stem))
    return tuple(refined), tuple(synthetic_cut_sites)


def _synthetic_split_piece_index(pieces: list[FracturePiece]) -> int | None:
    candidates = [
        (len(piece.base_face_indices), index)
        for index, piece in enumerate(pieces)
        if len(piece.base_face_indices) > 1
    ]
    if not candidates:
        return None
    _face_count, index = max(candidates, key=lambda item: (item[0], item[1]))
    return index


def _split_piece_spatially(
    piece: FracturePiece,
    face_centroids: tuple[Vector3 | None, ...],
    model: CanonicalTreeModel,
    prototype_bounds_by_key: dict[str, tuple[Vector3, Vector3]],
) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...], tuple[int, ...]] | None:
    centroids = [(face_index, face_centroids[face_index]) for face_index in piece.base_face_indices]
    if any(centroid is None for _face_index, centroid in centroids):
        return None
    points = tuple(centroid for _face_index, centroid in centroids if centroid is not None)
    axis = _widest_axis(points)
    projections = sorted(_axis_value(point, axis) for point in points)
    threshold = projections[len(projections) // 2]
    left_faces = tuple(face_index for face_index, centroid in centroids if _axis_value(centroid, axis) < threshold)
    right_faces = tuple(face_index for face_index, centroid in centroids if _axis_value(centroid, axis) >= threshold)
    if not left_faces or not right_faces:
        return None

    left_repeated: list[int] = []
    right_repeated: list[int] = []
    for part_index in piece.repeated_part_indices:
        side = _repeated_part_split_side(model.repeated_parts[part_index], prototype_bounds_by_key, axis, threshold)
        if side == "left":
            left_repeated.append(part_index)
        else:
            right_repeated.append(part_index)
    return left_faces, right_faces, tuple(left_repeated), tuple(right_repeated)


def _widest_axis(points: tuple[Vector3, ...]) -> str:
    spans = {
        "x": max(point.x for point in points) - min(point.x for point in points),
        "y": max(point.y for point in points) - min(point.y for point in points),
        "z": max(point.z for point in points) - min(point.z for point in points),
    }
    return max(("x", "y", "z"), key=lambda axis: (spans[axis], axis))


def _axis_value(point: Vector3, axis: str) -> float:
    return getattr(point, axis)


def _prototype_bounds_by_key(model: CanonicalTreeModel) -> dict[str, tuple[Vector3, Vector3]]:
    bounds: dict[str, tuple[Vector3, Vector3]] = {}
    for prototype in model.prototypes:
        points = _prototype_points(prototype)
        if points:
            bounds[prototype.source_key] = _points_bounds(points)
    return bounds


def _prototype_points(prototype) -> tuple[Vector3, ...]:
    if prototype.mesh is not None:
        return prototype.mesh.points
    payload = prototype.geometry_payload
    if payload is None:
        return ()
    components = payload.point_components
    return tuple(
        Vector3(float(components[index]), float(components[index + 1]), float(components[index + 2]))
        for index in range(0, len(components), 3)
    )


def _points_bounds(points: tuple[Vector3, ...]) -> tuple[Vector3, Vector3]:
    return (
        Vector3(min(point.x for point in points), min(point.y for point in points), min(point.z for point in points)),
        Vector3(max(point.x for point in points), max(point.y for point in points), max(point.z for point in points)),
    )


def _repeated_part_split_side(
    part: RepeatedPartInstance,
    prototype_bounds_by_key: dict[str, tuple[Vector3, Vector3]],
    axis: str,
    threshold: float,
) -> str:
    bounds = prototype_bounds_by_key.get(part.prototype_key)
    if bounds is None:
        raise FractureError(
            f"Synthetic fracture split cannot classify repeated part {part.name}: "
            f"prototype {part.prototype_key} has no mesh bounds."
        )
    projections = tuple(
        _axis_value(_transform_point(corner, part.position, part.orientation, part.scale), axis)
        for corner in _bounds_corners(bounds)
    )
    if max(projections) < threshold:
        return "left"
    if min(projections) >= threshold:
        return "right"
    raise FractureError(
        f"Synthetic fracture split plane crosses repeated part {part.name}; "
        "author a manual cut or provide a different target piece count."
    )


def _bounds_corners(bounds: tuple[Vector3, Vector3]) -> tuple[Vector3, ...]:
    minimum, maximum = bounds
    return (
        Vector3(minimum.x, minimum.y, minimum.z),
        Vector3(minimum.x, minimum.y, maximum.z),
        Vector3(minimum.x, maximum.y, minimum.z),
        Vector3(minimum.x, maximum.y, maximum.z),
        Vector3(maximum.x, minimum.y, minimum.z),
        Vector3(maximum.x, minimum.y, maximum.z),
        Vector3(maximum.x, maximum.y, minimum.z),
        Vector3(maximum.x, maximum.y, maximum.z),
    )


def _transform_point(point: Vector3, translate: Vector3, orientation, scale: Vector3) -> Vector3:
    scaled = Vector3(point.x * scale.x, point.y * scale.y, point.z * scale.z)
    rotated = _rotate_vector(scaled, orientation)
    return Vector3(rotated.x + translate.x, rotated.y + translate.y, rotated.z + translate.z)


def _rotate_vector(vector: Vector3, q) -> Vector3:
    w, x, y, z = float(q.real), float(q.i), float(q.j), float(q.k)
    length = sqrt(w * w + x * x + y * y + z * z)
    if length <= 0.0:
        raise FractureError("Synthetic fracture split encountered a zero-length repeated part orientation quaternion.")
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


def _base_face_owner_by_index(model: CanonicalTreeModel, graph: _SkeletonGraph) -> tuple[str | None, ...]:
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

    point_owner_tokens = tuple(_point_owner_token(model, graph, point_index) for point_index in range(len(mesh.points)))
    face_owner_tokens: list[str | None] = []
    cursor = 0
    for face_index, vertex_count in enumerate(mesh.face_vertex_counts):
        if vertex_count < 0:
            raise FractureError(f"Base mesh face {face_index} has invalid vertex count {vertex_count}.")
        if vertex_count == 0:
            face_owner_tokens.append(None)
            continue
        face_indices = mesh.face_vertex_indices[cursor : cursor + vertex_count]
        if len(face_indices) != vertex_count:
            raise FractureError(f"Base mesh face {face_index} is missing face vertex indices.")
        cursor += vertex_count
        for point_index in face_indices:
            if point_index < 0 or point_index >= len(point_owner_tokens):
                raise FractureError(f"Base mesh face {face_index} references point {point_index} outside the mesh.")
        face_owner_tokens.append(_majority_token(tuple(point_owner_tokens[index] for index in face_indices), face_index))
    if cursor != len(mesh.face_vertex_indices):
        raise FractureError("Base mesh has trailing face vertex indices that are not referenced by face counts.")
    return tuple(face_owner_tokens)


def _point_owner_token(model: CanonicalTreeModel, graph: _SkeletonGraph, point_index: int) -> str:
    mesh = model.base_mesh
    if mesh is None:
        raise FractureError("Fracture planning requires a base mesh.")
    start = point_index * mesh.skel_element_size
    best_slot = 0
    if mesh.skel_joint_weights:
        best_weight = mesh.skel_joint_weights[start]
        for slot in range(1, mesh.skel_element_size):
            weight = mesh.skel_joint_weights[start + slot]
            if weight > best_weight:
                best_weight = weight
                best_slot = slot
    joint_index = mesh.skel_joint_indices[start + best_slot]
    if joint_index < 0 or joint_index >= len(graph.joints):
        raise FractureError(f"Base mesh point {point_index} references skeleton joint index {joint_index}.")
    return graph.joints[joint_index].name


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

    for source_bone_id in part.source_bone_ids:
        for joint in graph.joints:
            if joint.source_id == source_bone_id:
                return joint.name
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


def _path_length(graph: _SkeletonGraph, path: tuple[str, ...]) -> float:
    total = 0.0
    for child_token in path[1:]:
        parent_token = graph.joint_by_name[child_token].parent
        if parent_token is None:
            continue
        child = graph.joint_by_name[child_token].rest_translate
        parent = graph.joint_by_name[parent_token].rest_translate
        total += sqrt((child.x - parent.x) ** 2 + (child.y - parent.y) ** 2 + (child.z - parent.z) ** 2)
    return total


def _generator_level_sort_key(joint: Joint) -> int:
    return joint.generator_level if joint.generator_level is not None else 999_999


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
