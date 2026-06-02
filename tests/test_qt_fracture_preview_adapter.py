from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

pytestmark = pytest.mark.qt

from xml_to_usda.fracture_preview_service import FracturePreviewSettings, generate_fracture_preview
from xml_to_usda.fracture_service import FractureSettings
from xml_to_usda.models import (
    ExportMetadata,
    InstanceBinding,
    Joint,
    Matrix4d,
    MeshData,
    Prototype,
    PrototypeIdentity,
    Quaternion,
    RepeatedPartInstance,
    TreeAsset,
    Vector3,
)
from xml_to_usda.qt_ui.fracture_preview import FRACTURE_VERTEX_STRIDE, FractureViewport, build_fracture_viewport_mesh


def _joint(name: str, source_id: int, parent: str | None, y: float, group: int) -> Joint:
    return Joint(
        name=name,
        source_id=source_id,
        parent=parent,
        generator_label=f"Group_{group}",
        generator_level=group,
        bind_transform=Matrix4d.from_translation(Vector3(0.0, y, 0.0)),
        rest_transform=Matrix4d.from_translation(Vector3(0.0, y, 0.0)),
    )


def _strip_mesh(name: str, joint_indices: tuple[int, ...]) -> MeshData:
    points: list[Vector3] = []
    face_vertex_counts: list[int] = []
    face_vertex_indices: list[int] = []
    skel_joint_indices: list[int] = []
    for face_index, joint_index in enumerate(joint_indices):
        first_point = len(points)
        x = float(face_index)
        points.extend(
            (
                Vector3(x, 0.0, 0.0),
                Vector3(x + 0.4, 0.0, 0.0),
                Vector3(x, 0.4, 0.0),
            )
        )
        face_vertex_counts.append(3)
        face_vertex_indices.extend((first_point, first_point + 1, first_point + 2))
        skel_joint_indices.extend((joint_index, joint_index, joint_index))
    return MeshData(
        name=name,
        points=tuple(points),
        face_vertex_counts=tuple(face_vertex_counts),
        face_vertex_indices=tuple(face_vertex_indices),
        skel_joint_indices=tuple(skel_joint_indices),
        skel_joint_weights=(1.0,) * len(skel_joint_indices),
        skel_element_size=1,
    )


def _repeated_part(name: str, joint_token: str, x: float) -> RepeatedPartInstance:
    return RepeatedPartInstance(
        name=name,
        prototype_key="Mesh_1",
        position=Vector3(x, 0.0, 0.0),
        orientation=Quaternion(1.0, 0.0, 0.0, 0.0),
        scale=Vector3(1.0, 1.0, 1.0),
        binding=InstanceBinding(joint_tokens=(joint_token,), weights=(1.0,)),
        source_object_id=None,
        source_mesh_id=1,
    )


def _tree() -> TreeAsset:
    return TreeAsset(
        metadata=ExportMetadata(source_path="tree.xml", source_version=None),
        materials=(),
        source_objects=(),
        base_mesh=_strip_mesh("Base", (0, 1, 2, 3, 4)),
        skeleton=(
            _joint("root", 0, None, 0.0, 0),
            _joint("bone_001", 1, "root", 1.0, 0),
            _joint("bone_002", 2, "bone_001", 2.0, 0),
            _joint("bone_003", 3, "bone_001", 1.4, 1),
            _joint("bone_004", 4, "bone_003", 1.8, 2),
        ),
        assembly_parts=(
            _repeated_part("TopLeaves", "bone_002", 10.0),
            _repeated_part("BranchLeaves", "bone_004", 20.0),
        ),
        prototypes=(
            Prototype(
                identity=PrototypeIdentity(source_key="Mesh_1", prim_name="LeafCluster"),
                mesh=_strip_mesh("LeafCluster", (0, 0, 0)),
                source_key="Mesh_1",
                source_mesh_id=1,
                source_name="LeafCluster",
            ),
        ),
    )


