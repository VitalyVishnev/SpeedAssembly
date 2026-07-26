from __future__ import annotations

from pathlib import Path

from xml_to_usda.models import DynamicWindData
from xml_to_usda.wind_preview_worker_subprocess import (
    WindPreviewWorkerRequest,
    read_wind_preview_worker_result,
    run_wind_preview_worker_request_file,
    write_wind_preview_worker_request,
)
from xml_to_usda.wind_service import WindInspectionRequest
from xml_to_usda.worker_file_protocol import WORKER_TOKEN_ENV


def test_wind_inspection_uses_the_existing_isolated_wind_worker(monkeypatch, tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    result_path = tmp_path / "result.json"
    error_path = tmp_path / "error.json"
    worker_token = "wind-inspection-test"
    expected = DynamicWindData(joint_assignments=(), simulation_groups=())
    monkeypatch.setenv(WORKER_TOKEN_ENV, worker_token)
    monkeypatch.setattr(
        "xml_to_usda.wind_preview_worker_subprocess.inspect_wind_groups",
        lambda request: expected,
    )
    write_wind_preview_worker_request(
        request_path,
        WindPreviewWorkerRequest(
            request=WindInspectionRequest(input_path="WorldTree.xml"),
            result_path=str(result_path),
            error_path=str(error_path),
            worker_token=worker_token,
        ),
    )

    assert run_wind_preview_worker_request_file(request_path) == 0
    assert read_wind_preview_worker_result(result_path) == expected
    assert not error_path.exists()
