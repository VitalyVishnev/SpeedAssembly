# Project log

Short history only. Current contracts, open risks, crash evidence, and rejected
routes belong in [wiki/decisions.md](wiki/decisions.md),
[wiki/known-bugs.md](wiki/known-bugs.md),
[wiki/encountered-crashes.md](wiki/encountered-crashes.md), and
[wiki/experiments.md](wiki/experiments.md). Original documentation is retained
under `docs/raw/`; Git retains per-change detail.

## 2026-10-02 - Compact repository root

- Moved application files, packaging metadata, tests, samples, and documentation
  into `Project/`; updated README assets, Pages workflow, and build/test helpers.
- Kept the existing Python environment at the repository root and excluded
  local development state and runtime logs from version control.
- Replaced obsolete contributor-instruction references with project documentation;
  technical source material and architecture history remain available.
- Validation: 611 source tests and 26 packaged contracts passed; full Package
  completed repeated Detailed Cuts and worker-recovery smoke without bypasses.
  Quick preview generation, strict MkDocs build, and release archive contents
  also passed.

## 2026-09-07 - External RefSkeleton parity

- Reworked external FBX/USD preview around the UE 5.8 default RefSkeleton
  contract: imported names, hierarchy, bind pose, and FBX cm/Z-up conversion
  are now established before grouping and JSON authoring.
- Replaced the JSON-only period rewrite with the predicted UE name set shared by
  preview, persistence, and export; reject incomplete/unknown assignments and
  same-group forks before JSON is written.
- Bound vertical-bone diagnostics to Dynamic Wind shader bind-pose +X, not
  Pivot Painter or parent-child geometry. Old Wind Preview sessions reset their
  display transform to the canonical FBX loaded space.

## 2026-07-01 - 2026-07-05: memory split, preview foundations

- Migrated active memory to `docs/wiki/`; preserved old docs in `docs/raw/`.
- Established practical test density, cache maintenance, narrow Proxy source
  loading, and low-latency preview paths.
- Built Fracture V1 natural-detach planning and isolated preview workers.
- Built Wind Preview V1: read-only XML inspection, bottom-up groups, Auto
  Hierarchy, shared viewport path, and worker isolation.

## 2026-07-09 - 2026-07-17: Wind V2 and Detailed Cuts

- Added Wind V2 group stack, manual overrides, undo/redo, autosave, external
  FBX/USD skeleton loading, explicit USD Skeleton selection, and frozen-worker
  fixes.
- Standardized compact viewport panels, screenshot preflight, and shared
  rendering/focus behavior.
- Replaced approximate fracture slicing with deterministic Boolean Detailed
  Cuts: physical-bone positions, provenance, caps, noise limits, prepared
  sessions, same-shell sequencing, and cutter-aware part ownership.
- Added the crash ledger, cold-cache/native mitigations, worker coalescing, and
  contract-layered tests. Exact implementation history is in the wiki.

## 2026-07-19 - 2026-07-28: release, failure boundaries, source semantics

- Established public SpeedAssembly identity, minimal release bundle, tutorial,
  modal previews, and cross-process crash context.
- Tightened fail-loud behavior for FBX/material preflight and worker recovery.
- Applied Object-local `LeafReferences` transforms for mesh-bearing hosts;
  non-mesh hosts remain fail-loud when transformed.
- Added optional post-prune Proxy base-mesh vertex fusion and began unified
  main-shell status work.

## 2026-08-02 - 2026-08-12: skeleton, static parts, Proxy Mesh

- Completed telemetry-backed status card and source-backed Quick build loop.
- Made local +X and Skinning Quality the production skeleton contract; added
  UE foliage-orientation repair and external-skeleton loading diagnostics.
- Added `static_parts`, output-folder routing, faster deterministic authoring,
  packed ufbx migration, and license notices.
- Added stem-aware Proxy collision, high-resolution density acceleration,
  collision UI, Proxy export from preview, user-docs foundation, and generator
  group-gap warning.

## 2026-08-13 - 2026-08-20: Scattered Parts and external-rig audit

- Normalized root-fixed SpeedTree attachments, prototype display modes, and
  vertical-skeleton protection.
- Added Scattered Parts assembly resolution and synthetic Dynamic Wind rigs;
  grass imports and animates normally in Unreal.
- Audited known bugs, docs navigation, external FBX diagnostics, and
  `TungTungTung.fbx`; PCG-specific cause remains Unverified.

## 2026-08-21 - Documentation compaction

- Compressed decision prose, experiment history, and this log; removed duplicated
  chronology while preserving contracts, risks, evidence, outcomes, and next tests.
- Retained detailed active contracts and crash records. No raw sources changed.

## 2026-08-29 - Viewport bone clipping

- Kept bone overlays visible and pickable when one endpoint leaves the camera
  frustum by clipping complete segments before screen projection.

## 2026-08-30 - Qt package dependency isolation

- Added the first host-`PATH` filter for an unrelated Poppler `icuuc.dll`.
  PyInstaller 6.19 later proved that this filter alone was insufficient.
- Made windowed Qt import failures report the original error without assuming
  that `sys.stderr` exists.

## 2026-08-30 - Unreal Dynamic Wind lookup diagnostic

- Added a read-only UE 5.7 Python diagnostic for the selected Skeletal Mesh. It
  exposes silent Dynamic Wind joint-name mismatches and root-only mappings.
- Confirmed that the tested FBX names `Bone.001` through `Bone.007` imported as
  `Bone_001` through `Bone_007`; only `Root` matched the generated JSON and
  caused the observed rigid wind rotation.
