# Decisions

This page stores active project contracts. Rejected or superseded approaches live in [experiments.md](experiments.md). Current limitations and bugs live in [known-bugs.md](known-bugs.md).

## Decision: Skeletal assembly remains the primary contract

Status: Active

Context:
The project now supports both skeletal and static assembly export shapes.

Decision:
Keep `skeletal_assembly` as the primary importer-facing contract. Treat `static_assembly` as a supported secondary mode.

Reasoning:
The project goal is still the skeletal vegetation pipeline, and UE behavior for that path is the highest-value validation target.

Consequences:
Static-mode simplifications must not erase locality for skeleton, binding, or part-skeleton rules.

Related files:
- `AGENTS.md`
- `docs/raw/ue_import_contract.md`
- `docs/raw/workflow_status.md`

## Decision: The canonical model is source-normalized

Status: Active

Context:
The project works from observed SpeedTree XML, not from a public XML spec.

Decision:
Treat the canonical model as normalized source facts, not as a skeletal-only authoring model.

Reasoning:
Static assembly and skeletal assembly both need the same normalized source interpretation.

Consequences:
Authoring mode is chosen after normalization, not inside raw XML traversal.

Related files:
- `docs/raw/speedtree_mapping.md`
- `docs/raw/DECISIONS.md`

## Decision: Resolved assembly is the seam between source facts and operator intent

Status: Active

Context:
Prototype replacement, explicit material choices, output naming, and export mode all depend on caller intent.

Decision:
Keep a resolved authoring model between canonical source facts and USDA authoring.

Reasoning:
Source facts and operator intent have different lifecycles and failure modes.

Consequences:
Request-specific behavior stays out of normalization.

Related files:
- `docs/raw/ARCHITECTURE.md`
- `docs/raw/DECISIONS.md`

## Decision: Validation is staged

Status: Active

Context:
Different invariants belong to source interpretation, request resolution, or USDA authoring.

Decision:
Use source validation, resolution validation, and authoring validation as separate stages.

Reasoning:
The stages have different inputs and different failure modes.

Consequences:
Tests and failures stay closer to the invariant that owns them.

Related files:
- `docs/raw/DECISIONS.md`
- `docs/raw/ARCHITECTURE.md`

## Decision: Test density is practical, not exhaustive

Status: Active

Context:
The test suite already protects many conversion, UI, runtime, and importer-contract paths. During experimental work, repeatedly adding or rewriting tests for every small attempt slows implementation and can encode temporary behavior before the operator has confirmed that the feature works.

Decision:
Keep existing tests, but add new tests selectively. New modules, public contracts, stable feature behavior, and importer-facing invariants need focused regression coverage. Simple edits, UI polish, documentation, mechanical cleanup, and intermediate experiments should usually rely on relevant existing checks until the behavior is accepted.

Reasoning:
Tests should protect completed intent and dangerous contracts, not mirror every implementation step. Prefer broad intent-level tests that catch meaningful breakage; when they fail, inspect the code to locate the exact cause.

Consequences:
Agents should not treat every small code change as requiring a new test. For experiments, prove the behavior with the smallest useful manual or focused check first, then freeze the accepted behavior with a compact regression test.

Related files:
- `AGENTS.md`
- `docs/raw/test_tiers.md`
- `docs/raw/test_suite_map.md`

## Decision: Repeated Part is source-level, Assembly Part is authored

Status: Active

Context:
`LeafReferences` are source records, while `PointInstancer` emits authored repeated geometry.

Decision:
Use `Repeated Part` for source-level repeated geometry and `Assembly Part` for authored repeated geometry.

Reasoning:
Source terminology and authored terminology serve different layers.

Consequences:
Static and skeletal exports can share the same source facts without sharing the same importer contract.

Related files:
- `docs/raw/GLOSSARY.md`
- `docs/raw/DECISIONS.md`

