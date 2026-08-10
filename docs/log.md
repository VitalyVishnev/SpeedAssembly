# Documentation Log

## 2026-07-01 - LLM Wiki migration

- Created `docs/raw/` and moved the existing documentation corpus there as preserved source material.
- Created `docs/wiki/` with maintained navigation, overview, architecture, decisions, bugs, experiments, and glossary pages.
- Added wiki maintenance rules to `AGENTS.md`.
- Updated the project README to point at the maintained wiki and legacy raw sources.
- Preserved the historical archive under `docs/raw/archive/`.

Major moves:

- `docs/ARCHITECTURE.md` -> `docs/raw/ARCHITECTURE.md`
- `docs/DECISIONS.md` -> `docs/raw/DECISIONS.md`
- `docs/GLOSSARY.md` -> `docs/raw/GLOSSARY.md`
- `docs/PROJECT_MAP.md` -> `docs/raw/PROJECT_MAP.md`
- `docs/ARCHITECTURE_IMPROVEMENT_PLAN.md` -> `docs/raw/ARCHITECTURE_IMPROVEMENT_PLAN.md`
- `docs/developer_architecture.md` -> `docs/raw/developer_architecture.md`
- `docs/REFRACTOR_LOG.md` -> `docs/raw/REFRACTOR_LOG.md`
- `docs/local-python-environment.md` -> `docs/raw/local-python-environment.md`
- `docs/speedtree_mapping.md` -> `docs/raw/speedtree_mapping.md`
- `docs/stage0_stress_validation.md` -> `docs/raw/stage0_stress_validation.md`
- `docs/test_suite_map.md` -> `docs/raw/test_suite_map.md`
- `docs/test_tiers.md` -> `docs/raw/test_tiers.md`
- `docs/troubleshooting.md` -> `docs/raw/troubleshooting.md`
- `docs/ue_import_contract.md` -> `docs/raw/ue_import_contract.md`
- `docs/ui_next_architecture.md` -> `docs/raw/ui_next_architecture.md`
- `docs/ui_review_workflow.md` -> `docs/raw/ui_review_workflow.md`
- `docs/ui_theme_bake.md` -> `docs/raw/ui_theme_bake.md`
- `docs/ui_theme_contract.md` -> `docs/raw/ui_theme_contract.md`
- `docs/wind_dynamic_json.md` -> `docs/raw/wind_dynamic_json.md`
- `docs/workflow_status.md` -> `docs/raw/workflow_status.md`
- `docs/archive/refactor_roadmap.md` -> `docs/raw/archive/refactor_roadmap.md`

## 2026-07-01 - Wiki contract cleanup

- Integrated active known-problem tracking into `docs/wiki/known-bugs.md`.
- Kept current contracts in `docs/wiki/decisions.md` and rejected or superseded approaches in `docs/wiki/experiments.md`.
- Updated `AGENTS.md` to treat the wiki as the active maintenance surface and `docs/raw/KNOWN_PROBLEMS.md` as legacy-only.
- Added navigation links between the maintained wiki pages and the documentation log.
- Archived the former root `KNOWN_PROBLEMS.md` content under `docs/raw/KNOWN_PROBLEMS.md`.

## 2026-07-01 - Wiki polish pass

- Rebuilt `AGENTS.md` with clean UTF-8 text after a codepage corruption in the Russian rules section.
- Removed the root `KNOWN_PROBLEMS.md` pointer so active problem tracking stays in `docs/wiki/known-bugs.md`.
- Trimmed `README.md` to match the `docs/wiki/` and `docs/raw/` split more directly.

## 2026-07-01 - Wiki terminology and bug-surface pass

- Added short-plus-full assembly naming to the maintained overview and glossary.
- Moved the fixed large-GUI worker isolation note out of `docs/wiki/known-bugs.md` and into `docs/wiki/decisions.md`.
- Narrowed `docs/wiki/known-bugs.md` to current dangerous or still-open issues.

## 2026-07-01 - Proxy base-mesh simplification priority

- Added deterministic connected-component pruning before Proxy Mesh base-mesh QEM simplification.
- Documented that the fix targets branchy base meshes with tiny terminal geometry and is not full foliage/shell zoning.

## 2026-07-01 - Shared small-branch pruning module

- Moved base-mesh connected-component pruning behind `src/xml_to_usda/mesh_pruning.py`.
- Added a persisted `branch_prune_aggression` setting for Proxy Mesh Preview and Fracture Preview.
- Wired Fracture Preview to prune tiny disconnected base-mesh branch islands before face sampling.
- Made `Remove Small Branches` literal and linear: it removes the requested percentage of the smallest connected islands, with no hidden face-budget cutoff.

## 2026-07-01 - Practical test-density policy

- Updated `AGENTS.md` and `docs/wiki/decisions.md` to keep existing tests but avoid adding or rewriting tests for every small edit or intermediate experiment.
- Clarified that new tests should protect stable features, new modules, public contracts, and importer-facing invariants with compact intent-level coverage.

## 2026-07-01 - Proxy Mesh large-tree speed pass

- Disabled the generic source-model JSON cache for Proxy Mesh source loading after profiling showed cache serialization dominating large-tree jobs.
- Trimmed proxy hot-path overhead in base-mesh budget counting, connected-component pruning, foliage bounds preparation, and XML source-limit traversal.
- Measured `SK_BirchAltai_Assembly_13.xml` at about 5.2s after the pass versus about 17.1s before, without adding the temporary tree to the repository.

## 2026-07-01 - Proxy Source Projection cache

- Added `src/xml_to_usda/proxy_source_projection.py` so Proxy Mesh source requests load only base geometry, repeated-part transforms, and source prototype geometry.
- Added a typed `.npz` Proxy Source Projection cache with `allow_pickle=False` reads and file-signature invalidation.
- Validated projection output against canonical-derived proxy output on repo samples and the temporary `SK_BirchAltai_Assembly_13.xml`.
- Measured the temporary Birch proxy path at about 4.0s cold and about 2.0s warm with the projection cache.

## 2026-07-01 - Proxy Mesh polish latency pass

- Reduced Proxy Mesh cold latency by speeding source-limit packed value counting without disabling XML safety budgets.
- Trimmed connected-component pruning allocations in `src/xml_to_usda/mesh_pruning.py`.
- Recorded the default low-latency policy for interactive preview/setup workflows.
- Measured the temporary Birch proxy path at about 3.5s cold and about 1.85s warm after the polish pass.

## 2026-07-01 - Fracture Preview generic-cache bypass

