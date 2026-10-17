# XML opening experiment

See [RESULTS.md](RESULTS.md). Run commands from the repository root using the
existing `.venv310`; application imports are resolved from `Project/src`.

Prepare the original discovery service snapshot once. It is private scratch
data, not imported by the application:

```powershell
New-Item -ItemType Directory -Force Project/tmp/xml-opening | Out-Null
./.venv310/Scripts/python.exe -c "from pathlib import Path; import subprocess; Path('Project/tmp/xml-opening/baseline_discovery.py').write_bytes(subprocess.check_output(['git','show','4b3ce7f:Project/src/xml_to_usda/discovery_service.py']))"
```

Each command below runs one fresh process. Use new output filenames for repeats.
For an old cold-cache run, choose a fresh private `--cache-root` and `--cache
enabled`; repeat with that same root to measure a warm application cache.
`--cache off` bypasses only the source-model JSON cache. It does not flush OS
file caches or change any application setting.

```powershell
$xml = 'Project/samples/speedtree/BigSpruce/SkeletalAssemblyTest_Spruce_Big_low.xml'
$bench = 'Project/experiments/xml_opening/benchmark.py'
./.venv310/Scripts/python.exe $bench --input $xml --variant baseline --cache off --cache-root Project/tmp/xml-opening/repro --output Project/tmp/xml-opening/before.json
./.venv310/Scripts/python.exe $bench --input $xml --variant candidate --cache off --cache-root Project/tmp/xml-opening/repro --output Project/tmp/xml-opening/after.json
```

Add `--parser packaged` to exercise the production frozen XML parser adapter
without freezing Python. This still runs the existing safety checks. Add
`--profile` only for attribution; profiled wall times are not speed comparisons.
Peak parent working set uses the Windows process memory counter.

Time a real empty Qt window through source rows and automatic Wind completion:

```powershell
$ui = 'Project/experiments/xml_opening/ui_open.py'
./.venv310/Scripts/python.exe $ui --input $xml --variant baseline --cache off --runtime Project/tmp/xml-opening/repro-ui-before --output Project/tmp/xml-opening/ui-before.json
./.venv310/Scripts/python.exe $ui --input $xml --variant candidate --cache off --runtime Project/tmp/xml-opening/repro-ui-after --output Project/tmp/xml-opening/ui-after.json
```

The script preserves production timers, supervisors, authentication and result
IPC. It changes worker executable selection to apply experimental instrumentation
inside fresh children, runs Qt offscreen, acknowledges warnings and uses private
settings/temp/cache roots. It does not mutate installed settings or production
backend selection. GUI settings are reset even for repeated warm-cache runs.

After the ordinary `-Package` gate, check a real frozen discovery worker:

```powershell
./.venv310/Scripts/python.exe Project/experiments/xml_opening/frozen_check.py --exe Project/dist-next/SpeedAssembly.exe --input $xml --runtime Project/tmp/xml-opening/repro-frozen --output Project/tmp/xml-opening/frozen.json
```

This asserts full source/frozen result equality and no source-model cache
creation. The retained large-source check also includes WorldTree and both grass
samples. Run `summarize.py` from the repository root to recheck parity and rebuild
the summary of the retained result filenames. External source assets are local
and not redistributed; exact paths and hashes are in `results/summary.json`.
