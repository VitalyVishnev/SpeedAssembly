# Wind Viewport Working Plan

Status: V1 is implemented. V2 is implemented for the current accepted scope:
manual override stack, preview-local JSON export, shortcut hints, missing-label
Auto fallback, autosave restore, worker-process external loading, FBX
skeleton-only preview, USD/UsdSkel loading, and explicit multi-skeleton USD
choice are in place.

## Goal

Make Wind Preview a deterministic wind-group authoring and inspection window
without forking the viewport system.

The window must support:

- SpeedTree XML wind inspection from XML generator groups.
- Auto Hierarchy grouping from skeleton topology, independent of XML wind
  labels.
- Manual override layers on top of XML or Auto base groups.
- Dynamic Wind JSON generation from the final visible group stack.
- External FBX/USD skeleton workflows for trees authored outside SpeedTree.

## Viewport Contract

- Wind Preview must stay on the shared `MatcapViewport`/`ViewportScene` path.
- Viewport fixes belong in the shared viewport interface, not in Wind-only
  rendering code.
- Proxy, Fracture, Prototype, and Wind previews may have different controls and
  scene adapters, but rendering, OpenGL upload, camera behavior, bone overlay,
  picking, and static-scene precompute belong behind shared viewport APIs.
- Visual-only selection, highlight, visibility, or wind-group color changes
  must update viewport state without rebuilding or re-uploading static mesh
  buffers.
- All viewport shortcuts in every preview window must be shown briefly in the
  bottom-right corner as small translucent text.
- Shortcut hints are contextual: show only shortcuts that are active in the
  current mode.
- Wind Preview mesh geometry is not pickable for group assignment. Picking uses
  the skeleton overlay and the exported child-joint token.

## Source Modes

Wind Preview has one window with source-specific controls and common
group/edit/export controls.

### SpeedTree XML

- Base modes:
  - `XML Generator Groups`
  - `Auto Hierarchy`
- XML Generator Groups uses XML-derived Dynamic Wind group labels.
- Auto Hierarchy must not read XML wind group labels.
- Manual override layers remain when switching between XML Generator Groups and
  Auto Hierarchy. Only the lower base stack changes.
- If XML generator labels are missing, open in Auto Hierarchy with a warning and
  disable XML Generator Groups.
- `Show Mesh` is available for XML sources. When off, the XML source is shown as
  skeleton-only.
- Wind Preview Generate JSON writes the final visible XML/Auto plus manual
  override result.
- The main-window Generate Wind JSON button remains the legacy XML-derived quick
  path and is not replaced by Wind Preview.

### External Skeleton

- External Skeleton mode is inside the same Wind Preview window.
- UI controls: source path field, `Browse`, explicit `Load`.
- Supported formats for this iteration:
  - FBX
  - `.usd`
  - `.usda`
  - `.usdc`
- `.usdz` is out of scope for this iteration.
- Unavailable FBX/USD backends report a short in-window error on `Load`.
- FBX uses the available Autodesk FBX SDK path and loads skeleton data only.
- USD uses `pxr`/OpenUSD Python support from the project `usd-core`
  dependency when available.
- Text `.usda` and ASCII `.usd` have a deterministic fallback that reads
  `def Skeleton` blocks directly and loads skeleton data only.
- Binary `.usdc` and binary `.usd` require `pxr`; do not hand-parse crate files.
- External import runs in a worker process, not in the Qt UI process.
- If no skeleton is found, keep the window open, show an error, clear the
  external viewport state, and allow another file to be loaded.
- Duplicate joint names fail loudly.
- If a USD file contains multiple Skeleton prims, Wind Preview shows a compact
  Skeleton dropdown. The operator chooses the prim explicitly; the loader must
  not choose by joint count, prim order, name, or any other hidden heuristic.
- Multiple roots inside the chosen skeleton are all group 0, matching multi-trunk
  trees.
