from __future__ import annotations

import json
import math
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

pytestmark = pytest.mark.qt

from PySide6.QtCore import Qt
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QFileDialog, QMessageBox

from xml_to_usda.conversion_service import ConversionLaunchPlan
from xml_to_usda.discovery_service import (
    BaseMaterialDiscovery,
    BaseMaterialRowSpec,
    PrototypeDiscovery,
    PrototypeMaterialSlotRowSpec,
    PrototypeRowSpec,
)
from xml_to_usda.fracture_export_service import FractureExportRequest
from xml_to_usda.fracture_preview_service import FracturePreviewSettings, FracturePreviewSourceRequest
from xml_to_usda.fracture_service import FRACTURE_METHOD_MANUAL_FRACTURING, FractureSettings
from xml_to_usda.models import (
    Color4,
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
    GeometryBuffer,
    MaterialPolicy,
    PrototypeSourceMode,
    UsdAssemblyDocument,
    WindJsonResult,
    UdimMode,
)
from xml_to_usda.proxy_mesh_service import ProxyMeshJobResult, ProxyMeshResult, ProxyMeshSettings, ProxyMeshSourceRequest
from xml_to_usda.qt_ui.dependencies import QtUiDependencies
from xml_to_usda.qt_ui.persistence import UiShellState, load_ui_shell_state
from xml_to_usda.qt_ui.proxy_preview import ProxyPreviewDialog, build_preview_cube_mesh
from xml_to_usda.qt_ui.theme import load_theme
from xml_to_usda.qt_ui.window import MainWindow
from xml_to_usda.runtime_paths import RuntimePaths, resolve_runtime_paths
from xml_to_usda.settings_service import (
    GuiPresetRecord,
    GuiSettingsSnapshot,
    load_gui_preset,
    load_gui_settings,
    save_gui_preset,
    save_gui_settings,
)
from xml_to_usda.wind_preview_service import WindPreviewRequest, WindPreviewResult
from xml_to_usda.wind_viewport_scene import build_wind_viewport_groups, build_wind_viewport_scene
from xml_to_usda.wind_service import WindGenerationRequest, WindInspectionPlan, WindInspectionRequest


def _expected_branch_prune_value(slider_value: int) -> float:
    position = max(0.0, min(1.0, float(slider_value) / 100.0))
    return 1.0 - ((1.0 - position) ** 4.0)


def _expected_branch_prune_slider(value: float) -> int:
    clamped = max(0.0, min(1.0, value))
    if clamped <= 0.0:
        return 0
    if clamped >= 1.0:
        return 100
    return int(round((1.0 - math.pow(1.0 - clamped, 0.25)) * 100.0))


def _build_fake_deps(calls: dict[str, object]) -> QtUiDependencies:
    class _FinishedProcess:
        exitcode = 0

        def is_alive(self) -> bool:
            return False

        def join(self, timeout=None) -> None:
            return None

        def terminate(self) -> None:
            return None

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
            base_material_overrides=kwargs["base_material_overrides"],
            udim_material_settings=kwargs["udim_material_settings"],
            prototype_source_configs=kwargs["prototype_source_configs"],
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

    def _fake_proxy_result(settings: ProxyMeshSettings) -> ProxyMeshResult:
        from array import array

        from xml_to_usda.models import GeometryBuffer

        return ProxyMeshResult(
            mesh=GeometryBuffer(
                name="ProxyMesh",
                point_components=array("f", [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0]),
                face_vertex_counts=array("i", [3]),
                face_vertex_indices=array("i", [0, 1, 2]),
            ),
            settings=settings,
            method=settings.method,
            source_instance_count=1,
            included_base_mesh=True,
        )

    def generate_proxy_mesh_from_source_request(request, settings):
        calls["generate_proxy_mesh_from_source_request"] = {
            "request": request,
            "settings": settings,
        }
        return _fake_proxy_result(settings)

    def export_proxy_usda_from_source_request(request, settings):
        calls["export_proxy_usda_from_source_request"] = {
            "request": request,
            "settings": settings,
        }
        class Result:
            input_path = request.input_path
            output_path = str(Path(request.output_path).with_name(f"{Path(request.output_path).stem}_proxy.usda"))
            proxy = _fake_proxy_result(settings)
            usda_text = "#usda 1.0"

        return Result()

    def export_generated_proxy_usda_from_source_request(request, proxy):
        calls["export_generated_proxy_usda_from_source_request"] = {
            "request": request,
            "proxy": proxy,
        }
        class Result:
            input_path = request.input_path
            output_path = str(Path(request.output_path).with_name(f"{Path(request.output_path).stem}_proxy.usda"))
            usda_text = "#usda 1.0"

        return Result()

    def start_proxy_mesh_process(request, settings, action):
        calls.setdefault("start_proxy_mesh_process_events", []).append(
            {
                "request": request,
                "settings": settings,
                "action": action,
            }
        )
        calls["start_proxy_mesh_process"] = {
            "request": request,
            "settings": settings,
            "action": action,
        }
        if action == "preview":
            return _FinishedProcess(), [("result", ProxyMeshJobResult(proxy=generate_proxy_mesh_from_source_request(request, settings)))], object()
        if action != "export":
            raise AssertionError("unexpected proxy process action")
        return _FinishedProcess(), [("result", ProxyMeshJobResult(export=export_proxy_usda_from_source_request(request, settings)))], object()

    def generate_fracture_preview_from_source_request(request, settings, *, telemetry_callback=None, cancel_event=None):
        from array import array
        from dataclasses import replace

        from xml_to_usda.fracture_preview_service import FracturePreviewPiece, FracturePreviewResult
        from xml_to_usda.fracture_service import FracturePiece, FracturePlan

        calls["generate_fracture_preview_from_source_request"] = {
            "request": request,
            "settings": settings,
        }
        output_stem = Path(request.output_path).stem if request.output_path else Path(request.input_path).stem
        settings = replace(settings, fracture=replace(settings.fracture, output_stem=output_stem))
        pieces: list[FracturePreviewPiece] = []
        for index in range(settings.fracture.target_piece_count):
            piece = FracturePiece(
                index=index,
                name=f"{settings.fracture.output_stem}_fracture_{index:02d}",
                is_root_piece=index == 0,
                cut_joint_token=None if index == 0 else f"bone_{index:03d}",
                joint_tokens=(f"bone_{index:03d}",),
                base_face_indices=(index,),
                repeated_part_indices=(),
                repeated_part_names=(),
            )
            pieces.append(
                FracturePreviewPiece(
                    piece=piece,
                    color=Color4(0.2 + index * 0.1, 0.4, 0.8, 1.0),
                    base_mesh=GeometryBuffer(
                        name=piece.name,
                        point_components=array(
                            "f",
                            [
                                float(index),
                                0.0,
                                0.0,
                                float(index) + 0.5,
                                0.0,
                                0.0,
                                float(index),
                                0.5,
                                0.0,
                            ],
                        ),
                        face_vertex_counts=array("i", [3]),
                        face_vertex_indices=array("i", [0, 1, 2]),
                    ),
                )
            )
        plan = FracturePlan(
            method=FRACTURE_METHOD_MANUAL_FRACTURING,
            requested_piece_count=settings.fracture.target_piece_count,
            actual_piece_count=len(pieces),
            output_stem=settings.fracture.output_stem,
            main_axis_joint_tokens=(),
            selected_cut_sites=(),
            rejected_cut_sites=(),
            pieces=tuple(preview_piece.piece for preview_piece in pieces),
            diagnostics=(),
        )
        result = FracturePreviewResult(
            plan=plan,
            pieces=tuple(pieces),
            prototypes={},
            instances=(),
            diagnostics=(),
        )
        from xml_to_usda.fracture_viewport_scene import build_fracture_viewport_scene

        return replace(result, viewport_scene=build_fracture_viewport_scene(result))

    def start_fracture_preview_process(request, settings):
        calls.setdefault("start_fracture_preview_process_events", []).append(
            {
                "request": request,
                "settings": settings,
            }
        )
        calls["start_fracture_preview_process"] = {
            "request": request,
            "settings": settings,
        }
        return _FinishedProcess(), [("result", generate_fracture_preview_from_source_request(request, settings))], object()

    def export_fracture_usda_from_export_request(request, settings):
        from xml_to_usda.fracture_export_service import FractureExportResult, FracturePieceExport
        from xml_to_usda.fracture_service import FracturePiece, FracturePlan

        calls["export_fracture_usda_from_export_request"] = {
            "request": request,
            "settings": settings,
        }
        pieces: list[FracturePiece] = []
        outputs: list[FracturePieceExport] = []
        for index in range(settings.target_piece_count):
            piece = FracturePiece(
                index=index,
                name=f"{Path(request.output_path).stem}_fracture_{index:02d}",
                is_root_piece=index == 0,
                cut_joint_token=None if index == 0 else f"bone_{index:03d}",
                joint_tokens=(f"bone_{index:03d}",),
                base_face_indices=(index,),
                repeated_part_indices=(),
                repeated_part_names=(),
            )
            pieces.append(piece)
            outputs.append(
                FracturePieceExport(
                    piece=piece,
                    output_path=str(Path(request.output_path).with_name(f"{piece.name}.usda")),
                    usda_document=UsdAssemblyDocument(text="#usda 1.0", diagnostics=()),
                )
            )
        plan = FracturePlan(
            method=FRACTURE_METHOD_MANUAL_FRACTURING,
            requested_piece_count=settings.target_piece_count,
            actual_piece_count=len(pieces),
            output_stem=Path(request.output_path).stem,
            main_axis_joint_tokens=(),
            selected_cut_sites=(),
            rejected_cut_sites=(),
            pieces=tuple(pieces),
            diagnostics=(),
        )
        return FractureExportResult(plan=plan, outputs=tuple(outputs), diagnostics=())

    def start_fracture_export_process(request, settings):
        calls["start_fracture_export_process"] = {
            "request": request,
            "settings": settings,
        }
        return _FinishedProcess(), [("result", export_fracture_usda_from_export_request(request, settings))], object()

    def start_part_preview_process(request, settings):
        from xml_to_usda.part_preview_service import PartPrototypePreviewResult

        calls.setdefault("start_part_preview_process_events", []).append(
            {
                "request": request,
                "settings": settings,
            }
        )
        calls["start_part_preview_process"] = {
            "request": request,
            "settings": settings,
        }
        return (
            _FinishedProcess(),
            [
                (
                    "result",
                    PartPrototypePreviewResult(
                        source_key=request.source_key,
                        source_name=request.source_name,
                        source_mode=request.prototype_source_config.mode,
                        mesh=None,
                    ),
                )
            ],
            object(),
        )

    def start_wind_preview_process(request, settings=None):
        from test_wind_viewport_scene import _tree_model

        calls["start_wind_preview_process"] = {"request": request, "settings": settings}
        model = _tree_model()
        dynamic_wind = DynamicWindData(
            joint_assignments=(
                DynamicWindJointAssignment(joint_name="root", simulation_group_index=0, branch_order=0),
                DynamicWindJointAssignment(joint_name="bone_001", simulation_group_index=1, branch_order=1),
                DynamicWindJointAssignment(joint_name="bone_002", simulation_group_index=2, branch_order=2),
            ),
            simulation_groups=(
                DynamicWindSimulationGroup(group_index=0, branch_order=0, is_trunk_group=True),
                DynamicWindSimulationGroup(group_index=1, branch_order=1),
                DynamicWindSimulationGroup(group_index=2, branch_order=2),
            ),
        )
        result = WindPreviewResult(
            input_path=request.input_path,
            source_model=model,
            dynamic_wind=dynamic_wind,
            groups=build_wind_viewport_groups(dynamic_wind),
            diagnostics=(),
            viewport_scene=build_wind_viewport_scene(model, dynamic_wind),
        )
        return _FinishedProcess(), [("result", result)], _CancelFlag()

    def drain_process_queue(queue):
        if isinstance(queue, list):
            events = list(queue)
            queue.clear()
            return events
        return []

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
        start_proxy_mesh_process=start_proxy_mesh_process,
        start_fracture_export_process=start_fracture_export_process,
        start_fracture_preview_process=start_fracture_preview_process,
        start_part_preview_process=start_part_preview_process,
        start_wind_preview_process=start_wind_preview_process,
        close_process_queue=lambda queue: None,
        drain_process_queue=drain_process_queue,
        convert_request=convert_request,
        discover_base_material_rows=discover_base_material_rows,
        discover_part_prototype_rows=discover_part_prototype_rows,
        inspect_fbx_material_slot_rows=inspect_fbx_material_slot_rows,
        load_gui_settings=load_gui_settings,
        save_gui_settings=save_gui_settings,
        prepare_wind_inspection_plan=prepare_wind_inspection_plan,
        inspect_wind_groups=inspect_wind_groups,
        prepare_wind_preview_request=lambda input_path: WindPreviewRequest(input_path=input_path),
        WindGenerationRequest=WindGenerationRequest,
        generate_wind_json_from_request=generate_wind_json_from_request,
        derive_wind_json_output_path=derive_wind_json_output_path,
        generate_proxy_mesh_from_source_request=generate_proxy_mesh_from_source_request,
        export_proxy_usda_from_source_request=export_proxy_usda_from_source_request,
        export_generated_proxy_usda_from_source_request=export_generated_proxy_usda_from_source_request,
        generate_fracture_preview_from_source_request=generate_fracture_preview_from_source_request,
        export_fracture_usda_from_export_request=export_fracture_usda_from_export_request,
        format_wind_error=lambda payload: f"{payload.get('type', 'Exception')}: {payload.get('message', '')}",
        should_retry_wind_error=lambda error_type, message: False,
        sys=__import__("sys"),
    )


