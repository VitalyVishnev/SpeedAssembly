# Architecture Improvement Plan

## Role

This document turns the current architecture review into a five-phase
implementation plan. It does not override `AGENTS.md`,
`docs/ue_import_contract.md`, `docs/speedtree_mapping.md`,
`docs/workflow_status.md`, or `docs/DECISIONS.md`.

The goal is not cosmetic cleanup. Each phase must increase module depth,
locality, or importer-facing confidence. If a phase discovers a blocked
contract decision, stop and record the unresolved item in `KNOWN_PROBLEMS.md`
or `docs/DECISIONS.md` before coding around it.

## Execution Rules

- Use vertical TDD slices: one behavior test, minimal implementation, then
  refactor.
- Test through stable interfaces, not private helpers, unless the helper is
  intentionally documented as a low-level parser/codec surface.
- Do not add a new seam unless at least two real adapters already use it, or one
  adapter plus one concrete regression-test adapter justifies it.
- Preserve current UE 5.7.x import behavior over architectural neatness.
- Keep compatibility facades thin. Do not move new behavior into `pipeline.py`,
  `usda_writer.py`, or `gui.py`.
- After implementation phases that change code, run the focused tests first,
  then full pytest, then package build.

## Phase 1 - Unify Worker File Protocol

Status: Implemented.

Verification:

- `python -m pytest -q tests/test_worker_file_protocol.py tests/test_conversion_process.py tests/test_fracture_worker_subprocess.py tests/test_fbx_read_options.py tests/test_fbx_prototype_sources.py tests/test_proxy_mesh_service.py`
- `python -m pytest -q`
- `.\scripts\build_qt_gui_exe.cmd -Package`

### Target

Create one deep infrastructure module for file-based worker exchange:
temporary path allocation, atomic request/result/error writes, result/error
reads, cleanup, and packaged/dev worker command resolution.

### Original Friction

Files involved:

- `src/xml_to_usda/conversion_process.py`
- `src/xml_to_usda/conversion_worker_subprocess.py`
- `src/xml_to_usda/proxy_mesh_worker_subprocess.py`
- `src/xml_to_usda/fracture_worker_subprocess.py`
- `src/xml_to_usda/fbx_worker_subprocess.py`
- `src/xml_to_usda/fbx_import_supervisor.py`
- `tests/test_conversion_process.py`
- `tests/test_fracture_worker_subprocess.py`
- `tests/test_fbx_read_options.py`
- `tests/test_fbx_prototype_sources.py`

The project already has several real adapters: Conversion Worker, Proxy Mesh
worker, Fracture worker, and FBX Helper. They all use similar file exchange,
but with inconsistent atomicity and result/error handling. Fracture request and
result writes are safer than conversion/proxy/FBX writes. That is a runtime
stability risk, not just duplication.

### Known Work

- Introduce a `worker_file_protocol.py` infrastructure module.
- Move atomic write helpers into that module.
- Standardize JSON error payload shape: message plus formatted traceback.
- Standardize pickle result payload read/write where pickle is still the right
  exchange format.
- Standardize temporary file naming and cleanup.
- Centralize worker command resolution for frozen and development runtimes.
- Keep action-specific request dataclasses in their existing worker modules
  until there is evidence that moving them improves locality.

### Needs Local Investigation

- Whether FBX request JSON should remain JSON because it is human-readable and
  small, or move to the same atomic JSON writer only.
- Whether conversion telemetry event files should share the same atomic writer.
- Whether command resolution should include FBX Helper immediately or only the
  UI worker processes first.
- Whether any tests depend on direct final-file writes and need behavior-level
  replacement tests.

### TDD Slices

1. Add a test that a failed atomic pickle write leaves no final result file.
2. Add a test that a successful atomic pickle write can be read back through the
   shared interface.
3. Add a test that JSON error payloads round-trip the same way for conversion,
   proxy, fracture, and FBX worker readers.
