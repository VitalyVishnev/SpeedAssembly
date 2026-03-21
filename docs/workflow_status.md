# Workflow And Status

## Role

This document is normative for the active baseline sample, current validation state, and milestone workflow.

## Active fixtures

The current real reverse-engineering baseline is:

- `samples/speedtree/simple_tree/variants/SimpleTree_01.xml`

The matching authored mesh assets next to that reference XML are treated as the canonical authored size and orientation baseline for part prototypes.

The repository also carries synthetic regression fixtures for `Phase 1` structural coverage:

- `tests/data/leafrefs_on_trunk.xml`
- `tests/data/leafrefs_on_branch_levels.xml`
- `tests/data/invalid_leaf_bone.xml`

These synthetic files exist to validate normalization, binding, and material authoring behavior that is not yet covered by additional real exports.

## Current validated status

The project has passed the baseline importer gate:

- UE accepts the generated baseline USDA as skeletal Nanite Assembly input
- the baseline keeps a real `Base Skeletal Tree`
- repeated parts are authored through `PointInstancer`
- UE-backed bark/leaves material assignment works on the current baseline workflow

The project has also passed automated `Phase 1` regression coverage for:

- `LeafReferences` on trunk and intermediate branch levels
- deeper branch hierarchy before repeated parts
- invalid leaf binding rejection
- multi-material part authoring through `GeomSubset`
- mixed inline plus external `PartMesh` prototype resolution
- separate Dynamic Wind JSON generation from the normalized skeleton

The wind-group contract has also been validated on the attached grass sample:

- `SkeletyalAssemblyTest_Grass.xml` now resolves to a single wind group under the explicit generator-level rule
- `Ground Cover` remains an explicit wind flag and does not change group count
- when `Ground Cover` is enabled, every generated simulation group is emitted as non-trunk
- legacy XML samples that do not provide usable generator levels are rejected by the wind path instead of being inferred

One specific dead-end has been closed:

- external `PartMesh` overrides now author a pure Unreal reference prototype instead of leaving inline low-poly `PartMesh` geometry in the same USDA branch
- the first debug check for an ignored override is now the generated USDA text, not UE import settings

The standalone package build path has also been stabilized:

- `.\scripts\build_gui_exe.cmd -Package` now clears stale `build/` and `dist/` state before invoking PyInstaller
- PyInstaller is also run with `--clean` so the package path does not reuse incremental analysis output from older runs
- the previous "looks stuck" behavior was a stale-package-state problem, not a converter logic regression

The project has not passed the final `Phase 1` quality gate yet:

- only one real SpeedTree XML sample is currently checked into the repository
- transform fidelity still requires manual UE validation across more than one real export
- texture/material fidelity still requires manual UE validation with real bark and leaf shaders
- wind tuning still requires broader manual UE comparison against more than one reference tree

## Phase 1 Definition Of Done

`Phase 1` is complete only when all of the following are true:

- UE imports the generated USDA as a skeletal Nanite Assembly
- unique geometry survives as the `Base Skeletal Tree`
- repeated geometry imports through `PointInstancer`
- materials work for the baseline import path, including UE-backed material overrides
- transforms and skeletal bindings are visually sane in UE
- automated regression fixtures cover the supported structural cases
- optional reuse of existing Unreal `PartMesh` skeletal assets is available
- mapping rules and importer-facing contract are documented

## Expected workflow

For importer-facing work, use this loop:

1. inspect the active XML fixture
2. convert it to USDA
3. verify the expected assembly structure
4. import into UE 5.7.x
5. inspect logs and resulting asset
6. compare against `vault` examples
7. record any importer-facing contract change before generalizing

## Workflow invariants

The stable `Phase 1` path must preserve:

- one `Base Skeletal Tree` for all unique tree geometry
- one `Main Skeleton`
- repeated `Assembly Parts` sourced from `LeafReferences`
- `PointInstancer`-based part instancing
- skeletal parts with one-bone local part skeletons for inline prototypes
- optional external `PartMesh` references for reused project assets

## Manual UE Checklist

Run this checklist for every real `Phase 1` sample:

1. import succeeds as skeletal Nanite Assembly
2. `Base Skeletal Tree` geometry is present and not truncated
3. instance counts are sane
4. part placement matches expected attachment points
5. parts do not drift away from the main skeleton
6. bark and leaves materials resolve correctly
7. existing external `PartMesh` references still import through the assembly path when enabled
8. wind JSON reimport produces sane primary-stem and secondary-branch bending
9. generated USDA contains `NaniteAssemblyExternalRefAPI` for every intentionally externalized part prototype
10. externalized part prototypes do not retain inline `PartMesh` mesh payloads in the same USDA branch

## Current milestone sequence

1. keep the baseline skeletal assembly path stable
2. validate transform and rig fidelity across more real exports
3. validate texture and material fidelity in UE
4. keep optional external `PartMesh` reuse stable
5. stabilize Dynamic Wind JSON behavior and document the observed UE contract
6. only then generalize to later features such as UV modification

## Troubleshooting shortcut

When a user says “I entered a UE object path, but the importer still used low-poly branches”:

1. inspect the exported USDA text
2. search for `NaniteAssemblyExternalRefAPI` and `unreal:naniteAssembly:meshAssetPath`
3. if the schema is missing, the bug is in the converter, not in UE
4. if the schema is present, verify that UE used the Interchange importer path and that the asset path matches the Content Browser object path exactly
