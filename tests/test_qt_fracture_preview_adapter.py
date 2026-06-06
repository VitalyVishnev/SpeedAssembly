from __future__ import annotations

from array import array
from dataclasses import replace

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

pytestmark = pytest.mark.qt

from xml_to_usda.fracture_preview_service import FracturePreviewSettings, generate_fracture_preview
from xml_to_usda.fracture_service import FRACTURE_METHOD_MANUAL_PINNED_BONES, FractureSettings
from xml_to_usda.fracture_preview_service import FracturePreviewBoneSegment
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
from xml_to_usda.qt_ui.fracture_preview import (
    FRACTURE_MATCAP_TINT_STRENGTH,
    FRACTURE_VERTEX_STRIDE,
    FracturePreviewDialog,
    FractureViewport,
    FractureViewportMesh,
    build_fracture_viewport_mesh,
)
from xml_to_usda.qt_ui.proxy_preview import _prepare_opaque_mesh_draw, _set_matcap_program_uniforms


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
    assert mesh.uploaded_triangle_count == 5
    assert mesh.piece_count == 3
    assert mesh.instance_count == 2
    assert len(mesh.vertex_components) == mesh.uploaded_triangle_count * 3 * FRACTURE_VERTEX_STRIDE
    assert len(mesh.draw_calls) == 5

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
    assert first_instance_vertex[0] < 10.0
    assert first_instance_vertex[6:10] == pytest.approx(
        (
            preview.pieces[1].color.r,
            preview.pieces[1].color.g,
            preview.pieces[1].color.b,
            preview.pieces[1].color.a,
        )
    )
    assert mesh.draw_calls[3].translate.x == pytest.approx(10.0)

    second_instance_source = mesh.draw_sources[mesh.draw_calls[4].source_index]
    second_instance_vertex_offset = second_instance_source.first_vertex * FRACTURE_VERTEX_STRIDE
    second_instance_vertex = tuple(
        mesh.vertex_components[second_instance_vertex_offset:second_instance_vertex_offset + FRACTURE_VERTEX_STRIDE]
    )
    assert second_instance_vertex[6:10] == pytest.approx(
        (
            preview.pieces[2].color.r,
            preview.pieces[2].color.g,
            preview.pieces[2].color.b,
            preview.pieces[2].color.a,
        )
    )
    assert mesh.draw_calls[4].translate.x == pytest.approx(20.0)


def test_fracture_viewport_payload_reuses_repeated_prototype_source_for_same_piece_instances() -> None:
    tree = _tree()
    preview = generate_fracture_preview(
        replace(
            tree,
            assembly_parts=(
                _repeated_part("TopLeavesA", "bone_002", 10.0),
                _repeated_part("TopLeavesB", "bone_002", 12.0),
                _repeated_part("TopLeavesC", "bone_002", 14.0),
            ),
        ),
        FracturePreviewSettings(
            fracture=FractureSettings(target_piece_count=2, output_stem="Oak"),
            max_base_faces_per_piece=1,
            max_prototype_faces=1,
        ),
    )

    mesh = build_fracture_viewport_mesh(preview)

    assert mesh.instance_count == 3
    assert mesh.triangle_count == 5
    assert mesh.uploaded_triangle_count == 3
    assert len(mesh.draw_sources) == 3
    assert len(mesh.draw_calls) == 5
    assert tuple(call.source_index for call in mesh.draw_calls[-3:]) == (2, 2, 2)
    assert tuple(call.translate.x for call in mesh.draw_calls[-3:]) == pytest.approx((10.0, 12.0, 14.0))


def test_fracture_viewport_payload_can_hide_repeated_parts_without_changing_plan() -> None:
    preview = generate_fracture_preview(
        _tree(),
        FracturePreviewSettings(
            fracture=FractureSettings(target_piece_count=3, output_stem="Oak"),
            max_base_faces_per_piece=1,
            max_prototype_faces=1,
        ),
    )

    full_mesh = build_fracture_viewport_mesh(preview)
    base_only_mesh = build_fracture_viewport_mesh(preview, include_repeated_parts=False)

    assert full_mesh.piece_count == base_only_mesh.piece_count == preview.plan.actual_piece_count
    assert full_mesh.instance_count == 2
    assert base_only_mesh.instance_count == 0
    assert len(base_only_mesh.draw_calls) == len(preview.pieces)
    assert base_only_mesh.triangle_count == sum(piece.base_mesh.face_count for piece in preview.pieces)
    assert preview.instances