## Decision: Attachment is source/resolution, Skeletal Binding is authored

Status: Active

Context:
Source placement facts such as `BoneID` are not yet authored USD skeletal binding arrays.

Decision:
Use `Attachment` for source or resolved placement relationships and `Skeletal Binding` only for authored USD binding.

Reasoning:
Static assembly can interpret source placement without authoring skeletal binding.

Consequences:
Binding bugs and placement bugs stay distinguishable.

Related files:
- `docs/raw/GLOSSARY.md`
- `docs/raw/DECISIONS.md`

## Decision: Material terminology is staged

Status: Active

Context:
Source materials, resolved material assignment, and authored material binding are different layers.

Decision:
Keep those terms separate in code and documentation.

Reasoning:
XML ids, operator overrides, and USD material bindings have different meanings.

Consequences:
Explicit FBX material modes and piece-local UDIM rules stay readable.

Related files:
- `docs/raw/GLOSSARY.md`
- `docs/raw/DECISIONS.md`

## Decision: Naming and transform terminology stay explicit

Status: Active

Context:
The project has had regressions around naming and transform-space confusion.

Decision:
Keep `Source Name`, `Output Stem`, `Prim Name`, `Authored Asset Name`, `Source Space`, `Stage Space`, `Prototype Space`, `Attachment Space`, and `Instance Transform` distinct.

Reasoning:
Naming and transform bugs are easier to reason about when the terms are precise.

Consequences:
Code and docs should not collapse those concepts into generic labels.

Related files:
- `docs/raw/GLOSSARY.md`
- `docs/raw/DECISIONS.md`

## Decision: PySide6 is the supported desktop shell

Status: Active

Context:
The old Tk shell has been retired.

Decision:
Keep PySide6 as the supported UI path and treat the old Tk path as retired.

Reasoning:
One supported shell keeps the UI contract and runtime behavior easier to maintain.

Consequences:
UI work should stay behind the PySide6 adapter layer.

Related files:
- `docs/raw/ui_next_architecture.md`
- `docs/raw/DECISIONS.md`

## Decision: UDIM resolution is piece-local

Status: Active

Context:
The same numeric material id can appear in different authored pieces without conflict.

Decision:
Apply UDIM settings independently per authored piece.

Reasoning:
Piece-local resolution matches operator expectations and avoids cross-piece overwrite.

Consequences:
Duplicate active settings within one piece, or a target that matches nothing, must fail loudly.

Related files:
- `docs/raw/DECISIONS.md`
- `docs/raw/ARCHITECTURE.md`

## Decision: Balanced stays the visible CPU profile

Status: Active

Context:
Large jobs need runtime stability more than exposed tuning knobs.

Decision:
Keep `balanced` as the visible default runtime profile.

Reasoning:
The operator should not need to reason about concurrency knobs for the normal workflow.

Consequences:
Deeper runtime tuning stays internal unless a validated need appears.

Related files:
- `docs/raw/DECISIONS.md`
- `docs/raw/workflow_status.md`

## Decision: Large GUI jobs run outside the UI process

Status: Active

Context:
Heavy conversions were unstable when too much FBX or USDA work happened inside the UI shell.

Decision:
Run large conversions in a dedicated worker subprocess and keep the UI shell out of the heavy native path.

Reasoning:
Process isolation keeps the interface responsive and contains native failures.

Consequences:
Packaged smoke and stability gates stay required for the worker path.

Related files:
- `docs/raw/workflow_status.md`
- `docs/raw/troubleshooting.md`

## Decision: Preview stability must not redefine mesh quality contracts

Status: Active

Context:
Proxy Mesh and Fracture Preview needed crash containment without changing the meaning of the exported geometry.

Decision:
Keep QEM-based Proxy Mesh and Fracture Preview simplification and file-first worker completion rules intact.

Reasoning:
Cheaper diagnostic paths are acceptable only when they do not weaken the exported topology contract.

