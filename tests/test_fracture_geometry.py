from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

import xml_to_usda.fracture_geometry as fracture_geometry
from xml_to_usda.fracture_geometry import (
    CutSurface,
    _Polygon,
    _Vertex,
    _cut_origin_and_normal,
    _raise_for_self_intersection,
    _resolve_safe_cut_surface,
    _split_polygon,
    build_fracture_geometry,
    slice_mesh_faces,
)
from xml_to_usda.fracture_service import (
    FractureCutSite,
    FractureError,
    FracturePiece,
    FracturePlan,
    FractureSettings,
)
from xml_to_usda.models import (
    Color4,
    ExportMetadata,
    InstanceBinding,
    Joint,
    Matrix4d,
    MeshData,
    MeshSection,
    Prototype,
    PrototypeIdentity,
    Quaternion,
    RepeatedPartInstance,
    Vector2,
    Vector3,
)


def test_auto_branch_cut_leaves_a_visible_child_branch_stub() -> None:
    parent = Joint(name="parent", bind_transform=Matrix4d.from_translation(Vector3(0.0, 0.0, 0.0)))
    child = Joint(
        name="child",
        parent="parent",
        bind_transform=Matrix4d.from_translation(Vector3(0.0, 1.0, 0.0)),
        bind_end_transform=Matrix4d.from_translation(Vector3(0.0, 11.0, 0.0)),
    )
    cut = FractureCutSite(
        joint_token="child",
        kind="joint",
        reason="auto_branch_length",
        parent_joint_token="parent",
        child_joint_token="child",
    )

    origin, normal = _cut_origin_and_normal(cut, parent, child)

    assert origin == Vector3(0.0, 4.0, 0.0)
    assert normal == Vector3(0.0, 1.0, 0.0)


def test_auto_branch_cut_moves_along_the_same_bone_when_the_first_cross_section_is_unsafe(monkeypatch) -> None:
    model, plan = _closed_cube_fracture_fixture()
    plan = replace(
        plan,
        selected_cut_sites=(replace(plan.selected_cut_sites[0], reason="auto_branch_length"),),
    )
    actual_resolver = fracture_geometry._resolve_safe_cut_surface
    attempted_origins: list[float] = []

    def reject_first_cross_section(surface, *args, **kwargs):
        attempted_origins.append(surface.origin.y)
        if len(attempted_origins) == 1:
            raise fracture_geometry._AutomaticCutGeometryError(surface.token, "unsafe first cross-section")
        return actual_resolver(surface, *args, **kwargs)

    monkeypatch.setattr(fracture_geometry, "_resolve_safe_cut_surface", reject_first_cross_section)

    result = build_fracture_geometry(model, plan, FractureSettings(target_piece_count=1, noisy_cut_intensity=0.0))

    assert attempted_origins[:2] == pytest.approx((0.28, 0.33))
    assert result.plan.selected_cut_sites == plan.selected_cut_sites
    assert any(issue.code == "fracture_auto_cut_shifted" for issue in result.plan.diagnostics)


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


def test_fracture_geometry_clips_closed_mesh_and_builds_opposed_exact_caps() -> None:
    model, plan = _closed_cube_fracture_fixture()
    settings = FractureSettings(
        target_piece_count=1,
        generate_caps=True,
        noisy_cut_enabled=True,
        noisy_cut_intensity=0.0,
    )

    result = build_fracture_geometry(model, plan, settings, cap_material_id=42)

    assert len(result.pieces) == 2
    assert len(result.cut_surfaces) == 1
    assert all(len(piece.base_mesh.face_vertex_counts) > 3 for piece in result.pieces)
    assert all(any(section.material_id == 42 for section in piece.base_mesh.sections) for piece in result.pieces)
    surface = result.cut_surfaces[0]
    cap_points = tuple(
        point
        for piece in result.pieces
        for point in piece.base_mesh.points
        if abs(surface.signed_distance(point)) <= 1e-7
    )
    assert len(cap_points) >= 8
    cap_normal_dots = tuple(_first_material_face_normal_dot(piece.base_mesh, 42, surface.normal) for piece in result.pieces)
    assert cap_normal_dots[0] > 0.99
    assert cap_normal_dots[1] < -0.99


