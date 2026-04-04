from __future__ import annotations

import time
from pathlib import Path

from .job_control import emit_telemetry
from .models import ConversionPhase, ExportStats, UsdAssemblyDocument, ValidationIssue
from .ue_schema import DEFAULT_UE_SCHEMA_CONTRACT, UeSchemaContract
from .usda_authoring import (
    author_usda_stream,
    author_usda_text,
    build_authoring_context,
    model_requires_streaming_writer,
)


def render_usda(
    model,
    diagnostics: tuple[ValidationIssue, ...],
    contract: UeSchemaContract = DEFAULT_UE_SCHEMA_CONTRACT,
    base_mesh_name: str | None = None,
) -> UsdAssemblyDocument:
    context = build_authoring_context(
        model,
        diagnostics,
        contract=contract,
        base_mesh_name=base_mesh_name,
    )
    text = author_usda_text(context)
    return UsdAssemblyDocument(text=text, diagnostics=diagnostics, stats=ExportStats(streamed=False))


def write_usda_document(
    model,
    diagnostics: tuple[ValidationIssue, ...],
    *,
    output_path: Path | None,
    contract: UeSchemaContract = DEFAULT_UE_SCHEMA_CONTRACT,
    base_mesh_name: str | None = None,
    telemetry_callback=None,
    cancel_event=None,
) -> UsdAssemblyDocument:
    context = build_authoring_context(
        model,
        diagnostics,
        contract=contract,
        base_mesh_name=base_mesh_name,
    )
    if output_path is None or not model_requires_streaming_writer(model):
        text = author_usda_text(context)
        document = UsdAssemblyDocument(text=text, diagnostics=diagnostics, stats=ExportStats(streamed=False))
        if output_path is None:
            return document
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
        stats = ExportStats(
            bytes_written=output_path.stat().st_size if output_path.exists() else 0,
            duration_seconds=0.0,
            streamed=False,
        )
        return UsdAssemblyDocument(text=text, diagnostics=diagnostics, stats=stats)

    started_at = time.perf_counter()
    emit_telemetry(
        telemetry_callback,
        ConversionPhase.USDA_WRITING,
        message="Streaming USDA to disk.",
        started_at=started_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output_path.with_name(f"{output_path.name}.partial")
    if temp_output.exists():
        temp_output.unlink()
    try:
        with temp_output.open("w", encoding="utf-8", buffering=1024 * 1024) as handle:
            author_usda_stream(
                handle,
                context,
                telemetry_callback=telemetry_callback,
                cancel_event=cancel_event,
                started_at=started_at,
            )
        temp_output.replace(output_path)
        stats = ExportStats(
            bytes_written=output_path.stat().st_size if output_path.exists() else 0,
            duration_seconds=max(0.0, time.perf_counter() - started_at),
            streamed=True,
        )
        emit_telemetry(
            telemetry_callback,
            ConversionPhase.COMPLETED,
            message="USDA export completed.",
            output_bytes_written=stats.bytes_written,
            started_at=started_at,
        )
        return UsdAssemblyDocument(text=None, diagnostics=diagnostics, stats=stats)
    except Exception:
        if temp_output.exists():
            temp_output.unlink()
        raise