4. Add a test that worker command resolution returns the same commands as the
   old per-worker functions in frozen and non-frozen cases.
5. Refactor one worker adapter at a time to the shared module, keeping tests
   green after each adapter.

### Acceptance Criteria

- Worker request/result/error write paths are atomic where partial files could
  affect process polling.
- Existing worker behavior is preserved.
- Crash/success classification remains file-first: result/error files are
  drained before a stopped worker is reported as crashed.
- No conversion semantics move into the worker protocol module.

## Phase 2 - Route CLI Through Conversion Launch Seam

Status: Implemented.

Verification:

- `python -m pytest -q tests/test_cli.py tests/test_conversion_service.py tests/test_conversion_validation.py tests/test_conversion_orchestrator.py`
- `python -m pytest -q`
- `.\scripts\build_qt_gui_exe.cmd -Package`

Implementation notes:

- CLI `convert` now uses `conversion_service.prepare_conversion_plan` to build
  the same main-export `ConversionRequest` shape as the UI path.
- CLI execution remains synchronous and delegates execution to
  `conversion_orchestrator.convert_request`.
- CLI does not expose `conversion_mode`; it keeps the current default
  `skeletal_assembly` contract.
- `--preserve-temp-files` remains the only CLI cleanup-policy toggle.

### Target

Make CLI and UI build main conversion `ConversionRequest` values through the
same application seam.

### Current Friction

Files involved:

- `src/xml_to_usda/cli.py`
- `src/xml_to_usda/conversion_service.py`
- `src/xml_to_usda/conversion_orchestrator.py`
- `src/xml_to_usda/conversion_validation.py`
- `tests/test_conversion_service.py`
- `tests/test_conversion_validation.py`
- CLI coverage to add or extend

`docs/ARCHITECTURE.md` says CLI and UI should enter through
`conversion_service.prepare_conversion_plan`, but CLI currently constructs the
conversion path through `convert_file`. That means Operator Intent
normalization is not guaranteed to stay identical between CLI and UI.

### Known Work

- Add a CLI-facing adapter that calls `prepare_conversion_plan` or a narrower
  shared function extracted from it.
- Keep CLI-specific concerns in `cli.py`: argparse, stdout/stderr, exit codes.
- Keep execution in `conversion_orchestrator.convert_request`.
- Preserve CLI compatibility for current options.
- Ensure `MaterialPolicy.SOURCE_MATERIALS` clears broad material override paths
  consistently.
- Ensure explicit material contract detection is identical for UI and CLI.

### Needs Local Investigation

- Whether CLI should expose `conversion_mode` now or stay on default
  `skeletal_assembly`.
- Whether CLI should expose `cleanup_policy` only via `--preserve-temp-files`.
- Whether CLI should ever expose async launch planning, or always run
  synchronously after request preparation.
- Whether current tests cover CLI invalid material path messages through the
  public command interface.

### TDD Slices

1. Add a CLI behavior test proving `source_materials` ignores broad bark/leaves
   paths the same way the UI plan does.
2. Add a CLI behavior test proving invalid Unreal material paths fail before
   conversion work starts.
3. Route `_run_convert` through the shared request preparation path.
4. Add a CLI behavior test for explicit prototype source config causing
   `use_explicit_material_contract` when relevant.
5. Refactor only after behavior parity is covered.

### Acceptance Criteria

- There is one module interface that normalizes main-export Operator Intent
  into `ConversionRequest`.
- CLI does not duplicate material path cleanup or explicit material contract
  rules.
- `conversion_orchestrator.py` remains the execution owner, not the planner.

## Phase 3 - Add Companion Workflow Request Projections

Status: Implemented.

### Target

Stop using full `ConversionRequest` as the implicit input for every companion
workflow. Keep main export intent distinct from Proxy Mesh, Fracture Preview,
and Fracture Export requests.

### Current Friction

Files involved:

