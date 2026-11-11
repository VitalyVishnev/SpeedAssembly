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

## 2026-10-11 - Investigate Black Alder Proxy scale

- Reproduced oversized Proxy generation from the external Black Alder XML;
  isolated it to Mesh_2 OriginalScale and recorded FBX node/unit evidence in
  Known Bugs. In-memory /100 comparison restores tree-sized bounds; intended
  source size and export cause remain unverified. Source assets and converter
  code are unchanged.

## 2026-10-11 - Keep Proxy silhouette and geometry on the same XML revision

- Confirmed the operator's corrected Black Alder XML restores Mesh_2 size.
  Fixed path-only in-memory Proxy/source-scene reuse after overwriting XML.
- Added file revision checks to cache reuse, export, dialog callbacks, and
  worker completion; extended the existing Qt lifecycle regression.
- Validation: Core checks passed in the combined run; all 131 Integration
  checks passed separately after one intermittent typography assertion,
  recorded in Known Bugs. All 27 packaged contracts and both Package smoke
  scenarios passed. Black Alder source/Proxy payloads now have tree-sized
  bounds; release ZIP EXE hash matches the built EXE. Version unchanged.

## 2026-10-11 - Diagnose Black Alder Dynamic Wind Trunk mismatch

- Verified supplied JSON has Ground Cover enabled and every Trunk flag false.
  Traced the converter's Ground Cover override and persisted checkbox display;
  UE 5.7 imports the JSON groups unchanged. Recorded the unresolved UI/policy
  mismatch and workaround; no runtime or source-asset changes.

## 2026-10-11 - Part library illustration

- Added the supplied CD PROJEKT RED branch-library screenshot to Choosing what
  to instance, under Building a part library, with the presentation source link.
- Updated the English original and Russian translation together; shared one
  unchanged image asset between both language versions.

## 2026-10-12 - Trace UE 5.8 PVE mesh extraction and wind groups

- Recorded the local UE 5.8.2 mesh-to-branch pipeline, continuation score,
  hierarchy-depth contract, radius-based wind grouping, and export call sites.
- Compared UE 5.7 grouping and current SpeedAssembly Auto Hierarchy; retained
  source-order contracts and marked comparative asset quality Unverified.
- Documentation only; engine and application code unchanged.

## 2026-10-12 - Add PVE-style Auto Hierarchy comparison and Package build

- Added `Auto Hierarchy (PVE)` beside the original mode in Advanced Wind
  Settings. Direction and descendant length select continuation; side branches
  increase hierarchy level. Reused Groups 1-10, manual layers, scene recoloring,
  session persistence, and Dynamic Wind JSON. Source skeletons remain unchanged.
- Recorded the physical-segment adaptation and provisional quality limits;
  retained the source-order mode and its Continue line settings.
- Validation: 41 focused grouping/stack/Qt/wind checks, source Wind smoke,
  27 packaged contracts, Package stability/recovery smoke, and frozen Wind
  smoke passed. Frozen PVE JSON covers all 105 SimpleTree joints; ZIP contains
  the exact built EXE. No required smoke skipped; unrelated source suites not
  rerun. Version remains 0.5.0-beta. Operator/UE quality comparison is pending.

## 2026-10-12 - Diagnose Norway Spruce external USD grouping and bone overlay

- Compared the supplied USDA and sibling XML: matching 249-joint hierarchy and
  bind poses, but the USD load loses all physical endpoints. Reproduced the
  PVE branch/stem continuation difference and verified 103 attachment links
  overlap the physical trunk axis.
- Recorded the source-XML workaround and the unresolved USD round-trip segment
  contract. Existing EXE and source assets unchanged; no endpoint heuristic or
  implicit sidecar loading introduced.

## 2026-10-12 - Calibrate bare-rig Tree hierarchy and build the comparison EXE

- Added `Auto Hierarchy (Tree)` alongside Order/PVE, using only bind poses and
  parent links. Reference data is confined to the benchmark/regression corpus;
  runtime has no source-file, name, ordinal, generator or endpoint lookup.
- Added reproducible XML/USDA-JSON comparison and ten independent anonymous
  skeleton fixtures. With matched group caps, 3336 labelled joints give Tree
  133 mismatches versus Order 485 and PVE 808. Recorded per-tree counterexamples,
  including the 03_28mil regression; 96% calibration is not generalization.
