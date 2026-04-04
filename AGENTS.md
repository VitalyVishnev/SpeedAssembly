# AGENTS.md

## Mission

Build a **deterministic converter** from **SpeedTree Raw XML** to **USDA** that Unreal Engine **5.7.x** imports as a **Skeletal Nanite Assembly** for the vegetation pipeline.

This is not a generic XML-to-USD tool.
It is a UE 5.7 skeletal tree assembly authoring pipeline.

Success means:

1. UE imports the generated USDA as a **Nanite Assembly**.
2. The assembly imports in **skeletal** mode, not static mode.
3. All unique tree geometry survives as the **Base Skeletal Tree**.
4. Repeated parts import through **PointInstancer** as **Assembly Parts**, not as duplicated meshes.
5. The result is reproducible and regression-tested.

Static assemblies also exist in UE, but they are out of scope here.

## Document contract

Use the docs in this order:

1. `AGENTS.md`
   Normative for mission, terminology, non-negotiable rules, and project intent.
2. `docs/ue_import_contract.md`
   Normative for importer-facing USDA structure and required UE/USD contract fields.
3. `docs/speedtree_mapping.md`
   Normative for how SpeedTree XML sections map into project concepts.
4. `docs/workflow_status.md`
   Normative for baseline sample, current validation state, and milestone workflow.
5. `docs/local-python-environment.md`
   Operational setup only.

If two documents disagree, this order wins.

## Source of truth order

When project docs conflict with reality, trust in this order:

1. **Actual successful import in UE 5.7.x**
2. UE local schema files
3. UE importer/plugin source
4. Official Epic docs/tutorials/forum replies from Epic staff
5. OpenUSD docs
6. Real SpeedTree XML samples
7. Community sources only as hints

If theory and UE behavior disagree, UE behavior wins.

## Canonical terminology

### `Skeletal Nanite Assembly`

A USD scene structure that UE imports as a skeletal Nanite Assembly: one main tree skeleton, one base skeletal tree for all unique geometry, and repeated skeletal parts instanced through `PointInstancer`.

### `Assembly Root`

The root prim of the USDA scene. It marks the scene as a Nanite Assembly and points UE at the main skeleton used by the assembly.

### `Base Skeletal Tree`

The unique skeletal part of the tree. It contains all non-instanced tree geometry on the main skeleton: trunk, major branches, optional roots, and any other unique geometry.

### `Base Mesh`

In this project, `Base Mesh` means the geometry payload of the **Base Skeletal Tree**, not a trunk-only mesh and not a minimal placeholder mesh.

### `Main Skeleton`

The shared skeleton of the tree. The Base Skeletal Tree is bound to it, and Assembly Parts are attached relative to it.

### `Assembly Parts`

Repeated instanced skeletal parts authored through `PointInstancer`. They may represent twigs, leaf clusters, small branches, or any other repeated detail. The term is structural, not botanical.

### `Part Skeletal Mesh`

The skeletal mesh payload of one Assembly Part prototype.

### `Part Skeleton`

The local skeleton of one Assembly Part. For the current target pipeline, each part has a one-bone local skeleton at the part pivot or base.

### `PointInstancer`

The mechanism that places Assembly Parts. It stores prototypes, instance transforms, and skeletal assembly binding data back to the Main Skeleton.

### `Prototype`

One reusable Assembly Part definition used by the `PointInstancer`.

### `Instance`

One placed occurrence of a Prototype, with transform and binding back to the Main Skeleton.

### `Leaf References`

The SpeedTree XML source section that the converter interprets as the source of **Assembly Parts**. `LeafReferences` does not promise that the payload is literally only leaves.

### `Unique Geometry`

Any tree geometry that stays inside the Base Skeletal Tree and is not instanced.

### `Instanced Geometry`

Any geometry sourced from `LeafReferences` and emitted as Assembly Parts through `PointInstancer`.

### `skeletal`

In this project, `skeletal` means the asset participates in the skeletal UE import path. The Base Skeletal Tree uses the Main Skeleton, and each Assembly Part is itself a skeletal mesh with a simple local skeleton.

## Core structural rule

The tree is split into two major components:

- **Base Skeletal Tree**
  All unique tree geometry on the Main Skeleton.
- **Assembly Parts**
  Everything sourced from `LeafReferences`, instanced through `PointInstancer`, each part authored as a skeletal mesh with a one-bone local skeleton.

Canonical mapping:

- regular XML hierarchy plus skeleton data -> **Base Skeletal Tree**
- `LeafReferences` -> **Assembly Parts**

## Target USDA structure

The generated USDA is expected to contain, conceptually:

- an **Assembly Root**
  - `Xform`
  - `NaniteAssemblyRootAPI`
  - skeletal assembly mode
  - relationship to the descendant Main Skeleton
