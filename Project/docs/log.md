# Project log

## 2026-10-06 - Remove heading permalink symbols

- Disabled MkDocs heading permalink symbols globally. Heading IDs and
  table-of-contents navigation remain available.
- Validation: strict MkDocs build passed; all 15 generated HTML pages contain
  no heading permalink links. Geometry heading ID and its TOC link are retained.

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

## 2026-10-03 - Main-window chrome and Wind count layout

- Stacked Total bones, Refresh, and Advanced Wind Settings across the action
  column; kept Total bones at Refresh height and verified counts through 262,144.
- Enlarged caption glyphs, preset dots, and the top settings gear. Preserved
  the Convert gear size and bounded icon targets by readable runtime font size.
- Updated corners on every Qt window-state transition. Maximized/FullScreen
  windows are square; normal windows retain rounded corners. Replaced the
  read-only QWidget `maximized` styling property with `windowExpanded`.
- Validation: 29 focused Qt tests; direct screenshots and width checks at
  runtime scales 0.90, 1.00, 1.25, and 1.75; Quick; Package with 26 packaged
  contract tests, repeated Detailed Cuts stability smoke, and worker recovery
  smoke. No smoke bypass. Temporary visual-check files removed.

## 2026-10-03 - Intermediate caption size and shared button outlines

- Reduced caption targets from 48 to 38 px and reduced top gear/preset dots.
  Caption marks now use geometric drawing: square/cross contours are centered,
  and the minimize bar matches the square's bottom edge.
- Added one shared subtle dark 1 px button outline to main/preview actions,
  tabs, section toggles, and compound presets. Caption controls and the top
  settings gear remain explicit exceptions. Recorded the rule in AGENTS.md
  and maintained decisions.
- Kept left title pills rounded at high runtime scale and made the bundled
  preset width scale explicitly so Factory Defaults remains readable.
- Validation: 36 focused Qt checks, including rendered caption alignment and
  window-state corners; direct normal/hover-fill screenshots and preset text
  bounds at scales 0.90, 1.00, and 1.75; Quick; full Package with 26 packaged
  contracts, Detailed Cuts stability and worker recovery smoke. No smoke bypass.
  Temporary visual-check files removed.

## 2026-10-03 - Half-size caption controls and UI preview cadence

- Halved the three right caption targets and marks, retaining geometric
  alignment and circular hover fills. Default targets are now 19 px; left
  controls and both settings gears retain their prior sizes.
- Recorded the operator's build preference: ordinary UI polish uses tests
  plus Quick until final visual approval, then one full Package build.
- Validation: 8 focused Qt checks, direct hover-fill rendering at scales
  1.00 and 1.75, and Quick. Temporary visual-check files removed.

## 2026-10-03 - Typography audit and review proposal

- Audited inherited Segoe UI, inverted title/body theme sizes, scattered local
  font rules and text-driven caption geometry. Verified local family/600 weight
  resolution through QFontInfo.
- Added typography.md with proposed roles, family rationale, migration bounds
  and references to Taste, Fluent and Qt. Proposal remains unapproved; runtime
  styles and builds are unchanged. Rendered a comparison specimen using Qt.

## 2026-10-03 - Keep the main window visible when opening viewport previews

- Reproduced Hide/Show, native surface destruction and HWND replacement when
  reparenting a populated OpenGL dialog to the visible raster shell in Qt 6.11.
  This was window recreation, not a process crash.
- Replaced QWidget parenting with native QWindow transient ownership in the
  shared preview shell. WindowModal blocking, close/reopen and owner cleanup
  remain explicit; main-window exit now also closes Fracture Preview.
- Extended the existing ownership regression with native handle, surface,
  Hide-event, normal/maximized, modal-scope and reopen checks. Packaged
  interactive smoke now checks stable main HWND/surface and native ownership.
- Validation: 19 focused Qt checks; all four real preview dialog classes in
  normal/maximized main windows; full Package, 26 packaged contracts, repeated
  Detailed Cuts stability smoke and worker recovery smoke. No smoke bypass.
  Temporary diagnostic scripts removed.

## 2026-10-03 - Version and release draft policy

- Recorded in AGENTS.md: explicit version changes only, full builds without
  automatic bumps, one version source, embedded build identity, and verified
  GitHub drafts with concise bullet-only notes. The operator publishes manually.
- Preserved the policy in maintained decisions and recorded the existing
  package/runtime version gap. Version implementation remains deferred.
