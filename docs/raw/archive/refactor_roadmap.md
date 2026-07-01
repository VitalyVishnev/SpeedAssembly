# Refactor Roadmap

## Status

This roadmap is **completed** and kept as an **archived planning document**.

Stages `0` through `6` were completed during the major refactor cycle.

Use this file as historical context for why the architecture was reshaped.
Do not treat it as the current active work queue.

For the current project structure, use `docs/developer_architecture.md`.

## Role

This document is the persistent project roadmap for architectural refactoring.

It exists so refactor decisions, priorities, and execution order do not depend on one chat session.

This document is planning and execution guidance for engineering work.
It does not override importer-facing requirements from:

1. `AGENTS.md`
2. `docs/ue_import_contract.md`
3. `docs/speedtree_mapping.md`
4. `docs/workflow_status.md`

If a refactor idea conflicts with the verified UE import contract or a currently passing workflow, the verified UE behavior wins.

## Refactor goal

Refactor the project toward **one modular conversion system** with:

- one core conversion model
- one conversion contract
- one USDA authoring contract
- one validation contract
- one application-facing request/result contract
- one UI-independent orchestration layer

The target architecture is **not**:

- one code path for small files
- another code path for huge files
- another code path for GUI-safe execution

The target architecture **is**:

- one conversion system
- one set of business rules
- one set of domain models
- one set of exporter rules
- different execution strategies when runtime conditions require them

Examples of acceptable execution-strategy differences:

- in-process vs subprocess execution
- sequential vs parallel prototype import
- string-backed output vs streaming file output

These are runtime strategies, not separate business systems.

## Architectural target

The project should converge on the following shape:

1. **Domain layer**
   Pure conversion concepts and rules.
2. **Application layer**
   Orchestration of use cases and execution policies.
3. **Infrastructure layer**
   FBX backend, filesystem, process management, runtime temp data, output sinks.
4. **UI layer**
   Thin adapter over application services and view models.

The UI must not be the place where conversion semantics live.

The conversion core must remain usable without the GUI.

## Non-negotiable refactor principles

### One core system, not two parallel systems

Refactoring must reduce duplicated business logic.

Do not preserve separate "normal" and "heavy" implementations when the difference is only execution style.

### Runtime strategy is allowed

Different runtime execution strategies are allowed when they do not change conversion semantics.

Allowed examples:

- `sync` vs `subprocess`
- `sequential` vs `parallel workers`
- `render to memory` vs `stream to disk`

These must share the same domain logic and authoring logic.

### Verified behavior must not regress

A refactor is not successful if it improves architecture but changes verified importer-facing behavior without explicit validation and acceptance.

### UI independence is a hard target

Future UI work must be able to evolve without changing core conversion logic.

Likewise, conversion internals should be able to evolve without forcing unrelated UI rewrites.

### No speculative cleanup

Do not rewrite code "for cleanliness" without:

- a defined boundary improvement
- a regression test
- a clear reduction in duplication, coupling, or ambiguity

## Current architectural risks

The current refactor is driven by these known risks:

1. `gui.py` is too large and mixes layout, state, persistence, validation, orchestration, and formatting.
2. `usda_writer.py` contains duplicated authoring behavior across normal and streaming paths.
3. `pipeline.py` mixes orchestration, validation, runtime concerns, and helper policy logic.
4. Some shared rules are duplicated across modules instead of living behind one contract.
5. Legacy compatibility paths still exist and need to be isolated and eventually reduced.
6. Code-level documentation and explicit public module contracts are weaker than project-level docs.

## Refactor execution order

Work in this order unless a verified production issue forces reprioritization:

1. strengthen regression coverage around current behavior
2. extract shared rule helpers and remove contract duplication
3. introduce an application/service layer between UI and core conversion
4. split orchestration from pure conversion flow
5. unify USDA authoring into one engine with different output sinks
6. split the GUI into thin modules and panels
7. reduce legacy compatibility paths and improve internal code documentation

