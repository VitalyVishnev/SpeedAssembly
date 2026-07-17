from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import xml_to_usda.fracture_export_service as fracture_export_service
import xml_to_usda.fracture_geometry as fracture_geometry
import xml_to_usda.fracture_preview_service as fracture_preview_service
from xml_to_usda.canonical_loader import load_source_tree_model
from xml_to_usda.fracture_collision import FractureCollisionMode, FractureCollisionSettings
from xml_to_usda.fracture_export_service import FractureExportRequest, export_fracture_usda_from_export_request
from xml_to_usda.fracture_preview_service import (
    FracturePreviewSettings,
    FracturePreviewSourceRequest,
    generate_fracture_preview_from_source_request,
)
from xml_to_usda.fracture_service import FractureSettings, plan_fracture
from xml_to_usda.models import ConversionRequest


SIMPLE_TREE_01 = (
    Path(__file__).resolve().parents[1]
    / "samples"
    / "speedtree"
    / "simple_tree"
    / "variants"
    / "SimpleTree_01.xml"
)
SIMPLE_TREE_THREE_TRUNKS = (
    Path(__file__).resolve().parents[1]
    / "samples"
    / "speedtree"
    / "simple_tree"
    / "variants"
    / "SimpleTree_02_three_trunks.xml"
)
BIG_SPRUCE = (
    Path(__file__).resolve().parents[1]
    / "samples"
    / "speedtree"
    / "BigSpruce"
    / "SkeletalAssemblyTest_Spruce_Big_low.xml"
)


def test_fracture_preview_and_export_on_real_simple_tree_sample(tmp_path: Path) -> None:
    request = ConversionRequest(
        input_paths=(str(SIMPLE_TREE_01),),
        output_path=str(tmp_path / "SimpleTree_01.usda"),
    )

    preview = generate_fracture_preview_from_source_request(
        FracturePreviewSourceRequest.from_conversion_request(request),
        FracturePreviewSettings(
            fracture=FractureSettings(target_piece_count=5),
            max_base_faces_per_piece=200,
            max_prototype_faces=100,
        ),
    )
    export = export_fracture_usda_from_export_request(
        FractureExportRequest.from_conversion_request(request),
        FractureSettings(target_piece_count=5),
    )

    assert preview.plan.actual_piece_count == 6
    assert len(preview.instances) > 0
    assert export.plan.actual_piece_count == 6
    assert tuple(Path(output.output_path).name for output in export.outputs) == (
        "SimpleTree_01_fracture_00.usda",
        "SimpleTree_01_fracture_01.usda",
        "SimpleTree_01_fracture_02.usda",
        "SimpleTree_01_fracture_03.usda",
        "SimpleTree_01_fracture_04.usda",
        "SimpleTree_01_fracture_05.usda",
    )
    assert all(Path(output.output_path).exists() for output in export.outputs)


def test_fracture_preview_capsule_collision_on_real_simple_tree_sample(tmp_path: Path) -> None:
    request = ConversionRequest(
        input_paths=(str(SIMPLE_TREE_01),),
        output_path=str(tmp_path / "SimpleTree_01.usda"),
    )

    preview = generate_fracture_preview_from_source_request(
        FracturePreviewSourceRequest.from_conversion_request(request),
        FracturePreviewSettings(
            fracture=FractureSettings(target_piece_count=11),
            collision=FractureCollisionSettings(enabled=True, mode=FractureCollisionMode.CAPSULE),
            final_polycount=1_000_000,
            base_mesh_priority=0.3,
            max_prototype_faces=2_000,
        ),
    )

    assert preview.plan.actual_piece_count == 12
    assert len(preview.collision_meshes) > 0


def test_real_simple_tree_auto_fracture_does_not_cut_trunk_chain() -> None:
    preview = generate_fracture_preview_from_source_request(
        FracturePreviewSourceRequest(input_path=str(SIMPLE_TREE_01)),
        FracturePreviewSettings(
            fracture=FractureSettings(target_piece_count=11),
            max_base_faces_per_piece=10_000,
            max_prototype_faces=10_000,
        ),
        include_viewport_scene=False,
    )

    assert preview.plan.actual_piece_count == 12
    assert {cut.reason for cut in preview.plan.selected_cut_sites} == {"auto_branch_length"}
    assert not {
        "bone_001",
        "bone_002",
        "bone_003",
        "bone_004",
        "bone_005",
    }.intersection(cut.joint_token for cut in preview.plan.selected_cut_sites)


