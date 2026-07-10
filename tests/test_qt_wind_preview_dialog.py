from __future__ import annotations

import json
from dataclasses import replace

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

pytestmark = pytest.mark.qt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QMessageBox

from xml_to_usda.dynamic_wind import build_dynamic_wind_data
from xml_to_usda.qt_ui.wind_preview import (
    GROUPING_MODE_AUTO,
    LAYERS_SCROLL_MIN_HEIGHT,
    SOURCE_MODE_EXTERNAL,
    WIND_PREVIEW_DEFAULT_HEIGHT,
    WIND_SETTINGS_PANEL_DEFAULT_WIDTH,
    WindPreviewDialog,
)
from xml_to_usda.wind_external_skeleton import ExternalSkeletonChoice, ExternalSkeletonChoicesResult
from xml_to_usda.wind_preview_service import WindPreviewResult
from xml_to_usda.wind_viewport_scene import build_auto_wind_viewport_data, build_wind_viewport_groups, build_wind_viewport_scene

from test_wind_viewport_scene import _tree_model


def test_wind_preview_dialog_lists_groups_and_updates_selection(qtbot) -> None:
    model = _tree_model()
    dynamic_wind = build_dynamic_wind_data(model.skeleton)
    preview = WindPreviewResult(
        input_path="tree.xml",
        source_model=model,
        dynamic_wind=dynamic_wind,
        groups=build_wind_viewport_groups(dynamic_wind),
        diagnostics=(),
        viewport_scene=build_wind_viewport_scene(model, dynamic_wind),
    )
    dialog = WindPreviewDialog(preview=preview)
    qtbot.addWidget(dialog)

    assert dialog._active_scene is preview.viewport_scene
    assert list(dialog._group_buttons) == [2, 1, 0]
    assert not hasattr(dialog, "clear_button")
    assert not hasattr(dialog, "undo_button")
    assert not hasattr(dialog, "redo_button")
    assert "QComboBox:hover" in dialog.settings_panel.styleSheet()
    assert dialog.height() == WIND_PREVIEW_DEFAULT_HEIGHT
    assert dialog.settings_panel_default_width == WIND_SETTINGS_PANEL_DEFAULT_WIDTH
    assert dialog.global_scroll.widgetResizable() is True
    assert dialog.layers_resize_handle.objectName() == "LayerResizeHandle"
    dialog._resize_layers_scroll(-1000)
    assert dialog.scroll.minimumHeight() == LAYERS_SCROLL_MIN_HEIGHT
    assert dialog.scroll.maximumHeight() == LAYERS_SCROLL_MIN_HEIGHT
    dialog._resize_layers_scroll(70)
    assert dialog.scroll.minimumHeight() == LAYERS_SCROLL_MIN_HEIGHT + 70
    assert dialog.scroll.maximumHeight() == LAYERS_SCROLL_MIN_HEIGHT + 70
    assert dialog.scroll.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    assert dialog.add_group_button.width() <= 24
    assert dialog.remove_group_button.width() <= 24
    assert dialog._group_buttons[2].height() <= 22

    initial_vertices = dialog.viewport._precomputed_matcap_vertices
    dialog.select_group(2)

    assert set(dialog._group_buttons) == {0, 1, 2}
    assert dialog._group_buttons[2].isChecked() is True
    assert dialog.viewport._precomputed_matcap_vertices is initial_vertices

    auto_index = dialog.grouping_mode_combo.findData("auto")
    assert auto_index >= 0
    dialog.grouping_mode_combo.setCurrentIndex(auto_index)
    dialog.group_count_slider.setValue(2)

    assert dialog.group_count_label.text() == "Groups: 1"
    assert list(dialog._group_buttons) == [0]
    assert "Auto hierarchy" in dialog.summary_label.text()

    auto_checkboxes = []
    for row_index in range(dialog.group_layout.count()):
        row = dialog.group_layout.itemAt(row_index).widget()
        if row is not None:
            auto_checkboxes.extend(row.findChildren(QCheckBox))
    assert len(auto_checkboxes) == 1
    assert auto_checkboxes[0].isChecked() is False

    auto_checkboxes[0].setChecked(True)

    assert dialog._auto_continuous_levels == {0}


