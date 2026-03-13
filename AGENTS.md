# AGENTS.md

## Mission

Build a **deterministic converter** from **SpeedTree Raw XML** to **USDA** that Unreal Engine **5.7.x** imports as a **Skeletal Nanite Assembly**.

This is **not** a generic XML→USD tool.  
It is a **UE 5.7 Skeletal Nanite Assembly authoring pipeline**.

Success means:

1. UE imports the generated USDA as a **Nanite Assembly**.
2. Skeletal mode is used when requested.
3. Repeated parts use **instancing / PointInstancer**, not duplicated meshes.
4. Skeleton/base mesh/bindings survive import.
5. The result is reproducible and regression-tested.

---

## Source of truth order

When something conflicts, trust in this order:

1. **Actual successful import in UE 5.7.x**
2. UE local schema file:  
   `Engine/Plugins/Runtime/USDCore/Resources/UsdResources/<platform>/plugins/unreal/resources/unreal/schema.usda`
3. UE importer/plugin source
4. Official Epic docs/tutorials/forum replies from Epic staff
5. OpenUSD docs
6. Real SpeedTree XML samples
7. Community sources only as hints

If theory and UE behavior disagree, **UE behavior wins**.

---

## Critical rules

### Never guess
Do **not** invent:

- UE schema names
- UE attribute names
- relationship names
- XML field meanings
- undocumented transform conventions

Every important rule must come from:
- schema inspection,
- source inspection,
- or a passing UE import test.

### Determinism is mandatory
Same input + same config = same logical USDA output.

### A valid USD file is not enough
If UE does not import it as the intended asset, it is a failure.

### Treat SpeedTree XML as observed schema
Do not assume a formal stable public specification. Build against **real samples**.

---

## Mandatory use of `vault`

There is a folder named **`vault`** in this project.

Agents **must** use `vault` as a primary comparison source during development.

Inside `vault` there may be:
- working `.usda` examples
- broken `.usda` examples
- USD snippets
- XML examples
- schema notes
- logs
- experimental files
- other reference material

### Required behavior around `vault`

1. Before making structural decisions, inspect relevant files in `vault`.
2. Compare generated USDA against known-good examples from `vault`.
3. Compare source XML against existing XML examples in `vault`.
4. Reuse naming, hierarchy, schema placement, and authoring patterns from verified `vault` examples when applicable.
5. If code behavior differs from a working `vault` example, explain why in code comments or docs.
6. Do not ignore `vault` just because a more elegant abstraction exists.

If a working example exists in `vault`, it has higher practical value than speculation.

---

## Target structure to generate

The USDA is expected to contain, conceptually:

- an **assembly root**
  - with `NaniteAssemblyRootAPI`
  - skeletal mesh assembly mode
- a **base `SkelRoot`**
  - real base geometry
  - a `Skeleton`
- one or more **`PointInstancer`** prims
  - repeated parts
  - prototypes
  - skeletal assembly binding info
- optional external refs where appropriate

Exact field names must be verified from UE schema files and working examples.

---

## Current working assumptions

Use these unless testing disproves them:

- skeletal assembly import in UE 5.7 needs **real base geometry**
- parts are effectively **rigidly driven**, not freely deforming
- default stage metadata should be:
  - `metersPerUnit = 0.01`
  - `upAxis = "Z"`
- repeated leaves/twigs/branches should prefer **`UsdGeomPointInstancer`**

---

## Required work order

Agents should work in this order:

1. inspect UE `schema.usda`
2. inspect UE importer source
3. inspect relevant examples inside `vault`
4. collect real SpeedTree XML samples
5. define normalized internal data model
6. implement XML parser
7. implement USDA writer
8. validate in UE 5.7.x
9. only then generalize

Do **not** start by designing a large abstract architecture before steps 1–4 are grounded.

---

## Internal model requirements

Do not write USDA directly from raw XML traversal.

Create a normalized model with entities such as:

- `TreeAsset`
- `Skeleton`
- `Joint`
- `BaseMesh`
- `Prototype`
- `InstanceSet`
- `Instance`
- `Binding`

The model must separate:

- XML parsing
- normalization
- USDA writing

---

## Mapping rules that must be explicit

The converter must make these decisions explicitly and in code:

1. what becomes the **base skeletal mesh**
2. what becomes a **prototype**
3. what becomes an **instance**
4. how parts are assigned to **joints**
5. how transforms are converted
6. how missing data is handled

No hidden heuristics.

---

## Transform policy

Treat transforms as a first-class subsystem.

Must be tested:

- axis remap
- handedness
- matrix decomposition/recomposition
- quaternion conversion
- pivot handling
- local vs parent vs world transforms
- scale inheritance

Never hide transform bugs with arbitrary corrective offsets.

---

## Validation loop

A change is not accepted until it is validated against UE.

Minimum loop:

1. generate USDA
2. import into UE 5.7.x
3. inspect logs/result
4. compare against expectations and `vault` examples

Validation must confirm:

- imported as Nanite Assembly
- imported as skeletal assembly when expected
- skeleton exists
- instance counts match
- transforms are sane
- bindings are sane

---

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

Do **not** silently emit broken USDA.

---

## Testing requirements

### Unit tests
Required for:
- XML normalization
- transform conversion
- naming/path generation
- prototype deduplication
- joint assignment
- USDA formatting helpers

### Golden tests
Given fixed XML/config:
- output USDA must be logically stable
- skeleton topology must match
- instance counts must match

### Reference comparison tests
Generated output should be compared against relevant known-good files from **`vault`** whenever possible.

---

## Definition of done

A milestone is done only if:

1. a real SpeedTree XML sample imports into UE 5.7.x as intended
2. USDA is generated entirely by the converter
3. only verified UE schema fields are used
4. repeated parts are instanced
5. transforms are correct
6. tests catch regressions
7. mapping rules are documented
8. the result is reproducible by another engineer

---

## Prohibited shortcuts

Do not:

- guess UE schema attributes from memory
- bake all repeated parts into unique meshes
- call a static assembly “skeletal”
- ignore `vault` examples
- mix local/world/source transform spaces
- silently create fallback geometry without logging it
- trust community snippets over schema inspection and working imports

---

## Minimum first deliverables

1. `docs/ue_schema_notes.md`
2. `docs/speedtree_xml_observed_schema.md`
3. `docs/import_validation.md`
4. minimal CLI:
   ```bash
   converter input.xml --out tree.usda
   ```
5. one working golden sample
6. one comparison note referencing the relevant files from `vault`

---

## Final rule

This project is an **engine-validated reverse-engineering pipeline**.

If forced to choose between:
- elegant abstraction,
- theoretical correctness,
- and what UE 5.7 actually imports,

choose **what UE 5.7 actually imports**.
