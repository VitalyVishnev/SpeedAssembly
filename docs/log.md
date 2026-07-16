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
