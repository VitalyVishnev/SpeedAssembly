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
        Joint("branch", parent="root", bind_transform=Matrix4d.from_translation(Vector3(0.0, 2.0, 0.0))),
    )
    monkeypatch.setattr(
        external_skeleton_module,
        "load_fbx_skeletal_preview",
        lambda _path: FbxSkeletalPreview(skeleton, None, (ValidationIssue("warning", "test_weights", "Normalize weights."),)),
    )
    preview = load_external_skeleton_preview(ExternalSkeletonPreviewRequest(str(external_path)))
    dialog = WindPreviewDialog(preview=preview)
    qtbot.addWidget(dialog)

    dialog.source_units_combo.setCurrentIndex(dialog.source_units_combo.findData("cm"))
    dialog.preview_units_combo.setCurrentIndex(dialog.preview_units_combo.findData("m"))
    dialog.preview_up_axis_combo.setCurrentIndex(dialog.preview_up_axis_combo.findData("Z"))
    snapshot = dialog.wind_session_snapshot()

    assert dialog.total_bones_label.text() == "Total bones: 2"
    assert not dialog.external_vertical_warning_label.isHidden()
    assert "branch" in dialog.external_vertical_warning_label.toolTip()
    assert not dialog.external_diagnostics_frame.isHidden()
    assert "Normalize weights" in dialog.external_diagnostics_label.text()
    assert dialog._active_scene.bone_segments[0].end == Vector3(0.0, 0.0, 0.02)
    assert preview.source_model.skeleton == skeleton
    assert snapshot["schema_version"] == 3

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

    assert dialog.source_units_combo.currentData() == "m"
    assert dialog.preview_units_combo.currentData() == "m"
    assert dialog.source_up_axis_combo.currentData() == "Y"
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

    restored = WindPreviewDialog(preview=preview, wind_session_snapshot=snapshot)
    qtbot.addWidget(restored)
    assert restored._group_settings_by_source_key[manual_group.source_key]["influence"] == pytest.approx(0.35)
    assert manual_group.source_key in restored._expanded_group_source_keys
