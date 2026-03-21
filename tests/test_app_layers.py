from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from xml_to_usda.models import (
    ConversionRequest,
    ConversionResult,
    DynamicWindData,
    DynamicWindJointAssignment,
    DynamicWindSimulationGroup,
    OutputMode,
    ValidationIssue,
    WindJsonResult,
)
from xml_to_usda.naming import build_prototype_identities, make_stable_prim_name
from xml_to_usda.pipeline import REPO_ROOT, convert_file, convert_request


DATA_DIR = Path(__file__).parent / "data"
SIMPLE_TREE_01 = Path(__file__).resolve().parents[1] / "samples" / "speedtree" / "simple_tree" / "variants" / "SimpleTree_01.xml"


def test_stable_prim_name_is_ascii_safe() -> None:
    assert make_stable_prim_name("Leaf Cluster 01") == "Leaf_Cluster_01"
    assert make_stable_prim_name("123 caf\u00e9") == "_123_caf"
    assert make_stable_prim_name("!!!") == "Prototype"


def test_prototype_identities_are_deterministic_and_unique() -> None:
    identities = build_prototype_identities(("Leaf A", "Leaf A", "Leaf-A"))

    assert [identity.prim_name for identity in identities] == ["Leaf_A", "Leaf_A_2", "Leaf_A_3"]


def test_generated_outputs_cannot_be_written_into_vault() -> None:
    output_path = REPO_ROOT / "vault" / "notes" / "illegal_output.usda"

    with pytest.raises(ValueError, match="immutable vault"):
        convert_file(str(SIMPLE_TREE_01), str(output_path))


def test_batch_ready_request_supports_output_directory_and_template(tmp_path: Path) -> None:
    request = ConversionRequest(
        input_paths=(str(SIMPLE_TREE_01),),
        output_directory=str(tmp_path),
        output_naming_template="{stem}_generated",
        output_mode=OutputMode.SELF_CONTAINED,
    )

    result = convert_request(request)[0]

    assert result.output_path is not None
    assert result.output_path.endswith("SimpleTree_01_generated.usda")
    assert Path(result.output_path).exists()
    assert result.usda_document is not None


def _build_tk_root_or_skip():
    tkinter = pytest.importorskip("tkinter")
    try:
        root = tkinter.Tk()
    except tkinter.TclError as exc:
        pytest.skip(f"tkinter runtime is not usable in this environment: {exc}")
    root.withdraw()
    return tkinter, root


def test_gui_smoke_builds_window() -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    try:
        app = ConversionApp(root)
        assert app.root.title() == "Convert XML -> USDA"
        assert hasattr(app, "bark_material_var")
        assert hasattr(app, "leaves_material_var")
        assert hasattr(app, "use_existing_part_meshes_var")
        assert hasattr(app, "gust_attenuation_var")
        assert hasattr(app, "wind_frame")
        assert hasattr(app, "materials_frame")
        assert hasattr(app, "part_mesh_frame")
        assert hasattr(app, "part_mesh_rows_container")
        assert hasattr(app, "log_frame")
        assert hasattr(app, "scroll_canvas")
        assert hasattr(app, "scrollbar")
        assert "Dynamic Wind JSON" in app.status_var.get()
    finally:
        root.destroy()


def test_gui_formatter_renders_diagnostics() -> None:
    from xml_to_usda.gui import format_conversion_results

    result = ConversionResult(
        input_path="input.xml",
        output_path="output.usda",
        diagnostics=(ValidationIssue(severity="warning", code="demo", message="demo warning"),),
        usda_document=None,
    )

    rendered = format_conversion_results((result,))

    assert "Input: input.xml" in rendered
    assert "[warning] demo: demo warning" in rendered
    assert "Status: failed" in rendered


def test_convert_file_applies_baseline_material_overrides(tmp_path: Path) -> None:
    result = convert_file(
        str(SIMPLE_TREE_01),
        str(tmp_path / "tree.usda"),
        bark_material_path="/Game/TestMaterials/M_Bark_Test",
        leaves_material_path="/Game/TestMaterials/M_Leaves_Test",
    )

    assert result.usda_document is not None
    assert 'token outputs:unreal:surface.connect = </Tree/Materials/Material_1_1/Material_1_1_unreal_shader.outputs:out>' in result.usda_document.text
    assert 'token outputs:unreal:surface.connect = </Tree/Materials/Material_2_2/Material_2_2_unreal_shader.outputs:out>' in result.usda_document.text
    assert 'uniform asset info:unreal:sourceAsset = @/Game/TestMaterials/M_Bark_Test.M_Bark_Test@' in result.usda_document.text
    assert 'uniform asset info:unreal:sourceAsset = @/Game/TestMaterials/M_Leaves_Test.M_Leaves_Test@' in result.usda_document.text


