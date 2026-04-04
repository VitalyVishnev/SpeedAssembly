from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from xml_to_usda.models import (
    BaseMaterialOverride,
    CleanupPolicy,
    ConversionJobResult,
    ConversionPhase,
    ConversionRequest,
    ConversionResult,
    ConversionTelemetry,
    CpuProfile,
    DynamicWindData,
    DynamicWindJointAssignment,
    DynamicWindSimulationGroup,
    FbxMaterialMode,
    FbxMaterialSlotOverride,
    FbxMaterialSlotSpec,
    MaterialPolicy,
    OutputMode,
    PrototypeSourceConfig,
    PrototypeSourceMode,
    ValidationIssue,
    WindJsonResult,
)
from xml_to_usda.cli import build_parser
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


def test_prototype_identities_use_display_names_and_suffix_collisions() -> None:
    identities = build_prototype_identities(("Mesh_1", "Mesh_2", "Mesh_3"), ("Aspen Twig", "Aspen Twig", "Aspen_Twig"))

    assert [identity.prim_name for identity in identities] == ["Aspen_Twig", "Aspen_Twig_2", "Aspen_Twig_3"]


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
        assert hasattr(app, "material_policy_var")
        assert hasattr(app, "bark_material_var")
        assert hasattr(app, "leaves_material_var")
        assert hasattr(app, "single_material_var")
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

    assert "Cleanup policy: ephemeral" in rendered
    assert "Material policy: source_material_roles" in rendered
    assert "Input: input.xml" in rendered
    assert "[warning] demo: demo warning" in rendered
    assert "Status: failed" in rendered


def test_cli_parser_accepts_material_policy_flags() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "convert",
            "input.xml",
            "output.usda",
            "--material-policy",
            "single_material",
            "--single-material-path",
            "/Game/Assembly/Fern/M_Fern.M_Fern",
        ]
    )

    assert args.material_policy == "single_material"
    assert args.single_material_path == "/Game/Assembly/Fern/M_Fern.M_Fern"
    assert args.bark_material_path is None
    assert args.leaves_material_path is None


def test_cli_parser_accepts_legacy_material_policy_alias() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "convert",
            "input.xml",
            "output.usda",
            "--material-policy",
            "legacy_role_ids",
        ]
    )

    assert args.material_policy == "legacy_role_ids"


def test_cli_parser_accepts_part_source_config_and_cpu_profile() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "convert",
            "input.xml",
            "output.usda",
            "--part-source-config",
            "part_sources.json",
            "--cpu-profile",
            "quiet",
            "--preserve-temp-files",
        ]
    )

    assert args.part_source_config == "part_sources.json"
    assert args.cpu_profile == "quiet"
    assert args.preserve_temp_files is True


def test_cli_parser_defaults_cpu_profile_to_balanced() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "convert",
            "input.xml",
            "output.usda",
        ]
    )

    assert args.cpu_profile == CpuProfile.BALANCED.value


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


def test_convert_file_uses_output_path_stem_for_base_mesh_name(tmp_path: Path) -> None:
    output_path = tmp_path / "SkeletalAssemblyTest_03_14mil_namedGroups.usda"
    result = convert_file(str(SIMPLE_TREE_01), str(output_path))

    assert result.output_path == str(output_path)
    assert result.usda_document is not None
    assert 'def Mesh "SkeletalAssemblyTest_03_14mil_namedGroups"' in result.usda_document.text
    assert 'def Skeleton "SkeletalAssemblyTest_03_14mil_namedGroups_Skeleton"' in result.usda_document.text
    assert 'uniform token[] jointNames = ["SkeletalAssemblyTest_03_14mil_namedGroups"' in result.usda_document.text
    assert 'uniform token[] joints = ["SkeletalAssemblyTest_03_14mil_namedGroups"' in result.usda_document.text
    assert (
        'custom rel unreal:naniteAssembly:skeleton = '
        '</Tree/SkeletalAssemblyTest_03_14mil_namedGroups_Geo/SkeletalAssemblyTest_03_14mil_namedGroups_Skeleton>'
        in result.usda_document.text
    )
    assert 'def SkelRoot "SkeletalAssemblyTest_03_14mil_namedGroups_Geo"' in result.usda_document.text
    assert 'def SkelAnimation "animation"' in result.usda_document.text
    assert 'uniform token[] joints = ["SkeletalAssemblyTest_03_14mil_namedGroups"' in result.usda_document.text
    assert (
        'append rel skel:animationSource = '
        '</Tree/SkeletalAssemblyTest_03_14mil_namedGroups_Geo/animation>'
        in result.usda_document.text
    )