- Cached one preview analysis, displayed own-pivot bone guides/terminal markers,
  and retained source rigs/manual layers/settings. Geometry scale uses a
  rotation-invariant centered sphere; ambiguous forks remain explicit.
- Narrowed the same-group-fork guard for explicit Trunk groups only, based on
  UE 5.8's separate trunk shader; branch forks still fail. New UE runtime
  verification remains open.
- Validation: 63 focused Wind checks, corpus rename/reorder/general-rotation/
  translation/scale invariance, source Wind smoke and real Norway USD preview/
  JSON passed. Final Package passed 27 packaged contracts and required
  stability/recovery smoke; frozen Wind smoke wrote Tree JSON. ZIP embeds the
  exact built EXE. No required smoke skipped; version remains 0.5.0-beta.


## 2026-10-13 - Live Tree hierarchy tuning

- Exposed semantic thresholds and default Keep parent level for equivalent forks.
  Preserved the previous continuation option and explicit export guard.
- Prepared both geometry models once, cached grouping/layers, and reused mesh
  vertices while updating instance tints and bone overlays. Settings persist;
  camera, manual assignments and group wind settings survive tuning.
- Recorded local CPU measurements and the 137/3336 default calibration result.
  Raw docs, source rigs, JSON schema and visible version remain unchanged.
- Validation: 71 focused Wind/viewport checks and 27 packaged contracts passed.
  Source and frozen Wind smoke exercised live controls and wrote complete JSON.
  Package stability/recovery smoke passed without skipped gates; ZIP contains
  the exact built EXE. Version remains 0.5.0-beta.

## 2026-10-13 - Scattered Rig and material assignment drafts

- Added English-only Workflows guides, navigation, five supplied screenshots,
  and links from Basic conversion. Translations are deferred until review.
- Documented synthetic rigs, baking/instancing, counts, orientation, clustering
  requirements, and unavailable Unreal Reference/Proxy/Fracturing paths.
- Documented material modes, SpeedTree Compute and color viewing, exact XML
  versus FBX face classification, Preview/Edit labels, and the existing UDIM guide.
- Validation: strict bilingual site build and all 45 existing Scattered Parts/
  material resolver tests passed. Initial sandbox run blocked ten FBX checks
  at atomic temporary-file replacement; the unsandboxed rerun passed them.


## 2026-10-13 - Wind readability and primary Tree mode

- Made Tree the primary automatic selection and renamed/reordered Skeleton Order.
  Preserved XML generator labels and saved operator choices.
- Decoupled displayed guides from grouping direction overrides; explained uniform
  bind axes, added choice tooltips, and moved degree/percent units beside values.
- Replaced Wind error dumps with short prominent explanations and file paths;
  retained raw worker diagnostics in logs.
- Added local-depth bone visibility and matching picking, cached independently
  from colors, plus optional rear-only overlap shading with session persistence.
- Validation: 73 relevant source checks and actual Alder/overlap/error rendering
  passed. No rig, JSON schema or release version change.
- Operator shadow feedback: removed excess black gaps by clipping only the
  front colored stroke and softening crossing outlines. Added live AO strength
  and radius controls with persisted defaults 14% / 7 px, after rejecting 28%
  as too aggressive and 6% as invisible. Fourteen focused Qt/viewport checks
  and actual pixels passed; near rear changes from 230 to 210 at the sampled
  point, front remains 230, distant difference is one raster quantization level.
- Final validation: Package passed all 27 packaged contracts and mandatory
  stability/recovery smoke. Final frozen Wind smoke exercised live Tree and
  shadow controls, reused visibility plans and wrote complete JSON. ZIP embeds
  the exact built EXE. No gates skipped; version remains 0.5.0-beta. AO slider
  persistence uses the existing 200 ms debounce and close flush.

## 2026-10-13 - Public links audit and remaining Russian translations

- Added Russian Scattered Rig and Assigning materials guides with matching
  procedures, UI labels, tables, screenshots, and English anchor IDs. All 14
  published English articles now have Russian siblings; FAQ remains hidden.
- Linked Basic workflow to all four Workflows articles, replaced stale future
  import-guide text, and linked format introductions and repeated-part authoring
  to the relevant public Wiki in both languages.
