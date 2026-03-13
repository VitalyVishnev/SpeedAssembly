from __future__ import annotations

import argparse
import sys

from .pipeline import convert_file, inspect_source
from .xml_reader import render_inspect_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xml-to-usda")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect observed XML schema.")
    inspect_parser.add_argument("input", help="Path to the source XML file.")

    convert_parser = subparsers.add_parser("convert", help="Convert XML to USDA.")
    convert_parser.add_argument("input", help="Path to the source XML file.")
    convert_parser.add_argument("output", help="Path to the output USDA file.")

    subparsers.add_parser("gui", help="Launch the desktop GUI.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "inspect":
            return _run_inspect(args.input)
        if args.command == "convert":
            return _run_convert(args.input, args.output)
        if args.command == "gui":
            from .gui import main as gui_main

            return gui_main()
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2

    parser.error(f"Unsupported command: {args.command}")
    return 2


def _run_inspect(input_path: str) -> int:
    report = inspect_source(input_path)
    sys.stdout.write(render_inspect_report(report) + "\n")
    return 0


def _run_convert(input_path: str, output_path: str) -> int:
    result = convert_file(input_path, output_path)
    for issue in result.diagnostics:
        _print_issue(issue)
    if result.usda_document is None:
        return 1
    sys.stdout.write(f"Wrote USDA to {result.output_path}\n")
    return 0


def _print_issue(issue) -> None:
    sys.stderr.write(f"[{issue.severity}] {issue.code}: {issue.message}\n")


if __name__ == "__main__":
    raise SystemExit(main())