- Bypassed the generic Fracture Preview source-model JSON cache after profiling showed it was slower than direct reload on both BigSpruce and the temporary Birch sample.
- Cached worker-payload class and dataclass metadata lookups so existing JSON worker payloads do less repeated Python/import work.
- Measured BigSpruce Fracture Preview at about 1.0s without the generic cache versus about 2.5s cached, and temporary Birch at about 6.8s without the generic cache versus about 9.0s cached warm.

## 2026-07-02 - Main UI parameter guidance

- Added the maintained rule that main export-tree UI parameters need concise English tooltips and functional grouping.
- Covered Wind, Geometry, Materials, Proxy Mesh, Fracture Preview, and prototype preview controls with short parameter tooltips.

## 2026-07-04 - Prototype Preview FBX and panel fix

- Recorded that FBX Prototype Preview loads the selected FBX payload directly instead of resolving the full assembly model.
- Noted the UI/runtime boundary for the fixed Prototype Preview path.

## 2026-07-04 - Fracturing V1 natural detach planner

- Implemented V1 automatic fracturing as length-ranked branch-base detachment plus optional stump and independent stem separation.
- Removed automatic trunk-chain refinement and synthetic face median splitting from auto-fill; candidate exhaustion now clamps with a diagnostic.
- Added Branch Height Bias, Separate Stems, Auto Branches UI semantics, and realtime exploded skeleton offsets.
- Measured preview planning at about 0.07s on `SimpleTree_01`, 0.18s on `SimpleTree_02_three_trunks`, and 1.7s on repo `BigSpruce`.

## 2026-07-05 - Fracture Preview small-branch default

- Set Fracture Preview `Remove Small Branches` default to `0.0` and stopped restoring/saving that field through GUI settings.
- Kept manual small-branch removal available for the current preview session while preventing stale high values from hiding child branch geometry by default.

## 2026-07-05 - Fracture Preview repeated-part visibility stability

- Changed `Hide Repeated Parts` from a Fracture Preview mesh rebuild into a viewport-only visible vertex range toggle.
- Added UI and packaged-smoke coverage so repeated-part visibility toggles no longer re-upload OpenGL buffers.

## 2026-07-05 - Fracture Preview typed source cache

- Added a typed `.npz` Fracture Preview source-facts cache for the slim preview model.
- Rejected the trial generic JSON cache path after timings showed it was slower than direct reload.
- Local timings: BigSpruce direct median about `3.35s`; generic JSON warm about `4.10s`; typed `.npz` warm about `3.02s`.

## 2026-07-05 - Wind viewport planning

- Added a separate wind preview plan next to the Fracturing V1 working plan.
- Fixed the first wind viewport scope to XML-only read-only inspection with subtree selection, group colors, and no editor/import/export in V1.

## 2026-07-05 - Central cache maintenance

- Added `cache_maintenance.py` as the runtime owner for bounded cache retention.
- GUI and CLI startup now sweep runtime leftovers, FBX payload cache, source-facts caches, and stale cache temp files through one policy.
- Added Global Settings support for total cache summary and clearing all managed cache entries.

## 2026-07-05 - Wind Preview V1

- Implemented the read-only XML Wind Preview dialog with group list, stable group colors, skeleton overlay, group highlighting, and `Ctrl+click` subtree highlighting.
- Added a Qt-free wind viewport scene adapter and a source-facts preview service that fails on missing XML generator labels.
- Recorded the Wind Preview V1 contract as an inspector only, with no group editing, persistence, external skeleton import, or wind JSON export.

## 2026-07-05 - Wind Preview viewport crash fix

- Moved static scene precompute behind the shared `MatcapViewport.set_scene(..., precompute_static=True)` interface instead of keeping a Wind-only viewport path.
- Wired Wind Preview through the same shared viewport upload contract used by other preview dialogs.
- Added `wind-preview` to packaged high-risk smoke so packaged GUI builds must open Wind Preview, upload the viewport scene, and keep bone overlay visible.
- Recorded the broader viewport rule: previews may have different mode dialogs and adapters, but rendering/upload/camera/overlay behavior must stay in the shared viewport system.

## 2026-07-05 - Wind Preview layer order and Auto Hierarchy

- Fixed the Wind Preview group list contract to bottom-up layers: group 0/trunks are the bottom layer and higher branch groups appear above them.
- Added preview-only Auto Hierarchy grouping with a 1..10 integer group-count slider; deeper descendants cap into the highest selected group.
- Made Clear Selection idempotent and covered it in packaged Wind Preview smoke.
- Recorded the future manual `+` rule: new layers are inserted at the top of the stack.

## 2026-07-05 - Wind Preview Auto Hierarchy branch-order fix

- Changed Auto Hierarchy from per-bone depth grouping to branch fork-order grouping.
- Kept linear branch chains in the same group and advanced group level only for child branches splitting off at forks.
- Tightened Wind layer buttons so long group labels no longer overflow the right panel.

## 2026-07-05 - Wind Preview Auto Hierarchy generator-level attempt rejected

- Rejected the trial where Auto Hierarchy used XML generator levels as the primary source; that did not satisfy the independent skeleton-analysis requirement.
- Changed Auto Hierarchy to use SpeedTree skeleton ordering instead: contiguous child order continues the current branch path, non-contiguous child subtrees advance one group level.
- Added regression coverage that strips generator labels and still matches the hand-authored XML group result on `SimpleTree_01` and `SimpleTree_02_three_trunks`.

## 2026-07-05 - Wind Preview Auto Hierarchy per-layer continuation

- Added preview-only per-layer `Continue line` checkboxes for Auto Hierarchy so selected levels can keep endpoint-continuous child chains in the same group even when the child joint is not adjacent in SpeedTree order.
- Kept strict Auto Hierarchy as the default so stripped-label `SimpleTree_01` and `SimpleTree_02_three_trunks` still match the current XML generator grouping unless the operator opts into continuation.
- Made the Wind Preview grouping dropdown visibly highlight on hover/focus.

## 2026-07-05 - Wind Preview worker isolation

- Moved Wind Preview source loading and viewport-scene construction from a GUI thread into a file-backed `wind-preview-worker`.
- Kept the dialog and OpenGL upload in the Qt process while giving Wind Preview the same worker crash/error context pattern as the other heavy previews.

## 2026-07-05 - Wind Preview layer selection stability

- Changed Wind Preview layer selection to update only shared viewport bone overlay state instead of rebuilding and re-uploading the static matcap mesh.
- Added shared `MatcapViewport.set_bone_segments(...)` and covered the bottom-layer selection path in packaged Wind Preview smoke.

## 2026-07-09 - Wind Preview V2 working plan