def test_gui_run_conversion_passes_material_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    calls: list[tuple[str, str, str | None, str | None, bool, tuple[tuple[str, str], ...]]] = []

    def fake_convert_file(
        input_path,
        output_path,
        output_mode=OutputMode.SELF_CONTAINED,
        bark_material_path=None,
        leaves_material_path=None,
        use_existing_part_meshes=False,
        part_mesh_asset_paths=(),
    ):
        calls.append(
            (
                input_path,
                output_path,
                bark_material_path,
                leaves_material_path,
                use_existing_part_meshes,
                part_mesh_asset_paths,
            )
        )
        return ConversionResult(
            input_path=input_path,
            output_path=output_path,
            diagnostics=(),
            usda_document=Mock(),
        )

    monkeypatch.setattr("xml_to_usda.gui.convert_file", fake_convert_file)
    monkeypatch.setattr("xml_to_usda.gui.messagebox.showinfo", lambda *args, **kwargs: None)
    monkeypatch.setattr("xml_to_usda.gui.messagebox.showerror", lambda *args, **kwargs: None)

    try:
        settings_path = tmp_path / "gui_settings.json"
        monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
        monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", settings_path)
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))
        app.output_var.set(str(Path("out.usda")))
        app.bark_material_var.set("/Game/TestMaterials/M_Bark_Test")
        app.leaves_material_var.set("/Game/TestMaterials/M_Leaves_Test")

        app.run_conversion()

        assert calls == [
            (
                str(SIMPLE_TREE_01),
                "out.usda",
                "/Game/TestMaterials/M_Bark_Test",
                "/Game/TestMaterials/M_Leaves_Test",
                False,
                (),
            )
        ]
        assert "Material overrides:" in app.log_widget.get("1.0", "end-1c")
    finally:
        root.destroy()


def test_gui_run_conversion_passes_part_mesh_xml_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    calls: list[tuple[str, str, str | None, str | None, bool, tuple[tuple[str, str], ...]]] = []

    def fake_convert_file(
        input_path,
        output_path,
        output_mode=OutputMode.SELF_CONTAINED,
        bark_material_path=None,
        leaves_material_path=None,
        use_existing_part_meshes=False,
        part_mesh_asset_paths=(),
    ):
        calls.append(
            (
                input_path,
                output_path,
                bark_material_path,
                leaves_material_path,
                use_existing_part_meshes,
                part_mesh_asset_paths,
            )
        )
        return ConversionResult(
            input_path=input_path,
            output_path=output_path,
            diagnostics=(),
            usda_document=Mock(),
        )

    monkeypatch.setattr("xml_to_usda.gui.convert_file", fake_convert_file)
    monkeypatch.setattr("xml_to_usda.gui.messagebox.showinfo", lambda *args, **kwargs: None)
    monkeypatch.setattr("xml_to_usda.gui.messagebox.showerror", lambda *args, **kwargs: None)

    try:
        settings_path = tmp_path / "gui_settings.json"
        monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
        monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", settings_path)
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))
        app.output_var.set("out.usda")
        app._part_mesh_rows[0]["use_unreal_var"].set(True)
        app._part_mesh_rows[0]["asset_var"].set("/Game/TreeParts/SK_Twig01.SK_Twig01")

        app.run_conversion()

        assert calls == [
            (
                str(SIMPLE_TREE_01),
                "out.usda",
                None,
                None,
                True,
                (("Twig_01", "/Game/TreeParts/SK_Twig01.SK_Twig01"),),
            )
        ]
    finally:
        root.destroy()