- one **Base Skeletal Tree**
  - `SkelRoot`
  - real base geometry
  - `Skeleton`
  - skeletal binding contract for the base mesh
- one or more **PointInstancer** prims
  - repeated Assembly Parts
  - skeletal assembly binding data
  - skeletal part prototypes
- per-prototype skeletal part subtrees
  - part skeletal mesh
  - one-bone part skeleton

Exact field names must be verified from UE schema files, importer source, and working examples.

## Critical rules

### Never guess

Do not invent:

- UE schema names
- UE attribute names
- relationship names
- XML field meanings
- undocumented transform conventions

Important rules must come from schema inspection, source inspection, or a passing UE import test.

### Mandatory UE schema contract adherence

Every generated USDA must preserve the required UE-facing:

- API schemas
- primvars
- USD attributes
- relationships
- metadata that importer behavior depends on

Do not emit a syntactically valid USD file that drops importer-relevant skeletal or assembly fields.

### Determinism is mandatory

Same input plus same config must produce the same logical USDA output.

### A valid USD file is not enough

If UE does not import it as the intended asset, it is a failure.

### Treat SpeedTree XML as observed schema

Do not assume a formal stable public specification. Build against real samples.

## Engineering architecture policy

This repository must prefer modular, system-oriented design over short-term convenience.

Required engineering behavior:

1. Build independently evolvable subsystems with explicit contracts.
2. Keep XML parsing, normalization, USDA authoring, validation, FBX import, material resolution, CLI, GUI, and runtime orchestration separated so each can be improved without rewriting the rest of the pipeline.
3. Give each module, class, and function one clear responsibility with well-bounded inputs, outputs, and failure modes.
4. Route cross-cutting behavior through explicit interfaces or shared domain models, not through ad-hoc flags, hidden globals, or unrelated modules reaching into each other.
5. Keep side effects at the edges where practical; core transformation logic should stay deterministic, inspectable, and easy to test in isolation.
6. Prefer extending the normalized model or module contract over stacking one-off conditionals onto an already fragile path.
7. Hardcoded values are acceptable only when they are backed by a verified UE contract, a verified observed source pattern, or an explicitly documented runtime constraint.
8. If a value, rule, or branch is intentionally hardcoded because the importer contract requires it, document that reason near the code or in project docs.

### Question-first rule for unresolved design choices

If implementation requires a structural, architectural, or contract decision and the correct choice is not grounded by the documented source-of-truth order, stop and ask questions before coding.

Do not:

- ship a speculative shortcut just to unblock the moment
- hide an unresolved design choice behind a "temporary" fallback
- add a branch that only fixes the current sample when the general contract is still unclear
- normalize confusion into production behavior by saying "we will clean it up later"

Clarification is preferred over a fast wrong abstraction.

## Mandatory use of `vault`

`vault` is a primary comparison source during development.

Required behavior:

1. Inspect relevant `vault` files before making structural decisions.
2. Compare generated USDA against known-good `vault` examples.
3. Compare source XML against existing `vault` XML examples.
4. Reuse verified naming, hierarchy, schema placement, and authoring patterns when applicable.
5. If code behavior differs from a working `vault` example, explain why in code comments or docs.

If a working example exists in `vault`, it has higher practical value than speculation.

## Current validated assumptions

Use these until UE validation disproves them:

- skeletal assembly import in UE 5.7 requires real base geometry
- Base Skeletal Tree means all unique tree geometry, not trunk-only geometry
- Assembly Parts are skeletal parts with one local bone
- `LeafReferences` is the structural source of Assembly Parts
- current validated stage defaults are:
  - `metersPerUnit = 1`
  - `upAxis = "Y"`

## Current performance and UX priority

Use these as active engineering guidance unless real production validation disproves them:

- `CpuProfile.BALANCED` is the default operator-facing profile and should remain the default unless measured production timing makes that untenable.
- Low aggregate CPU usage during a huge conversion is not, by itself, a bug. The current parallelism is primarily across independent prototypes and stages, not inside one single Autodesk FBX scene import.
- Prefer successful completion, deterministic output, system responsiveness, cleanup, diagnostics, and package-build stability over aggressive all-core saturation.
- Do not prioritize intra-file FBX all-core optimization unless real production trees show unacceptable wall-clock timings.
- Launcher and packaged GUI runtimes are both supported. Fixes that only make the launcher stable are incomplete when the packaged executable still fails on the same workflow.

## Required work order

Work in this order:

1. inspect UE schema files
2. inspect UE importer source
3. inspect relevant `vault` examples
4. inspect real SpeedTree XML samples
5. define the normalized internal model
6. implement XML parsing
7. implement USDA writing
8. validate in UE 5.7.x
9. only then generalize

Do not start with a large abstract architecture before the importer contract is grounded.

