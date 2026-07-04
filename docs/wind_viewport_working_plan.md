# Wind Viewport Working Plan

Status: Planned.

## Goal

Add a separate wind preview window, modeled after Proxy Preview and Fracture Preview, that shows:

- the full tree from XML
- the skeleton overlay
- XML-derived wind groups in distinct colors
- a right-side group list with an obvious color-to-group mapping

This first version is read-only. It is for inspection, not editing.

## V1 Contract

- The window uses XML as the only source of truth.
- The preview fails loudly if the XML does not provide usable wind generator labels.
- Group order is from root/trunk toward finer branches, following tree growth.
- The viewport shows the whole tree with instanced branches from XML only.
- The skeleton is drawn over the geometry.
- The right panel lists the detected groups.
- Each group has a stable color chip and label in the list.
- Clicking a group row highlights that group.
- `Ctrl+click` on a bone selects the subtree rooted at that bone and highlights it in the preview.
- Selection does not mutate group membership in V1.
- The preview does not export wind JSON.
- The preview does not persist manual group edits.
- The preview does not import FBX or USD skeletons in V1.

## Deferred

- Automatic group generation when XML groups are missing
- Manual group editor actions such as add, remove, rename, reorder, or split
- External skeleton import from FBX or USD
- Wind JSON export from this preview window

## First Pass Implementation Shape

1. Reuse the shared preview shell used by Proxy and Fracture.
2. Add a wind preview source adapter that builds a viewport scene from XML skeleton data.
3. Reuse the shared OpenGL viewport for tree and skeleton rendering.
4. Build a right-side group list that mirrors the preview colors.
5. Wire `Ctrl+click` bone selection to subtree highlighting only.
6. Add focused regression tests for the preview contract and selection behavior.

## Main Risks

- The biggest risk is mismatching visual selection with actual subtree membership.
- The second risk is accidentally turning the inspector into a hidden editor.
- The third risk is relaxing the fail-loudly rule and silently inventing wind groups.

## Future Follow-Up

After V1 is stable, the next layer can add:

- automatic group generation as an explicit fallback mode
- a manual group editor with `+` to seed a group from a clicked bone
- import of external skeletons from FBX or USD for non-SpeedTree workflows