def test_fracture_viewport_payload_keeps_bone_overlay_segments() -> None:
    preview = generate_fracture_preview(
        _tree(),
        FracturePreviewSettings(
            fracture=FractureSettings(target_piece_count=3, output_stem="Oak", pinned_cut_joint_tokens=("bone_003",)),
            max_base_faces_per_piece=1,
            max_prototype_faces=1,
        ),
    )

    mesh = build_fracture_viewport_mesh(preview)

    assert tuple((segment.parent_joint_token, segment.child_joint_token) for segment in mesh.bone_segments) == (
        ("root", "bone_001"),
        ("bone_001", "bone_002"),
        ("bone_001", "bone_003"),
        ("bone_003", "bone_004"),
    )
    assert tuple(segment.color for segment in mesh.bone_segments) == tuple(segment.color for segment in preview.bone_segments)


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
    assert tuple(viewport._fracture_render_payload.vertex_components[6:10]) == pytest.approx(
        (
            preview.pieces[0].color.r,
            preview.pieces[0].color.g,
            preview.pieces[0].color.b,
            FRACTURE_MATCAP_TINT_STRENGTH,
        )
    )
    first_instance_offset = 3 * 3 * FRACTURE_VERTEX_STRIDE
    assert tuple(
        viewport._fracture_render_payload.vertex_components[first_instance_offset + 6:first_instance_offset + 10]
    ) == pytest.approx(
        (
            preview.pieces[1].color.r,
            preview.pieces[1].color.g,
            preview.pieces[1].color.b,
            FRACTURE_MATCAP_TINT_STRENGTH,
        )
    )
    assert viewport.grid_vertex_count > 0
    assert 0.6 <= viewport.matcap_tint_strength <= 0.9
    assert viewport.camera_radius > 0.0
    assert viewport.camera_distance == pytest.approx(viewport.camera_radius * 3.0)


def test_fracture_preview_dialog_forces_bones_in_manual_mode_and_hides_repeated_parts(qtbot) -> None:
    preview = generate_fracture_preview(
        _tree(),
        FracturePreviewSettings(
            fracture=FractureSettings(
                method=FRACTURE_METHOD_MANUAL_PINNED_BONES,
                target_piece_count=3,
                output_stem="Oak",
                pinned_cut_joint_tokens=("bone_003",),
            ),
            max_base_faces_per_piece=1,
            max_prototype_faces=1,
        ),
    )
    dialog = FracturePreviewDialog(
        settings=FracturePreviewSettings(
            fracture=FractureSettings(
                method=FRACTURE_METHOD_MANUAL_PINNED_BONES,
                target_piece_count=3,
                pinned_cut_joint_tokens=("bone_003",),
            )
        ),
        preview=preview,
    )
    qtbot.addWidget(dialog)

    assert dialog.show_bones_check.isChecked()
    assert not dialog.show_bones_check.isEnabled()
    assert dialog.viewport.show_bones
    assert dialog.viewport_mesh.instance_count == 2

    dialog.hide_repeated_parts_check.setChecked(True)

    assert dialog.viewport_mesh.instance_count == 0
    assert dialog.current_preview is preview
    assert preview.instances


def test_fracture_preview_dialog_reset_cuts_clears_manual_session_tokens(qtbot) -> None:
    emitted: list[FracturePreviewSettings] = []
    settings = FracturePreviewSettings(
        fracture=FractureSettings(
            method=FRACTURE_METHOD_MANUAL_PINNED_BONES,
            target_piece_count=3,
            pinned_cut_joint_tokens=("bone_003",),
        )
    )
    dialog = FracturePreviewDialog(settings=settings, on_settings_changed=emitted.append)
    qtbot.addWidget(dialog)

    dialog.reset_cuts_button.click()

    assert emitted
    assert emitted[-1].fracture.pinned_cut_joint_tokens == ()


