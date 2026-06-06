from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
_QT_WIDGETS_PATCHED = False
_ORIGINAL_WIDGET_SHOW = None

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
