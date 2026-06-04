"""Fracture planning for destructible tree assemblies.

Layer: domain/application boundary.

This module plans stable static assembly pieces from an authored tree model.
It does not write USD and does not mutate the resolved model.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from .models import CanonicalTreeModel, Joint, RepeatedPartInstance, ValidationIssue


FRACTURE_METHOD_WIND_GUIDED_HIERARCHY = "wind_guided_hierarchy"
FRACTURE_METHOD_PURE_HIERARCHY = "pure_hierarchy"
FRACTURE_METHOD_BRANCH_BASE_GREEDY = "branch_base_greedy"

_SUPPORTED_METHODS = {
    FRACTURE_METHOD_WIND_GUIDED_HIERARCHY,
    FRACTURE_METHOD_PURE_HIERARCHY,
    FRACTURE_METHOD_BRANCH_BASE_GREEDY,
}


class FractureError(ValueError):
    """Raised when a fracture plan cannot be safely derived."""


@dataclass(frozen=True)
class FractureSettings:
    method: str = FRACTURE_METHOD_WIND_GUIDED_HIERARCHY
    target_piece_count: int = 5
    output_stem: str = "Tree"


@dataclass(frozen=True)
class FractureCutSite:
    joint_token: str
    kind: str
    reason: str


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


def plan_fracture(model: CanonicalTreeModel, settings: FractureSettings | None = None) -> FracturePlan:
    resolved_settings = settings or FractureSettings()
    _validate_settings(resolved_settings)
    _validate_fracture_source(model)

    graph = _build_skeleton_graph(model.skeleton)
    base_face_owner_by_index = _base_face_owner_by_index(model, graph)
    subtree_base_face_counts = _subtree_base_face_counts(graph, base_face_owner_by_index)
    main_axis = _select_main_axis(graph, resolved_settings.method)
    candidate_cut_sites, candidate_diagnostics = _candidate_cut_sites(
        graph,
        subtree_base_face_counts,
        method=resolved_settings.method,
        main_axis=main_axis,
    )

    selected: list[FractureCutSite] = []
    rejected: list[FractureCutSite] = []
    pieces = _build_pieces(
        model,
        graph,
        base_face_owner_by_index,
        selected,
        output_stem=resolved_settings.output_stem,
    )
    for cut_site in candidate_cut_sites:
        if len(pieces) >= resolved_settings.target_piece_count:
            break
        trial_selected = selected + [cut_site]
        trial_pieces = _build_pieces(
            model,
            graph,
            base_face_owner_by_index,
            trial_selected,
            output_stem=resolved_settings.output_stem,
        )
        if len(trial_pieces) == len(selected) + 2 and all(piece.base_face_indices for piece in trial_pieces):
            selected.append(cut_site)
            pieces = trial_pieces
        else:
            rejected.append(cut_site)

    if len(pieces) < resolved_settings.target_piece_count:
        pieces, synthetic_cut_sites = _refine_with_synthetic_face_splits(
            pieces,
            target_piece_count=resolved_settings.target_piece_count,
            output_stem=resolved_settings.output_stem,
        )
        selected.extend(synthetic_cut_sites)

    diagnostics = candidate_diagnostics
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
        method=resolved_settings.method,
        requested_piece_count=resolved_settings.target_piece_count,
        actual_piece_count=len(pieces),
        output_stem=resolved_settings.output_stem,
        main_axis_joint_tokens=main_axis,
        selected_cut_sites=tuple(selected),
        rejected_cut_sites=tuple(rejected),
        pieces=pieces,
        diagnostics=diagnostics,
    )


def _validate_settings(settings: FractureSettings) -> None:
    if settings.method not in _SUPPORTED_METHODS:
        raise FractureError(f"Unsupported fracture method: {settings.method}")
    if settings.target_piece_count <= 0:
        raise FractureError("Fracture target piece count must be greater than zero.")
    if not settings.output_stem.strip():
        raise FractureError("Fracture output stem must not be empty.")


def _validate_fracture_source(model: CanonicalTreeModel) -> None:
    if model.base_mesh is None:
        raise FractureError("Fracture planning requires a base mesh.")
    if not model.skeleton:
        raise FractureError("Fracture planning requires a skeleton hierarchy.")
    if model.base_mesh.skel_element_size <= 0 or not model.base_mesh.skel_joint_indices:
        raise FractureError("Fracture planning requires base mesh skinning indices.")


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


def _select_main_axis(graph: _SkeletonGraph, method: str) -> tuple[str, ...]:
    paths = _root_to_leaf_paths(graph)
    if not paths:
        return graph.roots[:1]
    if method == FRACTURE_METHOD_WIND_GUIDED_HIERARCHY:
        return max(
            paths,
            key=lambda path: (
                sum(1 for token in path if graph.joint_by_name[token].generator_level == 0),
                _path_length(graph, path),
                len(path),
                tuple(reversed(path)),
            ),
        )
    return max(paths, key=lambda path: (_path_length(graph, path), len(path), tuple(reversed(path))))


def _candidate_cut_sites(
    graph: _SkeletonGraph,
    subtree_base_face_counts: dict[str, int],
    *,
    method: str,
    main_axis: tuple[str, ...],
) -> tuple[tuple[FractureCutSite, ...], tuple[ValidationIssue, ...]]:
    if method == FRACTURE_METHOD_BRANCH_BASE_GREEDY:
        return _branch_base_candidates(graph, subtree_base_face_counts, main_axis), ()

    diagnostics: tuple[ValidationIssue, ...] = ()
    if method == FRACTURE_METHOD_WIND_GUIDED_HIERARCHY and not any(
        graph.joint_by_name[token].generator_level == 0 for token in main_axis
    ):
        diagnostics = (
            ValidationIssue(
                severity="warning",
                code="fracture_wind_guidance_missing",
                message="Wind-guided fracture could not find Group_0 joints and used hierarchy ordering.",
            ),
        )

    candidates: list[FractureCutSite] = []
    midpoint = _main_axis_midpoint(graph, main_axis, subtree_base_face_counts)
    if midpoint is not None:
        candidates.append(FractureCutSite(joint_token=midpoint, kind="joint", reason="main_axis_midpoint"))

    candidates.extend(_branch_base_candidates(graph, subtree_base_face_counts, main_axis))
    candidates.extend(_remaining_hierarchy_candidates(graph, subtree_base_face_counts, candidates))
    return tuple(_dedupe_cut_sites(candidates)), diagnostics


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
    base_face_owner_by_index: tuple[str, ...],
    selected_cut_sites: list[FractureCutSite],
    *,
    output_stem: str,
) -> tuple[FracturePiece, ...]:
    selected_tokens = tuple(cut_site.joint_token for cut_site in selected_cut_sites)
    owner_by_joint = {
        joint.name: _deepest_selected_ancestor(graph, joint.name, selected_tokens)
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

    for face_index, joint_token in enumerate(base_face_owner_by_index):
        face_indices_by_owner[owner_by_joint[joint_token]].append(face_index)

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


def _refine_with_synthetic_face_splits(
    pieces: tuple[FracturePiece, ...],
    *,
    target_piece_count: int,
    output_stem: str,
) -> tuple[tuple[FracturePiece, ...], tuple[FractureCutSite, ...]]:
    refined = list(pieces)
    synthetic_cut_sites: list[FractureCutSite] = []
    while len(refined) < target_piece_count:
        split_index = _synthetic_split_piece_index(refined)
        if split_index is None:
            break
        piece = refined[split_index]
        split_at = len(piece.base_face_indices) // 2
        left_faces = piece.base_face_indices[:split_at]
        right_faces = piece.base_face_indices[split_at:]
        if not left_faces or not right_faces:
            break
        cut_token = f"{piece.cut_joint_token or 'root'}#face_split_{len(synthetic_cut_sites) + 1:02d}"
        refined[split_index] = FracturePiece(
            index=piece.index,
            name=piece.name,
            is_root_piece=piece.is_root_piece,
            cut_joint_token=piece.cut_joint_token,
            joint_tokens=piece.joint_tokens,
            base_face_indices=left_faces,
            repeated_part_indices=piece.repeated_part_indices,
            repeated_part_names=piece.repeated_part_names,
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
                repeated_part_indices=(),
                repeated_part_names=(),
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
        if len(piece.base_face_indices) > 1 and not piece.repeated_part_indices
    ]
    if not candidates:
        return None
    _face_count, index = max(candidates, key=lambda item: (item[0], item[1]))
    return index


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


def _base_face_owner_by_index(model: CanonicalTreeModel, graph: _SkeletonGraph) -> tuple[str, ...]:
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
    face_owner_tokens: list[str] = []
    cursor = 0
    for face_index, vertex_count in enumerate(mesh.face_vertex_counts):
        if vertex_count <= 0:
            raise FractureError(f"Base mesh face {face_index} has invalid vertex count {vertex_count}.")
        face_indices = mesh.face_vertex_indices[cursor : cursor + vertex_count]
        if len(face_indices) != vertex_count:
            raise FractureError(f"Base mesh face {face_index} is missing face vertex indices.")
        cursor += vertex_count
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


def _deepest_selected_ancestor(
    graph: _SkeletonGraph,
    joint_token: str,
    selected_tokens: tuple[str, ...],
) -> str | None:
    selected = set(selected_tokens)
    current: str | None = joint_token
    while current is not None:
        if current in selected:
            return current
        current = graph.joint_by_name[current].parent
    return None


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
    base_face_owner_by_index: tuple[str, ...],
) -> dict[str, int]:
    counts = {joint.name: 0 for joint in graph.joints}
    for owner_token in base_face_owner_by_index:
        current: str | None = owner_token
        while current is not None:
            counts[current] += 1
            current = graph.joint_by_name[current].parent
    return counts