def test_gui_run_conversion_passes_material_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    calls: list[tuple[str, str, MaterialPolicy, str | None, str | None, str | None, bool, tuple[tuple[str, str], ...]]] = []

    def fake_convert_file(
        input_path,
        output_path,
        output_mode=OutputMode.SELF_CONTAINED,
        material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
        bark_material_path=None,
        leaves_material_path=None,
        single_material_path=None,
        cleanup_policy=None,
        use_existing_part_meshes=False,
        part_mesh_asset_paths=(),
        runtime_paths=None,
    ):
        calls.append(
            (
                input_path,
                output_path,
                material_policy,
                bark_material_path,
                leaves_material_path,
                single_material_path,
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
                MaterialPolicy.SOURCE_MATERIAL_ROLES,
                "/Game/TestMaterials/M_Bark_Test",
                "/Game/TestMaterials/M_Leaves_Test",
                None,
                False,
                (),
            )
        ]
        assert "Material policy: source_material_roles" in app.log_widget.get("1.0", "end-1c")
        assert "Material overrides:" in app.log_widget.get("1.0", "end-1c")
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_gui_run_conversion_passes_single_material_policy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    calls: list[tuple[str, str, MaterialPolicy, str | None, str | None, str | None]] = []

    def fake_convert_file(
        input_path,
        output_path,
        output_mode=OutputMode.SELF_CONTAINED,
        material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
        bark_material_path=None,
        leaves_material_path=None,
        single_material_path=None,
        cleanup_policy=None,
        use_existing_part_meshes=False,
        part_mesh_asset_paths=(),
        runtime_paths=None,
    ):
        calls.append(
            (
                input_path,
                output_path,
                material_policy,
                bark_material_path,
                leaves_material_path,
                single_material_path,
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
        monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
        monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", tmp_path / "gui_settings.json")
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))
        app.output_var.set("out.usda")
        app.material_policy_var.set(MaterialPolicy.SINGLE_MATERIAL.value)
        app.bark_material_var.set("Not/Game/Path")
        app.single_material_var.set("/Game/Assembly/Fern/M_Fern.M_Fern")

        app.run_conversion()

        assert calls == [
            (
                str(SIMPLE_TREE_01),
                "out.usda",
                MaterialPolicy.SINGLE_MATERIAL,
                None,
                None,
                "/Game/Assembly/Fern/M_Fern.M_Fern",
            )
        ]
        assert "Material policy: single_material" in app.log_widget.get("1.0", "end-1c")
        assert "Single material path: /Game/Assembly/Fern/M_Fern.M_Fern" in app.log_widget.get("1.0", "end-1c")
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_gui_run_conversion_passes_part_mesh_xml_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    calls: list[tuple[str, str, MaterialPolicy, str | None, str | None, str | None, bool, tuple[tuple[str, str], ...]]] = []

    def fake_convert_file(
        input_path,
        output_path,
        output_mode=OutputMode.SELF_CONTAINED,
        material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
        bark_material_path=None,
        leaves_material_path=None,
        single_material_path=None,
        cleanup_policy=None,
        use_existing_part_meshes=False,
        part_mesh_asset_paths=(),
        runtime_paths=None,
    ):
        calls.append(
            (
                input_path,
                output_path,
                material_policy,
                bark_material_path,
                leaves_material_path,
                single_material_path,
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
                MaterialPolicy.SOURCE_MATERIAL_ROLES,
                None,
                None,
                None,
                True,
                (("Twig_01", "/Game/TreeParts/SK_Twig01.SK_Twig01"),),
            )
        ]
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_gui_refresh_wind_groups_builds_slider_rows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", tmp_path / "gui_settings.json")

    try:
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))

        app.refresh_wind_groups()

        assert len(app._wind_group_rows) == 3
        assert app._wind_group_rows[0]["group_index"] == 0
        assert app._wind_group_rows[1]["group_index"] == 1
        assert app._wind_group_rows[0]["dual_influence_var"].get()
        assert app._wind_group_rows[0]["single_frame"].winfo_manager() == ""
        assert app._wind_group_rows[0]["dual_frame"].winfo_manager() == "grid"
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
        app._wind_group_rows[0]["dual_influence_var"].set(False)
        assert app._wind_group_rows[0]["single_frame"].winfo_manager() == "grid"
        assert app._wind_group_rows[0]["dual_frame"].winfo_manager() == ""
        app._wind_group_rows[0]["influence_var"].set(0.7)
        app._wind_group_rows[0]["shift_var"].set(0.2)
        app._wind_group_rows[1]["dual_influence_var"].set(True)
        app._wind_group_rows[1]["min_influence_var"].set(0.25)
        app._wind_group_rows[1]["max_influence_var"].set(0.55)
        app._wind_group_rows[1]["shift_var"].set(0.05)
        app.gust_attenuation_var.set(0.6)
        app.is_ground_cover_var.set(True)

        app.run_generate_wind_json()

        assert calls
        assert calls[0][0] == str(SIMPLE_TREE_01)
        assert calls[0][1] == "out_DynamicWind.json"
        assert calls[0][2][0].use_dual_influence is False
        assert calls[0][2][0].influence == pytest.approx(0.7)
        assert calls[0][2][0].shift_top == pytest.approx(0.2)
        assert calls[0][2][1].use_dual_influence is True
        assert calls[0][2][1].min_influence == pytest.approx(0.25)
        assert calls[0][2][1].max_influence == pytest.approx(0.55)
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
        try:
            root.destroy()
        except Exception:
            pass


