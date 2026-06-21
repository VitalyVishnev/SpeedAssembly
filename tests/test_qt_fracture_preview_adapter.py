from __future__ import annotations

from array import array
from dataclasses import replace

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

pytestmark = pytest.mark.qt

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QScrollArea

from xml_to_usda.fracture_collision import FractureCollisionMode, FractureCollisionSettings
from xml_to_usda.fracture_preview_service import FracturePreviewSettings, generate_fracture_preview
from xml_to_usda.fracture_service import FractureSettings
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
    FRACTURE_SOURCE_VERTEX_STRIDE,
    FRACTURE_VERTEX_STRIDE,
    FracturePreviewDialog,
    FractureViewportMesh,
    apply_fracture_viewport_mesh,
    build_fracture_viewport_mesh,
)
from xml_to_usda.qt_ui.window import _fracture_preview_visual_only_settings_changed
from xml_to_usda.qt_ui.viewport import MatcapViewport, _prepare_opaque_mesh_draw, _set_matcap_program_uniforms
from xml_to_usda.viewport_scene import ViewportBoneSegment, ViewportBounds, ViewportScene, ViewportStats


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


def _bone_only_scene(segments: tuple[FracturePreviewBoneSegment, ...]) -> ViewportScene:
    min_x = min(min(segment.parent_position.x, segment.child_position.x) for segment in segments)
    min_y = min(min(segment.parent_position.y, segment.child_position.y) for segment in segments)
    min_z = min(min(segment.parent_position.z, segment.child_position.z) for segment in segments)
    max_x = max(max(segment.parent_position.x, segment.child_position.x) for segment in segments)
    max_y = max(max(segment.parent_position.y, segment.child_position.y) for segment in segments)
    max_z = max(max(segment.parent_position.z, segment.child_position.z) for segment in segments)
    return ViewportScene(
        scene_id="bone_only",
        mesh_batches=(),
        draw_calls=(),
        bounds=ViewportBounds(
            min_point=Vector3(min_x, min_y, min_z),
            max_point=Vector3(max_x, max_y, max_z),
        ),
        stats=ViewportStats(uploaded_triangles=0, logical_triangles=0),
        bone_segments=tuple(
            ViewportBoneSegment(
                segment_id=f"bone:{segment.parent_joint_token}->{segment.child_joint_token}",
                parent_token=segment.parent_joint_token,
                child_token=segment.child_joint_token,
                start=segment.parent_position,
                end=segment.child_position,
                color=segment.color,
                selected=segment.is_selected_cut,
                selectable_id=f"bone:{segment.parent_joint_token}->{segment.child_joint_token}",
            )
            for segment in segments
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
    assert len(mesh.vertex_components) == mesh.uploaded_triangle_count * 3 * FRACTURE_SOURCE_VERTEX_STRIDE
    assert len(mesh.draw_calls) == 5

    first_vertex = tuple(mesh.vertex_components[:FRACTURE_SOURCE_VERTEX_STRIDE])
    assert first_vertex[6:10] == pytest.approx(
        (
            preview.pieces[0].color.r,
            preview.pieces[0].color.g,
            preview.pieces[0].color.b,
            preview.pieces[0].color.a,
        )
    )

    instance_vertex_offset = 3 * 3 * FRACTURE_SOURCE_VERTEX_STRIDE
    first_instance_vertex = tuple(
        mesh.vertex_components[instance_vertex_offset:instance_vertex_offset + FRACTURE_SOURCE_VERTEX_STRIDE]
    )
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
    second_instance_vertex_offset = second_instance_source.first_vertex * FRACTURE_SOURCE_VERTEX_STRIDE
    second_instance_vertex = tuple(
        mesh.vertex_components[second_instance_vertex_offset:second_instance_vertex_offset + FRACTURE_SOURCE_VERTEX_STRIDE]
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


def test_fracture_preview_dialog_uses_prebuilt_viewport_scene(qtbot, monkeypatch) -> None:
    preview = generate_fracture_preview(
        _tree(),
        FracturePreviewSettings(
            fracture=FractureSettings(target_piece_count=3, output_stem="Oak"),
            max_base_faces_per_piece=1,
            max_prototype_faces=1,
        ),
    )
    assert preview.viewport_scene is not None

    import xml_to_usda.qt_ui.fracture_preview as fracture_preview_ui

    monkeypatch.setattr(
        fracture_preview_ui,
        "build_fracture_viewport_scene",
        lambda _preview: (_ for _ in ()).throw(AssertionError("dialog rebuilt ViewportScene")),
    )
    dialog = FracturePreviewDialog(settings=FracturePreviewSettings(), preview=preview)
    qtbot.addWidget(dialog)

    assert dialog.viewport_mesh is not None
    assert dialog.viewport_mesh.piece_count == 3


def test_fracture_preview_dialog_builds_viewport_scene_for_worker_result(qtbot) -> None:
    preview = generate_fracture_preview(
        _tree(),
        FracturePreviewSettings(
            fracture=FractureSettings(target_piece_count=3, output_stem="Oak"),
            max_base_faces_per_piece=1,
            max_prototype_faces=1,
        ),
    )
    worker_preview = replace(preview, viewport_scene=None)

    dialog = FracturePreviewDialog(settings=FracturePreviewSettings(), preview=worker_preview)
    qtbot.addWidget(dialog)

    assert dialog.current_preview is not None
    assert dialog.current_preview.viewport_scene is not None
    assert dialog.viewport_mesh is not None
    assert dialog.viewport_mesh.piece_count == 3


def test_fracture_preview_dialog_does_not_reframe_camera_after_first_preview(qtbot) -> None:
    settings = FracturePreviewSettings(
        fracture=FractureSettings(target_piece_count=3, output_stem="Oak"),
        max_base_faces_per_piece=1,
        max_prototype_faces=1,
    )
    preview = generate_fracture_preview(_tree(), settings)
    dialog = FracturePreviewDialog(settings=settings, preview=preview)
    qtbot.addWidget(dialog)
    dialog.viewport._distance = 123.0

    dialog.set_preview(preview)

    assert dialog.viewport.camera_distance == pytest.approx(123.0)


def test_fracture_preview_dialog_settings_panel_scrolls(qtbot) -> None:
    dialog = FracturePreviewDialog(settings=FracturePreviewSettings())
    qtbot.addWidget(dialog)

    scrolls = dialog.settings_panel.findChildren(QScrollArea)

    assert len(scrolls) == 1
    assert scrolls[0].widgetResizable()
    assert scrolls[0].horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_fracture_preview_dialog_hides_collision_controls_for_other_modes(qtbot) -> None:
    dialog = FracturePreviewDialog(settings=FracturePreviewSettings())
    qtbot.addWidget(dialog)

    assert dialog.convex_vertices_label.isHidden()

    dialog.collision_check.setChecked(True)

    assert not dialog.convex_vertices_label.isHidden()
    assert dialog.sphere_scale_label.isHidden()
    assert dialog.capsule_simplify_label.isHidden()

    dialog.collision_mode_combo.setCurrentIndex(dialog.collision_mode_combo.findData("sphere"))

    assert dialog.convex_vertices_label.isHidden()
    assert not dialog.sphere_scale_label.isHidden()
    assert dialog.capsule_simplify_label.isHidden()

    dialog.collision_mode_combo.setCurrentIndex(dialog.collision_mode_combo.findData("capsule"))

    assert dialog.convex_vertices_label.isHidden()
    assert dialog.sphere_scale_label.isHidden()
    assert not dialog.capsule_simplify_label.isHidden()


def test_fracture_preview_dialog_wheel_over_parameter_scrolls_panel(qtbot) -> None:
    dialog = FracturePreviewDialog(settings=FracturePreviewSettings())
    qtbot.addWidget(dialog)
    scroll = dialog.settings_panel.findChildren(QScrollArea)[0]
    bar = scroll.verticalScrollBar()
    bar.setRange(0, 500)
    bar.setValue(100)
    original_value = dialog.piece_count_spin.value()

    class WheelEvent:
        def __init__(self) -> None:
            self.accepted = False

        def type(self):
            return QEvent.Type.Wheel

        def angleDelta(self):
            return QPoint(0, -120)

        def pixelDelta(self):
            return QPoint(0, 0)

        def accept(self) -> None:
            self.accepted = True

    event = WheelEvent()

    handled = dialog._parameter_wheel_filter.eventFilter(dialog.piece_count_spin, event)

    assert handled is True
    assert event.accepted is True
    assert dialog.piece_count_spin.value() == original_value
    assert bar.value() > 100


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

    viewport = MatcapViewport()
    viewport.set_matcap_tint_strength(FRACTURE_MATCAP_TINT_STRENGTH)
    qtbot.addWidget(viewport)
    payload = apply_fracture_viewport_mesh(viewport, mesh, scene=preview.viewport_scene)

    assert viewport.has_mesh()
    assert viewport.vertex_count == mesh.triangle_count * 3
    assert tuple(payload.vertex_components[6:10]) == pytest.approx(
        (
            preview.pieces[0].color.r,
            preview.pieces[0].color.g,
            preview.pieces[0].color.b,
            preview.pieces[0].color.a,
        )
    )
    first_instance_offset = 3 * 3 * FRACTURE_VERTEX_STRIDE
    assert tuple(
        payload.vertex_components[first_instance_offset + 6:first_instance_offset + 10]
    ) == pytest.approx(
        (
            preview.pieces[1].color.r,
            preview.pieces[1].color.g,
            preview.pieces[1].color.b,
            preview.pieces[1].color.a,
        )
    )
    assert viewport.grid_vertex_count > 0
    assert 0.6 <= viewport.matcap_tint_strength <= 0.9
    assert viewport.camera_radius > 0.0
    assert viewport.camera_distance == pytest.approx(viewport.camera_radius * 3.0)


def test_fracture_viewport_exploded_view_updates_uniform_state_without_reuploading_mesh(qtbot) -> None:
    preview = generate_fracture_preview(
        _tree(),
        FracturePreviewSettings(
            fracture=FractureSettings(target_piece_count=3, output_stem="Oak"),
            max_base_faces_per_piece=1,
            max_prototype_faces=1,
        ),
    )
    mesh = build_fracture_viewport_mesh(preview)
    viewport = MatcapViewport()
    qtbot.addWidget(viewport)
    payload = apply_fracture_viewport_mesh(viewport, mesh, scene=preview.viewport_scene)
    original_components = tuple(mesh.vertex_components)
    render_components = tuple(payload.vertex_components)
    explode_components: list[float] = []
    for offset in range(10, len(payload.vertex_components), FRACTURE_VERTEX_STRIDE):
        explode_components.extend(float(value) for value in payload.vertex_components[offset:offset + 3])
    assert any(abs(value) > 0.0 for value in explode_components)
    upload_calls = 0

    def count_upload() -> None:
        nonlocal upload_calls
        upload_calls += 1

    viewport._upload_mesh = count_upload  # type: ignore[method-assign]

    viewport.set_exploded_view_strength(1.0)

    assert tuple(payload.vertex_components) == render_components
    assert tuple(mesh.vertex_components) == original_components
    assert upload_calls == 0
    assert viewport.exploded_view_strength == pytest.approx(1.0)


def test_fracture_preview_dialog_enables_manual_bones_visibility_and_hides_repeated_parts(qtbot) -> None:
    preview = generate_fracture_preview(
        _tree(),
        FracturePreviewSettings(
            fracture=FractureSettings(
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
                target_piece_count=3,
                pinned_cut_joint_tokens=("bone_003",),
            )
        ),
        preview=preview,
    )
    qtbot.addWidget(dialog)

    assert dialog.show_bones_check.isEnabled()
    assert not dialog.viewport.show_bones
    assert dialog.viewport_mesh.instance_count == 2

    dialog.show_bones_check.setChecked(True)

    assert dialog.viewport.show_bones

    dialog.show_bones_check.setChecked(False)

    assert not dialog.viewport.show_bones

    dialog.hide_repeated_parts_check.setChecked(True)

    assert dialog.viewport_mesh.instance_count == 0
    assert dialog.current_preview is preview
    assert preview.instances


def test_fracture_preview_dialog_reset_cuts_clears_manual_session_tokens(qtbot) -> None:
    emitted: list[FracturePreviewSettings] = []
    settings = FracturePreviewSettings(
        fracture=FractureSettings(
            target_piece_count=3,
            pinned_cut_joint_tokens=("bone_003",),
        )
    )
    dialog = FracturePreviewDialog(settings=settings, on_settings_changed=emitted.append)
    qtbot.addWidget(dialog)

    dialog.reset_cuts_button.click()

    assert emitted
    assert emitted[-1].fracture.pinned_cut_joint_tokens == ()


def test_fracture_preview_dialog_lists_deletes_and_undoes_manual_cuts(qtbot) -> None:
    emitted: list[FracturePreviewSettings] = []
    settings = FracturePreviewSettings(
        fracture=FractureSettings(
            target_piece_count=3,
            pinned_cut_joint_tokens=("bone_002",),
        )
    )
    dialog = FracturePreviewDialog(settings=settings, on_settings_changed=emitted.append)
    qtbot.addWidget(dialog)

    assert tuple(dialog._cut_delete_buttons) == ("bone_002",)
    assert dialog._cut_delete_buttons["bone_002"].maximumWidth() == 22

    dialog._toggle_manual_cut_token("bone_003")

    assert emitted[-1].fracture.pinned_cut_joint_tokens == ("bone_002", "bone_003")
    assert tuple(dialog._cut_delete_buttons) == ("bone_002", "bone_003")

    dialog.undo_cut_shortcut.activated.emit()

    assert emitted[-1].fracture.pinned_cut_joint_tokens == ("bone_002",)
    assert tuple(dialog._cut_delete_buttons) == ("bone_002",)

    dialog._cut_delete_buttons["bone_002"].click()

    assert emitted[-1].fracture.pinned_cut_joint_tokens == ()
    assert dialog._cut_delete_buttons == {}


def test_fracture_preview_dialog_visual_sliders_do_not_emit_preview_settings(qtbot) -> None:
    emitted: list[FracturePreviewSettings] = []
    dialog = FracturePreviewDialog(settings=FracturePreviewSettings(), on_settings_changed=emitted.append)
    qtbot.addWidget(dialog)

    dialog.color_strength_slider.setValue(24)
    dialog.exploded_view_slider.setValue(67)

    assert emitted == []
    assert dialog.color_strength_spin.value() == pytest.approx(0.24)
    assert dialog.viewport.matcap_tint_strength == pytest.approx(0.24)
    assert dialog.exploded_view_spin.value() == pytest.approx(0.67)
    assert dialog.viewport.exploded_view_strength == pytest.approx(0.67)


def test_fracture_preview_dialog_collision_visual_sliders_update_existing_preview(qtbot) -> None:
    emitted: list[FracturePreviewSettings] = []
    settings = FracturePreviewSettings(
        fracture=FractureSettings(target_piece_count=3, output_stem="Oak"),
        collision=FractureCollisionSettings(
            enabled=True,
            mode=FractureCollisionMode.CAPSULE,
            capsule_scale=0.75,
            ghost_opacity=0.25,
        ),
        max_base_faces_per_piece=1,
        max_prototype_faces=1,
    )
    preview = generate_fracture_preview(_tree(), settings)
    assert preview.collision_meshes
    dialog = FracturePreviewDialog(settings=settings, preview=preview, on_settings_changed=emitted.append)
    qtbot.addWidget(dialog)
    upload_calls = 0

    def count_upload() -> None:
        nonlocal upload_calls
        upload_calls += 1

    dialog.viewport._mesh_dirty = False
    dialog.viewport._upload_mesh = count_upload  # type: ignore[method-assign]

    dialog.capsule_scale_slider.setValue(150)
    dialog.collision_opacity_slider.setValue(40)

    assert emitted == []
    assert upload_calls == 0
    assert dialog.viewport.collision_geometry_scale == pytest.approx(2.0)
    assert dialog.viewport.collision_opacity == pytest.approx(0.4)


def test_fracture_preview_window_treats_collision_scale_and_opacity_as_visual_only() -> None:
    previous = FracturePreviewSettings(
        collision=FractureCollisionSettings(
            enabled=True,
            mode=FractureCollisionMode.CAPSULE,
            capsule_scale=0.75,
            ghost_opacity=0.25,
        )
    )

    assert _fracture_preview_visual_only_settings_changed(
        previous,
        replace(previous, collision=replace(previous.collision, capsule_scale=1.5, ghost_opacity=0.4)),
    )
    assert not _fracture_preview_visual_only_settings_changed(
        previous,
        replace(previous, collision=replace(previous.collision, capsule_simplify=50)),
    )


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
    viewport = MatcapViewport()
    qtbot.addWidget(viewport)
    viewport.resize(500, 400)
    scene = _bone_only_scene(mesh.bone_segments)
    apply_fracture_viewport_mesh(viewport, mesh, scene=scene)
    viewport.set_show_bones(True)
    left_screen = viewport._project_point_to_screen(Vector3(-0.75, 0.5, 0.0))

    assert left_screen is not None
    cut_token = viewport.pick_bone_segment_child_token(left_screen[0], left_screen[1])
    assert cut_token is not None
    assert cut_token.startswith("root->left@")
    assert 0.40 < float(cut_token.rsplit("@", 1)[1]) < 0.60


def test_fracture_viewport_ctrl_hover_previews_cut_target_and_click_uses_it(qtbot) -> None:
    picked: list[str] = []
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
    viewport = MatcapViewport()
    qtbot.addWidget(viewport)
    viewport.resize(500, 400)
    scene = _bone_only_scene(mesh.bone_segments)
    apply_fracture_viewport_mesh(viewport, mesh, scene=scene)
    viewport.set_show_bones(True)
    viewport.on_bone_cut_toggled = picked.append
    right_screen = viewport._project_point_to_screen(Vector3(0.75, 0.5, 0.0))

    assert right_screen is not None
    qtbot.mouseMove(
        viewport,
        QPoint(int(round(right_screen[0])), int(round(right_screen[1]))),
        delay=0,
    )
    assert viewport.hover_cut_token is None

    viewport.mouseMoveEvent(
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(float(right_screen[0]), float(right_screen[1])),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.ControlModifier,
        )
    )

    assert viewport.hover_cut_token is not None
    assert viewport.hover_cut_token.startswith("root->right@")
    assert 0.40 < float(viewport.hover_cut_token.rsplit("@", 1)[1]) < 0.60

    viewport.mousePressEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(float(right_screen[0]), float(right_screen[1])),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ControlModifier,
        )
    )

    assert picked == [viewport.hover_cut_token]

    viewport.set_show_bones(False)

    assert viewport.hover_cut_token is None


