from __future__ import annotations

import zipfile
from pathlib import Path

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox

from xml_to_usda.conversion_service import ConversionLaunchPlan
from xml_to_usda.discovery_service import (
    BaseMaterialDiscovery,
    BaseMaterialRowSpec,
    PrototypeDiscovery,
    PrototypeMaterialSlotRowSpec,
    PrototypeRowSpec,
)
from xml_to_usda.models import (
    CleanupPolicy,
    ConversionPhase,
    ConversionRequest,
    ConversionResult,
    ConversionTelemetry,
    ConversionMode,
    CpuProfile,
    DynamicWindData,
    DynamicWindJointAssignment,
    DynamicWindSimulationGroup,
    FbxMaterialMode,
    MaterialPolicy,
    PrototypeSourceMode,
    UsdAssemblyDocument,
    WindJsonResult,
)
from xml_to_usda.qt_ui.dependencies import QtUiDependencies
from xml_to_usda.qt_ui.persistence import UiShellState, load_ui_shell_state
from xml_to_usda.qt_ui.theme import load_theme
from xml_to_usda.qt_ui.window import MainWindow
from xml_to_usda.runtime_paths import RuntimePaths
from xml_to_usda.settings_service import (
    GuiPresetRecord,
    GuiSettingsSnapshot,
    load_gui_preset,
    load_gui_settings,
    save_gui_preset,
    save_gui_settings,
)
from xml_to_usda.wind_service import WindGenerationRequest, WindInspectionPlan, WindInspectionRequest


