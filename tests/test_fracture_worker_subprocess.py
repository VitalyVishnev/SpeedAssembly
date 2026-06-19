from __future__ import annotations

import builtins
import importlib
import sys
from pathlib import Path

import xml_to_usda
from xml_to_usda.fracture_preview_service import FracturePreviewSettings, FracturePreviewSourceRequest
from xml_to_usda.fracture_service import FractureSettings
from xml_to_usda import worker_file_protocol
from xml_to_usda.fracture_worker_subprocess import (
    FRACTURE_WORKER_ACTION_PREVIEW,
    FractureWorkerRequest,
    read_fracture_worker_result,
    run_fracture_worker_request_file,
    write_fracture_worker_request,
    write_fracture_worker_result,
)


SIMPLE_TREE_01 = (
    Path(__file__).resolve().parents[1]
    / "samples"
    / "speedtree"
    / "simple_tree"
    / "variants"
    / "SimpleTree_01.xml"
)


def test_fracture_preview_worker_does_not_depend_on_export_service(monkeypatch, tmp_path: Path) -> None:
    request_path = tmp_path / "preview.request.pkl"
    result_path = tmp_path / "preview.result.pkl"
    error_path = tmp_path / "preview.error.json"
    write_fracture_worker_request(
        request_path,
        FractureWorkerRequest(
            request=FracturePreviewSourceRequest(
                input_path=str(SIMPLE_TREE_01),
                output_path=str(tmp_path / "SimpleTree_01.usda"),
            ),
            settings=FracturePreviewSettings(
                fracture=FractureSettings(target_piece_count=2),
                max_base_faces_per_piece=10,
                max_prototype_faces=5,
            ),
            action=FRACTURE_WORKER_ACTION_PREVIEW,
            result_path=str(result_path),
            error_path=str(error_path),
        ),
    )

    original_worker_module = sys.modules.get("xml_to_usda.fracture_worker_subprocess")
    original_export_module = sys.modules.get("xml_to_usda.fracture_export_service")
    sys.modules.pop("xml_to_usda.fracture_worker_subprocess", None)
    sys.modules.pop("xml_to_usda.fracture_export_service", None)
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in {"xml_to_usda.fracture_export_service", "fracture_export_service"}:
            raise AssertionError("Preview fracture worker imported export service.")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    try:
        worker_module = importlib.import_module("xml_to_usda.fracture_worker_subprocess")
        assert worker_module.run_fracture_worker_request_file(request_path) == 0
    finally:
        if original_worker_module is not None:
            sys.modules["xml_to_usda.fracture_worker_subprocess"] = original_worker_module
            setattr(xml_to_usda, "fracture_worker_subprocess", original_worker_module)
        elif hasattr(xml_to_usda, "fracture_worker_subprocess"):
            delattr(xml_to_usda, "fracture_worker_subprocess")
        if original_export_module is not None:
            sys.modules["xml_to_usda.fracture_export_service"] = original_export_module
            setattr(xml_to_usda, "fracture_export_service", original_export_module)
        elif hasattr(xml_to_usda, "fracture_export_service"):
            delattr(xml_to_usda, "fracture_export_service")

    result = read_fracture_worker_result(result_path)
    assert result is not None
    assert result.plan.actual_piece_count == 2
    assert error_path.exists() is False


def test_fracture_preview_worker_reports_caps_stage_breadcrumbs(capsys, tmp_path: Path) -> None:
    request_path = tmp_path / "preview_caps.request.pkl"
    result_path = tmp_path / "preview_caps.result.pkl"
    error_path = tmp_path / "preview_caps.error.json"
    write_fracture_worker_request(
        request_path,
        FractureWorkerRequest(
            request=FracturePreviewSourceRequest(
                input_path=str(SIMPLE_TREE_01),
                output_path=str(tmp_path / "SimpleTree_01.usda"),
            ),
            settings=FracturePreviewSettings(
                fracture=FractureSettings(target_piece_count=2, generate_caps=True),
                max_base_faces_per_piece=10,
                max_prototype_faces=5,
            ),
            action=FRACTURE_WORKER_ACTION_PREVIEW,
            result_path=str(result_path),
            error_path=str(error_path),
        ),
    )

    assert run_fracture_worker_request_file(request_path) == 0

    stderr = capsys.readouterr().err
    assert "fracture-worker stage=request.read.start" in stderr
    assert "fracture-worker stage=preview.generate.start" in stderr
    assert "generate_caps=True" in stderr
    assert "fracture-worker stage=preview.generate.end" in stderr
    assert "fracture-worker stage=result.write.end" in stderr
    result = read_fracture_worker_result(result_path)
    assert result is not None
    assert result.viewport_scene is None
    assert error_path.exists() is False


def test_fracture_worker_request_write_does_not_leave_empty_final_file(monkeypatch, tmp_path: Path) -> None:
    request_path = tmp_path / "preview.request.pkl"
    result_path = tmp_path / "preview.result.pkl"
    error_path = tmp_path / "preview.error.json"
    request = FractureWorkerRequest(
        request=FracturePreviewSourceRequest(
            input_path=str(SIMPLE_TREE_01),
            output_path=str(tmp_path / "SimpleTree_01.usda"),
        ),
        settings=FracturePreviewSettings(),
        action=FRACTURE_WORKER_ACTION_PREVIEW,
        result_path=str(result_path),
        error_path=str(error_path),
    )

    def fail_dump(*args, **kwargs):
        raise RuntimeError("simulated pickle failure")

    monkeypatch.setattr(worker_file_protocol.pickle, "dump", fail_dump)

    try:
        write_fracture_worker_request(request_path, request)
    except RuntimeError as exc:
        assert str(exc) == "simulated pickle failure"
    else:
        raise AssertionError("Expected simulated pickle failure.")

    assert request_path.exists() is False


def test_fracture_worker_result_write_does_not_leave_empty_final_file(monkeypatch, tmp_path: Path) -> None:
    result_path = tmp_path / "preview.result.pkl"

    def fail_dump(*args, **kwargs):
        raise RuntimeError("simulated result pickle failure")

    monkeypatch.setattr(worker_file_protocol.pickle, "dump", fail_dump)

    try:
        write_fracture_worker_result(result_path, object())
    except RuntimeError as exc:
        assert str(exc) == "simulated result pickle failure"
    else:
        raise AssertionError("Expected simulated result pickle failure.")

    assert result_path.exists() is False
