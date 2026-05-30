# Test Improvement Plan

## Purpose

Improve the test suite without weakening the UE 5.7 import contract.

The goal is not fewer tests. The goal is tests that protect product behavior,
domain invariants, deterministic output, failure modes, and Runtime Job
behavior without freezing accidental implementation details.

## Current Baseline

- `pytest -q` currently passes: `303 passed, 1 skipped`.
- `tests/test_pipeline.py` is the largest risk surface: it mixes end-to-end
  contract tests, private helper tests, writer tests, FBX tests, material tests,
  and compatibility tests.
- Several tests assert exact emitted USDA text. Some of this is valid for
  importer-facing fields, but long substring blocks are brittle and weak at
  checking structure.
- Some tests protect transition facades and legacy parity rather than stable
  domain interfaces.
- Important deep modules are covered mostly indirectly.

## Non-Goals

- Do not remove contract coverage before replacement coverage exists.
- Do not rewrite tests into a generic snapshot suite.
- Do not make structural tests depend on an external USD runtime.
- Do not treat automated tests as a replacement for UE import validation.
- Do not refactor production code only to make old brittle tests pass.

## Step 1 - Freeze The Current Safety Net

Record the current test inventory before moving anything.

Actions:

- Keep the current green baseline command: `python -m pytest -q`.
- Add a short test-suite map that groups tests by intent:
  - source normalization
  - material resolution
  - assembly resolution
  - USDA authoring
  - Runtime Job / cleanup / FBX helper
  - Qt Operator State and workflow
  - compatibility facades
- Mark tests that exist only for compatibility or migration.

Done when:

- Every current high-value behavior has an owner category.
- No test has to be understood only by reading all of `test_pipeline.py`.

## Step 2 - Split `test_pipeline.py` By Real Module Seams

Move tests out of `tests/test_pipeline.py` into focused files that match the
project's interfaces.

Suggested split:

- `test_normalizer.py`
  - Source XML interpretation
  - Base Skeletal Tree extraction
  - Repeated Part discovery
  - Source Space to Stage Space conversion facts
- `test_material_resolver.py`
  - Source Material policies
  - explicit material contract
  - FBX material modes
  - vertex-color split behavior
- `test_usda_authoring_contract.py`
  - Assembly Root
  - Main Skeleton
  - Base Skeletal Tree
  - PointInstancer
  - Part Skeleton
  - required and forbidden UE fields
- `test_export_modes.py`
  - `skeletal_assembly`
  - `skeletal_parts`
  - `static_assembly`
- `test_fbx_prototype_sources.py`
  - FBX replacement payloads
  - Unreal asset reuse
  - helper/supervisor integration that is not pure Runtime Job behavior
- `test_wind_pipeline.py`
  - move remaining wind cases from `test_pipeline.py`

Keep in `test_pipeline.py` only small end-to-end smoke/regression cases that
prove the public conversion path still connects correctly.

Done when:

- `test_pipeline.py` is no longer the primary owner of module-specific behavior.
- Private imports from `normalizer`, `fbx_adapter`, and compatibility helpers are
  either gone or isolated behind a clearly justified low-level test file.

## Step 3 - Replace Brittle USDA Substring Blocks With Structural Checks

Create a small test-only USDA inventory helper.

It should parse enough USDA text to answer contract questions without becoming
a full USDA parser:

- prim path
- prim type
- applied API schemas
- authored attributes by name
- authored relationships by name
- presence or absence of forbidden fields under a subtree

Use it for assertions such as:

- Assembly Root has `NaniteAssemblyRootAPI`.
- Skeletal assembly root points to descendant Main Skeleton.
- Static Mesh Assembly has no `SkelRoot`, `Skeleton`, or `primvars:skel:*`.
- External reused Authored Prototype has `NaniteAssemblyExternalRefAPI` and no
  inline fallback `PartMesh`.
- PointInstancer has required skeletal binding primvars with expected
  `elementSize`.

Keep exact text assertions only for fields where spelling and USDA token shape
are themselves the contract.

Done when:

- Long `assert "... in usda.text"` blocks are reduced.
- Tests can detect wrong scope, duplicate prims, and missing relationships.
- Formatting-only writer changes do not break importer-contract tests.

## Step 4 - Retire Or Quarantine Legacy-Parity Tests

Some tests currently prove new paths equal old paths. That is useful during a
migration, but dangerous as a permanent requirement.

Actions:

- Move legacy/facade parity tests into a dedicated `test_compatibility_facades.py`.
- Add comments that define why each compatibility test still exists.
- Remove tests that only prove two implementation paths are identical when one
  path is no longer a supported interface.
- Stop treating `pipeline._apply_material_policy` as public surface unless it is
  intentionally documented as compatibility-only.

Done when:

- Compatibility tests protect caller stability, not internal module shape.
- No new domain behavior is added through `pipeline.py` or `usda_writer.py`
  because tests made that easiest.