Consequences:
Face sampling stays rejected for Proxy Mesh and Fracture Preview because it creates disconnected triangle holes. Preview/proxy base-mesh paths may apply deterministic connected-component pruning before their own simplification pass to discard tiny disconnected terminal details: `Remove Small Branches` is a percentage of smallest connected islands to remove, not a relative size cutoff. Both workflows use the shared QEM topology simplification backend. Fracture Preview must not apply a hidden per-piece ceiling below the visible Preview Polycount range. Worker polling must drain result/error files before treating a stopped worker as a crash.

Related files:
- `docs/raw/DECISIONS.md`
- `docs/raw/ARCHITECTURE.md`

## Decision: Preview shell is shared infrastructure, not a mode switcher

Status: Active

Context:
Proxy Mesh Preview and Fracture Preview share window behavior but not the same mode payloads.

Decision:
Use one preview shell module for ownership, modality, focus, and layout, but keep mode-specific dialogs separate.

Reasoning:
A shared shell removes duplicated window behavior without coupling payload lifetimes or settings ownership.

Consequences:
Do not introduce a hot-swappable runtime preview shell unless the product becomes a real mode switcher.

Related files:
- `docs/raw/DECISIONS.md`
- `docs/raw/ARCHITECTURE.md`

## Decision: Manual fracture cuts are current XML session state

Status: Active

Context:
Pinned fracture cut sites depend on the current source skeleton and do not travel safely across files.

Decision:
Keep manual fracture cut sites in the active Fracture Preview session only.

Reasoning:
Cross-file reuse would create hidden coupling between unrelated trees.

Consequences:
Manual picks are not part of global presets or persisted operator settings.

Related files:
- `docs/raw/DECISIONS.md`
- `docs/raw/ARCHITECTURE.md`

## Decision: Fracturing uses one planner

Status: Active

Context:
Operator-facing Fracturing is now a single planner with pinned cuts and deterministic fill.

Decision:
Keep Manual Fracturing as one planner instead of several separate fracture methods.

Reasoning:
Separate modes made the UI look more powerful than the underlying planner.

Consequences:
Legacy fracture method ids should be rejected loudly.

Related files:
- `docs/raw/DECISIONS.md`
- `docs/raw/ARCHITECTURE.md`

## Decision: V1 automatic fracturing detaches natural weak points only

Status: Active

Context:
The old automatic fill could refine trunk chains and synthetic face regions, producing visibly unnatural trunk shredding on simple trees.

Decision:
Treat `target_piece_count` as operator-facing Auto Branches / Branch Count. Automatic V1 cuts may add a stump piece, separate independent root-level stems, and detach branch bases ranked by skeleton path length with optional height bias. Stump and separated stems are counted outside Branch Count. Manual pinned cuts still run first and may cut trunks explicitly. Noisy Cut changes only Cut Surface geometry; it must not change selected bones or piece structure.

Reasoning:
Length-first branch detachment better matches the perceived weak points of vehicle impact and nearby blast workflows while preserving manual control for exceptional cuts.

Consequences:
`preserve_trunk_bias` remains settings-compatible but is no longer an operator-facing V1 control. Preview skeleton segments must use the same realtime exploded offset as their owning pieces.

Related files:
- `src/xml_to_usda/fracture_service.py`
- `src/xml_to_usda/fracture_preview_service.py`
- `src/xml_to_usda/qt_ui/fracture_preview.py`
- `docs/fracturing_v1_working_plan.md`

## Decision: Packaged workers use the self executable

Status: Active

Context:
The release now ships one executable and launches worker commands through that executable.

Decision:
Keep packaged worker commands before Qt imports and before GUI bootstrap.

Reasoning:
Worker processes must not construct the UI shell, and one executable keeps distribution simple.

Consequences:
The release must not recreate a separate worker executable layout.

Related files:
- `docs/raw/DECISIONS.md`
- `docs/raw/troubleshooting.md`

