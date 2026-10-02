from __future__ import annotations

from pathlib import Path

from xml_to_usda.models import PrototypeSourceConfig
from xml_to_usda.part_preview_service import (
    PartPrototypePreviewRequest,
    PartPrototypePreviewResult,
    PartPrototypePreviewSettings,
)
from xml_to_usda.part_preview_worker_subprocess import (
    PartPreviewWorkerRequest,
    read_part_preview_worker_result,
    run_part_preview_worker_request_file,
    write_part_preview_worker_request,
)
from xml_to_usda.worker_file_protocol import WORKER_TOKEN_ENV


def test_part_preview_worker_writes_result(monkeypatch, tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    result_path = tmp_path / "result.json"
    error_path = tmp_path / "error.json"
    worker_token = "test-worker-token"
    result = PartPrototypePreviewResult(
        source_key="Mesh_1",
        source_name="Twig",
        source_mode=PrototypeSourceConfig(source_key="Mesh_1").mode,
        mesh=None,
    )

    monkeypatch.setenv(WORKER_TOKEN_ENV, worker_token)
    monkeypatch.setattr(
        "xml_to_usda.part_preview_worker_subprocess.build_part_prototype_preview",
        lambda request, settings: result,
    )
    write_part_preview_worker_request(
        request_path,
        PartPreviewWorkerRequest(
            request=PartPrototypePreviewRequest(
                input_path="tree.xml",
                source_key="Mesh_1",
                source_name="Twig",
                prototype_source_config=PrototypeSourceConfig(source_key="Mesh_1"),
            ),
            settings=PartPrototypePreviewSettings(),
            result_path=str(result_path),
            error_path=str(error_path),
            worker_token=worker_token,
        ),
    )

    assert run_part_preview_worker_request_file(request_path) == 0
    assert read_part_preview_worker_result(result_path) == result
    assert not error_path.exists()


def test_part_preview_worker_rejects_missing_origin_token(monkeypatch, tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    result_path = tmp_path / "result.json"
    error_path = tmp_path / "error.json"

    monkeypatch.delenv(WORKER_TOKEN_ENV, raising=False)
    write_part_preview_worker_request(
        request_path,
        PartPreviewWorkerRequest(
            request=PartPrototypePreviewRequest(
                input_path="tree.xml",
                source_key="Mesh_1",
                source_name="Twig",
                prototype_source_config=PrototypeSourceConfig(source_key="Mesh_1"),
            ),
            settings=PartPrototypePreviewSettings(),
            result_path=str(result_path),
            error_path=str(error_path),
            worker_token="request-token",
        ),
    )

    assert run_part_preview_worker_request_file(request_path) == 1
    assert error_path.exists()
    assert not result_path.exists()