def test_fracture_viewport_payload_triangulates_base_and_instanced_preview_geometry_with_piece_colors() -> None:
    preview = generate_fracture_preview(
        _tree(),
        FracturePreviewSettings(
            fracture=FractureSettings(target_piece_count=3, output_stem="Oak"),
            max_base_faces_per_piece=1,
            max_prototype_faces=1,
        ),
    )

    mesh = build_fracture_viewport_mesh(preview)

    assert mesh.name == "Oak_fracture_preview"
    assert mesh.triangle_count == 5
    assert mesh.piece_count == 3
    assert mesh.instance_count == 2
    assert len(mesh.vertex_components) == mesh.triangle_count * 3 * FRACTURE_VERTEX_STRIDE

    first_vertex = tuple(mesh.vertex_components[:FRACTURE_VERTEX_STRIDE])
    assert first_vertex[6:10] == pytest.approx(
        (
            preview.pieces[0].color.r,
            preview.pieces[0].color.g,
            preview.pieces[0].color.b,
            preview.pieces[0].color.a,
        )
    )

    instance_vertex_offset = 3 * 3 * FRACTURE_VERTEX_STRIDE
    first_instance_vertex = tuple(mesh.vertex_components[instance_vertex_offset:instance_vertex_offset + FRACTURE_VERTEX_STRIDE])
    assert first_instance_vertex[0] >= 10.0
    assert first_instance_vertex[6:10] == pytest.approx(
        (
            preview.pieces[1].color.r,
            preview.pieces[1].color.g,
            preview.pieces[1].color.b,
            preview.pieces[1].color.a,
        )
    )


def test_fracture_viewport_accepts_colored_triangle_payload_and_frames_camera(qtbot) -> None:
    preview = generate_fracture_preview(
        _tree(),
        FracturePreviewSettings(
            fracture=FractureSettings(target_piece_count=3, output_stem="Oak"),
            max_base_faces_per_piece=1,
            max_prototype_faces=1,
        ),
    )
    mesh = build_fracture_viewport_mesh(preview)

    viewport = FractureViewport()
    qtbot.addWidget(viewport)
    viewport.set_mesh(mesh)

    assert viewport.has_mesh()
    assert viewport.vertex_count == mesh.triangle_count * 3
    assert viewport.grid_vertex_count > 0
    assert 0.0 < viewport.matcap_tint_strength <= 0.35
    assert viewport.camera_radius > 0.0
    assert viewport.camera_distance == pytest.approx(viewport.camera_radius * 3.0)


def test_fracture_viewport_releases_gl_resources_with_current_context(qtbot, monkeypatch) -> None:
    class _Buffer:
        def __init__(self, name: str) -> None:
            self.name = name

        def destroy(self) -> None:
            calls.append(f"{self.name}.destroy")

    class _Program:
        def __init__(self, name: str) -> None:
            self.name = name

        def release(self) -> None:
            calls.append(f"{self.name}.release")

        def removeAllShaders(self) -> None:
            calls.append(f"{self.name}.removeAllShaders")

    calls: list[str] = []
    viewport = FractureViewport()
    qtbot.addWidget(viewport)
    monkeypatch.setattr(viewport, "isValid", lambda: True)
    monkeypatch.setattr(viewport, "makeCurrent", lambda: calls.append("makeCurrent"))
    monkeypatch.setattr(viewport, "doneCurrent", lambda: calls.append("doneCurrent"))
    viewport._program = _Program("mesh_program")
    viewport._grid_program = _Program("grid_program")
    viewport._vertex_buffer = _Buffer("mesh_buffer")
    viewport._grid_buffer = _Buffer("grid_buffer")
    viewport._vao = _Buffer("mesh_vao")
    viewport._grid_vao = _Buffer("grid_vao")

    viewport._release_gl_resources()
    viewport._release_gl_resources()

    assert calls == [
        "makeCurrent",
        "mesh_buffer.destroy",
        "grid_buffer.destroy",
        "mesh_vao.destroy",
        "grid_vao.destroy",
        "mesh_program.release",
        "mesh_program.removeAllShaders",
        "grid_program.release",
        "grid_program.removeAllShaders",
        "doneCurrent",
    ]
    assert viewport._program is None
    assert viewport._grid_program is None
    assert viewport._vertex_buffer is None
    assert viewport._grid_buffer is None
    assert viewport._vao is None
    assert viewport._grid_vao is None
