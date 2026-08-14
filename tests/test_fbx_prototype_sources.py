from __future__ import annotations

import json
from array import array
from pathlib import Path

import pytest

from xml_to_usda.cli import main as cli_main
from xml_to_usda.fbx_adapter import (
    FbxImportError,
    load_fbx_geometry,
)
from xml_to_usda.fbx_import_supervisor import FbxImportTask, _NativeHelperCrash
from xml_to_usda.fbx_payload_cache import FbxPayloadCacheResult
from xml_to_usda.fbx_worker_subprocess import (
    FBX_WORKER_COMMAND,
    FbxWorkerRequest,
    read_fbx_worker_error,
    read_fbx_worker_request,
    write_fbx_worker_request,
)
from xml_to_usda.models import CpuProfile, FbxMaterialMode, PrototypeSourceConfig, PrototypeSourceMode, Vector3
from xml_to_usda.pipeline import convert_file, load_canonical_model
from xml_to_usda.prototype_sources import load_prototype_source_configs_from_json
from xml_to_usda.worker_file_protocol import WORKER_TOKEN_ENV, read_worker_payload, write_error_payload


def _write_fbx_json_payload(
    tmp_path: Path,
    *,
    include_vertex_colors: bool = True,
    color_components: list[float] | None = None,
    fbx_material_slots: list[dict[str, object]] | None = None,
    sections: list[dict[str, object]] | None = None,
    file_name: str = "prototype_payload.json",
) -> Path:
    payload = {
        "point_components": [
            0.0, 0.0, 0.0,
            1.0, 0.0, 0.0,
            0.0, 1.0, 0.0,
            0.0, 0.0, 1.0,
            1.0, 0.0, 1.0,
            0.0, 1.0, 1.0,
        ],
        "face_vertex_counts": [3, 3],
        "face_vertex_indices": [0, 1, 2, 3, 4, 5],
        "uv_components": [
            0.0, 0.0,
            1.0, 0.0,
            0.0, 1.0,
            0.0, 0.0,
            1.0, 0.0,
            0.0, 1.0,
        ],
    }
    if color_components is not None:
        payload["vertex_color_components"] = color_components
    elif include_vertex_colors:
        payload["vertex_color_components"] = [
            0.0, 0.0, 0.0, 1.0,
            0.0, 0.0, 0.0, 1.0,
            0.0, 0.0, 0.0, 1.0,
            1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 1.0,
        ]
    if fbx_material_slots is not None:
        payload["fbx_material_slots"] = fbx_material_slots
    if sections is not None:
        payload["sections"] = sections
    payload_path = tmp_path / file_name
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    return payload_path


def test_load_prototype_source_configs_from_json_reads_fbx_and_unreal_modes(tmp_path: Path) -> None:
    payload_path = _write_fbx_json_payload(tmp_path)
    config_path = tmp_path / "part_sources.json"
    config_path.write_text(
        json.dumps(
            {
                "Twig_01": {
                    "mode": "fbx_file",
                    "fbx_path": str(payload_path),
                    "fbx_material_mode": "single_material",
                },
                "Mesh_2": {"mode": "unreal_asset", "asset_path": "/Game/TreeParts/SK_Twig02.SK_Twig02"},
            }
        ),
        encoding="utf-8",
    )

    configs = load_prototype_source_configs_from_json(str(config_path))

    assert configs == (
        PrototypeSourceConfig(
            source_key="Twig_01",
            source_name="",
            mode=PrototypeSourceMode.FBX_FILE,
            fbx_material_mode=FbxMaterialMode.SINGLE_MATERIAL,
            asset_path=None,
            fbx_path=str(payload_path),
        ),
        PrototypeSourceConfig(
            source_key="Mesh_2",
            source_name="",
            mode=PrototypeSourceMode.UNREAL_ASSET,
            fbx_material_mode=FbxMaterialMode.AUTO,
            asset_path="/Game/TreeParts/SK_Twig02.SK_Twig02",
            fbx_path=None,
        ),
    )


