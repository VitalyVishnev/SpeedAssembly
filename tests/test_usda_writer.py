from __future__ import annotations

import json
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from xml_to_usda.canonical_loader import load_canonical_model
from xml_to_usda.job_control import ConversionCancelledError
from xml_to_usda.models import (
    MeshData,
    MeshLibraryEntry,
    PrototypeSourceConfig,
    PrototypeSourceMode,
    Vector3,
)
from xml_to_usda.normalizer import _mesh_with_original_scale
from xml_to_usda.usda_authoring import author_usda_stream, author_usda_text, build_authoring_context
from xml_to_usda.usda_writer import render_usda, write_usda_document


SIMPLE_TREE_01 = (
    Path(__file__).resolve().parents[1]
    / "samples"
    / "speedtree"
    / "simple_tree"
    / "variants"
    / "SimpleTree_01.xml"
)


def _write_fbx_json_payload(tmp_path: Path, *, file_name: str = "prototype_payload.json") -> Path:
    payload = {
        "point_components": [0.0, 0.0, 0.0, 1.0, 0.0, 0.0],
        "face_vertex_counts": [3, 3],
        "face_vertex_indices": [0, 1, 2, 3, 4, 5],
        "uv_components": [0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0],
        "vertex_color_components": [
            0.0, 0.0, 0.0, 1.0,
            0.0, 0.0, 0.0, 1.0,
            0.0, 0.0, 0.0, 1.0,
            1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 1.0,
        ],
    }
    payload_path = tmp_path / file_name
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    return payload_path


def _normalize_usda_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))


def test_write_usda_document_matches_render_usda_for_baseline_model(tmp_path: Path) -> None:
    _, model, diagnostics = load_canonical_model(str(SIMPLE_TREE_01))
    output_path = tmp_path / "baseline_rendered.usda"

    rendered = render_usda(model, diagnostics, base_mesh_name=output_path.stem)
    written = write_usda_document(
        model,
        diagnostics,
        output_path=output_path,
        base_mesh_name=output_path.stem,
    )

    assert rendered.text is not None
    assert written.text == rendered.text
    assert written.stats.streamed is False
    assert output_path.exists()
    assert _normalize_usda_text(output_path.read_text(encoding="utf-8")) == _normalize_usda_text(rendered.text)


def test_streaming_writer_matches_rendered_usda_logically_for_small_fbx_payload(tmp_path: Path) -> None:
    payload_path = _write_fbx_json_payload(tmp_path, file_name="stage0_stream_payload.json")
    output_path = tmp_path / "streaming_parity.usda"
    _, model, diagnostics = load_canonical_model(
        str(SIMPLE_TREE_01),
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path=str(payload_path),
            ),
        ),
    )

    rendered = render_usda(model, diagnostics, base_mesh_name=output_path.stem)
    written = write_usda_document(
        model,
        diagnostics,
        output_path=output_path,
        base_mesh_name=output_path.stem,
    )

    assert rendered.text is not None
    assert written.text is None
    assert written.stats.streamed is True
    assert output_path.exists()
    assert _normalize_usda_text(output_path.read_text(encoding="utf-8")) == _normalize_usda_text(rendered.text)


def test_authoring_engine_matches_text_and_file_sinks_for_baseline_model(tmp_path: Path) -> None:
    _, model, diagnostics = load_canonical_model(str(SIMPLE_TREE_01))
    context = build_authoring_context(model, diagnostics, base_mesh_name="UnifiedBaseline")

    text_output = author_usda_text(context)
    output_path = tmp_path / "authoring_engine_baseline.usda"
    with output_path.open("w", encoding="utf-8") as handle:
        author_usda_stream(handle, context)

    assert _normalize_usda_text(output_path.read_text(encoding="utf-8")) == _normalize_usda_text(text_output)


def test_authoring_engine_matches_text_and_file_sinks_for_external_asset_prototypes(tmp_path: Path) -> None:
    _, model, diagnostics = load_canonical_model(
        str(SIMPLE_TREE_01),
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                mode=PrototypeSourceMode.UNREAL_ASSET,
                asset_path="/Game/TreeParts/SK_Twig01.SK_Twig01",
            ),
        ),
    )
    context = build_authoring_context(model, diagnostics, base_mesh_name="UnifiedExternal")

    text_output = author_usda_text(context)
    output_path = tmp_path / "authoring_engine_external.usda"
    with output_path.open("w", encoding="utf-8") as handle:
        author_usda_stream(handle, context)

    assert _normalize_usda_text(output_path.read_text(encoding="utf-8")) == _normalize_usda_text(text_output)


def test_authoring_engine_rejects_invalid_unreal_material_path() -> None:
    _, model, diagnostics = load_canonical_model(
        str(SIMPLE_TREE_01),
        material_policy="single_material",
        single_material_path="/Game/Assembly/SimpleTree/Leaves1.Leaves1",
    )
    bad_material = replace(model.materials[0], ue_asset_path='/Game/Assembly/Bad"\nInjected.Injected')
    context = build_authoring_context(replace(model, materials=(bad_material,)), diagnostics, base_mesh_name="BadMaterial")

    with pytest.raises(ValueError, match="Invalid Unreal Asset Path"):
        author_usda_text(context)


def test_authoring_engine_rejects_invalid_external_prototype_asset_path() -> None:
    _, model, diagnostics = load_canonical_model(
        str(SIMPLE_TREE_01),
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                mode=PrototypeSourceMode.UNREAL_ASSET,
                asset_path="/Game/TreeParts/SK_Twig01.SK_Twig01",
            ),
        ),
    )
    bad_prototype = replace(model.prototypes[0], mesh_asset_path="/Game/TreeParts/@Injected.Injected")
    context = build_authoring_context(replace(model, prototypes=(bad_prototype,) + model.prototypes[1:]), diagnostics)

    with pytest.raises(ValueError, match="Invalid Unreal Asset Path"):
        author_usda_text(context)


def test_mesh_with_original_scale_reports_invalid_point_payloads() -> None:
    entry = replace(
        MeshLibraryEntry(
            mesh_id=7,
            name="BrokenPrototype",
            mesh=MeshData(
                name="BrokenPrototype",
                points=(Vector3,),
                face_vertex_counts=(),
                face_vertex_indices=(),
            ),
            original_scale=2.0,
        ),
    )

    with pytest.raises(TypeError, match="BrokenPrototype"):
        _mesh_with_original_scale(entry)


def test_streaming_writer_cleans_partial_file_on_cancel(tmp_path: Path) -> None:
    payload_path = _write_fbx_json_payload(tmp_path)
    output_path = tmp_path / "cancelled_stream.usda"
    _, model, diagnostics = load_canonical_model(
        str(SIMPLE_TREE_01),
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                source_name="Twig_01",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path=str(payload_path),
            ),
        ),
    )
    cancel_event = threading.Event()
    cancel_event.set()

    with pytest.raises(ConversionCancelledError, match="cancelled"):
        write_usda_document(
            model,
            diagnostics,
            output_path=output_path,
            cancel_event=cancel_event,
        )

    assert not output_path.exists()
    assert not output_path.with_name("cancelled_stream.usda.partial").exists()
