from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from xml_to_usda.canonical_loader import (
    load_canonical_model,
    load_resolved_assembly_model,
    load_source_tree_model,
    resolve_assembly_model,
)
from xml_to_usda.models import (
    BaseMaterialOverride,
    ConversionMode,
    CpuProfile,
    MaterialPolicy,
    PrototypeResolutionMode,
    PrototypeSourceConfig,
    PrototypeSourceMode,
    PrototypeStrategy,
)
from xml_to_usda.validator import validate_authoring_model, validate_resolution, validate_source_model


SIMPLE_TREE_01 = (
    Path(__file__).resolve().parents[1]
    / "samples"
    / "speedtree"
    / "simple_tree"
    / "variants"
    / "SimpleTree_01.xml"
)


def _write_fbx_json_payload(tmp_path: Path) -> Path:
    payload = {
        "point_components": [
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
        ],
        "face_vertex_counts": [3],
        "face_vertex_indices": [0, 1, 2],
        "uv_components": [
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            1.0,
        ],
        "vertex_color_components": [
            0.0,
            0.0,
            0.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            0.0,
            0.0,
            0.0,
            1.0,
        ],
    }
    payload_path = tmp_path / "SM_Twig_01.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    return payload_path


def _prototype_by_key(model, source_key: str):
    return next(prototype for prototype in model.prototypes if prototype.source_key == source_key)


def test_load_source_tree_model_keeps_operator_intent_out_of_source_model() -> None:
    _report, source_model, diagnostics = load_source_tree_model(str(SIMPLE_TREE_01))

    assert diagnostics == ()
    assert source_model.repeated_parts == source_model.assembly_parts
    assert source_model.prototype_strategy == PrototypeStrategy.INLINE_SKELETAL_PART
    assert {prototype.source_mode for prototype in source_model.prototypes} == {PrototypeSourceMode.XML_MESH}
    assert all(prototype.geometry_payload is None for prototype in source_model.prototypes)


def test_resolve_assembly_model_applies_intent_without_mutating_source(tmp_path: Path) -> None:
    _report, source_model, source_diagnostics = load_source_tree_model(str(SIMPLE_TREE_01))
    payload_path = _write_fbx_json_payload(tmp_path)

    resolved = resolve_assembly_model(
        source_model,
        cpu_profile=CpuProfile.QUIET,
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path=str(payload_path),
            ),
        ),
        conversion_mode=ConversionMode.STATIC_ASSEMBLY,
        output_stem="StaticTree",
        source_diagnostics=source_diagnostics,
    )

    source_prototype = _prototype_by_key(source_model, "Mesh_1")
    resolved_prototype = _prototype_by_key(resolved.authoring_model, "Mesh_1")

    assert resolved.source_model is source_model
    assert resolved.conversion_mode == ConversionMode.STATIC_ASSEMBLY
    assert resolved.output_stem == "StaticTree"
    assert source_model.prototype_strategy == PrototypeStrategy.INLINE_SKELETAL_PART
    assert resolved.authoring_model.prototype_strategy == PrototypeStrategy.INLINE_STATIC_PART
    assert source_prototype.source_mode == PrototypeSourceMode.XML_MESH
    assert source_prototype.geometry_payload is None
    assert resolved_prototype.source_mode == PrototypeSourceMode.FBX_FILE
    assert resolved_prototype.fbx_source_path == str(payload_path.resolve())
    assert resolved_prototype.geometry_payload is not None


def test_material_resolution_does_not_rewrite_source_materials() -> None:
    _report, source_model, source_diagnostics = load_source_tree_model(str(SIMPLE_TREE_01))
    source_material = source_model.materials[0]

    resolved = resolve_assembly_model(
        source_model,
        material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
        use_explicit_material_contract=True,
        base_material_overrides=(
            BaseMaterialOverride(
                source_id=source_material.source_id,
                ue_asset_path="/Game/Materials/M_Base.M_Base",
            ),
        ),
        source_diagnostics=source_diagnostics,
    )

    resolved_material = next(
        material for material in resolved.authoring_model.materials if material.source_id == source_material.source_id
    )
    assert source_material.ue_asset_path is None
    assert resolved_material.ue_asset_path == "/Game/Materials/M_Base.M_Base"


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


def test_staged_validation_separates_source_resolution_and_authoring() -> None:
    _report, source_model, source_diagnostics = load_source_tree_model(str(SIMPLE_TREE_01))

    source_issues = validate_source_model(replace(source_model, source_objects=()))
    assert any(issue.code == "missing_object_hierarchy" for issue in source_issues)

    resolved = resolve_assembly_model(
        source_model,
        use_existing_part_meshes=True,
        part_mesh_asset_paths=(("Mesh_999", "/Game/TreeParts/SK_Missing.SK_Missing"),),
        source_diagnostics=source_diagnostics,
    )
    assert any(
        issue.code == "metadata_warning" and "Mesh_999" in issue.message
        for issue in resolved.resolution_diagnostics
    )
    assert not any("Mesh_999" in issue.message for issue in resolved.source_diagnostics)

    broken_authoring = replace(source_model, base_mesh=None)
    authoring_issues = validate_authoring_model(
        broken_authoring,
        conversion_mode=ConversionMode.SKELETAL_ASSEMBLY,
    )
    assert any(issue.code == "missing_base_tree_mesh" for issue in authoring_issues)


def test_resolution_validation_names_resolved_prototype_path_failures() -> None:
    _report, source_model, source_diagnostics = load_source_tree_model(str(SIMPLE_TREE_01))
    resolved = resolve_assembly_model(
        source_model,
        use_existing_part_meshes=True,
        part_mesh_asset_paths=(("Mesh_1", "/Game/TreeParts/SK_Twig01.SK_Twig01"),),
        source_diagnostics=source_diagnostics,
    )
    prototypes = list(resolved.authoring_model.prototypes)
    prototypes[0] = replace(
        prototypes[0],
        resolution_mode=PrototypeResolutionMode.EXTERNAL_ASSET,
        mesh_asset_path="TreeParts/SK_Bad.SK_Bad",
    )
    invalid_resolved = replace(
        resolved,
        authoring_model=replace(resolved.authoring_model, prototypes=tuple(prototypes)),
    )

    issues = validate_resolution(invalid_resolved)

    assert any(
        issue.code == "invalid_prototype_asset_path" and "Resolved Prototype" in issue.message
        for issue in issues
    )