def test_json_geometry_backend_requires_explicit_development_flag(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("XML_TO_USDA_ENABLE_JSON_GEOMETRY_BACKEND", raising=False)
    payload_path = _write_fbx_json_payload(tmp_path)

    with pytest.raises(FbxImportError, match="JSON geometry backend is test-only"):
        load_fbx_geometry(str(payload_path), "Twig_01", cpu_profile=CpuProfile.BALANCED)


def test_fbx_part_source_config_replaces_inline_prototype_with_geometry_payload(tmp_path: Path) -> None:
    payload_path = _write_fbx_json_payload(tmp_path, file_name="SM_BigBranch_01_HIGH.json")
    _, model, diagnostics = load_canonical_model(
        str(Path(__file__).resolve().parents[1] / "samples" / "speedtree" / "simple_tree" / "variants" / "SimpleTree_01.xml"),
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path=str(payload_path),
            ),
        ),
    )

    prototype = next(prototype for prototype in model.prototypes if prototype.source_key == "Mesh_1")

    assert not any(issue.severity == "error" for issue in diagnostics)
    assert prototype.source_mode == PrototypeSourceMode.FBX_FILE
    assert prototype.fbx_material_mode == FbxMaterialMode.AUTO
    assert prototype.mesh is None
    assert prototype.geometry_payload is not None
    assert prototype.fbx_source_path == str(payload_path)
    assert prototype.source_name == "SM_BigBranch_01_HIGH"
    assert prototype.identity.prim_name == "SM_BigBranch_01_HIGH"
    assert {section.material_id: list(section.face_indices) for section in prototype.geometry_payload.sections} == {
        1: [1],
        2: [0],
    }


def test_prototype_source_fbx_loading_uses_supervisor_adapter_for_multiple_prototypes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload_path = _write_fbx_json_payload(tmp_path, file_name="SM_BigBranch_01_HIGH.json")
    payload = load_fbx_geometry(str(payload_path), "SM_BigBranch_01_HIGH")
    supervisor_calls: list[tuple[str, ...]] = []

    import xml_to_usda.prototype_sources as prototype_sources_module

    monkeypatch.setattr(
        prototype_sources_module,
        "import_fbx_payloads",
        lambda tasks, **kwargs: supervisor_calls.append(tuple(task.display_name for task in tasks))
        or {task.task_id: payload for task in tasks},
    )

    _, model, diagnostics = load_canonical_model(
        str(Path(__file__).resolve().parents[1] / "samples" / "speedtree" / "simple_tree" / "variants" / "SimpleTree_01.xml"),
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path=str(payload_path),
            ),
            PrototypeSourceConfig(
                source_key="Mesh_2",
                source_name="Twig_02",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path=str(payload_path),
            ),
        ),
    )

    assert not any(issue.severity == "error" for issue in diagnostics)
    assert all(prototype.geometry_payload is not None for prototype in model.prototypes)
    assert supervisor_calls == [("SM_BigBranch_01_HIGH", "SM_BigBranch_01_HIGH")]


def test_cli_fbx_worker_command_writes_payload_json_and_returns_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import xml_to_usda.fbx_worker_subprocess as fbx_worker_subprocess_module

    result_path = tmp_path / "worker_payload.json"
    error_path = tmp_path / "worker_error.json"
    request_path = tmp_path / "worker_request.json"
    written_payload = {"points": [1, 2, 3]}
    worker_token = "test-worker-token"

    monkeypatch.setenv(WORKER_TOKEN_ENV, worker_token)
    monkeypatch.setattr(
        fbx_worker_subprocess_module,
        "load_fbx_geometry",
        lambda *args, **kwargs: written_payload,
    )
    write_fbx_worker_request(
        request_path,
        FbxWorkerRequest(
            fbx_path=str(tmp_path / "dummy.fbx"),
            prototype_name="SM_BigBranch_01_HIGH",
            cpu_profile=CpuProfile.BALANCED,
            strict_vertex_colors=False,
            result_path=str(result_path),
            error_path=str(error_path),
            worker_token=worker_token,
        ),
    )

    exit_code = cli_main([FBX_WORKER_COMMAND, "--request", str(request_path)])

    assert exit_code == 0
    assert error_path.exists() is False
    assert read_worker_payload(result_path) == written_payload
    assert read_fbx_worker_error(error_path) is None