- External sources start with Auto Hierarchy immediately.
- External Auto Hierarchy uses file order plus the same `Continue line` policy.
- Include all joints, including leaf/end/helper joints. Do not hide joints by
  name heuristics.
- Generate JSON uses the loaded skeleton snapshot that the operator sees in the
  viewport. It does not reload the file at export time.
- External Skeleton uses the same default tree camera behavior as existing
  previews.

## Auto Hierarchy Contract

- Group order follows tree growth: group 0 is trunk/root paths, higher groups
  are branch levels above them.
- The group list is bottom-up like layer stacks: group 0 is the bottom layer;
  higher groups appear above it.
- Auto group count is an integer slider from 1 to 10.
- Default group count is `min(detected_depth + 1, 3)`.
- Descendants deeper than the selected group count stay in the highest group.
- SpeedTree skeleton ordering is the default analyzer:
  - starting at each root, the child whose joint order immediately follows its
    parent continues the current branch path;
  - other child subtrees start the next group level.
- `Continue line` is visible only in Auto Hierarchy mode.
- `Continue line` applies per Auto group level. When enabled, an endpoint-
  continuous child chain may stay in the current group even when its joint order
  is not adjacent.
- `Continue line` affects only Auto base generation. It does not change manual
  override layers.
- `SimpleTree_01` and `SimpleTree_02_three_trunks` must match current
  hand-authored XML group assignment when generator labels are stripped before
  running Auto Hierarchy.

## Manual Override Layers

- Manual layers sit above the selected base stack and override it.
- Higher layers win over lower layers.
- `+` creates a new empty group at the top of the stack and does not enter Edit
  automatically.
- New manual groups have auto names only. Manual rename is out of scope.
- Manual group reorder is out of scope. Top insertion is the only V2 ordering
  action.
- Empty manual groups are ignored during export and do not show warnings.
- Final exported group indices are compacted bottom-up from non-empty visible
  groups.
- Group panels show the final visible count, because that is what JSON will
  export.
- The whole group panel toggles Edit. Clicking the active group again turns Edit
  off.
- Active Edit group is highlighted in yellow.
- `+` and `-` live in the Layers header. `-` deletes the active manual group
  after confirmation.
- `Clear` group does not require confirmation because undo is available.
- Generate JSON is allowed while Edit is active and exports the current state.

## Manual Picking

- Manual edit modes:
  - `Select Subtree`
  - `Select Bones`
- Default edit mode is `Select Subtree`.
- `Select Bones` uses single clicks only. No Shift range, box select, or batch
  selection in this iteration.
- The UI and export label the picked unit by child joint name.
- In `Select Subtree`, adding a subtree expands it into explicit child-joint
  tokens so individual bones can later be removed.
- `Alt` remove follows the current edit mode:
  - subtree mode removes the subtree from the active manual layer;
  - bone mode removes the clicked child joint from the active manual layer.
- Removing from a manual layer reveals the lower layer or base assignment.
- If no group is in Edit, clicking bones is inspect-only and never mutates
  groups.
- Remove the old `Ctrl+click` subtree inspect path so Wind Preview has one
  obvious picking model.
- The viewport color must update immediately after every edit click and match
  the final JSON result.

## Undo, Autosave, and Logging

- Undo/redo covers manual edits only:
  - add group
  - delete group
  - clear group
  - add bones/subtrees
  - remove bones/subtrees
  - group edit-mode changes
- Source load, source switch, and external import are not undoable.
- Undo history limit is 50 actions.
- Shortcuts:
  - `Ctrl+Z` undo
  - `Ctrl+Shift+Z` redo
- Undo/redo are shortcut-only in the UI and appear in the viewport shortcut
  hints when history is available. Do not add visible undo/redo buttons to the
  Wind Preview right panel.
- Autosave stores the last global Wind Preview session in GUI settings:
  - last source
  - source mode
  - selected base mode
  - manual layers
  - group edit policies