## Step 5 - Move Performance Assertions Out Of Normal Pytest

Wall-clock tests are unstable in normal development runs.

Actions:

- Remove strict time assertions from normal tests, especially the UDIM hot-path
  check.
- Keep correctness assertions in normal pytest.
- Move runtime thresholds to an optional stress/benchmark marker or script.
- Use deterministic checks where possible:
  - output size equals input UV payload size
  - secondary UV channel is allocated once per payload path
  - no full MeshData conversion occurs for GeometryBuffer hot paths, if this can
    be tested through a stable seam

Done when:

- Normal pytest does not fail because of transient machine load.
- Performance regression checks still exist, but run intentionally.

## Step 6 - Add Direct Coverage For Deep Modules

Add focused tests for modules that currently rely too much on indirect pipeline
coverage.

Priority modules:

- `material_resolver.py`
  - explicit material contract
  - Source Material vs Resolved Material Assignment separation
  - FBX `single_material`, `vertex_color_split`, and `material_slots`
  - warning and hard-failure behavior
- `conversion_orchestrator.py`
  - output resolution per input
  - diagnostics on validation errors
  - cleanup warning propagation
  - `skeletal_parts` bundle writing
- `naming.py`
  - Source Name to Prim Name sanitization
  - deterministic collision suffixes
  - numeric and non-ASCII fallbacks
- `geometry_buffers.py`
  - MeshData to GeometryBuffer round trip
  - section preservation
  - face-range iteration
  - payload count helpers

Done when:

- Deep modules can be changed with localized test feedback.
- End-to-end tests stop carrying all responsibility for low-level rules.

## Step 7 - Rationalize Qt Tests

Keep Qt workflow coverage, but reduce coupling to private methods and visual
implementation details.

Actions:

- Keep tests that prove Operator State becomes Operator Intent correctly.
- Keep tests for preset persistence, material rows, UDIM rows, wind rows, and
  diagnostics bundle export.
- Move pure formatting/theme math into non-widget tests.
- Avoid asserting exact UI text unless it is user-facing release contract.
- Avoid calling private window methods when the same behavior can be reached
  through a user action or a small application-layer function.

Done when:

- Qt tests fail for broken workflows, not harmless layout implementation changes.
- UI Shell State, Operator State, and Operator Intent stay separate in tests.

## Step 8 - Improve Fixtures Without Inventing New Source Semantics

Current synthetic fixtures are useful. Add only fixtures that encode a known
observed or explicitly supported case.

Actions:

- Keep real `SimpleTree_01.xml` and `BigSpruce` coverage.
- Keep current synthetic fixtures for Leaf References and invalid bindings.
- Add small focused XML fixtures only when a rule cannot be expressed clearly
  with existing samples.
- Name fixtures by contract, not by bug ticket.
- Record any fixture that represents an assumption not yet validated in UE.

Done when:

- Fixtures explain why they exist.
- Synthetic fixtures do not silently become fake SpeedTree schema truth.

## Step 9 - Define Test Tiers

Separate fast always-on tests from optional heavy tests.

Suggested tiers:

- default: deterministic unit and integration tests, no real heavy FBX
- qt: Qt workflow tests, still default when PySide6 is installed
- stress: huge FBX, large real files, cache stress
- ue-manual: checklist-driven UE 5.7 import validation, not automated pytest

Done when:

- Developers know which command protects normal changes.
- Heavy validation is preserved without making every local run expensive.

## Step 10 - Cleanup Pass

After replacements exist, delete or simplify low-signal tests.

Candidates:

- tests that only assert helper call counts without checking behavior
- tests that assert exact stylesheet repetition counts
- tests that duplicate the same USDA text check across export paths
- tests that preserve obsolete migration behavior
- tests that test implementation names instead of project vocabulary

Done when:

- Test count may go down or up, but signal per test improves.
- Failure output points to the broken contract owner.

## Suggested Order

1. Add test-suite map and category labels.
2. Create USDA inventory helper.
3. Move USDA authoring contract tests out of `test_pipeline.py`.
4. Move material tests into `test_material_resolver.py`.
5. Move normalizer/source tests into `test_normalizer.py`.
6. Quarantine compatibility tests.
7. Move performance checks to optional benchmark/stress path.
8. Add missing direct tests for `conversion_orchestrator`, `naming`, and
   `geometry_buffers`.
9. Prune duplicated or low-signal tests.
10. Run full pytest and package build.

## Final Acceptance Criteria

- `python -m pytest -q` remains green.
- Normal pytest remains fast and deterministic.
- `test_pipeline.py` contains only public-path conversion regressions.
- Importer-facing USDA checks use structural assertions where possible.
- Deep modules have local tests at their actual interfaces.
- Compatibility tests are explicit and removable.
- No test encodes an undocumented hardcoded branch as product truth.
- Any remaining deferred test weakness is recorded in `KNOWN_PROBLEMS.md`.