- Extended the existing site checker to reject missing internal destinations
  and HTML fragments. No new dependency or application behavior change.
- Validation: strict MkDocs build, the 28-page bilingual/link/image check,
  and headless Edge navigation check at 240 ms server latency passed. Six Epic
  article/API URLs opened; YouTube oEmbed confirmed the cited presentation.
  Edge's sandboxed temporary-profile launch failed; the unsandboxed check passed.

## 2026-10-13 - Documentation publication approval and README link

- Marked Scattered Rig and Assigning materials, their Russian translations,
  and screenshots ready for publication. Both guides are already in the site
  navigation and build; FAQ remains excluded.
- Added a prominent Documentation heading/link directly below Download
  SpeedAssembly in the root README, using the configured public site URL.
- Prepared public documentation sources and assets for the next commit.
  No commit or push; Pages deployment remains tied to a push to `master`.

## 2026-10-13 - Documentation publication checks

- The existing static checker now loads paths and site URL from MkDocs and
  verifies contextual ENG/RU head alternates against header destinations.
- Pinned Playwright 1.64.0 with an npm lockfile under `scripts/`. Pages installs
  Chromium and runs the existing navigation contract before artifact upload;
  benchmark modes remain separate. Updated local setup instructions.
- The browser gate derives its server prefix and sitemap origin rewrite from
  the built home canonical URL instead of duplicating the publication address.
- Validation: strict build and all 28 generated pages passed. Chromium passed
  the 240 ms navigation contract for the normal build and an isolated build
  using another origin, URL prefix, and site directory. Negative probes rejected
  a wrong head alternate and removed hover preloading. Workflow ordering passed.
  GitHub Actions itself has not run; no commit, push, or deployment.


## 2026-10-13 - Opaque realtime bone renderer

- Replaced QPainter bone strokes and CPU visibility clipping with one opaque
  unlit GPU batch using hardware depth. Vectorized endpoint projection and
  strict-crossing shadow events; excluded adjacent/endpoint/parallel contacts.
- Expanded strength to 0-100%, default 35%; normalized radius to 0-3, default 1
  = 12 pixels at 1440p with monitor height/DPI scaling. Migrated old pixel values
  and retained live uniform updates and debounced persistence.
- Rotating complete frames with GPU completion: 347 joints median 2.16 ms /
  p95 2.48 ms; 1108 joints median 6.22 ms / p95 6.90 ms. Real pixels verify
  opaque colors, correct depth, local AO and no serial-joint shading.
- Relevant source checks: 47 passed. Source Wind smoke wrote complete JSON.
  No source rig, export schema or release version change.
- Final Package: 27 packaged contracts plus mandatory stability/recovery
  passed. Frozen Wind smoke drew the opaque GPU batch, exercised relative AO
  controls and wrote complete JSON. ZIP contains the exact built EXE. No
  skipped gates; version remains 0.5.0-beta.


## 2026-10-17 - Bone shading defaults and section

- Wind now defaults to shading enabled, 50% strength and 1.20 relative radius;
  existing saved values retain precedence. All three controls share the
  collapsible Bones Shading section, expanded initially.
- Reused the Fracture section widget through the shared preview shell without
  changing its behavior. Relevant Wind, preview-shell and Fracture UI checks:
  10 passed. Quick preview built successfully at dist-preview/SpeedAssembly_preview.cmd;
  no Package or release validation.

## 2026-10-17 - Isolated Rust conversion performance experiment

- Added a reproducible PyO3 experiment outside the application package, with
  source profiling, fresh-process stage/wall/CPU/parent-memory measurements,
  private cache controls, Rust normalization kernels and numerical USDA writing.
- Retained 126 accepted conversions. Big Spruce: 1.358 -> 1.144 s; WorldTree:
  18.972 -> 15.633 s; unchanged 14.16M-triangle FBX path: 50.086 -> 32.754 s.
  Heavy USDA writing alone: 26.760 -> 9.556 s, 2.80x. Exact hashes match.
- Validated nine canonical XML models, packed-buffer and numeric edge parity,
  71 existing backend contracts, and OpenUSD counts on both large outputs.
  Recorded the source JSON cache slowdown and source-only integration gap.