def test_cli_fbx_worker_command_passes_selective_read_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import xml_to_usda.fbx_worker_subprocess as fbx_worker_subprocess_module

    result_path = tmp_path / "worker_payload.json"
    error_path = tmp_path / "worker_error.json"
    request_path = tmp_path / "worker_request.json"
    fbx_path = tmp_path / "branch.fbx"
    fbx_path.write_bytes(b"fbx")
    observed_kwargs = {}
    worker_token = "test-worker-token"

    monkeypatch.setenv(WORKER_TOKEN_ENV, worker_token)
    def _fake_load_fbx_geometry(*_args, **kwargs):
        observed_kwargs.update(kwargs)
        return {"points": [1, 2, 3]}

    monkeypatch.setattr(fbx_worker_subprocess_module, "load_fbx_geometry", _fake_load_fbx_geometry)
    monkeypatch.setattr(
        fbx_worker_subprocess_module,
        "load_fbx_payload_from_cache",
        lambda *_args, **_kwargs: FbxPayloadCacheResult(None, hit=False),
    )
    monkeypatch.setattr(
        fbx_worker_subprocess_module,
        "store_fbx_payload_in_cache",
        lambda *_args, **_kwargs: None,
    )
    write_fbx_worker_request(
        request_path,
        FbxWorkerRequest(
            fbx_path=str(fbx_path),
            prototype_name="SM_BigBranch_01_HIGH",
            cpu_profile=CpuProfile.BALANCED,
            strict_vertex_colors=False,
            result_path=str(result_path),
            error_path=str(error_path),
            worker_token=worker_token,
            read_vertex_colors=False,
            read_material_slots=True,
        ),
    )

    exit_code = cli_main([FBX_WORKER_COMMAND, "--request", str(request_path)])

    assert exit_code == 0
    assert observed_kwargs["read_vertex_colors"] is False
    assert observed_kwargs["read_material_slots"] is True
    assert observed_kwargs["strict_vertex_colors"] is False


