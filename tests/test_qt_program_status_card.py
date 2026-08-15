from __future__ import annotations

from types import SimpleNamespace

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytestmark = pytest.mark.qt

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QCheckBox, QStyle, QStyleOptionSlider

from xml_to_usda.models import ConversionPhase, ConversionTelemetry, PrototypeSourceMode, ScatteredRigMode, SkinningQuality
from xml_to_usda.qt_ui.dependencies import build_default_dependencies
from xml_to_usda.qt_ui.panels import GeometryRowState
from xml_to_usda.qt_ui.persistence import UiShellState
from xml_to_usda.qt_ui.status_card import ProgramStatusCard
from xml_to_usda.qt_ui.theme import load_theme
from xml_to_usda.qt_ui.window import MainWindow


def test_program_status_card_tracks_conversion_steps_and_progress(qtbot) -> None:
    card = ProgramStatusCard()
    qtbot.addWidget(card)
    card.show()

    card.begin_conversion("Preparing conversion job...")
    card.set_conversion_telemetry(
        ConversionTelemetry(
            phase=ConversionPhase.FBX_IMPORT,
            completed_units=1,
            total_units=2,
            message="Imported branch.fbx",
            elapsed_seconds=1.5,
        )
    )

    assert card.state_label.text() == "Converting Tree"
    assert card.progress.minimum() == 0
    assert card.progress.maximum() == 2
    assert card.progress.value() == 1
    assert "Imported branch.fbx" in card.status_label.text()
    assert card.step_labels[0].property("stepState") == "complete"
    assert card.step_labels[1].property("stepState") == "complete"
    assert card.step_labels[2].property("stepState") == "active"
    assert card.step_labels[3].property("stepState") == "pending"
    step_text = card.step_labels[2].text()
    qtbot.waitUntil(lambda: card.step_markers[2].text() != "◴", timeout=500)
    assert card.step_labels[2].text() == step_text


def test_program_status_card_success_resets_but_error_persists(qtbot) -> None:
    card = ProgramStatusCard()
    qtbot.addWidget(card)
    assert card.SUCCESS_RESET_MS == 5_000
    card.SUCCESS_RESET_MS = 10

    card.begin_activity("Proxy Mesh", "Generating Proxy Mesh...")
    assert card.progress.maximum() == 0
    card.finish("success", "Proxy Mesh ready.")
    assert card.state_label.text() == "Success"
    assert card.state_label.property("statusState") == "success"
    qtbot.waitUntil(lambda: card.state_label.text() == "Ready", timeout=500)

    card.begin_activity("Part Preview", "Generating Part Preview...")
    card.finish("error", "Part Preview failed.")
    qtbot.wait(30)
    assert card.state_label.text() == "Error"
    assert card.status_label.text() == "Part Preview failed."

    card.set_passive_message("New operator action.")
    assert card.state_label.text() == "Ready"
    assert card.status_label.text() == "New operator action."


@pytest.mark.parametrize(
    "operation",
    ("Inspecting XML", "Wind Preview", "Proxy Preview", "Fracture Preview", "Part Preview"),
)
def test_program_status_card_tracks_non_conversion_jobs(operation, qtbot) -> None:
    card = ProgramStatusCard()
    qtbot.addWidget(card)

    card.begin_activity(operation, "Working...")
    assert card.state_label.text() == operation
    assert card.progress.maximum() == 0
    assert card.steps_frame.isHidden()

    card.finish("success", f"{operation} ready.")
    assert card.state_label.text() == "Success"
    assert card.status_label.text() == f"{operation} ready."

    card.begin_activity(operation, "Working again...")
    card.finish("error", f"{operation} failed.")
    assert card.state_label.text() == "Error"
    assert card.status_label.text() == f"{operation} failed."


def test_program_status_card_cancelled_state_persists(qtbot) -> None:
    card = ProgramStatusCard()
    qtbot.addWidget(card)

    card.begin_conversion("Preparing conversion job...")
    card.finish("cancelled", "Conversion cancelled.")
    qtbot.wait(30)

    assert card.state_label.text() == "Cancelled"
    assert card.status_label.text() == "Conversion cancelled."


def test_program_status_card_updates_source_and_material_summary(qtbot) -> None:
    card = ProgramStatusCard()
    qtbot.addWidget(card)

    card.set_summary(
        mode="Static Assembly",
        skinning_quality=1,
        materials="Single Material · M_Bark",
        materials_tooltip="/Game/Tree/M_Bark.M_Bark",
        source="Base slots: 2\nPrototypes: 3\nInstances: 43,263",
    )

    assert "Static Assembly" in card.mode_label.text()
    assert "1 weight" in card.skinning_label.text()
    assert "Instances: 43,263" in card.source_label.text()
    assert card.material_label.toolTip() == "/Game/Tree/M_Bark.M_Bark"
    assert "<b>MATERIALS</b>" in card.material_label.text()


