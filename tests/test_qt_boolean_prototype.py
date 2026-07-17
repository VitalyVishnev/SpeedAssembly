from __future__ import annotations

from pathlib import Path

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

pytestmark = pytest.mark.qt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from xml_to_usda.boolean_fracture_prototype import (
    SYNTHETIC_CYLINDER_CUT_TOKEN,
    BooleanCutPrototypeSettings,
    BooleanMultiPrototypeSettings,
    build_boolean_cut_prototype,
    build_synthetic_boolean_cylinder_model,
    prepare_boolean_multi_prototype,
)
from xml_to_usda.canonical_loader import load_source_tree_model
from xml_to_usda.qt_ui import boolean_prototype as prototype_ui


class _TestViewport(QWidget):
    def set_show_bones(self, _enabled: bool) -> None:
        pass

    def set_bone_pick_requires_control(self, _enabled: bool) -> None:
        pass

    def set_shortcut_hints(self, _hints: tuple[str, ...]) -> None:
        pass

    def set_scene(self, scene, *, frame_camera: bool) -> None:
        self.scene = scene
        self.frame_camera = frame_camera

    def set_exploded_view_strength(self, value: float) -> None:
        self.exploded_view_strength = value


def test_synthetic_prototype_controls_regenerate_the_cut(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(prototype_ui, "MatcapViewport", _TestViewport)
    model = build_synthetic_boolean_cylinder_model()
    settings = BooleanCutPrototypeSettings(
        SYNTHETIC_CYLINDER_CUT_TOKEN,
        intensity=0.35,
        chip_scale=0.65,
        remesh_density=8,
    )
    result = build_boolean_cut_prototype(model, settings)
    window = prototype_ui.BooleanPrototypeWindow(model, result, settings, source_label="Synthetic")
    qtbot.addWidget(window)

    window._cut_position.setValue(0.625)
    window._intensity.setValue(0.0)
    window._chip_scale.setValue(1.2)
    window._remesh_density.setValue(10)
    window._max_bend_angle.setValue(45.0)
    qtbot.mouseClick(window._regenerate_button, Qt.MouseButton.LeftButton)

    assert window._settings == BooleanCutPrototypeSettings(
        "root->bone_001@0.625",
        intensity=0.0,
        chip_scale=1.2,
        remesh_density=10,
        max_bend_angle_degrees=45.0,
    )
    assert window._result.diagnostics.cut_origin.y == pytest.approx(0.5)
    assert {round(point.y, 8) for point in window._result.cutter_surface.points} == {0.5}
    assert window._cut_token_label.text() == "root->bone_001@0.625"
    assert window._stage_table.rowCount() == len(window._result.diagnostics.stages)
    assert window._timing_table.rowCount() == len(window._result.stage_timings)


def test_multi_prototype_window_lists_real_tree_pieces(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(prototype_ui, "MatcapViewport", _TestViewport)
    source = Path(__file__).resolve().parents[1] / "samples/speedtree/simple_tree/variants/SimpleTree_01.xml"
    model = load_source_tree_model(source)[1]
    settings = BooleanMultiPrototypeSettings(auto_branch_count=2, intensity=0.0, remesh_density=4)
    session = prepare_boolean_multi_prototype(model, settings)
    result = session.build(settings)
    window = prototype_ui.BooleanMultiPrototypeWindow(
        model,
        result,
        settings,
        source_label="SimpleTree",
        session=session,
    )
    qtbot.addWidget(window)

    window._exploded.setValue(0.75)

    assert len(window._piece_checks) == len(result.pieces) == 3
    assert window._cut_table.rowCount() == len(result.cuts) == 2
    assert window.viewport.exploded_view_strength == 0.75
    assert window.viewport.scene.scene_id == "boolean-multi-prototype"