class _RunningProcess:
    exitcode = None

    def __init__(self) -> None:
        self.terminated = False

    def is_alive(self) -> bool:
        return not self.terminated

    def join(self, timeout=None) -> None:
        return None

    def terminate(self) -> None:
        self.terminated = True


class _FinishedProcess:
    exitcode = 0

    def is_alive(self) -> bool:
        return False

    def join(self, timeout=None) -> None:
        return None

    def terminate(self) -> None:
        return None


class _CancelFlag:
    def __init__(self) -> None:
        self.was_set = False

    def set(self) -> None:
        self.was_set = True

    def is_set(self) -> bool:
        return self.was_set


def _select_conversion_mode(window: MainWindow, mode_key: str) -> None:
    window._conversion_mode_actions[mode_key].trigger()


def _current_conversion_mode(window: MainWindow) -> ConversionMode:
    return window._operator_state.conversion_mode


def _current_preset_name(window: MainWindow) -> str:
    return str(window.preset_combo.currentData() or "Factory Defaults")


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
    qtbot.waitUntil(lambda: "Loaded 1 wind groups." in window.status_label.text(), timeout=3000)
    qtbot.mouseClick(window.convert_button, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(lambda: "Wrote USDA to" in window.status_label.text(), timeout=3000)

    assert "convert_request" in calls
    assert "Wrote USDA to" in window.status_label.text()
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
    qtbot.waitUntil(lambda: "Loaded 1 wind groups." in window.status_label.text(), timeout=3000)
    _select_conversion_mode(window, "skeletal_parts")
    qtbot.mouseClick(window.convert_button, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(lambda: "Wrote USDA to" in window.status_label.text(), timeout=3000)

    request = calls["convert_request"]["request"]
    assert calls["prepare_conversion_plan"]["conversion_mode"] == ConversionMode.SKELETAL_PARTS
    assert "Wrote USDA to" in window.status_label.text()
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
    qtbot.waitUntil(lambda: "Loaded 1 wind groups." in window.status_label.text(), timeout=3000)
    _select_conversion_mode(window, "static_assembly")
    qtbot.mouseClick(window.convert_button, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(lambda: "Wrote USDA to" in window.status_label.text(), timeout=3000)

    request = calls["convert_request"]["request"]
    assert calls["prepare_conversion_plan"]["conversion_mode"] == ConversionMode.STATIC_ASSEMBLY
    assert "Wrote USDA to" in window.status_label.text()
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
    _select_conversion_mode(window, "static_assembly")
    window.wind_panel.gust_spin.setValue(0.5)

    window._save_preset_with_name("Static Grass")

    saved = load_gui_settings(settings_path)
    assert "Static Grass" in saved.presets
    assert saved.presets["Static Grass"].conversion_mode == ConversionMode.STATIC_ASSEMBLY
    assert saved.presets["Static Grass"].gust_attenuation == pytest.approx(0.5)

    _select_conversion_mode(window, "skeletal_parts")
    window.wind_panel.gust_spin.setValue(0.1)
    window.preset_combo.setCurrentIndex(window.preset_combo.findData("Factory Defaults"))
    preset_index = window.preset_combo.findData("Static Grass")
    window.preset_combo.setCurrentIndex(preset_index)

    assert _current_conversion_mode(window) == ConversionMode.STATIC_ASSEMBLY
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

    _select_conversion_mode(window, "static_assembly")
    window.wind_panel.gust_spin.setValue(0.5)
    window._save_preset_with_name("Reusable")

    _select_conversion_mode(window, "skeletal_parts")
    window.wind_panel.gust_spin.setValue(0.25)
    window._overwrite_current_preset()

    overwritten = load_gui_settings(settings_path).presets["Reusable"]
    assert overwritten.conversion_mode == ConversionMode.SKELETAL_PARTS
    assert overwritten.gust_attenuation == pytest.approx(0.25)

    window._reset_to_factory_defaults()

    assert _current_preset_name(window) == "Factory Defaults"
    assert _current_conversion_mode(window) == ConversionMode.SKELETAL_ASSEMBLY
    assert window.wind_panel.gust_attenuation() == pytest.approx(0.0)

    window.preset_combo.setCurrentIndex(window.preset_combo.findData("Reusable"))
    window._delete_current_preset()
    saved = load_gui_settings(settings_path)

    assert "Reusable" not in saved.presets
    assert saved.active_preset_name == "Factory Defaults"
    assert _current_preset_name(window) == "Factory Defaults"


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
    assert _current_preset_name(window) == "Imported Branches"
    assert _current_conversion_mode(window) == ConversionMode.SKELETAL_PARTS
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


def test_qt_window_part_preview_apply_updates_geometry_materials_and_settings(qtbot, tmp_path) -> None:
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
    fake_fbx = tmp_path / "twig.fbx"
    fake_fbx.write_bytes(b"fake")
    window.source_input.setText(str(tree_xml))

    row = window.geometry_panel._rows[0]
    row.preview_button.click()
    qtbot.waitUntil(lambda: window._part_preview_dialog is not None)
    dialog = window._part_preview_dialog

    dialog.editor.source_mode_combo.setCurrentIndex(
        dialog.editor.source_mode_combo.findData(PrototypeSourceMode.FBX_FILE.value)
    )
    dialog.editor.fbx_path_edit.setText(str(fake_fbx))
    dialog.editor.material_mode_combo.setCurrentIndex(
        dialog.editor.material_mode_combo.findData(FbxMaterialMode.SINGLE_MATERIAL.value)
    )
    dialog.editor.single_row.path_edit.setText("/Game/Test/M_Twig.M_Twig")
    dialog.editor.simplification_slider.setValue(45)
    dialog.apply_button.click()

    snapshot = window.geometry_panel.current_snapshot()["Mesh_7"]
    assert snapshot.source_mode == PrototypeSourceMode.FBX_FILE
    assert snapshot.fbx_path == str(fake_fbx)

    records = window.materials_panel.serialize_part_source_records()
    assert records[0].source_key == "Mesh_7"
    assert records[0].fbx_material_mode == FbxMaterialMode.SINGLE_MATERIAL
    assert records[0].single_material_path == "/Game/Test/M_Twig.M_Twig"
    assert records[0].simplification_percent == 45

    qtbot.waitUntil(lambda: bool(load_gui_settings(settings_path).part_mesh_settings))
    saved = load_gui_settings(settings_path)
    assert saved.part_mesh_settings[0].single_material_path == "/Game/Test/M_Twig.M_Twig"
    assert saved.part_mesh_settings[0].simplification_percent == 45


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
    assert not row.black_udim_mode_combo.isHidden()
    assert not row.black_udim_id_spin.isHidden()
    assert not row.white_udim_mode_combo.isHidden()
    assert not row.white_udim_id_spin.isHidden()
    assert row.single_udim_mode_combo.isHidden()
    assert row.single_udim_id_spin.isHidden()

    row.material_mode_combo.setCurrentIndex(row.material_mode_combo.findData(FbxMaterialMode.SINGLE_MATERIAL.value))
    assert not row.single_edit.isHidden()
    assert row.black_edit.isHidden()
    assert row.white_edit.isHidden()
    assert not row.single_udim_mode_combo.isHidden()
    assert not row.single_udim_id_spin.isHidden()
    assert row.black_udim_mode_combo.isHidden()
    assert row.black_udim_id_spin.isHidden()
    assert row.white_udim_mode_combo.isHidden()
    assert row.white_udim_id_spin.isHidden()

    geometry_row = window.geometry_panel._rows[0]
    geometry_row.source_mode_combo.setCurrentIndex(
        geometry_row.source_mode_combo.findData(PrototypeSourceMode.UNREAL_ASSET.value)
    )
    assert row.material_mode_combo.isHidden()
    assert row.single_edit.isHidden()
    assert row.black_edit.isHidden()
    assert row.white_edit.isHidden()
    assert row.single_udim_mode_combo.isHidden()
    assert row.single_udim_id_spin.isHidden()
    assert row.black_udim_mode_combo.isHidden()
    assert row.black_udim_id_spin.isHidden()
    assert row.white_udim_mode_combo.isHidden()
    assert row.white_udim_id_spin.isHidden()


def test_qt_window_serializes_udim_settings_for_part_material_rows(monkeypatch, qtbot, tmp_path) -> None:
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

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

    row.single_edit.setText("/Game/Test/M_Single.M_Single")
    row.single_udim_mode_combo.setCurrentIndex(row.single_udim_mode_combo.findData(UdimMode.SHIFT_PRIMARY_UV.value))
    row.single_udim_id_spin.setValue(1003)
    row.black_edit.setText("/Game/Test/M_Black.M_Black")
    row.black_udim_mode_combo.setCurrentIndex(row.black_udim_mode_combo.findData(UdimMode.WRITE_SECONDARY_UV_OFFSET.value))
    row.black_udim_id_spin.setValue(1028)
    row.white_edit.setText("/Game/Test/M_White.M_White")
    row.white_udim_mode_combo.setCurrentIndex(row.white_udim_mode_combo.findData(UdimMode.OFF.value))
    row.white_udim_id_spin.setValue(1001)

    records = window.materials_panel.serialize_part_source_records()
    assert records[0].single_material_path == "/Game/Test/M_Single.M_Single"
    assert records[0].single_material_udim_mode == UdimMode.SHIFT_PRIMARY_UV
    assert records[0].single_material_udim_id == 1003
    assert records[0].black_material_path == "/Game/Test/M_Black.M_Black"
    assert records[0].black_material_udim_mode == UdimMode.WRITE_SECONDARY_UV_OFFSET
    assert records[0].black_material_udim_id == 1028
    assert records[0].white_material_path == "/Game/Test/M_White.M_White"
    assert records[0].white_material_udim_mode == UdimMode.OFF
    assert records[0].white_material_udim_id == 1001


def test_qt_window_collects_part_material_udim_settings_for_conversion_request(monkeypatch, qtbot, tmp_path) -> None:
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

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

    row.black_edit.setText("/Game/Test/M_Black.M_Black")
    row.black_udim_mode_combo.setCurrentIndex(row.black_udim_mode_combo.findData(UdimMode.WRITE_SECONDARY_UV_OFFSET.value))
    row.black_udim_id_spin.setValue(1028)
    row.white_edit.setText("/Game/Test/M_White.M_White")
    row.white_udim_mode_combo.setCurrentIndex(row.white_udim_mode_combo.findData(UdimMode.SHIFT_PRIMARY_UV.value))
    row.white_udim_id_spin.setValue(1003)

    configs = window.materials_panel.collect_prototype_source_configs()
    assert configs[0].black_material_path == "/Game/Test/M_Black.M_Black"
    assert configs[0].black_material_udim_mode == UdimMode.WRITE_SECONDARY_UV_OFFSET
    assert configs[0].black_material_udim_id == 1028
    assert configs[0].white_material_path == "/Game/Test/M_White.M_White"
    assert configs[0].white_material_udim_mode == UdimMode.SHIFT_PRIMARY_UV
    assert configs[0].white_material_udim_id == 1003


def test_qt_window_collects_udim_only_part_rows_for_conversion_request(monkeypatch, qtbot, tmp_path) -> None:
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

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

    row.black_udim_mode_combo.setCurrentIndex(row.black_udim_mode_combo.findData(UdimMode.WRITE_SECONDARY_UV_OFFSET.value))
    row.black_udim_id_spin.setValue(1028)
    row.white_udim_mode_combo.setCurrentIndex(row.white_udim_mode_combo.findData(UdimMode.SHIFT_PRIMARY_UV.value))
    row.white_udim_id_spin.setValue(1003)

    configs = window.materials_panel.collect_prototype_source_configs()
    assert len(configs) == 1
    assert configs[0].black_material_path is None
    assert configs[0].black_material_udim_mode == UdimMode.WRITE_SECONDARY_UV_OFFSET
    assert configs[0].black_material_udim_id == 1028
    assert configs[0].white_material_path is None
    assert configs[0].white_material_udim_mode == UdimMode.SHIFT_PRIMARY_UV
    assert configs[0].white_material_udim_id == 1003


def test_qt_window_serializes_udim_only_part_rows(monkeypatch, qtbot, tmp_path) -> None:
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

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

    row.black_udim_mode_combo.setCurrentIndex(row.black_udim_mode_combo.findData(UdimMode.WRITE_SECONDARY_UV_OFFSET.value))
    row.black_udim_id_spin.setValue(1028)

    records = window.materials_panel.serialize_part_source_records()
    assert len(records) == 1
    assert records[0].black_material_path == ""
    assert records[0].black_material_udim_mode == UdimMode.WRITE_SECONDARY_UV_OFFSET
    assert records[0].black_material_udim_id == 1028


def test_qt_window_serializes_udim_settings_for_fbx_material_slot_rows(monkeypatch, qtbot, tmp_path) -> None:
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

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
    fake_fbx = tmp_path / "branch.fbx"
    fake_fbx.write_text("", encoding="utf-8")
    window.source_input.setText(str(tree_xml))

    geometry_row = window.geometry_panel._rows[0]
    geometry_row.fbx_edit.setText(str(fake_fbx))
    geometry_row.source_mode_combo.setCurrentIndex(
        geometry_row.source_mode_combo.findData(PrototypeSourceMode.FBX_FILE.value)
    )

    row = window.materials_panel._part_rows[0]
    row.material_mode_combo.setCurrentIndex(row.material_mode_combo.findData(FbxMaterialMode.MATERIAL_SLOTS.value))
    qtbot.waitUntil(lambda: len(row.slot_rows) == 1, timeout=3000)
    slot_row = row.slot_rows[0]
    slot_row.path_edit.setText("/Game/Test/M_Slot.M_Slot")
    slot_row.udim_mode_combo.setCurrentIndex(slot_row.udim_mode_combo.findData(UdimMode.WRITE_SECONDARY_UV_OFFSET.value))
    slot_row.udim_id_spin.setValue(1028)

    records = window.materials_panel.serialize_part_source_records()
    assert records[0].fbx_material_mode == FbxMaterialMode.MATERIAL_SLOTS
    assert records[0].fbx_material_slot_overrides[0].ue_asset_path == "/Game/Test/M_Slot.M_Slot"
    assert records[0].fbx_material_slot_overrides[0].udim_mode == UdimMode.WRITE_SECONDARY_UV_OFFSET
    assert records[0].fbx_material_slot_overrides[0].udim_id == 1028


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


def test_qt_window_opens_read_only_wind_preview_from_xml(monkeypatch, qtbot, tmp_path) -> None:
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

    qtbot.waitUntil(lambda: window.wind_panel.preview_button.isEnabled(), timeout=3000)
    qtbot.mouseClick(window.wind_panel.preview_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "Wind Preview ready: 3 group(s)." in window.status_label.text(), timeout=3000)

    request = calls["start_wind_preview_process"]["request"]
    assert request == WindPreviewRequest(input_path=str(tree_xml))
    assert window._wind_preview_dialog is not None
    assert window._wind_preview_dialog.current_preview is not None
    assert len(window._wind_preview_dialog._group_buttons) == 3
    assert window._wind_preview_dialog.viewport.show_bones is True


def test_qt_window_queues_wind_preview_until_auto_refresh_finishes(monkeypatch, qtbot, tmp_path) -> None:
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

    window.open_wind_preview_dialog()

    assert window._pending_wind_preview_after_refresh is True
    assert "start_wind_preview_process" not in calls

    window._source_refresh_timer.stop()
    dynamic_wind = window._deps.inspect_wind_groups(
        window._deps.prepare_wind_inspection_plan(
            input_path=str(tree_xml),
            is_ground_cover=False,
            async_threshold_bytes=0,
        ).request
    )
    window._set_wind_refresh_running(False)
    window._handle_wind_data_loaded(dynamic_wind, used_retry=False)
    qtbot.waitUntil(lambda: window._wind_preview_dialog is not None, timeout=3000)

    assert window._pending_wind_preview_after_refresh is False
    assert "start_wind_preview_process" in calls


def test_qt_window_retries_transient_wind_preview_process_crash(monkeypatch, qtbot, tmp_path) -> None:
    critical_messages: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: critical_messages.append(str(args[2]))))

    class _CrashedProcess:
        exitcode = 3221225477

        def is_alive(self) -> bool:
            return False

        def join(self, timeout=None) -> None:
            return None

        def terminate(self) -> None:
            return None

    calls: dict[str, object] = {}
    base_deps = _build_fake_deps(calls)
    starts: list[object] = []

    def start_wind_preview_process(request, settings=None):
        starts.append(request)
        if len(starts) == 1:
            return _CrashedProcess(), [], _CancelFlag()
        return base_deps.start_wind_preview_process(request, settings)

    deps = replace(base_deps, start_wind_preview_process=start_wind_preview_process)
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=deps,
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()
    tree_xml = tmp_path / "tree.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    window.source_input.setText(str(tree_xml))
    window._source_refresh_timer.stop()

    window.open_wind_preview_dialog()
    qtbot.waitUntil(
        lambda: window._wind_preview_dialog is not None and window._wind_preview_dialog.current_preview is not None,
        timeout=3000,
    )

    assert len(starts) == 2
    assert starts[0] == starts[1]
    assert critical_messages == []
    assert "Wind Preview worker process crashed unexpectedly" not in window._log_text


def test_proxy_preview_can_show_diagnostic_cube_without_generating_proxy(qtbot) -> None:
    calls: dict[str, object] = {}
    dialog = ProxyPreviewDialog(
        settings=ProxyMeshSettings(final_polycount=5000, density_resolution=12),
        on_settings_changed=lambda settings: calls.setdefault("settings_changed", settings),
        preview_mesh=build_preview_cube_mesh(),
    )
    qtbot.addWidget(dialog)
    dialog.show()

    qtbot.waitUntil(lambda: dialog.current_proxy is not None, timeout=3000)

    assert dialog.global_scroll.widgetResizable()
    assert dialog.settings_panel_default_width == 480
    assert "QComboBox::drop-down" in dialog.settings_panel.styleSheet()
    assert dialog.current_proxy.mesh.name == "ViewportCubePreview"
    assert dialog.status_label.text() == "Viewport cube preview: 6 polygons / 8 points"
    assert "settings_changed" not in calls


def test_proxy_preview_replaces_mesh_without_clearing_or_refitting_camera(qtbot) -> None:
    calls: dict[str, object] = {}
    request = ProxyMeshSourceRequest(input_path="tree.xml", output_path="tree.usda")
    first_proxy = _build_fake_deps(calls).generate_proxy_mesh_from_source_request(
        request,
        ProxyMeshSettings(final_polycount=2400, density_resolution=64),
    )
    changed_settings: list[ProxyMeshSettings] = []

    dialog = ProxyPreviewDialog(
        settings=ProxyMeshSettings(final_polycount=2400, density_resolution=64),
        initial_proxy=first_proxy,
        on_settings_changed=changed_settings.append,
    )
    qtbot.addWidget(dialog)
    dialog.show()

    qtbot.waitUntil(lambda: dialog.current_proxy is not None, timeout=3000)
    dialog.viewport._distance = 42.0

    dialog.polycount_spin.setValue(3600)
    dialog.polycount_spin.editingFinished.emit()

    assert dialog.current_proxy is first_proxy
    assert dialog.viewport._scene is not None
    assert dialog.viewport._scene.stats.uploaded_triangles == first_proxy.mesh.face_count
    qtbot.waitUntil(lambda: changed_settings and changed_settings[-1].final_polycount == 3600, timeout=3000)
    dialog.set_proxy(
        _build_fake_deps(calls).generate_proxy_mesh_from_source_request(
            request,
            changed_settings[-1],
        )
    )
    qtbot.waitUntil(lambda: dialog.current_proxy.settings.final_polycount == 3600, timeout=3000)

    assert dialog.viewport._distance == pytest.approx(42.0)
    assert not hasattr(dialog, "regenerate_button")


def test_qt_window_opens_proxy_preview_from_geometry_tab(monkeypatch, qtbot, tmp_path) -> None:
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
    window._proxy_mesh_settings = ProxyMeshSettings(
        final_polycount=2400,
        base_mesh_priority=0.72,
        branch_prune_aggression=0.62,
    )
    window.geometry_panel.apply_proxy_settings(window._proxy_mesh_settings)

    assert window.geometry_panel.preview_proxy_button.isEnabled()
    assert not hasattr(window.geometry_panel, "proxy_polycount_spin")
    assert not hasattr(window.geometry_panel, "proxy_base_priority_spin")

    qtbot.mouseClick(window.geometry_panel.preview_proxy_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window._proxy_preview_dialog.current_proxy is not None, timeout=3000)

    assert window._proxy_preview_dialog is not None
    assert window._proxy_preview_dialog.isVisible()
    assert isinstance(window._proxy_preview_dialog.viewport, QOpenGLWidget)
    assert window._proxy_preview_dialog.parent() is None
    assert window.isVisible()
    assert window._proxy_preview_dialog.windowModality() == Qt.WindowModality.NonModal
    assert not window._proxy_preview_dialog.isModal()
    first_dialog = window._proxy_preview_dialog
    window.open_proxy_preview_dialog()
    assert window._proxy_preview_dialog is first_dialog
    assert window._proxy_preview_dialog.method_combo.count() == 1
    assert window._proxy_preview_dialog.method_combo.currentData() == "density_field"
    assert window._proxy_preview_dialog.polycount_spin.maximum() == 100000
    assert window._proxy_preview_dialog.polycount_spin.width() >= window._proxy_preview_dialog.polycount_spin.fontMetrics().horizontalAdvance("100000")
    assert window._proxy_preview_dialog.density_resolution_spin.value() == 64
    assert window._proxy_preview_dialog.density_resolution_spin.maximum() == 256
    assert window._proxy_preview_dialog.branch_prune_spin.value() == pytest.approx(0.62)
    assert window._proxy_preview_dialog.branch_prune_slider.value() == _expected_branch_prune_slider(0.62)
    assert calls["start_proxy_mesh_process"]["action"] == "preview"
    assert calls["generate_proxy_mesh_from_source_request"]["settings"].method == "density_field"
    assert calls["generate_proxy_mesh_from_source_request"]["settings"].final_polycount == 2400
    assert calls["generate_proxy_mesh_from_source_request"]["settings"].base_mesh_priority == pytest.approx(0.72)
    assert calls["generate_proxy_mesh_from_source_request"]["settings"].branch_prune_aggression == pytest.approx(0.62)
    assert calls["generate_proxy_mesh_from_source_request"]["request"].output_path == str(tmp_path / "tree.usda")

    window._proxy_preview_dialog.polycount_spin.setValue(3600)
    window._proxy_preview_dialog.polycount_spin.editingFinished.emit()
    qtbot.waitUntil(lambda: calls["generate_proxy_mesh_from_source_request"]["settings"].final_polycount == 3600, timeout=3000)

    assert calls["generate_proxy_mesh_from_source_request"]["settings"].final_polycount == 3600

    window._proxy_preview_dialog.density_resolution_spin.setValue(18)
    window._proxy_preview_dialog.density_resolution_spin.editingFinished.emit()
    qtbot.waitUntil(lambda: calls["generate_proxy_mesh_from_source_request"]["settings"].density_resolution == 18, timeout=3000)

    assert calls["generate_proxy_mesh_from_source_request"]["settings"].density_resolution == 18

    window._proxy_preview_dialog.base_priority_spin.setValue(0.21)
    window._proxy_preview_dialog.base_priority_spin.editingFinished.emit()
    qtbot.waitUntil(lambda: calls["generate_proxy_mesh_from_source_request"]["settings"].base_mesh_priority == pytest.approx(0.21), timeout=3000)
    qtbot.waitUntil(lambda: window._proxy_preview_dialog.current_proxy.settings.base_mesh_priority == pytest.approx(0.21), timeout=3000)

    assert calls["generate_proxy_mesh_from_source_request"]["settings"].base_mesh_priority == pytest.approx(0.21)

    window._proxy_preview_dialog.branch_prune_slider.setValue(60)
    window._proxy_preview_dialog.branch_prune_slider.sliderReleased.emit()
    slider_prune = _expected_branch_prune_value(60)
    qtbot.waitUntil(
        lambda: calls["generate_proxy_mesh_from_source_request"]["settings"].branch_prune_aggression
        == pytest.approx(slider_prune),
        timeout=3000,
    )

    assert window._proxy_preview_dialog.branch_prune_spin.value() == pytest.approx(slider_prune)

    window._proxy_preview_dialog.branch_prune_spin.setValue(0.35)
    window._proxy_preview_dialog.branch_prune_spin.editingFinished.emit()
    qtbot.waitUntil(
        lambda: calls["generate_proxy_mesh_from_source_request"]["settings"].branch_prune_aggression == pytest.approx(0.35),
        timeout=3000,
    )
    qtbot.waitUntil(
        lambda: window._proxy_preview_dialog.current_proxy.settings.branch_prune_aggression == pytest.approx(0.35),
        timeout=3000,
    )

    trace_text = (tmp_path / "gui_trace.jsonl").read_text(encoding="utf-8")
    assert '"kind":"job.result"' in trace_text
    assert '"job":"proxy_preview"' in trace_text
    assert '"kind":"scene.ready"' in trace_text
    assert '"kind":"viewport.set_scene"' in trace_text
    assert '"kind":"viewport.upload"' in trace_text

    window._proxy_preview_dialog.close()
    qtbot.waitUntil(lambda: not window._proxy_preview_dialog.isVisible(), timeout=3000)
    qtbot.waitUntil(
        lambda: load_gui_settings(tmp_path / "gui_settings.json").proxy_mesh_settings.base_mesh_priority
        == pytest.approx(0.21),
        timeout=3000,
    )

    saved_settings = load_gui_settings(tmp_path / "gui_settings.json").proxy_mesh_settings
    assert saved_settings.final_polycount == 3600
    assert saved_settings.density_resolution == 18
    assert saved_settings.branch_prune_aggression == pytest.approx(0.35)
    assert window.geometry_panel.proxy_settings().final_polycount == 3600
    assert window.geometry_panel.proxy_settings().base_mesh_priority == pytest.approx(0.21)
    assert window.geometry_panel.proxy_settings().branch_prune_aggression == pytest.approx(0.35)

    qtbot.mouseClick(window.generate_proxy_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "Wrote Proxy Mesh USDA" in window.status_label.text(), timeout=3000)

    assert calls["export_generated_proxy_usda_from_source_request"]["proxy"].settings.final_polycount == 3600
    assert calls["export_generated_proxy_usda_from_source_request"]["proxy"].settings.density_resolution == 18
    assert calls["export_generated_proxy_usda_from_source_request"]["proxy"].settings.branch_prune_aggression == pytest.approx(0.35)
    assert [event["action"] for event in calls["start_proxy_mesh_process_events"]] == [
        "preview",
        "preview",
        "preview",
        "preview",
        "preview",
        "preview",
    ]


def test_qt_window_opens_fracture_preview_from_geometry_tab(monkeypatch, qtbot, tmp_path) -> None:
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
    window._fracture_preview_settings = FracturePreviewSettings(
        fracture=FractureSettings(target_piece_count=3),
        final_polycount=240000,
        base_mesh_priority=0.42,
        branch_prune_aggression=0.31,
    )
    window.geometry_panel.apply_fracture_preview_settings(window._fracture_preview_settings)

    assert window.geometry_panel.preview_fracture_button.isEnabled()
    assert not hasattr(window.geometry_panel, "fracture_polycount_spin")

    qtbot.mouseClick(window.geometry_panel.preview_fracture_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: (
            window._fracture_preview_dialog is not None
            and window._fracture_preview_dialog.isVisible()
            and window._fracture_preview_dialog.current_preview is not None
        ),
        timeout=3000,
    )

    assert isinstance(window._fracture_preview_dialog.viewport, QOpenGLWidget)
    assert window._fracture_preview_dialog.parent() is None
    assert window.isVisible()
    assert window._fracture_preview_dialog.windowModality() == Qt.WindowModality.NonModal
    assert not window._fracture_preview_dialog.isModal()
    first_dialog = window._fracture_preview_dialog
    window.open_fracture_preview_dialog()
    assert window._fracture_preview_dialog is first_dialog
    assert window._fracture_preview_dialog.piece_count_spin.value() == 3
    assert window._fracture_preview_dialog.piece_count_slider.value() == 3
    assert window._fracture_preview_dialog.polycount_spin.value() == 240000
    assert window._fracture_preview_dialog.polycount_slider.value() == 240000
    assert window._fracture_preview_dialog.branch_prune_spin.value() == pytest.approx(0.31)
    assert window._fracture_preview_dialog.branch_prune_slider.value() == _expected_branch_prune_slider(0.31)
    assert window._fracture_preview_dialog.base_priority_spin.value() == pytest.approx(0.42)
    assert window._fracture_preview_dialog.base_priority_slider.value() == 42
    assert window._fracture_preview_dialog.color_strength_slider.value() == 78
    assert window._fracture_preview_dialog.viewport_mesh.piece_count == 3
    assert window._fracture_preview_dialog.viewport_mesh.triangle_count == 3

    call = calls["generate_fracture_preview_from_source_request"]
    assert isinstance(call["request"], FracturePreviewSourceRequest)
    assert call["request"].input_path == str(tree_xml)
    assert call["request"].output_path == str(tmp_path / "tree.usda")
    assert not hasattr(call["request"], "prototype_source_configs")
    assert isinstance(call["settings"], FracturePreviewSettings)
    assert call["settings"].fracture.target_piece_count == 3
    assert call["settings"].fracture.preserve_trunk_bias == pytest.approx(0.5)
    assert call["settings"].final_polycount == 240000
    assert call["settings"].base_mesh_priority == pytest.approx(0.42)
    assert call["settings"].branch_prune_aggression == pytest.approx(0.31)

    window._fracture_preview_dialog.polycount_spin.setValue(360000)
    window._fracture_preview_dialog.polycount_spin.editingFinished.emit()
    qtbot.waitUntil(
        lambda: calls["generate_fracture_preview_from_source_request"]["settings"].final_polycount == 360000,
        timeout=3000,
    )

    assert window._fracture_preview_settings.final_polycount == 360000
    assert window.geometry_panel.fracture_preview_settings().final_polycount == 360000

    window._fracture_preview_dialog.branch_prune_slider.setValue(60)
    window._fracture_preview_dialog.branch_prune_slider.sliderReleased.emit()
    slider_prune = _expected_branch_prune_value(60)
    qtbot.waitUntil(
        lambda: calls["generate_fracture_preview_from_source_request"]["settings"].branch_prune_aggression
        == pytest.approx(slider_prune),
        timeout=3000,
    )

    assert window._fracture_preview_dialog.branch_prune_spin.value() == pytest.approx(slider_prune)

    window._fracture_preview_dialog.branch_prune_spin.setValue(0.73)
    window._fracture_preview_dialog.branch_prune_spin.editingFinished.emit()
    qtbot.waitUntil(
        lambda: calls["generate_fracture_preview_from_source_request"]["settings"].branch_prune_aggression
        == pytest.approx(0.73),
        timeout=3000,
    )

    assert window._fracture_preview_settings.branch_prune_aggression == pytest.approx(0.73)
    assert window.geometry_panel.fracture_preview_settings().branch_prune_aggression == pytest.approx(0.73)

    window._fracture_preview_dialog.piece_count_slider.setValue(4)
    window._fracture_preview_dialog.piece_count_slider.sliderReleased.emit()
    qtbot.waitUntil(
        lambda: calls["generate_fracture_preview_from_source_request"]["settings"].fracture.target_piece_count == 4,
        timeout=3000,
    )

    assert window._fracture_preview_dialog.piece_count_spin.value() == 4
    assert window._fracture_preview_settings.fracture.target_piece_count == 4

    window._fracture_preview_dialog.color_strength_spin.setValue(0.35)
    assert window._fracture_preview_dialog.color_strength_slider.value() == 35
    assert window._fracture_preview_dialog.viewport.matcap_tint_strength == pytest.approx(0.35)

    window._fracture_preview_dialog.color_strength_slider.setValue(92)
    assert window._fracture_preview_dialog.color_strength_spin.value() == pytest.approx(0.92)
    assert window._fracture_preview_dialog.viewport.matcap_tint_strength == pytest.approx(0.92)

    trace_text = (tmp_path / "gui_trace.jsonl").read_text(encoding="utf-8")
    assert '"kind":"ui.action"' in trace_text
    assert '"widget":"Preview Fracturing"' in trace_text
    assert '"kind":"job.start"' in trace_text
    assert '"job":"fracture_preview"' in trace_text
    assert '"kind":"worker.spawn"' in trace_text
    assert '"worker":"fracture_preview"' in trace_text
    assert '"kind":"scene.ready"' in trace_text
    assert '"kind":"viewport.set_scene"' in trace_text
    assert '"kind":"viewport.upload"' in trace_text


def test_qt_window_reuses_cached_fracture_preview_when_settings_return_to_previous_state(
    monkeypatch,
    qtbot,
    tmp_path,
) -> None:
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

    calls: dict[str, object] = {}
    deps = _build_fake_deps(calls)
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=deps,
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    tree_xml = tmp_path / "tree.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    window.source_input.setText(str(tree_xml))
    window.output_input.setText(str(tmp_path / "tree.usda"))

    qtbot.mouseClick(window.geometry_panel.preview_fracture_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: window._fracture_preview_dialog is not None
        and window._fracture_preview_dialog.current_preview is not None,
        timeout=3000,
    )
    first_preview = window._fracture_preview_dialog.current_preview
    start_events = calls["start_fracture_preview_process_events"]
    assert len(start_events) == 1

    window._fracture_preview_dialog.generate_caps_check.setChecked(True)
    qtbot.waitUntil(
        lambda: window._fracture_preview_dialog.current_preview is not None
        and window._fracture_preview_dialog.current_preview is not first_preview,
        timeout=3000,
    )
    assert len(start_events) == 2

    window._fracture_preview_dialog.generate_caps_check.setChecked(False)
    qtbot.waitUntil(
        lambda: window._fracture_preview_dialog.current_preview is first_preview,
        timeout=3000,
    )

    assert len(start_events) == 2
    assert window._fracture_preview_settings.fracture.generate_caps is False


def test_qt_window_opens_fracture_preview_shell_while_process_is_running(monkeypatch, qtbot, tmp_path) -> None:
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

    calls: dict[str, object] = {}
    base_deps = _build_fake_deps(calls)
    running_process = _RunningProcess()

    def start_fracture_preview_process(request, settings):
        calls.setdefault("start_fracture_preview_process_events", []).append({"request": request, "settings": settings})
        calls["start_fracture_preview_process"] = {"request": request, "settings": settings}
        return running_process, [], _CancelFlag()

    deps = replace(
        base_deps,
        start_fracture_preview_process=start_fracture_preview_process,
        generate_fracture_preview_from_source_request=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Fracture Preview must run in an isolated process")
        ),
    )
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=deps,
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    tree_xml = tmp_path / "tree.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    window.source_input.setText(str(tree_xml))
    window.output_input.setText(str(tmp_path / "tree.usda"))

    qtbot.mouseClick(window.geometry_panel.preview_fracture_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: window._fracture_preview_dialog is not None and window._fracture_preview_dialog.isVisible(),
        timeout=3000,
    )

    assert len(calls["start_fracture_preview_process_events"]) == 1
    assert window._fracture_preview_dialog.current_preview is None
    assert window._fracture_preview_dialog.viewport_mesh is None
    assert "Preparing preview geometry" in window._fracture_preview_dialog.loading_label.text()
    assert window.geometry_panel.preview_fracture_button.isEnabled() is False
    assert window._background_jobs.fracture_preview_running is True