Do not start by rewriting the GUI first.

Do not start by rewriting everything into a new architecture in one pass.

## Stage 0 - Lock the current behavior

### Objective

Before structural refactoring, capture the current validated behavior so that future changes cannot silently drift.

### Why this stage exists

The project currently works on real heavy jobs.
That working behavior is valuable and must be protected before module boundaries are changed.

### Required work

- add characterization tests for current successful conversion paths
- add coverage for sync conversion and subprocess conversion
- add coverage for standard USDA writing and streaming USDA writing
- add coverage for prototype source modes:
  - XML mesh
  - Unreal external asset
  - explicit FBX file
- add contract comparisons where two execution modes should produce the same logical result
- add GUI-adjacent tests that validate request assembly from UI state without needing full interactive workflows

### Deliverables

- stronger regression tests around existing working behavior
- at least one comparison test proving normal export and streaming export are logically equivalent for the same model
- test coverage that protects huge-job execution assumptions
- a documented manual stress procedure in `docs/stage0_stress_validation.md`

### Definition of done

This stage is done only when refactor work can safely detect regressions in:

- importer-facing USDA structure
- request-to-result behavior
- runtime execution mode differences
- external prototype handling
- material-policy handling

## Stage 1 - Extract shared contracts and rule helpers

### Objective

Create one source of truth for shared rules that are currently duplicated or imported from the wrong layer.

### Why this stage exists

The same semantic rule should not be implemented separately in GUI, pipeline, and validator code.

### Required work

- extract Unreal asset-path normalization and validation into one shared module
- extract prototype-source key normalization into one shared module
- extract generator-label parsing and related wind helper rules into one shared module
- stop importing private helper functions across layers
- make shared rule helpers explicit and public where they are intentionally reusable

### Expected boundary result

- UI, pipeline, validator, and prototype-source code use the same helper contract
- `pipeline.py` no longer depends on private internals from `normalizer.py`

### Definition of done

This stage is done only when:

- duplicated rule helpers are removed
- shared rule behavior is covered by tests
- no cross-layer dependency relies on another module's private helper as part of a stable flow

## Stage 2 - Introduce the application layer

### Objective

Place a proper application/service layer between UI and conversion internals.

### Why this stage exists

The GUI should not be responsible for business orchestration or request semantics.

### Required work

- define application-facing use cases or services for:
  - conversion
  - wind inspection/generation
  - prototype discovery
  - material discovery
  - settings persistence
- move request-building and request-validation logic out of the GUI where appropriate
- keep `ConversionRequest`, `ConversionResult`, and related typed models as stable application contracts
- make the GUI consume services rather than directly orchestrating most pipeline behavior

### Expected boundary result

- the UI becomes a thin adapter over typed application services
- core conversion remains callable from CLI, subprocess worker, tests, and future UI layers

### Definition of done

This stage is done only when:

- major conversion actions can be initiated without GUI-specific code
- GUI code is materially smaller in responsibility even if not yet split across files
- application services have tests independent of the widget tree

## Stage 3 - Separate orchestration from pure conversion

### Objective

Turn the current pipeline into a clear coordinator rather than a large mixed-responsibility module.

### Why this stage exists

Orchestration concerns and pure conversion concerns should not be blended if we want long-term maintainability.

### Required work

- split request validation from conversion orchestration
- split output-path resolution from conversion semantics
- split wind-loading helpers from unrelated pipeline duties
- isolate runtime workspace/cleanup and telemetry wrapping from domain flow
- keep `pipeline.py` as a small facade if useful, but move heavy implementation into focused modules

### Expected boundary result

- clearer conversion flow
- easier unit testing per stage
- lower coupling between runtime concerns and conversion logic

### Definition of done

This stage is done only when:

- conversion orchestration is readable as a short sequence of explicit steps
- runtime concerns are no longer interleaved with unrelated domain logic
- the same orchestrator can be reused by CLI and background worker execution