- Replaced the Wind Viewport working plan with the agreed V2 contract for manual override layers, External Skeleton Wind, preview-local Dynamic Wind JSON export, autosave, undo/redo, and fail-loud coverage rules.
- Updated maintained wiki references so Wind Preview is no longer documented as permanently read-only while still marking V2 as planned rather than implemented.
- Added the shared viewport rule that active shortcuts should appear as small translucent bottom-right hints in every viewport window.

## 2026-07-09 - Wind Preview V2 partial implementation

- Added a Qt-free Wind group stack for base XML/Auto groups plus manual override layers, with top-layer precedence and compact bottom-up JSON indices.
- Wired Wind Preview manual groups, subtree/bone picking, Alt removal, Delete/Clear, undo/redo, contextual shortcut hints, and preview-local Dynamic Wind JSON export.
- Added missing-label XML fallback to Auto Hierarchy and skeleton-only External FBX loading; verified the attached high-poly Black Alder FBX loads as 966 joints without mesh geometry.
- Left autosave restore, External Skeleton worker isolation, and USD skeleton import as open V2 items.

## 2026-07-09 - Wind Preview V2 autosave and external skeleton completion

- Added Wind Preview session autosave in GUI settings with skeleton fingerprint restore/reset behavior and empty undo history after restore.
- Routed External Skeleton loading through the Wind Preview worker process for FBX/USD requests and added single-skeleton USD/UsdSkel skeleton-only loading.
- Kept multi-skeleton USD choice deferred and documented it as an explicit fail-loud limitation.

## 2026-07-09 - Wind Preview autosave crash fix

- Fixed Wind Preview opening after worker result when GUI settings autosave fails with `OSError`/`PermissionError`; the preview now stays open and reports autosave failure in status/trace.

## 2026-07-09 - Wind Preview compact right panel

- Reworked Wind Preview's right panel into compact controls with a scrollable settings pane and a separate resizable Layers pane.
- Overrode Wind Preview's local button sizing so global action-button styling no longer makes layer/edit/export controls too tall or overlapping.
- Moved Layers directly under Edit, kept Generate JSON as the bottom action block, and replaced heavy combo-box arrows with a compact local chevron asset.

## 2026-07-09 - Qt direct screenshot workflow

- Documented the direct PySide `widget.grab()` screenshot loop as the preferred fast preflight for UI layout/style work before packaged builds.

## 2026-07-09 - Wind Preview right panel scroll contract

- Replaced the split top-controls/Layers layout with one global settings scroll and a nested resizable Layers scroll above Generate JSON.
- Moved manual-layer `+`/`-` actions into the Layers header, removed visible Undo/Redo buttons, and kept undo/redo discoverable through viewport shortcut hints.
- Updated the Wind Viewport plan and wiki architecture/decisions with the compact right-panel contract.

## 2026-07-10 - Wind Preview default geometry and Layers resize

- Set Wind Preview to open taller and default its right panel to the midpoint between the panel's minimum and maximum width.
- Replaced the nested Qt splitter with a local Layers resize handle so resizing remains stable when the global right-panel scrollbar is visible.
- Lowered the Layers scroll minimum so the group stack can collapse to about two visible rows.

## 2026-07-10 - Wind Preview text USDA skeleton loading

- Added a `pxr`-free text USDA/ASCII USD skeleton fallback for External Skeleton Wind Preview.
- The initial fallback chose the unique largest skeleton by joint count; this was later superseded by explicit Skeleton prim choice.
- Recorded the current Wind Preview right-panel UI as the accepted compact vertical quality bar.

## 2026-07-10 - Wind Preview USD skeleton chooser

- Added `usd-core` as the normal OpenUSD/`pxr` dependency for USD External Skeleton loading.
- Replaced largest-skeleton autoselection with explicit Skeleton prim enumeration and operator choice in Wind Preview.
- Documented largest-skeleton autoselection as a rejected heuristic.

## 2026-07-10 - Wind Preview USD skeleton choice path fix

- Fixed the Skeleton dropdown losing the selected USD skeleton when the UI path and worker-returned path used different Windows separators.
- Added regression coverage so the second `Load` sends the selected skeleton index instead of asking the operator to choose again.

## 2026-07-10 - Wind Preview initial scene stall fix

- Reused the worker-built initial viewport scene instead of rebuilding the same large SpeedTree scene on the GUI thread.
- Added fail-loud GUI error handling so scene setup failures replace `Preparing wind preview...` and enter the runtime trace.

## 2026-07-10 - Packaged Wind Preview native worker crash fix

- Kept the SpeedTree XML worker path independent from External FBX/USD imports.
- Narrowed the OpenUSD PyInstaller hook to the runtime `Usd`/`UsdSkel` dependency set and excluded unused debug/TBB binding binaries that produced native packaging instability.

## 2026-07-11 - Viewport right-panel alignment

- Moved Wind Preview's compact dropdown/popup treatment into the shared preview shell and applied it to Proxy Mesh, Fracture, and Prototype Preview.
- Gave Proxy Mesh the same global settings scroll and aligned all viewport panels to the Wind Preview default width; Fracture keeps its wheel-to-scroll safety behavior.

## 2026-07-11 - Main settings panel alignment

- Applied the shared compact Wind Preview controls to the main Wind, Geometry, and Materials tabs without changing the title bar or primary actions.
- Made UDIM tile IDs explicit bordered input fields across the main tabs and preview dialogs.

## 2026-07-11 - Exact noisy fracture geometry

- Replaced centroid-only fracture slicing with subtree-local deterministic Cut Surfaces, polygon clipping, interpolated vertex attributes, and intersection-loop caps shared by preview and export.
- Added Noisy Cuts, Cut Intensity, and Chip Scale operator settings with persistence, tracing, worker/cache participation, and Qt controls.
- Added transformed Repeated Part bounds classification, cap/topology-safe automatic candidate preflight, final-mesh collision input, and a preserved legacy path when Noisy Cuts is disabled.
- Profiled BigSpruce and moved preflight and cut-band filtering into NumPy-backed source facts so repeated parameter changes remain bounded and avoid full-tree Python clipping.
- Isolated nonlinear noisy edge roots and reject multiple crossings instead of applying linear plane interpolation.
- Fixed multi-stem stump planning: every stem receives a near-base segment cut, and Separate Stems produces one stump piece per stem on the real three-trunk sample.
- Replaced one-shot Fracture Preview workers with a persistent crash-isolated preview server and bounded one-source memory cache; local BigSpruce worker timing improved to about 1.4s for a warm parameter update.
- Vectorized Qt viewport triangle packing; the 50k-triangle BigSpruce adapter stage dropped from about 2s to about 0.08s locally.
- Lowered the hidden interactive per-piece preview cap from 50k to 20k faces, including migration of the old persisted value; exact export geometry is unchanged.