def test_qt_window_opening_proxy_preview_cancels_running_fracture_preview(monkeypatch, qtbot, tmp_path) -> None:
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

    calls: dict[str, object] = {}
    base_deps = _build_fake_deps(calls)
    running_process = _RunningProcess()
    cancel_flag = _CancelFlag()

    def start_fracture_preview_process(request, settings):
        calls["fracture_preview_started"] = True
        calls["start_fracture_preview_process"] = {"request": request, "settings": settings}
        return running_process, [], cancel_flag

    deps = replace(
        base_deps,
        start_fracture_preview_process=start_fracture_preview_process,
    )
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=deps,
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    tree_xml = tmp_path / "tree.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    window.source_input.setText(str(tree_xml))
    window.output_input.setText(str(tmp_path / "tree.usda"))

    qtbot.mouseClick(window.geometry_panel.preview_fracture_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "start_fracture_preview_process" in calls, timeout=3000)
    qtbot.waitUntil(lambda: window._fracture_preview_dialog is not None, timeout=3000)

    qtbot.mouseClick(window.geometry_panel.preview_proxy_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window._proxy_preview_dialog is not None, timeout=3000)
    qtbot.waitUntil(lambda: "start_proxy_mesh_process" in calls, timeout=3000)
    qtbot.waitUntil(lambda: cancel_flag.was_set, timeout=3000)

    assert window._background_jobs.fracture_preview_running is False
    assert running_process.terminated is True
    assert calls["start_proxy_mesh_process"]["action"] == "preview"
    assert calls["fracture_preview_started"] is True