## Stage 4 - Unify USDA authoring

### Objective

Replace duplicated normal-vs-streaming USDA logic with one authoring engine and different sinks.

### Why this stage exists

This is the biggest current source of hidden duplication and future exporter drift.

### Required work

- design one authoring flow for USDA structure
- separate "what gets authored" from "where it is written"
- use different sinks or emit targets for:
  - in-memory text
  - streaming file output
- factor large prim-authoring blocks into reusable emitters:
  - assembly root
  - materials
  - base skel root
  - skeleton
  - point instancer
  - prototype subtree
  - mesh payload
  - material binding

### Expected boundary result

- exporter semantics live in one place
- streaming mode becomes an output strategy, not a second exporter implementation

### Definition of done

This stage is done only when:

- normal and streaming exports share one authoring definition
- tests prove logical equivalence across output strategies
- importer-facing USDA changes no longer require updating duplicated exporter branches

## Stage 5 - Split the GUI into thin modules

### Objective

Break the current GUI monolith into manageable, testable UI modules.

### Why this stage exists

The current GUI file is too large and mixes too many responsibilities for future UI work to stay safe.

### Required work

- split the GUI into focused modules such as:
  - app shell
  - conversion panel
  - materials panel
  - repeated-part source panel
  - wind panel
  - settings store
  - background job bridge
  - UI formatting helpers
- reduce dict-shaped ad-hoc row state where typed view models are a better fit
- isolate widget-building from persistence and request assembly
- keep Tk-specific logic out of domain/application code

### Expected boundary result

- UI changes affect only UI modules
- conversion internals are insulated from widget-tree churn

### Definition of done

This stage is done only when:

- the app shell is thin
- major panels live in separate modules
- settings persistence is not embedded in unrelated widget code
- UI tests or smoke tests can target smaller surfaces

## Stage 6 - Legacy reduction and internal documentation

### Objective

Reduce compatibility clutter and make the refactored architecture easy to understand for another engineer.

### Why this stage exists

A cleaner architecture still fails maintainability goals if it is only understandable by the person who wrote it.

### Required work

- review each active legacy alias and compatibility bridge
- explicitly keep, deprecate, or remove each one
- add module-level docstrings to major public modules
- add short public API docstrings or comments where boundaries are non-obvious
- document the final layer model for developers

### Expected boundary result

- fewer silent compatibility branches
- easier onboarding
- cleaner public/internal API distinctions
- a developer-facing architecture map is available in `docs/developer_architecture.md`

### Definition of done

This stage is done only when:

- retained legacy paths are intentional and documented
- key public modules explain their role
- a new engineer can identify domain, application, infrastructure, and UI responsibilities quickly

## Runtime strategy policy during refactor

During and after refactor, the project should keep the following architectural policy:

- there is one conversion system
- runtime may choose the safest execution strategy for the current workload
- runtime strategy must not silently change conversion semantics
- small files should not require a separate business system
- huge files should not require a separate business system

Examples:

- subprocess execution may still be required for GUI stability
- sequential fallback may still be required when process pools are unavailable
- streaming output may still be required when output size is too large for a full in-memory text blob

These are acceptable as long as they are execution strategies over a shared conversion core.

## How to use this roadmap

For each refactor task:

1. identify which stage it belongs to
2. confirm the change improves a boundary defined in this roadmap
3. add or update regression tests first when the change touches verified behavior
4. avoid cross-stage rewrites unless they are truly necessary
5. record any stage-level completion criteria that were met

If a proposed change does not clearly improve:

- modularity
- boundary clarity
- duplication reduction
- UI independence
- authoring consistency

then it should not be treated as refactor progress.

## Immediate next recommended step

Begin with **Stage 0** and only then proceed to **Stage 1**.

The first practical sequence should be:

1. strengthen behavior-locking tests
2. extract shared rule helpers
3. move request assembly and request validation toward an application layer

This sequence gives the best stability-to-refactor-value ratio for the current project state.