## 2026-07-11 - BigSpruce Wind Preview worker memory fix

- Stopped serializing the full CanonicalTreeModel beside the worker-built Wind viewport scene; BigSpruce's result is now a compact 17 MB payload.
- Reused one base-mesh face-range table for all joint batches instead of rebuilding the full table 1108 times on BigSpruce.
- Together, the compact payload and shared range table remove the worker path that grew past 5 GB and ended with `0xC0000005`.
- Bounded only the interactive repeated-part mesh payload before Qt flattening; BigSpruce keeps all 3613 placements and complete Wind data while avoiding a 26.5-million-triangle viewport bake.
- Reused the existing mesh buffers for grouping edits and changed only draw-call colors and the bone overlay.
- Added automatic Wind-group refresh when a valid persisted XML path is restored at startup; the manual Refresh button remains available.

## 2026-07-12 - Wind Preview native crash recovery

- Queued an immediate Preview request until startup Wind-group inspection finishes, avoiding concurrent large-source normalization.
- Added one clean-process retry for unexpected Wind Preview worker exits such as `0xC0000005`; a repeated failure still surfaces normally.
- Enabled Python faulthandler in every worker environment so future native crashes can leave a stack in captured stderr instead of an empty file.

## 2026-07-16 - Wind Preview skeleton-only geometry

- Removed Repeated Parts from Wind Preview entirely; the viewport now shows only Base Mesh ownership colors and the skeleton overlay.
- Removed the superseded repeated-part sampling and transport path. BigSpruce now produces 1108 base draw calls, zero instances, and about 11 MB of viewport vertices.

## 2026-07-16 - Fracture Preview topology and upload fix

- Replaced Fracture Preview face sampling with the same topology-preserving QEM backend used by Proxy Mesh; exact clipping and caps now precede simplification.
- Removed the hidden 20k per-piece ceiling that overrode the visible Preview Polycount; BigSpruce's 57k-triangle stump now stays exact at the saved 6.35M target.
- Stopped expanding hidden Repeated Parts into the initial viewport payload. BigSpruce's reported 2.59 GB Qt upload path is no longer reached when the default hide filter is active.
- Added pre-allocation OpenGL buffer-size validation and surfaced the concrete viewport exception plus debug-log path instead of an empty generic error.

## 2026-07-17 - Stable Noisy Cut planning and manual cuts

- Made Noisy Cuts reuse the exact flat-planner structure; BigSpruce now keeps its stump and the same 11 length-ranked branch cuts instead of falling through to micro-branches.
- Kept Repeated Parts with their skeleton-attached piece instead of vetoing cuts with transformed prototype bounds.
- Isolated automatic branch clipping to the child subtree and moved the surface 30% into the first child bone so a visible broken stub remains and SimpleTree junction caps stay closed.
- Added deterministic manual-cut snapping to the nearest tested closed cross-section and clarified Cut Intensity versus Chip Scale tooltips.
- Made automatic noise one-sided toward the detached child so it cannot carve backward into the parent/stump; manual noise remains centered on the selected position.
- Added per-surface deterministic noise attenuation as a last-resort topology guard without replanning cuts; the 28M stability sample now keeps all five cuts at full intensity.
- Made packaged smoke errors non-modal: GUI failures now abort the scenario, write the JSON report/stderr, and print the concrete failure back to the build terminal automatically.
- Added same-bone automatic cut-position fallback from 30% to 80% in deterministic 5% steps for high-count cap scenarios; strict stability failures now print nested smoke errors directly to stderr.

## 2026-07-17 - Isolated Manifold Boolean fracture prototype

- Added a standalone one-cut connectivity-first Boolean path backed by `manifold3d`, with oriented loop closure, provenance, one-sided fractal lattice cutter, complementary split, common cap topology, volume conservation, and fail-loud diagnostics.
- Added a synthetic open cylinder with a manual skeleton cut and a separate Qt viewer for Original Shell, Closed Solid, Cutter Surface, Parent Stub, and Detached Branch.
- Verified the geometry core on the synthetic cylinder, Simple Tree `bone_086`, and Big Spruce `bone_508`; production Fracture Preview/export remains unchanged.

## 2026-07-17 - Physical-bone manual cut contract

- Changed manual cut position, direction, planner ownership, preview overlay, and Boolean prototype to use `child.bind → child.bind_end` instead of the hierarchy connector whenever `bind_end` exists.
- Prevented a manual branch cut from absorbing sibling branches that share the same trunk parent.
- Updated the synthetic cylinder to contain a distinct connector and verified real manual midpoint cuts on Simple Tree `bone_086` and Big Spruce `bone_508`.

## 2026-07-17 - Interactive Boolean prototype parameters

- Added editable cut position, intensity, chip scale, and remesh density controls to the standalone Boolean prototype viewer with explicit in-place regeneration and refreshed diagnostics/timings.
- Kept the noise seed deterministic so parameter comparisons remain repeatable.
- Removed the normalized intensity ceiling; the prototype UI now permits values through `100` for aggressive splinter-shape experiments.

## 2026-07-17 - Skeleton-limited Boolean noise and attribute transfer

- Uniformly limited requested cutter amplitude before the next physical skeleton terminal, branch, or bend above the editable `Max Bend Angle`, reserving one lattice edge and reporting requested/effective amplitude.
- Added exact source-triangle Manifold provenance and barycentric transfer of UV0, UV1, vertex colors, material sections, and normalized skin weights.
- Added planar cutter-space cap UVs plus side-local boundary-ring material/color/skinning transfer; verified synthetic, Simple Tree `bone_086`, and Big Spruce `bone_508`.

## 2026-07-17 - Prepared Boolean regeneration and shared planner speedup

- Split one-time Boolean cut preparation from cutter regeneration; the viewer now reuses plan, triangulation, connectivity, closed source solid, provenance, and static debug stages until the cut token changes.
- Replaced the shared planner's repeated selected-cut ancestry scan with one parent walk per skeleton joint, preserving deepest-cut ownership for Preview, Export, and Boolean.
- On local Big Spruce benchmarks, repeated Boolean regeneration fell to a 56 ms median; the shared 11-cut planner fell from 122 ms to 90 ms and the 64-cut stress plan from 1695 ms to 481 ms.

## 2026-07-17 - Multi-cut Boolean tree prototype

