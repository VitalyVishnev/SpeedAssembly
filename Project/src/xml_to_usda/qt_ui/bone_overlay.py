"""Vectorized bone projection and sparse, true-crossing shadow events.

Visibility belongs to the GPU depth buffer. CPU work here never clips one bone
against another, and adjacent joints/end contacts do not create shadows.
"""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np

MAX_BONE_SHADOWS = 8
NO_BONE_SHADOW = -1e20


@dataclass(frozen=True, slots=True)
class ProjectedBones:
    indices: np.ndarray
    points: np.ndarray
    start_t: np.ndarray
    end_t: np.ndarray


def project_bones(points: np.ndarray, matrix: np.ndarray, width: int, height: int) -> ProjectedBones:
    """Clip/project every endpoint in NumPy, without per-bone Qt matrix calls."""
    homogeneous = np.ones((*points.shape[:2], 4), dtype=np.float64)
    homogeneous[..., :3] = points
    clip = homogeneous @ matrix.T
    a, b = clip[:, 0], clip[:, 1]
    p0 = np.concatenate((a[:, 3:4] + a[:, :3], a[:, 3:4] - a[:, :3]), axis=1)
    p1 = np.concatenate((b[:, 3:4] + b[:, :3], b[:, 3:4] - b[:, :3]), axis=1)
    active = np.isfinite(clip).all(axis=(1, 2)) & ~((p0 < 0) & (p1 < 0)).any(axis=1)
    crossing = np.zeros_like(p0)
    np.divide(p0, p0 - p1, out=crossing, where=(p0 - p1) != 0)
    lo = np.maximum(0, np.max(np.where(p0 < 0, crossing, 0), axis=1))
    hi = np.minimum(1, np.min(np.where(p1 < 0, crossing, 1), axis=1))
    first, last = a + (b - a) * lo[:, None], a + (b - a) * hi[:, None]
    active &= (lo <= hi) & (first[:, 3] > 1e-8) & (last[:, 3] > 1e-8)
    indices = np.flatnonzero(active)
    clipped = np.stack((first[indices], last[indices]), axis=1)
    ndc = clipped[..., :3] / clipped[..., 3:4]
    ndc[..., 0] = (ndc[..., 0] + 1) * width * .5
    ndc[..., 1] = (1 - ndc[..., 1]) * height * .5
    return ProjectedBones(indices, ndc, lo[indices], hi[indices])


