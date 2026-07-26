from __future__ import annotations

from pathlib import Path

from xml_to_usda.discovery_service import SourceDiscoveryRequest
from xml_to_usda.settings_service import BaseMaterialSettingRecord
from xml_to_usda.source_discovery_worker_subprocess import (
    SourceDiscoveryWorkerRequest,
    read_source_discovery_worker_result,
    run_source_discovery_worker_request_file,
    write_source_discovery_worker_request,
)
from xml_to_usda.worker_file_protocol import WORKER_TOKEN_ENV


SIMPLE_TREE = Path("samples/speedtree/simple_tree/variants/SimpleTree_01.xml")


def test_source_discovery_worker_keeps_xml_parsing_outside_the_caller(monkeypatch, tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    result_path = tmp_path / "result.json"
    error_path = tmp_path / "error.json"
    worker_token = "source-discovery-test"
    monkeypatch.setenv(WORKER_TOKEN_ENV, worker_token)
    write_source_discovery_worker_request(
        request_path,
        SourceDiscoveryWorkerRequest(
            request=SourceDiscoveryRequest(
                input_path=str(SIMPLE_TREE),
                base_persisted_records=(
                    BaseMaterialSettingRecord(
                        source_id=1,
                        source_name="Bark",
                        ue_asset_path="/Game/Test/M_Bark.M_Bark",
                    ),
                ),
            ),
            result_path=str(result_path),
            error_path=str(error_path),
            worker_token=worker_token,
        ),
    )

    assert run_source_discovery_worker_request_file(request_path) == 0
    result = read_source_discovery_worker_result(result_path)
    assert result.input_path == str(SIMPLE_TREE)
    assert result.base.rows
    assert any(row.ue_asset_path == "/Game/Test/M_Bark.M_Bark" for row in result.base.rows)
    assert result.prototypes.rows
    assert not error_path.exists()