def test_qt_window_opening_fracture_preview_closes_running_proxy_preview(monkeypatch, qtbot, tmp_path) -> None:
    class _RunningProcess:
        exitcode = None

        def __init__(self) -> None:
            self.terminated = False

        def is_alive(self) -> bool:
            return not self.terminated

        def join(self, timeout=None) -> None:
            return None

        def terminate(self) -> None:
            self.terminated = True

    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

    calls: dict[str, object] = {}
    running_proxy = _RunningProcess()

    def start_proxy_mesh_process(request, settings, action):
        calls["start_proxy_mesh_process"] = {
            "request": request,
            "settings": settings,
            "action": action,
        }
        return running_proxy, [], object()

    deps = replace(_build_fake_deps(calls), start_proxy_mesh_process=start_proxy_mesh_process)
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=deps,
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    tree_xml = tmp_path / "tree.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    window.source_input.setText(str(tree_xml))
    window.output_input.setText(str(tmp_path / "tree.usda"))

    qtbot.mouseClick(window.geometry_panel.preview_proxy_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "start_proxy_mesh_process" in calls, timeout=3000)

    qtbot.mouseClick(window.geometry_panel.preview_fracture_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "start_fracture_preview_process" in calls, timeout=3000)

    assert running_proxy.terminated is True
    assert window._proxy_preview_dialog is None
    assert calls["start_fracture_preview_process"]["settings"].fracture.target_piece_count == 5