def test_gui_refresh_wind_groups_builds_slider_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    dynamic_wind = DynamicWindData(
        joint_assignments=(
            DynamicWindJointAssignment(joint_name="root", simulation_group_index=0, branch_order=0),
            DynamicWindJointAssignment(joint_name="branch_1", simulation_group_index=1, branch_order=1),
            DynamicWindJointAssignment(joint_name="branch_2", simulation_group_index=2, branch_order=2),
        ),
        simulation_groups=(
            DynamicWindSimulationGroup(group_index=0, branch_order=0, is_trunk_group=True),
            DynamicWindSimulationGroup(group_index=1, branch_order=1),
            DynamicWindSimulationGroup(group_index=2, branch_order=2),
        ),
    )

    monkeypatch.setattr("xml_to_usda.gui.inspect_wind_data", lambda _input_path, is_ground_cover=False: dynamic_wind)
    monkeypatch.setattr("xml_to_usda.gui.messagebox.showerror", lambda *args, **kwargs: None)

    try:
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))

        app.refresh_wind_groups()

        assert len(app._wind_group_rows) == 3
        assert app._wind_group_rows[0]["group_index"] == 0
        assert app._wind_group_rows[1]["group_index"] == 1
    finally:
        root.destroy()


def test_gui_generate_wind_json_uses_slider_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    dynamic_wind = DynamicWindData(
        joint_assignments=(DynamicWindJointAssignment(joint_name="root", simulation_group_index=0, branch_order=0),),
        simulation_groups=(
            DynamicWindSimulationGroup(group_index=0, branch_order=0, is_trunk_group=True),
            DynamicWindSimulationGroup(group_index=1, branch_order=1),
        ),
    )
    calls: list[tuple] = []

    def fake_generate_wind_json(
        input_path,
        output_path,
        group_settings=(),
        gust_attenuation=0.0,
        is_ground_cover=False,
    ):
        calls.append((input_path, output_path, group_settings, gust_attenuation, is_ground_cover))
        return WindJsonResult(
            input_path=input_path,
            output_path=output_path,
            dynamic_wind=DynamicWindData(
                joint_assignments=dynamic_wind.joint_assignments,
                simulation_groups=group_settings,
                gust_attenuation=gust_attenuation,
                is_ground_cover=is_ground_cover,
            ),
        )

    monkeypatch.setattr("xml_to_usda.gui.inspect_wind_data", lambda _input_path, is_ground_cover=False: dynamic_wind)
    monkeypatch.setattr("xml_to_usda.gui.generate_wind_json", fake_generate_wind_json)
    monkeypatch.setattr("xml_to_usda.gui.messagebox.showinfo", lambda *args, **kwargs: None)
    monkeypatch.setattr("xml_to_usda.gui.messagebox.showerror", lambda *args, **kwargs: None)

    try:
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))
        app.output_var.set("out.usda")
        app.refresh_wind_groups()
        app._wind_group_rows[0]["influence_var"].set(0.7)
        app._wind_group_rows[0]["shift_var"].set(0.2)
        app._wind_group_rows[1]["influence_var"].set(0.55)
        app._wind_group_rows[1]["shift_var"].set(0.05)
        app.gust_attenuation_var.set(0.6)
        app.is_ground_cover_var.set(True)

        app.run_generate_wind_json()

        assert calls
        assert calls[0][0] == str(SIMPLE_TREE_01)
        assert calls[0][1] == "out_DynamicWind.json"
        assert calls[0][2][0].influence == pytest.approx(0.7)
        assert calls[0][2][0].shift_top == pytest.approx(0.2)
        assert calls[0][2][1].influence == pytest.approx(0.55)
        assert calls[0][3] == pytest.approx(0.6)
        assert calls[0][4] is True
    finally:
        root.destroy()


def test_gui_refresh_part_mesh_rows_autoloads_xml_meshes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    try:
        settings_path = tmp_path / "gui_settings.json"
        monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
        monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", settings_path)
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))

        assert len(app._part_mesh_rows) == 2
        assert [row["source_name"] for row in app._part_mesh_rows] == ["Twig_01", "Twig_02"]
        assert [row["mesh_id"] for row in app._part_mesh_rows] == [1, 2]
        assert str(app._part_mesh_rows[0]["asset_entry"].cget("state")) == "disabled"
    finally:
        root.destroy()


