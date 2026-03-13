from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .models import CanonicalTreeModel, ConversionRequest, ConversionResult, ObservedXmlSchemaReport, OutputMode
from .normalizer import normalize_to_canonical
from .usda_writer import render_usda
from .validator import validate_model
from .xml_reader import inspect_xml, read_source_xml


REPO_ROOT = Path(__file__).resolve().parents[2]
VAULT_ROOT = REPO_ROOT / "vault"


def inspect_source(input_path: str) -> ObservedXmlSchemaReport:
    document = read_source_xml(input_path)
    return inspect_xml(document)


def load_canonical_model(input_path: str, output_mode: OutputMode = OutputMode.SELF_CONTAINED) -> tuple[ObservedXmlSchemaReport, CanonicalTreeModel, tuple]:
    document = read_source_xml(input_path)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    metadata = replace(model.metadata, output_mode=output_mode)
    model = replace(model, metadata=metadata)
    diagnostics = validate_model(model)
    return report, model, diagnostics


def convert_file(
    input_path: str,
    output_path: str | None,
    output_mode: OutputMode = OutputMode.SELF_CONTAINED,
) -> ConversionResult:
    request = ConversionRequest(input_paths=(input_path,), output_path=output_path, output_mode=output_mode)
    return convert_request(request)[0]


def convert_request(request: ConversionRequest) -> tuple[ConversionResult, ...]:
    if not request.input_paths:
        raise ValueError("ConversionRequest requires at least one input path.")
    if request.output_path and len(request.input_paths) != 1:
        raise ValueError("Explicit output_path is only valid for single-file conversion.")

    results: list[ConversionResult] = []
    for input_path in request.input_paths:
        resolved_output = _resolve_output_path(request, input_path)
        if resolved_output is not None:
            _ensure_output_path_allowed(resolved_output)

        _, model, diagnostics = load_canonical_model(input_path, request.output_mode)
        errors = [issue for issue in diagnostics if issue.severity == "error"]
        if errors:
            results.append(
                ConversionResult(
                    input_path=input_path,
                    output_path=str(resolved_output) if resolved_output is not None else None,
                    diagnostics=diagnostics,
                    usda_document=None,
                )
            )
            continue

        usda_document = render_usda(model, diagnostics)
        if resolved_output is not None:
            resolved_output.parent.mkdir(parents=True, exist_ok=True)
            resolved_output.write_text(usda_document.text, encoding="utf-8")

        results.append(
            ConversionResult(
                input_path=input_path,
                output_path=str(resolved_output) if resolved_output is not None else None,
                diagnostics=diagnostics,
                usda_document=usda_document,
            )
        )
    return tuple(results)


def _resolve_output_path(request: ConversionRequest, input_path: str) -> Path | None:
    if request.output_path:
        return Path(request.output_path)

    if request.output_directory:
        output_dir = Path(request.output_directory)
        file_name = _render_output_file_name(Path(input_path), request.output_naming_template)
        return output_dir / file_name

    if len(request.input_paths) == 1:
        input_file = Path(input_path)
        return input_file.with_suffix(".usda")

    raise ValueError("Batch conversion requires output_directory or explicit per-file naming.")


def _render_output_file_name(input_path: Path, naming_template: str | None) -> str:
    stem = input_path.stem
    if naming_template:
        file_name = naming_template.format(stem=stem)
        if not file_name.lower().endswith(".usda"):
            file_name = f"{file_name}.usda"
        return file_name
    return f"{stem}.usda"


def _ensure_output_path_allowed(output_path: Path) -> None:
    if not VAULT_ROOT.exists():
        return
    resolved_output = output_path.resolve()
    resolved_vault = VAULT_ROOT.resolve()
    if resolved_output.is_relative_to(resolved_vault):
        raise ValueError(f"Generated outputs must not be written inside the immutable vault: {resolved_output}")
