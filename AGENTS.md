# AGENTS.md

## Mission

Build a **deterministic converter** that takes **SpeedTree Raw XML** as input and emits **USDA** that Unreal Engine **5.7.x** can import as a **Skeletal Nanite Assembly** with minimal or no manual fixing.

This repository is **not** a generic XML→USD converter. It is a **UE 5.7 Skeletal Nanite Assembly authoring tool** for vegetation, starting from SpeedTree exports.

Success means:

1. the generated USDA is recognized by UE as a **Nanite Assembly**,
2. the imported asset is specifically a **skeletal** Nanite Assembly when requested,
3. repeated foliage parts are represented via **USD instancing / PointInstancer** rather than baked unique geometry,
4. skeleton-driven behavior survives import,
5. the pipeline is reproducible and regression-tested against real sample XML files.

---

## Read this first

### Hard truth

There are two areas where guessing is unacceptable:

1. **UE-specific USD schema details** for Nanite Assemblies  
2. the **observed structure** of real SpeedTree Raw XML exports

If anything conflicts between theory and actual UE import behavior, **UE import behavior wins**.

---

## Source of truth order

When implementing, trust sources in this order:

1. **Actual successful import in Unreal Engine 5.7.x**
2. UE local files inside the installed engine, especially:  
   `Engine/Plugins/Runtime/USDCore/Resources/UsdResources/<platform>/plugins/unreal/resources/unreal/schema.usda`
3. UE importer code and plugin source
4. Official Epic docs/tutorials/forum replies from Epic staff
5. OpenUSD official docs for generic USD / UsdSkel / PointInstancer behavior
6. Real SpeedTree XML exports collected for this project
7. Community writeups only as hints, never as final authority

---

## Project goal in one sentence

Recover enough structure from SpeedTree Raw XML to author USDA that encodes:

- a valid **assembly root**
- a valid **skeletal base mesh + skeleton**
- valid **repeated parts**
- valid **skeletal binding info** for those parts
- correct units, axes, transforms, and references

so UE 5.7 imports the result as a **Skeletal Nanite Assembly**.

---

## Non-goals

Do **not** drift into these unless explicitly added later:

- generic DCC USD export
- full SpeedTree editor compatibility
- perfect preservation of every SpeedTree feature
- wind simulation authoring beyond what is required for working UE import
- full material authoring if placeholder material binding is enough for validation
- optimizing for every UE version; target is **5.7.x first**
- supporting every XML variant before the golden sample set is stabilized

---

## Required mindset

Agents working in this repo must behave like reverse-engineering pipeline engineers.

That means:

- do not invent schema names
- do not assume undocumented attributes
- do not assume XML layout stability across SpeedTree versions
- do not over-generalize from one working example
- do not call a file “correct USDA” unless it imports correctly in UE 5.7.x

Every important behavior must be backed by one of:

- engine schema inspection,
- engine source inspection,
- or a passing import test.

---

## Definitions

### Skeletal Nanite Assembly
A UE 5.7 asset built from USD-authored assembly structure, where the assembly is treated as **skeletal**, using a base skeletal mesh and skeleton, plus repeated parts driven by assembly binding logic.

### Base mesh
The mesh UE expects as the main skeletal base for the assembly. For trees this is usually trunk/base structure. Current evidence indicates that skeletal assembly import expects **real base geometry**.

### Parts
Repeated geometry elements such as branches, twigs, leaf clusters, or leaves.

### Prototype
A reusable USD subtree used by a PointInstancer.

### Golden sample
A real input/output pair used as a locked regression example:
- input: SpeedTree Raw XML + any referenced geometry data
- output: known-good USDA
- result: verified UE import

---

## Absolute constraints

### 1. UE import is the final validator
A USDA file that is theoretically valid USD but does **not** import as the intended UE asset is a failure.

### 2. Never guess UE schema fields
UE-specific API schemas such as:
- `NaniteAssemblyRootAPI`
- `NaniteAssemblyExternalRefAPI`
- `NaniteAssemblySkelBindingAPI`

must be verified from local engine schema files and/or importer source.

### 3. Never assume SpeedTree XML schema is formally documented
Treat it as an **observed schema** built from real exports.

### 4. Determinism is mandatory
Given the same XML input and the same config, the converter must emit byte-stable or logically stable USDA.

### 5. The code must be inspectable
No opaque pipeline steps. Every mapping rule must be represented in code and documented.

---

## Target repository outputs

The repo should ultimately contain:

- the converter CLI
- schema inspection notes for UE
- observed XML schema notes for SpeedTree samples
- golden sample inputs
- generated USDA outputs
- automated validation scripts
- test fixtures
- debugging docs
- import checklist for UE 5.7.x

