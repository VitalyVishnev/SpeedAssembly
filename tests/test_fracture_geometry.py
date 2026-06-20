from __future__ import annotations

from types import SimpleNamespace

import pytest

from xml_to_usda.fracture_geometry import slice_mesh_faces
from xml_to_usda.fracture_service import FractureError
from xml_to_usda.models import MeshData, MeshSection, Vector3


def test_slice_mesh_faces_can_generate_deterministic_boundary_fan_caps() -> None:
    mesh = MeshData(
        name="Base",
        points=(
            Vector3(0.0, 0.0, 0.0),
            Vector3(1.0, 0.0, 0.0),
            Vector3(1.0, 1.0, 0.0),
            Vector3(0.0, 1.0, 0.0),
        ),
        face_vertex_counts=(3, 3),
        face_vertex_indices=(0, 1, 2, 0, 2, 3),
        sections=(MeshSection(material_id=7, face_indices=(0, 1)),),
    )

    sliced = slice_mesh_faces(mesh, (0,), name="Piece", generate_caps=True)

    assert sliced.face_vertex_counts == (3, 3)
    assert len(sliced.points) == 4
    assert sliced.points[3] == Vector3(0.5, 0.5, 0.0)
    assert sliced.face_vertex_indices == (0, 1, 2, 0, 2, 3)
    assert tuple(section.material_id for section in sliced.sections) == (7, 7)
    assert tuple(section.face_indices for section in sliced.sections) == ((0,), (1,))


def test_slice_mesh_faces_can_assign_caps_to_override_material() -> None:
    mesh = MeshData(
        name="Base",
        points=(
            Vector3(0.0, 0.0, 0.0),
            Vector3(1.0, 0.0, 0.0),
            Vector3(1.0, 1.0, 0.0),
            Vector3(0.0, 1.0, 0.0),
        ),
        face_vertex_counts=(3, 3),
        face_vertex_indices=(0, 1, 2, 0, 2, 3),
        sections=(MeshSection(material_id=7, face_indices=(0, 1)),),
    )

    sliced = slice_mesh_faces(mesh, (0,), name="Piece", generate_caps=True, cap_material_id=42)

    assert tuple(section.material_id for section in sliced.sections) == (7, 42)
    assert tuple(section.face_indices for section in sliced.sections) == ((0,), (1,))


def test_slice_mesh_faces_leaves_piece_open_when_caps_are_disabled() -> None:
    mesh = MeshData(
        name="Base",
        points=(
            Vector3(0.0, 0.0, 0.0),
            Vector3(1.0, 0.0, 0.0),
            Vector3(1.0, 1.0, 0.0),
            Vector3(0.0, 1.0, 0.0),
        ),
        face_vertex_counts=(3, 3),
        face_vertex_indices=(0, 1, 2, 0, 2, 3),
        sections=(MeshSection(material_id=7, face_indices=(0, 1)),),
    )

    sliced = slice_mesh_faces(mesh, (0,), name="Piece", generate_caps=False)

    assert sliced.face_vertex_counts == (3,)
    assert len(sliced.points) == 3
    assert tuple(section.face_indices for section in sliced.sections) == ((0,),)


def test_slice_mesh_faces_fails_loudly_when_mesh_indices_are_scalar() -> None:
    mesh = SimpleNamespace(
        name="CorruptBase",
        points=(Vector3(0.0, 0.0, 0.0),),
        face_vertex_counts=(3,),
        face_vertex_indices=0,
        uv_coords=(),
        secondary_uv_coords=(),
        vertex_colors=(),
        sections=(),
        skel_element_size=0,
        skel_joint_indices=(),
        skel_joint_weights=(),
    )

    with pytest.raises(FractureError, match="CorruptBase face_vertex_indices must be a sequence, got int"):
        slice_mesh_faces(mesh, (0,), name="Piece")