def test_gui_refresh_base_material_rows_autoloads_xml_materials(
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

        assert len(app._base_material_rows) == 1
        assert app.base_material_summary_var.get() == "Found 1 base XML material slot(s)."
        assert [(row["source_id"], row["source_name"]) for row in app._base_material_rows] == [
            (1, "Bark_Mat"),
        ]
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


def test_gui_persists_fbx_source_mode_and_cpu_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    settings_path = tmp_path / "gui_settings.json"
    fake_fbx_path = tmp_path / "prototype_branch.fbx"
    fake_fbx_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", settings_path)

    try:
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))
        app.cpu_profile_var.set(CpuProfile.QUIET.value)
        app.preserve_temp_files_var.set(True)
        row = app._part_mesh_rows[0]
        row["source_mode_var"].set(PrototypeSourceMode.FBX_FILE.value)
        row["fbx_var"].set(str(fake_fbx_path))
        row["fbx_material_mode_var"].set(FbxMaterialMode.SINGLE_MATERIAL.value)
        app._handle_window_close()

        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        key = str(SIMPLE_TREE_01.resolve())
        assert payload["cpu_profile"] == "quiet"
        assert payload["preserve_temp_files"] is True
        assert "wind_group_settings_by_input_path" in payload
        assert payload["part_mesh_settings_by_input_path"][key][0] == {
            "source_name": "Twig_01",
            "source_key": "Mesh_1",
            "source_mode": "fbx_file",
            "fbx_path": str(fake_fbx_path),
            "fbx_material_mode": "single_material",
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

        assert app.cpu_profile_var.get() == CpuProfile.QUIET.value
        assert app.preserve_temp_files_var.get() is True
        assert restored_row["source_mode_var"].get() == PrototypeSourceMode.FBX_FILE.value
        assert restored_row["fbx_var"].get() == str(fake_fbx_path)
        assert restored_row["fbx_material_mode_var"].get() == FbxMaterialMode.SINGLE_MATERIAL.value
        assert str(restored_row["fbx_entry"].cget("state")) == "normal"
        assert str(restored_row["fbx_material_mode_combo"].cget("state")) == "readonly"
        assert str(restored_row["asset_entry"].cget("state")) == "disabled"
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_gui_run_conversion_passes_explicit_base_material_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    calls: list[dict[str, object]] = []

    def fake_convert_file(input_path, output_path, output_mode=OutputMode.SELF_CONTAINED, **kwargs):
        calls.append(
            {
                "input_path": input_path,
                "output_path": output_path,
                "output_mode": output_mode,
                **kwargs,
            }
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
        monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
        monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", tmp_path / "gui_settings.json")
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))
        app.output_var.set("out.usda")
        app._base_material_rows[0]["material_path_var"].set("/Game/TestMaterials/M_Bark_Test")

        app.run_conversion()

        assert len(calls) == 1
        call = calls[0]
        assert call["use_explicit_material_contract"] is True
        assert call["base_material_overrides"] == (
            BaseMaterialOverride(
                source_id=1,
                source_name="Bark_Mat",
                ue_asset_path="/Game/TestMaterials/M_Bark_Test",
            ),
        )
        assert "Material contract: explicit_base_and_part_materials" in app.log_widget.get("1.0", "end-1c")
        assert "Base XML material overrides:" in app.log_widget.get("1.0", "end-1c")
    finally:
        root.destroy()


