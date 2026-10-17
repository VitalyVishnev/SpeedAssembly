"""Check real frozen discovery workers against the source result, including IPC."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(PROJECT / 'src'))


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--input', type=Path, action='append', required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    (runtime / 'temp').mkdir(parents=True, exist_ok=True)
    os.environ['LOCALAPPDATA'] = str(runtime / 'local')
    os.environ['TMP'] = os.environ['TEMP'] = str(runtime / 'temp')
    from xml_to_usda import conversion_process as workers
    from xml_to_usda.discovery_service import SourceDiscoveryRequest, discover_source_rows

    workers.resolve_worker_command = lambda command, request: [
        str(args.exe.resolve()), command, '--request', str(request)]
    rows = []
    for path in args.input:
        request = SourceDiscoveryRequest(str(path.resolve()))
        started = time.perf_counter()
        process, queue, cancel = workers.start_source_discovery_process(request)
        result = None
        try:
            while time.perf_counter() - started < 120:
                for kind, payload in workers.drain_process_queue(queue):
                    if kind.startswith('error'):
                        raise RuntimeError(str(payload))
                    if kind == 'result':
                        result = payload
                if result is not None:
                    break
                if not process.is_alive():
                    raise RuntimeError(f'Frozen discovery exited without a result: {process.exitcode}')
                time.sleep(0.01)
            elapsed = time.perf_counter() - started
            assert result is not None, 'Frozen discovery timed out'
            process.join(15)
            assert process.exitcode == 0, process.exitcode
            assert result == discover_source_rows(request), path
            rows.append(dict(input=str(path), seconds=elapsed,
                             joints=result.skeleton_joint_count,
                             instances=result.scattered_parts.instance_count,
                             eligible=result.scattered_parts.eligible,
                             clusters=result.scattered_parts.cluster_count))
        finally:
            if process.is_alive():
                cancel.set()
                process.join(5)
            workers.close_process_queue(queue)
    assert not list(runtime.rglob('source_models/*.json')), 'Discovery created a model cache'
    exe_hash = hashlib.sha256(args.exe.read_bytes()).hexdigest()
    report = dict(passed=True, exe_sha256=exe_hash, cases=rows)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