## Decision: UI shells are adapters over application interfaces

Status: Active

Context:
The supported PySide6 shell is only one adapter around the shared conversion system.

Decision:
Keep UI code thin and keep conversion semantics out of the shell.

Reasoning:
One UI surface keeps the package and launcher behavior aligned.

Consequences:
UI state, operator intent, and runtime jobs must stay distinct.

Related files:
- `docs/raw/ARCHITECTURE.md`
- `docs/raw/ui_next_architecture.md`

## Decision: Interactive workflows optimize for low latency by default

Status: Active

Context:
The operator repeatedly previews Proxy Mesh, Fracture Preview, materials, and export-adjacent settings while judging visual quality.

Decision:
Treat avoidable UI pauses as product defects. Preview and setup paths should prefer narrow projections, typed caches, incremental reuse, and measured hot-path simplification over broad object reconstruction.

Reasoning:
The converter is an operator tool, not only a batch exporter. A technically correct result that repeatedly blocks the workflow for several seconds still damages the pipeline.

Consequences:
Before adding a broad cache or full-model reload to an interactive path, measure it against a narrow workflow-specific payload. Generic worker-payload JSON remains acceptable for IPC, but not as the default persistent cache for large preview/source models. Keep importer-facing correctness first, but make the default UX target as close to real-time as the workflow safely allows.

Related files:
- `src/xml_to_usda/proxy_source_projection.py`
- `src/xml_to_usda/mesh_pruning.py`
- `src/xml_to_usda/fracture_preview_service.py`

## Decision: Proxy source loading bypasses the generic source-model cache

Status: Active

Context:
Proxy Mesh generation on large SpeedTree XML files needs only base geometry, repeated-part transforms, and source prototype geometry. The generic JSON source-model cache can cost more to read or write than reparsing and normalizing the XML, especially on branch-heavy real samples.

Decision:
Keep the generic cache for normal conversion callers, but use a dedicated Proxy Source Projection and typed `.npz` cache for the Proxy Mesh source request path.

Reasoning:
Measured Proxy Mesh timings on `SK_BirchAltai_Assembly_13.xml` improved from about 17.1s before the speed work to about 3.5s cold and about 1.85s warm after Proxy Source Projection cache and local hot-path polish, without changing QEM simplification, pruning policy, output geometry settings, or importer-facing contracts. Projection output matched canonical-derived proxy output on the temporary Birch sample and repo samples.

Consequences:
Proxy preview/export no longer builds a full `CanonicalTreeModel` through authoring resolution. The Projection cache must stay typed and loaded with pickle disabled. Do not put material, skeleton, or authoring-resolution fields into it unless Proxy Mesh starts using them directly.

Related files:
- `src/xml_to_usda/proxy_source_projection.py`
- `src/xml_to_usda/proxy_mesh_service.py`

## Decision: Main UI export parameters are grouped and tooltip-backed

Status: Active

Context:
The main PySide6 UI exposes export-tree parameters for wind, prototype source assignment, material overrides, Proxy Mesh, and Fracture Preview. Dense ungrouped lists made it hard to tell whether a value affected source loading, preview mesh quality, fracture planning, viewport-only display, or collision output.

Decision:
Every operator-facing export parameter in the main UI should have a short English tooltip. Sliders and numeric fields should state what the value controls and what lower versus higher values do. Dense parameter panels should use functional groups with a subtle divider and compact group label.

Reasoning:
The operator should not need code knowledge to distinguish preview-only controls from exported geometry contracts.

Consequences:
Do not add new main-UI export sliders, checkboxes, combos, path fields, or material/UDIM controls without a concise tooltip. Keep UI-settings controls separate from this rule unless they affect exported tree data.

Related files:
- `src/xml_to_usda/qt_ui/panels.py`
- `src/xml_to_usda/qt_ui/proxy_preview.py`
- `src/xml_to_usda/qt_ui/fracture_preview.py`