- Validation: documentation diff and whitespace checks; no code or build changes.

## 2026-10-03 - Prepare SpeedAssembly v0.5.0-beta

- Added one release version source shared by Python metadata, Qt titles/About,
  and Windows EXE version strings. Package embeds portable commit/time/dirty
  identity; diagnostics and `--build-info PATH` expose it without local sidecars.
- Source previews add DEV. The title bar reserves readable version width and
  derives the minimum window width from its controls, including at scale 1.75.
- Isolated the existing inline Part Skeleton test output in its temporary
  directory after a permission failure writing alongside the sample XML.
  Converter/importer behavior is unchanged.
- Validation: 619 Core/Integration checks; source rendering at scales 0.90,
  1.00, and 1.75; editable metadata resolves to Python-normalized `0.5.0b0`.
  Full Package and frozen-runtime evidence will be recorded after the build.

- The first Package passed 27 packaged contracts, repeated Detailed Cuts, and
  worker recovery. Additional high-risk smoke on the extracted ZIP found stale
  scenarios: automatic Wind groups were counted through manual-layer buttons,
  and conversion omitted required Base Mesh material assignments. Updated only
  smoke setup/assertions to the existing contracts; the release needs rebuilding.

## 2026-10-03 - SpeedAssembly v0.5.0-beta draft verified

- Built the final Package from clean source commit
  `c10131f0fce0862cb0cf725bc28a7e4f55158b03`, tagged `v0.5.0-beta`.
  Windows FileVersion/ProductVersion are `0.5.0-beta`; the prerelease flag is set.
- Validation: 619 Core/Integration checks, 27 packaged contracts, repeated
  Detailed Cuts stability, and injected worker recovery. The extracted public
  ZIP passed all eight high-risk scenarios with fail-on-retry, including
  version/About and embedded diagnostics, without a local build_info sidecar.
  No smoke bypass. Evidence: `dist-next/smoke/` and
  `tmp/release-0.5.0-beta-c10131f/high_risk_report.json`.
- Created an unpublished GitHub Pre-release draft with four bullet-only notes:
  https://github.com/VitalyVishnev/SpeedAssembly/releases/tag/untagged-b27b23b4772796cf342c
  Downloaded its ZIP and verified SHA-256 matches the validated local artifact:
  `cfe1a5d809bc6c2d4aa22f8db7abd98ac503f28f5484e85b9b679f9772747c26`.
  The operator reviews and publishes manually. This later evidence entry does
  not change the tagged build's source commit or its artifacts.

## 2026-10-05 - Hide Adjust UI in the main title bar

- Hid the development-only title-bar button with Qt visibility; retained the
  existing dialog and theme tooling.
- Validation: 12 existing Adjust UI/theme tests passed; `-Quick` completed and
  produced `dist-preview/SpeedAssembly_preview.cmd`. No Package build.

## 2026-10-05 - Basic conversion documentation draft

- Added Convert in SpeedAssembly as Basic workflow step three and linked from
  Prepare SpeedTree. Included eight supplied screenshots and a side-by-side
  one-/two-weight fern comparison.
- Separated JSON wind settings from USDA skin weights; described required
  material assignments, geometry replacement, Scattered Rig controls, optional
  Proxy/Fracturing, and all four export modes with current UI names.
- Used corrected Copy Object Path and `/Game/` material screenshots. Kept
  future guide links as editorial comments rather than broken public links.

## 2026-10-05 - File format primer for artists

- Added a short public Wiki article explaining XML, USD, USDA, and JSON,
  their common uses, and their roles in the SpeedAssembly workflow.
- Registered it in MkDocs navigation and linked the conversion and wind guides.
- Validation: `mkdocs build --strict -f Project/mkdocs.yml` passed.

## 2026-10-05 - Generate Wind JSON tooltip

- Replaced unrelated lower/higher wind advice with the button's action: create
  bone group assignments and per-group wind settings for Unreal Dynamic Wind,
  saved beside Output USDA.
- Clarified the existing tooltip decision and root agent rules: describe the
  owning control; lower/higher guidance belongs only to suitable numeric inputs,
  unless the operator explicitly requests different text.
- Validation: 16 existing wind-service and Qt theme checks passed; `-Quick`
  completed. Source-backed preview only; no Package build.

## 2026-10-05 - UI tooltip audit corrections

