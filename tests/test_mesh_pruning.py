from __future__ import annotations

from xml_to_usda.mesh_pruning import select_large_connected_face_indices
from xml_to_usda.models import MeshData, Vector3


def _branchy_mesh_with_tiny_terminal_islands() -> MeshData:
    points: list[Vector3] = []
    face_counts: list[int] = []
    face_indices: list[int] = []

    def add_face(face_points: tuple[Vector3, ...]) -> None:
        point_offset = len(points)
        points.extend(face_points)
        face_counts.append(len(face_points))
        face_indices.extend(range(point_offset, point_offset + len(face_points)))

    add_face(
        (
            Vector3(-2.0, 0.0, -1.0),
            Vector3(2.0, 0.0, -1.0),
            Vector3(2.0, 12.0, -1.0),
            Vector3(-2.0, 12.0, -1.0),
        ),
    )
    add_face(
        (
            Vector3(0.0, 8.0, -0.5),
            Vector3(8.0, 11.0, -0.5),
            Vector3(8.0, 12.0, -0.5),
            Vector3(0.0, 9.0, -0.5),
        ),
    )
    for index in range(80):
        x = 20.0 + index * 0.1
        add_face(
            (
                Vector3(x, 16.0, 0.0),
                Vector3(x + 0.02, 16.0, 0.0),
                Vector3(x, 16.02, 0.0),
            ),
        )

    return MeshData(
        name="BranchyBase",
        points=tuple(points),
        face_vertex_counts=tuple(face_counts),
        face_vertex_indices=tuple(face_indices),
    )


def _mesh_with_large_trunk_medium_branches_and_tiny_twigs() -> MeshData:
    points: list[Vector3] = []
    face_counts: list[int] = []
    face_indices: list[int] = []

    points.append(Vector3(0.0, 0.0, 0.0))
    for index in range(80):
        base = len(points)
        points.extend(
            (
                Vector3(float(index) * 0.1, 8.0, 0.0),
                Vector3(float(index) * 0.1 + 0.08, 8.0, 0.0),
            )
        )
        face_counts.append(3)
        face_indices.extend((0, base, base + 1))

    def add_face(face_points: tuple[Vector3, ...]) -> None:
        point_offset = len(points)
        points.extend(face_points)
        face_counts.append(len(face_points))
        face_indices.extend(range(point_offset, point_offset + len(face_points)))

    for index in range(10):
        x = 20.0 + index
        add_face(
            (
                Vector3(x, 10.0, 0.0),
                Vector3(x + 2.0, 10.0, 0.0),
                Vector3(x, 12.0, 0.0),
            ),
        )
    for index in range(80):
        x = 100.0 + index * 0.1
        add_face(
            (
                Vector3(x, 20.0, 0.0),
                Vector3(x + 0.02, 20.0, 0.0),
                Vector3(x, 20.02, 0.0),
            ),
        )

    return MeshData(
        name="LargeTrunkMediumBranchesTinyTwigs",
        points=tuple(points),
        face_vertex_counts=tuple(face_counts),
        face_vertex_indices=tuple(face_indices),
    )


def test_branch_pruning_keeps_large_islands_and_drops_tiny_terminal_islands() -> None:
    selected = select_large_connected_face_indices(
        _branchy_mesh_with_tiny_terminal_islands(),
        aggression=0.25,
    )

    assert selected is not None
    assert 0 in selected
    assert 1 in selected
    assert len(selected) == 61


def test_branch_pruning_aggression_controls_how_many_small_islands_survive() -> None:
    mesh = _branchy_mesh_with_tiny_terminal_islands()

    soft = select_large_connected_face_indices(mesh, aggression=0.01)
    hard = select_large_connected_face_indices(mesh, aggression=1.0)

    assert soft is not None
    assert hard is not None
    assert len(soft) > len(hard)
    assert len(soft) == 81
    assert len(hard) == 1


def test_soft_branch_pruning_keeps_medium_islands_after_large_trunk_exceeds_face_budget() -> None:
    mesh = _mesh_with_large_trunk_medium_branches_and_tiny_twigs()

    soft = select_large_connected_face_indices(mesh, aggression=0.01)
    hard = select_large_connected_face_indices(mesh, aggression=1.0)

    assert soft is not None
    assert hard is not None
    assert set(range(80, 90)).issubset(soft)
    assert len(set(range(80, 90)).intersection(hard)) == 0


def test_branch_pruning_can_be_disabled() -> None:
    assert select_large_connected_face_indices(
        _branchy_mesh_with_tiny_terminal_islands(),
        aggression=0.0,
    ) is None