- Reimporting a JSON with the seven actual underscore names restored correct
  Dynamic Wind deformation, validating the mismatch as the sole cause.

## 2026-08-30 - External FBX JSON joint-name adaptation

- Mapped the UE 5.7-verified FBX period rewrite only at Dynamic Wind JSON
  export, while preserving exact Source Names in the loaded rig and viewport.
- Added a fail-loud collision gate and regression coverage for source
  preservation, `Bone.001` to `Bone_001`, and ambiguous mapped names.
- Reopened the package ICU issue after PyInstaller 6.19 still collected the build host's
  Poppler's incompatible DLL and failed the mandatory Qt smoke; no
  `-SkipSmoke` release was accepted.

## 2026-08-30 - Deterministic packaged ICU policy

- Replaced the environment-only workaround with a generated PyInstaller spec
  that removes collected `icu*.dll` binaries after Analysis and rejects ICU in
  the final package TOC.
- The normal build environment now passes 26 packaged contracts, repeated
  Detailed Cuts smoke, and Fracture worker recovery without `-SkipSmoke`.

## 2026-10-01 - What is SpeedAssembly overview draft

- Added the artist-facing introduction and Supported Workflows table in
  `docs/user/overview/what-is-speedassembly.md`.
- Consolidated the supported-workflows page into that article in the editorial
  plan and recorded the audience and writing conventions.
- Added the article to Overview navigation and made immediate navigation
  registration the authoring rule for new drafts in the local preview.

## 2026-10-01 - Simplified documentation plan

- Replaced the extensive page inventory with Overview, four Basic workflow
  stages, three tab guides, and three Advanced workflow articles.
- Removed Quick Start and Getting Started from the planned structure and
  retained the authoring rules and existing article addresses.

## 2026-10-02 - Unreal preparation guide

- Added `workflows/prepare-unreal.md` with four author-provided screenshots
  and immediate Basic workflow navigation registration.
- Checked plugin names and the Nanite Foliage setting/restart metadata in local
  UE 5.7 and 5.8 sources. Kept import options for the separate import article.

## 2026-10-02 - SpeedTree preparation guide and wind budget research

- Added Prepare SpeedTree with seven supplied screenshots, recommended bone
  budgets, group naming, and exact export settings; registered Basic workflow
  navigation and linked from Unreal preparation.
- Recorded the separate 22-bit transform offset budget and eight-direction,
  current/previous allocation formula in experiments. The roughly 262k estimate
  is not a tested scene-wide hard limit and stays out of the public guide.
- Included the author's verified Leaf Flip limitation alongside per-leaf
  deformations that the repeated-part workflow does not preserve.

## 2026-10-02 - Public Wiki and Assembly part sizing

- Added Choosing what to instance, adapted from the author's HTML guide, to a
  new public Wiki navigation section and linked it from Prepare SpeedTree.
- Verified asset/runtime transform limits, active-skinning record costs, and
  NaniteStats counter semantics in UE 5.7/5.8. Kept profiling advice distinct
  from engine limits and recorded source navigation in experiments.
- Capped the CD PROJEKT RED skeleton screenshot at 500 px display height
  without resampling or modifying its source image.

## 2026-10-02 - Assembly sizing editorial revision

- Rechecked the English guide against the author's Russian original, merged
  repeated explanations, and made budget warnings name the actual console
  setting and intended plant density.
- Reframed the branch example as two construction choices for the same visible
  geometry, explicitly keeping twigs in the main mesh in the leaf-only option.
- Preserved verified limits, counter semantics, motion constraints, and reserve
  recommendations. The strict documentation build passed.

## 2026-10-02 - Documentation theme geometry and controls

- Shared Light Mode article geometry with Dark Mode at desktop and mobile
  breakpoints; switching themes changes colors without changing text wrapping.
- Applied the Qt theme's 18 px control radius to desktop search and its results
  panel. Preserved Material's mobile full-screen search layout.
- Replaced Back to Top transform positioning/animation with auto-margin
  centering and an opacity transition; checked unhovered text after deep scroll.
- Validation: strict MkDocs build, browser geometry comparisons at 1440 px and
  390 px, and a search returning eight matching documents for `wind`.

## 2026-10-02 - Assembly sizing symptoms and practical guidelines

- Clarified that transform-budget overflow omits parts from the affected pass
  and can appear as missing foliage or grass in the camera view.
- Noted the main-camera scope of bare NaniteStats without expanding the guide
  into shadow-stat filtering instructions.
- Added the author's polygon/reuse planning guidelines, explicitly separate
  from engine thresholds and benchmark evidence.

## 2026-10-02 - Dynamic Wind user overview

- Added How Dynamic Wind works beside Choosing what to instance in public Wiki
  navigation, based on local UE 5.8 source with Build.version 5.8.2.
- Covered reference-pose ownership, group chains, response controls, GPU motion,
  eight shared yaw variants, setup requirements, limitations, console variables,
  and ordered diagnostics. Included a collapsed engine source map and Epic API
  links; kept source evidence distinct from runtime confirmation.
- Recorded source findings and the shared-Skeleton metadata limitation in
  maintained memory. Validation: strict MkDocs build and live preview page;
  light/dark browser checks.

## 2026-10-02 - Dynamic Wind overview tone

- Replaced reader commands with descriptions of asset flow, runtime dependencies,
  settings, and failure boundaries in How Dynamic Wind works.
- Converted the diagnostic checklist to a cause-and-effect table; retained
  technical facts, console references, and stable section anchors.
- Validation: strict MkDocs build and updated live preview with all ten stable
  section anchors preserved.