def _build_fake_deps(calls: dict[str, object]) -> QtUiDependencies:
    def prepare_conversion_plan(**kwargs):
        calls["prepare_conversion_plan"] = kwargs
        request = ConversionRequest(
            input_paths=(kwargs["input_path"],),
            output_path=kwargs["output_path"],
            cpu_profile=kwargs["cpu_profile"],
            cleanup_policy=kwargs["cleanup_policy"],
            material_policy=kwargs["material_policy"],
            bark_material_path=kwargs["bark_material_path"],
            leaves_material_path=kwargs["leaves_material_path"],
            single_material_path=kwargs["single_material_path"],
            conversion_mode=kwargs["conversion_mode"],
        )
        return ConversionLaunchPlan(request=request, run_async=False)

    def convert_request(request, telemetry_callback=None, cancel_event=None, runtime_paths=None):
        calls["convert_request"] = {
            "request": request,
            "runtime_paths": runtime_paths,
            "cancel_event": cancel_event,
        }
        if telemetry_callback is not None:
            telemetry_callback(
                ConversionTelemetry(
                    phase=ConversionPhase.USDA_WRITING,
                    completed_units=1,
                    total_units=1,
                    message="Writing USDA",
                    elapsed_seconds=0.1,
                )
            )
        return (
            ConversionResult(
                input_path=request.input_paths[0],
                output_path=request.output_path,
                diagnostics=(),
                usda_document=UsdAssemblyDocument(text="#usda 1.0", diagnostics=()),
            ),
        )

    def prepare_wind_inspection_plan(**kwargs):
        calls["prepare_wind_inspection_plan"] = kwargs
        return WindInspectionPlan(
            request=WindInspectionRequest(
                input_path=kwargs["input_path"],
                is_ground_cover=kwargs["is_ground_cover"],
            ),
            run_async=False,
        )

    def inspect_wind_groups(request):
        calls["inspect_wind_groups"] = request
        return DynamicWindData(
            joint_assignments=(DynamicWindJointAssignment(joint_name="Root", simulation_group_index=0, branch_order=0),),
            simulation_groups=(DynamicWindSimulationGroup(group_index=0, branch_order=0, is_trunk_group=True),),
            is_ground_cover=request.is_ground_cover,
            gust_attenuation=0.0,
        )

    def derive_wind_json_output_path(input_path: str, output_path: str) -> Path:
        calls["derive_wind_json_output_path"] = (input_path, output_path)
        return Path(output_path).with_name(f"{Path(output_path).stem}_DynamicWind.json")

    def generate_wind_json_from_request(request):
        calls["generate_wind_json_from_request"] = request
        return WindJsonResult(
            input_path=request.input_path,
            output_path=request.output_path,
            dynamic_wind=DynamicWindData(
                joint_assignments=(DynamicWindJointAssignment(joint_name="Root", simulation_group_index=0, branch_order=0),),
                simulation_groups=request.group_settings,
                is_ground_cover=request.is_ground_cover,
                gust_attenuation=request.gust_attenuation,
            ),
        )

    def discover_base_material_rows(input_path, persisted_records=()):
        calls["discover_base_material_rows"] = {
            "input_path": input_path,
            "persisted_records": persisted_records,
        }
        return BaseMaterialDiscovery(
            summary="Found 1 base XML material slot(s).",
            rows=(BaseMaterialRowSpec(source_id=7, source_name="Bark"),),
        )

    def discover_part_prototype_rows(input_path, persisted_records=()):
        calls["discover_part_prototype_rows"] = {
            "input_path": input_path,
            "persisted_records": persisted_records,
        }
        return PrototypeDiscovery(
            summary="Found 3 repeated branch instances across 1 prototype(s).",
            rows=(
                PrototypeRowSpec(
                    source_key="Mesh_7",
                    source_name="BranchCluster",
                    source_mesh_id=7,
                    instance_count=3,
                    source_mode=PrototypeSourceMode.XML_MESH,
                    fbx_material_mode=FbxMaterialMode.VERTEX_COLOR_SPLIT,
                ),
            ),
        )

    def inspect_fbx_material_slot_rows(fbx_path, cpu_profile, persisted_records=()):
        calls["inspect_fbx_material_slot_rows"] = {
            "fbx_path": fbx_path,
            "cpu_profile": cpu_profile,
            "persisted_records": persisted_records,
        }
        return (
            PrototypeMaterialSlotRowSpec(
                slot_name="MatSlot_01",
                face_count=12,
                ue_asset_path="",
            ),
        )

    return QtUiDependencies(
        prepare_conversion_plan=prepare_conversion_plan,
        start_conversion_process=lambda request, runtime_paths=None: (_ for _ in ()).throw(AssertionError("unexpected async process")),
        close_process_queue=lambda queue: None,
        drain_process_queue=lambda queue: [],
        convert_request=convert_request,
        discover_base_material_rows=discover_base_material_rows,
        discover_part_prototype_rows=discover_part_prototype_rows,
        inspect_fbx_material_slot_rows=inspect_fbx_material_slot_rows,
        load_gui_settings=load_gui_settings,
        save_gui_settings=save_gui_settings,
        resolve_input_settings_key=lambda input_path: input_path,
        prepare_wind_inspection_plan=prepare_wind_inspection_plan,
        inspect_wind_groups=inspect_wind_groups,
        WindGenerationRequest=WindGenerationRequest,
        generate_wind_json_from_request=generate_wind_json_from_request,
        derive_wind_json_output_path=derive_wind_json_output_path,
        format_wind_error=lambda payload: f"{payload.get('type', 'Exception')}: {payload.get('message', '')}",
        should_retry_wind_error=lambda error_type, message: False,
        sys=__import__("sys"),
    )