## Decision: FBX Prototype Preview loads the selected payload directly

Status: Active

Context:
Prototype Preview is an interactive inspection workflow for one repeated-part
prototype. The FBX mode previously resolved the full assembly model before
showing one selected FBX replacement, which widened native failure surface and
added avoidable latency.

Decision:
For `FBX file` Prototype Preview, load the chosen FBX payload directly through
the same FBX read options and payload cache used by export. Keep the full
resolved assembly path for XML mesh preview, where source prototypes and
source material metadata come from the normalized XML model.

Reasoning:
The operator needs a responsive local preview of the selected replacement
payload and material split. Full assembly resolution is unnecessary for that
case and can make a preview crash look like an export-contract failure.

Consequences:
FBX Prototype Preview stays isolated from the UI process, keeps strict
vertex-color validation for `vertex_color_split`, and reuses the bounded FBX
payload cache. It does not redefine exported instance transforms, attachment,
or skeletal binding.

Related files:
- `src/xml_to_usda/part_preview_service.py`
- `src/xml_to_usda/qt_ui/part_preview.py`

## Decision: Fracture Preview does not remove small branches by default

Status: Active

Context:
`Remove Small Branches` is useful as a manual preview simplification control,
but a persisted high value made Fracture Preview hide child branch geometry on
the three-trunk sample and made separated stems look branchless.

Decision:
Fracture Preview defaults `Remove Small Branches` to `0.0` and does not restore
that field from persisted GUI settings. The operator can still raise it during
the current session when intentionally inspecting a simplified base mesh.

Reasoning:
Fracture Preview is primarily a fracture-plan diagnostic. Its default must show
the complete source base geometry for every piece, otherwise missing branches
look like planner or ownership bugs.

Consequences:
Keep Proxy Mesh pruning defaults separate from Fracture Preview. Do not make
Fracture Preview inherit the shared mesh-pruning default again.

Related files:
- `src/xml_to_usda/fracture_preview_service.py`
- `src/xml_to_usda/settings_service.py`

## Decision: Fracture Preview repeated-part visibility is viewport-only

Status: Active

Context:
Rapid or unlucky `Hide Repeated Parts` toggles could crash the packaged Qt
process with a native `0xc0000005` fault while rebuilding and re-uploading the
Fracture Preview OpenGL payload. Keeping the full payload resident also failed
on BigSpruce: 3613 hidden instances expanded to 38,044,065 vertices and a
2.59 GB upload, beyond Qt's signed buffer-size limit.

Decision:
When Repeated Parts are hidden, build and upload only the Base Mesh payload.
Build the full payload lazily on the first explicit show; after that upload,
hide/show changes only the visible vertex range. Reject an oversized payload
before allocating or passing it to Qt.

Reasoning:
The checkbox is a visual inspection filter, not an operator setting that changes
fracture ownership. Hidden geometry must consume neither CPU expansion memory
nor GPU upload capacity. Reusing a successfully loaded full payload keeps later
toggles realtime without restoring the startup overflow.

Consequences:
Opening Fracture Preview with the default hidden state is bounded by Base Mesh
geometry. Showing Repeated Parts may perform one deliberate upload; later
toggles reuse it. Future visual-only controls should update viewport state or
shader uniforms whenever possible.

Related files:
- `src/xml_to_usda/qt_ui/fracture_preview.py`
- `src/xml_to_usda/qt_ui/viewport.py`

## Decision: Fracture Preview source facts use a typed cache

Status: Active

Context:
Fracture Preview settings changes restart the isolated preview worker. Re-reading
and re-normalizing the same SpeedTree XML for every branch-count, stem, height,
caps, or preview-quality change was both slower and a larger native-crash
surface in the packaged worker path.