def test_qt_fracture_caps_material_controls_do_not_restart_preview(monkeypatch, qtbot, tmp_path) -> None:
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

    qtbot.mouseClick(window.geometry_panel.preview_fracture_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: window._fracture_preview_dialog is not None
        and window._fracture_preview_dialog.current_preview is not None,
        timeout=3000,
    )

    dialog = window._fracture_preview_dialog
    assert dialog is not None
    assert dialog.override_caps_material_check.isHidden()
    assert dialog.caps_material_row.isHidden()

    dialog.generate_caps_check.setChecked(True)
    qtbot.waitUntil(lambda: len(calls.get("start_fracture_preview_process_events", [])) >= 2, timeout=3000)
    preview_start_count = len(calls["start_fracture_preview_process_events"])

    dialog.override_caps_material_check.setChecked(True)
    dialog.caps_material_row.path_edit.setText("/Game/Fracture/M_Cap.M_Cap")
    dialog.caps_material_row.udim_mode_combo.setCurrentIndex(
        dialog.caps_material_row.udim_mode_combo.findData(UdimMode.WRITE_SECONDARY_UV_OFFSET.value)
    )
    dialog.caps_material_row.udim_id_spin.setValue(1003)
    qtbot.wait(100)

    assert not dialog.override_caps_material_check.isHidden()
    assert not dialog.caps_material_row.isHidden()
    assert dialog.caps_material_row.layout().itemAtPosition(0, 1).widget() is dialog.caps_material_row.path_edit
    assert dialog.caps_material_row.layout().itemAtPosition(1, 1).widget() is dialog.caps_material_row.udim_mode_combo
    assert dialog.caps_material_row.layout().itemAtPosition(1, 2).widget() is dialog.caps_material_row.udim_id_spin
    assert len(calls["start_fracture_preview_process_events"]) == preview_start_count


