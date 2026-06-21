# Decisions

## Role

This is the decision log for architecture reviews. It records choices that
future architecture work should not re-litigate without new evidence.

Importer-facing facts still belong in `docs/ue_import_contract.md`,
`docs/speedtree_mapping.md`, and `docs/workflow_status.md`.

## 2026-06-05: Preview stability must not redefine mesh quality contracts

Status: Accepted

Decision:

- Native-risk preview work may be isolated in worker subprocesses and may use
  cheaper diagnostic payloads when the output is explicitly viewport-only.
- Proxy Mesh generation must keep QEM simplification through
  `fast-simplification`; deterministic face sampling is not an acceptable proxy
  simplification backend.
- GUI worker polling must drain result/error files before reporting a stopped
  worker as crashed. A stopped worker with exit code `0` and a result file is a
  success, not a crash.

Rationale:

- Replacing QEM with face sampling fixed one native-crash suspicion but broke
  proxy topology into disconnected triangle clouds.
- Fracture Preview and Proxy Mesh have different quality contracts: one is a
  diagnostic viewport payload, the other is an exported companion asset.
- Packaged worker races can make the process state visible before the result
  event is processed; the file protocol is the more reliable completion signal.

## 2026-06-14: Preview shell is shared infrastructure, not a mode switcher

Status: Accepted

Decision:

- Proxy Mesh Preview and Fracture Preview use the same Preview Shell module for
  window ownership, modality, focus, and the two-column viewport/settings
  layout.
- The current UX keeps separate Geometry-tab entry points and separate
  mode-specific dialogs for mode settings and result presentation.
- Do not introduce one hot-swappable runtime shell object unless a real
  in-preview mode switcher becomes product behavior.

Rationale:

- The shared shell module removes duplicated window/layout behavior while
  preserving the current modal preview workflow.
- A runtime mode switcher would couple proxy and fracture panel lifetimes,
  settings ownership, and worker cancellation rules without current user-facing
  leverage.
- Future architecture reviews should treat one runtime shell object as a new UX
  requirement, not an unfinished stability fix.

## 2026-06-06: Manual fracture cuts are current-XML session state

Status: Accepted

Decision:

- Manual `Fracturing by Bones` cut sites are Pinned Fracture Cut Sites over the
  current source skeleton.
- They are stored in the active Fracture Preview settings only for the current
  XML session and are cleared when the selected XML changes.
- They are not Global Remembered State, Persisted Operator Settings, or named
  preset content.
- Qt owns viewport picking and visual-only toggles such as `Show Bones` and
  `Hide Repeated Parts`; `fracture_service.py` owns Fracture Piece membership,
  manual cut validation, and automatic fill.

Rationale:

- Joint tokens are source-specific and can become invalid or misleading on a
  different tree.
- Keeping manual picks out of presets avoids hidden cross-file coupling.
- The UI can choose bones, but it must not own the destructibility partition
  contract.

## 2026-06-12: Fracturing uses one Manual Fracturing planner

Status: Accepted

Decision:

- Operator-facing Fracturing has one planner: Manual Fracturing.
- Manual pinned cuts, optional Stump Piece, Preserve Trunk Bias, and automatic
  hierarchy fill are settings on that planner, not separate fracture methods.
- Legacy method ids such as `pure_hierarchy`, `wind_guided_hierarchy`,
  `branch_base_greedy`, and `manual_pinned_bones` are rejected loudly.
- Optional Fracture Caps are generated in `fracture_geometry.py` so preview and
  export use the same sliced piece mesh contract.
- Exploded Fracture Preview is visual-only Qt state and does not change export.

Rationale:

- The useful product model is always pinned cuts plus deterministic fill.
- Separate modes made UI state look more powerful than the underlying planner
  and encouraged mismatched preview/export expectations.
- Caps are geometry behavior, not viewport decoration.

## 2026-06-06: Fracture Preview uses a local UI background thread

Status: Superseded by 2026-06-12 process isolation

Decision:

- `Fracture Preview` generation runs in a Qt-owned background thread, not in a
  short-lived packaged frozen worker executable.
- `Fracture Export` remains subprocess-backed because it writes authoritative
  USDA files and should stay isolated from the Qt shell.
- Preview settings changes invalidate older preview generations by generation
  id; stale thread results must not update the current dialog.

Rationale:

- The packaged frozen executable showed intermittent native startup crashes
  before Python could write a worker error payload.
- Fracture Preview is read-only and interactive; repeatedly spawning frozen
  executables while the operator changes controls is a worse runtime contract
  than a local background thread.
- Export isolation still protects the high-stakes authoring path.

## 2026-06-12: Fracture Preview uses process isolation

Status: Accepted

Decision:

- `Fracture Preview` generation runs in an isolated worker process.
- Settings changes cancel stale preview workers and start a fresh isolated job.
- Worker result/error files are drained before reporting a stopped worker as
  crashed.

Rationale:

- Runtime traces showed native crashes inside threaded fracture preview work
  could close the Qt shell before Python produced a useful error.
- Process isolation keeps native failures outside the operator UI and matches
  the Proxy Mesh crash-containment contract.

## 2026-06-14: Packaged workers use a dedicated sidecar executable

Status: Superseded by 2026-06-19 self-worker packaged executable

Decision:

- Packaged release builds include `XMLtoUSDAConverter.exe` for the Qt shell and
  `XMLtoUSDAWorker.exe` for file-protocol worker commands.
- Conversion, Proxy Mesh, Fracture Preview/Export, and FBX helper worker
  commands should resolve to the sidecar worker when it exists.
- The GUI executable may remain a compatibility fallback for older layouts, but
  it is not the primary packaged worker runtime.

Rationale:

- Runtime traces showed repeated native worker crashes before Python could write
  an error payload while worker commands were launched through the GUI exe.
- A sidecar worker keeps Qt/OpenGL bootstrapping out of heavy geometry workers
  and makes packaged worker behavior easier to reproduce from smoke tests.

## 2026-06-19: Packaged GUI embeds the worker executable

Status: Superseded by 2026-06-19 self-worker packaged executable

Decision:

