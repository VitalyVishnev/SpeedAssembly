from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .normalizer import normalize_to_canonical
from .usda_writer import render_usda
from .validator import validate_model
from .xml_reader import inspect_xml, read_source_xml, render_inspect_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xml-to-usda")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect observed XML schema.")
    inspect_parser.add_argument("input", help="Path to the source XML file.")

    convert_parser = subparsers.add_parser("convert", help="Convert XML to USDA.")
    convert_parser.add_argument("input", help="Path to the source XML file.")
    convert_parser.add_argument("output", help="Path to the output USDA file.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "inspect":
        return _run_inspect(args.input)
    if args.command == "convert":
        return _run_convert(args.input, args.output)

    parser.error(f"Unsupported command: {args.command}")
    return 2


def _run_inspect(input_path: str) -> int:
    document = read_source_xml(input_path)
    report = inspect_xml(document)
    sys.stdout.write(render_inspect_report(report) + "\n")
    return 0


def _run_convert(input_path: str, output_path: str) -> int:
    document = read_source_xml(input_path)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)
    diagnostics = validate_model(model)

    errors = [issue for issue in diagnostics if issue.severity == "error"]
    if errors:
        for issue in diagnostics:
            _print_issue(issue)
        return 1

    usda_document = render_usda(model, diagnostics)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(usda_document.text, encoding="utf-8")

    for issue in diagnostics:
        _print_issue(issue)
    sys.stdout.write(f"Wrote USDA to {output}\n")
    return 0


def _print_issue(issue) -> None:
    sys.stderr.write(f"[{issue.severity}] {issue.code}: {issue.message}\n")


if __name__ == "__main__":
    raise SystemExit(main())