- Added `boolean-multi-prototype`: one shared source preparation, reusable independent cut sessions, Fracture Plan ownership assembly, colored piece visibility, exploded view, cut diagnostics, and stage timings.
- Verified 5-cut SimpleTree assembly, 11-cut Big Spruce assembly, and three independent stump Booleans on the three-trunk sample; structural stem separation reuses disconnected source shells without a fake cut.
- Measured repeated sequential Big Spruce regeneration at about 0.88 s for 11 cuts, Intensity 20, Density 8; outer process parallelism remains gated by speed/RSS/stability measurements.

## 2026-07-17 - Shared viewport focus and selective Boolean replan

- Added shared middle-button camera-plane pan, double-click mesh focus, and `F` frame-all to `MatcapViewport`; Boolean viewers expose the shortcuts without owning separate camera code.
- Multi-cut replans now reuse the source context, exact unchanged cut sessions, and their last Boolean results. Adding a Big Spruce stump reused 11 branch cuts and locally took about 353 ms replan plus 99 ms new Boolean.
- Fixed the production normal contract for future integration: hard source/cap perimeter, hard cap edges at 90 degrees or more, and preserved source-side normals.

## 2026-07-17 - Sequential same-shell Boolean cuts

- Grouped cuts by source connectivity component and sequentially split the region owned by each cut's parent Fracture Piece instead of rejecting duplicate components.
- Kept distinct cutter provenance through final regions, canonicalized every complementary cap independently, and transferred UVs, colors, materials, and skinning across pieces with multiple caps.
- Verified SimpleTree stump plus branch cuts on one shell, the three-trunk stump plan, and the independent 11-cut Big Spruce plan; local SimpleTree four-cut geometry took about 192 ms after preparation.

## 2026-07-17 - Production Detailed Cuts integration

- Replaced the former Noisy Cuts operator with production `Detailed Cuts`, defaulting to Intensity 20 and Cut Detail 8, and routed both Fracture Preview and export through the multi-cut Manifold backend.
- Kept Repeated Parts assigned only by skeleton binding/source bone, reused the existing collision builders on final Boolean meshes, transferred source/cap normals, and forced matching caps while Detailed Cuts are enabled.
- Added a real SimpleTree export regression covering all 39 Repeated Parts, filtered prototypes, authored normals, and capsule collision, plus packaged smoke that toggles Detailed Cuts ten times and varies every parameter.
- Fixed native-session lifetime and test-global tempfile isolation; the full suite completed without worker/native crashes.
- Vectorized cap-corner normal smoothing. Local Intensity 20 / Detail 8 regeneration medians improved from about 508 to 451 ms on SimpleTree and from 1197 to 1068 ms on 11-cut Big Spruce.

## 2026-07-17 - Fracture viewport shading, close zoom, and GL lifecycle

- Made flat and Detailed Fracture Preview use smooth source-surface shading; flat caps retain source normals and QEM payloads without normals receive area-weighted viewport normals.
- Reduced the shared viewport zoom floor from 35% to 0.1% of scene radius and made the near plane distance-adaptive for close cut inspection.
- Deferred scene buffer uploads to `paintGL` instead of forcing `makeCurrent()`/`doneCurrent()` from preview-result callbacks after a rapid Detailed toggle crash ended immediately after `viewport.upload_end`.

## 2026-07-17 - Dominant Boolean shell selection and viewport memory bound

- Selected the unique cut-plane component with strongest cut-bone face ownership, so disconnected descendant twigs with a few transition faces no longer make cuts such as Big Spruce `bone_033` ambiguous.
- Verified complete Detailed geometry for Big Spruce at 7/11/19/37/64 requested branches across height bias, stump, and separate-stem variants.
- Added a 256 MiB Fracture Preview upload budget. A 2.07 GB expanded Repeated Parts request now remains hidden instead of risking CPU/GPU exhaustion; bone visibility and segment count are traced.

## 2026-07-17 - Preview request coalescing and Fracture worker GC stability

- Replaced terminate-on-slider-change with one-active/one-latest scheduling for every process-backed interactive preview; completed but unread jobs remain active and stale results/errors are suppressed.
- Prevented crash retry from replacing a newer pending request and kept explicit close/cancel as the only normal termination path.
- Disabled cyclic GC for the bounded persistent Fracture Preview worker after a packaged `0xC0000005` occurred during cached mesh reconstruction; Big Spruce passed 5/15/28-cut sequential Detailed stress and the full 734-test suite.

## 2026-07-17 - Packaged uint32 Boolean connectivity fix

- Replaced repeated `min(int(numpy.uint32), ...)` edge expressions with one row conversion and comparison-based canonical edge keys in connectivity, boundary-loop, and diagnostics scans.
- Reproduced the reported Big Spruce settings locally, added a direct uint32 connectivity regression, and passed the same 15-branch request through the rebuilt packaged worker.

## 2026-07-17 - Test suite contract map and execution layers

- Recorded the 735-test / 98.16 s baseline and the 489-test default suite / 514-test non-stress collection result in `docs/wiki/testing.md`.
- Added Core, Integration, and Packaged pytest layers plus a single PowerShell test entrypoint; UE validation remains a manual gate.
- Moved the generic source-cache regression from Big Spruce to the equivalent Simple Tree contract after the large-model serialization path raised `0xC0000005`; Big Spruce remains stress-only.

## 2026-07-17 - Restored four compact safety contracts

- Restored `MeshData` boundary validation, deferred Qt GPU upload, and Fracture Preview's 256 MiB upload guard as focused tests.
- Added a packaged smoke scenario that injects one Fracture Preview worker crash and requires exactly one retry with real geometry before passing.
- Final collection is 518 non-stress tests (29.5% below the 735-test baseline); the small variance from the 30% target is intentional because these contracts guard native/UI failure modes.

## 2026-07-17 - Fracture coverage under contract-based test layers

- Restored three focused contracts removed by the test-policy reduction: Qt latest-request delivery without worker termination, smooth Fracture fallback normals, and close viewport focus/zoom.
- Reclassified real-source Detailed export and Boolean workflows as Integration while keeping Big Spruce explicit stress.
- Wired the 26 packaged contract tests into the package build before frozen Detailed Cuts stability and recovery smoke, so the packaged marker is no longer orphaned.

## 2026-07-17 - Fracture cold-cache crash removal and bounded Repeated Parts inspection

- Removed production Fracture Preview `.npz` reconstruction after the packaged Big Spruce worker again raised `0xC0000005` inside `_mesh_from_arrays`; a clean worker now reloads XML once and subsequent settings changes reuse the slim model in memory.
- Measured Big Spruce source preparation at about 0.50 s from `.npz` and 0.79 s from XML locally, accepting the one-time 0.29 s cost to remove the unstable native path.
- Preserved Fracture viewport instancing through OpenGL upload: unique prototype/piece-color geometry is uploaded once and all placement transforms are applied at draw time. Big Spruce keeps all 3613 instances without attempting the former 10.1-million-triangle flatten.