def test_qt_window_runs_sync_conversion_through_services(monkeypatch, qtbot, tmp_path) -> None:
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

    calls: dict[str, object] = {}
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=_build_fake_deps(calls),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    tree_xml = tmp_path / "tree.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    window.source_input.setText(str(tree_xml))
    window.output_input.setText(str(tmp_path / "tree.usda"))
    qtbot.mouseClick(window.convert_button, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(lambda: "Wrote USDA to" in window.status_label.text(), timeout=3000)

    assert "convert_request" in calls
    assert "Status: success" in window._log_text
    assert window.geometry_panel.has_rows() is True


def test_qt_window_passes_selected_conversion_mode_to_conversion_request(monkeypatch, qtbot, tmp_path) -> None:
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

    calls: dict[str, object] = {}
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=_build_fake_deps(calls),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    tree_xml = tmp_path / "tree.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    window.source_input.setText(str(tree_xml))
    window.output_input.setText(str(tmp_path / "tree.usda"))
    window._conversion_mode_actions["skeletal_parts"].trigger()
    qtbot.mouseClick(window.convert_button, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(lambda: "Wrote USDA to" in window.status_label.text(), timeout=3000)

    request = calls["convert_request"]["request"]
    assert calls["prepare_conversion_plan"]["conversion_mode"] == ConversionMode.SKELETAL_PARTS
    assert request.conversion_mode == ConversionMode.SKELETAL_PARTS


def test_qt_window_passes_static_assembly_mode_to_conversion_request(monkeypatch, qtbot, tmp_path) -> None:
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

    calls: dict[str, object] = {}
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=_build_fake_deps(calls),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    tree_xml = tmp_path / "tree.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    window.source_input.setText(str(tree_xml))
    window.output_input.setText(str(tmp_path / "tree.usda"))
    window._conversion_mode_actions["static_assembly"].trigger()
    qtbot.mouseClick(window.convert_button, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(lambda: "Wrote USDA to" in window.status_label.text(), timeout=3000)

    request = calls["convert_request"]["request"]
    assert calls["prepare_conversion_plan"]["conversion_mode"] == ConversionMode.STATIC_ASSEMBLY
    assert request.conversion_mode == ConversionMode.STATIC_ASSEMBLY


def test_qt_window_saves_and_applies_named_preset(monkeypatch, qtbot, tmp_path) -> None:
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

    settings_path = tmp_path / "gui_settings.json"
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=_build_fake_deps({}),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=settings_path,
    )
    qtbot.addWidget(window)
    window.show()

    tree_xml = tmp_path / "tree.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    window.source_input.setText(str(tree_xml))
    window.output_input.setText(str(tmp_path / "tree.usda"))
    window._conversion_mode_actions["static_assembly"].trigger()
    window.wind_panel.gust_spin.setValue(0.5)

    window._save_preset_with_name("Static Grass")

    saved = load_gui_settings(settings_path)
    assert "Static Grass" in saved.presets
    assert saved.presets["Static Grass"].conversion_mode == ConversionMode.STATIC_ASSEMBLY
    assert saved.presets["Static Grass"].gust_attenuation == pytest.approx(0.5)

    window._conversion_mode_actions["skeletal_parts"].trigger()
    window.wind_panel.gust_spin.setValue(0.1)
    window.preset_combo.setCurrentIndex(window.preset_combo.findData("Factory Defaults"))
    preset_index = window.preset_combo.findData("Static Grass")
    window.preset_combo.setCurrentIndex(preset_index)

    assert window._operator_state.conversion_mode == ConversionMode.STATIC_ASSEMBLY
    assert window.wind_panel.gust_attenuation() == pytest.approx(0.5)


def test_qt_window_overwrites_deletes_and_resets_presets(monkeypatch, qtbot, tmp_path) -> None:
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

    settings_path = tmp_path / "gui_settings.json"
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=_build_fake_deps({}),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=settings_path,
    )
    qtbot.addWidget(window)
    window.show()

    window._conversion_mode_actions["static_assembly"].trigger()
    window.wind_panel.gust_spin.setValue(0.5)
    window._save_preset_with_name("Reusable")

    window._conversion_mode_actions["skeletal_parts"].trigger()
    window.wind_panel.gust_spin.setValue(0.25)
    window._overwrite_current_preset()

    overwritten = load_gui_settings(settings_path).presets["Reusable"]
    assert overwritten.conversion_mode == ConversionMode.SKELETAL_PARTS
    assert overwritten.gust_attenuation == pytest.approx(0.25)

    window._reset_to_factory_defaults()

    assert window._current_preset_name() == "Factory Defaults"
    assert window._operator_state.conversion_mode == ConversionMode.SKELETAL_ASSEMBLY
    assert window.wind_panel.gust_attenuation() == pytest.approx(0.0)

    window.preset_combo.setCurrentIndex(window.preset_combo.findData("Reusable"))
    window._delete_current_preset()
    saved = load_gui_settings(settings_path)

    assert "Reusable" not in saved.presets
    assert saved.active_preset_name == "Factory Defaults"
    assert window._current_preset_name() == "Factory Defaults"


def test_qt_window_imports_and_exports_presets(monkeypatch, qtbot, tmp_path) -> None:
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

    import_path = tmp_path / "imported.json"
    export_stem_path = tmp_path / "exported_preset"
    imported = GuiPresetRecord(
        name="Imported Branches",
        conversion_mode=ConversionMode.SKELETAL_PARTS,
        material_policy=MaterialPolicy.SINGLE_MATERIAL,
        single_material_path="/Game/M_All.M_All",
        gust_attenuation=0.75,
    )
    save_gui_preset(import_path, imported)

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *args, **kwargs: (str(import_path), "")))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *args, **kwargs: (str(export_stem_path), "")))

    settings_path = tmp_path / "gui_settings.json"
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=_build_fake_deps({}),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=settings_path,
    )
    qtbot.addWidget(window)
    window.show()

    window._import_preset()

    saved = load_gui_settings(settings_path)
    assert saved.presets["Imported Branches"] == imported
    assert window._current_preset_name() == "Imported Branches"
    assert window._operator_state.conversion_mode == ConversionMode.SKELETAL_PARTS
    assert window.wind_panel.gust_attenuation() == pytest.approx(0.75)

    window._export_current_preset()

    exported_path = export_stem_path.with_suffix(".json")
    assert exported_path.exists()
    assert load_gui_preset(exported_path) == imported


