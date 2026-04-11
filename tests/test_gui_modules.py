from __future__ import annotations

import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from tkinter import ttk

import pytest

import xml_to_usda.gui as gui_module
from xml_to_usda.discovery_service import (
    BaseMaterialDiscovery,
    BaseMaterialRowSpec,
    PrototypeDiscovery,
    PrototypeMaterialSlotRowSpec,
    PrototypeRowSpec,
)
from xml_to_usda.gui_background_jobs import GuiBackgroundJobsBridge
from xml_to_usda.gui_materials_panel import MaterialsPanelController
from xml_to_usda.gui_part_sources_panel import PartSourcesPanelController
from xml_to_usda.gui_wind_panel import WindPanelController
from xml_to_usda.models import CpuProfile, DynamicWindSimulationGroup, FbxMaterialMode, PrototypeSourceMode
from xml_to_usda.qt_ui.theme import build_stylesheet, load_theme
from xml_to_usda.settings_service import BaseMaterialSettingRecord, WindGroupSettingRecord


def _build_tk_root_or_skip() -> tk.Tk:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk is unavailable in this environment: {exc}")
    root.withdraw()
    return root


def test_gui_public_facade_exports_compat_symbols() -> None:
    from xml_to_usda.gui import ConversionApp, format_conversion_results, format_wind_group_summary, format_wind_json_result, main

    assert ConversionApp is gui_module.ConversionApp
    assert format_conversion_results is gui_module.format_conversion_results
    assert format_wind_group_summary is gui_module.format_wind_group_summary
    assert format_wind_json_result is gui_module.format_wind_json_result
    assert main is gui_module.main


def test_qt_theme_styles_conversion_mode_menu_light() -> None:
    stylesheet = build_stylesheet(load_theme())

    assert "QMenu {" in stylesheet
    assert "QMenu::item" in stylesheet
    assert "background: #DCE5E8" in stylesheet
    assert "color: #1A1A15" in stylesheet


def test_materials_panel_round_trip_collects_and_serializes() -> None:
    root = _build_tk_root_or_skip()
    try:
        container = ttk.Frame(root)
        summary_var = tk.StringVar()
        controller = MaterialsPanelController(
            summary_var=summary_var,
            rows_container=container,
            refresh_scroll_region=lambda: None,
            on_persisted_field_change=lambda *_args: None,
        )

        controller.rebuild(
            BaseMaterialDiscovery(
                summary="Found 1 base XML material slot(s).",
                rows=(BaseMaterialRowSpec(source_id=7, source_name="Bark"),),
            )
        )

        controller.rows[0]["material_path_var"].set("/Game/Test/M_Bark.M_Bark")

        assert controller.collect_overrides()[0].ue_asset_path == "/Game/Test/M_Bark.M_Bark"
        assert controller.serialize_settings() == (
            BaseMaterialSettingRecord(
                source_id=7,
                source_name="Bark",
                ue_asset_path="/Game/Test/M_Bark.M_Bark",
            ),
        )
    finally:
        root.destroy()


