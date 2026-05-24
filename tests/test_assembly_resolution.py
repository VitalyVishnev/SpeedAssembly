from __future__ import annotations

from array import array
from pathlib import Path

import pytest

from xml_to_usda.assembly_resolution import (
    AssemblyResolutionOptions,
    ResolutionRuntime,
    resolve_assembly_model as resolve_assembly_model_from_options,
)
from xml_to_usda.canonical_loader import load_source_tree_model, resolve_assembly_model as legacy_resolve_assembly_model
from xml_to_usda.material_assignment_resolution import MaterialAssignmentOptions, resolve_material_assignments
from xml_to_usda.models import (
    BaseMaterialOverride,
    ConversionMode,
    FbxMaterialMode,
    GeometryBuffer,
    PrototypeSourceConfig,
    PrototypeSourceMode,
    PrototypeStrategy,
)


SIMPLE_TREE_01 = (
    Path(__file__).resolve().parents[1]
    / "samples"
    / "speedtree"
    / "simple_tree"
    / "variants"
    / "SimpleTree_01.xml"
)


def _geometry_payload(name: str) -> GeometryBuffer:
    return GeometryBuffer(
        name=name,
        point_components=array("f", [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0]),
        face_vertex_counts=array("i", [3]),
        face_vertex_indices=array("i", [0, 1, 2]),
        uv_components=array("f", [0.0, 0.0, 1.0, 0.0, 0.0, 1.0]),
        vertex_color_components=array("f", [0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0]),
    )


def _prototype_by_key(model, source_key: str):
    return next(prototype for prototype in model.prototypes if prototype.source_key == source_key)


def test_assembly_resolution_module_matches_compatibility_wrapper() -> None:
    _report, source_model, source_diagnostics = load_source_tree_model(str(SIMPLE_TREE_01))

    direct = resolve_assembly_model_from_options(
        source_model,
        AssemblyResolutionOptions(conversion_mode=ConversionMode.STATIC_ASSEMBLY),
        source_diagnostics=source_diagnostics,
    )
    compatibility = legacy_resolve_assembly_model(
        source_model,
        conversion_mode=ConversionMode.STATIC_ASSEMBLY,
        source_diagnostics=source_diagnostics,
    )

    assert direct.authoring_model == compatibility.authoring_model
    assert direct.diagnostics == compatibility.diagnostics


def test_prototype_resolution_uses_payload_loader_adapter_without_fbx_helper(tmp_path: Path) -> None:
    _report, source_model, source_diagnostics = load_source_tree_model(str(SIMPLE_TREE_01))
    fbx_path = tmp_path / "SM_Twig_01.fbx"
    fbx_path.write_text("stub", encoding="utf-8")
    calls = []

    def fake_payload_loader(prepared_imports, **kwargs):
        calls.append((prepared_imports, kwargs))
        return {
            prepared_import.prototype_index: _geometry_payload(prepared_import.resolved_identity.prim_name)
            for prepared_import in prepared_imports
        }

    resolved = resolve_assembly_model_from_options(
        source_model,
        AssemblyResolutionOptions(
            prototype_source_configs=(
                PrototypeSourceConfig(
                    source_key="Mesh_1",
                    source_name="Twig_01",
                    mode=PrototypeSourceMode.FBX_FILE,
                    fbx_material_mode=FbxMaterialMode.SINGLE_MATERIAL,
                    fbx_path=str(fbx_path),
                ),
            ),
        ),
        source_diagnostics=source_diagnostics,
        runtime=ResolutionRuntime(prototype_payload_loader=fake_payload_loader),
    )

    source_prototype = _prototype_by_key(source_model, "Mesh_1")
    resolved_prototype = _prototype_by_key(resolved.authoring_model, "Mesh_1")

    assert len(calls) == 1
    assert calls[0][0][0].resolved_source_name == "SM_Twig_01"
    assert source_prototype.geometry_payload is None
    assert resolved_prototype.source_mode == PrototypeSourceMode.FBX_FILE
    assert resolved_prototype.fbx_source_path == str(fbx_path.resolve())
    assert resolved_prototype.geometry_payload is not None


def test_resolution_reports_unused_prototype_source_config_as_resolution_diagnostic() -> None:
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

    assert any(
        issue.code == "metadata_warning" and "Mesh_999" in issue.message
        for issue in resolved.resolution_diagnostics
    )
    assert not any("Mesh_999" in issue.message for issue in resolved.source_diagnostics)


def test_conflicting_prototype_source_configs_fail_in_resolution(tmp_path: Path) -> None:
    _report, source_model, source_diagnostics = load_source_tree_model(str(SIMPLE_TREE_01))
    fbx_path = tmp_path / "SM_Twig_01.fbx"
    fbx_path.write_text("stub", encoding="utf-8")

    with pytest.raises(ValueError, match="Conflicting source configurations"):
        resolve_assembly_model_from_options(
            source_model,
            AssemblyResolutionOptions(
                prototype_source_configs=(
                    PrototypeSourceConfig(
                        source_key="Mesh_1",
                        mode=PrototypeSourceMode.FBX_FILE,
                        fbx_path=str(fbx_path),
                    ),
                    PrototypeSourceConfig(
                        source_key="Twig_01",
                        mode=PrototypeSourceMode.UNREAL_ASSET,
                        asset_path="/Game/TreeParts/SK_Twig01.SK_Twig01",
                    ),
                ),
            ),
            source_diagnostics=source_diagnostics,
        )


def test_material_assignment_resolution_changes_projection_only() -> None:
    _report, source_model, _source_diagnostics = load_source_tree_model(str(SIMPLE_TREE_01))
    source_material = source_model.materials[0]

    resolved_model = resolve_material_assignments(
        source_model,
        MaterialAssignmentOptions(
            use_explicit_material_contract=True,
            base_material_overrides=(
                BaseMaterialOverride(
                    source_id=source_material.source_id,
                    ue_asset_path="/Game/Materials/M_Base.M_Base",
                ),
            ),
        ),
    )

    resolved_material = next(
        material for material in resolved_model.materials if material.source_id == source_material.source_id
    )
    assert source_material.ue_asset_path is None
    assert resolved_material.ue_asset_path == "/Game/Materials/M_Base.M_Base"


def test_static_assembly_projection_does_not_change_source_strategy() -> None:
    _report, source_model, source_diagnostics = load_source_tree_model(str(SIMPLE_TREE_01))

    resolved = resolve_assembly_model_from_options(
        source_model,
        AssemblyResolutionOptions(conversion_mode=ConversionMode.STATIC_ASSEMBLY),
        source_diagnostics=source_diagnostics,
    )

    assert source_model.prototype_strategy == PrototypeStrategy.INLINE_SKELETAL_PART
    assert resolved.authoring_model.prototype_strategy == PrototypeStrategy.INLINE_STATIC_PART
