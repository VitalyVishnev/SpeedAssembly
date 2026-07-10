from __future__ import annotations

from dataclasses import replace
from xml.etree.ElementTree import ParseError

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

pytestmark = pytest.mark.qt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractSpinBox, QMessageBox, QWidget

from xml_to_usda.discovery_service import BaseMaterialDiscovery, BaseMaterialRowSpec, PrototypeDiscovery, PrototypeRowSpec
from xml_to_usda.qt_ui.dependencies import build_default_dependencies
from xml_to_usda.qt_ui.entry import main
from xml_to_usda.qt_ui.entry import _build_signature_from_executable_path
from xml_to_usda.models import CpuProfile, MaterialPolicy, UdimMode
from xml_to_usda.qt_ui.panels import SliderSpinEditor, _make_udim_controls
from xml_to_usda.qt_ui.persistence import UiShellState
from xml_to_usda.qt_ui.window import MainWindow
from xml_to_usda.qt_ui.theme import ThemeOverrides, load_bundled_theme, load_theme
from xml_to_usda.settings_service import GuiSettingsSnapshot, load_gui_settings
from xml_to_usda.cache_maintenance import CacheMaintenanceSummary
from xml_to_usda.fbx_payload_cache import FbxPayloadCacheSummary
from xml_to_usda.runtime_paths import RuntimeCleanupSummary


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


def test_qt_shell_survives_startup_discovery_failure(qtbot, tmp_path) -> None:
    theme = load_theme()
    xml_path = tmp_path / "tree.xml"
    xml_path.write_text("<Tree/>", encoding="utf-8")
    settings_path = tmp_path / "gui_settings.json"
    from xml_to_usda.settings_service import save_gui_settings

    save_gui_settings(
        settings_path,
        GuiSettingsSnapshot(last_input_path=str(xml_path)),
    )

    deps = build_default_dependencies()

    def _discover_part_prototype_rows(input_path, persisted_records=()):
        assert input_path == str(xml_path)
        return PrototypeDiscovery(
            summary="Found 1 repeated branch instance across 1 prototype(s).",
            rows=(
                PrototypeRowSpec(
                    source_key="Mesh_1",
                    source_name="Twig_01",
                    source_mesh_id=1,
                    instance_count=1,
                ),
            ),
        )

    def _discover_base_material_rows(_input_path, persisted_records=()):
        raise AttributeError("'str' object has no attribute 'target'")

    deps = replace(
        deps,
        discover_part_prototype_rows=_discover_part_prototype_rows,
        discover_base_material_rows=_discover_base_material_rows,
    )

    window = MainWindow(
        theme,
        UiShellState(),
        dependencies=deps,
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=settings_path,
    )
    qtbot.addWidget(window)
    window.show()

    assert window.materials_panel.summary_label.text() == "Selected XML file could not be loaded."
    assert window.geometry_panel.summary_label.text() == "Selected XML file could not be loaded."
    assert window.wind_panel.summary_label.text() == "Selected XML file could not be loaded."
    assert not window.geometry_panel.has_rows()


def test_qt_shell_startup_discovery_reads_xml_once_per_panel(qtbot, tmp_path) -> None:
    theme = load_theme()
    xml_path = tmp_path / "tree.xml"
    xml_path.write_text("<Tree/>", encoding="utf-8")
    settings_path = tmp_path / "gui_settings.json"
    from xml_to_usda.settings_service import save_gui_settings

    save_gui_settings(settings_path, GuiSettingsSnapshot(last_input_path=str(xml_path)))
    calls = {"part": 0, "base": 0}
    deps = build_default_dependencies()

    def _discover_part_prototype_rows(input_path, persisted_records=()):
        calls["part"] += 1
        if calls["part"] > 1:
            raise ParseError("simulated second startup XML parse failure")
        assert input_path == str(xml_path)
        return PrototypeDiscovery(
            summary="Found 1 repeated branch instance across 1 prototype(s).",
            rows=(
                PrototypeRowSpec(
                    source_key="Mesh_1",
                    source_name="Twig_01",
                    source_mesh_id=1,
                    instance_count=1,
                ),
            ),
        )

    def _discover_base_material_rows(input_path, persisted_records=()):
        calls["base"] += 1
        assert input_path == str(xml_path)
        return BaseMaterialDiscovery(
            summary="Found 1 base XML material slot(s).",
            rows=(BaseMaterialRowSpec(source_id=1, source_name="Bark"),),
        )

    deps = replace(
        deps,
        discover_part_prototype_rows=_discover_part_prototype_rows,
        discover_base_material_rows=_discover_base_material_rows,
    )

    window = MainWindow(
        theme,
        UiShellState(),
        dependencies=deps,
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=settings_path,
    )
    qtbot.addWidget(window)
    window.show()

    assert calls == {"part": 1, "base": 1}
    assert window.geometry_panel.has_rows()
    assert "Found 1 base XML material slot" in window.materials_panel.summary_label.text()


