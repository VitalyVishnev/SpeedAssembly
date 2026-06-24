from __future__ import annotations

from pathlib import Path

from xml_to_usda.proxy_mesh_service import ProxyMeshSettings, ProxyMeshSourceRequest
from xml_to_usda.proxy_mesh_worker_subprocess import (
    ProxyMeshWorkerRequest,
    run_proxy_mesh_worker_request_file,
    write_proxy_mesh_worker_request,
)


def test_proxy_mesh_worker_reports_stage_breadcrumbs(monkeypatch, capsys, tmp_path: Path) -> None:
    request_path = tmp_path / "proxy.request.pkl"
    result_path = tmp_path / "proxy.result.pkl"
    error_path = tmp_path / "proxy.error.json"

    monkeypatch.setattr(
        "xml_to_usda.proxy_mesh_worker_subprocess.generate_proxy_mesh_from_source_request",
        lambda _request, _settings: "proxy-result",
    )
    write_proxy_mesh_worker_request(
        request_path,
        ProxyMeshWorkerRequest(
            request=ProxyMeshSourceRequest(input_path="tree.xml", output_path=str(tmp_path / "tree.usda")),
            settings=ProxyMeshSettings(final_polycount=5000, density_resolution=12),
            action="preview",
            result_path=str(result_path),
            error_path=str(error_path),
        ),
    )

    assert run_proxy_mesh_worker_request_file(request_path) == 0

    stderr = capsys.readouterr().err
    assert "proxy-mesh-worker stage=request.read.start" in stderr
    assert "proxy-mesh-worker stage=preview.generate.start" in stderr
    assert "density_resolution=12" in stderr
    assert "proxy-mesh-worker stage=preview.generate.end" in stderr
    assert "proxy-mesh-worker stage=result.write.end" in stderr
    assert result_path.exists()
    assert error_path.exists() is False
