# Initial XML opening, 2026-10-17

Initial opening is faster after removing unnecessary canonical geometry work
and full-model JSON caching from discovery. This change uses Python only.
Rust XML parsing has not been implemented or measured in this experiment.

## User-visible wait

Real offscreen Qt window, paste into an initially empty input, then wait for
source rows and automatic Wind groups. Existing process supervisors,
authenticated result IPC, debounce/poll timers and fresh child processes run.
These are source Python timings, not frozen EXE launch timings.

| Input and baseline cache | Before | After, no source cache | Repetitions before/after |
| --- | ---: | ---: | ---: |
| Big Spruce, cache off | 4.017 s | 2.662 s | 3/3 |
| Big Spruce, cold JSON cache | 5.514 s | 2.662 s | 1/3 |
| Big Spruce, warm JSON cache | 4.498 s | 2.662 s | 2/3 |
| WorldTree, cache off | 32.503 s | 13.829 s | 2/2 |

Thus Big Spruce improves 1.51x against the old no-cache path, 2.07x against cold
JSON and 1.69x against warm JSON. WorldTree improves 2.35x without either version
using a source-model cache. Fixed UI/worker overhead reduces the gain seen in
service-only timings. WorldTree ranges were 32.431 to 32.576 s and 13.656 to 14.001 s.

## Discovery and Wind service costs

Fresh-process measurements; medians of three runs unless stated otherwise.
The packaged-parser rows exercise the exact stdlib adapter chosen by frozen
XML code inside source Python. They do not include EXE extraction or IPC.

| Case, cache off | Discovery before/after | Discovery + Wind before/after | Parent peak MiB before/after |
| --- | ---: | ---: | ---: |
| Simple Tree, source parser | 0.089 / 0.021 s | 0.101 / 0.034 s | 43 / 38 |
| Big Spruce, source parser | 1.745 / 0.570 s | 2.008 / 0.840 s | 128 / 73 |
| WorldTree, source parser | 25.775 / 7.591 s | 29.608 / 11.691 s | 1536 / 532 |
| Big Spruce, packaged parser | 1.623 / 0.506 s | 1.862 / 0.729 s | 134 / 79 |
| WorldTree, packaged parser | 23.086 / 7.467 s | 26.866 / 11.387 s | 1616 / 612 |

Old Big Spruce service path with cache creation took 3.752 s including Wind;
warm JSON took 2.781 s. Both exceed direct XML without cache, 2.008 s. Cold
writing alone took 1.704 s; warm JSON reconstruction took about 1.367 s.
WorldTree JSON creation/loading was deliberately not repeated because its
large-model serialization risk is already recorded in Known Bugs.

Additional real-source parity checks, one run per variant:

| Input | Discovery before/after | Full service before/after |
| --- | ---: | ---: |
| Norway spruce, 16.18 MB | 3.440 / 1.151 s | 3.964 / 1.729 s |
| Clustered grass, 572 parts | 0.161 / 0.078 s | 0.428 / 0.387 s |
| Unclustered grass, 41 parts | 0.038 / 0.009 s | 0.057 / 0.031 s |

Grass retains full canonical analysis; its unchanged Wind fallback dominates
the clustered example. Single runs establish parity, not reliable speed ratios.

## Why the old work existed

The historical `docs/raw/ARCHITECTURE_IMPROVEMENT_PLAN.md`, Phase 5, explicitly
kept streamed discovery because supported rows matched canonical facts and
full normalization would hurt responsiveness. Later Scattered Parts detection
requires actual canonical geometry and Object hierarchy, while strict-vertical
warnings require normalized, oriented source bones. Both requirements are valid.
The current implementation satisfied them by loading the complete cached model
for every input, then independently parsing XML three more times for UI rows.

The change reads one document through the existing hardened reader and reuses
it for all row projections. An authored normalized skeleton rules out Scattered
Parts, so discovery skips mesh arrays, mesh merging, binding, instance transforms
and cache serialization. It reuses canonical bone normalization and instance
count semantics, including the ambiguous LeafReferences position-space guard.
Skeletonless sources still undergo full canonical normalization on that same
document. No classification relies on names or assumed valid geometry tags.

The internal exclusion reason for skeletal input is now `skeleton is present`;
previously a simultaneous base mesh could take precedence. The UI does not
display that reason. Every other discovery field and complete Wind data match
between variants on all six sources. Conversion still performs full geometry
normalization and validation. Opening does not certify exportable geometry.

## Validation and limits

- 52 accepted opening runs: 39 service measurements and 13 real Qt runs.
- Exact discovery/Wind data signatures match on six real XML inputs, with only
  the explicitly documented exclusion-reason normalization above.
- An intent-level regression compares UI rows, counts, warnings and hierarchy
  classification against canonical and streamed facts. It forbids extra XML
  parsing, model-cache access and geometry normalization for authored skeletons.
  Fixtures cover ordinary trees, alternate source axis, invalid bone references,
  skeletonless input and clustered parts.
- XML safety budgets and DTD/entity rejection use the unchanged canonical reader.
  The >=5 MiB fresh-worker boundary from CR-013 remains unchanged.
- Default regression suite: 632 passed. Final focused checks: 59 passed.
- Package passed: 27 packaged contracts, repeated real-result Detailed Cuts
  stability smoke with no retries, and injected-worker-failure recovery smoke
  through a geometry result. No smoke was skipped. No unexpected crash occurred.
- The actual frozen EXE passed discovery/source equality on Big Spruce,
  WorldTree and both grass sources, with no source-model cache created. Counts
  include 4,249 joints/43,263 instances for WorldTree and 52 clusters/572 instances
  for clustered grass. Real worker time including EXE extraction and result IPC
  was 2.503 s for Big Spruce and 9.672 s for WorldTree; no frozen baseline was
  measured, so these are acceptance timings, not frozen speed ratios.
  See `results/frozen-check.json` for the executable SHA-256 and all cases.

The unchanged release version is `0.5.0-beta`. Local artifacts are
`Project/dist-next/SpeedAssembly.exe` and `SpeedAssembly_release.zip`. Build
reports are in `Project/dist-next/smoke/`; nothing was published. No new Unreal
import was performed because this change does not alter conversion semantics
or the USDA/importer contract.

No Rust build, new dependency, user-facing backend switch or release-version
change is part of this optimization. FBX loading/cache and conversion-cache
policy are unchanged. Removing discovery's cache warmup can move cache creation
to the later Convert action; conversion itself was not accelerated here.

Remaining cost: a complete XML element tree, separate in-memory row traversals,
and another XML parse for Wind. Leaf-only Wind retains its full-model fallback.
A bounded selective reader or typed reuse of skeleton facts could reduce these
costs, but neither has been measured. Parallelizing reads would retain duplicate
work and increase concurrent memory; these results do not justify it.

Machine: Windows, i9-14900K, repository `.venv310`, Python 3.10. OS file caches
were retained; cold/warm refers only to the application JSON cache. No CPU
affinity was forced, so do not compare absolute values to the earlier one-core
Rust conversion experiment. Final large-source and packaged-adapter comparisons
ran sequentially; the first service baseline block briefly overlapped candidate
pilots. Real Qt and packaged-adapter results independently confirm the effect.
Profile, GC diagnostic and Qt pilot records are excluded by `summarize.py`.
An initial Qt cache pilot restored saved input before timing and was discarded;
accepted cache runs explicitly reset GUI settings before each paste.

Raw JSON, input SHA-256 hashes, ranges and parity assertions are in
`results/summary.json`. Reproduction commands are in [README.md](README.md).
