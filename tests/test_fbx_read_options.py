from __future__ import annotations

from pathlib import Path

from xml_to_usda.models import (
    CpuProfile,
    FbxMaterialMode,
    Prototype,
    PrototypeIdentity,
    PrototypeSourceConfig,
    PrototypeSourceMode,
)
from xml_to_usda.prototype_resolution import _PreparedFbxImport
from xml_to_usda.prototype_sources import load_fbx_payloads_for_prototype_resolution


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