def test_program_status_card_keeps_missing_bone_warning_visible(qtbot) -> None:
    card = ProgramStatusCard()
    qtbot.addWidget(card)

    card.set_bone_gap_warning(("Group_2",))
    card.finish("success", "Source rows loaded.")

    assert not card.bone_gap_warning_label.isHidden()
    assert card.bone_gap_warning_label.text() == "⚠ Missing bones: Group_2"

    card.set_bone_gap_warning(("Group_2", "Group_4"))
    assert card.bone_gap_warning_label.text() == "⚠ Missing bones in 2 groups"
    assert card.bone_gap_warning_label.toolTip() == "Group_2, Group_4"

    card.set_bone_gap_warning(())
    assert card.bone_gap_warning_label.isHidden()


def test_program_status_card_compacts_paths_but_keeps_full_tooltip(qtbot) -> None:
    card = ProgramStatusCard()
    qtbot.addWidget(card)
    message = r"Wrote USDA to D:\3D Personal\XMLtoUSD_miscFiles\SkeletalAssemblyTest_Caps.usda"

    card.finish("success", message)

    assert card.status_label.text() == "Wrote USDA to\nSkeletalAssemblyTest_Caps.usda"
    assert card.status_label.toolTip() == message


def test_main_window_uses_one_status_card_and_no_tab_summary_rows(qtbot, tmp_path) -> None:
    window = MainWindow(
        load_theme(),
        UiShellState(width=1160, height=780, help_prompt_dismissed=True),
        dependencies=build_default_dependencies(),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)

    assert window.status_label is window.program_status_card.status_label
    assert window.wind_panel.skinning_quality_slider.minimum() == 1
    assert window.wind_panel.skinning_quality_slider.maximum() == 4
    assert window.wind_panel.skinning_quality().value == 1
    assert "Maximum skinning influences" in window.wind_panel.skinning_quality_slider.toolTip()
    assert not hasattr(window, "materials_card")
    assert not hasattr(window, "runtime_card")
    assert not hasattr(window.wind_panel, "summary_label")
    assert not hasattr(window.geometry_panel, "summary_label")
    assert not hasattr(window.materials_panel, "summary_label")


