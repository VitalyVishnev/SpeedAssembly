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
- UE-backed material overrides work on the current baseline workflow

The project has also passed automated `Phase 1` regression coverage for:

- `LeafReferences` on trunk and intermediate branch levels
- deeper branch hierarchy before repeated parts
- invalid leaf binding rejection
- multi-material part authoring through `GeomSubset`
- explicit material-policy remapping for shifted source material ids
- single-material remapping for base mesh and part prototypes
- vertex-color split remapping for base mesh and part prototypes
- mixed inline plus external `PartMesh` prototype resolution
- multi-root main skeleton USDA naming without duplicate root aliases
- prototype-derived one-bone part skeleton naming
- separate Dynamic Wind JSON generation from the normalized skeleton

The current naming contract used by the checked exports is:

- output USDA files are named `<stem>.usda`
- the base mesh prim uses the same `<stem>`
- the base `SkelRoot` uses `<stem>_Geo`
- the shared `Skeleton` uses `<stem>_Skeleton`
- the skeleton name is not inferred from the first bone name
- the XML source filename is not used to derive the main skeleton name

The wind-group contract has also been validated on the attached grass sample:

- `SkeletyalAssemblyTest_Grass.xml` now resolves to a single wind group under the explicit generator-level rule
- `Ground Cover` remains an explicit wind flag and does not change group count
- when `Ground Cover` is enabled, every generated simulation group is emitted as non-trunk
- legacy XML samples that do not provide usable generator levels are rejected by the wind path instead of being inferred

Current operator-facing material controls:

- the GUI exposes `Material Policy`
- `single_material` uses a dedicated `Single Material Path` field
- `legacy_role_ids` and `vertex_color_split` continue to use the bark/leaves override fields
- GUI settings persist the selected material policy and single-material path
- the CLI exposes:
  - `--material-policy`
  - `--single-material-path`
  - `--bark-material-path`
  - `--leaves-material-path`

The only remaining open item before `Phase 1` can be considered complete is broader validation on multiple real SpeedTree structures with different tree and grass shapes:

- small shrub with one trunk
- small shrub with multiple trunks
- tree with multiple trunks growing directly from the ground
- tree that starts as one trunk and later splits into two trunks
- palm-like form with a long trunk and a crown of large leaves
- tall branching grass
- short grass
- grass made from separate blades

Grass should be checked in more than one authoring style:

- clustered or bundled blades, with one bone per bundle if that is how the source is authored
- a more detailed blade-level variant, if a real source export exists for that shape

The standalone package build path has also been stabilized:

- `.\scripts\build_gui_exe.cmd -Package` now clears stale `build/` and `dist/` state before invoking PyInstaller
- PyInstaller is also run with `--clean` so the package path does not reuse incremental analysis output from older runs
- the previous "looks stuck" behavior was a stale-package-state problem, not a converter logic regression

At this point, the earlier importer-facing concerns are treated as closed by the current validation set:

- skeletal import path
- naming contract
- materials
- wind JSON
- external `PartMesh` reuse
- transform and instance placement sanity on the currently tested samples

Recent exporter fixes that must remain stable:

- the fern-style `single_material` path no longer depends on XML material ids being `1/2`
- multi-root plants must keep a real `Base Skeletal Tree`; they must not regress into `Assembly Parts`-only imports because of collapsed root-joint aliases
- inline part skeletons must not fall back to a generic `Root_Skeleton` naming pattern caused by a hardcoded local joint name

The remaining acceptance criterion is breadth, not a known functional blocker.

## Phase 1 Definition Of Done

`Phase 1` is complete only when all of the following are true:

- UE imports the generated USDA as a skeletal Nanite Assembly
- unique geometry survives as the `Base Skeletal Tree`
- repeated geometry imports through `PointInstancer`
- materials work for the baseline import path, including UE-backed material overrides
- material-policy behavior is documented and regression-tested for `legacy_role_ids`, `single_material`, and `vertex_color_split`
- transforms and skeletal bindings are visually sane in UE
- automated regression fixtures cover the supported structural cases
- optional reuse of existing Unreal `PartMesh` skeletal assets is available
- mapping rules and importer-facing contract are documented
- the converter has been validated on multiple real SpeedTree structures with meaningfully different tree, shrub, palm, and grass forms

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
- distinct root-joint naming for multi-root main skeletons
- repeated `Assembly Parts` sourced from `LeafReferences`
- `PointInstancer`-based part instancing
- skeletal parts with one-bone local part skeletons for inline prototypes
  - the one-bone local joint name comes from the prototype name, not a hardcoded `root`
- optional external `PartMesh` references for reused project assets

## Manual UE Checklist

Run this checklist for every real `Phase 1` sample:

1. import succeeds as skeletal Nanite Assembly
2. `Base Skeletal Tree` geometry is present and not truncated
3. instance counts are sane
4. part placement matches expected attachment points
5. parts do not drift away from the main skeleton
6. bark and leaves materials resolve correctly
7. in `single_material` mode, both base mesh and parts resolve to the one forced material
8. on multi-root plants, the base mesh still imports and does not disappear while parts continue to import
9. existing external `PartMesh` references still import through the assembly path when enabled
10. wind JSON reimport produces sane primary-stem and secondary-branch bending
11. generated USDA contains `NaniteAssemblyExternalRefAPI` for every intentionally externalized part prototype
12. externalized part prototypes do not retain inline `PartMesh` mesh payloads in the same USDA branch

## Current milestone sequence

1. keep the baseline skeletal assembly path stable
2. validate the current contract on multiple real structural variants
3. only then generalize to later features such as UV modification

## Troubleshooting shortcut

When a user says “I entered a UE object path, but the importer still used low-poly branches”:

1. inspect the exported USDA text
2. search for `NaniteAssemblyExternalRefAPI` and `unreal:naniteAssembly:meshAssetPath`
3. if the schema is missing, the bug is in the converter, not in UE
4. if the schema is present, verify that UE used the Interchange importer path and that the asset path matches the Content Browser object path exactly