def test_cli_benchmark_fbx_reports_payload_counts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload_path = _write_fbx_json_payload(tmp_path, file_name="benchmark_payload.json")

    exit_code = cli_main(["benchmark-fbx", str(payload_path), "--material-mode", "single_material"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "cache_hit: False" in captured.out
    assert "points: 6" in captured.out
    assert "faces: 2" in captured.out
    assert "vertex_colors: 0" in captured.out
    assert "material_slots: 0" in captured.out


def test_fbx_import_supervisor_uses_self_executable_in_frozen_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import xml_to_usda.fbx_import_supervisor as supervisor_module
    import xml_to_usda.worker_file_protocol as worker_file_protocol

    request_path = tmp_path / "worker_request.json"
    gui_executable = tmp_path / "SpeedAssembly.exe"
    gui_executable.write_bytes(b"")

    monkeypatch.setattr(worker_file_protocol.sys, "frozen", True, raising=False)
    monkeypatch.setattr(worker_file_protocol.sys, "executable", str(gui_executable))

    command = supervisor_module._resolve_helper_command(request_path)

    assert command == [
        str(gui_executable),
        supervisor_module.FBX_WORKER_COMMAND,
        "--request",
        str(request_path),
    ]


def test_fbx_import_supervisor_keeps_requested_initial_concurrency_for_heavy_inputs() -> None:
    import xml_to_usda.fbx_import_supervisor as supervisor_module

    prepared_imports = (
        FbxImportTask(
            task_id=0,
            display_name="SM_BigBranch_01_HIGH",
            prototype_name="SM_BigBranch_01_HIGH",
            fbx_path="first.fbx",
            cpu_profile=CpuProfile.BALANCED,
        ),
        FbxImportTask(
            task_id=1,
            display_name="SM_BigBranch_02_HIGH",
            prototype_name="SM_BigBranch_02_HIGH",
            fbx_path="second.fbx",
            cpu_profile=CpuProfile.BALANCED,
        ),
    )

    worker_count = supervisor_module._resolve_initial_worker_count(
        prepared_imports,
        requested_worker_count=4,
    )

    assert worker_count == 4


def test_fbx_import_supervisor_launches_helper_with_origin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    import xml_to_usda.fbx_import_supervisor as supervisor_module

    class _DummyProcess:
        pid = 12345

        def poll(self):
            return 0

        def terminate(self) -> None:
            pass

        def wait(self, timeout=None):
            return 0

    popen_calls: list[dict[str, object]] = []

    def _fake_popen(args, **kwargs):
        popen_calls.append({"args": args, "kwargs": kwargs})
        return _DummyProcess()

    monkeypatch.setattr(supervisor_module.subprocess, "Popen", _fake_popen)

    helper = supervisor_module._launch_helper(
        FbxImportTask(
            task_id=0,
            display_name="SM_BigBranch_01_HIGH",
            prototype_name="SM_BigBranch_01_HIGH",
            fbx_path="first.fbx",
            cpu_profile=CpuProfile.BALANCED,
        )
    )
    try:
        payload = read_fbx_worker_request(helper.request_path)
        env = popen_calls[0]["kwargs"]["env"]
        assert payload.worker_token == env[WORKER_TOKEN_ENV]
    finally:
        supervisor_module._terminate_helper(helper)


def test_fbx_import_supervisor_retries_remaining_tasks_with_lower_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import xml_to_usda.fbx_import_supervisor as supervisor_module

    tasks = (
        FbxImportTask(
            task_id=0,
            display_name="SM_BigBranch_01_HIGH",
            prototype_name="SM_BigBranch_01_HIGH",
            fbx_path="first.fbx",
            cpu_profile=CpuProfile.BALANCED,
        ),
        FbxImportTask(
            task_id=1,
            display_name="SM_BigBranch_02_HIGH",
            prototype_name="SM_BigBranch_02_HIGH",
            fbx_path="second.fbx",
            cpu_profile=CpuProfile.BALANCED,
        ),
    )
    worker_counts: list[int] = []

    monkeypatch.setattr(supervisor_module, "cpu_worker_count", lambda _profile: 2)
    monkeypatch.setattr(
        supervisor_module,
        "_resolve_initial_worker_count",
        lambda _tasks, requested_worker_count: requested_worker_count,
    )

    def _fake_run_import_batch(tasks, *, worker_count, **kwargs):
        worker_counts.append(worker_count)
        if worker_count == 2:
            raise _NativeHelperCrash(
                "native crash",
                partial_results={0: "payload-0"},
                remaining_tasks=(tasks[1],),
            )
        return {1: "payload-1"}

    monkeypatch.setattr(supervisor_module, "_run_import_batch", _fake_run_import_batch)

    results = supervisor_module.import_fbx_payloads(tasks, cpu_profile=CpuProfile.BALANCED)

    assert worker_counts == [2, 1]
    assert results == {0: "payload-0", 1: "payload-1"}


def test_fbx_import_supervisor_does_not_retry_handled_fbx_failures(
    tmp_path: Path,
) -> None:
    import xml_to_usda.fbx_import_supervisor as supervisor_module

    error_path = tmp_path / "error.json"
    write_error_payload(
        error_path,
        message="FBX parser reported malformed UV data",
        formatted_traceback="ValueError: FBX parser reported malformed UV data",
    )
    task = FbxImportTask(
        task_id=1,
        display_name="SM_BigBranch_02_HIGH",
        prototype_name="SM_BigBranch_02_HIGH",
        fbx_path="second.fbx",
        cpu_profile=CpuProfile.BALANCED,
    )
    helper = supervisor_module._RunningHelper(
        process=object(),
        task=task,
        request_path=tmp_path / "request.json",
        result_path=tmp_path / "result.json",
        error_path=error_path,
    )

    with pytest.raises(RuntimeError, match="malformed UV data"):
        supervisor_module._finalize_helper(helper, exit_code=1)


def test_fbx_part_source_restores_authored_instance_scale_without_xml_original_scale_multiplier(tmp_path: Path) -> None:
    payload_path = _write_fbx_json_payload(tmp_path)
    _, baseline_model, _ = load_canonical_model(str(Path(__file__).resolve().parents[1] / "samples" / "speedtree" / "simple_tree" / "variants" / "SimpleTree_01.xml"))
    _, fbx_model, _ = load_canonical_model(
        str(Path(__file__).resolve().parents[1] / "samples" / "speedtree" / "simple_tree" / "variants" / "SimpleTree_01.xml"),
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path=str(payload_path),
            ),
        ),
    )

    baseline_mesh_1_parts = [part for part in baseline_model.assembly_parts if part.prototype_key == "Mesh_1"]
    fbx_mesh_1_parts = [part for part in fbx_model.assembly_parts if part.prototype_key == "Mesh_1"]
    baseline_mesh_2_parts = [part for part in baseline_model.assembly_parts if part.prototype_key == "Mesh_2"]
    fbx_mesh_2_parts = [part for part in fbx_model.assembly_parts if part.prototype_key == "Mesh_2"]

    assert baseline_mesh_1_parts
    assert len(baseline_mesh_1_parts) == len(fbx_mesh_1_parts)
    assert baseline_mesh_2_parts
    assert len(baseline_mesh_2_parts) == len(fbx_mesh_2_parts)

    assert all(part.scale == Vector3(1.0, 1.0, 1.0) for part in baseline_mesh_1_parts)
    assert all(part.scale == Vector3(1.0, 1.0, 1.0) for part in fbx_mesh_1_parts)

    for baseline_part, fbx_part in zip(baseline_mesh_2_parts, fbx_mesh_2_parts, strict=True):
        assert fbx_part.scale == baseline_part.scale