- Removed unrelated parameter advice from Proxy/Fracturing/Prototype preview
  and Reset Cuts buttons. Display and UDIM now explain their named choices;
  material panels reuse the shared UDIM tooltip.
- Removed false empty-path fallback promises. Base Mesh, Single Material,
  Black/White, and FBX slot help now reflects conversion validation; shared
  material rows keep neutral text where the caller owns the policy.
- Proxy collision help now covers shared and per-stem primitives. Updated the
  maintained tooltip decision with material/collision constraints.
- Validation: 42 existing Qt and conversion-service checks passed; `-Quick`
  completed. Source-backed preview only; no Package build.

## 2026-10-06 - Unreal import workflow draft

- Added Basic workflow step four with the agreed grouped Interchange settings,
  expected assets, 5.7 fallback workaround, Wind JSON verification, and seven
  screenshots. Linked from conversion and registered navigation immediately.
- Added required Wind_TransformProvider setup for Blueprint/PCG and the sample
  Global Foliage Actor, with a World Partition spatial-loading tip.
- Recorded operator-reported engine crashes as CR-016/CR-017 with unverified
  causes. Source inspection does not support saying provider-less components
  disable geometric instancing entirely.
- Validation: strict MkDocs build passed; generated page contains all seven
  image references. No new Unreal runtime validation performed.

## 2026-10-06 - UE 5.7 skinning assertion evidence and documentation voice

- Removed third-person maintainer attribution from the import guide and recorded
  neutral/first-person voice as the public authoring rule.
- Updated CR-016 with the supplied 22-bit offset assertion, confirmed UE 5.7
  diagnosis/workaround, and matching batching/allocation source paths. Preserved
  the earlier analysis screenshot and distinguished its x16 wind estimate from
  the null-provider branch's one animation variant and separate object-space data.
- Public warning now explains the 5.7 overflow risk; 5.8 reproduction is unknown.
  Global controller advice uses impersonal wording without dismissing prior tests.

## 2026-10-06 - UE 5.8 skinning overflow risk comparison

- Confirmed in source that provider-less components still disable skeleton
  batching and allocate per-component buffers checked against 22-bit offsets.
- Updated the import warning to distinguish a confirmed UE 5.7 crash from
  source-confirmed UE 5.8 risk without claiming a 5.8 runtime reproduction.

## 2026-10-06 - Public documentation navigation cleanup

- Reordered navigation to Overview, Basic workflow, Workflows, Wiki, Parameter
  reference, and FAQ. Moved Pipeline overview under Overview without changing
  its file address; removed Getting Started and Concepts groups.
- Deleted the Quick Start article on request and replaced its incoming links
  with Basic workflow. Updated existing overview links to the completed guides.
- Kept Parameter reference provisionally and FAQ last; aligned the editorial
  plan and maintained navigation decision with the current structure.

## 2026-10-06 - UDIM workflow draft

- Added UDIM workflow under Workflows and linked from the conversion guide.
  Included the supplied Unreal graph and concise converter/material formulas.
- Verified tileOffset, UV1 center encoding, and UV1 overwrite behavior against
  udim_resolver.py and existing tests. Preview/Edit uses the same material state.
- Separated Shift UV/direct UV0 from Write UV1 Offset/Frac+Floor and avoided
  unsupported one-fetch or guaranteed Nanite performance claims.
- Validation: strict MkDocs build and diff whitespace check passed; all five
  existing UDIM resolver tests passed. No new Unreal material runtime test.

## 2026-10-06 - Shared viewport navigation hints

- All shared viewports show Orbit, Pan, Zoom, point focus, and `F` frame-all
  in the top-right corner as gray translucent text. Wind picking/history hints
  append to the same list; Boolean viewers reuse the shared camera hints.
- Replaced the direct-painted hint text, absent in source screenshots, with
  one mouse-transparent Qt label. It stays visible in Proxy Shaded and
  Silhouette Diff; the exact direct-paint failure mechanism is Unverified.
- Validation: 28 existing viewport/dialog/theme checks passed; source images
  checked shared navigation, editing hints, and both Proxy modes. `-Quick`
  completed. Source-backed preview only; no Package build.

## 2026-10-06 - Proxy workflow and inline parameter tables

- Rewrote Proxy Mesh with the supplied screenshots, concise distance-field,
  collision, and distant-shadow uses, generation steps, and silhouette comparison.