Recommended structure:

```text
/AGENTS.md
/README.md
/docs/
  ue_schema_notes.md
  speedtree_xml_observed_schema.md
  usd_structure_notes.md
  import_validation.md
/samples/
  speedtree/
  expected_usda/
  expected_reports/
/src/
  xml_parser/
  domain_model/
  usd_writer/
  ue_validation/
  cli/
/tests/
  unit/
  integration/
  golden/
```

---

## Minimum functional target

The first working milestone is **not** full production coverage.

The first meaningful milestone is:

1. one real tree XML export,
2. one valid generated USDA,
3. successful import into UE 5.7.x as a **skeletal Nanite Assembly**,
4. repeated parts represented as instances, not exploded unique geometry,
5. transforms visually correct,
6. skeleton recognized and bound correctly enough for assembly import.

Only after that should the system be generalized.

---

## Expected UE-side structure

Current evidence indicates the USDA must conceptually look like this:

- assembly root prim
  - has `NaniteAssemblyRootAPI`
  - indicates skeletal mesh assembly mode
- trunk/base `SkelRoot`
  - contains actual base geometry
  - contains `Skeleton`
- one or more `PointInstancer` prims
  - represent repeated parts
  - use prototypes
  - carry UE skeletal assembly binding information
- optional referenced or external prototype assets where appropriate

This is a conceptual skeleton only. The exact field names and relationships must be taken from UE schema files and validated in import tests.

---

## Known implementation realities

### Base geometry requirement
Treat it as a current project assumption that skeletal assembly import in UE 5.7 requires actual base mesh geometry.  
If the source asset has no meaningful trunk/base mesh, plan for a configurable fallback base mesh strategy.

### Rigid part behavior
Assume assembly parts are effectively rigidly driven, not freely deforming like a classic skinned mesh segment, unless engine tests prove otherwise.  
Design branch segmentation with this in mind.

### Units and up-axis
Default authoring target should be:

- `metersPerUnit = 0.01`
- `upAxis = "Z"`

unless a verified sample demonstrates a better mapping.

### Instancing
Leaves / leaf clusters / repeated branch pieces should preferentially be represented with `UsdGeomPointInstancer` rather than duplicated mesh prims.

---

## Required workstreams

## Workstream A — collect engine truth

Before building serious logic, extract and document:

1. all relevant UE schema entries from local `schema.usda`
2. exact attribute names
3. exact relationship names
4. expected types
5. which fields are required vs optional
6. which prims these APIs are expected to be applied to
7. importer behavior differences between:
   - legacy USD import
   - Interchange USD import

Deliverable:
`docs/ue_schema_notes.md`

This file must contain exact copied schema names and human explanations.

---

## Workstream B — collect real XML truth

Build a corpus of real SpeedTree Raw XML files from multiple asset classes:

- trunked tree
- bush/shrub
- ground vegetation
- simple leaf-heavy asset
- branch-heavy asset

For each sample, record:

- SpeedTree version
- export settings
- whether bones/skeleton were enabled
- whether leaf references were enabled
- whether branch spines were enabled
- all external files the export depends on

Then reverse-map the observed XML into a normalized internal data model.

Deliverable:
`docs/speedtree_xml_observed_schema.md`

This is not a speculative XSD. It is a field guide based on observed samples.

---

## Workstream C — define internal domain model

Do not write USDA directly from raw XML traversal.

Create a normalized internal model with explicit entities such as:

- `TreeAsset`
- `Skeleton`
- `Joint`
- `BaseMesh`
- `Prototype`
- `InstanceSet`
- `Instance`
- `Binding`
- `MaterialRef`
- `ExportMetadata`

The internal model must separate:
- source parsing concerns
- normalization concerns
- USDA writing concerns

This will prevent the converter from becoming an unreadable XML walker.

---

## Workstream D — author USDA

Implement USDA writing from the normalized domain model.

The writer must support:

- stage metadata
- prim hierarchy emission
- API schema application
- generic USD relationships and attributes
- `SkelRoot` / `Skeleton`
- `PointInstancer`
- prototype scopes
- internal or external prototype definition strategies
- stable prim naming
- stable path generation
- comments/debug output in dev mode if useful

The writer must have a **strict mode** that fails on missing required data rather than silently emitting broken USDA.

---

## Workstream E — validation loop

Create an automated or semi-automated validation loop:

1. generate USDA
2. import into UE 5.7.x
3. capture logs
4. export result or inspect created asset
5. compare against expected conditions

Validation is not complete until it checks:

- asset imported as Nanite Assembly
- asset imported as skeletal assembly when expected
- skeleton exists
- instance counts match expectations
- prototype counts match expectations
- transforms are sane
- scale/orientation are sane
- missing base geometry errors are surfaced clearly
- binding errors are surfaced clearly

---

## Internal data model requirements

The normalized model must represent at least:

### Asset-level metadata
- source file
- SpeedTree version if discoverable
- export settings if discoverable
- authoring coordinate system if discoverable
- source scale if discoverable

### Skeleton data
- joint names
- joint hierarchy
- parent indices or paths
- local transforms
- bind or rest transforms if present
- mapping from source branch/leaf structures to joints

### Base mesh data
- geometry identity
- topology source
- material assignments
- transform space
- skinning data if relevant

### Prototype data
- unique prototype ID
- prototype type: branch / twig / leaf / cluster / other
- referenced mesh source
- local pivot
- local orientation basis
- any per-prototype binding defaults

### Instance data
- prototype index
- position
- orientation
- scale
- optional visibility/activation
- source provenance for debugging

### Binding data
- instance → joint mapping
- weights
- whether mapping is rigid single-joint or multi-joint
- provenance of how the mapping was derived

---

## Mapping rules the converter must make explicit

The converter must explicitly document and implement how it decides:

### 1. What becomes the base skeletal mesh
Usually trunk/base structure, but must be rule-based, not ad hoc.

### 2. What becomes a prototype
The converter must define deduplication rules for repeated parts.

### 3. What becomes an instance
If multiple XML elements reference the same reusable geometry, this must collapse into prototype + instances where possible.

### 4. How joints are assigned to parts
Do not bury this logic. It must be a named strategy.

Possible strategies may include:
- nearest joint
- owning branch joint
- source-declared anchor joint
- branch-spine segment joint

The chosen rule must be testable and configurable if necessary.

### 5. How local transforms are converted
Every coordinate conversion must be explicit:
- handedness
- axis remap
- rotation convention
- scale convention
- pivot convention

### 6. How missing data is handled
If XML lacks a required value:
- fail,
- synthesize,
- or fallback

This must be deliberate and logged.

---

## Coordinate and transform rules

Treat coordinate conversion as a first-class subsystem.

The repo must include utility code and tests for:

- axis remapping
- matrix decomposition/recomposition
- quaternion conversion
- pivot-relative transform handling
- local-to-parent vs local-to-world conversion
- scale inheritance
- stable float formatting for USDA

Never mix transform-space assumptions across the codebase.

For each sample, be able to answer:
- was this source transform local or world?
- relative to which parent?
- before or after pivot offset?
- before or after unit conversion?

If this is not known, the code should expose the ambiguity instead of masking it.

---

## SpeedTree-specific assumptions to verify

These are working hypotheses, not permanent truths. Each must be verified against real samples:

1. Raw XML can contain enough data to reconstruct skeleton and leaf references.
2. Leaf references can be converted to PointInstancer instances.
3. Branch spines can help derive branch segmentation or joint mapping.
4. Repeated branch/twig structures may be recoverable as reusable prototypes in some exports.
5. Source XML structure may differ significantly by asset type and export settings.

Whenever a hypothesis is confirmed or disproven, update the docs.

---

## USDA authoring rules

### Stage metadata
Default to:

```usda
#usda 1.0
(
    defaultPrim = "Tree"
    metersPerUnit = 0.01
    upAxis = "Z"
)
```

unless a validated case requires otherwise.

### Naming
Prim names must be:
- deterministic
- ASCII-safe
- stable across runs
- human-readable

Use stable path patterns such as:

- `/Tree`
- `/Tree/TrunkSkelRoot`
- `/Tree/TrunkSkelRoot/TrunkMesh`
- `/Tree/TrunkSkelRoot/TrunkSkeleton`
- `/Tree/PartsInstancer`
- `/Tree/PartsInstancer/Prototypes/...`

### Separation of concerns
Prefer authoring assembly structure separately from prototype library structure when it improves clarity, but keep single-file output available for debugging.

### Debuggability
In development mode, the emitted USDA may include comments indicating:
- source XML IDs
- deduplication choices
- joint binding derivation
- fallback behavior

---

## Unreal-specific schema policy

Any UE-specific field must be added only after it is verified.

For each UE-specific field used by the converter, document:

- exact authored name
- exact USD type
- prim type it belongs on
- whether it is required
- proof source:
  - schema file
  - importer source
  - working example

Maintain this in `docs/ue_schema_notes.md`.

---

## Import pipeline policy

The project must define a single preferred validation target:

- UE version
- plugin configuration
- importer mode

