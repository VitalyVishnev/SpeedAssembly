# Proxy Mesh Feature Overview

## Concept

This feature adds a separate proxy-mesh companion pipeline for tree assets.
It is not a new export mode.
It is an auxiliary asset, like Wind JSON, except the output is USDA geometry instead of JSON.

The goal is not visual parity with the source tree. The goal is a compact static proxy that:

- preserves the broad silhouette of the tree
- keeps the overall foliage volume stable
- produces usable input for Distance Fields and low-cost shadowing
- stays within a strict polycount budget
- can be inspected interactively before export

The main tree export remains the source of truth for the actual vegetation asset.
The proxy exists only as a companion asset for rendering, shadows, and distance-field evaluation.

## Fixed Contract

- The proxy is a separate static mesh USDA asset written to its own file.
- The proxy file is always a sibling of the main USDA output when an output path exists.
- The proxy file name uses the main USDA stem plus the `_proxy` suffix.
- If no output path is set, proxy export follows the same fallback behavior as Wind JSON generation and derives the file name from the input source path.
- The proxy is derived from `CanonicalTreeModel` source-normalized data, not from raw XML traversal.
- The proxy uses repeated-part instancing as input. All `LeafReferences` instances are part of the proxy input set.
- The proxy does not pre-cull repeated parts just because they are small.
- The proxy output is one polygonal mesh prim inside one USD(A) file.
- The proxy does not author skeletons, `PointInstancer` data, skeletal binding, or Nanite Assembly root schemas.
- The proxy is geometry-only for v1; no source materials are translated into the proxy file.
- The proxy preview must render the same generated mesh that is exported.
- Preview and export must use the same mesh result.
- The proxy must fail loudly if it cannot safely build the mesh.
- There is no fallback proxy geometry.
- Proxy generation is a companion workflow, not a separate `ConversionMode`.
- Proxy generation should run in a dedicated worker process when possible.
- If parallel execution is unavailable, it may fall back to a sequential worker path.

## Methods Under Investigation

The feature should keep multiple proxy-generation strategies available while the
implementation is being tested against real trees.

### `density_field`

- build local kernels for repeated foliage and small vegetation elements
- scatter kernels through the tree using the canonical instance data
- accumulate them into a sparse density field
- extract a surface
- simplify the result with QEM

This is the primary candidate for the first working method.

### `triangle_soup`

- aggressively simplify the base mesh and foliage geometry
- useful as a baseline or debug reference
- likely too noisy for dense foliage if used as the final method

### `sphere_blob`

- scatter spheres or ellipsoids over the canopy and merge them
- useful for quick volume approximation
- good as a fallback or comparison method

### `df_emulation`

- approximate a distance-field-like proxy by building rough geometry first and smoothing it
- useful as a research branch
- not the first shipping method

## Simplification Model

After surface extraction, proxy reduction should not be uniform across the whole mesh.
The simplifier should treat the proxy as zones with different importance:

- `shell`
  - keep the outer silhouette readable
  - simplify gently
  - preserve the overall outline
- `interior`
  - collapse aggressively
  - remove noisy internal triangles
  - prioritize volume stability over local detail
- `outside`
  - remove isolated or weak features first
  - do not spend budget on geometry that does not help silhouette or volume

The simplification budget should be driven by either:

- target triangle count
- target density / voxel size

Those controls are not interchangeable, but both are useful for iteration.
The final UI may eventually hide one of them if it proves redundant.

## UI Contract

### Geometry Tab

- The `Geometry` tab contains a `Proxy Mesh` section.
- That section has a `Preview Proxy Mesh` button.
- That section also has compact quick controls for method and the chosen budget mode.
- The default triangle budget is `5000`.

### Action Row

- The export action row keeps `Generate Wind JSON`.
- The export action row also gets `Generate Proxy Mesh`.
- `Generate Proxy Mesh` saves the proxy next to the main USDA file.

### Preview Window

- `Preview Proxy Mesh` opens a separate window.
- The preview window is viewport-first: the viewport fills the whole window.
- The preview window also contains settings.
- During development, the preview window exposes the selected method, triangle budget or density budget, and method-specific tuning parameters.
- Later, the long-term operator surface may be reduced to method plus a single budget control, but that is not the current development contract.
- Changes to preview settings regenerate the mesh on mouse up, not on every keystroke or slider move.
- The preview window auto-generates a proxy when it opens.
- The preview window always frames the tree so the full object fits in view at open.

### Camera Controls

- Left mouse drag rotates the camera.
- Mouse wheel zooms.
- The camera always rotates around the center of the tree.
- The camera target does not drift away from the tree center.
- The initial view is framed so the whole proxy fits inside the viewport.

## Scope For The First Iteration