def test_qt_window_exports_fracture_pieces_with_current_operator_intent(monkeypatch, qtbot, tmp_path) -> None:
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
    fake_fbx = tmp_path / "branch.fbx"
    fake_fbx.write_text("", encoding="utf-8")
    output_path = tmp_path / "tree.usda"
    window.source_input.setText(str(tree_xml))
    window.output_input.setText(str(output_path))
    window._fracture_preview_settings = FracturePreviewSettings(
        fracture=FractureSettings(target_piece_count=4, generate_caps=True)
    )
    window.geometry_panel.apply_fracture_preview_settings(window._fracture_preview_settings)
    geometry_row = window.geometry_panel._rows[0]
    geometry_row.fbx_edit.setText(str(fake_fbx))
    geometry_row.source_mode_combo.setCurrentIndex(
        geometry_row.source_mode_combo.findData(PrototypeSourceMode.FBX_FILE.value)
    )

    qtbot.mouseClick(window.geometry_panel.preview_fracture_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: window._fracture_preview_dialog is not None
        and window._fracture_preview_dialog.current_preview is not None,
        timeout=3000,
    )
    dialog = window._fracture_preview_dialog
    assert dialog is not None
    dialog.override_caps_material_check.setChecked(True)
    dialog.caps_material_row.path_edit.setText("/Game/Fracture/M_Cap.M_Cap")
    dialog.caps_material_row.udim_mode_combo.setCurrentIndex(
        dialog.caps_material_row.udim_mode_combo.findData(UdimMode.WRITE_SECONDARY_UV_OFFSET.value)
    )
    dialog.caps_material_row.udim_id_spin.setValue(1003)

    qtbot.mouseClick(dialog.export_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "Wrote 4 Fracture USDA piece(s)." in window.status_label.text(), timeout=3000)

    assert calls["start_fracture_export_process"]["settings"].target_piece_count == 4
    call = calls["export_fracture_usda_from_export_request"]
    assert call["settings"].target_piece_count == 4
    assert call["settings"].generate_caps is True
    assert isinstance(call["request"], FractureExportRequest)
    assert call["request"].input_path == str(tree_xml)
    assert call["request"].output_path == str(output_path)
    assert call["request"].cap_material_setting.enabled is True
    assert call["request"].cap_material_setting.ue_asset_path == "/Game/Fracture/M_Cap.M_Cap"
    assert call["request"].cap_material_setting.udim_mode == UdimMode.WRITE_SECONDARY_UV_OFFSET
    assert call["request"].cap_material_setting.udim_id == 1003
    assert call["request"].prototype_source_configs[0].mode == PrototypeSourceMode.FBX_FILE
    assert call["request"].prototype_source_configs[0].fbx_path == str(fake_fbx)
    assert "tree_fracture_03.usda" in window._log_text


def test_qt_window_exports_fracture_pieces_with_current_manual_bone_session(monkeypatch, qtbot, tmp_path) -> None:
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
    output_path = tmp_path / "tree.usda"
    window.source_input.setText(str(tree_xml))
    window.output_input.setText(str(output_path))
    window._fracture_preview_settings = FracturePreviewSettings(
        fracture=FractureSettings(
            target_piece_count=2,
            pinned_cut_joint_tokens=("bone_003",),
            preserve_trunk_bias=1.0,
        )
    )
    window.geometry_panel.apply_fracture_preview_settings(window._fracture_preview_settings)

    window.run_export_fracture_usda()
    qtbot.waitUntil(lambda: "start_fracture_export_process" in calls, timeout=3000)

    settings = calls["start_fracture_export_process"]["settings"]
    assert settings.pinned_cut_joint_tokens == ("bone_003",)
    assert settings.preserve_trunk_bias == pytest.approx(1.0)

    other_xml = tmp_path / "other.xml"
    other_xml.write_text("<tree/>", encoding="utf-8")
    window.source_input.setText(str(other_xml))

    assert window._fracture_preview_settings.fracture.pinned_cut_joint_tokens == ()


def test_qt_window_reports_fracture_preview_error_with_request_context(monkeypatch, qtbot, tmp_path) -> None:
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

    calls: dict[str, object] = {}
    base_deps = _build_fake_deps(calls)

    def start_fracture_preview_process(request, settings):
        calls["start_fracture_preview_process"] = {
            "request": request,
            "settings": settings,
        }
        return _FinishedProcess(), [
            ("error_traceback", "Traceback: preview planner exploded"),
            ("error", "preview planner exploded"),
        ], _CancelFlag()

    deps = replace(
        base_deps,
        start_fracture_preview_process=start_fracture_preview_process,
    )
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=deps,
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    tree_xml = tmp_path / "tree.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    output_path = tmp_path / "tree.usda"
    window.source_input.setText(str(tree_xml))
    window.output_input.setText(str(output_path))
    window._fracture_preview_settings = FracturePreviewSettings(
        fracture=FractureSettings(target_piece_count=7),
        final_polycount=123400,
        base_mesh_priority=0.27,
    )
    window.geometry_panel.apply_fracture_preview_settings(window._fracture_preview_settings)

    qtbot.mouseClick(window.geometry_panel.preview_fracture_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "Fracture Preview failed." in window.status_label.text(), timeout=3000)

    assert "preview planner exploded" in window._log_text
    assert "Traceback: preview planner exploded" in window._log_text
    assert "input_path=" in window._log_text
    assert str(tree_xml) in window._log_text
    assert "output_path=" in window._log_text
    assert str(output_path) in window._log_text
    assert "target_branch_count=7" in window._log_text
    assert "branch_height_bias=0.0" in window._log_text
    assert "preview_polycount=123400" in window._log_text
    assert "preview_base_priority=0.27" in window._log_text


def test_qt_window_runs_fracture_preview_in_isolated_worker_process(monkeypatch, qtbot, tmp_path) -> None:
    critical_messages: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: critical_messages.append(str(args[2]))))

    calls: dict[str, object] = {}
    deps = _build_fake_deps(calls)
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=deps,
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    tree_xml = tmp_path / "tree.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    window.source_input.setText(str(tree_xml))
    window.output_input.setText(str(tmp_path / "tree.usda"))
    window._fracture_preview_settings = FracturePreviewSettings(
        fracture=FractureSettings(target_piece_count=5, preserve_trunk_bias=0.0)
    )
    window.geometry_panel.apply_fracture_preview_settings(window._fracture_preview_settings)

    qtbot.mouseClick(window.geometry_panel.preview_fracture_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "Fracture Preview ready" in window.status_label.text(), timeout=3000)

    assert calls["start_fracture_preview_process"]["settings"].fracture.preserve_trunk_bias == pytest.approx(0.0)
    assert critical_messages == []
    assert window._fracture_preview_dialog is not None
    assert window._fracture_preview_dialog.current_preview is not None


def test_qt_window_retries_transient_fracture_preview_process_crash(monkeypatch, qtbot, tmp_path) -> None:
    critical_messages: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: critical_messages.append(str(args[2]))))

    class _CrashedProcess:
        exitcode = 3221225477

        def is_alive(self) -> bool:
            return False

        def join(self, timeout=None) -> None:
            return None

        def terminate(self) -> None:
            return None

    calls: dict[str, object] = {}
    base_deps = _build_fake_deps(calls)
    start_events: list[dict[str, object]] = []

    def start_fracture_preview_process(request, settings):
        start_events.append({"request": request, "settings": settings})
        calls["start_fracture_preview_process"] = {"request": request, "settings": settings}
        if len(start_events) == 1:
            return _CrashedProcess(), [], _CancelFlag()
        return _FinishedProcess(), [
            ("result", base_deps.generate_fracture_preview_from_source_request(request, settings))
        ], _CancelFlag()

    deps = replace(base_deps, start_fracture_preview_process=start_fracture_preview_process)
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=deps,
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    tree_xml = tmp_path / "tree.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    window.source_input.setText(str(tree_xml))
    window.output_input.setText(str(tmp_path / "tree.usda"))
    window._fracture_preview_settings = FracturePreviewSettings(
        fracture=FractureSettings(target_piece_count=26, generate_caps=True),
        base_mesh_priority=0.74,
    )
    window.geometry_panel.apply_fracture_preview_settings(window._fracture_preview_settings)

    qtbot.mouseClick(window.geometry_panel.preview_fracture_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: window._fracture_preview_dialog is not None
        and window._fracture_preview_dialog.current_preview is not None,
        timeout=3000,
    )

    assert len(start_events) == 2
    assert start_events[0]["settings"] == start_events[1]["settings"]
    assert window._fracture_preview_dialog.current_preview.plan.actual_piece_count == 26
    assert critical_messages == []
    assert "Fracture preview worker process crashed unexpectedly" not in window._log_text


