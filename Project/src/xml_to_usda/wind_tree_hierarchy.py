"""Bare-rig tree grouping. Prepare geometry once, classify levels interactively.

Names, ordering and generator labels never classify branches. See
docs/wiki/wind-tree-hierarchy.md for calibration and export boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from math import acos, cos, degrees, isfinite, radians

import numpy as np

from .models import Joint, Vector3


@dataclass(frozen=True, slots=True)
class TreeHierarchySettings:
    equivalent_forks: str = "keep_parent"
    direction_mode: str = "auto"
    fork_angle: float = 45.0
    chain_angle: float = 30.0
    distal_fraction: float = 0.95
    equivalent_angle: float = 10.0
    equivalent_size: float = 0.8
    equivalent_length: float = 0.8
    basal_distance: float = 0.1
    basal_balance: float = 0.25
    basal_planarity: float = 0.1
    frame_variation: float = 0.01
    independent_stems: bool = True
    prefer_branched: bool = True
    preserve_terminal: bool = True

    def __post_init__(self) -> None:
        if self.equivalent_forks not in {"keep_parent", "advance", "continuation"}:
            raise ValueError("wind_tree_invalid_settings: unknown equivalent fork policy.")
        if self.direction_mode not in {"auto", "bind", "attachments"}:
            raise ValueError("wind_tree_invalid_settings: unknown direction mode.")
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name in {"equivalent_forks", "direction_mode"}:
                continue
            if field.name in {"independent_stems", "prefer_branched", "preserve_terminal"}:
                if not isinstance(value, bool):
                    raise ValueError(f"wind_tree_invalid_settings: {field.name} must be Boolean.")
            else:
                maximum = 180.0 if field.name.endswith("angle") else 1.0
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or not 0 <= value <= maximum:
                    raise ValueError(f"wind_tree_invalid_settings: {field.name} must be finite in [0, {maximum}].")


@dataclass(frozen=True, slots=True)
class TreeHierarchyJoint:
    name: str
    branch_order: int
    display_end: Vector3
    ambiguous: bool = False
    equivalent: bool = False


@dataclass(frozen=True, slots=True)
class _ForkGeometry:
    alignments: tuple[float, ...]
    projections: tuple[float, ...]
    distal_length: float
    angle_span: float
    ambiguous: bool
    display_end: Vector3


@dataclass(frozen=True, slots=True)
class PreparedTreeHierarchy:
    names: tuple[str, ...]
    parents: tuple[int, ...]
    children: tuple[tuple[int, ...], ...]
    traversal: tuple[int, ...]
    fork_counts: tuple[int, ...]
    mass_ratios: tuple[float, ...]
    length_ratios: tuple[float, ...]
    root_geometry: tuple[tuple[float, float, float], ...]
    frame_variation: float
    tolerance: float
    bind_geometry: tuple[_ForkGeometry, ...]
    attachment_geometry: tuple[_ForkGeometry, ...]
    short_ends: tuple[Vector3, ...]
    attachment_short_ends: tuple[Vector3, ...]


def prepare_tree_hierarchy(skeleton: tuple[Joint, ...]) -> PreparedTreeHierarchy:
    """Validate and cache topology, both direction models and fork metrics."""
    index = {joint.name: i for i, joint in enumerate(skeleton)}
    if len(index) != len(skeleton):
        raise ValueError("wind_tree_duplicate_joint: joint names must be unique.")
    children: list[list[int]] = [[] for _ in skeleton]
    parents, roots = [], []
    for i, joint in enumerate(skeleton):
        if joint.parent is not None and joint.parent not in index:
            raise ValueError(f"wind_tree_missing_parent: {joint.name} -> {joint.parent}.")
        parent = index[joint.parent] if joint.parent is not None else -1
        parents.append(parent)
        (roots if parent < 0 else children[parent]).append(i)
    traversal, pending = [], list(roots)
    while pending:
        i = pending.pop()
        traversal.append(i)
        pending.extend(children[i])
    if len(traversal) != len(skeleton):
        raise ValueError("wind_tree_cyclic_hierarchy: joints are not reachable from roots.")
    positions = np.asarray([(j.bind_translate.x, j.bind_translate.y, j.bind_translate.z) for j in skeleton], dtype=float).reshape((-1, 3))
    axes = np.asarray([j.bind_transform.rows[0][:3] for j in skeleton], dtype=float).reshape((-1, 3))
    invalid = np.flatnonzero(~np.isfinite(positions).all(axis=1) | ~np.isfinite(axes).all(axis=1))
    sizes = np.linalg.norm(axes, axis=1)
    invalid = np.union1d(invalid, np.flatnonzero((sizes == 0) | ~np.isfinite(sizes)))
    if len(invalid):
        names = ", ".join(skeleton[i].name for i in invalid[:8])
        raise ValueError(f"wind_tree_invalid_pose: invalid bind position/forward axis at {names}.")
    axes /= sizes[:, None]
    extent = float(2 * np.max(np.linalg.norm(positions - positions.mean(axis=0), axis=1))) if skeleton else 0.0
    if not isfinite(extent):
        raise ValueError("wind_tree_invalid_extent: bind positions exceed the numerical range.")
    if extent <= 1e-12 and len(skeleton) > 1:
        raise ValueError("wind_tree_no_spatial_extent: coincident joints do not describe a tree's branches.")
    tolerance = max(extent * 1e-5, 1e-12)
    variation = float(np.max(np.linalg.norm(axes - axes.mean(axis=0), axis=1))) if skeleton else 0.0
    offsets = [positions[kids] - positions[i] for i, kids in enumerate(children)]
    inferred_axes = axes.copy()
    ambiguous = [False] * len(skeleton)
    # Uniform old USD frames need attachment-based axes. Cache both models so
    # moving the frame threshold never reruns PCA or reads the source.
    for i in traversal:
        if children[i]:
            if np.linalg.norm(offsets[i]) <= tolerance:
                ambiguous[i] = True
                continue
            values, vectors = np.linalg.eigh(offsets[i].T @ offsets[i])
            if values[-1] - values[-2] <= values[-1] * 1e-5:
                ambiguous[i] = True
                continue
            axis = vectors[:, -1]
            if np.dot(axis, offsets[i].sum(axis=0)) < 0:
                axis = -axis
            inferred_axes[i] = axis
        elif parents[i] >= 0:
            offset = positions[i] - positions[parents[i]]
            size = np.linalg.norm(offset)
            if size > 0:
                inferred_axes[i] = offset / size
    fork_counts, masses, path_lengths = [0] * len(skeleton), [1] * len(skeleton), [0.0] * len(skeleton)
    for i in reversed(traversal):
        kids = children[i]
        fork_counts[i] = int(len(kids) > 1) + sum(fork_counts[c] for c in kids)
        masses[i] += sum(masses[c] for c in kids)
        path_lengths[i] = max((float(np.linalg.norm(offset)) + path_lengths[c] for c, offset in zip(kids, offsets[i])), default=0.0)
    mass_ratios, length_ratios, root_geometry = [], [], []
    for i, kids in enumerate(children):
        mass_ratios.append(min((masses[c] for c in kids), default=1) / max((masses[c] for c in kids), default=1))
        lengths = [float(np.linalg.norm(offset)) + path_lengths[c] for c, offset in zip(kids, offsets[i])]
        length_ratios.append(min(lengths) / max(lengths) if lengths and max(lengths) > tolerance else 1.0)
        compact = max((float(np.linalg.norm(offset)) for offset in offsets[i]), default=0.0) / max(extent, tolerance)
        planarity, plane_distance = 0.0, float("inf")
        if parents[i] < 0 and len(kids) >= 3:
            centered = offsets[i] - offsets[i].mean(axis=0)
            values, vectors = np.linalg.eigh(centered.T @ centered)
            if values[2] > 0:
                planarity = float(values[1] / values[2])
            plane_distance = abs(float(np.dot(offsets[i].mean(axis=0), vectors[:, 0]))) / max(extent, tolerance)
        root_geometry.append((compact, planarity, plane_distance))

    def geometry(directions, uncertain):
        result, short_ends = [], []
        for i, joint in enumerate(skeleton):
            alignments = tuple(float(np.dot(directions[i], directions[c])) for c in children[i])
            projections = tuple(float(value) for value in offsets[i] @ directions[i])
            length = max(0.0, max(projections, default=0.0))
            angles = [degrees(acos(max(-1.0, min(1.0, value)))) for value in alignments]
            span = max(angles, default=0.0) - min(angles, default=0.0)
            short = joint.bind_end_translate or Vector3(*(float(v) for v in positions[i] + directions[i] * extent * 0.015))
            end = joint.bind_end_translate or Vector3(*(float(v) for v in positions[i] + directions[i] * (length if length > tolerance else extent * 0.015)))
            result.append(_ForkGeometry(alignments, projections, length, span, uncertain[i], end))
            short_ends.append(short)
        return tuple(result), tuple(short_ends)

    bind, short = geometry(axes, [False] * len(skeleton))
    attachments, attachment_short = geometry(inferred_axes, ambiguous)
    return PreparedTreeHierarchy(
        tuple(j.name for j in skeleton), tuple(parents), tuple(tuple(kids) for kids in children), tuple(traversal),
        tuple(fork_counts), tuple(mass_ratios), tuple(length_ratios), tuple(root_geometry), variation, tolerance,
        bind, attachments, short, attachment_short,
    )


def classify_tree_hierarchy(prepared: PreparedTreeHierarchy, settings: TreeHierarchySettings = TreeHierarchySettings()) -> tuple[TreeHierarchyJoint, ...]:
    """One forward O(joints + links) pass; no geometry, eigensolves or recursion."""
    directional = settings.direction_mode == "bind" or (settings.direction_mode == "auto" and prepared.frame_variation > settings.frame_variation)
    geometry = prepared.bind_geometry if directional else prepared.attachment_geometry
    # Grouping overrides must not turn a readable skeleton into a frame-axis
    # diagnostic. Display follows the reliable automatic model independently.
    display_bind = prepared.frame_variation > 0.01
    display_geometry = prepared.bind_geometry if display_bind else prepared.attachment_geometry
    short_ends = prepared.short_ends if display_bind else prepared.attachment_short_ends
    levels, terminal = [0] * len(prepared.names), [False] * len(prepared.names)
    ambiguous = [g.ambiguous for g in geometry]
    equivalent = [False] * len(levels)
    basal = [False] * len(levels)
    fork_alignment, chain_alignment = cos(radians(settings.fork_angle)), cos(radians(settings.chain_angle))
    tolerance = prepared.tolerance
    for i in prepared.traversal:
        kids = prepared.children[i]
        if not kids:
            continue
        g = geometry[i]
        compact, planarity, plane_distance = prepared.root_geometry[i]
        if settings.independent_stems and prepared.parents[i] < 0 and len(kids) >= 2 and (
            (compact < settings.basal_distance and prepared.mass_ratios[i] >= settings.basal_balance)
            or (len(kids) >= 3 and planarity > settings.basal_planarity and plane_distance < settings.basal_distance)
        ):
            basal[i] = True
            for c in kids:
                levels[c] = levels[i]
            continue
        if len(kids) == 1:
            child = kids[0]
            birth = not terminal[i] and directional and g.alignments[0] < chain_alignment
            levels[child] = levels[i] + int(birth)
            terminal[child] = settings.preserve_terminal and (terminal[i] or (birth and prepared.fork_counts[child] == 0))
            continue
        distal = max(0.0, g.distal_length * settings.distal_fraction)
        equivalent[i] = (
            prepared.mass_ratios[i] >= settings.equivalent_size
            and prepared.length_ratios[i] >= settings.equivalent_length
            and (g.ambiguous or g.angle_span <= settings.equivalent_angle)
            and (g.ambiguous or min(g.projections) + tolerance >= distal)
        )
        if equivalent[i] and settings.equivalent_forks != "continuation":
            birth = settings.equivalent_forks == "advance"
            for c in kids:
                levels[c] = levels[i] + int(birth)
                terminal[c] = settings.preserve_terminal and (terminal[i] or (birth and prepared.fork_counts[c] == 0))
            continue
        candidates = [k for k in range(len(kids)) if g.alignments[k] >= fork_alignment and g.projections[k] + tolerance >= distal]
        if g.ambiguous or (not directional and all(not prepared.children[c] for c in kids)):
            candidates = []
        if levels[i] > 0:
            structured = [k for k in candidates if prepared.fork_counts[kids[k]] > 0] if settings.prefer_branched else []
            candidates = structured or [k for k in candidates if g.alignments[k] >= chain_alignment]
        continuation = None
        if candidates:
            continuation = max(candidates, key=lambda k: (g.alignments[k], g.projections[k]))
            if any(k != continuation and abs(g.alignments[k] - g.alignments[continuation]) <= 1e-5
                   and abs(g.projections[k] - g.projections[continuation]) <= tolerance for k in candidates):
                ambiguous[i] = True
                continuation = None
        for k, c in enumerate(kids):
            birth = k != continuation
            levels[c] = levels[i] + int(birth)
            terminal[c] = settings.preserve_terminal and (terminal[i] or (birth and prepared.fork_counts[c] == 0))
    return tuple(TreeHierarchyJoint(name, levels[i], short_ends[i] if display_geometry[i].ambiguous or basal[i] else display_geometry[i].display_end, ambiguous[i], equivalent[i])
                 for i, name in enumerate(prepared.names))


def analyze_tree_hierarchy(skeleton: tuple[Joint, ...], settings: TreeHierarchySettings = TreeHierarchySettings()) -> tuple[TreeHierarchyJoint, ...]:
    """Batch convenience entry point; the UI retains the prepared rig."""
    return classify_tree_hierarchy(prepare_tree_hierarchy(skeleton), settings)
