from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from xml_to_usda.models import ConversionRequest, ConversionResult, OutputMode, ValidationIssue
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
        assert "Single-file mode" in app.status_var.get()
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
    assert 'token outputs:unreal:surface.connect = </Tree/Materials/Material_0_0/Material_0_0_unreal_shader.outputs:out>' in result.usda_document.text
    assert 'token outputs:unreal:surface.connect = </Tree/Materials/Material_2_2/Material_2_2_unreal_shader.outputs:out>' in result.usda_document.text
    assert 'uniform asset info:unreal:sourceAsset = @/Game/TestMaterials/M_Bark_Test@' in result.usda_document.text
    assert 'uniform asset info:unreal:sourceAsset = @/Game/TestMaterials/M_Leaves_Test@' in result.usda_document.text


def test_gui_run_conversion_passes_material_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    calls: list[tuple[str, str, str | None, str | None]] = []

    def fake_convert_file(input_path, output_path, output_mode=OutputMode.SELF_CONTAINED, bark_material_path=None, leaves_material_path=None):
        calls.append((input_path, output_path, bark_material_path, leaves_material_path))
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
            )
        ]
        assert "Material overrides:" in app.log_widget.get("1.0", "end-1c")
    finally:
        root.destroy()


def test_gui_invalid_material_path_blocks_conversion(monkeypatch: pytest.MonkeyPatch) -> None:
    _, root = _build_tk_root_or_skip()
    from xml_to_usda.gui import ConversionApp

    convert_mock = Mock()
    error_messages: list[str] = []

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
