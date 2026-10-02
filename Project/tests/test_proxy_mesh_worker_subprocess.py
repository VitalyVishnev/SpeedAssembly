from __future__ import annotations

from pathlib import Path

from xml_to_usda.proxy_mesh_service import ProxyMeshSettings, ProxyMeshSourceRequest
from xml_to_usda.proxy_mesh_worker_subprocess import (
    ProxyMeshWorkerRequest,
    run_proxy_mesh_worker_request_file,
    write_proxy_mesh_worker_request,
)
from xml_to_usda.worker_file_protocol import WORKER_TOKEN_ENV, read_worker_payload


def test_proxy_mesh_worker_reports_stage_breadcrumbs(monkeypatch, capsys, tmp_path: Path) -> None:
    request_path = tmp_path / "proxy.request.json"
    result_path = tmp_path / "proxy.result.json"
    error_path = tmp_path / "proxy.error.json"
    worker_token = "test-worker-token"

    monkeypatch.setenv(WORKER_TOKEN_ENV, worker_token)
    monkeypatch.setattr(
        "xml_to_usda.proxy_mesh_worker_subprocess.generate_proxy_preview_payload_from_source_request",
        lambda _request, _settings: ("proxy-result", "source-scene"),
    )
    write_proxy_mesh_worker_request(
        request_path,
        ProxyMeshWorkerRequest(
            request=ProxyMeshSourceRequest(input_path="tree.xml", output_path=str(tmp_path / "tree.usda")),
            settings=ProxyMeshSettings(
                final_polycount=5000,
                density_resolution=12,
                fuse_base_mesh_vertices=True,
                branch_prune_aggression=0.4,
            ),
            action="preview_with_source",
            result_path=str(result_path),
            error_path=str(error_path),
            worker_token=worker_token,
        ),
    )

    assert run_proxy_mesh_worker_request_file(request_path) == 0

    stderr = capsys.readouterr().err
    assert "proxy-mesh-worker stage=request.read.start" in stderr
    assert "proxy-mesh-worker stage=preview.generate.start" in stderr
    assert "density_resolution=12" in stderr
    assert "fuse_base_mesh_vertices=True" in stderr
    assert "branch_prune_aggression=0.4" in stderr
    assert "proxy-mesh-worker stage=preview.generate.end" in stderr
    assert "proxy-mesh-worker stage=result.write.end" in stderr
    result = read_worker_payload(result_path)
    assert result.proxy == "proxy-result"
    assert result.source_scene == "source-scene"
    assert result_path.exists()
    assert error_path.exists() is False


def test_proxy_mesh_worker_rejects_mismatched_origin_token(monkeypatch, tmp_path: Path) -> None:
    request_path = tmp_path / "proxy.request.json"
    result_path = tmp_path / "proxy.result.json"
    error_path = tmp_path / "proxy.error.json"

    monkeypatch.setenv(WORKER_TOKEN_ENV, "expected-token")
    write_proxy_mesh_worker_request(
        request_path,
        ProxyMeshWorkerRequest(
            request=ProxyMeshSourceRequest(input_path="tree.xml", output_path=str(tmp_path / "tree.usda")),
            settings=ProxyMeshSettings(),
            action="preview",
            result_path=str(result_path),
            error_path=str(error_path),
            worker_token="wrong-token",
        ),
    )

    assert run_proxy_mesh_worker_request_file(request_path) == 1
    assert error_path.exists()
    assert result_path.exists() is False


def test_proxy_mesh_worker_can_fit_collision_without_generating_proxy(monkeypatch, tmp_path: Path) -> None:
    request_path = tmp_path / "proxy.request.json"
    result_path = tmp_path / "proxy.result.json"
    error_path = tmp_path / "proxy.error.json"
    worker_token = "test-worker-token"
    expected = ()

    def fail_if_proxy_regenerates(*_args) -> None:
        raise AssertionError("Proxy Mesh must not regenerate")

    monkeypatch.setenv(WORKER_TOKEN_ENV, worker_token)
    monkeypatch.setattr(
        "xml_to_usda.proxy_mesh_worker_subprocess.generate_proxy_collision_meshes_from_source_request",
        lambda _request, _settings: expected,
    )
    monkeypatch.setattr(
        "xml_to_usda.proxy_mesh_worker_subprocess.generate_proxy_preview_payload_from_source_request",
        fail_if_proxy_regenerates,
    )
    write_proxy_mesh_worker_request(
        request_path,
        ProxyMeshWorkerRequest(
            request=ProxyMeshSourceRequest(input_path="tree.xml"),
            settings=ProxyMeshSettings(),
            action="collision",
            result_path=str(result_path),
            error_path=str(error_path),
            worker_token=worker_token,
        ),
    )

    assert run_proxy_mesh_worker_request_file(request_path) == 0
    assert read_worker_payload(result_path).collision_meshes == expected