def test_qt_shell_title_buttons_do_not_clip_text_when_theme_height_is_too_small(qtbot, tmp_path) -> None:
    theme = load_theme(
        overrides=ThemeOverrides(
            theme_name="default",
            payload={"chrome": {"title_pill_height": 10, "adjust_ui_button_height": 10}},
        )
    )
    window = MainWindow(
        theme,
        UiShellState(),
        dependencies=build_default_dependencies(),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    for button in (
        window.title_bar.help_button,
        window.title_bar.log_button,
        window.title_bar.support_button,
        window.title_bar.adjust_button,
    ):
        assert button.height() >= button.fontMetrics().height() + 6


def test_qt_shell_title_help_button_fits_its_label_width(qtbot, tmp_path) -> None:
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

    help_button = window.title_bar.help_button
    assert help_button.width() >= help_button.fontMetrics().horizontalAdvance(help_button.text()) + 32


def test_qt_shell_scrollable_surfaces_keep_vertical_scrollbar_visible(qtbot, tmp_path) -> None:
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

    window.open_log_dialog()

    assert window._log_dialog is not None
    for widget in (
        window._log_dialog.editor,
        window.wind_panel.scroll,
        window.geometry_panel.scroll,
        window.materials_panel.scroll,
    ):
        assert widget.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOn


def test_qt_shell_factory_defaults_preset_control_stays_compact(qtbot, tmp_path) -> None:
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

    text_width = window.preset_combo.fontMetrics().horizontalAdvance(window.preset_combo.currentText())
    assert window.preset_combo.width() >= text_width + 40
    assert window.preset_combo.width() <= text_width + 64


def test_udim_id_spin_has_room_for_four_digit_id(qtbot) -> None:
    host = QWidget()
    qtbot.addWidget(host)

    _mode_combo, spin = _make_udim_controls(host, mode=UdimMode.OFF, udim_id=1001)

    assert spin.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
    assert spin.objectName() == "UdimIdSpin"
    assert spin.minimumWidth() >= spin.fontMetrics().horizontalAdvance("1999") + 32
    assert spin.maximumWidth() == spin.minimumWidth()


def test_udim_mode_combo_has_room_for_longest_label(qtbot) -> None:
    host = QWidget()
    qtbot.addWidget(host)

    combo, _spin = _make_udim_controls(host, mode=UdimMode.WRITE_SECONDARY_UV_OFFSET, udim_id=1001)

    longest_label_width = combo.fontMetrics().horizontalAdvance("Write UV1 Offset")
    assert combo.minimumWidth() >= longest_label_width + 64
    assert combo.maximumWidth() == combo.minimumWidth()


def test_qt_shell_scales_glass_panel_from_runtime_screen_scale(monkeypatch, qtbot, tmp_path) -> None:
    monkeypatch.setattr("xml_to_usda.qt_ui.window.compute_screen_scale", lambda *_args, **_kwargs: 1.25)
    theme = load_theme()
    window = MainWindow(
        theme,
        UiShellState(width=1360, height=860),
        dependencies=build_default_dependencies(),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=tmp_path / "gui_settings.json",
    )
    qtbot.addWidget(window)
    window.show()

    assert window.panel.width() == 1224
    assert theme.layout["panel_preferred_width"] == 979


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
            build_signature=None,
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


def test_qt_entry_build_signature_can_come_from_single_executable(tmp_path) -> None:
    executable_path = tmp_path / "XMLtoUSDAConverter.exe"
    executable_path.write_bytes(b"abc")

    signature = _build_signature_from_executable_path(executable_path)

    assert signature == f"exe|3|{executable_path.stat().st_mtime_ns}"


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


def test_qt_shell_groups_generate_actions_into_a_split_button(qtbot, tmp_path) -> None:
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

    assert window.generate_button.text() == "Generate\nWind JSON"
    assert window.generate_proxy_button.text() == "Generate\nProxy Mesh"
    assert window.generate_action_frame.layout().count() == 3
    assert window.generate_action_divider.objectName() == "GenerateActionDivider"
    assert window.generate_action_frame.width() == window.convert_action_frame.width()
    assert window.generate_action_frame.height() == window.convert_action_frame.height()
    assert window.generate_button.width() + window.generate_proxy_button.width() + window.generate_action_divider.width() == window.generate_action_frame.width()
    assert window.generate_button.height() > 0
    assert window.generate_proxy_button.height() > 0


def test_qt_shell_bundled_theme_bakes_reduced_left_column_width() -> None:
    assert load_bundled_theme().layout["left_column_width"] == 300


def test_qt_title_bar_shows_global_settings_gear_instead_of_title(qtbot, tmp_path) -> None:
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

    assert window.title_bar.settings_button.text() == "⚙"
    assert not hasattr(window.title_bar, "title_label")


def test_qt_global_settings_popup_saves_cache_limits_and_sweeps(monkeypatch, qtbot, tmp_path) -> None:
    sweep_calls = []
    monkeypatch.setattr(
        "xml_to_usda.qt_ui.window.summarize_fbx_payload_cache",
        lambda **_kwargs: FbxPayloadCacheSummary(entry_count=2, total_bytes=4096),
    )
    monkeypatch.setattr(
        "xml_to_usda.qt_ui.window.sweep_fbx_payload_cache",
        lambda **kwargs: sweep_calls.append(kwargs) or FbxPayloadCacheSummary(entry_count=1, total_bytes=1024),
    )
    theme = load_theme()
    settings_path = tmp_path / "gui_settings.json"
    window = MainWindow(
        theme,
        UiShellState(),
        dependencies=build_default_dependencies(),
        state_path=tmp_path / "ui_next_state.json",
        operator_settings_path=settings_path,
    )
    qtbot.addWidget(window)
    window.show()
    sweep_calls.clear()

    qtbot.mouseClick(window.title_bar.settings_button, Qt.MouseButton.LeftButton)
    dialog = window._global_settings_dialog
    assert dialog is not None
    assert dialog.isVisible()
    dialog.max_size_spin.setValue(12)
    dialog.max_age_spin.setValue(3)
    dialog.debug_trace_checkbox.setChecked(True)
    qtbot.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)

    saved = load_gui_settings(settings_path)
    assert saved.fbx_cache_max_size_gb == 12
    assert saved.fbx_cache_max_age_days == 3
    assert saved.debug_trace_enabled is True
    assert sweep_calls[-1]["max_bytes"] == 12 * 1024 * 1024 * 1024
    assert sweep_calls[-1]["max_age_seconds"] == 3 * 24 * 60 * 60


