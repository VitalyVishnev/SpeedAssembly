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