- Corrected separate base/foliage simplification, base budget allocation, and
  disconnected-component pruning descriptions against current code.
- Moved all Proxy parameter details into a collapsible workflow table, preserved
  anchor IDs at the new path, updated FAQ links, and deleted the old reference
  article. Removed its now-empty navigation group and recorded the inline-table
  convention for other preview guides.

## 2026-10-06 - Layout-independent viewport frame-all

- Windows frame-all follows physical F through its native scan code regardless
  of the translated character. Events without native data retain logical F;
  auto-repeat is still ignored.
- Added the keyboard-layout UX rule to agent instructions and maintained
  decisions. Extended the existing camera regression with native English,
  Cyrillic, unknown-letter, wrong-physical-key, and auto-repeat events.
- Validation: 17 existing viewport/dialog checks passed; `-Quick` completed.
  Source-backed preview only; no Package build or hardware-layout matrix run.

## 2026-10-06 - Contextual documentation buttons

- Added shared circular 24 px question buttons with hover/focus highlighting
  beside Proxy launch, in Proxy Preview, and across UDIM material controls.
- Documentation in the title bar opens the public site through Qt desktop
  services. Shared destinations and browser-opening errors live in
  `qt_ui/documentation.py`.
- Validation: 20 relevant Qt checks passed, including destination/navigation
  coverage and fixed square button geometry. Source screenshots checked UDIM
  rows and Proxy placement; `-Quick` completed. Source-backed preview only.
- Live home and Proxy URLs returned 200; the locally authored UDIM guide still
  returned 404. Recorded its pending publication in Known Bugs.

## 2026-10-06 - Documentation publication preparation

- Temporarily removed FAQ from navigation and excluded it from site/search
  output without deleting its source.
- Confirmed all other public articles are registered in navigation and that
  the Pages workflow builds Project/docs/user after documentation pushes to
  master. Prepared public documentation and screenshots for the next commit;
  no commit, push, or deployment performed in this task.

## 2026-10-07 - English originals and Russian documentation preview

- Established English-first public authoring; Russian sibling `.ru.md` files
  are translations only. Recorded the rule in developer setup, decisions,
  and local agent guidance.
- Added pinned MkDocs static i18n builds, visible ENG/RU header links, Russian
  navigation, and a notice on untranslated articles. English URLs remain the
  default; RU uses `/ru/`. Translated only the home page for operator review.
- Added a generated-site contract check to Pages CI and watched isolated theme
  overrides in local preview. The preview helper detects the new dependency.
- Validation: strict build and all 24 generated-page checks passed. Browser
  review confirmed same-article switching, fallback notices, responsive header,
  and Russian search for `коллизий`. Public deployment remains pending.

## 2026-10-07 - Complete Russian user documentation

- Translated all 12 registered public pages and the still-hidden FAQ after
  operator approval of the switcher. Reworked home-page descriptions: simpler
  Proxy Mesh wording and Fracturing as creating static pieces for destruction.
- Kept familiar 3D terms and UI labels in English; adapted overview prose
  naturally while preserving technical instructions, settings, and caveats.
  Recorded this style in developer setup, decisions, and local agent guidance.
- Preserved all section anchors, link/image targets, inline identifiers, and
  executable code. Extended the existing site check to protect translation
  anchors. Kept both FAQ sources excluded from publication and search.
- Validation: strict build and 24-page bilingual check passed; all 12 Russian
  articles are indexed and none use the untranslated-page fallback. Browser
  review checked home copy and the translated Proxy parameter table. English
  article sources are unchanged; public publication remains pending.

## 2026-10-07 - Measure and optimize documentation navigation

- Enabled Material instant navigation and added 100 ms cancellable hover/focus
  preloading using the browser HTTP cache. The last hovered link wins; touch
  and Save-Data skip speculative work. No new runtime dependencies.
- Kept contextual ENG/RU links current after navigation; locale transitions
  reload translated controls, including transitions from bilingual search.
- Added an optional browser contract/benchmark and extended static locale checks.
  Strict build and 24-page checks passed. Browser checks passed at 240 ms server
  latency, including cancellation, in-flight click reuse and failed prefetch.
- Seven-run medians with 120 ms server latency: baseline 200.7 ms, instant
  navigation 153.1 ms, hover-preloaded 29.5 ms to article paint. Recorded limits
  and upstream alternate-sitemap probes. Public deployment remains pending.