- Production code, UI, FBX loading, application dependencies and release version
  are unchanged. No Rust-enabled EXE, Package build, UE import or GitHub upload.

## 2026-10-17 - Faster initial XML discovery without full-model caching

- Traced the old streamed-discovery decision and later Scattered Parts/vertical
  warning requirements before changing the Python source-opening boundary.
  Reuse one hardened XML document; normalize authored bones and count parts
  without constructing geometry. Skeletonless input retains canonical analysis.
- Retained 52 accepted opening runs and six real-source parity comparisons.
  Real Qt readiness: Big Spruce 4.017 -> 2.662 s without source caching, or
  5.514 s cold/4.498 s warm JSON before; WorldTree 32.503 -> 13.829 s uncached.
  Recorded exact inputs, caveats, service/packaged-adapter timings and memory.
- Preserved XML safety budgets, ambiguous placement rejection, normalized bone
  warnings and the >=5 MiB fresh-worker boundary. Conversion and FBX caches
  remain unchanged; generic JSON-cache risk and remaining reads stay tracked.
- Passed 632 default tests, 59 final focused checks, 27 packaged contracts and
  both required real-result/recovery smokes with no skips. The actual frozen EXE
  matches source discovery on Big Spruce, WorldTree and both grass inputs without
  creating a source cache. No unexpected crash or new Unreal import.
- Built `dist-next/SpeedAssembly.exe` and its ZIP at the existing version.
  Rust remains experimental; no dependency, backend switch, release bump or
  GitHub publication. Evidence: `experiments/xml_opening/RESULTS.md`.

## 2026-10-18 - Native XML opening with shared Wind data

- Added the default packaged Rust/PyO3 opening reader. Validate complete XML and
  existing source budgets, then return compact opening facts; retain Python
  canonical transforms, skeleton normalization and Scattered Parts semantics.
  Legacy encodings and unusual structure use the existing reader.
- Discovery returns authored Wind from the same source snapshot, avoiding the
  second read and worker startup. Preserve manual refresh, Ground Cover,
  large-source isolation, cancellation and leaf-only synthetic-rig behavior.
- Retained 43 accepted measurements and six-source exact parity. Paired source
  Qt readiness: Big Spruce 3.454 -> 1.565 s, WorldTree 15.701 -> 4.085 s.
  Clustered grass shows no established total gain; native DOM memory and worker
  startup remain measured limits. Evidence: `experiments/rust_xml/RESULTS.md`.
- Passed 664 default tests, 81 focused checks, 27 packaged contracts and both
  required real-result/recovery smokes without skips. No unexpected native
  crash or new UE import. Package bundles the extension and upstream notices;
  user machines do not need Rust. No version change or GitHub publication.
- Final EXE readiness: Big Spruce 1.071–1.303 s, WorldTree 3.440–3.892 s, two
  openings each including automatic Wind. Complete source/frozen worker equality
  holds on four inputs; ZIP/EXE hashes, integrity and bundled licenses verified.

## 2026-10-18 - One owner for Source Opening Facts

- Consolidated reader selection, native projection recovery and authored Wind
  identity reading in `opening_xml.py`. Discovery merges complete source facts
  with persisted settings; Wind retains JSON output and synthetic-rig resolution.
  Partial XML/native availability no longer reaches those callers.
- Kept Rust exchange, canonical interpretation, UI/worker payloads and cache
  policy unchanged. Added the domain term and recorded module ownership.
- Passed the 670-test default suite after one documented Qt typography flake;
  a separate theme/opening/Wind/Qt check passed all 76 tests. Added intent-level
  checks that both opening views propagate broken-native and rejected-input
  errors without silently selecting Python.
- Retained exact discovery/Wind signatures on six sources and full equality
  with the pre-refactor EXE on Big Spruce, WorldTree and both grass sources.
  No new native kernel, release version, commit or GitHub publication.
- Package passed 27 contracts and both mandatory real-result smokes without
  skips. The new EXE equals source on four inputs; ZIP/embedded EXE, input hashes
  and upstream notices verify. Four interleaved openings per version give
  1.356 -> 1.379 s for Big Spruce and 4.189 -> 4.057 s for WorldTree. No new
  speedup or stable regression is established. Evidence:
  `experiments/rust_xml/OPENING_OWNERSHIP.md` and its acceptance records.