def test_exact_cut_interpolates_face_varying_and_skinning_attributes() -> None:
    model, plan = _closed_cube_fracture_fixture()

    result = build_fracture_geometry(
        model,
        plan,
        FractureSettings(target_piece_count=1, noisy_cut_intensity=0.0),
    )

    for piece in result.pieces:
        mesh = piece.base_mesh
        assert len(mesh.uv_coords) == len(mesh.face_vertex_indices)
        assert len(mesh.secondary_uv_coords) == len(mesh.face_vertex_indices)
        assert len(mesh.vertex_colors) == len(mesh.face_vertex_indices)
        cut_point_indices = tuple(index for index, point in enumerate(mesh.points) if abs(point.y) <= 1e-7)
        assert cut_point_indices
        assert any(
            all(weight > 0.0 for weight in mesh.skel_joint_weights[index * 2 : index * 2 + 2])
            for index in cut_point_indices
        )
        assert any(color.r > 0.0 and color.b > 0.0 for color in mesh.vertex_colors)
        assert any(0.0 < uv.y < 1.0 for uv in mesh.uv_coords)


def test_noisy_fracture_geometry_is_deterministic_and_changes_the_cut_surface() -> None:
    model, plan = _closed_cube_fracture_fixture()
    flat = build_fracture_geometry(
        model,
        plan,
        FractureSettings(target_piece_count=1, noisy_cut_intensity=0.0),
    )
    settings = FractureSettings(target_piece_count=1, noisy_cut_intensity=0.8, noisy_cut_scale=0.5)

    first = build_fracture_geometry(model, plan, settings)
    second = build_fracture_geometry(model, plan, settings)

    assert first == second
    assert first.cut_surfaces[0].seed == second.cut_surfaces[0].seed
    assert first.pieces[0].base_mesh.points != flat.pieces[0].base_mesh.points
    surface = first.cut_surfaces[0]
    assert all(
        surface.signed_distance(
            Vector3(surface.origin.x + x, surface.origin.y, surface.origin.z + z)
        )
        <= 1e-8
        for x, z in ((-1.0, -1.0), (-0.5, 0.25), (0.0, 0.0), (0.75, -0.25), (1.0, 1.0))
    )


def test_disabled_noisy_cut_preserves_legacy_face_slicing_contract() -> None:
    model, plan = _closed_cube_fracture_fixture()
    settings = FractureSettings(
        target_piece_count=1,
        generate_caps=False,
        noisy_cut_enabled=False,
    )

    result = build_fracture_geometry(model, plan, settings)

    assert result.cut_surfaces == ()
    assert tuple(piece.base_mesh for piece in result.pieces) == tuple(
        slice_mesh_faces(
            model.base_mesh,
            piece.base_face_indices,
            name=f"{piece.name}_BaseMesh",
            generate_caps=False,
        )
        for piece in plan.pieces
    )


def test_multiple_exact_cuts_keep_stable_order_and_closed_caps() -> None:
    model, plan = _stacked_box_fracture_fixture()
    settings = FractureSettings(
        target_piece_count=2,
        generate_caps=True,
        noisy_cut_intensity=0.0,
    )

    first = build_fracture_geometry(model, plan, settings, cap_material_id=42)
    second = build_fracture_geometry(model, plan, settings, cap_material_id=42)

    assert first == second
    assert tuple(surface.token for surface in first.cut_surfaces) == ("root->child@0.500", "child->grand@0.500")
    assert len(first.pieces) == 3
    assert all(piece.base_mesh.face_vertex_counts for piece in first.pieces)
    assert all(any(section.material_id == 42 for section in piece.base_mesh.sections) for piece in first.pieces)


def test_noisy_cut_fails_loudly_when_one_edge_crosses_surface_more_than_once() -> None:
    surface = CutSurface(
        token="oscillating",
        parent_piece_index=0,
        child_piece_index=1,
        origin=Vector3(0.0, 0.0, 0.0),
        normal=Vector3(0.0, 1.0, 0.0),
        tangent=Vector3(1.0, 0.0, 0.0),
        bitangent=Vector3(0.0, 0.0, 1.0),
        radius=1.0,
        amplitude=1.0,
        wavelength=0.1,
        seed=1,
    )
    polygon = _Polygon(
        vertices=(
            _test_vertex(Vector3(-1.0, 0.0, 0.0)),
            _test_vertex(Vector3(1.0, 0.0, 0.0)),
            _test_vertex(Vector3(0.0, 2.0, 0.0)),
        ),
        material_id=0,
        source_face_index=17,
    )

    with pytest.raises(FractureError, match="source face 17 edge 0 more than once"):
        _split_polygon(polygon, surface)


