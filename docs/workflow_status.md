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
- `tests/data/missing_leaf_refs.xml`
- `tests/data/missing_skeleton.xml`
- `tests/data/non_default_metadata.xml`

These synthetic files exist to validate normalization, binding, and material authoring behavior that is not yet covered by additional real exports.

## Current validated status

The project has passed the baseline importer gate:

- UE accepts the generated baseline USDA as skeletal Nanite Assembly input
- the baseline keeps a real `Base Skeletal Tree`
- repeated parts are authored through `PointInstancer`
- UE-backed material overrides work on the current baseline workflow
- the authored second UV channel (`primvars:st1`) is accepted by UE 5.7.x on the current baseline sample, and UDIM offsets behave as expected in that path
- automated tests cover the USDA authoring path and the secondary-UV overwrite rule that fills untouched faces with `(0.5, 0.5)`

The project has also passed automated `Phase 1` regression coverage for:

- `LeafReferences` placement and binding edge cases
- material-policy and prototype-resolution variants
- multi-root naming and one-bone part-skeleton cases
- wind JSON generation
- streamed USDA writing
- `skeletal_parts` and `static_assembly` export coverage

Current large-job execution contract:

- large GUI conversions run as a `Runtime Job` in a dedicated `Conversion Worker` instead of inside the UI process
- the GUI process now only owns the UI and telemetry polling; the Conversion Worker owns XML normalization, FBX import, material resolution, and USDA writing
- explicit FBX prototype imports are parallelized across a `spawn` process pool when more than one FBX prototype must be imported
- this parallelism is currently prototype-level and stage-level, not "all cores inside one single FBX file"
- explicit FBX prototype payloads are cached across Runtime Jobs in the bounded FBX payload cache under the runtime cache root; the shipped default policy is `20 GB` / `14 days` and is configurable from the Qt title-bar gear
- repeated-part FBX import now avoids vertex-color and material-slot face-section reads when the selected FBX material mode does not need them
- packaged frozen runs use isolated `FBX Helper` imports through the shared FBX supervisor and start from the requested prototype-level concurrency
- if a native helper crash occurs at that concurrency, the supervisor automatically retries the remaining FBX imports with a lower helper count instead of failing the whole job immediately
- if that worker pool cannot be created in the current environment, FBX prototype import falls back to sequential execution instead of failing outright
- the conversion worker must not be daemonized, because parallel FBX import requires child worker processes
- the validated `WorldTree.xml` stress path with two huge FBX branch replacements completes successfully through the subprocess path
- low total CPU percentage on a monster export with only one or two huge FBX prototypes is not, by itself, a defect; the more important signal is whether the supervisor keeps safe parallel progress instead of stalling or crashing
- the active engineering priority for huge jobs is runtime stability, recovery, diagnostics, and packaged-build reliability before deeper intra-file FBX saturation work

Current huge-FBX status:

- huge FBX writing uses the streamed USDA path with temp-file replacement and runtime telemetry
- `Runtime Job` manifests now include `runtime_context` for launcher-versus-packaged crash comparison
- use `python -m xml_to_usda benchmark-fbx <fbx path> --material-mode <mode>` for local heavy-FBX cache/read-option profiling

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

The primary standalone package build path has also been stabilized:

- `.\scripts\build_qt_gui_exe.cmd -Package` now clears stale `build-next/` and `dist-next/` state before invoking PyInstaller
- PyInstaller is also run with `--clean` so the package path does not reuse incremental analysis output from older runs
- the previous "looks stuck" behavior was a stale-package-state problem, not a converter logic regression

The earlier importer-facing concerns are treated as closed by the current validation set.

Recent exporter fixes that must remain stable:

- the fern-style `single_material` path no longer depends on XML material ids being `1/2`
- multi-root plants must keep a real `Base Skeletal Tree`; they must not regress into `Assembly Parts`-only imports because of collapsed root-joint aliases
- inline part skeletons must not fall back to a generic `Root_Skeleton` naming pattern caused by a hardcoded local joint name
- large GUI conversions must not reuse the UI process for Autodesk FBX import or huge USDA writing
- the conversion subprocess must remain non-daemon so nested FBX worker processes can be created on Windows

The remaining acceptance criterion is breadth, not a known functional blocker.

## Phase 1 Definition Of Done

`Phase 1` is complete only when all of the following are true:

- UE imports the generated USDA as a skeletal Nanite Assembly
- unique geometry survives as the `Base Skeletal Tree`
- repeated geometry imports through `PointInstancer`
- materials work for the baseline import path, including UE-backed material overrides
- material-policy behavior is documented and regression-tested for `source_material_roles`, `single_material`, and `vertex_color_split`
- explicit repeated-part material behavior is regression-tested for `single_material`, `vertex_color_split`, and `material_slots`
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
3. extend UDIM validation across additional real SpeedTree samples while keeping the importer path stable

## Troubleshooting shortcut

When a user says вЂњI entered a UE object path, but the importer still used low-poly branchesвЂќ:

1. inspect the exported USDA text
2. search for `NaniteAssemblyExternalRefAPI` and `unreal:naniteAssembly:meshAssetPath`
3. if the schema is missing, the bug is in the converter, not in UE
4. if the schema is present, verify that UE used the Interchange importer path and that the asset path matches the Content Browser object path exactly


