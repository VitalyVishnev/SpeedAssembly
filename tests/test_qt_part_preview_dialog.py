from __future__ import annotations

from array import array
from types import SimpleNamespace

import pytest

from xml_to_usda.models import CpuProfile, GeometryBuffer
from xml_to_usda.part_preview_service import PartPreviewDisplayMode
from xml_to_usda.qt_ui.part_preview import PartPrototypePreviewDialog
from xml_to_usda.qt_ui.part_source_controls import PartSourceMaterialValue


def _mesh() -> GeometryBuffer:
    return GeometryBuffer(
        name="Twig",
        point_components=array("f", [0, 0, 0, 1, 0, 0, 0, 1, 0]),
        face_vertex_counts=array("i", [3]),
        face_vertex_indices=array("i", [0, 1, 2]),
        vertex_color_components=array("f", [1, 0, 0, 1, 0, 1, 0, 1, 0, 0, 1, 1]),
    )


@pytest.mark.parametrize(
    ("display_mode", "expected_strength", "expected_alpha"),
    (
        (PartPreviewDisplayMode.DEFAULT, 0.0, 0.0),
        (PartPreviewDisplayMode.VERTEX_COLORS, 1.0, 0.8),
        (PartPreviewDisplayMode.MATERIAL_COLORS, 1.0, 0.7),
    ),
)
def test_part_preview_display_modes_set_viewport_tint(qtbot, display_mode, expected_strength, expected_alpha) -> None:
    dialog = PartPrototypePreviewDialog(
        input_path="tree.xml",
        value=PartSourceMaterialValue(source_key="Mesh_1", source_name="Twig", display_mode=display_mode),
        cpu_profile=CpuProfile.BALANCED,
        fbx_cache_max_bytes=1,
        fbx_cache_max_age_seconds=1,
    )
    qtbot.addWidget(dialog)

    dialog.set_preview(
        SimpleNamespace(
            mesh=_mesh(),
            material_colors=(),
            source_section_triangle_counts=(1,),
        )
    )

    assert dialog.viewport.matcap_tint_strength == pytest.approx(expected_strength)
    assert dialog.viewport._mesh_tint_alpha == pytest.approx(expected_alpha)
