"""Minimal dedicated entrypoint for packaged FBX helper workers.

Layer: infrastructure.

This module intentionally bypasses the broader CLI and GUI startup flow. FBX
helper processes only need to parse a request-file argument and hand it to the
file-based worker protocol in `fbx_worker_subprocess`.
"""

from __future__ import annotations

import argparse

from .fbx_worker_subprocess import FBX_WORKER_COMMAND, run_fbx_worker_request_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=FBX_WORKER_COMMAND)
    parser.add_argument("--request", required=True, help="Path to the serialized FBX helper request file.")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or [])
    if argv and argv[0] == FBX_WORKER_COMMAND:
        argv = argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    return run_fbx_worker_request_file(args.request)