- `src/xml_to_usda/models.py`
- `src/xml_to_usda/proxy_mesh_service.py`
- `src/xml_to_usda/fracture_preview_service.py`
- `src/xml_to_usda/fracture_export_service.py`
- `src/xml_to_usda/conversion_process.py`
- `src/xml_to_usda/qt_ui/window.py`
- `src/xml_to_usda/qt_ui/background_jobs.py`
- `tests/test_proxy_mesh_service.py`
- `tests/test_fracture_preview_service.py`
- `tests/test_fracture_export_service.py`
- `tests/test_conversion_process.py`
- `tests/test_qt_ui_workflows.py`

Proxy Mesh already has `ProxyMeshSourceRequest`, which is the right direction.
Before this phase, Fracture Preview and Fracture Export still commonly took full
`ConversionRequest`. This leaks too much main-export Operator Intent into
companion workflows and makes UI methods responsible for building special-case
requests.

### Completed Work

- Kept `ProxyMeshSourceRequest` and added a small application helper for UI
  request construction.
- Added `FracturePreviewSourceRequest` for preview-only source geometry needs.
- Added `FractureExportRequest` for
  resolved Operator Intent needed by export.
- Moved `_single_input_path`, output stem/path derivation, and request narrowing
  out of UI methods and into application modules.
- Kept Fracture Preview fast and source-geometry based.
- Kept Fracture Export resolved-intent based and always writing
  `Static Mesh Assembly` pieces.

### Investigation Results

- Fracture Export should not carry full `ConversionRequest`; the narrower
  `FractureExportRequest` carries explicit material, UDIM, prototype, output,
  cache, and CPU fields.
- Preview and Export should not share a base request type yet; their overlap is
  too small and would create a shallow abstraction.
- Preview validates source/path requirements locally. Export reuses
  `validate_conversion_request` through an explicit conversion projection
  because export still resolves operator material/prototype intent.
- Worker pickle compatibility across code versions is not treated as stable;
  workers are launched from the same installed code version.

### TDD Slices

1. Add a Fracture Preview test proving main-export material/prototype/UDIM
   intent is not read by preview.
2. Add a Fracture Export test proving resolved material and prototype intent is
   preserved.
3. Add a worker request round-trip test for the new fracture request projection.
4. Move request construction from `MainWindow` into application-level helpers.
5. Update Qt workflow tests to assert behavior through buttons/actions where
   practical, not private request-building methods.

### Acceptance Criteria

- Companion workflow requests are explicit and smaller than
  `ConversionRequest` where the workflow does not need full main-export intent.
- UI Shell collects Operator State but does not decide companion workflow
  semantics.
- Preview and export cannot accidentally inherit unrelated main-export fields.

### Implementation Notes

- `FracturePreviewSourceRequest` now carries only preview source geometry
  inputs, output naming context, and CPU profile.
- `FractureExportRequest` now carries the explicit material, UDIM, prototype,
  output, cache, and CPU intent needed to resolve Static Mesh Assembly fracture
  exports.
- Fracture worker pickle requests now carry the action-specific projection,
  not a broad `ConversionRequest`.
- `MainWindow` delegates Proxy Mesh and Fracture Preview request construction
  to application helpers.
- Compatibility wrappers remain for older call sites, but UI and worker paths
  use the explicit projections.

Verification:

- `& '.\.venv310\Scripts\python.exe' -m pytest -q tests/test_fracture_preview_service.py tests/test_fracture_export_service.py tests/test_fracture_worker_subprocess.py tests/test_conversion_process.py tests/test_qt_ui_workflows.py tests/test_fracture_real_sample.py`
  - Result: 64 passed.
- `& '.\.venv310\Scripts\python.exe' -m pytest -q`
  - Result: 408 passed, 3 deselected.
- `& '.\scripts\build_qt_gui_exe.cmd' -Package`
  - Result: passed; rebuilt `dist-next\XMLtoUSDAConverter.exe` and release
    zip.

## Phase 4 - Reduce UI Shell Knowledge

Status: Implemented as a scoped UI-shell reduction.