def test_part_sources_panel_restores_modes_and_collects_slot_overrides(tmp_path: Path) -> None:
    root = _build_tk_root_or_skip()
    try:
        container = ttk.Frame(root)
        summary_var = tk.StringVar()
        fake_fbx = tmp_path / "spruce_branch.fbx"
        fake_fbx.write_text("", encoding="utf-8")

        controller = PartSourcesPanelController(
            summary_var=summary_var,
            rows_container=container,
            refresh_scroll_region=lambda: None,
            on_persisted_field_change=lambda *_args: None,
            cpu_profile_getter=lambda: CpuProfile.BALANCED,
            inspect_fbx_material_slot_rows_fn=lambda *_args, **_kwargs: (
                PrototypeMaterialSlotRowSpec(slot_name="Bark", face_count=12),
                PrototypeMaterialSlotRowSpec(slot_name="Needles", face_count=24),
            ),
        )

        controller.rebuild(
            PrototypeDiscovery(
                summary="Found 13 repeated branch instances across 1 prototype(s).",
                rows=(
                    PrototypeRowSpec(
                        source_key="Mesh_1",
                        source_name="Twig_01",
                        source_mesh_id=1,
                        instance_count=13,
                    ),
                ),
            )
        )

        row = controller.rows[0]
        row["source_mode_var"].set(PrototypeSourceMode.FBX_FILE.value)
        row["fbx_var"].set(str(fake_fbx))
        row["fbx_material_mode_var"].set(FbxMaterialMode.MATERIAL_SLOTS.value)

        assert len(row["material_slot_rows"]) == 2
        row["material_slot_rows"][0]["path_var"].set("/Game/Test/M_Bark.M_Bark")

        configs = controller.collect_part_source_configs()
        assert configs[0].mode == PrototypeSourceMode.FBX_FILE
        assert configs[0].fbx_material_mode == FbxMaterialMode.MATERIAL_SLOTS
        assert configs[0].fbx_material_slot_overrides[0].slot_name == "Bark"
        assert configs[0].fbx_material_slot_overrides[0].ue_asset_path == "/Game/Test/M_Bark.M_Bark"

        row["source_mode_var"].set(PrototypeSourceMode.UNREAL_ASSET.value)
        row["asset_var"].set("/Game/TreeParts/SK_Twig01.SK_Twig01")
        use_existing_part_meshes, mappings = controller.collect_existing_part_overrides()
        assert use_existing_part_meshes is True
        assert mappings == (("Twig_01", "/Game/TreeParts/SK_Twig01.SK_Twig01"),)
    finally:
        root.destroy()


def test_wind_panel_round_trip_collects_and_serializes() -> None:
    root = _build_tk_root_or_skip()
    try:
        container = ttk.Frame(root)
        controller = WindPanelController(
            container=container,
            max_wind_influence=1.0,
            max_shift_top=1.0,
            schedule_settings_save=lambda: None,
        )
        controller.set_persisted_settings(
            {
                "0": WindGroupSettingRecord(
                    use_dual_influence=False,
                    influence=0.35,
                    shift_top=0.1,
                )
            }
        )
        controller.rebuild(
            (
                DynamicWindSimulationGroup(group_index=0, branch_order=0, is_trunk_group=True),
                DynamicWindSimulationGroup(group_index=1, branch_order=2, is_trunk_group=False),
            )
        )

        assert controller.rows[0]["single_frame"].winfo_manager() == "grid"
        assert controller.rows[0]["dual_frame"].winfo_manager() == ""

        controller.rows[1]["dual_influence_var"].set(True)
        controller.rows[1]["min_influence_var"].set(0.2)
        controller.rows[1]["max_influence_var"].set(0.6)
        controller.rows[1]["shift_var"].set(0.15)

        settings = controller.serialize_settings()
        groups = controller.collect_group_settings()

        assert settings["0"].influence == pytest.approx(0.35)
        assert settings["1"].max_influence == pytest.approx(0.6)
        assert groups[1].use_dual_influence is True
        assert groups[1].shift_top == pytest.approx(0.15)
    finally:
        root.destroy()


def test_background_jobs_bridge_retries_known_wind_error_on_main_thread() -> None:
    status_var = SimpleNamespace(value="", set=lambda value: setattr(status_var, "value", value))
    recovered = object()
    app = SimpleNamespace(
        status_var=status_var,
        _deps=SimpleNamespace(
            should_retry_wind_error=lambda error_type, message: error_type == "SystemError",
            inspect_wind_groups=lambda _request: recovered,
            format_wind_error=lambda payload: f"{payload['type']}: {payload['message']}",
        ),
        _set_log=lambda _text: None,
        _append_runtime_log_entry=lambda *_args, **_kwargs: None,
    )

    handled, dynamic_wind = GuiBackgroundJobsBridge(app).retry_wind_group_refresh_if_needed(
        request=object(),
        error_payload={"type": "SystemError", "message": "setobject.c", "traceback": "trace"},
    )

    assert handled is True
    assert dynamic_wind is recovered
    assert status_var.value == "Retrying wind group inspection on the main thread..."
