from __future__ import annotations

from xml_to_usda.discovery_service import PrototypeMaterialSlotRowSpec
from xml_to_usda.models import Color4, FbxMaterialMode, PrototypeSourceMode, UdimMode
from xml_to_usda.part_preview_service import PartMaterialPreviewColor, PartPreviewDisplayMode
from xml_to_usda.qt_ui.part_source_controls import (
    PartSourceMaterialEditor,
    PartSourceMaterialValue,
    format_triangle_count,
)
from xml_to_usda.qt_ui.material_controls import MaterialUdimValue


def test_part_source_material_editor_switches_source_mode_visibility(qtbot) -> None:
    editor = PartSourceMaterialEditor(value=PartSourceMaterialValue(source_key="Mesh_1", source_name="Twig"))
    qtbot.addWidget(editor)
    editor.show()

    assert editor.material_frame.isVisible()
    assert not editor.fbx_path_edit.isVisible()
    assert not editor.unreal_path_edit.isVisible()

    editor.source_mode_combo.setCurrentIndex(editor.source_mode_combo.findData(PrototypeSourceMode.FBX_FILE.value))
    assert editor.fbx_path_edit.isVisible()
    assert editor.material_frame.isVisible()

    editor.source_mode_combo.setCurrentIndex(editor.source_mode_combo.findData(PrototypeSourceMode.UNREAL_ASSET.value))
    assert editor.unreal_path_edit.isVisible()
    assert not editor.material_frame.isVisible()
    assert not editor.simplification_slider.isEnabled()


def test_format_triangle_count_uses_space_groups() -> None:
    assert format_triangle_count(1234567) == "1 234 567"


def test_part_source_material_editor_limits_display_modes_to_valid_material_modes(qtbot) -> None:
    editor = PartSourceMaterialEditor(value=PartSourceMaterialValue(source_key="Mesh_1", source_name="Twig"))
    qtbot.addWidget(editor)
    editor.show()

    assert _combo_values(editor.display_mode_combo) == [
        PartPreviewDisplayMode.DEFAULT.value,
        PartPreviewDisplayMode.VERTEX_COLORS.value,
        PartPreviewDisplayMode.MATERIAL_COLORS.value,
    ]

    editor.material_mode_combo.setCurrentIndex(editor.material_mode_combo.findData(FbxMaterialMode.SINGLE_MATERIAL.value))
    assert _combo_values(editor.display_mode_combo) == [PartPreviewDisplayMode.DEFAULT.value]

    editor.source_mode_combo.setCurrentIndex(editor.source_mode_combo.findData(PrototypeSourceMode.FBX_FILE.value))
    editor.material_mode_combo.setCurrentIndex(editor.material_mode_combo.findData(FbxMaterialMode.MATERIAL_SLOTS.value))
    assert _combo_values(editor.display_mode_combo) == [
        PartPreviewDisplayMode.DEFAULT.value,
        PartPreviewDisplayMode.MATERIAL_COLORS.value,
    ]


def test_part_source_material_editor_builds_fbx_slot_rows(qtbot) -> None:
    def inspect_slots(_fbx_path, _overrides):
        return (
            PrototypeMaterialSlotRowSpec(
                slot_name="TwigSlot",
                face_count=1234,
                ue_asset_path="/Game/M_Twig.M_Twig",
                udim_mode=UdimMode.SHIFT_PRIMARY_UV,
                udim_id=1002,
            ),
        )

    editor = PartSourceMaterialEditor(
        value=PartSourceMaterialValue(
            source_key="Mesh_1",
            source_name="Twig",
            source_mode=PrototypeSourceMode.FBX_FILE,
            fbx_path="twig.fbx",
            fbx_material_mode=FbxMaterialMode.MATERIAL_SLOTS,
        ),
        inspect_fbx_slots=inspect_slots,
    )
    qtbot.addWidget(editor)
    editor.show()

    assert len(editor._slot_rows) == 1
    value = editor.value()
    assert value.fbx_material_slot_overrides[0].slot_name == "TwigSlot"
    assert value.fbx_material_slot_overrides[0].ue_asset_path == "/Game/M_Twig.M_Twig"
    assert value.fbx_material_slot_overrides[0].udim_mode == UdimMode.SHIFT_PRIMARY_UV
    assert value.fbx_material_slot_overrides[0].udim_id == 1002


def test_part_source_material_editor_material_color_dots_follow_active_rows(qtbot) -> None:
    editor = PartSourceMaterialEditor(
        value=PartSourceMaterialValue(
            source_key="Mesh_1",
            source_name="Twig",
            fbx_material_mode=FbxMaterialMode.VERTEX_COLOR_SPLIT,
            black_material=MaterialUdimValue("/Game/M_Black.M_Black"),
            white_material=MaterialUdimValue("/Game/M_White.M_White"),
            display_mode=PartPreviewDisplayMode.MATERIAL_COLORS,
        )
    )
    qtbot.addWidget(editor)
    editor.show()

    editor.set_material_colors(
        (
            PartMaterialPreviewColor(1, "Black", Color4(1.0, 0.0, 0.0, 1.0)),
            PartMaterialPreviewColor(2, "White", Color4(0.0, 0.5, 1.0, 1.0)),
        )
    )

    assert editor.black_row.color_dot.isVisible()
    assert "rgb(255, 0, 0)" in editor.black_row.color_dot.styleSheet()
    assert editor.white_row.color_dot.isVisible()
    assert "rgb(0, 128, 255)" in editor.white_row.color_dot.styleSheet()


def test_part_source_material_editor_live_triangle_prediction_uses_space_groups(qtbot) -> None:
    editor = PartSourceMaterialEditor(value=PartSourceMaterialValue(source_key="Mesh_1", source_name="Twig"))
    qtbot.addWidget(editor)
    preview_requests: list[object] = []
    editor.previewAffectingChanged.connect(lambda: preview_requests.append(object()))

    editor.set_triangle_prediction_base((123456, 10))
    editor.simplification_slider.setValue(50)

    assert "61 733" in editor.triangle_count_label.text()
    assert "123 466" in editor.triangle_count_label.text()
    assert preview_requests == []


def _combo_values(combo) -> list[str]:
    return [combo.itemData(index) for index in range(combo.count())]