## 2026-07-17 - Encountered Crashes ledger and hardware instancing

- Added `docs/wiki/encountered-crashes.md`, a maintained crash ledger with evidence strength, process boundary,
  systemic class, fix, and regression gate for resolved and open native failures.
- Replaced 3613 per-frame draw/uniform sequences with one compact GPU transform
  buffer and one hardware-instanced draw per unique source mesh.
- The packaged Big Spruce rapid-settings scenario passed three consecutive runs
  with all 3613 instances and no retry; the command-pressure cause remains an
  explicit hypothesis until broader operator use confirms it.

## 2026-07-17 - Detailed Cuts material lookup failure mitigation

- Replaced incremental material lookup mutation with an atomic deterministic
  comprehension after the frozen worker reported an impossible local `int`
  assignment; the precise trigger remains unverified.
- Rebuilt the package and verified Big Spruce through Computer Use by toggling
  Detailed Cuts off/on with 17 pieces and all 3613 repeated instances visible.

## 2026-07-17 - Detailed Cuts native worker isolation

- Replaced the persistent Fracture Preview server with one fresh worker per
  request after Big Spruce produced unrelated access violations and Python
  internal errors after native Boolean work.
- Kept the GUI's one-active/one-latest coalescing contract; no preview workers
  overlap, and a failed native lifetime cannot poison the next request.
- Recorded the incident as CR-010. The native root cause remains unverified;
  repeated packaged Big Spruce UI smoke is the regression gate.
## 2026-07-19 - Public SpeedAssembly README

- Replaced the internal-first root README with a public entry point for SpeedAssembly: release download link, validated UE 5.7.x skeletal-assembly workflow, quick start, explicit limitations, and links to maintained detailed documentation.
- Reserved the top demo slot for a future verified SpeedTree-to-Unreal capture instead of using a synthetic visual.
- Refocused that README on the standalone artist workflow: removed developer setup and internal pipeline detail; added UE 5.8 validation, Dynamic Wind JSON, instanced parts, proxy, fracture, and part-export discovery paths.
- Added a compact README workflow composite from real application screenshots: main workspace above tightly packed Dynamic Wind, Proxy Mesh, and Fracture Preview viewports.
## 2026-07-19 - SpeedAssembly release identity and UE 5.8 baseline confirmation

- Renamed the distributed executable and release archive to `SpeedAssembly.exe` and `SpeedAssembly_release.zip`; aligned the Qt title, Windows application ID, runtime root, diagnostics archive, package help, release bundle, and packaged stability gate.
- Recorded manual baseline confirmation in UE 5.7 and UE 5.8.
- Clarified Proxy Mesh as the companion Static Mesh for collision, distance-field, and lower-cost shadow workflows; per-asset scene-lighting validation remains open.
## 2026-07-19 - Minimal first release bundle

- Reduced `SpeedAssembly_release.zip` to the executable and one `SimpleTree_01.xml` example. Build metadata and generated help remain local diagnostics/build artifacts and are not distributed.

## 2026-07-19 - In-shell tutorial callout

- Replaced the first-launch tutorial `Tool` window with a child callout under `How to use`, preventing it from escaping a restored non-maximized main window.
- Kept per-build first-launch behavior and persist dismissal immediately; added Qt regression coverage for containment and build-signature reset.

## 2026-07-19 - Modal viewport previews

- Restored shared window-modal behavior for operational viewport previews: they remain above the main shell and require closing before editing the main UI.

## 2026-07-19 - Cross-process crash context

- Recorded CR-011: current GUI requests ended without a worker result while
  historical WER also showed unrelated-process access violations. No
  application-local cause or code fix is claimed; next reproduction must retain
  the active executable path/build and matching worker/Windows evidence.

## 2026-07-21 - Fail-loud fallback cleanup

- Limited parallel FBX material partition fallback to process/OS infrastructure failures and made the sequential retry visible as a runtime warning; programming and payload errors now propagate.
- Rejected external USD skeletons with missing or unreadable joint transforms instead of fabricating identity or zero-position joints.
- Replaced the generic Wind JSON worker fallback message and updated two stale implementation comments.

## 2026-07-23 - Wiki maintenance

- Verified wiki navigation and current pytest collection; no broken local links found.
- Updated the test collection counts in `docs/wiki/testing.md` and linked the crash ledger and test policy from the project overview.
- Runtime duration remains unverified because this pass collected tests only.

## 2026-07-23 - Fracture Preview control hierarchy

- Reorganized Fracture Preview controls into collapsible task-oriented groups;
  no settings contract or tooltip text changed.
- Kept Preview Geometry and Automatic Cuts open by default; Cut Surface,
  Collision, and Manual Cuts can stay out of the active parameter list.

## 2026-07-23 - Shared automatic branch cut position

- Added persisted `Cut From Branch Start` (5–95%, default 30%) to Fracture Preview.
- The shared fracture plan now applies this physical-bone offset to flat and Detailed Cuts, so both paths split at the same automatic cut site; Detailed noise only changes the surface shape around that site.

## 2026-07-24 - Detailed fracture hot-path optimization

- Reused per-plan face centroids, O(1) skeleton ancestry, per-bone segment-cut
  filters, source seed bytes, and material lookup state; skipped unused
  result-face normal calculations.
- Local 11-cut Big Spruce preparation fell to a 1.49 s median and Detailed
  regeneration to 0.835 s while the geometry signature remained unchanged.
- Removed a measured Perlin-gradient cache because its small gain did not
  justify the extra dictionary work.
- Updated synthetic preview/export face placement to exercise the current
  physical-bone automatic cut contract.

## 2026-07-24 - Automatic branch ownership isolation

- Fixed automatic segment cuts claiming parent-owned collars from sibling
  branches when their centroids projected beyond the selected branch cut.
- Parent-dominated transition faces now cross an automatic cut only when their
  skin binding includes the selected child subtree; flat and Detailed paths use
  the same cached decision.
- Added a mixed-weight sibling-collar regression and audited 318 automatic cuts
  across 12 real-sample/settings runs with no cross-subtree assignments.
- The exact Big Spruce Detailed settings completed with 38 non-empty pieces,
  36 automatic cuts, and one stump cut.
- Recorded a standalone `python.exe` null-write dialog as unverified
  system-context evidence because no dump/WER/process boundary was available
  and the computer is independently unstable.

