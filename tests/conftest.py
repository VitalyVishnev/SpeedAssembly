from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
_QT_WIDGETS_PATCHED = False
_ORIGINAL_WIDGET_SHOW = None
_PACKAGED_TEST_FILES = {
    "test_packaged_stability_gate.py",
    "test_qt_smoke_runner.py",
    "test_release_build.py",
    "test_release_bundle.py",
}
_INTEGRATION_TEST_FILES = {
    "test_detailed_fracture_export_regression.py",
}
_INTEGRATION_TEST_IDS = (
    "test_boolean_fracture_prototype.py::test_multi_prototype_assembles_independent_real_tree_cuts",
    "test_boolean_fracture_prototype.py::test_big_spruce_cut_selects_the_dominant_bone_shell",
    "test_boolean_fracture_prototype.py::test_prepared_multi_session_does_not_retain_native_manifold_objects",
    "test_boolean_fracture_prototype.py::test_multi_prototype_keeps_one_boolean_stump_per_disconnected_stem",
    "test_boolean_fracture_prototype.py::test_multi_replan_reuses_unchanged_cut_sessions_and_results",
    "test_boolean_fracture_prototype.py::test_multi_prototype_sequences_stump_and_branch_cuts_on_one_shell",
)
_INTEGRATION_TEST_TOKENS = (
    "_process",
    "_real_sample",
    "_pipeline",
    "_worker_subprocess",
)

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def _enable_json_geometry_test_backend(monkeypatch):
    monkeypatch.setenv("XML_TO_USDA_ENABLE_JSON_GEOMETRY_BACKEND", "1")


def pytest_runtest_setup(item):
    global _QT_WIDGETS_PATCHED, _ORIGINAL_WIDGET_SHOW
    if _QT_WIDGETS_PATCHED:
        return
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QWidget
    except Exception:
        return

    _ORIGINAL_WIDGET_SHOW = QWidget.show

    def _show_without_mapping(self, *args, **kwargs):
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        if self.isWindow():
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        return _ORIGINAL_WIDGET_SHOW(self, *args, **kwargs)

    QWidget.show = _show_without_mapping
    _QT_WIDGETS_PATCHED = True


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Assign one execution layer without duplicating per-test decorators."""
    for item in items:
        file_name = item.path.name
        if "big_spruce" in item.nodeid.lower():
            item.add_marker(pytest.mark.stress)
        if file_name in _PACKAGED_TEST_FILES:
            item.add_marker(pytest.mark.packaged)
        elif (
            file_name in _INTEGRATION_TEST_FILES
            or file_name.startswith("test_qt_")
            or any(token in file_name for token in _INTEGRATION_TEST_TOKENS)
            or any(token in item.nodeid for token in _INTEGRATION_TEST_IDS)
        ):
            item.add_marker(pytest.mark.integration)
        else:
            item.add_marker(pytest.mark.core)
