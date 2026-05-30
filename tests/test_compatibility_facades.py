from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from xml_to_usda.authoring_validation import validate_authoring_model
from xml_to_usda.canonical_loader import load_canonical_model, load_resolved_assembly_model, load_source_tree_model
from xml_to_usda.models import ConversionMode
from xml_to_usda.usda_authoring import build_authoring_context, build_resolved_authoring_context, author_usda_text
from xml_to_usda.normalizer import normalize_to_canonical
from xml_to_usda.source_validation import validate_source_model
from xml_to_usda.validator import validate_model
from xml_to_usda.xml_reader import analyze_xml, read_source_xml
from xml_to_usda.usda_writer import render_resolved_usda, render_usda, write_resolved_usda_document, write_usda_document


SIMPLE_TREE_01 = Path(__file__).resolve().parents[1] / "samples" / "speedtree" / "simple_tree" / "variants" / "SimpleTree_01.xml"


def test_canonical_model_matches_when_source_node_index_is_prebuilt() -> None:
    # Compat only: keep prebuilt source-node path aligned with normal canonical loading.
    document = read_source_xml(SIMPLE_TREE_01)
    analysis = analyze_xml(document)
    model_from_analysis = normalize_to_canonical(document, analysis.report, source_nodes=analysis.source_nodes)
    model_without_shared_index = normalize_to_canonical(document, analysis.report)

    assert model_without_shared_index == model_from_analysis


def test_resolved_authoring_context_matches_legacy_context() -> None:
    _report, resolved = load_resolved_assembly_model(str(SIMPLE_TREE_01), output_stem="UnifiedBaseline")

    resolved_context = build_resolved_authoring_context(resolved)
    legacy_context = build_authoring_context(
        resolved.authoring_model,
        resolved.diagnostics,
        base_mesh_name="UnifiedBaseline",
        conversion_mode=resolved.conversion_mode,
    )

    assert author_usda_text(resolved_context) == author_usda_text(legacy_context)


def test_load_canonical_model_remains_compatibility_projection() -> None:
    old_report, old_model, old_diagnostics = load_canonical_model(
        str(SIMPLE_TREE_01),
        conversion_mode=ConversionMode.STATIC_ASSEMBLY,
    )
    new_report, resolved = load_resolved_assembly_model(
        str(SIMPLE_TREE_01),
        conversion_mode=ConversionMode.STATIC_ASSEMBLY,
    )

    assert old_report == new_report
    assert old_model == resolved.authoring_model
    assert old_diagnostics == resolved.diagnostics


def test_validator_facade_preserves_legacy_validate_model_shape() -> None:
    _report, source_model, _source_diagnostics = load_source_tree_model(str(SIMPLE_TREE_01))
    broken_model = replace(source_model, base_mesh=None, source_objects=())

    assert validate_model(broken_model) == validate_source_model(broken_model) + validate_authoring_model(broken_model)


def _normalize_usda_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))


def test_render_resolved_usda_matches_legacy_render() -> None:
    _report, resolved = load_resolved_assembly_model(str(SIMPLE_TREE_01), output_stem="UnifiedBaseline")

    resolved_document = render_resolved_usda(resolved)
    legacy_document = render_usda(
        resolved.authoring_model,
        resolved.diagnostics,
        base_mesh_name="UnifiedBaseline",
        conversion_mode=resolved.conversion_mode,
    )

    assert resolved_document.text == legacy_document.text
    assert resolved_document.diagnostics == legacy_document.diagnostics


def test_write_resolved_usda_document_matches_legacy_write(tmp_path: Path) -> None:
    output_path = tmp_path / "resolved_authoring.usda"
    legacy_output_path = tmp_path / "legacy_authoring.usda"
    _report, resolved = load_resolved_assembly_model(str(SIMPLE_TREE_01), output_stem=output_path.stem)

    resolved_document = write_resolved_usda_document(resolved, output_path=output_path)
    legacy_document = write_usda_document(
        resolved.authoring_model,
        resolved.diagnostics,
        output_path=legacy_output_path,
        base_mesh_name=output_path.stem,
        conversion_mode=resolved.conversion_mode,
    )

    assert resolved_document.text is not None
    assert legacy_document.text is not None
    assert _normalize_usda_text(resolved_document.text) == _normalize_usda_text(legacy_document.text)
    assert _normalize_usda_text(output_path.read_text(encoding="utf-8")) == _normalize_usda_text(
        legacy_output_path.read_text(encoding="utf-8")
    )


def test_pipeline_public_facade_exports_stable_symbols() -> None:
    from xml_to_usda import pipeline

    assert callable(pipeline.inspect_source)
    assert callable(pipeline.discover_part_prototypes)
    assert callable(pipeline.discover_source_materials)
    assert callable(pipeline.load_canonical_model)
    assert callable(pipeline.load_source_tree_model)
    assert callable(pipeline.resolve_assembly_model)
    assert callable(pipeline.load_resolved_assembly_model)
    assert callable(pipeline.convert_file)
    assert callable(pipeline.convert_request)
    assert callable(pipeline.inspect_wind_data)
    assert callable(pipeline.generate_wind_json)
    assert callable(pipeline._apply_material_policy)
    assert pipeline.REPO_ROOT.name == "XMLtoUSDAconverter"


def test_usda_writer_public_facade_exports_stable_symbols() -> None:
    from xml_to_usda import usda_writer

    assert callable(usda_writer.render_usda)
    assert callable(usda_writer.render_resolved_usda)
    assert callable(usda_writer.write_usda_document)
    assert callable(usda_writer.write_resolved_usda_document)


def test_retired_tk_gui_facade_keeps_only_non_ui_helpers() -> None:
    from xml_to_usda import gui

    assert callable(gui.main)
    assert callable(gui.format_conversion_results)
    assert callable(gui.format_wind_group_summary)
    assert callable(gui.format_wind_json_result)
    assert not hasattr(gui, "ConversionApp")
    with pytest.raises(RuntimeError, match="Tk GUI is retired"):
        gui.main()
