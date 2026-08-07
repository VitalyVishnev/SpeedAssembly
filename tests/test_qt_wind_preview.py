from __future__ import annotations

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytestmark = pytest.mark.qt

from xml_to_usda.qt_ui import wind_preview as wind_preview_module
from xml_to_usda.qt_ui.wind_preview import WindPreviewDialog
from xml_to_usda.wind_external_skeleton import (
    ExternalSkeletonChoice,
    ExternalSkeletonChoicesResult,
    ExternalSkeletonPreviewRequest,
)


def test_external_skeleton_selection_loads_without_a_load_button(qtbot, monkeypatch, tmp_path) -> None:
    selected_path = tmp_path / "tree.fbx"
    requests = []
    dialog = WindPreviewDialog(external_preview_requested=requests.append)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(
        wind_preview_module.QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(selected_path), "FBX files (*.fbx)"),
    )
    monkeypatch.setattr(wind_preview_module, "external_skeleton_backend_available", lambda _suffix: (True, ""))

    dialog.browse_external_path()
    dialog.browse_external_path()

    assert not hasattr(dialog, "load_external_button")
    assert dialog.external_path_edit.isReadOnly()
    assert requests == [
        ExternalSkeletonPreviewRequest(str(selected_path), group_count=1),
        ExternalSkeletonPreviewRequest(str(selected_path), group_count=1),
    ]


def test_external_usd_skeleton_choice_loads_when_selected(qtbot, monkeypatch, tmp_path) -> None:
    selected_path = tmp_path / "tree.usda"
    requests = []
    dialog = WindPreviewDialog(external_preview_requested=requests.append)
    qtbot.addWidget(dialog)
    dialog.external_path_edit.setText(str(selected_path))
    monkeypatch.setattr(wind_preview_module, "external_skeleton_backend_available", lambda _suffix: (True, ""))

    initial_request = dialog.set_external_skeleton_choices(
        ExternalSkeletonChoicesResult(
            str(selected_path),
            (
                ExternalSkeletonChoice(0, "/Tree/Oak", "Oak", 12),
                ExternalSkeletonChoice(1, "/Tree/Pine", "Pine", 20),
            ),
        )
    )
    dialog.external_skeleton_combo.setCurrentIndex(2)

    assert initial_request is None
    assert requests == [ExternalSkeletonPreviewRequest(str(selected_path), group_count=1, skeleton_index=1)]