## Internal model requirements

Do not write USDA directly from raw XML traversal.

Use a normalized model that cleanly separates:

- XML parsing
- normalization
- USDA writing

At minimum, the model must represent concepts such as:

- `TreeAsset`
- `Skeleton`
- `Joint`
- `Base Skeletal Tree`
- `Prototype`
- `Assembly Part`
- `Instance`
- `Binding`

The internal model and surrounding modules should also preserve clean subsystem boundaries:

- parsing should not depend on writer-specific formatting decisions
- normalization should not depend on GUI state or CLI plumbing
- USDA writing should consume normalized data rather than raw XML traversal state
- validation and diagnostics should be able to inspect normalized or authored output without mutating core conversion logic

## Mapping rules that must be explicit in code

The converter must make these decisions explicitly:

1. what becomes the Base Skeletal Tree
2. what becomes a Prototype
3. what becomes an Instance
4. how Assembly Parts bind to the Main Skeleton
5. how transforms are converted
6. how missing data is handled
7. how base-tree XML material slots are resolved separately from repeated-part prototype material modes
8. how explicit FBX repeated-part material modes (`single_material`, `vertex_color_split`, `material_slots`) are resolved

No hidden heuristics.

## Transform policy

Treat transforms as a first-class subsystem.

Must be tested:

- axis remap
- handedness
- matrix decomposition and recomposition
- quaternion conversion
- pivot handling
- local vs parent vs world transforms
- scale inheritance

Never hide transform bugs with arbitrary corrective offsets.

## Validation loop

A change is not accepted until it is validated against UE.

Minimum loop:

1. generate USDA
2. import into UE 5.7.x
3. inspect logs and result
4. compare against expectations and `vault` examples

Validation must confirm:

- imported as Nanite Assembly
- imported in skeletal mode when expected
- Main Skeleton exists
- Base Skeletal Tree exists
- instance counts match
- transforms are sane
- bindings are sane
- required API schemas are present on the correct prims
- required primvars and importer-relevant USD attributes are present with the correct names and layout

## Failure policy

Fail loudly when the converter cannot safely determine:

- skeleton hierarchy
- required prototype identity
- instance transforms
- required UE schema fields
- required binding data

Errors must say:

- what failed
- where it failed
- which assumption was missing

Do not silently emit broken USDA.

## Code quality standard

Production code in this repository must be clean, modular, readable, and professional.

Required characteristics:

- names should reflect domain meaning, not temporary implementation detail
- modules and files should stay focused; avoid "god modules" that mix parsing, domain logic, writing, UI, and process control
- functions should be small enough that their invariant, side effects, and error behavior are easy to understand
- control flow should be straightforward and reviewable, not clever at the expense of maintainability
- duplicated logic should be consolidated behind one owned abstraction when it represents the same rule
- invariants, assumptions, and failure paths should be explicit
- hidden mutable state should be minimized
- comments should explain why a non-obvious rule exists, especially when it comes from UE behavior or a verified `vault` pattern
- touched code should become more coherent, not less, after a change
- every non-trivial change should land with the right tests for its layer instead of relying on manual memory

Code that is fast to patch but hard to reason about is not considered a successful implementation.

## Testing requirements

### Unit tests

Required for:

- XML normalization
- transform conversion
- naming and path generation
- prototype deduplication
- joint assignment
- USDA formatting helpers

### Golden tests

Given fixed XML and config:

- output USDA must be logically stable
- skeleton topology must match
- instance counts must match

### Reference comparison tests

Generated output should be compared against relevant known-good files from `vault` whenever possible.

## Definition of done

A milestone is done only if:

1. a real SpeedTree XML sample imports into UE 5.7.x as intended
2. USDA is generated entirely by the converter
3. only verified UE schema fields are used
4. repeated Assembly Parts are instanced
5. transforms are correct
6. tests catch regressions
7. mapping rules are documented
8. the result is reproducible by another engineer

## Prohibited shortcuts

Do not:

- guess UE schema attributes from memory
- bake repeated Assembly Parts into unique meshes
- call a static assembly skeletal
- encode unresolved behavior in undocumented hardcoded branches
- ignore `vault` examples
- mix local, world, and source transform spaces
- use a "temporary" architectural shortcut when the correct contract is still unknown
- silently create fallback geometry without logging it
- trust community snippets over schema inspection and working imports

## Minimum documentation set

The compact project docs set is:

1. `AGENTS.md`
2. `docs/ue_import_contract.md`
3. `docs/speedtree_mapping.md`
4. `docs/workflow_status.md`
5. `docs/local-python-environment.md`

## Final rule

This project is an engine-validated reverse-engineering pipeline.

If forced to choose between elegant abstraction, theoretical correctness, and what UE 5.7 actually imports, choose what UE 5.7 actually imports.