def test_wind_preview_dialog_layer_controls_survive_common_clicks(qtbot, monkeypatch) -> None:
    model = _tree_model()
    dynamic_wind = build_dynamic_wind_data(model.skeleton)
    preview = WindPreviewResult(
        input_path="tree.xml",
        source_model=model,
        dynamic_wind=dynamic_wind,
        groups=build_wind_viewport_groups(dynamic_wind),
        diagnostics=(),
        viewport_scene=build_wind_viewport_scene(model, dynamic_wind),
    )
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    dialog = WindPreviewDialog(preview=preview)
    qtbot.addWidget(dialog)

    auto_index = dialog.grouping_mode_combo.findData(GROUPING_MODE_AUTO)
    dialog.grouping_mode_combo.setCurrentIndex(auto_index)
    dialog.group_count_slider.setValue(3)
    for checkbox in dialog.group_host.findChildren(QCheckBox):
        checkbox.setChecked(not checkbox.isChecked())
    for group_index in list(dialog._group_buttons):
        dialog.select_group(group_index)

    dialog.add_manual_group()
    dialog.toggle_manual_group_edit(0)
    dialog._edit_group_from_pick_token("root->bone_001@0.500", Qt.KeyboardModifier.NoModifier)
    dialog.clear_active_manual_group()
    dialog.undo_manual_edit()
    dialog.redo_manual_edit()
    dialog.delete_active_manual_group()

    assert dialog._manual_groups == ()


def test_wind_preview_dialog_manual_group_overrides_and_alt_removes(qtbot) -> None:
    model = _tree_model()
    dynamic_wind = build_dynamic_wind_data(model.skeleton)
    preview = WindPreviewResult(
        input_path="tree.xml",
        source_model=model,
        dynamic_wind=dynamic_wind,
        groups=build_wind_viewport_groups(dynamic_wind),
        diagnostics=(),
        viewport_scene=build_wind_viewport_scene(model, dynamic_wind),
    )
    dialog = WindPreviewDialog(preview=preview)
    qtbot.addWidget(dialog)

    dialog.add_manual_group()

    assert len(dialog._manual_groups) == 1
    assert dialog._manual_groups[0].joint_tokens == frozenset()

    dialog.toggle_manual_group_edit(0)

    assert dialog.viewport._shortcut_hints[:3] == ("LMB add subtree", "Alt+LMB remove subtree", "Wheel zoom")
    assert "Ctrl+Z undo" in dialog.viewport._shortcut_hints

    dialog._edit_group_from_pick_token("root->bone_001@0.500", Qt.KeyboardModifier.NoModifier)

    assert dialog._manual_groups[0].joint_tokens == frozenset({"bone_001", "bone_002"})
    assert {assignment.joint_name: assignment.simulation_group_index for assignment in dialog._current_dynamic_wind().joint_assignments} == {
        "root": 0,
        "bone_001": 1,
        "bone_002": 1,
    }
    assert dialog.viewport._precomputed_matcap_vertices is not None

    dialog.edit_mode_combo.setCurrentIndex(dialog.edit_mode_combo.findData("bones"))

    assert dialog.viewport._shortcut_hints[:3] == ("LMB add bone", "Alt+LMB remove bone", "Wheel zoom")

    dialog._edit_group_from_pick_token("root->bone_001@0.500", Qt.KeyboardModifier.AltModifier)

    assert dialog._manual_groups[0].joint_tokens == frozenset({"bone_002"})
    assert {assignment.joint_name: assignment.simulation_group_index for assignment in dialog._current_dynamic_wind().joint_assignments} == {
        "root": 0,
        "bone_001": 1,
        "bone_002": 2,
    }