## 2026-10-18 - Production Rust USDA numerical serialization

- Moved numerical payload iteration/chunking behind `usda_numbers.py`; added
  pinned `native/usda_numbers` with borrowed buffers and exact `%g` text. Kept
  scene authoring/publication, canonical models, FBX and UI choices unchanged.
- Added shared Rust build ownership, frozen-module inclusion, upstream notices
  and a mandatory real-result conversion-worker smoke. Kept source Python
  recovery and explicit packaged import/API failures. Mid-array cancellation
  preserves old outputs and releases buffer leases.
- Passed 679 default tests, 27 Package contracts and all required smokes without
  skips; strict native lint/format, 24 old/new author pairs and actual frozen
  heavy-FBX parity pass. Retained UE 5.7.4 import/build evidence with matching
  skeleton bindings; recorded pre-existing material API warnings separately.
- Twenty-four source timing runs: heavy writing 45.680 -> 16.560 s
  wall and 27.000 -> 9.469 s CPU; full 87.115 -> 56.827 s.
  Parent peak 3331 -> 2103 MiB. WorldTree full median
  31.310 -> 27.453 s. Small-input CPU gain is not established; keep measured
  scope and wall variation. No version bump, commit or publication.
- Evidence and exact candidate hashes: `experiments/rust_usda/RESULTS.md` and
  `results/acceptance.json`. Runtime Wind/viewport validation was not rerun.

## 2026-10-18 - Shared source extraction for canonical and Proxy projections

- Implemented architecture candidate 3 in `source_extraction.py`. Shared
  geometry, skinning, skeleton and Repeated Part interpretation now have one
  owner; canonical and Proxy composition, diagnostics, identity and cache
  policies stay separate. Updated opening queries and isolated Rust experiment
  hooks. No new native extraction adapter or cache schema change.
- Exact old/new source facts match on ten inputs through WorldTree; all four
  Simple Tree export modes match. Passed 680 source tests, 27 Package contracts,
  all required smokes, frozen Proxy Preview and old/new frozen worker parity on
  Simple Tree and BigSpruce. ZIP/native/notices checks pass.
- UE 5.7.4 imports the exact new EXE output with three correct mesh/Skeleton
  associations and no error-level log entries. Existing material API warnings
  remain; animated Wind/material appearance were not rerun. Recorded the
  pre-existing non-finite OriginalScale discrepancy for a separate change.
- Evidence: `experiments/source_extraction/RESULTS.md` and `results/acceptance.json`.
  No measured speedup, version change, commit or publication claimed.

## 2026-10-18 - Commit production Rust work and retain local experiments

- Split production XML opening, USDA numerical serialization and shared source
  extraction into three logical commits. Retained native sources, lockfiles,
  build integration, licenses and contract tests; excluded local experiment
  directories and their binaries/results.
- Recorded the operator's validation rule: byte-identical USD with unchanged
  payloads/settings reuses accepted UE import evidence. Source/Package gates
  still apply to runtime changes. No new build is required for commit grouping
  and documentation alone; the preceding 680-test/full-Package result applies.

## 2026-10-18 - Move durable experiments outside the repository

- Archived all five experiments in
  `D:/3D Personal/XMLtoUSD_miscFiles/SpeedAssembly_Experiments`. Retained 242
  original source, document, configuration and evidence files, verified with
  SHA-256. The external README and manifest describe reproduction limits,
  retained files and intentional omissions; the complete archive is 1.11 MiB.
- Removed `Project/experiments/`, including the previously tracked Python-only
  opening study. Discarded 409 generated/runtime/build files, about 13.50 GiB,
  after verifying the retained archive. Test-tree assets were not modified.
- Recorded the external storage contract in the wiki and local agent rules;
  updated current evidence references and retired the in-repository directory.
  Future archives keep useful code and compact results; disposable outputs,
  caches and temporary files stay outside them. Production Rust crates stay in
  `Project/native/` and builds/tests do not depend on the archive.
- Rechecked all retained hashes and current evidence paths. Production, native,
  test and build sources are unchanged; no new Package or Unreal import needed.

## 2026-11-04 - Assign the next release candidate