- The distributed release contains one executable: `XMLtoUSDAConverter.exe`.
- The GUI executable embeds `XMLtoUSDAWorker.exe` as a PyInstaller binary
  payload and extracts it on demand to
  `%LOCALAPPDATA%\XMLtoUSDAConverter\runtime\worker\<worker-build-id>\`.
- The worker remains a separate runtime process. Packaged worker commands must
  resolve to the extracted embedded worker, not to the GUI executable and not
  to a sidecar beside `dist-next`.
- The worker cache key is derived from the embedded worker SHA-256 so copying
  the GUI executable does not create a false cache miss.

Rationale:

- The operator should be able to share one executable without auxiliary files.
- Process isolation remains required because native geometry failures must not
  take down the Qt shell.
- Keeping extraction behind the Runtime Adapter preserves launcher/dev and
  packaged conversion semantics while localizing packaging failure modes.

## 2026-06-19: Packaged workers use the self executable

Status: Accepted

Decision:

- The distributed release contains one executable: `XMLtoUSDAConverter.exe`.
- Packaged worker commands launch the same executable with the worker command
  prefix, such as `XMLtoUSDAConverter.exe fracture-worker --request <path>`.
- `xml_to_usda.qt_ui.entry` must keep worker command dispatch before Qt imports
  and before GUI bootstrap so worker processes do not construct the UI shell.
- The release build must not create, embed, extract, or distribute
  `XMLtoUSDAWorker.exe`.

Rationale:

- Embedding a nested worker executable created a fragile extraction point in
  PyInstaller onefile temp directories and failed before worker startup on real
  packaged runs.
- Reusing the packaged executable preserves one-file distribution and process
  isolation without relying on an auxiliary executable on disk.
- This reopens the original GUI-executable worker risk, so packaged smoke and
  strict stability gates are the acceptance signal for this Runtime Adapter.

## 2026-06-15: Fracture Preview uses latest-state coalescing and cached reuse

Status: Accepted

Decision:

- Fracture Preview stays process-isolated, but the UI preview lifecycle now
  coalesces rapid settings changes into the latest pending request instead of
  starting a fresh worker for every transient toggle.
- Fracture Preview reuses a cached completed result when the operator returns
  to a previously computed XML/settings combination during the same session.
- Visual-only viewport controls such as `Piece Color` and `Exploded View`
  remain local viewport state and do not restart the worker.

Rationale:

- The observed crash pattern came from repeated fast worker churn over the same
  large XML, not from the fracture planner contract itself.
- Keeping the current worker alive until the last pending settings are ready
  avoids a cancellation/start storm and reduces redundant XML normalization.
- Cached reuse makes "toggle back" interactions feel immediate without changing
  the preview/export contract.

## 2026-06-21: Viewport visual-only controls are real-time state

Status: Accepted

Decision:

- Controls that do not change topology, ownership, draw-call structure, or the
  generated preview payload must update viewport/shader state directly.
- `Capsule Scale`, `Collision Opacity`, `Piece Color`, and `Exploded View` must
  not rebuild `ViewportScene`, reupload mesh buffers, or restart preview
  workers while the operator drags them.
- Preview settings that do change collision structure, such as collision mode,
  include-instance-parts, convex target, sphere fit, capsule simplify, or cap
  generation, may still use the worker path.

Rationale:

- Real-time viewport response is the default UX contract for visual-only
  controls.
- Rebuilding scene payloads for opacity/scale caused avoidable stalls and
  crash-prone event pressure.
- Shader uniforms and viewport scalar state give the same interaction model as
  piece tint and exploded preview while persisted export settings remain the
  source of truth for final authoring.

## 2026-06-16: UDIM resolution is piece-local

Status: Accepted

Decision:

- UDIM settings are applied independently per authored piece: the `Base Skeletal
  Tree` resolves its own base-material rows, and each prototype resolves its own
  repeated-part UDIM rows after local material remap.
- The same numeric `material_id` may appear in different pieces without
  cross-piece overwrite. `material_id` is not a global semantic role.
- Duplicate active UDIM settings for one `material_id` inside one piece, or a
  UDIM target that matches no real section in that piece, are fail-loud
  conversion errors.

Rationale:

- The previous global post-pass made prototype settings depend on unrelated
  pieces and allowed the wrong scope to win when ids overlapped.
- Source material ids are observed section keys, not stable semantic identities.
- Piece-local resolution matches the operator expectation that what is visible
  per row is what gets authored per piece.

## 2026-05-19: Operator settings are global, not per-XML

Status: Accepted

Decision:

- Operator settings are remembered as one global state across trees and sessions.
- Per-XML settings are not part of the product contract.
- Named presets are the intentional reuse surface on top of the global state.

Rationale:

- Users repeat the same vegetation workflow across many trees and should not
  have to rebuild state per file.
- Per-XML persistence creates implicit coupling that is hard to reason about
  when files move or are reused.

## 2026-05-19: Presets are the reuse mechanism

Status: Accepted

Decision:

- Ship a factory-defaults preset by default.
- Allow user-saved named presets.
- Show factory defaults and user presets in the preset dropdown.
- Support save, overwrite, delete, import, export, and reset-to-default flows.

Rationale:

- Users need a stable way to capture a working setup and reuse it later.
- A default preset gives the first-run experience a known anchor without
  requiring a project model.

## 2026-05-19: Output and folder memory are explicit

Status: Accepted

Decision:

- Remember last-used XML folder and last-used output folder separately.
- Auto-fill the output path from the first XML selection.
- If the user has already edited the output path manually, later XML selections
  preserve that chosen output path style and only update the filename stem to
  match the new XML.
- Overwrite decisions must be explicit user choices.

Rationale:

- The workflow is repeated often enough that folder memory removes real friction.
- Auto-fill should help first use without silently taking control away once the
  user has chosen a custom output path.

## 2026-05-19: Help is bundled inside the exe

Status: Accepted

Decision:

- The app ships with an in-app "How to use" deck.
- The deck is slide-style, with topic navigation buttons and next/back arrows.
- A dismissible first-launch prompt near the help affordance invites the user to
  open the guide.
- Everyday usage should not depend on external documents or websites.

Rationale:

- First-time users need help at the point of action, not in a separate browser
  workflow.
- The packaged app must stay self-contained for offline production use.

## 2026-05-19: Release and diagnostics are local-first

Status: Accepted

Decision:

- User-facing release is a standalone GitHub download.
- Users do not need Python installed on their machine to run the packaged app.
- The user-facing release targets Windows first.
- The app remains 100% local by default; no network telemetry.
- Diagnostics bundles are local artifacts and should include the active preset,
  settings snapshot, runtime log, output path, and other files needed to
  reproduce a bug.

Rationale:

- The release must be self-contained and easy to hand to an artist or tester.
- Local-only diagnostics keep the bug-report path practical without adding
  privacy risk or network dependence.

## 2026-05-19: Balanced is the visible CPU profile

Status: Accepted

Decision:

- Keep `balanced` as the visible default runtime profile.
- Do not expose multiple CPU profiles as an ordinary operator choice.
- Treat deeper runtime tuning as internal unless a validated need appears.

Rationale:

- The operator should not have to reason about concurrency knobs to run the
  normal tree workflow.
- Runtime tuning belongs behind the release contract, not in the core artist
  workflow.

## 2026-05-19: UV work is deferred

Status: Superseded by 2026-05-24 UDIM material UV support

Decision:

- UDIM support and second UV channel work are future work, not part of the
  current near-term product contract.
- When UV work is taken up, it must stay per-material-slot and importer
  validated.

Rationale:

- The current product goal is stable vegetation conversion first.
- UV expansion should not dilute the importer-facing contract until it is
  validated against UE.

## 2026-05-24: UDIM material UV support is operator intent

Status: Accepted

Decision:

- UDIM behavior is configured as per-material Operator Intent.
- Default behavior is `off`.
- `shift_primary_uv` offsets primary face-varying UVs for matching material faces.
- `write_secondary_uv_offset` initializes a full-size second face-varying UV channel to the first UDIM offset `(0.5, 0.5)` for every face and then overwrites only the target material faces with the selected UDIM offset.
- UDIM math uses fixed `base_udim = 1001`.
- Active UDIM settings that match no authored inline material are resolution errors.

Rationale:

- The material target is the stable operator-facing unit for shared bark/branch atlas workflows.
- Full-size second UV data avoids malformed per-face-varying payloads when only part of a mesh uses UDIM, and default-filling the whole channel prevents stale authored `st1` data from leaking through.
- External Unreal asset prototypes do not expose inline geometry in USDA, so unmatched settings must fail loudly instead of pretending to edit them.

## 2026-05-24: Tk shell is retired

Status: Accepted

Decision:

- The Tk GUI is no longer a supported operator surface.
- The supported desktop UI path is the PySide6 shell.
- The Tk implementation has been removed. The retired `gui.py` entrypoint must
  stay a hard failure that points users to the PySide6 shell.

Rationale:

- The PySide6 shell now covers the supported operator workflow.
- Maintaining two supported desktop shells dilutes locality and release confidence without a current product benefit.

## 2026-05-16: Architecture review docs follow the skill entry-point names

Status: Accepted

Decision:

- Keep `docs/PROJECT_MAP.md`, `docs/GLOSSARY.md`, `docs/ARCHITECTURE.md`, and
  `docs/DECISIONS.md` as the main architecture-review inputs.
- Keep `docs/developer_architecture.md` as a reference document, not a
  separate source of architectural truth.

Rationale:

- The architecture skill searches these names first.
- Stable entry points reduce exploration cost and make future reviews more
  deterministic.

## 2026-05-16: UE/importer contract stays above architecture neatness

Status: Accepted

Decision:

- Architecture changes must preserve the source-of-truth order from `AGENTS.md`.
- When a proposed module shape conflicts with verified UE 5.7 import behavior,
  verified UE behavior wins.

Rationale:

- This project is a reverse-engineering pipeline, not a generic converter.
- Module depth is useful only if it preserves importer-facing correctness.

## 2026-05-16: Normalized model remains the central conversion seam

Status: Accepted

Decision:

- Raw XML traversal must not write USDA directly.
- XML parsing, normalization, validation, material resolution, and USDA
  authoring continue to meet through the normalized `CanonicalTreeModel`.

Rationale:

- This gives locality for XML interpretation and makes writer behavior testable
  without duplicating parsing assumptions.

## 2026-05-16: UI shells are adapters over application interfaces

Status: Accepted

Decision:

- Qt is the supported UI contract; the retired Tk path must not receive new feature work.
- UI modules collect operator state and render diagnostics; they do not own core
  conversion semantics.

Rationale:

- The packaged GUI and launcher/dev runtime must stay behaviorally aligned.
- Duplicated UI-side conversion rules are hard to regression-test.

## 2026-05-16: Runtime stability outranks all-core saturation

Status: Accepted

Decision:

- `CpuProfile.BALANCED` remains the default operator-facing profile.
- Large-job work prioritizes completion, diagnostics, cleanup, and packaged
  runtime reliability before single-FBX all-core optimization.

Rationale:

- Current parallelism is prototype-level and stage-level.
- Low aggregate CPU use during one huge FBX import is not by itself a defect.

## 2026-05-16: Compatibility facades stay thin

Status: Accepted

Decision:

- `pipeline.py`, `usda_writer.py`, and `gui.py` remain stable import/launch
  surfaces.
- New business rules should live in focused modules behind those facades.

Rationale:

- Older tests and callers still need stable surfaces.
- Letting facades grow would reduce locality and make deletion-test reasoning
  weaker.

## 2026-05-16: Static assembly is supported, skeletal assembly remains primary

Status: Accepted

Decision:

- Treat `static_assembly` as a fully supported secondary export mode, not an
  experiment.
- Keep `skeletal_assembly` as the primary project goal and default lens for
  mission, Definition of Done, and architecture trade-offs.
- Do not let static-mode simplifications erase locality for skeletal concepts
  such as `Main Skeleton`, `Base Skeletal Tree`, `Part Skeleton`, and skeletal
  binding.

Rationale:

- Static assembly import has been confirmed to work normally in UE 5.7.x.
- The project's strategic value is still the skeletal vegetation pipeline.
- Both modes can share normalized source data, but they have different
  importer-facing contracts.

## 2026-05-16: CanonicalTreeModel is source-normalized, not skeletal-only

Status: Accepted

Decision:

- Treat `CanonicalTreeModel` as the normalized representation of observed
  SpeedTree source data for vegetation assembly authoring.
- Allow it to contain skeleton, binding, prototype, material, wind, and unique
  geometry facts even when the selected export mode authors only a subset.
- Let `ConversionMode` choose the USDA authoring contract rather than changing
  the meaning of the canonical model.

Rationale:

- `skeletal_assembly` and `static_assembly` are both supported export modes.
- Static assembly should not be modeled as a hack layered on a skeletal-only
  model.
- A shared normalized model preserves locality for XML interpretation while
  keeping mode-specific importer contracts in validation and authoring.

## 2026-05-16: Add the resolved assembly model seam

Status: Accepted

Decision:

- Keep `CanonicalTreeModel` focused on source facts from observed SpeedTree XML.
- Use `ResolvedAssemblyModel` as the authoring-stage model for source facts plus
  operator intent.
- Keep mode-specific prototype replacement, explicit material overrides, output
  naming, and authoring-ready decisions behind the Assembly Resolution Module
  instead of pushing them into XML normalization.

Rationale:

- The project now has multiple supported export modes.
- Source facts and operator intent have different lifecycles, tests, and failure
  modes.
- A resolved authoring model improves locality for validation and USDA authoring
  without weakening deterministic source normalization.

## 2026-05-16: Validation is staged by invariant ownership

Status: Accepted

Decision:

- Use three validation stages as project language:
  `Source Validation`, `Resolution Validation`, and `Authoring Validation`.
- Source Validation owns source-derived XML/model invariants before operator
  intent is applied.
- Resolution Validation owns invariants that require both source facts and
  operator intent.
- Authoring Validation owns the final USDA/importer contract that will be
  written for the selected export mode.
- `validator.py` remains a public facade; stage rules live in focused
  validation modules.

Rationale:

- The validation stages have different inputs and failure modes.
- `ResolvedAssemblyModel` needs a clear validation role.
- Separating stages improves locality and makes future tests less brittle.

## 2026-05-16: Repeated Part is source-level, Assembly Part is authored

Status: Accepted

Decision:

- Use `Repeated Part` for source-level repeated part records interpreted from
  SpeedTree `LeafReferences`.
- Use `Assembly Part` for authored repeated geometry emitted through
  `PointInstancer`.
- Treat `Assembly Part` as mode-neutral: skeletal exports author skeletal
  Assembly Parts, and static exports author static Assembly Parts.
- In code, source repeated parts are `RepeatedPartInstance` values and USDA
  authoring projects them into `AuthoredAssemblyPartInstance` values.

Rationale:

- `static_assembly` and `skeletal_assembly` are both supported assembly modes.
- `LeafReferences` is a SpeedTree source concept, while Assembly Part is a USDA
  authoring concept.
- The distinction keeps source normalization language separate from export-mode
  authoring language.

## 2026-05-16: Prototype terminology is stage-specific

Status: Accepted

Decision:

- Use `Source Prototype` for reusable repeated-part definitions from SpeedTree
  `Meshes/Mesh`.
- Use `Resolved Prototype` for a prototype after source facts are combined with
  operator intent such as XML mesh, Unreal asset, FBX replacement, and material
  behavior.
- Use `Authored Prototype` for the USDA prim or subtree targeted by
  `PointInstancer.prototypes`.
- Use bare `Prototype` only as shorthand when the stage is obvious.

Rationale:

- Prototype identity, resolved payload, and authored USD prims have different
  lifecycles and failure modes.
- Static assembly can author synthetic base prototypes that do not come from a
  SpeedTree `Meshes/Mesh` source prototype.
- The `Resolved Assembly Model` needs precise vocabulary for this seam.

## 2026-05-16: Instance terminology is stage-specific

Status: Accepted

Decision:

- Use `Repeated Part Instance` for source-level placed records interpreted from
  SpeedTree `LeafReferences`.
- Use `Resolved Instance` for placed records after source facts are combined
  with operator intent and a Resolved Prototype.
- Use `Authored Instance` for per-instance data emitted into USDA
  `PointInstancer` arrays.
- Use bare `Instance` only as shorthand when the stage is obvious.

Rationale:

- Source transform interpretation, resolved prototype selection, and authored
  `PointInstancer` arrays fail in different ways.
- The distinction makes transform and binding bugs easier to locate.
- The `Resolved Assembly Model` needs a clear term for the middle stage.

## 2026-05-16: Attachment is source/resolution, Skeletal Binding is authored

Status: Accepted

Decision:

- Use `Attachment` for source or resolved relationships that associate a
  Repeated Part Instance with a source skeleton object, joint, or placement
  context.
- Use `Skeletal Binding` only for the authored skeletal USDA contract that binds
  base geometry or skeletal Assembly Parts to the Main Skeleton.
- Static Mesh Assembly export may use Attachment during interpretation, but it
  does not author Skeletal Binding.

Rationale:

- SpeedTree fields such as `BoneID` are source inputs, not already-authored USD
  skeletal binding arrays.
- Static and skeletal export modes share source placements but have different
  importer-facing contracts.
- The distinction prevents static export from inheriting skeletal-only
  requirements while keeping skeletal authoring strict.

## 2026-05-16: Material terminology is staged

Status: Accepted

Decision:

- Use `Source Material` for XML/payload material ids, names, face assignments,
  vertex colors, and FBX slot names before operator overrides.
- Use `Resolved Material Assignment` for material decisions after source facts
  are combined with operator intent and material policy.
- Use `Authored Material Binding` for USDA material prims, `material:binding`,
  and `GeomSubset` authoring.

Rationale:

- XML material ids are opaque source metadata, not universal semantic roles.
- Base-tree material controls and repeated-part material controls have separate
  resolution paths.
- Explicit FBX material modes need language that separates source slots,
  operator choices, and final USDA bindings.

## 2026-05-16: Naming terminology is explicit

Status: Accepted

Decision:

- Use `Source Name` for names observed in XML, FBX, or source filenames.
- Use `Output Stem` for the file stem chosen from the output USDA path.
- Use `Prim Name` for USD-valid prim identifiers in authored USDA.
- Use `Authored Asset Name` for the intended imported/authored asset identity.
- Use `Unreal Asset Path` only for UE package/object paths such as
  `/Game/Trees/SK_Branch.SK_Branch`.

Rationale:

- The converter has already had important naming regressions around skeleton
  naming and multi-root root-joint aliases.
- USD prim paths and Unreal asset paths are different contracts.
- Static and skeletal export modes use different root naming rules while
  sharing source names.

## 2026-05-16: Transform spaces are explicit

Status: Accepted

Decision:

- Use `Source Space` for transforms as observed in SpeedTree XML or imported
  source payloads before project conversion.
- Use `Stage Space` for transforms authored into USDA after validated axis and
  basis conversion.
- Use `Prototype Space` for local prototype payload space.
- Use `Attachment Space` for interpreting how a Repeated Part Instance relates
  to its source Attachment.
- Use `Instance Transform` for resolved per-instance position/orientation/scale
  before USD array authoring.
- Use `Authored PointInstancer Transform` for the final `positions`,
  `orientations`, `scales`, and `protoIndices` authored into USDA.

Rationale:

- Transform bugs can hide behind vague words like rotation, pivot, or scale.
- XML inline prototypes, FBX replacement payloads, and PointInstancer arrays
  have different transform contracts.
- Explicit transform-space language supports targeted tests and prevents
  arbitrary corrective offsets from becoming production behavior.

## 2026-05-16: Runtime execution terminology is explicit

Status: Accepted

Decision:

- Use `Runtime Job` for one executing conversion run with telemetry,
  cancellation, cleanup, worker/helper processes, and a Job Workspace.
- Use `Job Workspace` for the per-run temp/cache directory and diagnostics
  surface.
- Use `Conversion Worker` for the subprocess that owns a large conversion
  outside the UI process.
- Use `FBX Helper` for isolated native Autodesk FBX import helper processes.
- Use `Runtime Adapter` for launcher/dev runtime and packaged frozen executable
  runtime behavior.

Rationale:

- Caller intent, runtime execution, and authored output have different
  lifecycles and failure modes.
- Large conversions need precise language for telemetry, cleanup, crash
  recovery, and packaged-vs-launcher parity.
- `CpuProfile` and runtime strategy must not be confused with USDA authoring
  semantics.

## 2026-05-16: UI and operator state terminology is explicit

Status: Accepted

Decision:

- Use `Operator State` for current operator-selected UI values.
- Use `Persisted Operator Settings` for saved global operator values and named
  presets that restore Operator State.
- Use `UI Shell State` for visual shell state such as window geometry, theme,
  open tabs, and visual preferences.
- Only the conversion-relevant subset of Operator State becomes Operator Intent
  for `ConversionRequest` or `ResolvedAssemblyModel`.

Rationale:

- Material overrides, prototype source choices, wind sliders, UI theme, and
  window geometry have different lifecycles.
- `ResolvedAssemblyModel` must not accidentally depend on visual UI preferences.
- Qt should remain an adapter over shared application contracts, not an owner
  of conversion semantics.