The first iteration should end when all of the following are true:

- the shell has a working proxy preview viewport
- the viewport can display a generated proxy mesh with a simple Matcap material
- the viewport opens from `Preview Proxy Mesh`
- the proxy settings are editable in the preview window
- the preview updates on mouse up when settings change
- at least one proxy-generation method works end-to-end
- the generated proxy can be exported as a separate USD(A) asset
- the proxy can be imported into Unreal Engine as a static mesh and inspected there

The first iteration does not need the final best algorithm.
It only needs one stable method plus a preview loop strong enough to iterate visually.
The method itself remains under investigation.

## Data Contract

- The proxy starts from `CanonicalTreeModel`.
- The proxy must include all repeated-part instances from `LeafReferences`.
- The proxy may reuse resolved prototype payloads already available in the canonical model.
- The proxy keeps the main tree's overall stage-space scale and pivot behavior.
- The proxy must not invent fallback geometry if source facts are insufficient.
- If proxy generation cannot safely resolve the needed tree facts, it fails loudly and reports the missing assumption.

## Implementation Order

### 1. Define The Proxy Contract

Lock the non-negotiable contract:

- separate USD(A) file
- sibling path beside the main USDA output
- `_proxy` suffix
- CanonicalTreeModel input
- all repeated parts included
- no pre-culling by size
- no skeleton authoring
- no `PointInstancer` output
- no fallback geometry
- same preview mesh as export mesh
- not a separate export mode

### 2. Keep The Method Pluggable

Do not hardcode a single proxy algorithm into the contract.
The UI must support method selection and method-specific tuning while the feature is under development.

The current contract only requires:

- a method selector
- a final triangle budget control or equivalent density control
- method-specific dev parameters while the feature is being investigated
- the same preview/export mesh for any chosen method

### 3. Build The Proxy Preview Window

The preview window is the main inspection surface.
It opens from `Preview Proxy Mesh` in the `Geometry` tab.
It auto-generates on open.
It frames the whole tree on open.
It regenerates on mouse up when settings change.

Viewport rules:

- black background
- Matcap-style look
- viewport fills the window
- orbit camera around the tree center
- left-drag rotate
- wheel zoom
- no scene clutter
- no ambient occlusion
- no heavy lighting stack

### 4. Add The UI Controls

The UI has two layers of controls:

- `Geometry` tab quick controls:
  - method
  - triangle budget or density budget
  - `Preview Proxy Mesh` button
- preview window controls:
  - method
  - triangle budget or density budget
  - method-specific tuning parameters while development continues

The long-term user surface should converge toward method plus a single budget control.
That is not a requirement for the first iteration.

### 5. Add The Export Action

The export action is separate from the preview action.
It lives beside `Generate Wind JSON`.
It saves the proxy as `<main stem>_proxy.usda` next to the main USD file.

Export behavior:

- if an output path is set, use that path to derive the sibling proxy file
- if no output path is set, follow the same fallback behavior as Wind JSON generation
- keep the proxy export deterministic
- keep the proxy file separate from the main USD file
- do not merge proxy export into the main tree export

### 6. Keep The Generation Result Shared

The preview mesh and the export mesh must be the same generated result.
There is no preview-only approximation and no export-only refinement.

### 7. Validate In Unreal Engine

The first validation gate is deliberately minimal:

- preview opens and renders the proxy
- proxy export succeeds
- UE imports the exported proxy as a static mesh

Later validation can add distance fields, shadow checks, and method comparison.

### 8. Record Research Questions

The implementation should explicitly leave the following as research items until measured:

- best QEM backend for Python packaging and Windows build stability
- whether `fast-simplification` is good enough for the first release path
- whether `meshoptimizer` gives better long-term control
- whether Open3D is useful as a reference or fallback only
- whether a sibling prim inside a stage is safe enough to revisit later
- whether the final user surface should keep both triangle and density controls
- which proxy method fits sparse trees, dense crowns, grass, and moss best

## Success Criteria

The feature is complete when:

- the proxy is deterministic for the same input and settings
- the proxy preview and exported file match
- the UI remains responsive during generation
- the exported proxy imports in UE 5.7.x as a static mesh
- the proxy is materially cheaper than the source tree
- the proxy still reads as the same tree silhouette
- the proxy path remains sibling to the main USDA path
- the proxy remains a companion asset, not a new export mode

## Deferred Research

The following remain research items, not contract blockers:

- best method per vegetation type
- whether the proxy should later get fewer visible controls
- which method-specific tuning parameters deserve to stay long-term
- the best QEM backend or equivalent simplification backend
- later distance-field and shadow tuning across real samples
- whether the proxy exporter should ever be merged into the main USDA stage instead of staying a sibling asset
