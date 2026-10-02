from array import array

import pytest

from xml_to_usda.fracture_geometry import build_fracture_geometry, slice_mesh_faces
from xml_to_usda.fracture_service import FractureError, FracturePiece, FracturePlan, FractureSettings
from xml_to_usda.models import CanonicalTreeModel, Color4, ExportMetadata, MeshData, MeshSection, Vector2, Vector3


def _two_triangle_mesh() -> MeshData:
    return MeshData(
        name="Base",
        points=(
            Vector3(0.0, 0.0, 0.0),
            Vector3(1.0, 0.0, 0.0),
            Vector3(1.0, 1.0, 0.0),
            Vector3(0.0, 1.0, 0.0),
        ),
        face_vertex_counts=(3, 3),
        face_vertex_indices=(0, 1, 2, 0, 2, 3),
        normals=(Vector3(0.0, 0.0, 1.0),) * 6,
        uv_coords=(
            Vector2(0.0, 0.0),
            Vector2(1.0, 0.0),
            Vector2(1.0, 1.0),
            Vector2(0.0, 0.0),
            Vector2(1.0, 1.0),
            Vector2(0.0, 1.0),
        ),
        vertex_colors=(Color4(1.0, 1.0, 1.0, 1.0),) * 6,
        sections=(MeshSection(material_id=7, face_indices=(0, 1)),),
        skel_joint_indices=(0, 0, 0, 0),
        skel_joint_weights=(1.0, 1.0, 1.0, 1.0),
        skel_element_size=1,
    )


def test_slice_mesh_faces_preserves_face_varying_attributes_and_skinning() -> None:
    result = slice_mesh_faces(_two_triangle_mesh(), (1,), name="Piece")

    assert result.face_vertex_counts == (3,)
    assert len(result.normals) == len(result.face_vertex_indices) == 3
    assert len(result.uv_coords) == 3
    assert len(result.vertex_colors) == 3
    assert len(result.skel_joint_indices) == len(result.points)
    assert result.sections == (MeshSection(material_id=7, face_indices=(0,)),)


def test_slice_mesh_faces_generates_deterministic_caps_with_override_material() -> None:
    mesh = _two_triangle_mesh()
    first = slice_mesh_faces(mesh, (0,), name="Piece", generate_caps=True, cap_material_id=99)
    second = slice_mesh_faces(mesh, (0,), name="Piece", generate_caps=True, cap_material_id=99)

    assert first == second
    assert len(first.face_vertex_counts) > 1
    assert len(first.normals) == len(first.face_vertex_indices)
    assert first.normals[:3] == mesh.normals[:3]
    assert any(section.material_id == 99 for section in first.sections)


def test_slice_mesh_faces_rejects_non_sequence_indices() -> None:
    mesh = _two_triangle_mesh()
    object.__setattr__(mesh, "face_vertex_indices", 1)

    with pytest.raises(FractureError, match="must be a sequence"):
        slice_mesh_faces(mesh, (0,), name="Broken")


def test_flat_geometry_keeps_planner_piece_membership() -> None:
    mesh = _two_triangle_mesh()
    pieces = (
        FracturePiece(0, "Tree_fracture_00", True, None, (), (0,), (), ()),
        FracturePiece(1, "Tree_fracture_01", False, "child", (), (1,), (3,), ("Leaf",)),
    )
    plan = FracturePlan(
        method="bone_hierarchy",
        requested_piece_count=1,
        actual_piece_count=2,
        output_stem="Tree",
        main_axis_joint_tokens=(),
        selected_cut_sites=(),
        rejected_cut_sites=(),
        pieces=pieces,
        diagnostics=(),
    )
    model = CanonicalTreeModel(
        metadata=ExportMetadata(source_path="fixture.xml", source_version=None),
        materials=(),
        source_objects=(),
        skeleton=(),
        assembly_parts=(),
        base_mesh=mesh,
    )

    result = build_fracture_geometry(
        model,
        plan,
        FractureSettings(target_piece_count=1, detailed_cuts_enabled=False, generate_caps=False),
    )

    assert tuple(piece.piece.repeated_part_indices for piece in result.pieces) == ((), (3,))
    assert tuple(len(piece.base_mesh.face_vertex_counts) for piece in result.pieces) == (1, 1)


def test_slice_mesh_faces_accepts_materialized_array_payloads() -> None:
    mesh = _two_triangle_mesh()
    object.__setattr__(mesh, "face_vertex_counts", array("i", mesh.face_vertex_counts))
    object.__setattr__(mesh, "face_vertex_indices", array("i", mesh.face_vertex_indices))

    result = slice_mesh_faces(mesh, (0,), name="ArrayPiece")

    assert result.face_vertex_counts == (3,)
