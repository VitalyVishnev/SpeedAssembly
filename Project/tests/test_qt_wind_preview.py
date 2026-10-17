from __future__ import annotations

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytestmark = pytest.mark.qt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QFrame, QLabel, QPushButton

from xml_to_usda.fbx_adapter import FbxSkeletalPreview
from xml_to_usda.qt_ui import wind_preview as wind_preview_module
from xml_to_usda.qt_ui.wind_preview import WindPreviewDialog
from xml_to_usda.models import Joint, Matrix4d, ValidationIssue, Vector3
import xml_to_usda.wind_external_skeleton as external_skeleton_module
from xml_to_usda.wind_external_skeleton import (
    ExternalSkeletonChoice,
    ExternalSkeletonChoicesResult,
    ExternalSkeletonPreviewRequest,
    load_external_skeleton_preview,
)


def test_external_skeleton_selection_loads_without_a_load_button(qtbot, monkeypatch, tmp_path) -> None:
    selected_path = tmp_path / "tree.fbx"
    requests = []
    dialog = WindPreviewDialog(external_preview_requested=requests.append)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(
        wind_preview_module.QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(selected_path), "FBX files (*.fbx)"),
    )
    monkeypatch.setattr(wind_preview_module, "external_skeleton_backend_available", lambda _suffix: (True, ""))

    dialog.browse_external_path()
    dialog.browse_external_path()

    assert not hasattr(dialog, "load_external_button")
    assert dialog.external_path_edit.isReadOnly()
    assert requests == [
        ExternalSkeletonPreviewRequest(str(selected_path), group_count=1),
        ExternalSkeletonPreviewRequest(str(selected_path), group_count=1),
    ]


def test_external_usd_skeleton_choice_loads_when_selected(qtbot, monkeypatch, tmp_path) -> None:
    selected_path = tmp_path / "tree.usda"
    requests = []
    dialog = WindPreviewDialog(external_preview_requested=requests.append)
    qtbot.addWidget(dialog)
    dialog.external_path_edit.setText(str(selected_path))
    monkeypatch.setattr(wind_preview_module, "external_skeleton_backend_available", lambda _suffix: (True, ""))

    initial_request = dialog.set_external_skeleton_choices(
        ExternalSkeletonChoicesResult(
            str(selected_path),
            (
                ExternalSkeletonChoice(0, "/Tree/Oak", "Oak", 12),
                ExternalSkeletonChoice(1, "/Tree/Pine", "Pine", 20),
            ),
        )
    )
    dialog.external_skeleton_combo.setCurrentIndex(2)

    assert initial_request is None
    assert requests == [ExternalSkeletonPreviewRequest(str(selected_path), group_count=1, skeleton_index=1)]


def test_external_display_transform_persists_and_warns_without_mutating_skeleton(qtbot, monkeypatch, tmp_path) -> None:
    external_path = tmp_path / "external.fbx"
    external_path.write_bytes(b"stub")
    skeleton = (
        Joint("root", parent=None, bind_transform=Matrix4d.from_translation(Vector3(0.0, 0.0, 0.0))),
        Joint(
            "branch",
            parent="root",
            bind_transform=Matrix4d(rows=(
                (0.0, 1.0, 0.0, 0.0),
                (-1.0, 0.0, 0.0, 0.0),
                (0.0, 0.0, 1.0, 0.0),
                (0.0, 2.0, 0.0, 1.0),
            )),
        ),
    )
    monkeypatch.setattr(
        external_skeleton_module,
        "load_fbx_skeletal_preview",
        lambda _path: FbxSkeletalPreview(skeleton, None, (ValidationIssue("warning", "test_weights", "Normalize weights."),)),
    )
    preview = load_external_skeleton_preview(ExternalSkeletonPreviewRequest(str(external_path)))
    dialog = WindPreviewDialog(preview=preview)
    qtbot.addWidget(dialog)

    assert dialog.grouping_mode_combo.currentData() == "auto_tree"
    # Also protect unit/up-axis transport in the earlier connector display.
    dialog.grouping_mode_combo.setCurrentIndex(dialog.grouping_mode_combo.findData("auto"))
    dialog.source_units_combo.setCurrentIndex(dialog.source_units_combo.findData("cm"))
    dialog.preview_units_combo.setCurrentIndex(dialog.preview_units_combo.findData("m"))
    dialog.source_up_axis_combo.setCurrentIndex(dialog.source_up_axis_combo.findData("Y"))
    dialog.preview_up_axis_combo.setCurrentIndex(dialog.preview_up_axis_combo.findData("Z"))
    snapshot = dialog.wind_session_snapshot()

    assert dialog.total_bones_label.text() == "Total bones: 2"
    assert not dialog.external_vertical_warning_label.isHidden()
    assert "branch" in dialog.external_vertical_warning_label.toolTip()
    assert not dialog.external_diagnostics_frame.isHidden()
    assert "Normalize weights" in dialog.external_diagnostics_label.text()
    assert dialog._active_scene.bone_segments[0].end == Vector3(0.0, 0.0, 0.02)
    assert preview.source_model.skeleton == skeleton
    assert snapshot["schema_version"] == 4

    restored = WindPreviewDialog(preview=preview, wind_session_snapshot=snapshot)
    qtbot.addWidget(restored)
    assert restored.source_units_combo.currentData() == "cm"
    assert restored.preview_up_axis_combo.currentData() == "Z"


