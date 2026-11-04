# Test Policy

## Execution layers

Run these commands from `Project/`. The scripts use the repository-root
`.venv310/` environment; activate `../.venv310/Scripts/Activate.ps1` before
running Python commands directly.

| Layer | Command | Scope |
| --- | --- | --- |
| Preview build | `scripts\\build_qt_gui_exe.cmd -Quick` | Source-backed UI review; no PyInstaller, packaged contracts, ZIP, or smoke. |
| Core | `scripts\\run_tests.cmd Core` | Fast deterministic contracts and synthetic fixtures. |
| Integration | `scripts\\run_tests.cmd Integration` | XML source workflows, workers, and Qt transport/lifecycle. |
| Packaged | `scripts/build_qt_gui_exe.cmd -Package` | Packaged contract tests, then frozen EXE worker/cache/viewport smoke. |
| UE validation | Manual UE 5.7.x import check | Importer behavior; never pytest. |

`pytest` runs Core and Integration by default, excluding `stress` and
`packaged`; the package-build gate runs those contract tests before building
and then owns the frozen-runtime smoke. Markers are assigned centrally in
`tests/conftest.py`; a test has one primary execution layer, while `stress` is
an additional opt-in marker.

A byte-identical final USD and unchanged referenced payloads may reuse an
existing successful Unreal import under the same import settings. Retain the
baseline and output SHA-256 comparison. Repeat source and Package checks for
the changed runtime; repeat Unreal import when output or importer behavior
changes. This avoids repeating an import solely for an internal refactor.

Quick writes `dist-preview/SpeedAssembly_preview.cmd`, which launches the
current source tree through `.venv310` after an import check. It is a manual
preview artifact, not a standalone build or validation layer. Use it after
relevant tests for low-risk UI iteration. Package remains required for
frozen/native/runtime boundaries and before release. A normal UI defect found
in Quick stays on the Quick loop until fixed, followed by one full Package gate;
a packaged-only or native defect stays on Package validation.

## Full builds and extended stability

A normal full build runs the required source checks and the complete `-Package`
gate, including its packaged contracts and real-result smokes. A release draft
does not automatically add `run_packaged_stability_gate.ps1` to that definition.

That separate script is an extended repetition test. Its defaults run 50 worker
cases and ten cycles of three UI scenarios on each of two large inputs: 160
fresh EXE launches. Reserve it for an explicit extended-stress request or an
identified repeated-state/native-lifetime regression in Fracture, workers or
OpenGL. State the risk, scope and expected cost before running it. Changes to
unrelated serialization or a version number alone do not justify the full sweep.
Keep the script and its strict crash/retry checks available; do not reduce
timeouts, accept retries or remove contract tests to shorten routine builds.

Observed on candidate `751de6c`, 2026-11-04:

| Phase | Elapsed | Scope |
| --- | --- | --- |
| Default source suite | 97.97 s | 680 selected tests |
| Complete Package | 169.09 s | Native build, 27 contracts, EXE/ZIP, required smokes |
| Separate extended stability | 2249.55 s | 100 worker launches and 60 UI scenarios |

Package elapsed uses its log creation/last-write timestamps. Its Rust release
builds took 3.60 s combined. Within extended stability, the 20 interactive
Fracture scenarios report 1201.69 s total, rapid-settings 223.23 s and Proxy
82.83 s. Each interactive run rebuilds actual Detailed Cuts geometry several
times; the event polling interval is 50 ms, not a minute-long fixed sleep.
These measurements identify extra validation work, not a Rust slowdown.
The ordinary source/Package portion was about 4.5 minutes in this run; that is
an observation, not a universal time guarantee. The extended script itself
was unchanged from `v0.5.0-beta`. Evidence: `<archive>/validation_duration_2026-11-05/`.

## System contract map

| Contract | Minimal test | Integration | Packaged |
| --- | --- | --- | --- |
| Connectivity | Synthetic closed mesh with integer NumPy indices | Detailed Cuts | Cold-start Detailed Cuts smoke |
| Worker lifecycle | Fake process/coalescing | Qt controller request -> result/error | Rapid-settings smoke plus one injected crash -> retry -> geometry result |
| Cache | Typed payload cold -> warm | Preview request | Two consecutive smoke runs |
| Attribute transfer | Synthetic attributes/caps | Detailed export | — |
| Multi-stem/stumps | Synthetic independent topology | `SimpleTree_02_three_trunks.xml` | — |
| Fracture viewport inspection | Smooth shared-point normals | Qt focus + close zoom contract | Real geometry upload |

## Fixture policy

- Synthetic geometry covers algorithms, boundaries, and fail-loud cases.
- Simple Tree covers the normal complete workflow.
- The three-trunk Simple Tree variant covers independent stems and stumps.
- Big Spruce is reserved for explicit scale/performance stress and packaged stress.

Every test must protect a distinct contract. Use a real sample only for unique
topology, scale, importer behavior, or a packaged boundary. Reproduce an asset
bug on its original source, then retain the smallest fixture preserving its
cause.

## 2026-07-17 baseline audit

- Historical collection before the policy audit: 735 tests.
- Current collection: 531 primary-layer tests: 430 Core, 75 Integration, and 26 Packaged contracts; 4 Core/Integration tests also carry the explicit `stress` marker. The default Core + Integration selection contains 501 tests. Runtime has not been remeasured in this maintenance pass.
- The Fracture follow-up restored only three missing user contracts: latest-only Qt worker delivery, smooth fallback normals, and close focus/zoom. Real-source Detailed export and Boolean cases run in Integration; Big Spruce remains explicit stress.
- Slowest cases: Big Spruce pipeline smoke (3.62 s), Qt restored-path/wind refresh (2.67 s), Qt adjustment dialogs (2.11–2.64 s), Big Spruce dominant-shell cut (2.10 s), and Simple Tree/three-trunk fracture workflows (0.69–1.60 s).
- Removed duplicate categories: sample-specific cache coverage, repeated Qt control/layout assertions, Qt copies of backend geometry checks, superseded compatibility facades, and duplicate real-tree fracture permutations. Each retained layer still has a contract-map row.
- The previous generic Big Spruce source-model-cache regression caused a `0xC0000005` Python access violation during JSON serialization. The cache contract is now run on Simple Tree; Big Spruce remains a stress-only fixture.