def test_gui_run_conversion_passes_explicit_xml_part_material_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    calls: list[dict[str, object]] = []

    def fake_convert_file(input_path, output_path, output_mode=OutputMode.SELF_CONTAINED, **kwargs):
        calls.append(
            {
                "input_path": input_path,
                "output_path": output_path,
                "output_mode": output_mode,
                **kwargs,
            }
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
        monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
        monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", tmp_path / "gui_settings.json")
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))
        app.output_var.set("out.usda")
        row = app._part_mesh_rows[0]
        row["fbx_material_mode_var"].set(FbxMaterialMode.SINGLE_MATERIAL.value)
        row["single_material_var"].set("/Game/TreeParts/M_Twig.M_Twig")

        app.run_conversion()

        assert len(calls) == 1
        call = calls[0]
        assert call["use_explicit_material_contract"] is True
        assert call["prototype_source_configs"] == (
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.XML_MESH,
                fbx_material_mode=FbxMaterialMode.SINGLE_MATERIAL,
                asset_path=None,
                fbx_path=None,
                single_material_path="/Game/TreeParts/M_Twig.M_Twig",
                black_material_path=None,
                white_material_path=None,
            ),
        )
        assert "Prototype source overrides:" in app.log_widget.get("1.0", "end-1c")
        assert "xml_mesh[single_material]" in app.log_widget.get("1.0", "end-1c")
    finally:
        root.destroy()


def test_gui_collects_fbx_material_slot_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    fake_fbx_path = tmp_path / "spruce_branch.fbx"
    fake_fbx_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", tmp_path / "gui_settings.json")
    monkeypatch.setattr(
        "xml_to_usda.gui.inspect_fbx_material_slots",
        lambda *_args, **_kwargs: (
            FbxMaterialSlotSpec(source_id=1, name="Bark", face_count=12),
            FbxMaterialSlotSpec(source_id=2, name="Needles", face_count=24),
        ),
    )

    try:
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))
        row = app._part_mesh_rows[0]
        row["source_mode_var"].set(PrototypeSourceMode.FBX_FILE.value)
        row["fbx_var"].set(str(fake_fbx_path))
        row["fbx_material_mode_var"].set(FbxMaterialMode.MATERIAL_SLOTS.value)
        row["material_slot_rows"][0]["path_var"].set("/Game/TreeParts/M_Bark.M_Bark")

        configs = app._collect_part_source_configs()

        assert configs == (
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_material_mode=FbxMaterialMode.MATERIAL_SLOTS,
                fbx_path=str(fake_fbx_path.resolve()),
                single_material_path=None,
                black_material_path=None,
                white_material_path=None,
                fbx_material_slot_overrides=(
                    FbxMaterialSlotOverride(
                        slot_name="Bark",
                        ue_asset_path="/Game/TreeParts/M_Bark.M_Bark",
                    ),
                    FbxMaterialSlotOverride(
                        slot_name="Needles",
                        ue_asset_path=None,
                    ),
                ),
            ),
        )
    finally:
        root.destroy()