## 2026-07-24 - Flatter Fracture exploded view

- Scaled the Fracture Preview exploded-view vertical offset by the fixed
  multiplier `0.2`, keeping pieces visually separated mostly sideways without
  adding another UI setting.

## 2026-07-24 - Cutter-aware Repeated Part ownership

- Detailed Cuts now reassign an atomic Repeated Part to the parent piece when
  its pivot lies behind the already-built triangular Boolean cutter surface.
- Candidate work is isolated by skeleton child subtree and Fracture Piece
  ancestry; nested cuts resolve deepest-first and sibling bindings are never
  spatially tested.
- Reused the existing cutter mesh without rebuilding noise or Boolean state.
  Pivots outside that cutter's projection keep skeleton ownership.
- The exact 36-branch Big Spruce case moved 88 of 3,613 parts, preserved every
  instance exactly once, and retained 38 pieces / 37 cuts.

## 2026-07-24 - Flat-cut Repeated Part ownership

- Flat segment cuts now classify only skeleton-related Repeated Part pivots
  against the existing physical-bone `segment_t` plane.
- Nested ownership can climb through related parent cuts; unrelated sibling
  cuts are not evaluated.
- The 36-branch Big Spruce case moved 26 of 3,613 parts in flat mode, while
  Detailed mode retained its expected total of 88 cutter-supported moves.

## 2026-07-24 - Boolean outer-parallel prototype rejected

- Prototyped process execution only across independent connectivity components;
  nested cuts on one shell remained sequential and reused the production
  Boolean implementation.
- Verified exact parent/child/cutter meshes and diagnostics across sequential,
  1/2/4-process, batched-process, and 1/2/4/8-thread variants.
- On 37 independent Big Spruce cuts, sequential took 6.81-6.88 s; two
  processes took 6.99-7.34 s and four took 7.92-8.05 s while increasing
  child peak RSS. Twelve-cut and thread variants were also slower.
- Removed the prototype instead of adding a dormant runtime subsystem. The
  production Detailed Boolean path remains sequential.

## 2026-07-27 - WorldTree conversion preflight and FBX recovery

- Blocked USDA conversion before worker launch when discovered Base Mesh or
  inline Part material rows lack required Unreal paths; Unreal asset references
  and Proxy Mesh remain exempt.
- Confirmed `SM_BigBranch_02_HIGH.fbx` is readable sequentially at 16,813,048
  points / 21,029,320 triangles after the paired HIGH import produced
  `FbxVector2.__getitem__(): not enough arguments`.
- Added a narrow lower-concurrency retry for that transient Autodesk binding
  signature while preserving completed FBX payloads.
- Replaced per-control-point FBX `MultT` calls with equivalent matrix
  coefficient arithmetic after frozen Part Preview reproduced an invalid
  `FbxVector4` dispatch on the HIGH branch.
- Limited oversized Part Preview viewport payloads to 50,000 evenly sampled
  faces while retaining exact source/export counts and untouched export
  geometry.
- Removed the eager Autodesk FBX import from normal GUI bootstrap.
- Moved source-row discovery for XML files at or above 5 MiB into a
  file-backed crash-isolated worker; restored WorldTree startup now constructs
  the window before parsing and serializes Wind refresh behind discovery.
- Routed large-file Wind group inspection through the existing isolated Wind
  worker instead of a GUI-process Python thread.
- Added persistent bootstrap traceback logging and regression coverage for a
  restored large input.
- Verified the packaged shell with the real restored WorldTree: isolated source
  discovery and Wind inspection both returned, then the timed GUI exited
  normally.

## 2026-07-28 - Object-local Repeated Part transforms

- Corrected mesh-bearing Object `LeafReferences` to receive the same `Abs*`
  translation as their sibling mesh points in canonical and Proxy source paths.
- Kept zero-transform hosts unchanged and made the unresolved non-mesh,
  non-zero-transform shape fail loudly.
- Invalidated canonical source-model and Proxy Source Projection caches after
  the normalization semantic changed.
- Updated the branch-level fixture to use local source coordinates and retained
  its expected world positions through explicit assertions.
- Reproduced both Willow samples: canonical/proxy positions matched exactly;
  the original tree's false near-origin instances dropped from 7,894 to zero,
  while the shortened tree remained at zero.
- Full regression suite passed: 515 tests, 30 deselected.
- Clean package build passed 26 packaged contract tests and both bundled
  high-risk smoke checks.

## 2026-07-28 - Optional Proxy base-mesh vertex fusion

- Added a persisted `Fuse Base Mesh Vertices` control beside Base Mesh Priority;
  it is disabled by default and uses a fixed one-millimeter threshold.
- Kept existing small-component pruning ahead of the weld, then removed
  weld-degenerate faces before QEM.
- On the original Willow base path, the enabled option reduced post-QEM
  connected components from 1,914 to 1,533 and faces from 35,738 to 34,385 at
  the same 1,648-face requested base budget.
- Added intent-level service, settings round-trip, and worker breadcrumb
  coverage; visually checked the direct Qt dialog before packaging.
- Full regression suite passed: 516 tests, 30 deselected.
- Clean package build passed 26 packaged contract tests and both bundled
  high-risk smoke checks.

## 2026-08-02 - Unified main-shell program status

- Replaced the separate material/runtime cards and tab summary lines with one
  opaque, scrollable `Program Status` card.
- Routed conversion telemetry into five visible stages and routed Discovery,
  Wind, Proxy, Fracture, and Part Preview lifecycles through the same card.
- Kept the concise mode/material/XML counts in the card while moving full paths
  and runtime configuration into the conversion-start log.
- Retained `MainWindow.status_label` as a compatibility alias and added focused
  Qt coverage for progress, stage grouping, summaries, and terminal states.
- Full regression suite passed: 525 tests, 30 deselected.
- Package build passed 26 packaged contract tests, Detailed Cuts stability
  smoke, and Fracture worker recovery smoke.

## 2026-08-02 - Fast source-backed UI previews

- Added `build_qt_gui_exe.cmd -Quick`, which import-checks the current source
  and writes an isolated source-backed preview launcher without running
  PyInstaller, packaged contracts, release ZIP assembly, or smoke.
- Kept the full Package gate for frozen/native/importer/runtime risk and release
  validation, while low-risk UI iteration now uses relevant tests plus Quick.
- Measured Quick at 1.07 seconds versus 180.3 seconds for the full Package gate
  on the same workspace state.
- Verified 14 focused packaging-script contracts, 26 packaged contracts, the
  release EXE/ZIP, Detailed Cuts stability smoke, and worker recovery smoke.

## 2026-08-02 - Program Status readability polish

