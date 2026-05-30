from __future__ import annotations

import pytest


pytest.importorskip("PySide6")

pytestmark = pytest.mark.qt

from xml_to_usda.qt_ui.window import PathLineEdit, _format_bytes


def test_format_bytes_uses_human_readable_units() -> None:
    assert _format_bytes(0) == "0 B"
    assert _format_bytes(1024) == "1.0 KB"
    assert _format_bytes(5 * 1024 * 1024) == "5.0 MB"


def test_compact_path_keeps_tail_only_for_nested_paths() -> None:
    assert PathLineEdit._compact_path("D:/trees/nested/tree.xml") == "...\\nested\\tree.xml"
    assert PathLineEdit._compact_path("tree.xml") == "tree.xml"
    assert PathLineEdit._compact_path("") == ""