At minimum, record:
- whether Interchange USD is enabled
- whether legacy USD import path is being used
- required CVars or project settings if any
- exact import route used during tests

Do not claim compatibility with both importers unless both are tested.

---

## Required experiments

The following experiments are mandatory.

### Experiment 1 — minimal skeletal assembly
Author the smallest possible USDA that UE 5.7 imports as a skeletal Nanite Assembly.

Goal:
identify the minimum required prims, schemas, and fields.

### Experiment 2 — one prototype, one instance
Confirm the smallest possible PointInstancer + binding setup that survives skeletal assembly import.

### Experiment 3 — multiple instances, one joint
Confirm rigid binding of repeated parts to one joint.

### Experiment 4 — multiple instances, multiple joints
Test whether multi-joint weighting is meaningful or required for assembly parts.

### Experiment 5 — no real base mesh
Test failure mode and fallback base-mesh workaround.

### Experiment 6 — axis/unit mismatch
Deliberately perturb units and axes to prove transform conversion tests detect the problem.

### Experiment 7 — external prototype references
Compare embedded prototypes vs referenced prototypes.

---

## Failure policy

Do not silently “best effort” critical data.

The converter must fail loudly when it cannot safely determine:

- skeleton hierarchy
- instance transform
- required prototype identity
- required UE schema fields
- required binding data

Errors must include:
- source XML location if possible
- which rule failed
- what assumption was missing

---

## Logging policy

Provide structured logs for:

- sample identification
- source parsing summary
- skeleton extraction summary
- prototype extraction summary
- instance count summary
- binding summary
- emitted prim count
- warnings
- fallbacks used

Useful debug output beats terse output.

---

## Testing requirements

### Unit tests
Required for:
- XML normalization helpers
- transform conversion
- quaternion conversion
- stable naming/path generation
- prototype deduplication
- joint assignment logic
- USDA formatting helpers

### Golden tests
Given a fixed XML sample and config:
- generated USDA must match expected logical structure
- instance counts must match
- skeleton topology must match
- stable important text sections must match

### Integration tests
At minimum, support a scripted workflow that:
- generates USDA
- runs validation checklist against imported UE asset
- records pass/fail and logs

If full automated UE import is not possible immediately, create a reproducible semi-automated harness.

---

## Definition of done

A milestone is **done** only if all are true:

1. at least one real SpeedTree XML sample imports into UE 5.7.x as intended,
2. the USDA was generated entirely by the converter,
3. the generated USDA uses verified UE schema fields only,
4. repeated foliage parts are instanced,
5. transforms are correct in orientation, scale, and placement,
6. the repository contains tests that would catch regression,
7. the docs explain the exact mapping rules,
8. the result can be reproduced by another engineer without hidden steps.

---

## Immediate execution order

Agents should execute in this order:

1. inspect local UE `schema.usda`
2. inspect local UE importer source
3. build `ue_schema_notes.md`
4. collect real SpeedTree XML samples
5. build `speedtree_xml_observed_schema.md`
6. define normalized domain model
7. implement minimal XML parser
8. implement minimal USDA writer
9. pass minimal skeletal assembly experiment
10. iterate until one real tree sample imports successfully
11. only then generalize

Do not start with “full converter architecture” before steps 1–5 are grounded.

---

## Prohibited shortcuts

Do not do any of the following:

- hardcode guessed schema attributes from memory
- bake all leaves/branches into unique mesh copies just to get a visible result
- call a static assembly solution “skeletal” because it imports
- hide transform bugs with ad hoc corrective offsets without documenting why
- ship support for multiple SpeedTree versions without sample coverage
- conflate source-space, local-space, and world-space transforms
- silently auto-create fallback geometry without logging it
- trust a community snippet over engine schema inspection

---

## Deliverables expected from agents

Every major task should leave behind one of:

- code
- a markdown note
- a regression sample
- a failing test that defines the next problem
- a passing import proof

No “I investigated” work without an artifact.

---

## First deliverables to produce now

1. `docs/ue_schema_notes.md`  
   Extract exact UE Nanite Assembly schema details.

2. `docs/speedtree_xml_observed_schema.md`  
   Document real XML samples and observed fields.

3. `docs/import_validation.md`  
   Step-by-step checklist for validating generated USDA in UE 5.7.x.

4. Minimal CLI:
   ```bash
   converter input.xml --out tree.usda
   ```

5. One golden sample that passes end-to-end.

---

## Final rule

This project is an **engine-validated reverse-engineering pipeline**, not a speculative format converter.

If forced to choose between:
- elegant abstraction,
- official-looking theory,
- and what UE 5.7 actually imports,

choose **what UE 5.7 actually imports**.