def test_qt_global_settings_clear_cache_requires_confirmation(monkeypatch, qtbot, tmp_path) -> None:
    clear_calls = []
    monkeypatch.setattr(
        "xml_to_usda.qt_ui.window.summarize_fbx_payload_cache",
        lambda **_kwargs: FbxPayloadCacheSummary(entry_count=2, total_bytes=4096),
    )
    monkeypatch.setattr(
        "xml_to_usda.qt_ui.window.sweep_fbx_payload_cache",
        lambda **_kwargs: FbxPayloadCacheSummary(entry_count=2, total_bytes=4096),
    )
    monkeypatch.setattr(
        "xml_to_usda.qt_ui.window.clear_fbx_payload_cache",
        lambda **kwargs: clear_calls.append(kwargs) or FbxPayloadCacheSummary(removed_entries=2, removed_bytes=4096),
    )
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.No))
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

    qtbot.mouseClick(window.title_bar.settings_button, Qt.MouseButton.LeftButton)
    dialog = window._global_settings_dialog
    assert dialog is not None
    qtbot.mouseClick(dialog.clear_button, Qt.MouseButton.LeftButton)
    assert clear_calls == []

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    qtbot.mouseClick(dialog.clear_button, Qt.MouseButton.LeftButton)
    assert len(clear_calls) == 1


def test_qt_global_settings_clear_all_cache_requires_confirmation(monkeypatch, qtbot, tmp_path) -> None:
    clear_calls = []
    empty_summary = CacheMaintenanceSummary(
        runtime=RuntimeCleanupSummary(),
        fbx=FbxPayloadCacheSummary(entry_count=3, total_bytes=8192),
    )
    monkeypatch.setattr("xml_to_usda.qt_ui.window.summarize_application_cache", lambda *_args: empty_summary)
    monkeypatch.setattr("xml_to_usda.qt_ui.window.sweep_application_cache", lambda *_args, **_kwargs: empty_summary)
    monkeypatch.setattr(
        "xml_to_usda.qt_ui.window.clear_application_cache",
        lambda *_args: clear_calls.append(True) or empty_summary,
    )
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.No))
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

    qtbot.mouseClick(window.title_bar.settings_button, Qt.MouseButton.LeftButton)
    dialog = window._global_settings_dialog
    assert dialog is not None
    qtbot.mouseClick(dialog.clear_all_button, Qt.MouseButton.LeftButton)
    assert clear_calls == []

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    qtbot.mouseClick(dialog.clear_all_button, Qt.MouseButton.LeftButton)
    assert len(clear_calls) == 1


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
    assert not window.title_bar.settings_button.isEnabled()
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
    available = window.screen().availableGeometry()
    assert geometry.width() == max(window.minimumWidth(), int(round(available.width() * 0.66)))
    assert geometry.height() == max(window.minimumHeight(), int(round(available.height() * 0.78)))


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
