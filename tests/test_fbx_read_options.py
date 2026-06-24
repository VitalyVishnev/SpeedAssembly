from __future__ import annotations

from array import array
from pathlib import Path

from xml_to_usda.fbx_payload_cache import FbxPayloadCacheResult
from xml_to_usda.models import (
    CpuProfile,
    FbxMaterialMode,
    GeometryBuffer,
    Prototype,
    PrototypeIdentity,
    PrototypeSourceConfig,
    PrototypeSourceMode,
)
from xml_to_usda.prototype_resolution import _PreparedFbxImport
from xml_to_usda.prototype_sources import load_fbx_payloads_for_prototype_resolution
from xml_to_usda.fbx_worker_subprocess import (
    FbxWorkerRequest,
    read_fbx_worker_request,
    run_fbx_worker_request_file,
    write_fbx_worker_request,
)


def _prepared_import(tmp_path: Path, mode: FbxMaterialMode) -> _PreparedFbxImport:
    fbx_path = tmp_path / f"{mode.value}.fbx"
    fbx_path.write_bytes(b"fbx")
    identity = PrototypeIdentity(source_key="Mesh_1", prim_name="Branch")
    prototype = Prototype(
        identity=identity,
        mesh=None,
        source_key="Mesh_1",
        source_mesh_id=1,
        source_name="Branch",
    )
    return _PreparedFbxImport(
        prototype_index=0,
        original_prototype=prototype,
        config=PrototypeSourceConfig(
            source_key="Mesh_1",
            source_name="Branch",
            mode=PrototypeSourceMode.FBX_FILE,
            fbx_material_mode=mode,
            fbx_path=str(fbx_path),
        ),
        resolved_identity=identity,
        resolved_source_name="Branch",
    )


def test_fbx_single_material_import_skips_vertex_colors_and_material_slots(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import xml_to_usda.prototype_sources as prototype_sources_module

    observed = []
    monkeypatch.setattr(
        prototype_sources_module,
        "import_fbx_payloads",
        lambda tasks, **_kwargs: observed.extend(tasks) or {},
    )

    load_fbx_payloads_for_prototype_resolution(
        (_prepared_import(tmp_path, FbxMaterialMode.SINGLE_MATERIAL),),
        cpu_profile=CpuProfile.BALANCED,
    )

    assert observed[0].read_vertex_colors is False
    assert observed[0].read_material_slots is False
    assert observed[0].strict_vertex_colors is False


def test_fbx_material_slots_import_reads_slots_without_vertex_colors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import xml_to_usda.prototype_sources as prototype_sources_module

    observed = []
    monkeypatch.setattr(
        prototype_sources_module,
        "import_fbx_payloads",
        lambda tasks, **_kwargs: observed.extend(tasks) or {},
    )

    load_fbx_payloads_for_prototype_resolution(
        (_prepared_import(tmp_path, FbxMaterialMode.MATERIAL_SLOTS),),
        cpu_profile=CpuProfile.BALANCED,
    )

    assert observed[0].read_vertex_colors is False
    assert observed[0].read_material_slots is True
    assert observed[0].strict_vertex_colors is False


def test_fbx_vertex_color_split_import_reads_vertex_colors_without_slots(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import xml_to_usda.prototype_sources as prototype_sources_module

    observed = []
    monkeypatch.setattr(
        prototype_sources_module,
        "import_fbx_payloads",
        lambda tasks, **_kwargs: observed.extend(tasks) or {},
    )

    load_fbx_payloads_for_prototype_resolution(
        (_prepared_import(tmp_path, FbxMaterialMode.VERTEX_COLOR_SPLIT),),
        cpu_profile=CpuProfile.BALANCED,
    )

    assert observed[0].read_vertex_colors is True
    assert observed[0].read_material_slots is False
    assert observed[0].strict_vertex_colors is True


def test_fbx_cache_policy_is_attached_to_import_tasks(tmp_path: Path, monkeypatch) -> None:
    import xml_to_usda.prototype_sources as prototype_sources_module

    observed = []
    monkeypatch.setattr(
        prototype_sources_module,
        "import_fbx_payloads",
        lambda tasks, **_kwargs: observed.extend(tasks) or {},
    )

    load_fbx_payloads_for_prototype_resolution(
        (_prepared_import(tmp_path, FbxMaterialMode.SINGLE_MATERIAL),),
        cpu_profile=CpuProfile.BALANCED,
        fbx_cache_max_bytes=1234,
        fbx_cache_max_age_seconds=5678,
    )

    assert observed[0].fbx_cache_max_bytes == 1234
    assert observed[0].fbx_cache_max_age_seconds == 5678


def test_fbx_worker_request_round_trips_cache_policy(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    request = FbxWorkerRequest(
        fbx_path="branch.fbx",
        prototype_name="Branch",
        cpu_profile=CpuProfile.BALANCED,
        strict_vertex_colors=False,
        read_vertex_colors=False,
        read_material_slots=False,
        fbx_cache_max_bytes=1234,
        fbx_cache_max_age_seconds=5678,
        result_path="result.json",
        error_path="error.json",
    )

    write_fbx_worker_request(request_path, request)

    assert read_fbx_worker_request(request_path) == request


def test_fbx_worker_passes_cache_policy_to_store(tmp_path: Path, monkeypatch) -> None:
    import xml_to_usda.fbx_worker_subprocess as worker_module

    result_path = tmp_path / "result.json"
    error_path = tmp_path / "error.json"
    request_path = tmp_path / "request.json"
    observed_store_kwargs = {}
    payload = GeometryBuffer(
        name="Branch",
        point_components=array("f", [0.0, 0.0, 0.0]),
        face_vertex_counts=array("i"),
        face_vertex_indices=array("i"),
    )

    monkeypatch.setattr(worker_module, "load_fbx_payload_from_cache", lambda *_args, **_kwargs: FbxPayloadCacheResult(None, hit=False))
    monkeypatch.setattr(worker_module, "load_fbx_geometry", lambda *_args, **_kwargs: payload)
    monkeypatch.setattr(
        worker_module,
        "store_fbx_payload_in_cache",
        lambda *_args, **kwargs: observed_store_kwargs.update(kwargs),
    )
    write_fbx_worker_request(
        request_path,
        FbxWorkerRequest(
            fbx_path=str(tmp_path / "branch.fbx"),
            prototype_name="Branch",
            cpu_profile=CpuProfile.BALANCED,
            strict_vertex_colors=False,
            fbx_cache_max_bytes=1234,
            fbx_cache_max_age_seconds=5678,
            result_path=str(result_path),
            error_path=str(error_path),
        ),
    )

    assert run_fbx_worker_request_file(request_path) == 0
    assert observed_store_kwargs["max_bytes"] == 1234
    assert observed_store_kwargs["max_age_seconds"] == 5678
