# Viewport Rework Plan

## Purpose

Create one reliable viewport system for Proxy Mesh Preview, Fracture Preview,
and future inspection tools such as branch/prototype preview.

The goal is not to turn the app into a DCC tool. The goal is a production-grade
preview viewport: stable, predictable, diagnosable, and shared across preview
modes instead of copied through separate dialogs.

## Current Problem

The current preview implementation mixes several concerns:

- preview generation and runtime job lifecycle
- CPU viewport payload construction
- OpenGL resource ownership and upload
- camera/orbit/grid/render state
- fracture-specific overlays, picking, cuts, and controls
- proxy-specific process preview behavior

This makes failures hard to isolate. Recent logs show both kinds of native-risk
failure:

- isolated worker crashes with no Python traceback when preview work runs in a
  frozen subprocess
- whole-GUI exits when preview work runs in a background thread inside the Qt
  process

The strategic issue is the same in both cases: the viewport path is not a deep
module. Callers know too much, and native-risk work is not clearly separated
from UI rendering.

## Target Architecture

### 1. Viewport Scene Module

Create a Qt-free `ViewportScene` payload that describes what should be drawn.

It should contain:

- mesh batches
- repeated/instanced draw calls
- per-batch color/tint metadata
- optional overlays: bones, cut markers, labels
- selectable ids for picking
- bounds and camera framing hints
- diagnostic stats: uploaded triangles, logical triangles, instance count

Rules:

- no Qt classes
- no OpenGL objects
- no fracture/proxy business rules inside the renderer
- deterministic scene payload for the same source input and settings

### 2. Preview Job Module

Create one runtime module for preview generation jobs.

Responsibilities:

- latest-request-wins behavior
- cancellation
- structured result/error reporting
- trace breadcrumbs for every stage
- worker/process isolation policy
- consistent lifecycle for Proxy Mesh Preview and Fracture Preview

Default policy:

- native-risk/heavy preview preparation runs outside the main Qt process
- the Qt process receives only a ready `ViewportScene` or a loud error
- UI-only visual controls such as color strength and exploded view must update
  without regenerating the source preview job

### 3. Qt Viewport Module

Create one reusable `QOpenGLWidget` viewport implementation.

Responsibilities:

- camera/orbit/zoom
- grid
- opaque mesh rendering
- instanced rendering or pre-expanded render batches
- x-ray overlay rendering
- marker and label rendering
- OpenGL resource lifecycle
- viewport diagnostics

Rules:

- no source XML interpretation
- no Fracture Piece membership planning
- no Proxy Mesh generation
- no worker lifecycle ownership

### 4. Mode Adapters

Create thin adapters from application preview results to `ViewportScene`.

Initial adapters:

- `ProxyPreviewModeAdapter`
- `FracturePreviewModeAdapter`

Future adapter:

- `BranchInspectionModeAdapter`

Adapter responsibilities:

- convert domain/application result into viewport scene payload
- provide mode-specific overlays and selectable ids
- provide mode-specific stats and labels
- keep mode-specific UI panels outside the renderer

### 5. Preview Shell

Keep the current UX entry points:

- `Preview Proxy`
- `Preview Fracturing`

Internally, both should open/use the same preview shell and viewport module with
different mode panels and mode adapters.

Rules:

- do not open duplicate windows for the same mode/input
- preview windows stay modal/top-level over the main UI
- changing main UI while a preview window is open should be intentionally
  constrained
- mode settings are preserved according to existing Operator State rules

## Migration Plan

### Phase 0: Stabilize The Current Release

Purpose: stop making the packaged GUI worse while the rework is prepared.

Steps:

1. Resolve the decision conflict in `docs/DECISIONS.md`.
   - Pick one current runtime contract for Fracture Preview.
   - Record why the other approach is unsafe.
2. Revert Fracture Preview generation out of the main GUI thread.
   - Whole-GUI crashes are worse than contained worker crashes.
   - Preserve diagnostics from worker result/error files.
3. Keep export process isolation unchanged.
4. Add a known problem entry for the current viewport architecture.
   - Location: `qt_ui/proxy_preview.py`, `qt_ui/fracture_preview.py`,
     `qt_ui/background_jobs.py`, `qt_ui/window.py`.
   - Reason: mixed job, scene, renderer, and mode responsibilities.

Validation:

- packaged app opens reliably
- opening Fracture Preview does not close the whole GUI
- worker failure reports an error dialog instead of terminating the app

### Phase 1: Define Viewport Scene Contract

Purpose: create a stable payload between preview generation and rendering.

Steps:

1. Add a Qt-free viewport scene model.
2. Model mesh batches and draw calls.
3. Model overlay primitives:
   - bone segment
   - cut marker
   - hover marker
   - label