- Changed successful states and completed conversion stages to semantic green;
  errors now consistently use red state text.
- Replaced width-changing pulse markers with a rotating indicator in a fixed
  marker column, keeping operation and stage text stationary.
- Made Current Setup headings explicit, split dense source counts across lines,
  and compacted long result paths to filenames while preserving full tooltips.
- Restored the visual gap between the Wind/Geometry/Materials tabs and their
  content panels without reintroducing the removed summary text.

## 2026-08-07 - Production skeleton orientation and dual skinning

- Made +X-along-bone frames mandatory after UE 5.7 validation on fern and
  spruce assets fixed opposite wind bending across the trunk.
- Made linear parent/current Dual Skinning the default for the base mesh and
  repeated Parts while retaining an explicit Wind-panel opt-out.
- Removed skeleton-mode filename suffixes and renamed the implementation to
  `skeleton_processing.py` now that both behaviors are production contracts.
- Added concise On/Off guidance to the checkbox and exposed its current value
  in the left Program Status card.
- Passed 530 regression tests, 26 packaged contracts, the release EXE/ZIP
  build, Detailed Cuts stability smoke, and Fracture worker recovery smoke.
- Added mandatory hierarchy, +X/basis/rest-transform, chain-roll, and
  base/repeated influence validation to the existing source/authoring gates;
  no new reference assets were created.
- Passed 533 regression tests, 26 packaged contracts, a fresh release build,
  and both packaged stability smokes with the validator enabled.

## 2026-08-07 - Automatic external skeleton preview loading

- Removed the redundant External Skeleton `Load` button from Wind Preview.
- Selecting an FBX/USD file now starts loading immediately; multi-skeleton USD
  files load when the operator selects a Skeleton prim.

## 2026-08-08 - Automatic Proxy trunk collision

- Added enabled-by-default fitted Box/Capsule collision to Proxy Mesh using the
  shared Fracturing stem-axis selection contract.
- Added Height and Width multipliers, combined multi-stem fitting, and optional
  one-primitive-per-stem output.
- Extended Proxy Source Projection/cache with +X skeleton and base-mesh skin
  binding facts, and added translucent collision preview plus `UBX_`/`UCP_`
  guide siblings in the final proxy USDA.
- Fixed Proxy Preview remaining on `Generating...` after a successful collision
  job by converting exported collision `MeshData` to the viewport buffer contract.
- Fixed startup persistence so Output USDA is saved as an Input/Output pair;
  legacy unpaired output state is regenerated from the restored Input XML.
- Confirmed Box and Capsule Proxy collision import in UE 5.7.x.
- Split Proxy Preview collision fitting from render-mesh generation: On/Off is
  immediate and fit changes no longer rerun voxel extraction or QEM.
- Fixed the Proxy grid at the tree pivot and excluded guide collision from
  viewport framing bounds.
- Moved the shared oriented Box/Capsule builders out of Fracturing into the
  collision-primitives module used by both workflows.
- Polished the final change set: removed duplicate collision validation and an
  unused skeleton helper, narrowed domain error handling, and made collision
  ownership/imports explicit without changing the UE or UI contracts.

## 2026-08-08 - Faster canonical XML normalization

- Reused immutable source UV values across face corners, batch-remapped normal
  axes without temporary vectors, added direct scalar packed-value parsing,
  reused parsed object translations, and removed generator overhead from the
  hot 4x4 skeleton matrix multiply and mandatory skeleton validation.
- Reduced schema-inspection bookkeeping and suspended cyclic GC only across the
  acyclic cold-load phase, restoring the caller's prior state through `finally`.
- On the 9.7 MB Big Spruce sample with source cache disabled, an order-balanced
  one-core comparison reduced the complete `read + inspect + normalize +
  validate` phase from 1.689 s to 1.114 s wall median and from 1.648 s to
  1.078 s CPU median: 34.0% and 34.6% faster respectively.
- Passed 546 regression tests, 26 packaged contracts, a fresh release build,
  Detailed Cuts stability smoke, and Fracture worker recovery smoke.

## 2026-08-08 - Conversion result handoff race

- Fixed a packaged-only false failure where a Conversion worker published its
  final file result between the GUI's queue drain and process-liveness check.
- The GUI now performs one terminal drain before classifying a stopped worker
  as crashed; the regression test preserves the observed exit-code-zero order.
- Passed 547 regression tests, 26 packaged contracts, the release build and
  stability smokes, plus 10/10 clean packaged Big-low Conversion worker runs.

## 2026-08-09 - UE imported-skeleton orientation experiment

- Added a duplicate-first UE 5.8 Python experiment that reorients the selected
  Skeletal Mesh to primary +X with the native `SkeletonModifier` API.
- Documented that animation tracks, sockets, and Physics Asset frames are not
  automatically compensated and require manual validation.

## 2026-08-10 - Dynamic Wind Skeleton reference-pose experiment

- Changed the orientation experiment to create its Skeletal Mesh beside the
  source and generate a dedicated sibling Skeleton from the modified mesh.
- Recorded the UE 5.8 Dynamic Wind runtime contract: bind transforms come from
  the assigned Skeleton asset, so editing only the mesh reference pose cannot
  change wind behavior.
- Corrected the experiment after runtime evidence showed that UE Python blocks
  the protected `SkeletonFactory.TargetSkeletalMesh` property. The script now
  selects its output for the native `Create Skeleton` content-browser action.
- Added a self-contained one-line Output Log variant suitable for attaching to
  an Epic bug report; it has no dependency on the repository path.

## 2026-08-10 - Static Assembly Parts export

- Enabled the existing Static Assembly Parts UI action and connected it to the
  shared parts-library bundle path.
- Each unique resolved Repeated Part prototype now writes as a standalone
  static USDA without assembly, instancer, skeleton, or skinning fields.
- Added an intent-level batch/USDA contract regression.

## 2026-08-11 - Static Assembly Parts validation and polish

- Operator validation confirmed standalone part import and successful reuse by
  a full Static Assembly through Unreal Reference.
- Removed an unreachable multi-prototype naming branch from the shared parts
  authoring path; output structure remains unchanged.

## 2026-08-11 - Parts output folder choice

- Added a parts-only `Create Parts Folder` checkbox beside Output USDA.
- Checked output uses `<OutputStem>_SkeletalParts` or
  `<OutputStem>_StaticParts`; unchecked output writes directly beside the
  selected USDA path.
- Kept the choice in the UI path-routing layer; USDA authoring remains
  unchanged.
- Parts conversion now stays idle and reports `Nothing to export` in the
  status card when every prototype uses Unreal Reference.