- Assigned `0.6.0-beta.1` for the requested full build and GitHub draft. MINOR
  reflects Tree/PVE Wind grouping, live Wind controls and skeleton diagnostics
  added since published `v0.5.0-beta`, alongside XML-opening and USDA-writing
  performance work. The release stage remains beta.
- The candidate must pass source checks, the complete Package gate and release
  stability checks before its verified ZIP is attached to a draft. The version
  remains fixed across repairs/rebuilds. Publish remains a manual operator step.
- Source validation passed all 680 selected tests; both native crates passed
  formatting and strict Clippy. Public home, Proxy Mesh and UDIM help routes
  return HTTP 200 in ENG and RU. Removed the obsolete UDIM-publication blocker;
  browser navigation/cache behavior was not revalidated in this check.

## 2026-11-05 - Explain the long release-validation run

- Audited existing candidate `751de6c` reports without rerunning the heavy tests.
  Default pytest took 97.97 s; Package log timestamps span 169.09 s, including
  3.60 s for Rust release builds. The additional 160-launch stability sweep
  took 2249.55 s. Twenty interactive Fracture scenarios alone report 1201.69 s.
- The long delay came from selecting extended Fracture/viewport validation,
  not evidence of a Rust performance regression. The standalone gate code was
  unchanged from `v0.5.0-beta`. The default repetition volume was added beyond
  the completed ordinary full-build gate without a specific new failure to
  investigate; that selection caused the extra delay.
- Clarified that ordinary full builds retain source checks and all Package
  checks/smokes. Extended stability requires an explicit request or a justified
  repeated-state/native-lifetime regression. Historical raw instructions remain
  preserved but are superseded by this maintained policy. No runtime, tests,
  build scripts, candidate ZIP or GitHub draft changed.
- Compact timing evidence: `<archive>/validation_duration_2026-11-05/`.

## 2026-11-09 - Probe SpeedTree import into UE 5.8 PVE

