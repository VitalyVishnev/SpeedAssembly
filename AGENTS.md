# AGENTS.md

## Mission

Build a deterministic converter from SpeedTree Raw XML to USDA that Unreal Engine 5.7.x imports as a Skeletal Nanite Assembly for the vegetation pipeline.

This is not a generic XML-to-USD tool. It is a UE 5.7 skeletal tree assembly authoring pipeline.

Success means:

1. UE imports the generated USDA as a Nanite Assembly.
2. The primary path imports in skeletal mode.
3. All unique tree geometry survives as the Base Skeletal Tree.
4. Repeated parts import through PointInstancer as Assembly Parts, not duplicated meshes.
5. The result is reproducible and regression-tested.

Static Mesh Assemblies are supported as a secondary export mode, but they must not weaken the skeletal baseline.

For `static_assembly`, success means UE imports the generated USDA as a Static Mesh Nanite Assembly with rigid repeated parts through PointInstancer.

## Documentation contract

Use these docs in this order:

1. `AGENTS.md`
2. `docs/ue_import_contract.md`
3. `docs/speedtree_mapping.md`
4. `docs/workflow_status.md`
5. `docs/local-python-environment.md`

If these documents conflict, this order wins.

For architecture reviews, use:

1. `docs/PROJECT_MAP.md`
2. `docs/GLOSSARY.md`
3. `docs/ARCHITECTURE.md`
4. `docs/DECISIONS.md`

These files carry the terminology, module map, and decision log. Do not duplicate that material here.

## Source of truth order

When docs conflict with reality, trust:

1. Actual successful import in UE 5.7.x
2. UE local schema files
3. UE importer/plugin source
4. Official Epic docs/tutorials/forum replies from Epic staff
5. OpenUSD docs
6. Real SpeedTree XML samples
7. Community sources only as hints

If theory and UE behavior disagree, UE behavior wins.

## Engineering policy

1. Keep modules focused, explicit, and testable.
2. Keep XML parsing, normalization, USDA authoring, validation, FBX import, material resolution, CLI, GUI, and runtime orchestration separated.
3. Route cross-cutting behavior through explicit contracts and shared domain models.
4. Keep side effects at the edges. Core transformation logic should stay deterministic and inspectable.
5. Prefer extending the normalized model or module contract over stacking one-off conditionals.
6. Hardcoded values are acceptable only when backed by verified UE contract, verified observed source pattern, or documented runtime constraint.
7. If a hardcoded rule exists because importer contract requires it, document that reason near the code or in project docs.

## Contract discipline

1. Do not invent UE schema names, USD attributes, relationship names, XML field meanings, or undocumented transform conventions.
2. Do not write USDA directly from raw XML traversal. Use source parsing, normalization, resolution, validation, and authoring stages.
3. Same input plus same config must produce the same logical USDA output.
4. A syntactically valid USD file is not enough. UE must import it as the intended asset.
5. Treat SpeedTree XML as observed schema built from real samples, not as a stable public specification.
6. If implementation requires an unresolved structural, architectural, or importer-contract decision, stop and ask before coding.

## Vocabulary

Use the canonical terms from `docs/GLOSSARY.md`.

Do not restate or rename those terms here unless this file needs a short mission-level reminder.

## Vault use

`vault` is a primary comparison source during development.

1. Inspect relevant `vault` files before structural decisions.
2. Compare generated USDA against known-good `vault` examples.
3. Compare source XML against existing `vault` XML examples.
4. Reuse verified naming, hierarchy, schema placement, and authoring patterns when applicable.
5. If code behavior differs from a working `vault` example, explain why in code comments or docs.

## Required work order

When changing importer-facing behavior:

1. inspect UE schema files
2. inspect UE importer source
3. inspect relevant `vault` examples
4. inspect real SpeedTree XML samples
5. define or adjust the normalized internal model
6. implement parsing or resolution changes
7. implement USDA writing changes
8. validate in UE 5.7.x
9. only then generalize

## Validation loop

A change is not accepted until it is validated against UE:

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
- modules and files should stay focused
- functions should be small enough that their invariant, side effects, and error behavior are easy to understand
- control flow should be straightforward and reviewable
- duplicated logic should be consolidated behind one owned abstraction when it represents the same rule
- invariants, assumptions, and failure paths should be explicit
- hidden mutable state should be minimized
- comments should explain why a non-obvious rule exists, especially when it comes from UE behavior or a verified `vault` pattern
- touched code should become more coherent, not less, after a change
- every non-trivial change should land with the right tests for its layer instead of relying on manual memory

Code that is fast to patch but hard to reason about is not a successful implementation.

## Simplicity and Architecture Requirements

1. Prefer the simplest working solution.
   Solve the task with the least necessary complexity. After implementing a module or feature, review it once specifically to identify what can be simplified, removed, merged, or expressed more directly. Do not add abstraction, configuration, indirection, or generic systems unless they clearly solve a real current need.

2. Aim for deep modules, not shallow modules.
   Keep architecture clean by designing modules with simple interfaces and meaningful internal responsibility. A good module should hide complexity behind a small, clear API. Avoid shallow modules that add many files, layers, wrappers, or concepts while providing little actual simplification. Prefer fewer stronger boundaries over many weak ones.

3. Track postponed issues explicitly.
   If any known problem, limitation, incomplete edge case, technical debt, or “fix later” item remains after a change, record it in `KNOWN_PROBLEMS.md`. Include a short description of the issue, where it appears, why it was postponed, and what likely needs to be done later. Do not rely on memory or comments hidden in code for unfinished work.


## Testing requirements

Required tests:

- XML normalization
- transform conversion
- naming and path generation
- prototype deduplication
- joint assignment
- USDA formatting helpers

Transform tests must cover:

- axis remap
- handedness
- matrix decomposition and recomposition
- quaternion conversion
- pivot handling
- local vs parent vs world transforms
- scale inheritance

For fixed XML and config:

- output USDA must be logically stable
- skeleton topology must match
- instance counts must match

Compare generated output against relevant known-good files from `vault` whenever possible.

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
- use a temporary architectural shortcut when the correct contract is still unknown
- silently create fallback geometry without logging it
- trust community snippets over schema inspection and working imports

## Minimum documentation set

The compact project docs set is:

1. `AGENTS.md`
2. `docs/ue_import_contract.md`
3. `docs/speedtree_mapping.md`
4. `docs/workflow_status.md`
5. `docs/local-python-environment.md`

The architecture-review docs set is:

1. `docs/PROJECT_MAP.md`
2. `docs/GLOSSARY.md`
3. `docs/ARCHITECTURE.md`
4. `docs/DECISIONS.md`

## Final rule

If forced to choose between elegant abstraction, theoretical correctness, and what UE 5.7 actually imports, choose what UE 5.7 actually imports.