def test_scattered_parts_replaces_skinning_slider_contract_and_disables_cluster_ticks_without_clusters(qtbot, tmp_path) -> None:
    window = MainWindow(
        load_theme(),
        UiShellState(width=1160, height=780, help_prompt_dismissed=True),
        dependencies=build_default_dependencies(),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    panel = window.wind_panel
    assert panel.scattered_orientation_checkbox.isHidden()
    assert panel.orient_scattered_bones_from_instances() is False

    panel.set_scattered_parts_mode(active=True, clustered=True, cluster_count=103, instance_count=4223)

    assert panel.skinning_label.text() == "Scattered Rig Mode"
    assert not panel.scattered_orientation_checkbox.isHidden()
    panel.scattered_orientation_checkbox.setChecked(True)
    assert panel.orient_scattered_bones_from_instances() is True
    assert panel.scattered_rig_mode() == ScatteredRigMode.PER_CLUSTER_SKINNED
    assert panel.effective_skinning_quality() == SkinningQuality.TWO_WEIGHTS
    assert "207 joints" in panel.skinning_description_label.text()
    assert "Warning" in panel.skinning_tick_labels.labels[3].text()
    panel.skinning_quality_slider.setValue(4)
    assert "4,224 joints" in panel.skinning_description_label.text()
    panel.skinning_quality_slider.setValue(3)

    panel.set_scattered_parts_mode(active=True, clustered=False, instance_count=41)

    assert panel.scattered_rig_mode() == ScatteredRigMode.WHOLE_MESH_SKINNED
    assert not panel.skinning_tick_labels.labels[1].isEnabled()
    assert not panel.skinning_tick_labels.labels[2].isEnabled()
    assert panel.skinning_tick_labels.labels[0].isEnabled()
    assert panel.skinning_tick_labels.labels[3].isEnabled()
    assert panel.skinning_tick_labels.labels[0].font().bold()
    assert all(label.graphicsEffect() is None for label in panel.skinning_tick_labels.labels)

    panel.skinning_quality_slider.setValue(2)
    assert panel.skinning_quality_slider.value() == 1
    assert panel.skinning_tick_labels.labels[0].font().bold()
    assert not panel.skinning_tick_labels.labels[1].font().bold()

    panel.skinning_quality_slider.setValue(3)
    assert panel.skinning_quality_slider.value() == 4
    assert panel.skinning_tick_labels.labels[3].font().bold()
    assert not panel.skinning_tick_labels.labels[2].font().bold()


def test_skinning_quality_slider_labels_align_and_control_supports_click_and_drag(qtbot, tmp_path) -> None:
    window = MainWindow(
        load_theme(),
        UiShellState(width=1160, height=780, help_prompt_dismissed=True),
        dependencies=build_default_dependencies(),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()
    slider = window.wind_panel.skinning_quality_slider
    labels = window.wind_panel.skinning_tick_labels
    def labels_are_aligned() -> bool:
        option = QStyleOptionSlider()
        slider.initStyleOption(option)
        groove = slider.style().subControlRect(QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, slider)
        handle = slider.style().subControlRect(QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, slider)
        span = groove.width() - handle.width()
        slider_offset = labels.mapFromGlobal(slider.mapToGlobal(QPoint())).x()
        return all(
            abs(
                label.geometry().center().x()
                - (
                    slider_offset
                    + groove.x()
                    + handle.width() // 2
                    + QStyle.sliderPositionFromValue(1, 4, label.value, span, option.upsideDown)
                )
            )
            <= 1
            for label in labels.labels
        )

    qtbot.waitUntil(labels_are_aligned, timeout=1000)

    option = QStyleOptionSlider()
    slider.initStyleOption(option)
    groove = slider.style().subControlRect(QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, slider)
    handle = slider.style().subControlRect(QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, slider)
    span = groove.width() - handle.width()
    slider_offset = labels.mapFromGlobal(slider.mapToGlobal(QPoint())).x()
    for label in labels.labels:
        position = QStyle.sliderPositionFromValue(1, 4, label.value, span, option.upsideDown)
        expected_center = slider_offset + groove.x() + handle.width() // 2 + position
        assert abs(label.geometry().center().x() - expected_center) <= 1
        assert label.toolTip()
        assert label.height() >= label.sizeHint().height() + 4

    slider.setValue(1)
    qtbot.mouseClick(slider, Qt.MouseButton.LeftButton, pos=QPoint(slider.width() - 2, slider.height() // 2))
    assert slider.value() == 4
    assert labels.labels[3].font().bold()

    qtbot.mouseClick(labels.labels[1], Qt.MouseButton.LeftButton)
    assert slider.value() == 2

    start = QPoint(slider.width() // 3, slider.height() // 2)
    end = QPoint(slider.width() * 2 // 3, slider.height() // 2)
    qtbot.mousePress(slider, Qt.MouseButton.LeftButton, pos=start)
    assert slider.isSliderDown()
    qtbot.mouseMove(slider, pos=end)
    qtbot.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=end)
    assert slider.value() == 3
    assert not slider.isSliderDown()


def test_parts_folder_button_controls_output_directory_and_visibility(qtbot, tmp_path) -> None:
    window = MainWindow(
        load_theme(),
        UiShellState(width=1160, height=780, help_prompt_dismissed=True),
        dependencies=build_default_dependencies(),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    output_path = tmp_path / "Tree.usda"
    window.output_input.setText(str(output_path))

    assert isinstance(window.parts_folder_button, QCheckBox)
    assert window.parts_folder_button.isHidden()

    window._set_conversion_mode("skeletal_parts")
    assert not window.parts_folder_button.isHidden()
    assert window.parts_folder_button.isChecked()
    assert window._conversion_output_path() == str(tmp_path / "Tree_SkeletalParts")

    window.parts_folder_button.setChecked(False)
    assert window._conversion_output_path() == str(tmp_path)

    window.parts_folder_button.setChecked(True)
    window._set_conversion_mode("static_parts")
    assert window._conversion_output_path() == str(tmp_path / "Tree_StaticParts")

    window._set_conversion_mode("static_assembly")
    assert window.parts_folder_button.isHidden()
    assert window._conversion_output_path() == str(output_path)


@pytest.mark.parametrize("mode", ("skeletal_parts", "static_parts"))
def test_parts_conversion_reports_when_all_sources_are_unreal_references(
    qtbot, tmp_path, monkeypatch, mode
) -> None:
    window = MainWindow(
        load_theme(),
        UiShellState(width=1160, height=780, help_prompt_dismissed=True),
        dependencies=build_default_dependencies(),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    unreal_row = GeometryRowState(
        source_key="Mesh_1",
        source_name="FernLeaf",
        source_mesh_id=1,
        instance_count=347,
        source_mode=PrototypeSourceMode.UNREAL_ASSET,
        unreal_asset_path="/Game/Assembly/FernLeaf.FernLeaf",
        fbx_path="",
    )
    monkeypatch.setattr(window.geometry_panel, "current_snapshot", lambda: {unreal_row.source_key: unreal_row})
    monkeypatch.setattr(window, "_prepare_current_conversion_plan", lambda: pytest.fail("conversion must not start"))

    window._set_conversion_mode(mode)
    window.run_conversion()

    assert window.program_status_card.state_label.text() == "Ready"
    assert window.status_label.text() == "Nothing to export: all parts use Unreal Reference."

    xml_row = GeometryRowState(
        source_key="Mesh_2",
        source_name="FernStem",
        source_mesh_id=2,
        instance_count=1,
        source_mode=PrototypeSourceMode.XML_MESH,
        unreal_asset_path="",
        fbx_path="",
    )
    monkeypatch.setattr(
        window.geometry_panel,
        "current_snapshot",
        lambda: {unreal_row.source_key: unreal_row, xml_row.source_key: xml_row},
    )
    monkeypatch.setattr(
        window,
        "_prepare_current_conversion_plan",
        lambda: SimpleNamespace(request="request", run_async=False),
    )
    started = []
    monkeypatch.setattr(window._background_jobs, "start_conversion", lambda **kwargs: started.append(kwargs))

    window.run_conversion()

    assert started == [{"request": "request", "run_async": False}]