### Target

Make the Qt shell a thinner adapter over application modules, Operator State,
Persisted Operator Settings, UI Shell State, and background Runtime Job events.

### Original Friction

Files involved:

- `src/xml_to_usda/qt_ui/window.py`
- `src/xml_to_usda/qt_ui/background_jobs.py`
- `src/xml_to_usda/qt_ui/operator_state.py`
- `src/xml_to_usda/qt_ui/persistence.py`
- `src/xml_to_usda/qt_ui/panels.py`
- `src/xml_to_usda/qt_ui/dependencies.py`
- `tests/test_qt_ui_workflows.py`
- `tests/test_qt_ui_operator_state.py`
- `tests/test_qt_ui_persistence.py`

Before this phase, `MainWindow` owned too much: preset management, request preparation,
diagnostics bundle construction, preview cache behavior, cache settings,
runtime status, UI shell geometry, and background job coordination. The module
is large because it is carrying several interfaces at once.

### Completed Work

- Extracted diagnostics bundle request construction into
  `diagnostics_bundle.build_diagnostics_bundle_request`.
- Removed the obsolete `resolve_input_settings_key` entry from
  `QtUiDependencies`; no supported Qt workflow consumed it.
- Kept preset management in `MainWindow`; extracting a `PresetController` would
  currently hide dialogs and widget interactions behind a shallow interface.
- Kept preview cache state in `MainWindow`; there is not yet enough shared
  lifecycle behavior to justify a separate cache controller.
- Removed unused or obsolete dependency bundle entries such as
  `resolve_input_settings_key` after confirming it was historical per-XML
  settings residue in the Qt dependency bundle.
- Kept visual widget layout in Qt modules and settings persistence ownership in
  `settings_service.py`.

### Investigation Results

- `QtBackgroundJobsController` should not be split in this phase; job-specific
  split would be broad and the existing single interface is still coherent for
  the window.
- Preset import/export still mixes dialogs and settings persistence. It should
  be revisited only with a concrete preset workflow change.
- Diagnostics bundle request construction belongs in the diagnostics
  application module; the Qt shell should pass selected UI values, not assemble
  runtime/cache/build semantics.

### TDD Slices

1. Add or adjust tests so one Operator State to Operator Intent path is covered
   through a stable application helper.
2. Extract one small behavior at a time from `MainWindow`; keep Qt tests green.
3. Replace private-method tests with behavior tests only where the public path
   is practical and reliable.
4. Remove obsolete dependency entries after tests prove no supported workflow
   needs them.
5. Refactor after each vertical slice, not after a large extraction batch.

### Acceptance Criteria

- `MainWindow` remains responsible for widgets and user interaction, not
  conversion semantics.
- Operator State, Persisted Operator Settings, UI Shell State, and Operator
  Intent remain distinct in code and tests.
- Qt tests fail for broken workflows, not harmless internal movement.

### Implementation Notes

- Added `build_diagnostics_bundle_request(...)` in `diagnostics_bundle.py`.
- `MainWindow.export_diagnostics_bundle()` now delegates diagnostics request
  semantics to that helper and only handles dialog selection, save-state, and
  UI reporting.
- Removed `resolve_input_settings_key` from `QtUiDependencies` and its fake
  test dependency construction.

Verification:

- `& '.\.venv310\Scripts\python.exe' -m pytest -q tests/test_diagnostics_bundle.py tests/test_qt_ui_workflows.py tests/test_qt_ui_operator_state.py tests/test_qt_ui_persistence.py`
  - Result: 57 passed.
- Final full verification after Phase 5:
  `& '.\.venv310\Scripts\python.exe' -m pytest -q`
  - Result: 415 passed, 3 deselected.
- Final package build:
  `& '.\scripts\build_qt_gui_exe.cmd' -Package`
  - Result: passed; rebuilt `dist-next\XMLtoUSDAConverter.exe` and release
    zip.