def test_qt_window_hides_irrelevant_geometry_path_fields(qtbot, tmp_path) -> None:
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=_build_fake_deps({}),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    tree_xml = tmp_path / "tree.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    window.source_input.setText(str(tree_xml))
    row = window.geometry_panel._rows[0]

    assert row.asset_edit.isHidden()
    assert row.fbx_edit.isHidden()

    row.source_mode_combo.setCurrentIndex(row.source_mode_combo.findData(PrototypeSourceMode.UNREAL_ASSET.value))
    assert not row.asset_edit.isHidden()
    assert row.fbx_edit.isHidden()
    assert row.browse_button.isHidden()

    row.source_mode_combo.setCurrentIndex(row.source_mode_combo.findData(PrototypeSourceMode.FBX_FILE.value))
    assert row.asset_edit.isHidden()
    assert not row.fbx_edit.isHidden()
    assert not row.browse_button.isHidden()


def test_qt_window_hides_irrelevant_part_material_path_fields(qtbot, tmp_path) -> None:
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=_build_fake_deps({}),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    tree_xml = tmp_path / "tree.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    window.source_input.setText(str(tree_xml))
    row = window.materials_panel._part_rows[0]

    assert not row.black_edit.isHidden()
    assert not row.white_edit.isHidden()
    assert row.single_edit.isHidden()

    row.material_mode_combo.setCurrentIndex(row.material_mode_combo.findData(FbxMaterialMode.SINGLE_MATERIAL.value))
    assert not row.single_edit.isHidden()
    assert row.black_edit.isHidden()
    assert row.white_edit.isHidden()

    geometry_row = window.geometry_panel._rows[0]
    geometry_row.source_mode_combo.setCurrentIndex(
        geometry_row.source_mode_combo.findData(PrototypeSourceMode.UNREAL_ASSET.value)
    )
    assert row.material_mode_combo.isHidden()
    assert row.single_edit.isHidden()
    assert row.black_edit.isHidden()
    assert row.white_edit.isHidden()


def test_qt_window_refreshes_wind_and_generates_json(monkeypatch, qtbot, tmp_path) -> None:
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

    calls: dict[str, object] = {}
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=_build_fake_deps(calls),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    tree_xml = tmp_path / "tree.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    window.source_input.setText(str(tree_xml))
    window.output_input.setText(str(tmp_path / "tree.usda"))

    qtbot.mouseClick(window.wind_panel.refresh_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "Loaded 1 wind groups." in window.status_label.text(), timeout=3000)

    assert "Wind groups detected: 1" in window._log_text
    assert "inspect_wind_groups" in calls

    window.wind_panel.ground_cover_checkbox.setChecked(True)
    window.wind_panel.gust_spin.setValue(0.6)
    trunk_checkbox = window.wind_panel._rows[0].trunk_checkbox
    trunk_checkbox.setChecked(False)

    qtbot.mouseClick(window.generate_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "Wrote Dynamic Wind JSON" in window.status_label.text(), timeout=3000)

    assert "generate_wind_json_from_request" in calls
    request = calls["generate_wind_json_from_request"]
    assert request.gust_attenuation == pytest.approx(0.6)
    assert request.is_ground_cover is True
    assert request.group_settings[0].is_trunk_group is False
    assert "Wind groups: 1" in window._log_text