def test_gui_part_mesh_reuse_persists_per_xml_and_restores_on_reload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    settings_path = tmp_path / "gui_settings.json"
    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", settings_path)

    try:
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))
        row = app._part_mesh_rows[0]
        row["use_unreal_var"].set(True)
        row["asset_var"].set("/Game/TreeParts/SK_Twig01.SK_Twig01")
        app._handle_window_close()

        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        key = str(SIMPLE_TREE_01.resolve())
        assert payload["part_mesh_settings_by_input_path"][key][0] == {
            "source_name": "Twig_01",
            "source_key": "Mesh_1",
            "use_unreal_reference": True,
            "unreal_asset_path": "/Game/TreeParts/SK_Twig01.SK_Twig01",
        }
    finally:
        try:
            root.destroy()
        except Exception:
            pass

    _, root = _build_tk_root_or_skip()
    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", settings_path)

    try:
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))
        restored_row = app._part_mesh_rows[0]

        assert restored_row["use_unreal_var"].get() is True
        assert restored_row["asset_var"].get() == "/Game/TreeParts/SK_Twig01.SK_Twig01"
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_gui_part_mesh_settings_do_not_cross_contaminate_between_xml_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    settings_path = tmp_path / "gui_settings.json"
    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", settings_path)

    try:
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))
        app._part_mesh_rows[0]["use_unreal_var"].set(True)
        app._part_mesh_rows[0]["asset_var"].set("/Game/TreeParts/SK_Twig01.SK_Twig01")
        app._handle_window_close()
    finally:
        try:
            root.destroy()
        except Exception:
            pass

    _, root = _build_tk_root_or_skip()
    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", settings_path)
    other_xml = Path(__file__).resolve().parents[1] / "references" / "speedtree" / "xml" / "SkeletyalAssemblyTest_01.xml"

    try:
        app = ConversionApp(root)
        app.input_var.set(str(other_xml))

        assert len(app._part_mesh_rows) == 1
        assert app._part_mesh_rows[0]["source_name"] == "Suzanne_Leaf"
        assert app._part_mesh_rows[0]["use_unreal_var"].get() is False
        assert app._part_mesh_rows[0]["asset_var"].get() == ""
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_gui_collapsible_sections_toggle_visibility() -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    try:
        app = ConversionApp(root)

        materials_content = app._sections["materials"]["content"]
        wind_content = app._sections["wind"]["content"]
        log_content = app._sections["log"]["content"]

        assert materials_content.winfo_manager() == "grid"
        assert wind_content.winfo_manager() == "grid"
        assert log_content.winfo_manager() == "grid"

        app._toggle_section("materials")
        app._toggle_section("wind")
        app._toggle_section("log")
        root.update_idletasks()

        assert materials_content.winfo_manager() == ""
        assert wind_content.winfo_manager() == ""
        assert log_content.winfo_manager() == ""

        app._toggle_section("materials")
        app._toggle_section("wind")
        app._toggle_section("log")
        root.update_idletasks()

        assert materials_content.winfo_manager() == "grid"
        assert wind_content.winfo_manager() == "grid"
        assert log_content.winfo_manager() == "grid"
    finally:
        root.destroy()


def test_gui_loads_persisted_material_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    settings_path = tmp_path / "gui_settings.json"
    settings_path.write_text(
        '{"bark_material_path": "/Game/TestMaterials/M_Bark_Test", "leaves_material_path": "/Game/TestMaterials/M_Leaves_Test", "gust_attenuation": 0.25, "is_ground_cover": true, "wind_group_settings": {"0": {"influence": 1.4, "shift_top": 0.1}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", settings_path)

    try:
        app = ConversionApp(root)
        assert app.bark_material_var.get() == "/Game/TestMaterials/M_Bark_Test"
        assert app.leaves_material_var.get() == "/Game/TestMaterials/M_Leaves_Test"
        assert app.gust_attenuation_var.get() == pytest.approx(0.25)
        assert app.is_ground_cover_var.get() is True
    finally:
        root.destroy()


def test_gui_persists_material_paths_after_successful_conversion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    settings_path = tmp_path / "gui_settings.json"
    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr("xml_to_usda.gui.messagebox.showinfo", lambda *args, **kwargs: None)
    monkeypatch.setattr("xml_to_usda.gui.messagebox.showerror", lambda *args, **kwargs: None)

    def fake_convert_file(
        input_path,
        output_path,
        output_mode=OutputMode.SELF_CONTAINED,
        bark_material_path=None,
        leaves_material_path=None,
        use_existing_part_meshes=False,
        part_mesh_asset_paths=(),
    ):
        return ConversionResult(
            input_path=input_path,
            output_path=output_path,
            diagnostics=(),
            usda_document=Mock(),
        )

    monkeypatch.setattr("xml_to_usda.gui.convert_file", fake_convert_file)

    try:
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))
        app.output_var.set("out.usda")
        app.bark_material_var.set("/Game/TestMaterials/M_Bark_Test")
        app.leaves_material_var.set("/Game/TestMaterials/M_Leaves_Test")

        app.run_conversion()

        assert settings_path.exists()
        assert settings_path.read_text(encoding="utf-8") == (
            '{\n'
            '  "bark_material_path": "/Game/TestMaterials/M_Bark_Test",\n'
            '  "leaves_material_path": "/Game/TestMaterials/M_Leaves_Test",\n'
            '  "gust_attenuation": 0.0,\n'
            '  "is_ground_cover": false,\n'
            '  "wind_group_settings": {}\n'
            '}'
        )
    finally:
        root.destroy()


