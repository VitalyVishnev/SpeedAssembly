# Project Roadmap

## Phase 1 - Golden sample pipeline

Goal: prove one controlled SpeedTree 10 tree imports into UE 5.7.x through the current self-contained USDA path.

Current status:

- import now succeeds for the baseline sample
- remaining work for this phase is visual correctness of transforms / rig fidelity, not basic importer acceptance

Deliverables:
- one simple SpeedTree tree with multiple XML export variants
- inspect reports for every export variant
- chosen baseline export profile
- expected USDA and observed notes
- importer validation notes in `docs/import_validation.md`

## Phase 2 - Desktop GUI and exe packaging

Goal: provide a simple Windows-first interface that wraps the existing CLI pipeline.

Deliverables:
- single-window GUI built on `tkinter`
- single-file conversion workflow
- diagnostics/log area
- later packaging pass to Windows one-folder executable

## Phase 3 - External branch reuse

Goal: author USDA that can reference already imported Unreal Engine branch/prototype assets instead of regenerating equivalent geometry repeatedly.

Deliverables:
- `external_refs` writer mode
- stable prototype identities suitable for matching UE-side assets
- validation docs for expected project-side asset layout

## Phase 4 - Dynamic Wind JSON

Goal: generate a separate JSON artifact derived from tree structure once the core import path is stable.

Deliverables:
- vault-backed reference notes from Dynamic Wind plugin materials
- documented JSON contract and mapping rules
- separate generator command/module
