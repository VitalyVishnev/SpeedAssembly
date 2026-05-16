from __future__ import annotations

from pathlib import Path

from xml_to_usda.canonical_loader import load_resolved_assembly_model
from xml_to_usda.usda_authoring import author_usda_text, build_authoring_context, build_resolved_authoring_context
from xml_to_usda.usda_writer import render_resolved_usda, render_usda, write_resolved_usda_document, write_usda_document


SIMPLE_TREE_01 = (
    Path(__file__).resolve().parents[1]
    / "samples"
    / "speedtree"
    / "simple_tree"
    / "variants"
    / "SimpleTree_01.xml"
)


def _normalize_usda_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))


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