def test_noisy_cut_attenuates_shape_without_changing_the_cut_site() -> None:
    surface = CutSurface(
        token="fixed-cut",
        parent_piece_index=0,
        child_piece_index=1,
        origin=Vector3(0.0, 0.0, 0.0),
        normal=Vector3(0.0, 1.0, 0.0),
        tangent=Vector3(1.0, 0.0, 0.0),
        bitangent=Vector3(0.0, 0.0, 1.0),
        radius=1.0,
        amplitude=1.0,
        wavelength=0.1,
        seed=1,
    )
    polygon = _Polygon(
        vertices=(
            _test_vertex(Vector3(-1.0, -0.2, 0.0)),
            _test_vertex(Vector3(1.0, 0.2, 0.0)),
            _test_vertex(Vector3(0.0, 2.0, 0.0)),
        ),
        material_id=0,
        source_face_index=17,
    )
    face_mins = np.zeros(18)
    face_maxs = np.zeros(18)
    face_mins[17] = -0.2
    face_maxs[17] = 2.0

    resolved, affected = _resolve_safe_cut_surface(
        surface,
        [polygon],
        {17},
        face_mins,
        face_maxs,
        generate_caps=False,
    )

    assert resolved.token == surface.token
    assert resolved.parent_piece_index == surface.parent_piece_index
    assert resolved.child_piece_index == surface.child_piece_index
    assert resolved.amplitude == 0.0
    assert affected == {17}


def test_fracture_geometry_rejects_zero_length_cut_bone() -> None:
    model, plan = _closed_cube_fracture_fixture()
    point = Vector3(0.0, 0.0, 0.0)
    transform = Matrix4d.from_translation(point)
    model.skeleton = (
        replace(model.skeleton[0], bind_transform=transform, rest_transform=transform),
        replace(
            model.skeleton[1],
            bind_transform=transform,
            rest_transform=transform,
            bind_end_transform=transform,
        ),
    )

    with pytest.raises(FractureError, match="zero-length skeleton edge"):
        build_fracture_geometry(model, plan, FractureSettings(target_piece_count=1))


def test_fracture_geometry_rejects_cut_without_mesh_intersection() -> None:
    model, plan = _closed_cube_fracture_fixture()
    model.skeleton = (
        model.skeleton[0],
        replace(
            model.skeleton[1],
            bind_transform=Matrix4d.from_translation(Vector3(0.0, 3.0, 0.0)),
            rest_transform=Matrix4d.from_translation(Vector3(0.0, 3.0, 0.0)),
            bind_end_transform=Matrix4d.from_translation(Vector3(0.0, 4.0, 0.0)),
        ),
    )

    with pytest.raises(FractureError, match="child has no non-degenerate Base Mesh intersection"):
        build_fracture_geometry(model, plan, FractureSettings(target_piece_count=1))


def test_fracture_geometry_rejects_open_cap_loop() -> None:
    model, plan = _closed_cube_fracture_fixture()
    mesh = model.base_mesh
    model.base_mesh = replace(
        mesh,
        face_vertex_counts=mesh.face_vertex_counts[:-1],
        face_vertex_indices=mesh.face_vertex_indices[:-4],
        uv_coords=mesh.uv_coords[:-4],
        secondary_uv_coords=mesh.secondary_uv_coords[:-4],
        vertex_colors=mesh.vertex_colors[:-4],
        sections=(MeshSection(material_id=7, face_indices=(0, 1, 2, 3, 4)),),
    )
    plan = replace(
        plan,
        pieces=(
            replace(plan.pieces[0], base_face_indices=(0, 2)),
            plan.pieces[1],
        ),
    )

    with pytest.raises(FractureError, match="open or non-manifold"):
        build_fracture_geometry(
            model,
            plan,
            FractureSettings(target_piece_count=1, generate_caps=True, noisy_cut_intensity=0.0),
        )