Decision:
Cache the slim Fracture Preview source facts as a typed `.npz` payload keyed by
source path, file size, mtime, cache schema, and parser mode. The cache stores
only the preview source model facts needed by fracture planning and preview
generation: metadata, base mesh, skeleton, repeated parts, prototypes, and
diagnostics. It does not use pickle and loads with `allow_pickle=False`.

Reasoning:
The earlier generic worker-payload JSON cache serialized full dataclass graphs
and was slower than direct reload on large trees. The typed cache avoids per-
`Vector3` object metadata and keeps the cache narrow to this workflow.

Consequences:
Fracture Preview warm runs should reuse source facts and recompute only the
settings-dependent fracture preview. Corrupt or stale cache files are deleted
and fall back to XML reload. Do not replace this with the generic source-model
JSON cache.

Related files:
- `src/xml_to_usda/fracture_preview_service.py`
- `tests/test_fracture_preview_service.py`

## Decision: Runtime caches are centrally bounded

Status: Active

Context:
The converter now has several useful persistent caches: FBX payloads, generic
source models, Proxy Source Projections, and Fracture Preview source facts. The
file-signature keys keep them correct, but old entries from changed XML files
would otherwise accumulate indefinitely.

Decision:
Keep disk-retention policy in `cache_maintenance.py`. GUI and CLI startup sweep
runtime/job leftovers, bounded FBX payload cache, source-facts caches, and stale
cache temp files through that module. FBX keeps its operator-configurable size
and age limits. Source-facts caches use a shared default budget of `2 GB` and
`14 days`; stale `.tmp`/`.partial` cache files follow the runtime stale-job TTL.
The Global Settings dialog can clear all managed cache entries.

Reasoning:
Cache producers should own payload shape, but not separate unbounded retention
rules. One runtime-facing maintenance module prevents source/proxy/fracture
caches from becoming invisible disk growth while preserving low-latency warm
preview paths.

Consequences:
New persistent cache directories must be registered with cache maintenance or
explicitly documented as non-user cache. Do not add a workflow cache that only
invalidates by source signature without also giving it age and size cleanup.

Related files:
- `src/xml_to_usda/cache_maintenance.py`
- `src/xml_to_usda/qt_ui/window.py`
- `src/xml_to_usda/cli.py`
- `tests/test_cache_maintenance.py`

## Decision: Wind Preview uses base groups plus manual override layers

Status: Active

Context:
Wind Preview started as a read-only XML inspector with explicit Auto Hierarchy
preview grouping. The current workflow uses the same window to author Dynamic
Wind JSON for both SpeedTree XML skeletons and external FBX/USD skeletons
without creating a separate viewport system.

Decision:
Keep Wind Preview as a separate PySide6 dialog on the shared viewport path, but
move the product contract toward a stack model: XML Generator Groups or Auto
Hierarchy provide the base groups, and manual override layers sit above them.
Higher layers win, empty manual groups are ignored, and final non-empty visible
groups are compacted bottom-up before Dynamic Wind JSON export. Manual edits are
stored as explicit child-joint token assignments, so visual colors and exported
JSON describe the same final result.

Reasoning:
This keeps the XML-derived path, the independent skeleton analyzer, and manual
operator correction in one deterministic model. It also supports non-SpeedTree
trees from Houdini, Blender, or other DCC tools by loading external skeletons
without mesh geometry and running Auto Hierarchy before optional manual fixes.