def test_gui_persists_material_paths_without_running_conversion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    settings_path = tmp_path / "gui_settings.json"
    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", settings_path)

    app = ConversionApp(root)
    app.bark_material_var.set("/Game/Assembly/Custom/Bark_A.Bark_A")
    app.leaves_material_var.set("/Game/Assembly/Custom/Leaves_A.Leaves_A")
    app._handle_window_close()

    assert settings_path.exists()
    assert settings_path.read_text(encoding="utf-8") == (
        '{\n'
        '  "bark_material_path": "/Game/Assembly/Custom/Bark_A.Bark_A",\n'
        '  "leaves_material_path": "/Game/Assembly/Custom/Leaves_A.Leaves_A",\n'
        '  "gust_attenuation": 0.0,\n'
        '  "is_ground_cover": false,\n'
        '  "wind_group_settings": {}\n'
        '}'
    )


def test_gui_persists_latest_field_edits_immediately(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    settings_path = tmp_path / "gui_settings.json"
    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", settings_path)

    try:
        app = ConversionApp(root)
        app.bark_material_var.set("/Game/Assembly/Latest/Bark_Final.Bark_Final")
        app.leaves_material_var.set("/Game/Assembly/Latest/Leaves_Final.Leaves_Final")

        assert settings_path.exists()
        assert settings_path.read_text(encoding="utf-8") == (
            '{\n'
            '  "bark_material_path": "/Game/Assembly/Latest/Bark_Final.Bark_Final",\n'
            '  "leaves_material_path": "/Game/Assembly/Latest/Leaves_Final.Leaves_Final",\n'
            '  "gust_attenuation": 0.0,\n'
            '  "is_ground_cover": false,\n'
            '  "wind_group_settings": {}\n'
            '}'
        )
    finally:
        root.destroy()


def test_gui_invalid_material_path_blocks_conversion(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    convert_mock = Mock()
    error_messages: list[str] = []

    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", tmp_path / "gui_settings.json")
    monkeypatch.setattr("xml_to_usda.gui.convert_file", convert_mock)
    monkeypatch.setattr("xml_to_usda.gui.messagebox.showinfo", lambda *args, **kwargs: None)
    monkeypatch.setattr("xml_to_usda.gui.messagebox.showerror", lambda _title, message: error_messages.append(message))

    try:
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))
        app.output_var.set("out.usda")
        app.bark_material_var.set("Not/Game/Path")

        app.run_conversion()

        convert_mock.assert_not_called()
        assert error_messages == ["Bark material path must start with /Game/."]
    finally:
        root.destroy()


def test_gui_invalid_part_mesh_path_blocks_conversion(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    convert_mock = Mock()
    error_messages: list[str] = []

    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", tmp_path / "gui_settings.json")
    monkeypatch.setattr("xml_to_usda.gui.convert_file", convert_mock)
    monkeypatch.setattr("xml_to_usda.gui.messagebox.showinfo", lambda *args, **kwargs: None)
    monkeypatch.setattr("xml_to_usda.gui.messagebox.showerror", lambda _title, message: error_messages.append(message))

    try:
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))
        app.output_var.set("out.usda")
        app._part_mesh_rows[0]["use_unreal_var"].set(True)
        app._part_mesh_rows[0]["asset_var"].set("Not/Game/Path")

        app.run_conversion()

        convert_mock.assert_not_called()
        assert error_messages == ["PartMesh asset path for Twig_01 must start with /Game/."]
    finally:
        root.destroy()


def test_gui_copy_uses_full_log_when_selection_missing() -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    try:
        app = ConversionApp(root)
        app._set_log("line one\nline two")
        app.copy_log()
        assert root.clipboard_get() == "line one\nline two"
    finally:
        root.destroy()

