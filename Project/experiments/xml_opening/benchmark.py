"""Measure discovery and Wind preparation in a fresh process, with isolated caches.

Run with .venv310 Python. OS file caches are deliberately left warm.
"""
from __future__ import annotations

import argparse
import cProfile
import ctypes
import dataclasses
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(PROJECT / 'src'))


def peak_working_set():
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [(key, ctypes.c_size_t) for key in (
            'peak', 'working', 'peak_paged', 'paged', 'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile', 'private')]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.peak / (1024 * 1024)


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--variant', choices=('baseline', 'candidate'), required=True)
    parser.add_argument('--cache', choices=('off', 'enabled'), default='off')
    parser.add_argument('--cache-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--parser', choices=('source', 'packaged'), default='source')
    args = parser.parse_args()
    args.cache_root.mkdir(parents=True, exist_ok=True)
    os.environ['LOCALAPPDATA'] = str(args.cache_root.resolve())
    from xml_to_usda import canonical_loader, discovery_service, wind_pipeline
    if args.parser == 'packaged':
        from xml_to_usda import xml_reader
        xml_reader._use_packaged_xml_parser_adapter = lambda: True

    timings = {}
    if args.cache == 'off':
        canonical_loader._source_model_cache_path = lambda _path: None
    if args.variant == 'baseline':
        spec = importlib.util.spec_from_file_location(
            'xml_to_usda._opening_baseline', PROJECT / 'tmp/xml-opening/baseline_discovery.py')
        discovery_service = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = discovery_service
        spec.loader.exec_module(discovery_service)
    for owner in (canonical_loader, discovery_service):
        for name in ('read_source_xml', 'analyze_xml', 'normalize_to_canonical',
                     '_read_source_model_cache', '_write_source_model_cache'):
            if not hasattr(owner, name):
                continue
            original = getattr(owner, name)
            def timed(*values, _fn=original, _name=name, **kwargs):
                start = time.perf_counter()
                try:
                    return _fn(*values, **kwargs)
                finally:
                    timings[_name] = timings.get(_name, 0) + time.perf_counter() - start
            setattr(owner, name, timed)

    profiler = cProfile.Profile() if args.profile else None
    if profiler:
        profiler.enable()
    start = time.perf_counter()
    result = discovery_service.discover_source_rows(
        discovery_service.SourceDiscoveryRequest(str(args.input.resolve())))
    discovery_seconds = time.perf_counter() - start
    start = time.perf_counter()
    wind = wind_pipeline.inspect_wind_data(str(args.input.resolve()))
    wind_seconds = time.perf_counter() - start
    if profiler:
        profiler.disable()
        profiler.dump_stats(str(args.output.with_suffix('.prof')))
    data = dataclasses.asdict(result)
    # A valid authored skeleton alone excludes Scattered Parts. The UI does not
    # expose which of two simultaneous exclusion reasons was chosen.
    if result.skeleton_joint_count:
        data['scattered_parts']['reason'] = 'skeleton is present'
    signature = hashlib.sha256(json.dumps(
        [data, dataclasses.asdict(wind)], sort_keys=True, default=str).encode()).hexdigest()
    row = dict(input=str(args.input), bytes=args.input.stat().st_size,
               variant=args.variant, cache=args.cache, parser=args.parser, discovery=discovery_seconds,
               wind=wind_seconds, total=discovery_seconds + wind_seconds,
               peak_mib=peak_working_set(), stages=timings, signature=signature,
               skeleton=result.skeleton_joint_count, instances=result.scattered_parts.instance_count)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(row, indent=2), encoding='utf-8')
    print(json.dumps(row))


if __name__ == '__main__':
    main()
