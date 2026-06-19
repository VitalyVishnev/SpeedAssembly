from __future__ import annotations

import argparse
import multiprocessing
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from xml_to_usda.runtime_error_mode import suppress_windows_native_error_dialogs
from xml_to_usda.worker_commands import (
    CONVERSION_WORKER_COMMAND,
    FBX_WORKER_COMMAND,
    FRACTURE_WORKER_COMMAND,
    PROXY_MESH_WORKER_COMMAND,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="XMLtoUSDAWorker")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in (
        FBX_WORKER_COMMAND,
        CONVERSION_WORKER_COMMAND,
        PROXY_MESH_WORKER_COMMAND,
        FRACTURE_WORKER_COMMAND,
    ):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--request", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    suppress_windows_native_error_dialogs()
    multiprocessing.freeze_support()
    args = build_parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.command == FBX_WORKER_COMMAND:
        from xml_to_usda.fbx_worker_subprocess import run_fbx_worker_request_file

        return run_fbx_worker_request_file(args.request)
    if args.command == CONVERSION_WORKER_COMMAND:
        from xml_to_usda.conversion_worker_subprocess import run_conversion_worker_request_file

        return run_conversion_worker_request_file(args.request)
    if args.command == PROXY_MESH_WORKER_COMMAND:
        from xml_to_usda.proxy_mesh_worker_subprocess import run_proxy_mesh_worker_request_file

        return run_proxy_mesh_worker_request_file(args.request)
    if args.command == FRACTURE_WORKER_COMMAND:
        from xml_to_usda.fracture_worker_subprocess import run_fracture_worker_request_file

        return run_fracture_worker_request_file(args.request)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