def test_qt_window_restarts_fracture_preview_process_for_latest_settings(
    monkeypatch,
    qtbot,
    tmp_path,
) -> None:
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

    calls: dict[str, object] = {}
    base_deps = _build_fake_deps(calls)
    first_process = _RunningProcess()
    cancel_flag = _CancelFlag()
    start_events: list[dict[str, object]] = []

    def start_fracture_preview_process(request, settings):
        start_events.append({"request": request, "settings": settings})
        calls["start_fracture_preview_process"] = {"request": request, "settings": settings}
        if len(start_events) == 1:
            return first_process, [], cancel_flag
        return _FinishedProcess(), [
            ("result", base_deps.generate_fracture_preview_from_source_request(request, settings))
        ], _CancelFlag()

    deps = replace(
        base_deps,
        start_fracture_preview_process=start_fracture_preview_process,
    )
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=deps,
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    tree_xml = tmp_path / "tree.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    window.source_input.setText(str(tree_xml))
    window.output_input.setText(str(tmp_path / "tree.usda"))
    window._fracture_preview_settings = FracturePreviewSettings(
        fracture=FractureSettings(target_piece_count=5)
    )
    window.geometry_panel.apply_fracture_preview_settings(window._fracture_preview_settings)

    qtbot.mouseClick(window.geometry_panel.preview_fracture_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: len(start_events) == 1, timeout=3000)
    qtbot.waitUntil(lambda: window._fracture_preview_dialog is not None, timeout=3000)

    window._fracture_preview_dialog.piece_count_spin.setValue(6)
    window._fracture_preview_dialog.piece_count_spin.editingFinished.emit()

    qtbot.waitUntil(lambda: len(start_events) == 2, timeout=3000)

    qtbot.waitUntil(
        lambda: window._fracture_preview_dialog.current_preview is not None
        and window._fracture_preview_dialog.current_preview.plan.actual_piece_count == 6,
        timeout=3000,
    )

    assert first_process.terminated is True
    assert cancel_flag.was_set is True
    assert start_events[0]["settings"].fracture.target_piece_count == 5
    assert start_events[1]["settings"].fracture.target_piece_count == 6
    assert window._fracture_preview_dialog.current_preview.plan.actual_piece_count == 6
    assert window._fracture_preview_dialog.viewport_mesh.piece_count == 6


def test_qt_window_accepts_fracture_preview_process_result(monkeypatch, qtbot, tmp_path) -> None:
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

    calls: dict[str, object] = {}
    deps = _build_fake_deps(calls)
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=deps,
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    tree_xml = tmp_path / "tree.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    window.source_input.setText(str(tree_xml))
    window.output_input.setText(str(tmp_path / "tree.usda"))

    qtbot.mouseClick(window.geometry_panel.preview_fracture_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: window._fracture_preview_dialog is not None
        and window._fracture_preview_dialog.current_preview is not None,
        timeout=3000,
    )

    assert "Fracture Preview failed" not in window.status_label.text()
    assert "Fracture preview worker process crashed unexpectedly" not in window._log_text
    assert calls["start_fracture_preview_process"]["request"].input_path == str(tree_xml)


def test_qt_window_reports_fracture_preview_process_error_without_closing_gui(monkeypatch, qtbot, tmp_path) -> None:
    critical_messages: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: critical_messages.append(str(args[2]))))

    calls: dict[str, object] = {}
    base_deps = _build_fake_deps(calls)

    def start_fracture_preview_process(request, settings):
        calls["start_fracture_preview_process"] = {"request": request, "settings": settings}
        return _FinishedProcess(), [
            ("error_traceback", "Traceback: preview planner exploded"),
            ("error", "preview planner exploded"),
        ], _CancelFlag()

    deps = replace(
        base_deps,
        start_fracture_preview_process=start_fracture_preview_process,
    )
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=deps,
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    tree_xml = tmp_path / "tree.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    window.source_input.setText(str(tree_xml))
    window.output_input.setText(str(tmp_path / "tree.usda"))

    qtbot.mouseClick(window.geometry_panel.preview_fracture_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "Fracture Preview failed" in window.status_label.text(), timeout=3000)

    assert "start_fracture_preview_process" in calls
    assert "preview planner exploded" in window._log_text
    assert critical_messages
    assert window.isVisible()


def test_qt_window_records_fracture_preview_runtime_breadcrumbs(monkeypatch, qtbot, tmp_path) -> None:
    settings_dir = tmp_path / "settings"
    runtime_paths = resolve_runtime_paths(
        settings_dir=settings_dir,
        settings_path=settings_dir / "gui_settings.json",
        cache_root=tmp_path / "cache",
    )
    monkeypatch.setattr("xml_to_usda.qt_ui.window.resolve_runtime_paths", lambda **kwargs: runtime_paths)
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

    calls: dict[str, object] = {}
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=_build_fake_deps(calls),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=settings_dir / "gui_settings.json",
    )
    qtbot.addWidget(window)

    tree_xml = tmp_path / "tree.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    window.source_input.setText(str(tree_xml))
    window.output_input.setText(str(tmp_path / "tree.usda"))

    qtbot.mouseClick(window.geometry_panel.preview_fracture_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: window._fracture_preview_dialog is not None
        and window._fracture_preview_dialog.current_preview is not None,
        timeout=3000,
    )

    runtime_log = (settings_dir / "gui_runtime.log").read_text(encoding="utf-8")
    assert "INFO Fracture Preview requested" in runtime_log
    assert "input_path=" in runtime_log
    assert str(tree_xml) in runtime_log
    assert "INFO Fracture Preview result received" in runtime_log
    assert "piece_count=5" in runtime_log
    assert "INFO Fracture Preview viewport mesh ready" in runtime_log

    trace_events = [
        json.loads(line)
        for line in (settings_dir / "gui_trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    app_start = next(event for event in trace_events if event["kind"] == "app.start")
    assert app_start["data"]["debug_trace_enabled"] is True
    assert app_start["data"]["debug_trace_forced"] is True
    fracture_worker_events = [
        event
        for event in trace_events
        if event.get("worker") == "fracture_preview" and event["kind"] in {"worker.start", "worker.spawn", "worker.event", "worker.result"}
    ]
    assert {event["kind"] for event in fracture_worker_events} >= {
        "worker.start",
        "worker.spawn",
        "worker.event",
        "worker.result",
    }
    assert all("preview_job_id" in event.get("data", {}) for event in fracture_worker_events)
    assert any(event["kind"] == "scene.ready" and event.get("job") == "fracture_preview" for event in trace_events)
    assert any(event["kind"] == "viewport.set_scene" and event.get("job") == "fracture_preview" for event in trace_events)


def test_proxy_preview_keeps_stalled_process_isolated_without_local_fallback(monkeypatch, qtbot, tmp_path) -> None:
    class _StalledProcess:
        exitcode = None

        def __init__(self) -> None:
            self.terminated = False

        def is_alive(self) -> bool:
            return not self.terminated

        def join(self, timeout=None) -> None:
            return None

        def terminate(self) -> None:
            self.terminated = True

    calls: dict[str, object] = {}
    process = _StalledProcess()

    def start_proxy_mesh_process(request, settings, action):
        calls["start_proxy_mesh_process"] = {
            "request": request,
            "settings": settings,
            "action": action,
        }
        return process, [], object()

    deps = replace(_build_fake_deps(calls), start_proxy_mesh_process=start_proxy_mesh_process)
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=deps,
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    tree_xml = tmp_path / "tree.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    window.source_input.setText(str(tree_xml))
    window.output_input.setText(str(tmp_path / "tree.usda"))

    qtbot.mouseClick(window.geometry_panel.preview_proxy_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window._proxy_preview_dialog is not None, timeout=3000)
    qtbot.waitUntil(lambda: calls.get("start_proxy_mesh_process", {}).get("action") == "preview", timeout=3000)

    assert process.terminated is False
    assert window._proxy_preview_dialog.status_label.text() == "Generating..."
    assert window._background_jobs.proxy_preview_running is True


def test_proxy_preview_retries_transient_worker_error_once(monkeypatch, qtbot, tmp_path) -> None:
    class _FinishedProcess:
        exitcode = 0

        def is_alive(self) -> bool:
            return False

        def join(self, timeout=None) -> None:
            return None

        def terminate(self) -> None:
            return None

    calls: dict[str, object] = {"starts": 0, "errors": []}

    def start_proxy_mesh_process(request, settings, action):
        assert action == "preview"
        calls["starts"] += 1
        if calls["starts"] == 1:
            return (
                _FinishedProcess(),
                [
                    ("error_traceback", "Traceback\nTypeError: bad operand type for unary -: 'type'"),
                    ("result", ProxyMeshJobResult(error_message="bad operand type for unary -: 'type'")),
                ],
                object(),
            )
        return (
            _FinishedProcess(),
            [("result", ProxyMeshJobResult(proxy=_build_fake_deps(calls).generate_proxy_mesh_from_source_request(request, settings)))],
            object(),
        )

    deps = replace(_build_fake_deps(calls), start_proxy_mesh_process=start_proxy_mesh_process)
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=deps,
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    tree_xml = tmp_path / "tree.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    window.source_input.setText(str(tree_xml))
    window.output_input.setText(str(tmp_path / "tree.usda"))

    qtbot.mouseClick(window.geometry_panel.preview_proxy_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: window._proxy_preview_dialog is not None and window._proxy_preview_dialog.current_proxy is not None,
        timeout=3000,
    )

    assert calls["starts"] == 2
    assert window._proxy_preview_dialog.status_label.text() == "1 polygons / 3 points"
    assert window._background_jobs.proxy_preview_running is False


def test_qt_window_generates_proxy_usda_beside_main_output(monkeypatch, qtbot, tmp_path) -> None:
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
    output_path = tmp_path / "exports" / "tree.usda"
    output_path.parent.mkdir()
    window.source_input.setText(str(tree_xml))
    window.output_input.setText(str(output_path))

    qtbot.mouseClick(window.generate_proxy_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "Wrote Proxy Mesh USDA" in window.status_label.text(), timeout=3000)

    assert calls["start_proxy_mesh_process"]["action"] == "export"
    assert "export_proxy_usda_from_source_request" in calls
    assert calls["export_proxy_usda_from_source_request"]["request"].output_path == str(output_path)
    assert "Wrote Proxy Mesh USDA" in window.status_label.text()


def test_qt_window_proxy_request_uses_only_proxy_relevant_operator_intent(monkeypatch, qtbot, tmp_path) -> None:
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
    fake_fbx = tmp_path / "branch.fbx"
    fake_fbx.write_text("", encoding="utf-8")
    window.source_input.setText(str(tree_xml))
    window.output_input.setText(str(tmp_path / "tree.usda"))

    base_row = window.materials_panel._base_rows[0]
    base_row.path_edit.setText("/Game/Test/M_Base.M_Base")
    base_row.udim_mode_combo.setCurrentIndex(base_row.udim_mode_combo.findData(UdimMode.WRITE_SECONDARY_UV_OFFSET.value))
    base_row.udim_id_spin.setValue(1028)
    geometry_row = window.geometry_panel._rows[0]
    geometry_row.fbx_edit.setText(str(fake_fbx))
    geometry_row.source_mode_combo.setCurrentIndex(
        geometry_row.source_mode_combo.findData(PrototypeSourceMode.FBX_FILE.value)
    )

    qtbot.mouseClick(window.generate_proxy_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "Wrote Proxy Mesh USDA" in window.status_label.text(), timeout=3000)

    request = calls["start_proxy_mesh_process"]["request"]
    assert isinstance(request, ProxyMeshSourceRequest)
    assert request.input_path == str(tree_xml)
    assert request.output_path == str(tmp_path / "tree.usda")
    assert not hasattr(request, "base_material_overrides")
    assert not hasattr(request, "udim_material_settings")
    assert not hasattr(request, "prototype_source_configs")


def test_qt_window_does_not_export_stale_proxy_preview_after_settings_change(monkeypatch, qtbot, tmp_path) -> None:
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
    window.geometry_panel.apply_proxy_settings(ProxyMeshSettings(final_polycount=2400))
    window._handle_proxy_settings_changed()

    qtbot.mouseClick(window.geometry_panel.preview_proxy_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window._proxy_preview_dialog.current_proxy is not None, timeout=3000)
    window._proxy_preview_dialog.close()
    qtbot.waitUntil(lambda: window._proxy_mesh_preview_result is not None, timeout=3000)

    window.geometry_panel.apply_proxy_settings(ProxyMeshSettings(final_polycount=3600))
    window._handle_proxy_settings_changed()
    qtbot.waitUntil(lambda: window._proxy_mesh_preview_result is None, timeout=3000)

    qtbot.mouseClick(window.generate_proxy_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "Wrote Proxy Mesh USDA" in window.status_label.text(), timeout=3000)

    assert "export_generated_proxy_usda_from_source_request" not in calls
    assert calls["start_proxy_mesh_process"]["action"] == "export"
    assert calls["export_proxy_usda_from_source_request"]["settings"].final_polycount == 3600


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


def test_qt_window_reanchors_relative_output_to_selected_xml_folder(qtbot, tmp_path) -> None:
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=_build_fake_deps({}),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    window.output_input.setText("SkeletalAssemblyTest_Spruce_Big_low.usda")
    tree_xml = tmp_path / "XMLtoUSD_miscFiles" / "SkeletalAssemblyTest_Spruce_Big_low.xml"
    tree_xml.parent.mkdir(parents=True, exist_ok=True)
    tree_xml.write_text("<tree/>", encoding="utf-8")
    window.source_input.setText(str(tree_xml))

    assert window.output_input.text() == str(tree_xml.with_suffix(".usda"))


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
    assert Path(observed["output_directory"]) == remembered_output.with_name("selected.usda")
    assert saved.last_input_path == str(selected_xml)
    assert saved.last_output_path == str(selected_output)


def test_qt_window_restores_last_xml_and_derives_output_when_only_input_was_remembered(qtbot, tmp_path) -> None:
    settings_path = tmp_path / "gui_settings.json"
    remembered_xml = tmp_path / "xml_folder" / "last.xml"
    remembered_xml.parent.mkdir()
    remembered_xml.write_text("<tree/>", encoding="utf-8")
    save_gui_settings(settings_path, GuiSettingsSnapshot(last_input_path=str(remembered_xml)))

    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=_build_fake_deps({}),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=settings_path,
    )
    qtbot.addWidget(window)
    window.show()

    assert window.source_input.text() == str(remembered_xml)
    assert window.output_input.text() == str(remembered_xml.with_suffix(".usda"))
    assert window.convert_button.isEnabled()


def test_wind_preview_session_autosave_failure_does_not_escape(qtbot, tmp_path: Path) -> None:
    deps = replace(
        _build_fake_deps({}),
        save_gui_settings=lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("settings locked")),
    )
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=deps,
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)

    window._save_wind_preview_session({"schema_version": 1, "input_path": "tree.xml"})

    assert window._operator_snapshot.wind_preview_session["input_path"] == "tree.xml"
    assert "autosave failed" in window.status_label.text()