def test_qt_window_autofills_output_path_from_selected_xml(qtbot, tmp_path) -> None:
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=_build_fake_deps({}),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    tree_xml = tmp_path / "spruce.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    window.source_input.setText(str(tree_xml))

    assert window.output_input.text() == str(tree_xml.with_suffix(".usda"))


def test_qt_window_preserves_manual_output_folder_and_updates_stem(qtbot, tmp_path) -> None:
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=_build_fake_deps({}),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    first_xml = tmp_path / "inputs" / "spruce.xml"
    second_xml = tmp_path / "other_inputs" / "cedar.xml"
    output_path = tmp_path / "exports" / "custom_name.usda"
    first_xml.parent.mkdir()
    second_xml.parent.mkdir()
    output_path.parent.mkdir()
    first_xml.write_text("<tree/>", encoding="utf-8")
    second_xml.write_text("<tree/>", encoding="utf-8")

    window.source_input.setText(str(first_xml))
    window.output_input.setText(str(output_path))
    window.source_input.setText(str(second_xml))

    assert window.output_input.text() == str(output_path.with_name("cedar.usda"))


def test_qt_window_uses_remembered_xml_and_output_folders_for_browse_dialogs(monkeypatch, qtbot, tmp_path) -> None:
    settings_path = tmp_path / "gui_settings.json"
    remembered_xml = tmp_path / "xml_folder" / "last.xml"
    remembered_output = tmp_path / "output_folder" / "last.usda"
    selected_xml = tmp_path / "new_xml_folder" / "selected.xml"
    selected_output = tmp_path / "new_output_folder" / "chosen.usda"
    for path in (remembered_xml, remembered_output, selected_xml, selected_output):
        path.parent.mkdir(exist_ok=True)
    remembered_xml.write_text("<tree/>", encoding="utf-8")
    selected_xml.write_text("<tree/>", encoding="utf-8")
    save_gui_settings(
        settings_path,
        GuiSettingsSnapshot(
            last_input_path=str(remembered_xml),
            last_output_path=str(remembered_output),
        ),
    )
    observed: dict[str, str] = {}

    def fake_open_file_name(parent, title, directory, filters):
        observed["input_directory"] = directory
        return str(selected_xml), ""

    def fake_save_file_name(parent, title, directory, filters):
        observed["output_directory"] = directory
        return str(selected_output), ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(fake_open_file_name))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(fake_save_file_name))

    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=_build_fake_deps({}),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=settings_path,
    )
    qtbot.addWidget(window)
    window.show()

    window.browse_input()
    window.browse_output()
    saved = load_gui_settings(settings_path)

    assert Path(observed["input_directory"]) == remembered_xml.parent
    assert Path(observed["output_directory"]) == remembered_output
    assert saved.last_input_path == str(selected_xml)
    assert saved.last_output_path == str(selected_output)


