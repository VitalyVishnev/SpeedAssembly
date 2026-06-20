from __future__ import annotations

from pathlib import Path

from xml_to_usda.discovery_service import (
    discover_base_material_rows,
    discover_part_prototype_rows,
    inspect_fbx_material_slot_rows,
)
from xml_to_usda.models import CpuProfile, FbxMaterialMode, FbxMaterialSlotSpec, PrototypeSourceMode
from xml_to_usda.settings_service import (
    BaseMaterialSettingRecord,
    FbxMaterialSlotSettingRecord,
    PartSourceSettingRecord,
)


SIMPLE_TREE_01 = Path(__file__).resolve().parents[1] / "samples" / "speedtree" / "simple_tree" / "variants" / "SimpleTree_01.xml"


def test_discover_base_material_rows_merges_persisted_paths() -> None:
    discovery = discover_base_material_rows(
        str(SIMPLE_TREE_01),
        persisted_records=(
            BaseMaterialSettingRecord(
                source_id=1,
                source_name="Bark_Mat",
                ue_asset_path="/Game/TestMaterials/M_Bark_Test",
            ),
        ),
    )

    assert discovery.summary == "Found 2 base XML material slot(s)."
    assert discovery.rows[0].source_name == "Bark_Mat"
    assert discovery.rows[0].ue_asset_path == "/Game/TestMaterials/M_Bark_Test"
    assert discovery.rows[1].source_id == 0
    assert discovery.rows[1].source_name == "Default_Mat"
    assert discovery.rows[1].ue_asset_path == ""


def test_discover_part_prototype_rows_restores_persisted_modes() -> None:
    discovery = discover_part_prototype_rows(
        str(SIMPLE_TREE_01),
        persisted_records=(
            PartSourceSettingRecord(
                source_name="Twig_01",
                source_key="Mesh_1",
                source_mode=PrototypeSourceMode.FBX_FILE,
                fbx_path=r"D:\XMLtoUSD_miscFiles\spruce_branch.fbx",
                fbx_material_mode=FbxMaterialMode.MATERIAL_SLOTS,
                simplification_percent=25,
                fbx_material_slot_overrides=(
                    FbxMaterialSlotSettingRecord(
                        slot_name="Bark",
                        ue_asset_path="/Game/TreeParts/M_Bark.M_Bark",
                    ),
                ),
            ),
        ),
    )

    assert discovery.summary == "Found 39 repeated branch instances across 2 prototype(s)."
    assert discovery.rows[0].source_name == "Twig_01"
    assert discovery.rows[0].source_mode == PrototypeSourceMode.FBX_FILE
    assert discovery.rows[0].fbx_material_mode == FbxMaterialMode.MATERIAL_SLOTS
    assert discovery.rows[0].simplification_percent == 25
    assert discovery.rows[0].fbx_material_slot_overrides == (
        FbxMaterialSlotSettingRecord(
            slot_name="Bark",
            ue_asset_path="/Game/TreeParts/M_Bark.M_Bark",
        ),
    )


def test_inspect_fbx_material_slot_rows_merges_persisted_overrides(monkeypatch, tmp_path: Path) -> None:
    fake_fbx_path = tmp_path / "spruce_branch.fbx"
    fake_fbx_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "xml_to_usda.discovery_service._inspect_fbx_material_slots_cached",
        lambda *_args, **_kwargs: (
            FbxMaterialSlotSpec(source_id=1, name="Bark", face_count=12),
            FbxMaterialSlotSpec(source_id=2, name="Needles", face_count=24),
        ),
    )

    rows = inspect_fbx_material_slot_rows(
        str(fake_fbx_path),
        cpu_profile=CpuProfile.BALANCED,
        persisted_records=(
            FbxMaterialSlotSettingRecord(
                slot_name="Bark",
                ue_asset_path="/Game/TreeParts/M_Bark.M_Bark",
            ),
        ),
    )

    assert rows == (
        rows[0].__class__(slot_name="Bark", face_count=12, ue_asset_path="/Game/TreeParts/M_Bark.M_Bark"),
        rows[1].__class__(slot_name="Needles", face_count=24, ue_asset_path=""),
    )