- Verified Growth Data import and reload and saved a PVE graph from a
  two-branch SpeedTree XML fragment in UE 5.8.4. Recorded the internal JSON
  route and remaining graph evaluation and fidelity checks in
  [Experiments](wiki/experiments.md#speedtree-raw-xml-to-ue-58-pve-growth-data).

## 2026-11-10 - Verify the PVE Growth Data import UI

- Created a Growth Data asset in the UE 5.8.4 Content Browser, loaded the
  SpeedTree fragment through UpdateDataAsset, and saved the asset. Added
  the click path and folder replacement behavior to the experiment record.
- Traced the subsequent PVE graph crash to a missing per-point `budStatus`
  array in the fragment and recorded CR-018 and its regression gate.
- Corrected the fixture's bud status and UpVectors. Verified the fragment
  in the PVE viewport and baked a non-Nanite Static Mesh in UE 5.8.4.
- Traced the Growth Data radius channel and typed attributes, including
  fields the importer and Mesh Builder recompute.

## 2026-11-10 - Add the PVE Growth Data prototype

- Added the UE 5.8 JSON mode to the conversion gear and packaged Rust
  extensions. It uses Spine with a whole-tree Bones fallback and an operator
  warning that identifies the rejected Spine data.
- Tested the full SimpleTree through Growth Data Loader, Manual Edit and
  Mesh Builder in UE 5.8.4. Added source regression coverage for physical
  joins, preserved radii, deterministic output and fallback.
- Package passed all 27 packaged contracts and all three smokes. The frozen
  conversion worker reproduced both Unreal-tested JSON files byte for byte.
  A source Qt smoke confirmed the yellow fallback status. The broader
  status-card suite reproduced one pre-existing SkinningTickLabel teardown
  failure on HEAD.

- Reused the resolved PVE parent indices and request validation.

## 2026-11-10 - Show the active mode on the conversion button

- The conversion button shows the active export mode beneath its action label.
  The menu, button caption, and status summary share one label table.

## 2026-11-10 - Document PVE Growth Data export

- Added the English and Russian export guide and linked it from the workflow
  lists and Unreal import guide. Both languages passed the strict site build.

## 2026-11-11 - Compare UE 5.7/5.8 and 5.9 Dynamic Wind

- Archived a Russian standalone HTML report with architecture diagrams,
  structural work/memory charts and 37 source-file hashes.
- Recorded GPU-only provider semantics, force-mode track lifecycle, automatic
  bake compatibility, authored-radius/modal-frequency requirements and exact
  JSON/USD units. Added the 5.9 authoring/reimport gap to known bugs.
- Checked desktop/mobile rendering and source anchors. Source research only;
  no production code, engine files, runtime validation or build changed.

## 2026-11-11 - Add UE 5.9 Force Based export

- Added the Status profile switch, independent saved Legacy/Force settings and
  shared optional-override controls in Wind and Advanced Wind Settings.
- Added one JSON/USD Wind model with structural sections from Spines/Bone Radius,
  missing-radius warnings and matching exported root names. Legacy bytes match HEAD.
- UE 5.9 import/reimport matched groups and all structural profiles; runtime bake
  accepted 42 non-root modal bones. Package contracts, three required smokes,
  frozen Force export parity and strict bilingual documentation build passed.
- Recorded nine existing source-test failures and remaining visual/cooked-game
  validation limits. SpeedTree screenshot replacement awaits app access.

## 2026-11-11 - Restyle the wind profile selector

- Joined both modes into one rounded pill using the shared tab colors and
  button outlines. Verified both states visually; four wind tests passed.
- Quick preview built. The packaged EXE retains the previous styling until
  the UI is approved and Package is run again.
- Follow-up: reduced selector height from 60 to 48 px and used sage/olive
  colors. Visual check, four wind tests and Quick preview passed again.
- Final styling correction uses the Convert/Generate button palette. Wind
  retains Ground Cover and Gust Attenuation in Legacy only, reserves the same
  header height in Force Based, and centers its remaining controls. Both
  layouts checked; four wind tests passed; Quick preview updated.

## 2026-11-11 - Replace the SpeedTree export screenshot

- Replaced the shared English/Russian export-settings image with the operator's screenshot showing Branch spines enabled. Verified an exact SHA-256 match to the supplied PNG.

## 2026-11-11 - Consolidate Wind state and structural Source extraction

- Moved Main/Advanced group exchange, both profiles' settings and session
  acceptance into one Qt-free owner. Match joint membership instead of list
  position; retain Advanced state through ordinary autosave and main edits.
- Shared named structural facts between Wind and PVE. Force inspection/JSON
  use one source snapshot for identities and sections. PVE keeps whole-tree
  fallback and native row adaptation; Wind keeps incoming-section policy.
- Ten USD/Wind/PVE outputs match their pre-refactor SHA-256. Source checks:
  678 passed, the same nine known failures. Package passed 27 contracts and all
  three required real-result smokes. No version bump or new Unreal import.

## 2026-11-11 - Polish the complete working diff

- Clarified Wind state/payload construction, typed shared Qt controls and reused
  profile constants. Simplified Skeleton USD field indentation with identical
  bytes. Kept transformation math, error rules and public parameters unchanged.
- Corrected stale wiki claims about USD Wind support, private PVE parsing and
  the already-replaced export screenshot. Public ENG/RU copy and image unchanged.
- Baseline and final focused checks: 115 passed. Full source: 678 passed with
  the same nine known failures. All ten export hashes still match; serialization
  CPU checks at 43/16,384 joints detect no regression. Strict documentation and
  the 30-page bilingual contract passed. No new tests or dependencies.
- Package passed 27 contracts and all three required real-result smokes without
  bypasses. Version unchanged; byte-identical exports reuse Unreal acceptance.

## 2026-11-12 - Reconcile the nine stale fixture checks

- Traced all nine failures to the SimpleTree_01 re-export in `98f0dc1` and
  checked the old Boolean prerequisites against the XML from `6a0f5cb`.
- Preserved same-shell cuts on a minimal synthetic cylinder; selected a real
  terminal branch with one Repeated Part for Detailed Cuts export. Replaced
  stale counts, root origin and bone IDs with source-derived contracts.
- Verified complete USD bindings through OpenUSD and byte-identical Legacy
  USDA with/without Spines. Merged two duplicate cases into stronger tests.
- Full source gate: 685 passed. No skip/xfail additions, production or fixture
  asset edits, version change or new Unreal import. Removed the resolved issue
  from Known Bugs; retained the evidence in Experiments.
- Package passed all 27 contracts and all three required real-result smokes,
  without bypasses or the separate extended stress sweep.