def test_qt_window_shows_and_persists_dismissed_first_launch_tutorial_callout(qtbot, tmp_path) -> None:
    state_path = tmp_path / "ui_next_state.json"
    window = MainWindow(
        load_theme(),
        UiShellState(help_prompt_dismissed=False),
        dependencies=_build_fake_deps({}),
        state_path=state_path,
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    assert window.help_callout.isVisible()
    assert "Start here for the tutorial" in window.help_callout_title.text()
    assert window.help_callout.y() > window.title_bar.y()

    qtbot.mouseClick(window.help_callout_dismiss_button, Qt.MouseButton.LeftButton)

    assert window.help_callout.isHidden()
    window.close()
    restored = load_ui_shell_state(state_path)
    assert restored.help_prompt_dismissed is True


def test_qt_window_opens_slide_style_help_deck_with_topics_and_arrows(qtbot, tmp_path) -> None:
    window = MainWindow(
        load_theme(),
        UiShellState(help_prompt_dismissed=True),
        dependencies=_build_fake_deps({}),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    window.open_help_dialog()
    dialog = window._help_dialog

    assert dialog is not None
    assert dialog.windowTitle() == "How to use"
    assert [button.text() for button in dialog.topic_buttons] == ["Start", "Presets", "Materials", "Run"]
    assert dialog.slide_title_label.text() == "Start"
    assert dialog.previous_button.isEnabled() is False
    assert dialog.next_button.isEnabled() is True

    qtbot.mouseClick(dialog.next_button, Qt.MouseButton.LeftButton)
    assert dialog.slide_title_label.text() == "Presets"
    assert dialog.previous_button.isEnabled() is True

    qtbot.mouseClick(dialog.topic_buttons[2], Qt.MouseButton.LeftButton)
    assert dialog.slide_title_label.text() == "Materials"

    qtbot.mouseClick(dialog.previous_button, Qt.MouseButton.LeftButton)
    assert dialog.slide_title_label.text() == "Presets"


def test_qt_window_support_dialog_exports_diagnostics_bundle(monkeypatch, qtbot, tmp_path) -> None:
    settings_dir = tmp_path / "settings"
    cache_root = tmp_path / "cache"
    jobs_root = cache_root / "jobs"
    settings_path = settings_dir / "gui_settings.json"
    runtime_log_path = settings_dir / "gui_runtime.log"
    build_info_path = tmp_path / "dist-next" / "build_info.json"
    selected_bundle_stem = tmp_path / "operator_support_bundle"
    settings_dir.mkdir()
    jobs_root.mkdir(parents=True)
    build_info_path.parent.mkdir()
    runtime_log_path.write_text("Runtime traceback", encoding="utf-8")
    build_info_path.write_text('{"build_mode": "package"}', encoding="utf-8")
    latest_job = jobs_root / "20260523-090000-latest"
    latest_job.mkdir()
    (latest_job / "job_manifest.json").write_text('{"job_id": "latest"}', encoding="utf-8")
    runtime_paths = RuntimePaths(
        settings_dir=settings_dir,
        settings_path=settings_path,
        cache_root=cache_root,
        jobs_root=jobs_root,
    )

    monkeypatch.setattr("xml_to_usda.qt_ui.window.resolve_runtime_paths", lambda **kwargs: runtime_paths)
    monkeypatch.setattr("xml_to_usda.qt_ui.window.default_build_info_path", lambda: build_info_path)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *args, **kwargs: (str(selected_bundle_stem), "")))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

    window = MainWindow(
        load_theme(),
        UiShellState(help_prompt_dismissed=True),
        dependencies=_build_fake_deps({}),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=settings_path,
    )
    qtbot.addWidget(window)
    window.show()
    tree_xml = tmp_path / "oak.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    window.source_input.setText(str(tree_xml))
    window.output_input.setText(str(tmp_path / "oak.usda"))
    window._append_log("Operator-visible failure context.")

    qtbot.mouseClick(window.title_bar.support_button, Qt.MouseButton.LeftButton)
    dialog = window._support_dialog

    assert dialog is not None
    assert dialog.windowTitle() == "Support / About"
    assert "Diagnostics are local-only" in dialog.summary_label.text()

    qtbot.mouseClick(dialog.export_button, Qt.MouseButton.LeftButton)

    exported_bundle = selected_bundle_stem.with_suffix(".zip")
    assert exported_bundle.exists()
    assert "Diagnostics bundle exported" in window.status_label.text()
    with zipfile.ZipFile(exported_bundle) as archive:
        assert "settings/gui_settings.json" in archive.namelist()
        assert b"Runtime traceback" in archive.read("logs/gui_runtime.log")
        assert b"Operator-visible failure context." in archive.read("logs/in_app_log.txt")
        assert b'"job_id": "latest"' in archive.read("runtime/latest_job_manifest.json")
