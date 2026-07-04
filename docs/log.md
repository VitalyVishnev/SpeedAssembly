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
