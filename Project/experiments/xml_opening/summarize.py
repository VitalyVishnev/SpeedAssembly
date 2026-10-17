"""Assert source-fact parity and summarize accepted, unprofiled measurements."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent
RESULTS = HERE / 'results'
PROJECT = HERE.parents[1]


def main():
    groups = defaultdict(list)
    signatures = defaultdict(set)
    inputs = {}
    count = 0
    for path in sorted(RESULTS.glob('*.json')):
        if not (path.stem.endswith(('-1', '-2', '-3')) or path.stem.startswith(
                ('GrassOnlyLeaves_', 'SK_Norway_'))):
            continue
        if path.stem == 'ui-spruce-candidate-1':  # untimed-method pilot
            continue
        row = json.loads(path.read_text(encoding='utf-8'))
        kind = 'qt' if path.stem.startswith('ui-') else 'service'
        source = Path(row['input']).resolve()
        if 'signature' in row:
            signatures[str(source)].add(row['signature'])
        cache = row['cache']
        if cache == 'enabled':
            cache = 'cold' if path.stem.endswith('-1') else 'warm'
        key = (kind, source.name, row.get('parser', 'source'), row['variant'], cache)
        groups[key].append(row)
        if str(source) not in inputs:
            inputs[str(source)] = dict(bytes=source.stat().st_size,
                                      sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        count += 1
    assert len(signatures) == 6, signatures.keys()
    assert all(len(values) == 1 for values in signatures.values()), signatures
    summary = []
    for key, rows in sorted(groups.items()):
        values = {}
        for field in ('discovery', 'wind', 'total', 'peak_mib', 'rows', 'ready'):
            if field in rows[0]:
                samples = [row[field] for row in rows]
                values[field] = dict(median=statistics.median(samples),
                                     min=min(samples), max=max(samples))
        summary.append(dict(kind=key[0], input=key[1], parser=key[2],
                            variant=key[3], cache=key[4], n=len(rows), values=values))
    report = dict(accepted_runs=count, parity_inputs=len(signatures), inputs=inputs, groups=summary)
    (RESULTS / 'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