## Phase 5 - Reconcile Fast Source Discovery With Canonical Source Facts

Status: Implemented by parity tests and documented discovery contract.

### Target

Prevent streamed XML discovery helpers from becoming a second source-of-truth
for SpeedTree interpretation.

### Original Friction

Files involved:

- `src/xml_to_usda/source_analysis.py`
- `src/xml_to_usda/xml_reader.py`
- `src/xml_to_usda/normalizer.py`
- `src/xml_to_usda/discovery_service.py`
- `tests/test_source_analysis.py`
- `tests/test_discovery_service.py`
- `tests/test_normalizer.py`

`source_analysis.py` has fast streamed discovery for prototype rows and base
material rows. This is useful for UI responsiveness, but it duplicates parts of
the XML interpretation owned by `normalizer.py` and the `CanonicalTreeModel`
seam.

### Completed Work

- Documented fast discovery as a UI adapter whose supported prototype and base
  material rows must stay parity-tested against `CanonicalTreeModel`.
- Added parity tests against `CanonicalTreeModel` for real samples and current
  synthetic fixtures.
- Kept `inspect_source` canonical-backed, as it already normalizes before
  enriching the report.
- Avoided moving heavy full normalization into every UI discovery call because
  current streamed discovery matches canonical facts for supported fixtures.
- Fast discovery now has an explicit contract note in `source_analysis.py`.

### Investigation Results

- No mismatch was found for `SimpleTree_01` repeated-part prototype rows.
- Current Leaf References edge fixtures match canonical prototype identity and
  instance counts.
- Base material discovery for `SimpleTree_01` matches canonical base mesh
  material sections.
- Canonical-backed discovery remains unnecessary for every UI discovery call
  until a measured mismatch appears.

### TDD Slices

1. Add parity tests: streamed prototype discovery vs canonical prototypes on
   `SimpleTree_01`.
2. Add parity tests for current Leaf References edge fixtures.
3. Add base material discovery parity tests against canonical base material
   sections.
4. If parity fails, decide whether the streamed adapter is wrong or its
   interface needs to declare weaker semantics.
5. Refactor only the confirmed mismatch owner.

### Acceptance Criteria

- Source discovery cannot silently disagree with `CanonicalTreeModel` for
  supported cases.
- Any intentional approximation is named and documented.
- Synthetic fixtures remain marked as contract fixtures, not observed SpeedTree
  schema truth.

### Implementation Notes

- Added canonical parity tests in `tests/test_source_analysis.py`.
- Added a source-analysis module contract note that fast discovery is allowed
  only when supported rows remain parity-tested against `CanonicalTreeModel`.

Verification:

- `& '.\.venv310\Scripts\python.exe' -m pytest -q tests/test_source_analysis.py tests/test_discovery_service.py tests/test_normalizer.py`
  - Result: 28 passed.
- Final full verification:
  `& '.\.venv310\Scripts\python.exe' -m pytest -q`
  - Result: 415 passed, 3 deselected.
- Final package build:
  `& '.\scripts\build_qt_gui_exe.cmd' -Package`
  - Result: passed; rebuilt `dist-next\XMLtoUSDAConverter.exe` and release
    zip.

## Recommended Order

1. Phase 1: worker protocol. Highest stability risk and clearest real seam.
2. Phase 2: CLI launch seam. Small surface, removes request-planning drift.
3. Phase 3: companion workflow request projections. Builds on cleaner launch
   and worker interfaces.
4. Phase 4: UI Shell reduction. Safer after request projections exist.
5. Phase 5: source discovery reconciliation. It may reveal product choices, so
   keep it after runtime and request interfaces are calmer.

## Global Done Criteria

- Focused tests pass for each phase.
- Full pytest passes before merging a phase.
- Package build passes after code-changing phases.
- `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, and `KNOWN_PROBLEMS.md` are
  updated when a phase changes an accepted seam or leaves a known limitation.
- No phase emits broken USDA or weakens fail-loud behavior.