def test_version_one_wind_session_uses_safe_external_display_defaults(qtbot, monkeypatch, tmp_path) -> None:
    external_path = tmp_path / "external.fbx"
    external_path.write_bytes(b"stub")
    monkeypatch.setattr(
        external_skeleton_module,
        "load_fbx_skeletal_preview",
        lambda _path: FbxSkeletalPreview(
            skeleton=(
                Joint("root", parent=None, bind_transform=Matrix4d.from_translation(Vector3(0.0, 0.0, 0.0))),
                Joint("branch", parent="root", bind_transform=Matrix4d.from_translation(Vector3(1.0, 0.0, 0.0))),
            ),
            mesh=None,
            diagnostics=(),
        ),
    )
    preview = load_external_skeleton_preview(ExternalSkeletonPreviewRequest(str(external_path)))
    legacy_session = {
        "schema_version": 1,
        "fingerprint": [["root", None], ["branch", "root"]],
        "input_path": str(external_path),
    }
    dialog = WindPreviewDialog(preview=preview, wind_session_snapshot=legacy_session)
    qtbot.addWidget(dialog)

    assert dialog.source_units_combo.currentData() == "cm"
    assert dialog.preview_units_combo.currentData() == "m"
    assert dialog.source_up_axis_combo.currentData() == "Z"
    assert dialog.preview_up_axis_combo.currentData() == "Y"