def test_wind_preview_dialog_restores_session_when_skeleton_matches(qtbot, tmp_path) -> None:
    model = _tree_model()
    dynamic_wind = build_dynamic_wind_data(model.skeleton)
    preview = WindPreviewResult(
        input_path=str(tmp_path / "tree.xml"),
        source_model=model,
        dynamic_wind=dynamic_wind,
        groups=build_wind_viewport_groups(dynamic_wind),
        diagnostics=(),
        viewport_scene=build_wind_viewport_scene(model, dynamic_wind),
    )
    saved_sessions: list[dict[str, object]] = []
    dialog = WindPreviewDialog(preview=preview, wind_session_changed=saved_sessions.append)
    qtbot.addWidget(dialog)
    dialog.add_manual_group()
    dialog.toggle_manual_group_edit(0)
    dialog._edit_group_from_pick_token("root->bone_001@0.500", Qt.KeyboardModifier.NoModifier)
    dialog.output_path_edit.setText(str(tmp_path / "tree_wind.json"))

    snapshot = dialog.wind_session_snapshot()
    restored = WindPreviewDialog(preview=preview, wind_session_snapshot=snapshot)
    qtbot.addWidget(restored)

    assert saved_sessions
    assert restored._manual_groups[0].joint_tokens == frozenset({"bone_001", "bone_002"})
    assert restored._active_manual_layer_id == 0
    assert restored.output_path_edit.text().endswith("tree_wind.json")
    assert {assignment.joint_name: assignment.simulation_group_index for assignment in restored._current_dynamic_wind().joint_assignments} == {
        "root": 0,
        "bone_001": 1,
        "bone_002": 1,
    }


def test_wind_preview_dialog_resets_session_when_skeleton_fingerprint_differs(qtbot) -> None:
    model = _tree_model()
    dynamic_wind = build_dynamic_wind_data(model.skeleton)
    preview = WindPreviewResult(
        input_path="tree.xml",
        source_model=model,
        dynamic_wind=dynamic_wind,
        groups=build_wind_viewport_groups(dynamic_wind),
        diagnostics=(),
        viewport_scene=build_wind_viewport_scene(model, dynamic_wind),
    )
    session = {
        "schema_version": 1,
        "fingerprint": [["other_root", None]],
        "manual_groups": [{"layer_id": 0, "joint_tokens": ["bone_001"]}],
    }

    dialog = WindPreviewDialog(preview=preview, wind_session_snapshot=session)
    qtbot.addWidget(dialog)

    assert dialog._manual_groups == ()
    assert "session reset: skeleton changed" in dialog.summary_label.text()


def test_wind_preview_dialog_undo_redo_clear_and_delete_manual_groups(qtbot, monkeypatch) -> None:
    model = _tree_model()
    dynamic_wind = build_dynamic_wind_data(model.skeleton)
    preview = WindPreviewResult(
        input_path="tree.xml",
        source_model=model,
        dynamic_wind=dynamic_wind,
        groups=build_wind_viewport_groups(dynamic_wind),
        diagnostics=(),
        viewport_scene=build_wind_viewport_scene(model, dynamic_wind),
    )
    dialog = WindPreviewDialog(preview=preview)
    qtbot.addWidget(dialog)
    dialog.add_manual_group()
    dialog.toggle_manual_group_edit(0)
    dialog._edit_group_from_pick_token("root->bone_001@0.500", Qt.KeyboardModifier.NoModifier)

    dialog.undo_manual_edit()

    assert dialog._manual_groups[0].joint_tokens == frozenset()

    dialog.redo_manual_edit()

    assert dialog._manual_groups[0].joint_tokens == frozenset({"bone_001", "bone_002"})

    dialog.clear_active_manual_group()

    assert dialog._manual_groups[0].joint_tokens == frozenset()

    dialog.undo_manual_edit()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    dialog.delete_active_manual_group()

    assert dialog._manual_groups == ()