def bone_shadow_centers(points: np.ndarray, connections: np.ndarray) -> np.ndarray:
    """Up to eight nearer crossing shadows per bone, measured along its line.

    Sweep bounds, vectorize all candidate intersections once, then keep nearest
    foreground crossings. No shadow from mere proximity, parallel projections,
    connected consecutive bones, touching endpoints, or equal 3D depth.
    """
    count = len(points)
    centers = np.full((count, MAX_BONE_SHADOWS), NO_BONE_SHADOW, dtype=np.float32)
    if count < 2:
        return centers
    low, high = np.minimum(points[:, 0, :2], points[:, 1, :2]), np.maximum(points[:, 0, :2], points[:, 1, :2])
    order = np.argsort(low[:, 0], kind="stable")
    sorted_x = low[order, 0]
    stops = np.searchsorted(sorted_x, high[order, 0], side="right")
    aa, bb = [], []
    # Expand sweep intervals in small vectorized blocks, instead of thousands
    # of Python/NumPy calls per frame. Temporary memory is bounded by 64 rows.
    for first in range(0, count, 64):
        rows = np.arange(first, min(first + 64, count))
        sizes = np.maximum(stops[rows] - rows - 1, 0)
        starts = np.cumsum(sizes) - sizes
        row = np.repeat(rows, sizes)
        column = row + 1 + np.arange(int(sizes.sum())) - np.repeat(starts, sizes)
        a, b = order[row], order[column]
        take = (low[a, 1] <= high[b, 1]) & (high[a, 1] >= low[b, 1])
        if take.any():
            aa.append(a[take])
            bb.append(b[take])
    if not aa:
        return centers
    a, b = np.concatenate(aa), np.concatenate(bb)
    da = points[a, 1, :2] - points[a, 0, :2]
    db = points[b, 1, :2] - points[b, 0, :2]
    offset = points[b, 0, :2] - points[a, 0, :2]
    determinant = da[:, 0] * db[:, 1] - da[:, 1] * db[:, 0]
    t, u = np.zeros(len(a)), np.zeros(len(a))
    np.divide(offset[:, 0] * db[:, 1] - offset[:, 1] * db[:, 0], determinant, out=t, where=abs(determinant) > 1e-8)
    np.divide(offset[:, 0] * da[:, 1] - offset[:, 1] * da[:, 0], determinant, out=u, where=abs(determinant) > 1e-8)
    adjacent = ((connections[a, 0] >= 0) & (connections[a, 0] == connections[b, 1])) | ((connections[b, 0] >= 0) & (connections[b, 0] == connections[a, 1]))
    za = points[a, 0, 2] + (points[a, 1, 2] - points[a, 0, 2]) * t
    zb = points[b, 0, 2] + (points[b, 1, 2] - points[b, 0, 2]) * u
    valid = (abs(determinant) > 1e-8) & (t > 1e-4) & (t < 1 - 1e-4) & (u > 1e-4) & (u < 1 - 1e-4) & ~adjacent & (abs(za - zb) > 1e-7)
    a, b, t, u, za, zb = (values[valid] for values in (a, b, t, u, za, zb))
    rear = np.where(za > zb, a, b)
    lengths = np.linalg.norm(points[:, 1, :2] - points[:, 0, :2], axis=1)
    center = np.where(za > zb, t * lengths[a], u * lengths[b])
    sort = np.lexsort((np.minimum(za, zb), rear))
    rear, center = rear[sort], center[sort]
    if rear.size:
        starts = np.maximum.accumulate(np.where(np.r_[True, rear[1:] != rear[:-1]], np.arange(len(rear)), 0))
        slot = np.arange(len(rear)) - starts
        take = slot < MAX_BONE_SHADOWS
        centers[rear[take], slot[take]] = center[take]
    return centers


def bone_quad_vertices(points, widths, colors, shadows, width, height):
    """Six screen-aligned triangle vertices per bone, with opaque RGB colors."""
    count = len(points)
    if not count:
        return np.empty((0, 20), dtype=np.float32)
    delta = points[:, 1, :2] - points[:, 0, :2]
    lengths = np.linalg.norm(delta, axis=1)
    direction = np.zeros_like(delta)
    np.divide(delta, lengths[:, None], out=direction, where=lengths[:, None] > 1e-8)
    direction[lengths <= 1e-8] = (1, 0)
    perpendicular = np.stack((-direction[:, 1], direction[:, 0]), axis=1)
    half = widths * .5
    endpoint = np.asarray((0, 1, 1, 0, 1, 0))
    side = np.asarray((-1, -1, 1, -1, 1, 1))
    along = np.where(endpoint[None, :] == 0, -half[:, None], lengths[:, None] + half[:, None])
    xy = points[:, 0, None, :2] + direction[:, None, :] * along[..., None] + perpendicular[:, None, :] * (half[:, None] * side)[..., None]
    vertices = np.empty((count, 6, 20), dtype=np.float32)
    vertices[..., 0] = xy[..., 0] / max(1, width) * 2 - 1
    vertices[..., 1] = 1 - xy[..., 1] / max(1, height) * 2
    vertices[..., 2] = np.where(endpoint[None, :] == 0, points[:, 0, 2:3], points[:, 1, 2:3])
    vertices[..., 3:6] = colors[:, None, :]
    vertices[..., 6] = along
    vertices[..., 7] = half[:, None] * side
    vertices[..., 8] = lengths[:, None]
    vertices[..., 9] = half[:, None]
    vertices[..., 10:12] = points[:, None, :, 2]
    vertices[..., 12:20] = shadows[:, None, :]
    return vertices.reshape((-1, 20))