def test_gui_persists_fbx_material_slot_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    settings_path = tmp_path / "gui_settings.json"
    fake_fbx_path = tmp_path / "spruce_branch.fbx"
    fake_fbx_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr(
        "xml_to_usda.gui.inspect_fbx_material_slots",
        lambda *_args, **_kwargs: (
            FbxMaterialSlotSpec(source_id=1, name="Bark", face_count=12),
            FbxMaterialSlotSpec(source_id=2, name="Needles", face_count=24),
        ),
    )

    try:
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))
        row = app._part_mesh_rows[0]
        row["source_mode_var"].set(PrototypeSourceMode.FBX_FILE.value)
        row["fbx_var"].set(str(fake_fbx_path))
        row["fbx_material_mode_var"].set(FbxMaterialMode.MATERIAL_SLOTS.value)
        row["material_slot_rows"][0]["path_var"].set("/Game/TreeParts/M_Bark.M_Bark")
        app._handle_window_close()

        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        key = str(SIMPLE_TREE_01.resolve())
        assert payload["part_mesh_settings_by_input_path"][key][0]["fbx_material_mode"] == "material_slots"
        assert payload["part_mesh_settings_by_input_path"][key][0]["fbx_material_slot_overrides"] == [
            {"slot_name": "Bark", "ue_asset_path": "/Game/TreeParts/M_Bark.M_Bark"},
            {"slot_name": "Needles", "ue_asset_path": ""},
        ]
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_gui_persists_wind_group_settings_per_xml(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    settings_path = tmp_path / "gui_settings.json"
    other_xml = Path(__file__).parent / "data" / "leafrefs_on_branch_levels.xml"
    dynamic_wind = DynamicWindData(
        joint_assignments=(DynamicWindJointAssignment(joint_name="root", simulation_group_index=0, branch_order=0),),
        simulation_groups=(DynamicWindSimulationGroup(group_index=0, branch_order=0, is_trunk_group=True),),
    )

    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr(ConversionApp, "RUNTIME_LOG_PATH", tmp_path / "gui_runtime.log")
    monkeypatch.setattr("xml_to_usda.gui.inspect_wind_data", lambda _input_path, is_ground_cover=False: dynamic_wind)

    try:
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))
        app.refresh_wind_groups()
        app._wind_group_rows[0]["influence_var"].set(0.35)
        app._save_settings()

        app.input_var.set(str(other_xml))
        app.refresh_wind_groups()
        app._wind_group_rows[0]["influence_var"].set(0.75)
        app._save_settings()
        app._handle_window_close()

        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        first_key = str(SIMPLE_TREE_01.resolve())
        second_key = str(other_xml.resolve())
        assert payload["wind_group_settings_by_input_path"][first_key]["0"]["influence"] == 0.35
        assert payload["wind_group_settings_by_input_path"][second_key]["0"]["influence"] == 0.75
    finally:
        try:
            root.destroy()
        except Exception:
            pass

    _, root = _build_tk_root_or_skip()
    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr(ConversionApp, "RUNTIME_LOG_PATH", tmp_path / "gui_runtime.log")
    monkeypatch.setattr("xml_to_usda.gui.inspect_wind_data", lambda _input_path, is_ground_cover=False: dynamic_wind)

    try:
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))
        app.refresh_wind_groups()
        assert app._wind_group_rows[0]["influence_var"].get() == pytest.approx(0.35)

        app.input_var.set(str(other_xml))
        app.refresh_wind_groups()
        assert app._wind_group_rows[0]["influence_var"].get() == pytest.approx(0.75)
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
    other_xml = Path(__file__).parent / "data" / "leafrefs_on_branch_levels.xml"

    try:
        app = ConversionApp(root)
        app.input_var.set(str(other_xml))
        app._handle_source_path_change()

        assert len(app._part_mesh_rows) >= 1
        assert all(row["asset_var"].get() == "" for row in app._part_mesh_rows)
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
        '{"material_policy": "legacy_role_ids", "bark_material_path": "/Game/TestMaterials/M_Bark_Test", "leaves_material_path": "/Game/TestMaterials/M_Leaves_Test", "single_material_path": "", "gust_attenuation": 0.25, "is_ground_cover": true, "wind_group_settings": {"0": {"influence": 1.4, "shift_top": 0.1}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", settings_path)

    try:
        app = ConversionApp(root)
        assert app.material_policy_var.get() == MaterialPolicy.SOURCE_MATERIAL_ROLES.value
        assert app.bark_material_var.get() == "/Game/TestMaterials/M_Bark_Test"
        assert app.leaves_material_var.get() == "/Game/TestMaterials/M_Leaves_Test"
        assert app.single_material_var.get() == ""
        assert app.gust_attenuation_var.get() == pytest.approx(0.25)
        assert app.is_ground_cover_var.get() is True
    finally:
        root.destroy()


def test_gui_refresh_wind_groups_uses_background_worker_for_large_xml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    dynamic_wind = DynamicWindData(
        joint_assignments=(DynamicWindJointAssignment(joint_name="root", simulation_group_index=0, branch_order=0),),
        simulation_groups=(DynamicWindSimulationGroup(group_index=0, branch_order=0, is_trunk_group=True),),
    )

    monkeypatch.setattr("xml_to_usda.gui.inspect_wind_data", lambda _input_path, is_ground_cover=False: dynamic_wind)
    monkeypatch.setattr("xml_to_usda.gui.messagebox.showerror", lambda *args, **kwargs: None)
    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", tmp_path / "gui_settings.json")
    monkeypatch.setattr(ConversionApp, "ASYNC_WIND_REFRESH_THRESHOLD_BYTES", 0)

    try:
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))

        app.refresh_wind_groups()

        for _ in range(50):
            root.update()
            if app._wind_group_rows:
                break
            time.sleep(0.01)

        assert len(app._wind_group_rows) == 1
        assert app._wind_group_rows[0]["group_index"] == 0
        assert str(app.refresh_wind_button.cget("state")) == "normal"
    finally:
        root.destroy()