- Autosave restores state only. Undo/redo history starts empty after restore.
- Skeleton fingerprint is joint names plus parent indices, not positions.
- Fingerprint mismatch resets the restored state with a warning.
- Successful restore shows a small status notice, not a modal dialog.
- Generate JSON does not clear autosave/session state.
- Log every manual edit compactly: action type, group, edit mode, and
  added/removed/overridden counts. Do not log full bone-name lists by default.

## Generate JSON

- The right panel contains an export block near the bottom:
  - Output Path
  - Browse
  - Generate JSON
- Output Path is derived with the existing SpeedTree XML wind JSON path rule and
  is editable by typing or `Browse`.
- Confirm before overwriting an existing JSON file.
- Wind Preview writes the same Dynamic Wind JSON schema as the existing
  SpeedTree XML generation path. No new schema or metadata is introduced in
  this iteration.
- If any final joint/segment is unassigned after flattening the stack, Generate
  JSON fails loudly with count and a short sample.
- Wind Preview Generate JSON reports status and the written path inside Wind
  Preview only. It does not mutate the main window output path.

## UI Requirements

- Match the compact style of existing preview windows.
- Wind Preview opens taller than the shared preview default and uses the midpoint
  between minimum and maximum right-panel width as its default panel width.
- Current accepted quality bar: the panel should feel like a compact vertical
  tool surface, not a wide form. Icon-only actions stay small, primary dropdowns
  stay readable at minimum width, and layer rows are dense but visibly clickable.
- Validate UI polish with direct Qt screenshots at minimum width, default width,
  and short-window/global-scrollbar states before the packaged gate.
- Use one global scroll for the whole right panel.
- Inside that global flow, Layers has its own local scroll and a draggable
  bottom resize handle. The handle changes only the Layers scroll height, so it
  must keep working even when the global right-panel scrollbar is visible.
- Source, Grouping, Edit, Layers, and Generate JSON stay in that vertical order.
- Group rows must be thin enough that long names/counts do not overflow the
  right panel.
- Layer rows are compact panels with a color chip, final group label/count, and
  per-layer Auto options inside the row rather than detached at the far edge.
- Functional blocks use subtle dividers and compact labels.
- All operator-facing controls need short tooltips. Sliders and numeric fields
  must state what lower and higher values do.
- Dropdowns must visibly highlight on hover/focus.
- Do not use visible instructional paragraphs in the UI.
- Keep group stack order bottom-up. `+` inserts above all existing layers.

## Main Risks

- Manual overrides can make the visual group color differ from lower base groups.
  The viewport must always show the final winning assignment.
- External skeleton import must not load high-poly mesh geometry into the
  viewport.
- Missing skeleton coverage must fail loudly instead of producing partial wind
  JSON.
- Viewport stability fixes must not become Wind-only code paths.

## Implementation Shape

1. Keep the shared viewport seam first: add only public shared viewport methods
   needed for bone colors, shortcut hints, and selection state.
2. Introduce a Qt-free wind group stack model that can flatten base groups plus
   manual override layers into final Dynamic Wind groups.
3. Route XML Generator Groups and Auto Hierarchy through the same base-group
   interface.
4. Add manual layer UI on top of the shared group stack model.
5. Add Wind Preview Generate JSON using the existing Dynamic Wind JSON writer
   and output path derivation.
6. Add External Skeleton source loading through worker-process adapters for FBX
   and USD skeleton-only payloads.
7. Add focused regression coverage for flattening, picking, autosave
   fingerprint behavior, JSON coverage failure, and external skeleton import
   diagnostics.
8. Run the packaged Qt GUI build gate:
   `.\scripts\build_qt_gui_exe.cmd -Package`.

## Deferred

- Manual group rename.
- Manual group reorder.
- Shift/range/box selection.
- `.usdz` skeleton import.
- Helper/end-joint name heuristics.
- Persisting per-file camera state.
- Cross-source manual edit transfer by joint names.
- Syncing Wind Preview output path back into the main window.
