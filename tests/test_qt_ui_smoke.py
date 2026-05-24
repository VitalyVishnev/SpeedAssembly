from __future__ import annotations

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtWidgets import QAbstractSpinBox

from xml_to_usda.qt_ui.dependencies import build_default_dependencies
from xml_to_usda.qt_ui.entry import main
from xml_to_usda.models import CpuProfile, MaterialPolicy
from xml_to_usda.qt_ui.panels import SliderSpinEditor
from xml_to_usda.qt_ui.persistence import UiShellState
from xml_to_usda.qt_ui.window import MainWindow
from xml_to_usda.qt_ui.theme import load_theme
from xml_to_usda.settings_service import GuiSettingsSnapshot


def test_qt_shell_window_creation(qtbot, tmp_path) -> None:
    theme = load_theme()
    window = MainWindow(
        theme,
        UiShellState(),
        dependencies=build_default_dependencies(),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    assert window.windowTitle() == "XML to USDA Converter"
    assert window.minimumWidth() >= 1100


def test_qt_shell_applies_native_corner_preference_on_show(monkeypatch, qtbot, tmp_path) -> None:
    theme = load_theme()
    calls: list[bool] = []

    def _fake_apply(self) -> None:
        calls.append(True)

    monkeypatch.setattr(MainWindow, "_apply_native_corner_preference", _fake_apply)
    window = MainWindow(
        theme,
        UiShellState(),
        dependencies=build_default_dependencies(),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(50)

    assert calls


def test_qt_entry_main_launches_and_exits_cleanly(monkeypatch) -> None:
    timer_calls: list[int] = []
    icon_calls: list[object] = []

    class _FakeApp:
        def __init__(self, _args):
            pass

        @staticmethod
        def instance():
            return None

        def setApplicationName(self, _name: str) -> None:
            pass

        def setWindowIcon(self, icon: object) -> None:
            icon_calls.append(icon)

        def quit(self) -> None:
            pass

        def exec(self) -> int:
            return 0

    class _FakeWindow:
        def __init__(
            self,
            _theme,
            _state,
            *,
            dependencies,
            state_path=None,
            operator_settings_path=None,
            base_theme=None,
            theme_overrides=None,
            theme_overrides_path=None,
        ):
            self.shown = False

        def show(self) -> None:
            self.shown = True

    class _FakeIcon:
        def __init__(self, path: str):
            self.path = path

    identity_calls: list[bool] = []

    monkeypatch.setattr("PySide6.QtWidgets.QApplication", _FakeApp)
    monkeypatch.setattr("PySide6.QtGui.QIcon", _FakeIcon)
    monkeypatch.setattr("PySide6.QtCore.QTimer.singleShot", lambda delay, callback: timer_calls.append(delay))
    monkeypatch.setattr("xml_to_usda.qt_ui.window.MainWindow", _FakeWindow)
    monkeypatch.setattr(
        "xml_to_usda.qt_ui.entry.configure_windows_taskbar_identity",
        lambda: identity_calls.append(True),
    )

    exit_code = main(["--smoke-exit-ms", "1"])

    assert exit_code == 0
    assert timer_calls == [1]
    assert len(icon_calls) == 1
    assert isinstance(icon_calls[0], _FakeIcon)
    assert icon_calls[0].path.endswith("Icon.ico")
    assert identity_calls == [True]


def test_qt_entry_application_icon_is_bundled() -> None:
    from xml_to_usda.qt_ui.entry import application_icon_path

    icon_path = application_icon_path()

    assert icon_path.endswith("Icon.ico")
    with open(icon_path, "rb") as icon_file:
        assert icon_file.read(6)[:4] == b"\x00\x00\x01\x00"


def test_qt_shell_enables_actions_when_paths_present(qtbot, tmp_path) -> None:
    theme = load_theme()
    window = MainWindow(
        theme,
        UiShellState(),
        dependencies=build_default_dependencies(),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    assert not window.convert_button.isEnabled()
    assert window.convert_button.text() == "Convert to USDA"
    assert not window.wind_panel.refresh_button.isEnabled()
    assert not window.generate_button.isEnabled()

    window.source_input.setText(str(tmp_path / "tree.xml"))
    window.output_input.setText(str(tmp_path / "tree.usda"))

    assert window.convert_button.isEnabled()
    assert window.wind_panel.refresh_button.isEnabled()
    assert window.generate_button.isEnabled()


def test_qt_shell_convert_button_switches_to_cancel_while_running(qtbot, tmp_path) -> None:
    theme = load_theme()
    window = MainWindow(
        theme,
        UiShellState(),
        dependencies=build_default_dependencies(),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    window.source_input.setText(str(tmp_path / "tree.xml"))
    window.output_input.setText(str(tmp_path / "tree.usda"))

    assert window.convert_button.text() == "Convert to USDA"
    assert window.convert_mode_button.isEnabled()

    window._set_conversion_running(True)

    assert window.convert_button.text() == "Cancel"
    assert window.convert_button.isEnabled()
    assert not window.convert_mode_button.isEnabled()
    assert not window.wind_panel.refresh_button.isEnabled()


def test_qt_shell_restores_last_paths_when_shared_settings_exist(qtbot, tmp_path) -> None:
    deps = build_default_dependencies()
    saved_xml = tmp_path / "saved.xml"
    saved_usda = tmp_path / "saved.usda"
    saved_xml.write_text("<tree/>", encoding="utf-8")
    deps.save_gui_settings(
        tmp_path / "gui_settings.json",
        GuiSettingsSnapshot(
            last_input_path=str(saved_xml),
            last_output_path=str(saved_usda),
            cpu_profile=CpuProfile.BALANCED,
            preserve_temp_files=True,
            material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
            bark_material_path="/Game/Assembly/SimpleTree/Bark1.Bark1",
            leaves_material_path="/Game/Assembly/SimpleTree/Leaves1.Leaves1",
            single_material_path="",
            gust_attenuation=0.6,
            is_ground_cover=False,
            wind_group_settings={},
        ),
    )
    theme = load_theme()
    window = MainWindow(
        theme,
        UiShellState(),
        dependencies=deps,
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    assert window.source_input.text() == str(saved_xml)
    assert window.output_input.text() == str(saved_usda)
    assert window.convert_button.isEnabled()


def test_qt_shell_auto_refreshes_wind_after_source_insert(monkeypatch, qtbot, tmp_path) -> None:
    theme = load_theme()
    window = MainWindow(
        theme,
        UiShellState(),
        dependencies=build_default_dependencies(),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    calls: list[str] = []
    monkeypatch.setattr(window, "_reload_input_dependent_tabs", lambda: None)
    monkeypatch.setattr(window, "refresh_wind_groups", lambda: calls.append("refresh"))

    xml_path = tmp_path / "tree.xml"
    xml_path.write_text("<Tree/>", encoding="utf-8")
    window.source_input.setText(str(xml_path))
    qtbot.waitUntil(lambda: calls == ["refresh"], timeout=1000)

    assert calls == ["refresh"]


def test_qt_shell_path_fields_show_compact_display_when_not_focused(qtbot, tmp_path) -> None:
    theme = load_theme()
    window = MainWindow(
        theme,
        UiShellState(),
        dependencies=build_default_dependencies(),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    xml_path = tmp_path / "nested" / "tree.xml"
    xml_path.parent.mkdir()
    xml_path.write_text("<Tree/>", encoding="utf-8")
    window.source_input.setText(str(xml_path))

    assert window.source_input.text() == str(xml_path)
    assert window.source_input.displayText().endswith("\\nested\\tree.xml")
    assert window.source_input.displayText().startswith("...\\")


def test_qt_shell_restores_from_maximized_state(qtbot, tmp_path) -> None:
    theme = load_theme()
    state = UiShellState(x=140, y=100, width=1280, height=820, is_maximized=True)
    window = MainWindow(
        theme,
        state,
        dependencies=build_default_dependencies(),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(window.isMaximized, timeout=3000)

    window.toggle_maximized()
    qtbot.waitUntil(lambda: not window.isMaximized(), timeout=3000)

    geometry = window.geometry()
    assert geometry.width() == 1280
    assert geometry.height() == 820


def test_qt_shell_uses_slider_editor_for_wind_numeric_controls(qtbot, tmp_path) -> None:
    theme = load_theme()
    window = MainWindow(
        theme,
        UiShellState(),
        dependencies=build_default_dependencies(),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    assert isinstance(window.wind_panel.gust_spin, SliderSpinEditor)
    assert window.wind_panel.gust_spin.spin.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