def test_three_trunk_sample_can_separate_stems_without_branch_count() -> None:
    preview = generate_fracture_preview_from_source_request(
        FracturePreviewSourceRequest(input_path=str(SIMPLE_TREE_THREE_TRUNKS)),
        FracturePreviewSettings(
            fracture=FractureSettings(target_piece_count=0, separate_stems=True),
            max_base_faces_per_piece=10_000,
            max_prototype_faces=10_000,
        ),
        include_viewport_scene=False,
    )

    assert preview.plan.actual_piece_count == 3
    assert tuple(cut.reason for cut in preview.plan.selected_cut_sites) == (
        "auto_stem_length",
        "auto_stem_length",
    )


def test_three_trunk_sample_generates_one_stump_cut_per_stem() -> None:
    preview = generate_fracture_preview_from_source_request(
        FracturePreviewSourceRequest(input_path=str(SIMPLE_TREE_THREE_TRUNKS)),
        FracturePreviewSettings(
            fracture=FractureSettings(
                target_piece_count=0,
                separate_stems=True,
                force_stump_piece=True,
            ),
            max_base_faces_per_piece=10_000,
            max_prototype_faces=10_000,
        ),
        include_viewport_scene=False,
    )

    stump_cuts = tuple(cut for cut in preview.plan.selected_cut_sites if cut.reason == "stump_piece")
    assert len(stump_cuts) == 3
    assert preview.plan.actual_piece_count == 6
    assert all(piece.base_mesh.face_count > 0 for piece in preview.pieces)


def test_fracture_preview_defaults_to_no_small_branch_removal_on_real_three_trunk_sample() -> None:
    preview = generate_fracture_preview_from_source_request(
        FracturePreviewSourceRequest(input_path=str(SIMPLE_TREE_THREE_TRUNKS)),
        FracturePreviewSettings(
            fracture=FractureSettings(target_piece_count=0, separate_stems=True),
            max_base_faces_per_piece=10_000,
            max_prototype_faces=10_000,
        ),
        include_viewport_scene=False,
    )
    pruned = generate_fracture_preview_from_source_request(
        FracturePreviewSourceRequest(input_path=str(SIMPLE_TREE_THREE_TRUNKS)),
        FracturePreviewSettings(
            fracture=FractureSettings(target_piece_count=0, separate_stems=True),
            branch_prune_aggression=0.9689,
            max_base_faces_per_piece=10_000,
            max_prototype_faces=10_000,
        ),
        include_viewport_scene=False,
    )

    default_faces = sum(piece.base_mesh.face_count for piece in preview.pieces)
    source_faces = sum(len(piece.piece.base_face_indices) for piece in preview.pieces)
    pruned_faces = sum(piece.base_mesh.face_count for piece in pruned.pieces)
    # Exact clipping may add boundary polygons; the default must not drop source geometry.
    assert default_faces >= source_faces
    assert pruned_faces < default_faces


def test_three_trunk_sample_branch_height_bias_changes_length_ordering() -> None:
    lower = generate_fracture_preview_from_source_request(
        FracturePreviewSourceRequest(input_path=str(SIMPLE_TREE_THREE_TRUNKS)),
        FracturePreviewSettings(
            fracture=FractureSettings(target_piece_count=5, branch_height_bias=-1.0),
            max_base_faces_per_piece=10_000,
            max_prototype_faces=10_000,
        ),
        include_viewport_scene=False,
    )
    upper = generate_fracture_preview_from_source_request(
        FracturePreviewSourceRequest(input_path=str(SIMPLE_TREE_THREE_TRUNKS)),
        FracturePreviewSettings(
            fracture=FractureSettings(target_piece_count=5, branch_height_bias=1.0),
            max_base_faces_per_piece=10_000,
            max_prototype_faces=10_000,
        ),
        include_viewport_scene=False,
    )

    lower_tokens = tuple(cut.joint_token for cut in lower.plan.selected_cut_sites)
    upper_tokens = tuple(cut.joint_token for cut in upper.plan.selected_cut_sites)
    assert lower_tokens != upper_tokens
    assert "bone_229" in lower_tokens
    assert "bone_224" in upper_tokens