def test_advanced_wind_group_controls_only_edit_manual_groups_and_persist_settings(qtbot, monkeypatch, tmp_path) -> None:
    external_path = tmp_path / "external.fbx"
    external_path.write_bytes(b"stub")
    monkeypatch.setattr(
        external_skeleton_module,
        "load_fbx_skeletal_preview",
        lambda _path: FbxSkeletalPreview(
            skeleton=(
                Joint("root", parent=None, bind_transform=Matrix4d.from_translation(Vector3(0.0, 0.0, 0.0))),
                Joint("branch", parent="root", bind_transform=Matrix4d.from_translation(Vector3(1.0, 0.0, 0.0))),
            ),
            mesh=None,
            diagnostics=(),
        ),
    )
    preview = load_external_skeleton_preview(ExternalSkeletonPreviewRequest(str(external_path)))
    dialog = WindPreviewDialog(preview=preview)
    qtbot.addWidget(dialog)

    assert dialog.bone_overlap_checkbox.isChecked()
    assert dialog.bone_overlap_strength_editor.value() == 50
    assert dialog.bone_overlap_radius_editor.value() == 1.2
    assert dialog.viewport._bone_overlap_strength == pytest.approx(.5)
    assert dialog.viewport._bone_overlap_radius == pytest.approx(1.2)
    assert dialog.bones_shading_section.toggle.text() == "Bones Shading"
    dialog.bones_shading_section.toggle.click()
    assert dialog.bones_shading_section.content.isHidden()
    assert dialog.bone_overlap_checkbox.isChecked()
    dialog.bones_shading_section.toggle.click()
    assert not dialog.bones_shading_section.content.isHidden()

    assert [dialog.grouping_mode_combo.itemData(i) for i in range(dialog.grouping_mode_combo.count())] == ["xml", "auto_tree", "auto_pve", "auto"]
    assert dialog.grouping_mode_combo.currentData() == "auto_tree"
    assert dialog.tree_threshold_editors["fork_angle"].spin.suffix() == " °"
    assert dialog.tree_threshold_editors["equivalent_size"].spin.suffix() == " %"
    assert len({dialog.tree_equivalent_combo.itemData(i, Qt.ItemDataRole.ToolTipRole) for i in range(3)}) == 3
    ends = tuple(s.end for s in dialog._active_scene.bone_segments)
    dialog.tree_direction_combo.setCurrentIndex(dialog.tree_direction_combo.findData("bind"))
    qtbot.waitUntil(lambda: not dialog._tree_update_timer.isActive())
    assert tuple(s.end for s in dialog._active_scene.bone_segments) == ends
    assert "Identical orientations" in dialog.tree_direction_combo.toolTip()
    assert not dialog.tree_direction_notice.isHidden()
    dialog.tree_direction_combo.setCurrentIndex(dialog.tree_direction_combo.findData("auto"))
    qtbot.waitUntil(lambda: not dialog._tree_update_timer.isActive())
    dialog.bone_overlap_checkbox.setChecked(False)
    dialog.bone_overlap_strength_editor.slider.setValue(1700)
    dialog.bone_overlap_radius_editor.slider.setValue(90)
    batches = dialog._active_scene.mesh_batches
    dialog.grouping_mode_combo.setCurrentIndex(dialog.grouping_mode_combo.findData("auto_pve"))
    assert dialog._is_auto_mode()
    assert dialog.group_count_slider.isEnabled()
    qtbot.waitUntil(lambda: not any(box.text() == "Continue line" for box in dialog.findChildren(QCheckBox)))
    assert dialog._active_scene.mesh_batches is batches
    dialog.grouping_mode_combo.setCurrentIndex(dialog.grouping_mode_combo.findData("auto_tree"))
    analysis = dialog._get_tree_analysis()
    assert dialog._active_scene.mesh_batches is batches
    assert "Tree bone guides" in dialog.summary_label.text()
    dialog.group_count_slider.setValue(2)
    assert dialog._get_tree_analysis() is analysis
    qtbot.waitUntil(lambda: not dialog._tree_update_timer.isActive())
    prepared = dialog._prepared_tree
    camera = (dialog.viewport.camera_target, dialog.viewport.camera_distance)
    geometry = dialog.viewport._precomputed_matcap_vertices
    monkeypatch.setattr(wind_preview_module, "prepare_tree_hierarchy", lambda _: pytest.fail("slider re-prepared the rig"))
    monkeypatch.setattr(dialog.viewport, "set_precomputed_instanced_matcap_scene", lambda *args, **kwargs: pytest.fail("slider rebuilt mesh geometry"))
    dialog.tree_threshold_editors["fork_angle"].slider.setValue(5500)
    dialog.tree_threshold_editors["chain_angle"].setValue(40)
    dialog.tree_threshold_editors["chain_angle"].valueChanged.emit(40)
    qtbot.waitUntil(lambda: not dialog._tree_update_timer.isActive())
    assert dialog._tree_settings.fork_angle == 55
    assert dialog._prepared_tree is prepared
    assert dialog.viewport._precomputed_matcap_vertices is geometry
    assert (dialog.viewport.camera_target, dialog.viewport.camera_distance) == camera
    monkeypatch.undo()

    assert dialog.windowTitle() == "Advanced Wind Settings"
    assert not dialog._group_buttons
    assert any(label.text().startswith("G0 | Base group") for label in dialog.findChildren(QLabel))
    assert not any(button.text().startswith("G0 | Base group") for button in dialog.findChildren(QPushButton))

    dialog.add_manual_group()
    layer_id = dialog._manual_groups[0].layer_id
    dialog.toggle_manual_group_edit(layer_id)
    assert dialog._active_manual_layer_id == layer_id
    dialog.toggle_manual_group_edit(layer_id)
    assert dialog._active_manual_layer_id is None
    assert dialog._selection.group_index is None

    dialog.toggle_manual_group_edit(layer_id)
    dialog._edit_group_from_pick_token("branch", Qt.KeyboardModifier.NoModifier)
    manual_group = next(group for group in dialog._flattened().groups if group.source_layer_id == layer_id)
    assert tuple(dialog._group_buttons) == (manual_group.final_group_index,)

    dialog._toggle_group_settings(manual_group.source_key)
    settings_frame = next(frame for frame in dialog.findChildren(QFrame) if frame.objectName() == "WindGroupSettings")
    checkboxes = {checkbox.text(): checkbox for checkbox in settings_frame.findChildren(QCheckBox)}
    assert {"Trunk", "Dual Influence"} <= set(checkboxes)
    checkboxes["Trunk"].setChecked(True)
    checkboxes["Dual Influence"].setChecked(False)
    dialog._set_group_setting(manual_group.source_key, "influence", 0.35)

    dynamic_wind = dialog._current_dynamic_wind()
    settings = dynamic_wind.simulation_groups[manual_group.final_group_index]
    assert settings.is_trunk_group is True
    assert settings.use_dual_influence is False
    assert settings.influence == pytest.approx(0.35)

    snapshot = dialog.wind_session_snapshot()
    assert snapshot["group_settings"][manual_group.source_key]["influence"] == pytest.approx(0.35)
    assert manual_group.source_key in snapshot["expanded_group_source_keys"]

    dialog.tree_threshold_editors["equivalent_size"].slider.setValue(6500)
    qtbot.waitUntil(lambda: not dialog._tree_update_timer.isActive())
    assert dialog._manual_groups[0].joint_tokens == frozenset({"branch"})
    assert dialog._active_manual_layer_id == layer_id
    assert dialog._current_dynamic_wind().simulation_groups[manual_group.final_group_index].influence == pytest.approx(0.35)
    snapshot = dialog.wind_session_snapshot()

    restored = WindPreviewDialog(preview=preview, wind_session_snapshot=snapshot)
    qtbot.addWidget(restored)
    assert restored.grouping_mode_combo.currentData() == "auto_tree"
    assert restored._tree_settings == dialog._tree_settings
    assert restored.bone_overlap_checkbox.isChecked() is False
    assert restored.viewport._bone_overlap_shading is False
    assert restored.bone_overlap_strength_editor.value() == 17
    assert restored.bone_overlap_radius_editor.value() == .9
    assert restored.viewport._bone_overlap_strength == pytest.approx(.17)
    assert restored.bone_overlap_strength_editor.spin.maximum() == 100
    assert restored.bone_overlap_radius_editor.spin.maximum() == 3
    assert restored.bone_overlap_radius_editor.spin.minimum() == 0
    assert restored.bone_overlap_radius_editor.spin.suffix() == ""
    legacy = dict(snapshot)
    legacy.pop("bone_overlap_radius_scale")
    legacy["bone_overlap_radius"] = 12
    legacy_restored = WindPreviewDialog(preview=preview, wind_session_snapshot=legacy)
    qtbot.addWidget(legacy_restored)
    assert legacy_restored.bone_overlap_radius_editor.value() == 1
    assert restored._current_dynamic_wind() == dialog._current_dynamic_wind()
    assert restored._group_settings_by_source_key[manual_group.source_key]["influence"] == pytest.approx(0.35)
    assert manual_group.source_key in restored._expanded_group_source_keys


def test_wind_error_dialog_explains_missing_skeleton_and_keeps_trace_in_log(qtbot, monkeypatch) -> None:
    from PySide6.QtWidgets import QWidget, QMessageBox
    from xml_to_usda.qt_ui.window import MainWindow
    window = QWidget()
    qtbot.addWidget(window)
    window._wind_preview_dialog = None
    logged = []
    window._append_log = logged.append
    window._finish_status_activity = lambda *args: None
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: shown.append((box.text(), box.informativeText())))
    message = "external_skeleton_not_found: D:/Trees/Alder_proxy.usda\n\nTraceback (most recent call last):\nprivate worker details"
    MainWindow._report_error(window, "Wind Preview failed", message)
    assert "No skeleton in this file." in shown[0][0]
    assert "font-size:18px" in shown[0][0]
    assert shown[0][1] == "File: D:/Trees/Alder_proxy.usda"
    assert "Traceback" not in " ".join(shown[0])
    assert logged == [message]