def test_wind_preview_dialog_generates_json_from_final_visible_groups(qtbot, tmp_path) -> None:
    model = _tree_model()
    dynamic_wind = build_dynamic_wind_data(model.skeleton)
    preview = WindPreviewResult(
        input_path=str(tmp_path / "tree.xml"),
        source_model=model,
        dynamic_wind=dynamic_wind,
        groups=build_wind_viewport_groups(dynamic_wind),
        diagnostics=(),
        viewport_scene=build_wind_viewport_scene(model, dynamic_wind),
    )
    dialog = WindPreviewDialog(preview=preview)
    qtbot.addWidget(dialog)
    output_path = tmp_path / "tree_DynamicWind.json"
    dialog.output_path_edit.setText(str(output_path))
    dialog.add_manual_group()
    dialog.toggle_manual_group_edit(0)
    dialog._edit_group_from_pick_token("root->bone_001@0.500", Qt.KeyboardModifier.NoModifier)

    dialog.generate_json()

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert [(joint["JointName"], joint["SimulationGroupIndex"]) for joint in payload["Joints"]] == [
        ("root", 0),
        ("bone_001", 1),
        ("bone_002", 1),
    ]
    assert "Wrote Dynamic Wind JSON" in dialog.summary_label.text()


def test_wind_preview_dialog_loads_external_skeleton_source(qtbot, tmp_path, monkeypatch) -> None:
    model = _tree_model()
    dynamic_wind = build_dynamic_wind_data(model.skeleton)
    preview = WindPreviewResult(
        input_path="tree.xml",
        source_model=model,
        dynamic_wind=dynamic_wind,
        groups=build_wind_viewport_groups(dynamic_wind),
        diagnostics=(),
        viewport_scene=build_wind_viewport_scene(model, dynamic_wind),
    )
    external_path = tmp_path / "external.fbx"
    external_path.write_bytes(b"stub")
    external_model = replace(model, base_mesh=None, assembly_parts=(), prototypes=())
    external_wind = build_auto_wind_viewport_data(external_model.skeleton, group_count=3)
    external_preview = WindPreviewResult(
        input_path=str(external_path),
        source_model=external_model,
        dynamic_wind=external_wind,
        groups=build_wind_viewport_groups(external_wind),
        diagnostics=(),
        viewport_scene=build_wind_viewport_scene(external_model, external_wind),
        xml_groups_available=False,
        preferred_grouping_mode=GROUPING_MODE_AUTO,
    )
    monkeypatch.setattr(
        "xml_to_usda.qt_ui.wind_preview.load_external_skeleton_preview",
        lambda request: external_preview,
    )
    dialog = WindPreviewDialog(preview=preview)
    qtbot.addWidget(dialog)

    dialog.source_mode_combo.setCurrentIndex(dialog.source_mode_combo.findData(SOURCE_MODE_EXTERNAL))
    dialog.external_path_edit.setText(str(external_path))
    dialog.load_external_skeleton()

    assert dialog.current_preview is external_preview
    assert dialog.grouping_mode_combo.currentData() == GROUPING_MODE_AUTO
    assert "External skeleton loaded" in dialog.summary_label.text()


def test_wind_preview_dialog_requests_external_skeleton_through_worker_callback(qtbot, tmp_path, monkeypatch) -> None:
    model = _tree_model()
    dynamic_wind = build_dynamic_wind_data(model.skeleton)
    preview = WindPreviewResult(
        input_path="tree.xml",
        source_model=model,
        dynamic_wind=dynamic_wind,
        groups=build_wind_viewport_groups(dynamic_wind),
        diagnostics=(),
        viewport_scene=build_wind_viewport_scene(model, dynamic_wind),
    )
    external_path = tmp_path / "external.fbx"
    external_path.write_bytes(b"stub")
    calls = []
    monkeypatch.setattr(
        "xml_to_usda.qt_ui.wind_preview.load_external_skeleton_preview",
        lambda _request: (_ for _ in ()).throw(AssertionError("direct external load should not run")),
    )
    dialog = WindPreviewDialog(preview=preview, external_preview_requested=calls.append)
    qtbot.addWidget(dialog)
    dialog.source_mode_combo.setCurrentIndex(dialog.source_mode_combo.findData(SOURCE_MODE_EXTERNAL))
    dialog.external_path_edit.setText(str(external_path))

    dialog.load_external_skeleton()

    assert len(calls) == 1
    assert calls[0].input_path == str(external_path)
    assert "Loading external skeleton" in dialog.summary_label.text()