Consequences:
Group order is bottom-up like layer stacks: group 0/trunks are the bottom layer
and `+` inserts new manual groups above all existing layers. Auto Hierarchy must
not read XML generator labels; it uses SpeedTree/file joint ordering plus the
explicit `Continue line` policy visible only in Auto mode. Missing coverage,
duplicate external joint names, missing skeletons, and unavailable import
backends fail loudly. Wind Preview JSON export uses the existing Dynamic Wind
JSON schema and output-path derivation rather than introducing a new schema.
The right panel uses one global settings scroll; Layers is the only nested
scroll, resizes vertically through a local handle even when the global scrollbar
is visible, and owns compact `+`/`-` manual-layer actions. Wind Preview opens
taller than the shared preview default and defaults the right panel to the
midpoint between its minimum and maximum width. Undo/redo remain shortcut-only
and are surfaced through viewport shortcut hints instead of visible panel
buttons. Text `.usda` and ASCII `.usd` external skeleton loading must not depend
on `pxr`; when OpenUSD Python is unavailable, Wind Preview reads text Skeleton
blocks directly. Multiple USD Skeleton prims require an explicit operator
choice through the Skeleton dropdown. The loader must not choose by largest
joint count, prim order, or name. Binary `.usd`/`.usdc` stay behind the `pxr`
requirement.
The SpeedTree worker result must not contain the full CanonicalTreeModel beside
the already-built viewport scene. It carries only the skeleton, Dynamic Wind
data, and compact Base Mesh scene buffers. Repeated Parts are omitted entirely:
Wind Preview inspects the skeleton, and repeated geometry adds visual noise
without changing grouping or JSON. Grouping edits recolor those existing draw
calls and replace the bone overlay. A restored valid XML
path triggers the same Wind-group refresh as the manual button after startup.
If Preview is requested before that refresh finishes, queue it instead of
normalizing the same large XML concurrently in the GUI and preview worker. A
native Wind Preview process crash receives one clean-process retry; a second
failure remains fail-loud. All worker environments enable Python faulthandler
so native failures can populate the existing stderr crash context.
Detailed V2 behavior lives in `docs/wind_viewport_working_plan.md`.

Related files:
- `src/xml_to_usda/wind_preview_service.py`
- `src/xml_to_usda/wind_viewport_scene.py`
- `src/xml_to_usda/qt_ui/wind_preview.py`
- `tests/test_wind_viewport_scene.py`

## Decision: Preview dialogs share one viewport system

Status: Active

Context:
Proxy Preview, Fracture Preview, Part Prototype Preview, and Wind Preview all
render inspection geometry through the Qt/OpenGL viewport. A crash in one
preview is often a viewport lifecycle, upload, camera, or overlay problem that
can affect other previews later.

Decision:
Keep `MatcapViewport` and `ViewportScene` as the shared viewport seam. Preview
mode dialogs may differ in controls, source requests, worker strategy, and
Qt-free scene adapters, but they should not invent separate viewport behavior
for rendering, OpenGL upload, camera fit, bone overlay, picking, static-scene
precompute, or trace milestones. When a viewport fix is generally useful, add a
public `MatcapViewport` interface and route the mode dialog through it.

Reasoning:
The working previews are evidence that the shared viewport system is the safer
contract. A mode-specific rendering path hides native crash fixes in one dialog
and makes future previews drift. A shared interface keeps leverage high: one
fix improves every preview that uses the same upload and overlay path.

Consequences:
Do not import private viewport helpers from mode dialogs to solve a rendering
or upload problem. Do not add a second OpenGL widget for a new preview unless
the existing viewport cannot represent the required primitive after a measured
attempt to extend it. Heavy static scenes should use the shared
`MatcapViewport.set_scene(..., precompute_static=True)` path or a documented
public equivalent. Visual-only selection, highlight, or visibility changes
should not rebuild or re-upload static mesh buffers; add a small public
viewport update method instead. Every viewport window should show active
shortcuts briefly in the bottom-right corner as small translucent text, so
mode-specific interactions remain discoverable without adding instructional UI
blocks. Packaged smoke should cover any new high-risk viewport path.

Related files:
- `src/xml_to_usda/qt_ui/viewport.py`
- `src/xml_to_usda/viewport_scene.py`
- `src/xml_to_usda/qt_ui/wind_preview.py`
- `src/xml_to_usda/qt_ui/fracture_preview.py`
- `src/xml_to_usda/qt_ui/proxy_preview.py`
- `src/xml_to_usda/qt_ui/part_preview.py`
- `src/xml_to_usda/qt_ui/smoke.py`

