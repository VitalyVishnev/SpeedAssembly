from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from xml_to_usda.assembly_resolution import AssemblyResolutionOptions
from xml_to_usda.assembly_resolution import resolve_assembly_model as resolve_assembly_model_from_options
from xml_to_usda.authoring_validation import validate_authoring_model
from xml_to_usda.canonical_loader import load_source_tree_model
from xml_to_usda.models import ConversionMode, PrototypeSourceConfig, PrototypeSourceMode
from xml_to_usda.resolution_validation import validate_resolution
from xml_to_usda.source_validation import validate_source_model
from xml_to_usda.validator import validate_model


SIMPLE_TREE_01 = (
    Path(__file__).resolve().parents[1]
    / "samples"
    / "speedtree"
    / "simple_tree"
    / "variants"
    / "SimpleTree_01.xml"
)


def test_source_validation_module_owns_source_fact_failures() -> None:
    _report, source_model, _source_diagnostics = load_source_tree_model(str(SIMPLE_TREE_01))

    issues = validate_source_model(replace(source_model, source_objects=()))

    assert any(issue.code == "missing_object_hierarchy" for issue in issues)


def test_resolution_validation_module_owns_operator_intent_failures() -> None:
    _report, source_model, source_diagnostics = load_source_tree_model(str(SIMPLE_TREE_01))
    resolved = resolve_assembly_model_from_options(
        source_model,
        AssemblyResolutionOptions(
            prototype_source_configs=(
                PrototypeSourceConfig(
                    source_key="Mesh_999",
                    mode=PrototypeSourceMode.UNREAL_ASSET,
                    asset_path="/Game/TreeParts/SK_Missing.SK_Missing",
                ),
            ),
        ),
        source_diagnostics=source_diagnostics,
    )

    issues = validate_resolution(resolved)

    assert any(issue.code == "metadata_warning" and "Mesh_999" in issue.message for issue in issues)


def test_authoring_validation_module_owns_usda_contract_failures() -> None:
    _report, source_model, _source_diagnostics = load_source_tree_model(str(SIMPLE_TREE_01))

    issues = validate_authoring_model(
        replace(source_model, base_mesh=None),
        conversion_mode=ConversionMode.SKELETAL_ASSEMBLY,
    )

    assert any(issue.code == "missing_base_tree_mesh" for issue in issues)


def test_validator_facade_preserves_legacy_validate_model_shape() -> None:
    _report, source_model, _source_diagnostics = load_source_tree_model(str(SIMPLE_TREE_01))
    broken_model = replace(source_model, base_mesh=None, source_objects=())

    assert validate_model(broken_model) == validate_source_model(broken_model) + validate_authoring_model(broken_model)