def test_fracture_viewport_ctrl_click_picks_nearest_bone_segment_deterministically(qtbot) -> None:
    mesh = FractureViewportMesh(
        name="bones",
        vertex_components=array("f"),
        triangle_count=0,
        uploaded_triangle_count=0,
        piece_count=0,
        instance_count=0,
        draw_sources=(),
        draw_calls=(),
        bone_segments=(
            FracturePreviewBoneSegment(
                parent_joint_token="root",
                child_joint_token="left",
                parent_position=Vector3(-0.75, 0.0, 0.0),
                child_position=Vector3(-0.75, 1.0, 0.0),
            ),
            FracturePreviewBoneSegment(
                parent_joint_token="root",
                child_joint_token="right",
                parent_position=Vector3(0.75, 0.0, 0.0),
                child_position=Vector3(0.75, 1.0, 0.0),
            ),
        ),
    )
    viewport = FractureViewport()
    qtbot.addWidget(viewport)
    viewport.resize(500, 400)
    viewport.set_mesh(mesh)
    viewport.set_show_bones(True)
    left_screen = viewport._project_point_to_screen(Vector3(-0.75, 0.5, 0.0))

    assert left_screen is not None
    assert viewport.pick_bone_segment_child_token(left_screen[0], left_screen[1]) == "left"


def test_fracture_viewport_show_bones_does_not_upload_overlay_over_grid(qtbot, monkeypatch) -> None:
    viewport = FractureViewport()
    qtbot.addWidget(viewport)
    calls: list[str] = []
    monkeypatch.setattr(viewport, "isValid", lambda: True)
    monkeypatch.setattr(viewport, "makeCurrent", lambda: calls.append("makeCurrent"))
    monkeypatch.setattr(viewport, "doneCurrent", lambda: calls.append("doneCurrent"))

    viewport.set_show_bones(True)
    viewport.set_show_bones(False)

    assert calls == []
    assert viewport.bone_vertex_count == 0


def test_fracture_viewport_piece_color_slider_updates_render_payload_without_regenerating_preview(qtbot, monkeypatch) -> None:
    preview = generate_fracture_preview(
        _tree(),
        FracturePreviewSettings(
            fracture=FractureSettings(target_piece_count=3, output_stem="Oak"),
            max_base_faces_per_piece=1,
            max_prototype_faces=1,
        ),
    )
    viewport = FractureViewport()
    qtbot.addWidget(viewport)
    calls: list[str] = []
    monkeypatch.setattr(viewport, "isValid", lambda: False)
    viewport.set_mesh(build_fracture_viewport_mesh(preview))

    viewport.set_matcap_tint_strength(0.24)

    assert viewport.matcap_tint_strength == pytest.approx(0.24)
    assert tuple(viewport._fracture_render_payload.vertex_components[6:10]) == pytest.approx(
        (
            preview.pieces[0].color.r,
            preview.pieces[0].color.g,
            preview.pieces[0].color.b,
            0.24,
        )
    )
    assert viewport._mesh_dirty
    assert calls == []


def test_matcap_uniforms_do_not_runtime_bind_piece_color_strength() -> None:
    class _Program:
        def __init__(self) -> None:
            self.calls = []

        def uniformLocation(self, name) -> int:
            self.calls.append(("uniformLocation", name))
            return 7

        def setUniformValue(self, name, value) -> None:
            self.calls.append((name, value))

    class _Functions:
        def __init__(self) -> None:
            self.calls = []

        def glUniform1f(self, location: int, value: float) -> None:
            self.calls.append((location, value))

    program = _Program()
    functions = _Functions()

    _set_matcap_program_uniforms(
        program,
        functions=functions,
        mvp="mvp",
        normal_matrix="normal",
        piece_tint_strength=0.78,
    )

    assert ("uniformLocation", "pieceTintStrength") not in program.calls
    assert ("mvp", "mvp") in program.calls
    assert ("normalMatrix", "normal") in program.calls
    assert functions.calls == []


def test_fracture_viewport_prepares_opaque_mesh_draw_after_blended_grid() -> None:
    class _Functions:
        def __init__(self) -> None:
            self.calls = []

        def glDisable(self, value: int) -> None:
            self.calls.append(("glDisable", value))

        def glEnable(self, value: int) -> None:
            self.calls.append(("glEnable", value))

        def glDepthMask(self, value: bool) -> None:
            self.calls.append(("glDepthMask", value))

    functions = _Functions()

    _prepare_opaque_mesh_draw(functions)

    assert functions.calls == [
        ("glDisable", 0x0BE2),
        ("glEnable", 0x0B71),
        ("glDepthMask", True),
    ]


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