def test_fbx_part_source_streams_usda_to_disk(tmp_path: Path) -> None:
    payload_path = _write_fbx_json_payload(tmp_path, file_name="SM_BigBranch_01_HIGH.json")
    output_path = tmp_path / "fbx_streamed.usda"

    result = convert_file(
        str(Path(__file__).resolve().parents[1] / "samples" / "speedtree" / "simple_tree" / "variants" / "SimpleTree_01.xml"),
        str(output_path),
        cpu_profile=CpuProfile.QUIET,
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path=str(payload_path),
            ),
        ),
    )

    assert result.usda_document is not None
    assert result.usda_document.text is None
    assert result.usda_document.stats.streamed is True
    assert result.usda_document.stats.bytes_written > 0
    assert output_path.exists()
    assert not output_path.with_name("fbx_streamed.usda.partial").exists()
    usda_text = output_path.read_text(encoding="utf-8")
    assert 'def Xform "SM_BigBranch_01_HIGH"' in usda_text
    assert 'def Mesh "SM_BigBranch_01_HIGH"' in usda_text
    assert 'def Skeleton "SM_BigBranch_01_HIGH_Skeleton"' in usda_text
    assert (
        'append rel skel:skeleton = '
        '</Tree/AssemblyPartsInstancer/Prototypes/SM_BigBranch_01_HIGH/PartSkelRoot/SM_BigBranch_01_HIGH_Skeleton>'
        in usda_text
    )
    assert 'def GeomSubset "Material_1_1"' in usda_text
    assert 'def GeomSubset "Material_2_2"' in usda_text
