from __future__ import annotations

import math

import pytest

from xml_to_usda.models import ExportMetadata, Joint, Matrix4d, MeshData, TreeAsset, Vector3
from xml_to_usda.proxy_collision import ProxyCollisionSettings, build_proxy_collision_meshes


def _curved_trunk() -> TreeAsset:
    skeleton = (
        Joint(
            name="root",
            generator_level=0,
            bind_transform=Matrix4d.from_translation(Vector3(0.0, 0.0, 0.0)),
            bind_end_transform=Matrix4d.from_translation(Vector3(0.0, 2.0, 0.0)),
        ),
        Joint(
            name="mid",
            parent="root",
            generator_level=0,
            bind_transform=Matrix4d.from_translation(Vector3(0.0, 2.0, 0.0)),
            bind_end_transform=Matrix4d.from_translation(Vector3(2.0, 4.0, 0.0)),
        ),
        Joint(
            name="top",
            parent="mid",
            generator_level=0,
            bind_transform=Matrix4d.from_translation(Vector3(2.0, 4.0, 0.0)),
            bind_end_transform=Matrix4d.from_translation(Vector3(4.0, 5.0, 0.0)),
        ),
    )
    mesh = MeshData(
        name="TreeBaseMesh",
        points=(
            Vector3(-0.5, 0.0, -0.5),
            Vector3(0.5, 0.0, 0.5),
            Vector3(-0.5, 2.0, -0.5),
            Vector3(0.5, 2.0, 0.5),
            Vector3(1.5, 4.0, -0.5),
            Vector3(2.5, 4.0, 0.5),
        ),
        face_vertex_counts=(3, 3),
        face_vertex_indices=(0, 1, 2, 3, 4, 5),
        skel_joint_indices=(0, 0, 1, 1, 2, 2),
        skel_joint_weights=(1.0,) * 6,
        skel_element_size=1,
    )
    return TreeAsset(
        metadata=ExportMetadata(source_path="curved.xml", source_version=None),
        materials=(),
        source_objects=(),
        base_mesh=mesh,
        skeleton=skeleton,
        assembly_parts=(),
    )


def test_curved_trunk_box_uses_fitted_axis_height_and_width_multipliers() -> None:
    model = _curved_trunk()
    half = build_proxy_collision_meshes(model, ProxyCollisionSettings(height_multiplier=0.5))[0]
    full = build_proxy_collision_meshes(model, ProxyCollisionSettings(height_multiplier=1.0))[0]
    wide = build_proxy_collision_meshes(
        model,
        ProxyCollisionSettings(height_multiplier=0.5, width_multiplier=2.0),
    )[0]

    half_axis = _box_axis(half)
    full_axis = _box_axis(full)
    assert half_axis.x > 0.1  # PCA follows the bend instead of keeping the first bone's vertical direction.
    assert _length(half_axis) == pytest.approx(_skeleton_length(model.skeleton) * 0.5)
    assert _length(full_axis) == pytest.approx(_skeleton_length(model.skeleton))
    assert _distance(wide.points[0], wide.points[1]) == pytest.approx(_distance(half.points[0], half.points[1]) * 2.0)


def _box_axis(mesh: MeshData) -> Vector3:
    start = _average(mesh.points[:4])
    end = _average(mesh.points[4:])
    return Vector3(end.x - start.x, end.y - start.y, end.z - start.z)


def _average(points: tuple[Vector3, ...]) -> Vector3:
    return Vector3(
        sum(point.x for point in points) / len(points),
        sum(point.y for point in points) / len(points),
        sum(point.z for point in points) / len(points),
    )


def _skeleton_length(skeleton: tuple[Joint, ...]) -> float:
    points = tuple(joint.bind_translate for joint in skeleton) + (skeleton[-1].bind_end_translate,)
    assert points[-1] is not None
    return sum(_distance(points[index], points[index + 1]) for index in range(len(points) - 1))  # type: ignore[arg-type]


def _distance(a: Vector3, b: Vector3) -> float:
    return _length(Vector3(a.x - b.x, a.y - b.y, a.z - b.z))


def _length(value: Vector3) -> float:
    return math.sqrt(value.x * value.x + value.y * value.y + value.z * value.z)
