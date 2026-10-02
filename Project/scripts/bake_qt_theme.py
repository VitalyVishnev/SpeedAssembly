from __future__ import annotations

import argparse
from pathlib import Path

from xml_to_usda.qt_ui.theme import bake_theme_payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bake an exported Qt UI theme snapshot into the bundled default theme.")
    parser.add_argument("--snapshot", required=True, help="Path to the exported merged theme JSON.")
    parser.add_argument(
        "--target",
        default="src/xml_to_usda/qt_ui/themes/default/theme.json",
        help="Bundled theme.json path to overwrite.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    snapshot_path = Path(args.snapshot).resolve()
    target_path = Path(args.target).resolve()
    bake_theme_payload(snapshot_path=snapshot_path, target_theme_path=target_path)
    print(f"Baked theme snapshot {snapshot_path} -> {target_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
