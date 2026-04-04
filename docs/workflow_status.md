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
- mixed inline, external Unreal asset, and explicit disk-FBX prototype resolution
- multi-root main skeleton USDA naming without duplicate root aliases
- prototype-derived one-bone part skeleton naming
- separate Dynamic Wind JSON generation from the normalized skeleton
- streamed USDA writing for explicit FBX prototype payloads without returning a full in-memory USDA text blob

Current Python runtime contract:

- `.venv310` is the primary development and validation environment
- real Autodesk FBX import is expected to run from `.venv310`
- the known-good FBX package is Autodesk `FBX Python SDK 2020.3.4` for CPython `3.10`
- GUI build helpers are expected to run from `.venv310`
- future chats should assume `.venv310` first when running the converter or debugging FBX import

The current naming contract used by the checked exports is:

- output USDA files are named `<stem>.usda`
- the base mesh prim uses the same `<stem>`
- the base `SkelRoot` uses `<stem>_Geo`
- the shared `Skeleton` uses `<stem>_Skeleton`
- the skeleton name is not inferred from the first bone name
- the XML source filename is not used to derive the main skeleton name

The wind-group contract has also been validated on the attached grass sample:

- `SkeletalAssemblyTest_Grass.xml` now resolves to a single wind group under the explicit generator-level rule
- `Ground Cover` remains an explicit wind flag and does not change group count
- when `Ground Cover` is enabled, every generated simulation group is emitted as non-trunk
- legacy XML samples that do not provide usable generator levels are rejected by the wind path instead of being inferred

Current operator-facing material controls:

- the GUI now separates `Base XML materials` from repeated-part material settings
- base XML materials are discovered from the XML source and shown as per-slot rows:
  - source `ID`
  - source `Name`
  - Unreal material path
- prototype-only material slots used only by instanced repeated parts are intentionally excluded from the base-material list
- assigning the same Unreal material path to multiple XML rows is a supported way to intentionally collapse those XML slots to the same UE material asset
- repeated part prototypes now carry their own stage-1 material controls in the GUI
- current GUI part-material modes are:
  - `vertex_color_split`
  - `single_material`
  - `material_slots` for `FBX file` rows
- `vertex_color_split` for part rows is an explicit black/white split
- `single_material` for part rows uses its own dedicated Unreal material path field
- `material_slots` reads the FBX and shows only the slots actually used by faces in the imported payload
- `material_slots` merges repeated FBX material names into one UI slot row
- `material_slots` labels unnamed slot usage as `Unassigned`
- the GUI no longer relies on `auto` as the primary interactive workflow for part materials
- GUI settings persist per-XML base-material rows and per-XML repeated-part material settings
- the CLI exposes:
  - `--material-policy`
  - `--single-material-path`
  - `--bark-material-path`
  - `--leaves-material-path`

Current operator-facing part-source controls:

- the GUI exposes a per-prototype `Source Mode` for each repeated part prototype discovered from `LeafReferences`
- each row can keep the XML mesh, point at an existing Unreal skeletal asset, or load a disk FBX file
- GUI settings persist the per-prototype choice per input XML
- the GUI also exposes `CPU Profile`:
  - `balanced`
  - `max_speed`
  - `quiet`
- the CLI exposes:
  - `--part-source-config`
  - `--cpu-profile`

Current operator-facing wind-settings contract:

- wind-group slider values are persisted per input XML path
- switching between different trees must restore the last saved wind values for that specific XML instead of reusing another tree's settings

Current large-job execution contract:

- large GUI conversions are executed in a dedicated worker subprocess instead of inside the Tk UI process
- the GUI process now only owns the UI and telemetry polling; the worker subprocess owns XML normalization, FBX import, material resolution, and USDA writing
- explicit FBX prototype imports are parallelized across a `spawn` process pool when more than one FBX prototype must be imported
- this parallelism is currently prototype-level and stage-level, not "all cores inside one single FBX file"
- packaged frozen runs deliberately fall back to sequential multi-FBX import instead of nested parallel FBX workers, because package-build stability currently has higher priority than peak CPU saturation
- if that worker pool cannot be created in the current environment, FBX prototype import falls back to sequential execution instead of failing outright
- the conversion worker must not be daemonized, because parallel FBX import requires child worker processes
- the validated `WorldTree.xml` stress path with two huge FBX branch replacements completes successfully through the subprocess path
- `balanced` remains the default operator-facing CPU profile for this path
- low total CPU percentage on a monster export with only one or two huge FBX prototypes is currently expected and is not treated as a defect on its own
- the active engineering priority for huge jobs is runtime stability, recovery, diagnostics, and packaged-build reliability before deeper intra-file FBX saturation work

Current huge-FBX contract:

- XML `LOD/@Filename` is ignored for this workflow
- FBX mode is explicit only through GUI/CLI prototype source config
- v1 accepts rigid polygon payloads only
- animated or skinned FBX payloads are rejected
- FBX-origin pivot is treated as the attachment pivot
- FBX prototype source config supports `fbx_material_mode`:
  - `auto`
  - `vertex_color_split`
  - `single_material`
  - `material_slots`
- GUI repeated-part material controls expose `vertex_color_split`, `single_material`, and `material_slots` for `FBX file` rows
- `vertex_color_split` expects exact black and exact white face buckets for part-material assignment
- if `fbx_material_mode=auto` and FBX vertex colors are missing, incomplete, or all collapse to one bucket, the prototype falls back to one primary material section
- if `fbx_material_mode=vertex_color_split`, the split is strict: unusable colors or Autodesk SDK vertex-color access failures now produce a detailed conversion error instead of silently degrading the prototype to one material
- if `fbx_material_mode=material_slots`, only the slots actually used by faces are emitted
- if multiple FBX mesh nodes share the same material name, they collapse to one logical slot row in the UI and one logical slot override contract
- if some `material_slots` rows are blank, one filled Unreal material path is reused and a warning is emitted
- if every `material_slots` row is blank, conversion fails loudly
- huge FBX prototype payloads are written through the streaming USDA path using a temp file plus atomic replace on success
- when multiple explicit FBX prototype replacements are present, their imports may overlap in parallel worker processes
- telemetry for huge jobs now distinguishes `xml_normalization`, `prototype_resolution`, `fbx_import`, `material_resolution`, and `usda_writing`
- runtime job manifests now also record a small `runtime_context` block so packaged-worker crashes can be compared against launcher-worker crashes after the fact

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
- large GUI conversions must not reuse the Tk process for Autodesk FBX import or huge USDA writing
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
3. only then generalize to later features such as UV modification

## Troubleshooting shortcut

When a user says вЂњI entered a UE object path, but the importer still used low-poly branchesвЂќ:

1. inspect the exported USDA text
2. search for `NaniteAssemblyExternalRefAPI` and `unreal:naniteAssembly:meshAssetPath`
3. if the schema is missing, the bug is in the converter, not in UE
4. if the schema is present, verify that UE used the Interchange importer path and that the asset path matches the Content Browser object path exactly


