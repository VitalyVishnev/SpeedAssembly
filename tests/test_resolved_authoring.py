from __future__ import annotations

from pathlib import Path

from xml_to_usda.canonical_loader import load_resolved_assembly_model
from xml_to_usda.models import AuthoredAssemblyPartInstance
from xml_to_usda.usda_authoring import build_authoring_context, build_resolved_authoring_context


SIMPLE_TREE_01 = (
    Path(__file__).resolve().parents[1]
    / "samples"
    / "speedtree"
    / "simple_tree"
    / "variants"
    / "SimpleTree_01.xml"
)


def test_resolved_authoring_context_projects_authored_assembly_parts() -> None:
    _report, resolved = load_resolved_assembly_model(str(SIMPLE_TREE_01), output_stem="UnifiedBaseline")

    context = build_resolved_authoring_context(resolved)

    assert context.assembly_parts
    assert all(isinstance(part, AuthoredAssemblyPartInstance) for part in context.assembly_parts)
    assert len(context.assembly_parts) == len(resolved.authoring_model.repeated_parts)
    assert all(not hasattr(part, "source_object_id") for part in context.assembly_parts)
