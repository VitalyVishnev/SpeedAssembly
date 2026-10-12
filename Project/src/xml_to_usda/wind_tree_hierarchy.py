"""Geometric tree branch analysis from bind poses and parent relationships.

Generator labels, joint names, source ordering and physical XML endpoints are
not classification signals. Calibration evidence lives in the Wind hierarchy
benchmark; the result is a proposal for the existing manual group stack.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, radians

import numpy as np

from .models import Joint, Vector3


_FORK_ALIGNMENT = cos(radians(45))
_CHAIN_ALIGNMENT = cos(radians(30))
_DISTAL_FRACTION = 0.95
_BASE_FRACTION = 0.1
_UNIFORM_FRAME_TOLERANCE = 0.01


@dataclass(frozen=True, slots=True)
class TreeHierarchyJoint:
    name: str
    branch_order: int
    display_end: Vector3
    ambiguous: bool = False


def analyze_tree_hierarchy(skeleton: tuple[Joint, ...]) -> tuple[TreeHierarchyJoint, ...]:
    """Return branch levels and display guides without changing the input rig."""
    if not skeleton:
        return ()
    index = {joint.name: i for i, joint in enumerate(skeleton)}
    if len(index) != len(skeleton):
        raise ValueError("wind_tree_duplicate_joint: joint names must be unique.")
    children: list[list[int]] = [[] for _ in skeleton]
    parents = []
    roots = []
    for i, joint in enumerate(skeleton):
        if joint.parent is not None and joint.parent not in index:
            raise ValueError(f"wind_tree_missing_parent: {joint.name} -> {joint.parent}.")
        parent = index[joint.parent] if joint.parent is not None else -1
        parents.append(parent)
        if parent < 0:
            roots.append(i)
        else:
            children[parent].append(i)
    traversal = []
    pending = list(roots)
    while pending:
        i = pending.pop()
        traversal.append(i)
        pending.extend(children[i])
    if len(traversal) != len(skeleton):
        raise ValueError("wind_tree_cyclic_hierarchy: joints are not reachable from roots.")

    positions = np.asarray([(j.bind_translate.x, j.bind_translate.y, j.bind_translate.z) for j in skeleton])
    axes = np.asarray([j.bind_transform.rows[0][:3] for j in skeleton], dtype=float)
    invalid = np.flatnonzero(~np.isfinite(positions).all(axis=1) | ~np.isfinite(axes).all(axis=1))
    if len(invalid):
        names = ", ".join(skeleton[i].name for i in invalid[:8])
        raise ValueError(f"wind_tree_invalid_pose: non-finite bind position/forward axis at {names}.")
    sizes = np.linalg.norm(axes, axis=1)
    if np.any(sizes == 0):
        names = ", ".join(skeleton[i].name for i in np.flatnonzero(sizes == 0)[:8])
        raise ValueError(f"wind_tree_invalid_pose: zero-length bind-pose forward axis at {names}.")
    axes /= sizes[:, None]
    # A centered bounding sphere is invariant under arbitrary rigid rotation;
    # an axis-aligned box diagonal is not.
    extent = float(2 * np.max(np.linalg.norm(positions - positions.mean(axis=0), axis=1)))
    if not np.isfinite(extent):
        raise ValueError("wind_tree_invalid_extent: bind positions exceed the numerical range.")
    if extent <= 1e-12 and len(skeleton) > 1:
        raise ValueError("wind_tree_no_spatial_extent: coincident joints do not describe a tree's branches.")
    tolerance = max(extent * 1e-5, 1e-12)
    ambiguous = [False] * len(skeleton)
    directional_frames = bool(np.max(np.linalg.norm(axes - axes.mean(axis=0), axis=1)) > _UNIFORM_FRAME_TOLERANCE)
    # Older USD exports have identical bone rotations. Their +X carries no
    # branch direction: estimate the outgoing segment from attachment points.
    if not directional_frames:
        for i in traversal:
            if children[i]:
                offsets = positions[children[i]] - positions[i]
                if np.linalg.norm(offsets) <= tolerance:
                    ambiguous[i] = True
                    continue
                values, vectors = np.linalg.eigh(offsets.T @ offsets)
                if values[-1] - values[-2] <= values[-1] * 1e-5:
                    ambiguous[i] = True
                    continue
                axis = vectors[:, -1]
                sign_reference = offsets.sum(axis=0)
                if np.dot(axis, sign_reference) < 0:
                    axis = -axis
                axes[i] = axis
            elif parents[i] >= 0:
                offset = positions[i] - positions[parents[i]]
                size = np.linalg.norm(offset)
                if size > 0:
                    axes[i] = offset / size

    fork_counts = [0] * len(skeleton)
    subtree_sizes = [1] * len(skeleton)
    for i in reversed(traversal):
        fork_counts[i] = int(len(children[i]) > 1) + sum(fork_counts[c] for c in children[i])
        subtree_sizes[i] += sum(subtree_sizes[c] for c in children[i])
    levels = [0] * len(skeleton)
    terminal_lines = [False] * len(skeleton)
    lengths = [0.0] * len(skeleton)

    for i in traversal:
        kids = children[i]
        if not kids:
            continue
        offsets = positions[kids] - positions[i]
        projections = offsets @ axes[i]
        lengths[i] = max(0.0, float(projections.max()))
        basal_roots = False
        if parents[i] < 0 and len(kids) >= 2:
            masses = [subtree_sizes[c] for c in kids]
            basal_roots = (
                max(np.linalg.norm(offset) for offset in offsets) < extent * _BASE_FRACTION
                and min(masses) >= max(masses) * 0.25
            )
            if not basal_roots and len(kids) >= 3:
                centered = offsets - offsets.mean(axis=0)
                values, vectors = np.linalg.eigh(centered.T @ centered)
                basal_roots = (
                    values[1] > values[2] * 0.1
                    and abs(float(np.dot(offsets.mean(axis=0), vectors[:, 0]))) < extent * _BASE_FRACTION
                )
        if basal_roots:
            lengths[i] = 0.0
            for child in kids:
                levels[child] = levels[i]
            continue
        if len(kids) == 1:
            child = kids[0]
            birth = (
                not terminal_lines[i] and directional_frames
                and float(np.dot(axes[i], axes[child])) < _CHAIN_ALIGNMENT
            )
            levels[child] = levels[i] + int(birth)
            terminal_lines[child] = terminal_lines[i] or (birth and fork_counts[child] == 0)
            continue

        alignments = {child: float(np.dot(axes[i], axes[child])) for child in kids}
        projection = dict(zip(kids, (float(value) for value in projections)))
        distal = max(0.0, lengths[i] * _DISTAL_FRACTION)
        candidates = [child for child in kids if alignments[child] >= _FORK_ALIGNMENT and projection[child] + tolerance >= distal]
        if ambiguous[i]:
            candidates = []
        if not directional_frames and all(not children[c] for c in kids):
            candidates = []
        if levels[i] > 0:
            continuing_structure = [c for c in candidates if fork_counts[c] > 0]
            candidates = continuing_structure or [c for c in candidates if alignments[c] >= _CHAIN_ALIGNMENT]
        continuation = None
        if candidates:
            continuation = max(candidates, key=lambda child: (alignments[child], projection[child]))
            competing = [c for c in candidates if c != continuation
                         and abs(alignments[c] - alignments[continuation]) <= 1e-5
                         and abs(projection[c] - projection[continuation]) <= tolerance]
            if competing:
                # Indistinguishable continuations start separate branches instead
                # of choosing one from names or incidental array order.
                ambiguous[i] = True
                continuation = None
        for child in kids:
            birth = child != continuation
            levels[child] = levels[i] + int(birth)
            terminal_lines[child] = terminal_lines[i] or (birth and fork_counts[child] == 0)

    result = []
    for i, joint in enumerate(skeleton):
        # These are display guides, not authored/reconstructed physical endpoints.
        # Terminal joints receive short direction markers so their groups remain visible.
        span = lengths[i] if lengths[i] > tolerance and not ambiguous[i] else extent * 0.015
        end = positions[i] + axes[i] * span
        display_end = joint.bind_end_translate or Vector3(float(end[0]), float(end[1]), float(end[2]))
        result.append(TreeHierarchyJoint(joint.name, levels[i], display_end, ambiguous[i]))
    return tuple(result)