def test_gui_refresh_wind_groups_retries_internal_worker_error_on_main_thread(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    dynamic_wind = DynamicWindData(
        joint_assignments=(DynamicWindJointAssignment(joint_name="root", simulation_group_index=0, branch_order=0),),
        simulation_groups=(DynamicWindSimulationGroup(group_index=0, branch_order=0, is_trunk_group=True),),
    )
    call_count = {"count": 0}
    error_messages: list[str] = []

    def flaky_inspect_wind_data(_input_path, is_ground_cover=False):
        call_count["count"] += 1
        if call_count["count"] == 1:
            raise SystemError(r"D:\w1\s\Objects\setobject.c:2295: bad argument to internal function")
        return dynamic_wind

    monkeypatch.setattr("xml_to_usda.gui.inspect_wind_data", flaky_inspect_wind_data)
    monkeypatch.setattr("xml_to_usda.gui.messagebox.showerror", lambda _title, message: error_messages.append(message))
    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", tmp_path / "gui_settings.json")
    monkeypatch.setattr(ConversionApp, "ASYNC_WIND_REFRESH_THRESHOLD_BYTES", 0)

    try:
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))

        app.refresh_wind_groups()

        for _ in range(50):
            root.update()
            if app._wind_group_rows:
                break
            time.sleep(0.01)

        assert call_count["count"] == 2
        assert len(app._wind_group_rows) == 1
        assert "after fallback retry" in app.status_var.get()
        assert "Background wind worker failed once" in app.log_widget.get("1.0", "end-1c")
        assert error_messages == []
    finally:
        root.destroy()


def test_gui_browse_input_auto_refreshes_wind_groups_and_shows_instance_counts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    settings_path = tmp_path / "gui_settings.json"
    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr("xml_to_usda.gui.filedialog.askopenfilename", lambda **_kwargs: str(SIMPLE_TREE_01))
    dynamic_wind = DynamicWindData(
        joint_assignments=(DynamicWindJointAssignment(joint_name="root", simulation_group_index=0, branch_order=0),),
        simulation_groups=(DynamicWindSimulationGroup(group_index=0, branch_order=0, is_trunk_group=True),),
    )

    monkeypatch.setattr("xml_to_usda.gui.inspect_wind_data", lambda *_args, **_kwargs: dynamic_wind)

    try:
        app = ConversionApp(root)

        app.browse_input()

        assert app.input_var.get() == str(SIMPLE_TREE_01)
        assert len(app._wind_group_rows) == 1
        assert app._part_mesh_rows[0]["instance_count"] == 13
        assert app._part_mesh_rows[1]["instance_count"] == 26
        assert "39 repeated branch instances" in app.part_mesh_summary_var.get()
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
        material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
        bark_material_path=None,
        leaves_material_path=None,
        single_material_path=None,
        cleanup_policy=None,
        use_existing_part_meshes=False,
        part_mesh_asset_paths=(),
        runtime_paths=None,
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
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        assert payload["material_policy"] == "source_material_roles"
        assert payload["bark_material_path"] == "/Game/TestMaterials/M_Bark_Test"
        assert payload["leaves_material_path"] == "/Game/TestMaterials/M_Leaves_Test"
        assert payload["single_material_path"] == ""
        assert payload["gust_attenuation"] == 0.0
        assert payload["is_ground_cover"] is False
        assert isinstance(payload["wind_group_settings"], dict)
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
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert payload["material_policy"] == "source_material_roles"
    assert payload["bark_material_path"] == "/Game/Assembly/Custom/Bark_A.Bark_A"
    assert payload["leaves_material_path"] == "/Game/Assembly/Custom/Leaves_A.Leaves_A"
    assert payload["single_material_path"] == ""
    assert payload["gust_attenuation"] == 0.0
    assert payload["is_ground_cover"] is False
    assert isinstance(payload["wind_group_settings"], dict)


def test_gui_persists_single_material_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    settings_path = tmp_path / "gui_settings.json"
    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", settings_path)

    try:
        app = ConversionApp(root)
        app.material_policy_var.set(MaterialPolicy.SINGLE_MATERIAL.value)
        app.single_material_var.set("/Game/Assembly/Fern/M_Fern.M_Fern")
        app._handle_window_close()

        assert settings_path.exists()
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        assert payload["material_policy"] == "single_material"
        assert payload["bark_material_path"] == ""
        assert payload["leaves_material_path"] == ""
        assert payload["single_material_path"] == "/Game/Assembly/Fern/M_Fern.M_Fern"
        assert payload["gust_attenuation"] == 0.0
        assert payload["is_ground_cover"] is False
        assert isinstance(payload["wind_group_settings"], dict)
    finally:
        try:
            root.destroy()
        except Exception:
            pass


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
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        assert payload["material_policy"] == "source_material_roles"
        assert payload["bark_material_path"] == "/Game/Assembly/Latest/Bark_Final.Bark_Final"
        assert payload["leaves_material_path"] == "/Game/Assembly/Latest/Leaves_Final.Leaves_Final"
        assert payload["single_material_path"] == ""
        assert payload["gust_attenuation"] == 0.0
        assert payload["is_ground_cover"] is False
        assert isinstance(payload["wind_group_settings"], dict)
    finally:
        root.destroy()


