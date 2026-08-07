"""Source and resolved assembly model loading for conversion workflows.

Layer: application/domain boundary.

This module keeps the source-normalized CanonicalTreeModel separate from the
ResolvedAssemblyModel that applies operator intent for authoring.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import time
import tempfile
from pathlib import Path

from .assembly_resolution import (
    AssemblyResolutionOptions,
    ResolutionRuntime,
    resolve_assembly_model as resolve_assembly_model_from_options,
)
from .asset_paths import normalize_unreal_asset_path
from .job_control import emit_telemetry, throw_if_cancelled
from .material_resolver import apply_material_policy as resolve_material_policy
from .models import (
    BaseMaterialOverride,
    CanonicalTreeModel,
    ConversionPhase,
    ConversionMode,
    CpuProfile,
    MaterialPolicy,
    ObservedXmlSchemaReport,
    OutputMode,
    PrototypeSourceConfig,
    ResolvedAssemblyModel,
    UdimMaterialSetting,
    ValidationIssue,
)
from .normalizer import normalize_to_canonical
from .source_validation import validate_source_model
from .skeleton_processing import apply_dual_skinning
from .worker_file_protocol import read_worker_payload, write_worker_payload_atomic
from .xml_reader import analyze_xml, read_source_xml


SOURCE_MODEL_CACHE_SCHEMA_VERSION = 9


class _InvalidSourceModelCache(Exception):
    pass


def load_source_tree_model(
    input_path: str,
    *,
    source_cache_enabled: bool = True,
    telemetry_callback=None,
    cancel_event=None,
) -> tuple[ObservedXmlSchemaReport, CanonicalTreeModel, tuple[ValidationIssue, ...]]:
    """Load one XML source into the source-normalized CanonicalTreeModel."""
    started_at = time.perf_counter()
    emit_telemetry(
        telemetry_callback,
        ConversionPhase.XML_NORMALIZATION,
        message="Reading and normalizing XML source.",
        started_at=started_at,
    )
    throw_if_cancelled(cancel_event)
    cache_path = _source_model_cache_path(input_path) if source_cache_enabled else None
    if cache_path is not None:
        cached = _read_source_model_cache(cache_path)
        if cached is not None:
            report, model, diagnostics = cached
            emit_telemetry(
                telemetry_callback,
                ConversionPhase.XML_NORMALIZATION,
                message="Reusing cached XML source model.",
                started_at=started_at,
            )
            return report, model, diagnostics

    document = read_source_xml(input_path)
    analysis = analyze_xml(document)
    report = analysis.report
    model = normalize_to_canonical(document, report, source_nodes=analysis.source_nodes)
    diagnostics = validate_source_model(model)
    if cache_path is not None:
        _write_source_model_cache(cache_path, (report, model, diagnostics))
    return report, model, diagnostics


def resolve_assembly_model(
    source_model: CanonicalTreeModel,
    *,
    output_mode: OutputMode = OutputMode.SELF_CONTAINED,
    material_policy: MaterialPolicy = MaterialPolicy.SOURCE_MATERIALS,
    bark_material_path: str | None = None,
    leaves_material_path: str | None = None,
    single_material_path: str | None = None,
    base_material_overrides: tuple[BaseMaterialOverride, ...] = (),
    udim_material_settings: tuple[UdimMaterialSetting, ...] = (),
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
    use_explicit_material_contract: bool = False,
    prototype_source_configs: tuple[PrototypeSourceConfig, ...] = (),
    conversion_mode: ConversionMode | str = ConversionMode.SKELETAL_ASSEMBLY,
    output_stem: str | None = None,
    fbx_cache_max_bytes: int = 20 * 1024 * 1024 * 1024,
    fbx_cache_max_age_seconds: int = 14 * 24 * 60 * 60,
    source_diagnostics: tuple[ValidationIssue, ...] | None = None,
    telemetry_callback=None,
    cancel_event=None,
) -> ResolvedAssemblyModel:
    """Compatibility wrapper over the Assembly Resolution Module."""
    return resolve_assembly_model_from_options(
        source_model,
        AssemblyResolutionOptions(
            output_mode=output_mode,
            material_policy=material_policy,
            bark_material_path=bark_material_path,
            leaves_material_path=leaves_material_path,
            single_material_path=single_material_path,
            base_material_overrides=base_material_overrides,
            udim_material_settings=udim_material_settings,
            cpu_profile=cpu_profile,
            use_explicit_material_contract=use_explicit_material_contract,
            prototype_source_configs=prototype_source_configs,
            conversion_mode=conversion_mode,
            output_stem=output_stem,
            fbx_cache_max_bytes=fbx_cache_max_bytes,
            fbx_cache_max_age_seconds=fbx_cache_max_age_seconds,
        ),
        source_diagnostics=source_diagnostics,
        runtime=ResolutionRuntime(
            telemetry_callback=telemetry_callback,
            cancel_event=cancel_event,
        ),
    )


def load_resolved_assembly_model(
    input_path: str,
    output_mode: OutputMode = OutputMode.SELF_CONTAINED,
    material_policy: MaterialPolicy = MaterialPolicy.SOURCE_MATERIALS,
    bark_material_path: str | None = None,
    leaves_material_path: str | None = None,
    single_material_path: str | None = None,
    base_material_overrides: tuple[BaseMaterialOverride, ...] = (),
    udim_material_settings: tuple[UdimMaterialSetting, ...] = (),
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
    use_explicit_material_contract: bool = False,
    prototype_source_configs: tuple[PrototypeSourceConfig, ...] = (),
    conversion_mode: ConversionMode | str = ConversionMode.SKELETAL_ASSEMBLY,
    dual_skinning: bool = True,
    output_stem: str | None = None,
    fbx_cache_max_bytes: int = 20 * 1024 * 1024 * 1024,
    fbx_cache_max_age_seconds: int = 14 * 24 * 60 * 60,
    source_cache_enabled: bool = True,
    telemetry_callback=None,
    cancel_event=None,
) -> tuple[ObservedXmlSchemaReport, ResolvedAssemblyModel]:
    """Load XML source facts and resolve them into authoring-ready state."""
    report, source_model, source_diagnostics = load_source_tree_model(
        input_path,
        source_cache_enabled=source_cache_enabled,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
    )
    if dual_skinning:
        source_model = apply_dual_skinning(source_model)
        source_diagnostics = validate_source_model(source_model)
    resolved = resolve_assembly_model(
        source_model,
        output_mode=output_mode,
        material_policy=material_policy,
        bark_material_path=bark_material_path,
        leaves_material_path=leaves_material_path,
        single_material_path=single_material_path,
        base_material_overrides=base_material_overrides,
        udim_material_settings=udim_material_settings,
        cpu_profile=cpu_profile,
        use_explicit_material_contract=use_explicit_material_contract,
        prototype_source_configs=prototype_source_configs,
        conversion_mode=conversion_mode,
        output_stem=output_stem,
        fbx_cache_max_bytes=fbx_cache_max_bytes,
        fbx_cache_max_age_seconds=fbx_cache_max_age_seconds,
        source_diagnostics=source_diagnostics,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
    )
    return report, resolved


def load_canonical_model(
    input_path: str,
    output_mode: OutputMode = OutputMode.SELF_CONTAINED,
    material_policy: MaterialPolicy = MaterialPolicy.SOURCE_MATERIALS,
    bark_material_path: str | None = None,
    leaves_material_path: str | None = None,
    single_material_path: str | None = None,
    base_material_overrides: tuple[BaseMaterialOverride, ...] = (),
    udim_material_settings: tuple[UdimMaterialSetting, ...] = (),
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
    use_explicit_material_contract: bool = False,
    prototype_source_configs: tuple[PrototypeSourceConfig, ...] = (),
    conversion_mode: ConversionMode | str = ConversionMode.SKELETAL_ASSEMBLY,
    dual_skinning: bool = True,
    fbx_cache_max_bytes: int = 20 * 1024 * 1024 * 1024,
    fbx_cache_max_age_seconds: int = 14 * 24 * 60 * 60,
    source_cache_enabled: bool = True,
    telemetry_callback=None,
    cancel_event=None,
) -> tuple[ObservedXmlSchemaReport, CanonicalTreeModel, tuple[ValidationIssue, ...]]:
    """Compatibility wrapper returning the resolved authoring model."""
    report, resolved = load_resolved_assembly_model(
        input_path,
        output_mode=output_mode,
        material_policy=material_policy,
        bark_material_path=bark_material_path,
        leaves_material_path=leaves_material_path,
        single_material_path=single_material_path,
        base_material_overrides=base_material_overrides,
        udim_material_settings=udim_material_settings,
        cpu_profile=cpu_profile,
        use_explicit_material_contract=use_explicit_material_contract,
        prototype_source_configs=prototype_source_configs,
        conversion_mode=conversion_mode,
        dual_skinning=dual_skinning,
        fbx_cache_max_bytes=fbx_cache_max_bytes,
        fbx_cache_max_age_seconds=fbx_cache_max_age_seconds,
        source_cache_enabled=source_cache_enabled,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
    )
    return report, resolved.authoring_model, resolved.diagnostics


def _apply_material_policy(
    model: CanonicalTreeModel,
    material_policy: MaterialPolicy,
    bark_material_path: str | None,
    leaves_material_path: str | None,
    single_material_path: str | None,
) -> CanonicalTreeModel:
    """Compatibility helper retained for callers that still import it via `pipeline`."""
    return resolve_material_policy(
        model,
        material_policy=material_policy,
        bark_material_path=bark_material_path,
        leaves_material_path=leaves_material_path,
        single_material_path=single_material_path,
        normalize_asset_path=normalize_unreal_asset_path,
    )


def _source_model_cache_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    candidate = Path(local_app_data) / "XMLtoUSDAConverter" / "cache" / "source_models" if local_app_data else None
    fallback = Path(tempfile.gettempdir()) / "XMLtoUSDAConverter" / "cache" / "source_models"
    for root in (candidate, fallback):
        if root is None:
            continue
        try:
            root.mkdir(parents=True, exist_ok=True)
            return root
        except OSError:
            continue
    return fallback


def _source_model_cache_path(input_path: str) -> Path:
    xml_path = Path(input_path)
    try:
        stat_result = xml_path.stat()
    except OSError:
        return _source_model_cache_root() / "unavailable.json"
    signature = "|".join(
        (
            str(SOURCE_MODEL_CACHE_SCHEMA_VERSION),
            _source_model_cache_parser_key(),
            os.path.normcase(str(xml_path.resolve(strict=False))),
            str(stat_result.st_size),
            str(stat_result.st_mtime_ns),
        )
    )
    cache_key = hashlib.sha256(signature.encode("utf-8")).hexdigest()
    return _source_model_cache_root() / f"{cache_key}.json"


def _source_model_cache_parser_key() -> str:
    from .xml_reader import packaged_xml_parser_adapter_enabled

    parser = "packaged-et-explicit" if packaged_xml_parser_adapter_enabled() else "defused"
    return f"{parser}-normals-v1"


def _read_source_model_cache(cache_path: Path):
    try:
        payload = read_worker_payload(cache_path)
    except FileNotFoundError:
        return None
    except Exception:
        with contextlib.suppress(Exception):
            cache_path.unlink(missing_ok=True)
        return None
    if not isinstance(payload, tuple) or len(payload) != 3:
        with contextlib.suppress(Exception):
            cache_path.unlink(missing_ok=True)
        return None
    report, model, diagnostics = payload
    if not isinstance(report, ObservedXmlSchemaReport):
        with contextlib.suppress(Exception):
            cache_path.unlink(missing_ok=True)
        return None
    if not isinstance(model, CanonicalTreeModel):
        with contextlib.suppress(Exception):
            cache_path.unlink(missing_ok=True)
        return None
    if not isinstance(diagnostics, tuple):
        with contextlib.suppress(Exception):
            cache_path.unlink(missing_ok=True)
        return None
    return report, model, diagnostics


def _write_source_model_cache(cache_path: Path, payload: tuple[ObservedXmlSchemaReport, CanonicalTreeModel, tuple[ValidationIssue, ...]]) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        write_worker_payload_atomic(cache_path, payload)
    except Exception:
        with contextlib.suppress(Exception):
            cache_path.unlink(missing_ok=True)