def test_qt_window_persists_wind_settings_for_next_session(monkeypatch, qtbot, tmp_path) -> None:
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

    settings_path = tmp_path / "gui_settings.json"
    tree_xml = tmp_path / "tree.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    first_window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=_build_fake_deps({}),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=settings_path,
    )
    qtbot.addWidget(first_window)
    first_window.show()
    first_window.source_input.setText(str(tree_xml))
    first_window.output_input.setText(str(tree_xml.with_suffix(".usda")))
    qtbot.mouseClick(first_window.wind_panel.refresh_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: bool(first_window.wind_panel._rows), timeout=3000)

    first_window.wind_panel.ground_cover_checkbox.setChecked(True)
    first_window.wind_panel.gust_spin.setValue(0.6)
    row = first_window.wind_panel._rows[0]
    row.trunk_checkbox.setChecked(False)
    row.dual_checkbox.setChecked(False)
    row.influence_spin.setValue(0.75)
    first_window._save_operator_state()

    saved = load_gui_settings(settings_path)
    assert saved.last_input_path == str(tree_xml)
    assert saved.gust_attenuation == pytest.approx(0.6)
    assert saved.is_ground_cover is True
    assert saved.wind_group_settings["0"].is_trunk_group is False
    assert saved.wind_group_settings["0"].use_dual_influence is False
    assert saved.wind_group_settings["0"].influence == pytest.approx(0.75)

    second_window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=_build_fake_deps({}),
        state_path=tmp_path / "ui_next_state_2.json",
        operator_settings_path=settings_path,
    )
    qtbot.addWidget(second_window)
    second_window.show()
    qtbot.mouseClick(second_window.wind_panel.refresh_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: bool(second_window.wind_panel._rows), timeout=3000)

    restored_row = second_window.wind_panel._rows[0]
    assert second_window.source_input.text() == str(tree_xml)
    assert second_window.wind_panel.is_ground_cover_enabled() is True
    assert second_window.wind_panel.gust_attenuation() == pytest.approx(0.6)
    assert restored_row.trunk_checkbox.isChecked() is False
    assert restored_row.dual_checkbox.isChecked() is False
    assert restored_row.influence_spin.value() == pytest.approx(0.75)


def test_qt_window_keeps_live_wind_changes_in_snapshot_before_refresh(monkeypatch, qtbot, tmp_path) -> None:
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

    settings_path = tmp_path / "gui_settings.json"
    tree_xml = tmp_path / "tree.xml"
    tree_xml.write_text("<tree/>", encoding="utf-8")
    window = MainWindow(
        load_theme(),
        UiShellState(),
        dependencies=_build_fake_deps({}),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=settings_path,
    )
    qtbot.addWidget(window)
    window.show()

    window.source_input.setText(str(tree_xml))
    qtbot.mouseClick(window.wind_panel.refresh_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: bool(window.wind_panel._rows), timeout=3000)

    row = window.wind_panel._rows[0]
    row.trunk_checkbox.setChecked(False)
    row.dual_checkbox.setChecked(False)
    row.influence_spin.setValue(0.75)
    window.wind_panel.ground_cover_checkbox.setChecked(True)

    window.refresh_wind_groups()
    qtbot.waitUntil(
        lambda: (
            bool(window.wind_panel._rows)
            and window.wind_panel._rows[0].trunk_checkbox.isChecked() is False
            and window.wind_panel._rows[0].dual_checkbox.isChecked() is False
            and window.wind_panel._rows[0].influence_spin.value() == pytest.approx(0.75)
        ),
        timeout=3000,
    )

    window._save_operator_state()
    saved = load_gui_settings(settings_path)

    assert saved.wind_group_settings["0"].is_trunk_group is False
    assert saved.wind_group_settings["0"].use_dual_influence is False
    assert saved.wind_group_settings["0"].influence == pytest.approx(0.75)
    assert saved.is_ground_cover is True


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
    assert window.help_callout.isWindow()
    assert "Start here for the tutorial" in window.help_callout_title.text()
    assert window.help_callout_dismiss_button.text() == "\u00d7"
    assert window.help_callout.y() > window.title_bar.y()

    qtbot.wait(50)
    assert window.help_callout.isVisible()

    qtbot.mouseClick(window.help_callout_dismiss_button, Qt.MouseButton.LeftButton)

    assert window.help_callout.isHidden()
    window.close()
    restored = load_ui_shell_state(state_path)
    assert restored.help_prompt_dismissed is True


def test_qt_window_restores_and_saves_active_tab(qtbot, tmp_path) -> None:
    state_path = tmp_path / "ui_next_state.json"
    window = MainWindow(
        load_theme(),
        UiShellState(active_tab_name="Materials"),
        dependencies=_build_fake_deps({}),
        state_path=state_path,
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    assert window.tabs.tabText(window.tabs.currentIndex()) == "Materials"

    window.tabs.setCurrentIndex(window.tabs.indexOf(window.geometry_panel))
    window.close()

    assert load_ui_shell_state(state_path).active_tab_name == "Geometry"


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
    monkeypatch.setattr("xml_to_usda.diagnostics_bundle.default_build_info_path", lambda: build_info_path)
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
