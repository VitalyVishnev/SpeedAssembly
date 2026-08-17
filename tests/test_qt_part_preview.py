from __future__ import annotations

from array import array

from xml_to_usda.models import Color4, CompactMeshSection, CpuProfile, GeometryBuffer, PrototypeSourceMode
from xml_to_usda.part_preview_service import (
    PartMaterialPreviewColor,
    PartPreviewDisplayMode,
    PartPrototypePreviewResult,
)
from xml_to_usda.qt_ui.part_preview import PartPrototypePreviewDialog
from xml_to_usda.qt_ui.part_source_controls import PartSourceMaterialValue


def test_part_preview_display_switch_reuses_loaded_geometry(qtbot) -> None:
    requests = []
    dialog = PartPrototypePreviewDialog(
        input_path="tree.xml",
        value=PartSourceMaterialValue(source_key="Mesh_1", source_name="Twig"),
        cpu_profile=CpuProfile.BALANCED,
        fbx_cache_max_bytes=1,
        fbx_cache_max_age_seconds=1,
        on_preview_requested=lambda request, settings: requests.append((request, settings)),
    )
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: len(requests) == 1)
    dialog.editor.display_mode_combo.setCurrentIndex(
        dialog.editor.display_mode_combo.findData(PartPreviewDisplayMode.MATERIAL_COLORS.value)
    )

    mesh = GeometryBuffer(
        name="Twig",
        point_components=array("f", [0, 0, 0, 1, 0, 0, 0, 1, 0]),
        face_vertex_counts=array("i", [3]),
        face_vertex_indices=array("i", [0, 1, 2]),
        vertex_color_components=array("f", [0.25, 0.5, 0.75, 1.0] * 3),
        sections=(CompactMeshSection(material_id=10, face_indices=array("i", [0])),),
    )
    dialog.set_preview(
        PartPrototypePreviewResult(
            source_key="Mesh_1",
            source_name="Twig",
            source_mode=PrototypeSourceMode.XML_MESH,
            mesh=mesh,
            material_colors=(PartMaterialPreviewColor(10, "Leaf", Color4(0.0, 1.0, 0.0, 1.0)),),
        )
    )

    assert len(requests) == 1
    assert dialog.viewport.matcap_tint_strength == 1.0
    assert tuple(dialog.viewport._mesh.vertex_color_components[:4]) == (0.0, 1.0, 0.0, 1.0)

    dialog.editor.display_mode_combo.setCurrentIndex(
        dialog.editor.display_mode_combo.findData(PartPreviewDisplayMode.VERTEX_COLORS.value)
    )

    assert len(requests) == 1
    assert dialog.viewport._mesh is mesh