4. Model selection ids separately from visible labels.
5. Add bounds and stats to the scene.
6. Add tests for deterministic scene payloads.

Validation:

- proxy scene can be built without importing Qt
- fracture scene can be built without importing Qt
- same input/settings produce same scene stats and draw ids

### Phase 2: Move Fracture CPU Payload Out Of Dialog

Purpose: stop doing expensive scene construction in `dialog.set_preview()`.

Steps:

1. Move `build_fracture_viewport_mesh` behavior behind the Fracture Preview
   mode adapter.
2. Make worker return both:
   - fracture preview domain result needed for export/session state
   - `ViewportScene` needed for rendering
3. Keep manual cut tokens and selected ids in session state.
4. Ensure visual-only controls do not rebuild the domain preview:
   - piece color strength
   - exploded view
   - show bones
   - hide repeated parts, if implemented as viewport visibility

Validation:

- moving `Piece Color` is instant and does not start a preview job
- moving `Exploded View` is instant and does not start a preview job
- toggling `Show Bones` does not start a preview job
- changing Target Pieces still starts a preview job

### Phase 3: Unify Runtime Preview Jobs

Purpose: make proxy and fracture preview use the same job lifecycle.

Status:

- Done: introduced `qt_ui/preview_jobs.py` as the shared process-backed
  preview job lifecycle module.
- Done: moved Proxy Mesh Preview process ownership out of
  `ProxyPreviewDialog` and into `QtBackgroundJobsController`.
- Done: moved Fracture Preview lifecycle behind the same `PreviewProcessJob`
  interface.

Steps:

1. Introduce a shared Preview Job Controller.
2. Move proxy preview process ownership out of `ProxyPreviewDialog`.
3. Move fracture preview lifecycle out of mode-specific code.
4. Support:
   - start
   - cancel
   - latest request wins
   - stale result rejection
   - structured error
   - trace breadcrumbs
5. Ensure worker file protocol is drained before crash classification.

Validation:

- proxy and fracture have equivalent crash containment
- opening one preview mode cancels or closes the other predictably
- logs show the same stage vocabulary for both modes

### Phase 4: Extract Shared Qt Viewport

Purpose: make rendering one deep module instead of two related implementations.

Status:

- Done: introduced `qt_ui/viewport.py` as the shared Qt/OpenGL matcap/grid
  viewport module.
- Done: moved `MatcapViewport`, `ProxyViewport`, camera/orbit/grid behavior,
  and shared OpenGL helpers out of `qt_ui/proxy_preview.py`.
- Done: Proxy Mesh Preview renders `ViewportScene` payloads through
  `MatcapViewport.set_scene()`.
- Done: shared matcap vertex upload and shader attribute binding now live in
  `qt_ui/viewport.py`; Fracture Preview no longer duplicates the OpenGL vertex
  layout contract.
- Done: `MatcapViewport` accepts precomputed matcap vertex payloads, so
  Fracture Preview no longer overrides mesh upload and still avoids rebuilding
  heavy fracture render buffers on visual-only controls.
- Done: Fracture Preview uses composition over `MatcapViewport`; fracture-only
  `FractureViewportMesh` state now stays in `FracturePreviewDialog` and its
  adapter functions instead of a viewport subclass.

Steps:

1. Move `MatcapViewport` out of `proxy_preview.py`.
2. Create a dedicated viewport module under `qt_ui/`.
3. Give it one public interface:
   - set scene
   - set visual state
   - set selection/hover state
   - report pick result
4. Keep OpenGL resources private.
5. Move camera/grid/orbit behavior into this module.
6. Replace fracture inheritance with composition over the shared viewport.

Validation:

- Proxy Preview renders through the shared viewport
- Fracture Preview renders through the shared viewport
- camera behavior is identical across modes
- viewport can be tested with synthetic `ViewportScene`

### Phase 5: Rebuild Fracture Overlays And Picking

Purpose: make bones/cuts/hover markers stable and debuggable.

Status:

- Done: `ViewportScene` carries bone segments, cut markers, labels, and
  selectable ids for Fracture Preview.
- Done: `qt_ui/viewport.py` owns bone overlay drawing, selected cut markers,
  Ctrl+Hover target preview, Ctrl+Click picking, and screen-space segment
  picking math.
- Done: `FracturePreviewDialog` passes the prebuilt `ViewportScene` and
  precomputed fracture matcap payload into the shared viewport.
- Done: Show Bones affects overlay visibility only and does not start a
  preview job.

Steps:

1. Represent bones as overlay primitives in `ViewportScene`.
2. Represent cut markers as overlay primitives.
3. Represent hover target as UI visual state, not regenerated scene data.
4. Use selectable ids for picking.
5. Keep cut validity in `fracture_service.py`.
6. Keep picking math in the viewport module.

Validation:

- `Ctrl+Hover` shows the exact target that `Ctrl+Click` will select
- selected cut marker can be deleted from the list
- Show Bones affects only overlay visibility
- hidden bones do not block normal camera interaction

### Phase 6: Preview Shell Consolidation

Purpose: one shell, multiple modes.

Status:

- Done: introduced `qt_ui/preview_shell.py` as the shared preview dialog shell
  for viewport/settings slots, stable sizing, owner, modality, and focus
  behavior.
- Done: Proxy and Fracture preview dialogs use the same modal/focus helper and
  focus an existing visible dialog instead of opening a duplicate.
- Done: Proxy and Fracture preview dialogs now subclass `PreviewShellDialog`
  and no longer duplicate the base two-column shell layout.
- Done: the shared shell module owns the common window/layout/modality contract;
  mode-specific dialogs own only their settings controls and result
  presentation.
- Decision: do not introduce one hot-swappable runtime shell object until mode
  switching inside an already-open preview window becomes a required UX
  behavior. The current product contract has separate Geometry-tab entry points
  and no in-preview mode switcher, so a runtime mode switcher would add
  coupling without current leverage.

Steps:

1. Create shared preview shell window/dialog.
2. Add mode panel slots:
   - proxy settings panel
   - fracture settings panel
3. Keep existing Geometry tab buttons.
4. Prevent duplicate preview windows.
5. Keep modality/top-level behavior.
6. Preserve current settings and current XML session state.

Validation:

- `Preview Proxy` opens proxy mode
- `Preview Fracturing` opens fracture mode
- reopening focuses existing window
- closing preview keeps intended settings
- changing XML clears source-specific manual cuts

### Phase 7: Diagnostics And Smoke

Purpose: make future regressions reproducible from the packaged build.

Status:

- Done: Fracture Preview already records `job.start`, worker events,
  `viewport.prepare`, and `viewport.upload` breadcrumbs.
- Done: Proxy Preview now records `job.result` and `viewport.upload`
  breadcrumbs with mesh/triangle/vertex counts.
- Done: preview modes now record standardized `scene.request`,
  `scene.ready`, `scene.error`, `viewport.set_scene`,
  `viewport.upload_begin`, `viewport.upload_end`, and
  `viewport.context_lost` events through the shared viewport trace callback.
- Done: packaged high-risk smoke now includes
  `fracture-preview-interactive`, so Show Bones and visual controls are covered
  by the final package gate.
- Done: smoke checks assert modal preview dialogs, viewport mesh/bone state,
  scene readiness, scene handoff to the viewport, and real viewport upload
  completion.

Steps:

1. Add viewport-stage trace events:
   - scene.request
   - scene.ready
   - scene.error
   - viewport.set_scene
   - viewport.upload_begin
   - viewport.upload_end
   - viewport.context_lost
2. Add packaged smoke flows:
   - open app
   - open proxy preview
   - open fracture preview
   - load scene
   - toggle bones
   - move visual-only sliders
   - close preview
3. Save smoke screenshots where practical.
4. Include viewport state in diagnostics bundle.

Validation:

- packaged smoke fails when preview cannot open
- packaged smoke fails when viewport upload does not complete
- diagnostics bundle contains enough data to identify last successful stage

## Test Plan

Unit and integration tests should target module interfaces, not internal helper
shapes.

Required tests:

- `ViewportScene` deterministic payload tests
- proxy result to viewport scene adapter tests
- fracture result to viewport scene adapter tests
- preview job controller lifecycle tests
- stale result rejection tests
- visual-only controls do not regenerate preview tests
- packaged smoke test for opening both preview modes
- viewport synthetic scene render smoke

High-risk tests:

- crash in preview worker does not close GUI
- crash before worker error file creates loud UI error
- stopped worker with result file is success
- repeated quick settings changes produce only latest visible scene

## Non-Goals

- No DCC editing tools in this rework.
- No change to USDA export contract.
- No change to Fracture Piece membership semantics except where separately
  planned.
- No replacement of Proxy Mesh QEM simplification with diagnostic sampling.
- No migration to a new UI framework.

## Success Criteria

The rework is successful when:

- Proxy Preview and Fracture Preview share one viewport implementation.
- The GUI does not close from preview generation failures.
- Heavy/native-risk preview preparation is isolated from the Qt process.
- Visual-only controls update instantly.
- Logs identify whether failure happened in generation, scene preparation,
  upload, or render.
- Future branch/prototype preview can be added as a new mode adapter without
  copying viewport code.