def test_fracture_geometry_keeps_repeated_part_with_its_skeleton_attachment_piece() -> None:
    model, plan = _closed_cube_fracture_fixture()
    prototype_mesh = MeshData(
        name="Leaf",
        points=(Vector3(-0.1, -0.1, -0.1), Vector3(0.1, 0.1, 0.1)),
        face_vertex_counts=(),
        face_vertex_indices=(),
    )
    model.prototypes = (
        Prototype(
            identity=PrototypeIdentity(source_key="Leaf", prim_name="Leaf"),
            mesh=prototype_mesh,
            source_key="Leaf",
            source_mesh_id=1,
            source_name="Leaf",
        ),
    )
    model.repeated_parts = (
        RepeatedPartInstance(
            name="CrossingLeaf",
            prototype_key="Leaf",
            position=Vector3(0.0, 0.0, 0.0),
            orientation=Quaternion(1.0, 0.0, 0.0, 0.0),
            scale=Vector3(1.0, 1.0, 1.0),
            binding=InstanceBinding(joint_tokens=("child",), weights=(1.0,)),
            source_object_id=None,
            source_mesh_id=1,
        ),
    )
    plan = replace(
        plan,
        pieces=(plan.pieces[0], replace(plan.pieces[1], repeated_part_indices=(0,), repeated_part_names=("CrossingLeaf",))),
    )

    result = build_fracture_geometry(model, plan, FractureSettings(target_piece_count=1, noisy_cut_intensity=0.0))

    assert result.pieces[0].piece.repeated_part_indices == ()
    assert result.pieces[1].piece.repeated_part_indices == (0,)


def test_self_intersecting_cap_boundary_fails_loudly() -> None:
    with pytest.raises(FractureError, match="self-intersecting"):
        _raise_for_self_intersection(((0.0, 0.0), (1.0, 1.0), (0.0, 1.0), (1.0, 0.0)), "bowtie")


def _closed_cube_fracture_fixture():
    points = (
        Vector3(-1.0, -1.0, -1.0),
        Vector3(1.0, -1.0, -1.0),
        Vector3(1.0, -1.0, 1.0),
        Vector3(-1.0, -1.0, 1.0),
        Vector3(-1.0, 1.0, -1.0),
        Vector3(1.0, 1.0, -1.0),
        Vector3(1.0, 1.0, 1.0),
        Vector3(-1.0, 1.0, 1.0),
    )
    faces = (
        (0, 3, 2, 1),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    )
    face_vertex_indices = tuple(index for face in faces for index in face)
    mesh = MeshData(
        name="Cube",
        points=points,
        face_vertex_counts=tuple(len(face) for face in faces),
        face_vertex_indices=face_vertex_indices,
        uv_coords=tuple(
            Vector2((points[index].x + 1.0) * 0.5, (points[index].y + 1.0) * 0.5)
            for index in face_vertex_indices
        ),
        secondary_uv_coords=tuple(
            Vector2((points[index].z + 1.0) * 0.5, (points[index].y + 1.0) * 0.5)
            for index in face_vertex_indices
        ),
        vertex_colors=tuple(
            Color4(1.0, 0.0, 0.0, 1.0) if points[index].y < 0.0 else Color4(0.0, 0.0, 1.0, 1.0)
            for index in face_vertex_indices
        ),
        sections=(MeshSection(material_id=7, face_indices=tuple(range(len(faces)))),),
        skel_joint_indices=tuple(
            joint
            for point in points
            for joint in ((0, 1) if point.y < 0.0 else (1, 0))
        ),
        skel_joint_weights=tuple(weight for _point in points for weight in (1.0, 0.0)),
        skel_element_size=2,
    )
    root = Joint(
        name="root",
        bind_transform=Matrix4d.from_translation(Vector3(0.0, -1.0, 0.0)),
        rest_transform=Matrix4d.from_translation(Vector3(0.0, -1.0, 0.0)),
    )
    child = Joint(
        name="child",
        parent="root",
        bind_transform=Matrix4d.from_translation(Vector3(0.0, -0.02, 0.0)),
        rest_transform=Matrix4d.from_translation(Vector3(0.0, -0.02, 0.0)),
        bind_end_transform=Matrix4d.from_translation(Vector3(0.0, 0.98, 0.0)),
    )
    pieces = (
        FracturePiece(0, "Cube_fracture_00", True, None, ("root",), (0, 2, 5), (), ()),
        FracturePiece(1, "Cube_fracture_01", False, "child", ("child",), (1, 3, 4), (), ()),
    )
    cut = FractureCutSite(
        joint_token="child",
        kind="joint",
        reason="manual_pinned",
        parent_joint_token="root",
        child_joint_token="child",
    )
    plan = FracturePlan(
        method="manual_fracturing",
        requested_piece_count=1,
        actual_piece_count=2,
        output_stem="Cube",
        main_axis_joint_tokens=("root", "child"),
        selected_cut_sites=(cut,),
        rejected_cut_sites=(),
        pieces=pieces,
    )
    model = SimpleNamespace(
        metadata=ExportMetadata(source_path="cube.xml", source_version=None),
        base_mesh=mesh,
        skeleton=(root, child),
        repeated_parts=(),
        prototypes=(),
    )
    return model, plan


