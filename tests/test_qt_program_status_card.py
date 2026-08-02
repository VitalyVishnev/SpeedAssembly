from __future__ import annotations

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytestmark = pytest.mark.qt

from xml_to_usda.models import ConversionPhase, ConversionTelemetry
from xml_to_usda.qt_ui.dependencies import build_default_dependencies
from xml_to_usda.qt_ui.persistence import UiShellState
from xml_to_usda.qt_ui.status_card import ProgramStatusCard
from xml_to_usda.qt_ui.theme import load_theme
from xml_to_usda.qt_ui.window import MainWindow


def test_program_status_card_tracks_conversion_steps_and_progress(qtbot) -> None:
    card = ProgramStatusCard()
    qtbot.addWidget(card)
    card.show()

    card.begin_conversion("Preparing conversion job...")
    card.set_conversion_telemetry(
        ConversionTelemetry(
            phase=ConversionPhase.FBX_IMPORT,
            completed_units=1,
            total_units=2,
            message="Imported branch.fbx",
            elapsed_seconds=1.5,
        )
    )

    assert card.state_label.text() == "Converting Tree"
    assert card.progress.minimum() == 0
    assert card.progress.maximum() == 2
    assert card.progress.value() == 1
    assert "Imported branch.fbx" in card.status_label.text()
    assert card.step_labels[0].property("stepState") == "complete"
    assert card.step_labels[1].property("stepState") == "complete"
    assert card.step_labels[2].property("stepState") == "active"
    assert card.step_labels[3].property("stepState") == "pending"
    step_text = card.step_labels[2].text()
    qtbot.waitUntil(lambda: card.step_markers[2].text() != "◴", timeout=500)
    assert card.step_labels[2].text() == step_text


def test_program_status_card_success_resets_but_error_persists(qtbot) -> None:
    card = ProgramStatusCard()
    qtbot.addWidget(card)
    assert card.SUCCESS_RESET_MS == 5_000
    card.SUCCESS_RESET_MS = 10

    card.begin_activity("Proxy Mesh", "Generating Proxy Mesh...")
    assert card.progress.maximum() == 0
    card.finish("success", "Proxy Mesh ready.")
    assert card.state_label.text() == "Success"
    assert card.state_label.property("statusState") == "success"
    qtbot.waitUntil(lambda: card.state_label.text() == "Ready", timeout=500)

    card.begin_activity("Part Preview", "Generating Part Preview...")
    card.finish("error", "Part Preview failed.")
    qtbot.wait(30)
    assert card.state_label.text() == "Error"
    assert card.status_label.text() == "Part Preview failed."

    card.set_passive_message("New operator action.")
    assert card.state_label.text() == "Ready"
    assert card.status_label.text() == "New operator action."


@pytest.mark.parametrize(
    "operation",
    ("Inspecting XML", "Wind Preview", "Proxy Preview", "Fracture Preview", "Part Preview"),
)
def test_program_status_card_tracks_non_conversion_jobs(operation, qtbot) -> None:
    card = ProgramStatusCard()
    qtbot.addWidget(card)

    card.begin_activity(operation, "Working...")
    assert card.state_label.text() == operation
    assert card.progress.maximum() == 0
    assert card.steps_frame.isHidden()

    card.finish("success", f"{operation} ready.")
    assert card.state_label.text() == "Success"
    assert card.status_label.text() == f"{operation} ready."

    card.begin_activity(operation, "Working again...")
    card.finish("error", f"{operation} failed.")
    assert card.state_label.text() == "Error"
    assert card.status_label.text() == f"{operation} failed."


def test_program_status_card_cancelled_state_persists(qtbot) -> None:
    card = ProgramStatusCard()
    qtbot.addWidget(card)

    card.begin_conversion("Preparing conversion job...")
    card.finish("cancelled", "Conversion cancelled.")
    qtbot.wait(30)

    assert card.state_label.text() == "Cancelled"
    assert card.status_label.text() == "Conversion cancelled."


def test_program_status_card_updates_source_and_material_summary(qtbot) -> None:
    card = ProgramStatusCard()
    qtbot.addWidget(card)

    card.set_summary(
        mode="Static Assembly",
        materials="Single Material · M_Bark",
        materials_tooltip="/Game/Tree/M_Bark.M_Bark",
        source="Base slots: 2\nPrototypes: 3\nInstances: 43,263",
    )

    assert "Static Assembly" in card.mode_label.text()
    assert "Instances: 43,263" in card.source_label.text()
    assert card.material_label.toolTip() == "/Game/Tree/M_Bark.M_Bark"
    assert "<b>MATERIALS</b>" in card.material_label.text()


def test_program_status_card_compacts_paths_but_keeps_full_tooltip(qtbot) -> None:
    card = ProgramStatusCard()
    qtbot.addWidget(card)
    message = r"Wrote USDA to D:\3D Personal\XMLtoUSD_miscFiles\SkeletalAssemblyTest_Caps.usda"

    card.finish("success", message)

    assert card.status_label.text() == "Wrote USDA to\nSkeletalAssemblyTest_Caps.usda"
    assert card.status_label.toolTip() == message


def test_main_window_uses_one_status_card_and_no_tab_summary_rows(qtbot, tmp_path) -> None:
    window = MainWindow(
        load_theme(),
        UiShellState(width=1160, height=780, help_prompt_dismissed=True),
        dependencies=build_default_dependencies(),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)

    assert window.status_label is window.program_status_card.status_label
    assert not hasattr(window, "materials_card")
    assert not hasattr(window, "runtime_card")
    assert not hasattr(window.wind_panel, "summary_label")
    assert not hasattr(window.geometry_panel, "summary_label")
    assert not hasattr(window.materials_panel, "summary_label")