def test_gui_invalid_material_path_blocks_conversion(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    convert_mock = Mock()

    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", tmp_path / "gui_settings.json")
    monkeypatch.setattr(ConversionApp, "RUNTIME_LOG_PATH", tmp_path / "gui_runtime.log")
    monkeypatch.setattr("xml_to_usda.gui.convert_file", convert_mock)
    monkeypatch.setattr("xml_to_usda.gui.messagebox.showinfo", lambda *args, **kwargs: None)

    try:
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))
        app.output_var.set("out.usda")
        app.bark_material_var.set("Not/Game/Path")

        app.run_conversion()

        convert_mock.assert_not_called()
        assert app.status_var.get() == "Invalid material path"
        assert "Bark material path must start with /Game/." in app.log_widget.get("1.0", "end-1c")
    finally:
        root.destroy()


def test_gui_invalid_single_material_path_blocks_conversion(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    convert_mock = Mock()

    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", tmp_path / "gui_settings.json")
    monkeypatch.setattr(ConversionApp, "RUNTIME_LOG_PATH", tmp_path / "gui_runtime.log")
    monkeypatch.setattr("xml_to_usda.gui.convert_file", convert_mock)
    monkeypatch.setattr("xml_to_usda.gui.messagebox.showinfo", lambda *args, **kwargs: None)

    try:
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))
        app.output_var.set("out.usda")
        app.material_policy_var.set(MaterialPolicy.SINGLE_MATERIAL.value)
        app.single_material_var.set("Not/Game/Path")

        app.run_conversion()

        convert_mock.assert_not_called()
        assert app.status_var.get() == "Invalid material path"
        assert "Single material path must start with /Game/." in app.log_widget.get("1.0", "end-1c")
    finally:
        root.destroy()


