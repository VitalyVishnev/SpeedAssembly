from xml_to_usda.qt_ui.operator_state import OperatorState, load_operator_state, save_operator_state
from xml_to_usda.settings_service import GuiSettingsSnapshot


class _SettingsDeps:
    def __init__(self, snapshot: GuiSettingsSnapshot) -> None:
        self.snapshot = snapshot

    def load_gui_settings(self, _path):
        return self.snapshot

    def save_gui_settings(self, _path, snapshot: GuiSettingsSnapshot) -> None:
        self.snapshot = snapshot


def test_legacy_unpaired_output_is_rederived_from_input() -> None:
    deps = _SettingsDeps(
        GuiSettingsSnapshot(last_input_path="spruce.xml", last_output_path="old_tree.usda")
    )

    state, _snapshot = load_operator_state(deps, settings_path="unused.json")

    assert state.input_path == "spruce.xml"
    assert state.output_path == ""


def test_current_output_is_saved_and_restored_for_its_input() -> None:
    deps = _SettingsDeps(GuiSettingsSnapshot())
    saved = save_operator_state(
        deps,
        OperatorState(
            input_path="spruce.xml",
            output_path="exports/custom.usda",
            orient_scattered_bones_from_instances=True,
        ),
        previous_snapshot=deps.snapshot,
        settings_path="unused.json",
    )

    restored, _snapshot = load_operator_state(deps, settings_path="unused.json")

    assert saved.last_output_input_path == "spruce.xml"
    assert restored.output_path == "exports/custom.usda"
    assert restored.orient_scattered_bones_from_instances is True