def test_wind_preview_dialog_requires_explicit_usd_skeleton_choice(qtbot, tmp_path, monkeypatch) -> None:
    model = _tree_model()
    dynamic_wind = build_dynamic_wind_data(model.skeleton)
    preview = WindPreviewResult(
        input_path="tree.xml",
        source_model=model,
        dynamic_wind=dynamic_wind,
        groups=build_wind_viewport_groups(dynamic_wind),
        diagnostics=(),
        viewport_scene=build_wind_viewport_scene(model, dynamic_wind),
    )
    usd_path = tmp_path / "external.usda"
    usd_path.write_text("#usda 1.0", encoding="utf-8")
    result = ExternalSkeletonChoicesResult(
        input_path=str(usd_path),
        choices=(
            ExternalSkeletonChoice(index=0, prim_path="/Tree/MainSkeleton", name="MainSkeleton", joint_count=105),
            ExternalSkeletonChoice(index=1, prim_path="/Tree/PartSkeleton", name="PartSkeleton", joint_count=1),
        ),
    )
    calls = []
    monkeypatch.setattr("xml_to_usda.qt_ui.wind_preview.list_external_usd_skeletons", lambda _path: result)
    monkeypatch.setattr(
        "xml_to_usda.qt_ui.wind_preview.load_external_skeleton_preview",
        lambda request: calls.append(request) or preview,
    )
    dialog = WindPreviewDialog(preview=preview)
    qtbot.addWidget(dialog)
    dialog.source_mode_combo.setCurrentIndex(dialog.source_mode_combo.findData(SOURCE_MODE_EXTERNAL))
    dialog.external_path_edit.setText(str(usd_path))

    dialog.load_external_skeleton()

    assert calls == []
    assert not dialog.external_skeleton_combo.isHidden()
    assert "Choose a Skeleton prim" in dialog.summary_label.text()

    dialog.external_skeleton_combo.setCurrentIndex(1)
    dialog.load_external_skeleton()

    assert len(calls) == 1
    assert calls[0].skeleton_index == 1


def test_wind_preview_dialog_keeps_usd_skeleton_choice_after_path_normalization(qtbot, tmp_path, monkeypatch) -> None:
    model = _tree_model()
    dynamic_wind = build_dynamic_wind_data(model.skeleton)
    preview = WindPreviewResult(
        input_path="tree.xml",
        source_model=model,
        dynamic_wind=dynamic_wind,
        groups=build_wind_viewport_groups(dynamic_wind),
        diagnostics=(),
        viewport_scene=build_wind_viewport_scene(model, dynamic_wind),
    )
    usd_path = tmp_path / "external.usda"
    usd_path.write_text("#usda 1.0", encoding="utf-8")
    typed_path = str(usd_path).replace("\\", "/")
    result = ExternalSkeletonChoicesResult(
        input_path=str(usd_path),
        choices=(
            ExternalSkeletonChoice(index=0, prim_path="/Tree/MainSkeleton", name="MainSkeleton", joint_count=105),
            ExternalSkeletonChoice(index=1, prim_path="/Tree/PartSkeleton", name="PartSkeleton", joint_count=1),
        ),
    )
    calls = []
    monkeypatch.setattr("xml_to_usda.qt_ui.wind_preview.list_external_usd_skeletons", lambda _path: result)
    monkeypatch.setattr(
        "xml_to_usda.qt_ui.wind_preview.load_external_skeleton_preview",
        lambda request: calls.append(request) or preview,
    )
    dialog = WindPreviewDialog(preview=preview)
    qtbot.addWidget(dialog)
    dialog.source_mode_combo.setCurrentIndex(dialog.source_mode_combo.findData(SOURCE_MODE_EXTERNAL))
    dialog.external_path_edit.setText(typed_path)
    dialog.load_external_skeleton()

    dialog.external_skeleton_combo.setCurrentIndex(1)
    dialog.load_external_skeleton()

    assert len(calls) == 1
    assert calls[0].input_path == typed_path
    assert calls[0].skeleton_index == 1
