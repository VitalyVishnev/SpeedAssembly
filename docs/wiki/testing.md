# Test Policy

## Execution layers

| Layer | Command | Scope |
| --- | --- | --- |
| Core | `scripts\\run_tests.cmd Core` | Fast deterministic contracts and synthetic fixtures. |
| Integration | `scripts\\run_tests.cmd Integration` | XML source workflows, workers, and Qt transport/lifecycle. |
| Packaged | `scripts/build_qt_gui_exe.cmd -Package` | Packaged contract tests, then frozen EXE worker/cache/viewport smoke. |
| UE validation | Manual UE 5.7.x import check | Importer behavior; never pytest. |

`pytest` runs Core and Integration by default, excluding `stress` and
`packaged`; the package-build gate runs those contract tests before building
and then owns the frozen-runtime smoke. Markers are assigned centrally in
`tests/conftest.py`; a test has one primary execution layer, while `stress` is
an additional opt-in marker.

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
