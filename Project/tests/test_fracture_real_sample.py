from __future__ import annotations

from pathlib import Path

from xml_to_usda.fracture_export_service import FractureExportRequest, export_fracture_usda_from_export_request
from xml_to_usda.fracture_preview_service import (
    FracturePreviewSettings,
    FracturePreviewSourceRequest,
    generate_fracture_preview_from_source_request,
)
from xml_to_usda.fracture_service import FractureSettings
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