def _stacked_box_fracture_fixture():
    levels = (-1.0, -0.25, 0.25, 1.0)
    ring = ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0))
    points = tuple(Vector3(x, y, z) for y in levels for x, z in ring)
    faces: list[tuple[int, ...]] = [(0, 3, 2, 1), (12, 13, 14, 15)]
    for level_index in range(3):
        lower = level_index * 4
        upper = (level_index + 1) * 4
        for side in range(4):
            following = (side + 1) % 4
            faces.append((lower + side, lower + following, upper + following, upper + side))
    face_indices = tuple(index for face in faces for index in face)
    point_joint_indices = (0,) * 4 + (1,) * 8 + (2,) * 4
    mesh = MeshData(
        name="StackedBox",
        points=points,
        face_vertex_counts=tuple(len(face) for face in faces),
        face_vertex_indices=face_indices,
        sections=(MeshSection(material_id=7, face_indices=tuple(range(len(faces)))),),
        skel_joint_indices=point_joint_indices,
        skel_joint_weights=(1.0,) * len(points),
        skel_element_size=1,
    )
    root = Joint(
        name="root",
        bind_transform=Matrix4d.from_translation(Vector3(0.0, -1.0, 0.0)),
        rest_transform=Matrix4d.from_translation(Vector3(0.0, -1.0, 0.0)),
    )
    child = Joint(
        name="child",
        parent="root",
        bind_transform=Matrix4d.from_translation(Vector3(0.0, 0.0, 0.0)),
        rest_transform=Matrix4d.from_translation(Vector3(0.0, 0.0, 0.0)),
    )
    grand = Joint(
        name="grand",
        parent="child",
        bind_transform=Matrix4d.from_translation(Vector3(0.0, 1.0, 0.0)),
        rest_transform=Matrix4d.from_translation(Vector3(0.0, 1.0, 0.0)),
    )
    cuts = (
        FractureCutSite("root->child@0.500", "manual_segment", "manual_pinned_segment", "root", "child", 0.5),
        FractureCutSite("child->grand@0.500", "manual_segment", "manual_pinned_segment", "child", "grand", 0.5),
    )
    pieces = (
        FracturePiece(0, "Stacked_fracture_00", True, None, ("root",), (0,), (), ()),
        FracturePiece(1, "Stacked_fracture_01", False, cuts[0].joint_token, ("child",), tuple(range(2, 10)), (), ()),
        FracturePiece(2, "Stacked_fracture_02", False, cuts[1].joint_token, ("grand",), (1, 10, 11, 12, 13), (), ()),
    )
    plan = FracturePlan(
        method="manual_fracturing",
        requested_piece_count=2,
        actual_piece_count=3,
        output_stem="Stacked",
        main_axis_joint_tokens=("root", "child", "grand"),
        selected_cut_sites=cuts,
        rejected_cut_sites=(),
        pieces=pieces,
    )
    model = SimpleNamespace(
        metadata=ExportMetadata(source_path="stacked.xml", source_version=None),
        base_mesh=mesh,
        skeleton=(root, child, grand),
        repeated_parts=(),
        prototypes=(),
    )
    return model, plan


def _test_vertex(point: Vector3) -> _Vertex:
    return _Vertex(point=point, uv=None, secondary_uv=None, color=None, joint_indices=(), joint_weights=())


def _first_material_face_normal_dot(mesh: MeshData, material_id: int, normal: Vector3) -> float:
    face_index = next(
        face_index
        for section in mesh.sections
        if section.material_id == material_id
        for face_index in section.face_indices
    )
    start = sum(mesh.face_vertex_counts[:face_index])
    indices = mesh.face_vertex_indices[start : start + mesh.face_vertex_counts[face_index]]
    a, b, c = (mesh.points[index] for index in indices[:3])
    ab = Vector3(b.x - a.x, b.y - a.y, b.z - a.z)
    ac = Vector3(c.x - a.x, c.y - a.y, c.z - a.z)
    cross = Vector3(
        ab.y * ac.z - ab.z * ac.y,
        ab.z * ac.x - ab.x * ac.z,
        ab.x * ac.y - ab.y * ac.x,
    )
    length = (cross.x * cross.x + cross.y * cross.y + cross.z * cross.z) ** 0.5
    return (cross.x * normal.x + cross.y * normal.y + cross.z * normal.z) / length