## Decision: Qt UI polish uses direct widget screenshots before packaging

Status: Active

Context:
Small visual changes in PySide6 dialogs were previously validated mostly by
building the packaged app, then having the operator open the UI manually. That
loop is slow and misses obvious layout issues until late.

Decision:
For UI layout/style work, first render the target Qt widget or dialog directly
from `.venv310`, call `show()`, `QApplication.processEvents()`, then save a
PNG with `widget.grab().save(...)`. Inspect that image before running the
slower packaged gate. Use this especially for right panels, preview dialogs,
button density, scroll behavior, dropdown styling, and text overlap.

Reasoning:
This is the shortest reliable feedback loop for visual regressions. It keeps
design iteration local to the changed widget and lets the agent see the same
layout problems the operator would see, without waiting for PyInstaller.

Consequences:
Direct screenshots do not replace tests or packaged high-risk smoke. They are
a preflight visual check before final validation. Prefer grabbing the smallest
useful widget, for example `dialog.settings_panel.grab()`, so the screenshot is
easy to inspect. Delete temporary screenshots after use unless the user asks to
keep them.

Related files:
- `src/xml_to_usda/qt_ui/`
- `tests/test_qt_wind_preview_dialog.py`
- `docs/wiki/architecture.md`

## Decision: Fracture Geometry is one deep preview/export module

Status: Active

Context:
The former Fracture path assigned whole faces by centroid and generated caps
from ownership boundaries. Preview, export, collision, Repeated Part ownership,
and cap behavior could not remain exact through that interface.

Decision:
Keep planning in `fracture_service.py` and place settings-dependent mesh work
behind the `prepare_fracture_geometry(...)` interface. The Fracture Geometry
module owns subtree-local Cut Surfaces, deterministic noisy clipping, attribute
interpolation, loop validation, cap triangulation, and manual cross-section
snapping. Preview simplifies only after
this geometry contract; export and collision consume the same per-piece mesh.

Consequences:
`noisy_cut_enabled=False` preserves the legacy face-ownership path. Repeated
Parts remain with the Fracture Piece determined by their skeleton attachment;
their prototype bounds do not veto cuts. A manual segment cut that lands on an
open source junction snaps to the nearest tested 0.1 segment position with a
closed cross-section and records a warning; if none exists, it fails loudly.
Automatic branch cuts use the child `bind -> bind_end` direction and first try
30% inside the child bone, leaving a visible broken stub and avoiding parent
branch triangles. If that exact cross-section cannot split/cap safely, geometry
tries deterministic 5% steps up to 80% on the same bone and records a warning;
the selected cut and Fracture Piece do not change. Stump/stem joint cuts retain
the 2% offset.
Automatic cuts map noise to the child side of the base plane, so displacement
cannot cut backward into the parent/stump. Manual cuts remain symmetric around
the operator-selected position. Noisy edge roots are isolated deterministically;
if a fixed cut would cross one edge more than once or produce an invalid cap,
only that surface amplitude is retried at 75%, 50%, 25%, then flat. The selected
cut and piece structure never change, and attenuation records a warning. `Stump
Piece` plans one cut per independent stem. Multi-stem sources use a segment cut
near the end of each first stem bone because some SpeedTree stems have no faces
owned directly by their root joint.

Fracture Preview uses one persistent crash-isolated worker for sequential
settings changes. This preserves process isolation while avoiding packaged
Python startup and source-cache reconstruction on every slider release. Cancel
terminates the server; the next request starts a clean one. Viewport triangle
packing is NumPy-vectorized rather than a per-vertex Python loop.

Related files:
- `src/xml_to_usda/fracture_geometry.py`
- `src/xml_to_usda/fracture_preview_service.py`
- `src/xml_to_usda/fracture_export_service.py`