def test_fracture_viewport_show_bones_does_not_upload_overlay_over_grid(qtbot, monkeypatch) -> None:
    viewport = MatcapViewport()
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
    viewport = MatcapViewport()
    qtbot.addWidget(viewport)
    calls: list[str] = []
    monkeypatch.setattr(viewport, "isValid", lambda: False)
    mesh = build_fracture_viewport_mesh(preview)
    original_payload = apply_fracture_viewport_mesh(viewport, mesh, scene=preview.viewport_scene)
    original_components = tuple(original_payload.vertex_components)
    viewport._mesh_dirty = False
    monkeypatch.setattr(viewport, "_upload_mesh", lambda: calls.append("upload"))

    viewport.set_matcap_tint_strength(0.24)

    assert viewport.matcap_tint_strength == pytest.approx(0.24)
    assert tuple(original_payload.vertex_components) == original_components
    assert tuple(original_payload.vertex_components[6:10]) == pytest.approx(
        (
            preview.pieces[0].color.r,
            preview.pieces[0].color.g,
            preview.pieces[0].color.b,
            preview.pieces[0].color.a,
        )
    )
    assert not viewport._mesh_dirty
    assert calls == []


def test_matcap_uniforms_bind_visual_controls_as_gl_float_uniforms_without_reuploading_vertices() -> None:
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
        exploded_view_strength=0.42,
    )

    assert ("uniformLocation", "pieceTintStrength") in program.calls
    assert ("uniformLocation", "explodeStrength") in program.calls
    assert (7, 0.78) in functions.calls
    assert (7, 0.42) in functions.calls
    assert ("mvp", "mvp") in program.calls
    assert ("normalMatrix", "normal") in program.calls


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
    viewport = MatcapViewport()
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