def test_gui_invalid_part_mesh_path_blocks_conversion(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    convert_mock = Mock()

    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", tmp_path / "gui_settings.json")
    monkeypatch.setattr(ConversionApp, "RUNTIME_LOG_PATH", tmp_path / "gui_runtime.log")
    monkeypatch.setattr("xml_to_usda.gui.convert_file", convert_mock)
    monkeypatch.setattr("xml_to_usda.gui.messagebox.showinfo", lambda *args, **kwargs: None)

    try:
        app = ConversionApp(root)
        app.input_var.set(str(SIMPLE_TREE_01))
        app.output_var.set("out.usda")
        app._part_mesh_rows[0]["use_unreal_var"].set(True)
        app._part_mesh_rows[0]["asset_var"].set("Not/Game/Path")

        app.run_conversion()

        convert_mock.assert_not_called()
        assert app.status_var.get() == "Invalid PartMesh mapping"
        assert "PartMesh asset path for Twig_01 must start with /Game/." in app.log_widget.get("1.0", "end-1c")
    finally:
        root.destroy()


def test_gui_logs_worker_traceback_when_background_conversion_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", tmp_path / "gui_settings.json")
    monkeypatch.setattr(ConversionApp, "RUNTIME_LOG_PATH", tmp_path / "gui_runtime.log")

    try:
        app = ConversionApp(root)
        app._conversion_error_traceback = "Traceback line 1\nTraceback line 2"
        app._conversion_context = {
            "cpu_profile": CpuProfile.BALANCED,
            "cleanup_policy": CleanupPolicy.EPHEMERAL,
            "material_policy": MaterialPolicy.SOURCE_MATERIAL_ROLES,
            "bark_material_path": None,
            "leaves_material_path": None,
            "single_material_path": None,
            "prototype_source_configs": (),
            "use_existing_part_meshes": False,
            "part_mesh_asset_paths": (),
        }

        app._handle_conversion_job_result(
            ConversionJobResult(error_message="'list_iterator' object is not callable"),
            app._conversion_context,
        )

        log_text = app.log_widget.get("1.0", "end-1c")
        assert "'list_iterator' object is not callable" in log_text
        assert "Traceback line 1" in log_text
        assert app.status_var.get() == "Conversion failed."
        assert "Traceback line 2" in (tmp_path / "gui_runtime.log").read_text(encoding="utf-8")
    finally:
        root.destroy()


def test_gui_logs_tk_callback_exceptions_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", tmp_path / "gui_settings.json")
    monkeypatch.setattr(ConversionApp, "RUNTIME_LOG_PATH", tmp_path / "gui_runtime.log")

    try:
        app = ConversionApp(root)
        try:
            raise RuntimeError("ui blew up")
        except RuntimeError as exc:
            app._handle_tk_callback_exception(RuntimeError, exc, exc.__traceback__)

        assert app.status_var.get() == "UI callback failed."
        log_text = app.log_widget.get("1.0", "end-1c")
        assert "RuntimeError: ui blew up" in log_text
        assert "UI callback failed" in (tmp_path / "gui_runtime.log").read_text(encoding="utf-8")
    finally:
        root.destroy()


def test_gui_shows_startup_build_banner_when_build_info_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, root = _build_tk_root_or_skip()
    import xml_to_usda.gui as gui_module
    from xml_to_usda.gui import ConversionApp

    build_root = tmp_path / "dist"
    build_root.mkdir(parents=True, exist_ok=True)
    fake_exe = build_root / "XMLtoUSDAConverter.exe"
    fake_exe.write_text("", encoding="utf-8")
    (build_root / "build_info.json").write_text(
        json.dumps(
            {
                "built_at": "2026-04-04 12:34:56 +05:00",
                "build_mode": "launcher",
                "exe_path": str(fake_exe),
                "python_exe": str(tmp_path / ".venv310" / "Scripts" / "python.exe"),
                "git_branch": "codex/test",
                "git_head": "abc1234",
                "git_dirty": True,
                "change_summary": "M src/xml_to_usda/gui.py; M scripts/build_gui_exe.ps1",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", tmp_path / "gui_settings.json")
    monkeypatch.setattr(ConversionApp, "RUNTIME_LOG_PATH", tmp_path / "gui_runtime.log")
    monkeypatch.setattr(gui_module.sys, "argv", [str(fake_exe)])
    monkeypatch.setattr(gui_module.sys, "executable", str(fake_exe))

    try:
        app = ConversionApp(root)
        log_text = app.log_widget.get("1.0", "end-1c")
        assert "Build info:" in log_text
        assert "Runtime info:" in log_text
        assert "built_at: 2026-04-04 12:34:56 +05:00" in log_text
        assert "mode: launcher" in log_text
        assert "git_head: abc1234" in log_text
        assert "changes: M src/xml_to_usda/gui.py; M scripts/build_gui_exe.ps1" in log_text
        assert "Build banner" in (tmp_path / "gui_runtime.log").read_text(encoding="utf-8")
    finally:
        root.destroy()


def test_gui_reports_runtime_context_for_unexpected_worker_crash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    monkeypatch.setattr(ConversionApp, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(ConversionApp, "SETTINGS_PATH", tmp_path / "gui_settings.json")
    monkeypatch.setattr(ConversionApp, "RUNTIME_LOG_PATH", tmp_path / "gui_runtime.log")

    try:
        app = ConversionApp(root)
        app._conversion_context = {
            "cpu_profile": CpuProfile.BALANCED,
            "cleanup_policy": CleanupPolicy.EPHEMERAL,
            "material_policy": MaterialPolicy.SOURCE_MATERIAL_ROLES,
            "bark_material_path": None,
            "leaves_material_path": None,
            "single_material_path": None,
            "prototype_source_configs": (),
            "use_existing_part_meshes": False,
            "part_mesh_asset_paths": (),
        }
        app._last_conversion_telemetry = ConversionTelemetry(
            phase=ConversionPhase.FBX_IMPORT,
            completed_units=1,
            total_units=2,
            message="Imported FBX Branch_A.",
            elapsed_seconds=123.4,
        )
        app.status_var.set("Imported FBX Branch_A (1/2) 123.4s")
        app._handle_conversion_job_result(
            ConversionJobResult(
                error_message=(
                    "Conversion worker process crashed unexpectedly (exit code 3221225477)\n"
                    "Last telemetry: Imported FBX Branch_A. (1/2) 123.4s\n"
                    "Runtime context:\n"
                    "  frozen=False\n"
                    "  executable=python.exe\n"
                    "  argv0=test\n"
                    "  jobs_root=C:/tmp/jobs"
                )
            ),
            app._conversion_context,
        )

        log_text = app.log_widget.get("1.0", "end-1c")
        assert "Conversion worker process crashed unexpectedly" in log_text
        assert "Last telemetry:" in log_text
        assert "Runtime context:" in log_text
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

