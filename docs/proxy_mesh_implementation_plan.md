# Proxy Mesh Implementation Plan

## Step 1. Prepare Proxy Backend Skeleton

Create the minimal code path for proxy generation without implementing the real simplification yet.

- add a dedicated proxy worker/service
- define shared proxy input data from `CanonicalTreeModel`
- define proxy output metadata
- add a separate `Generate Proxy Mesh` action in the UI
- add a placeholder mesh path so the pipeline can run end-to-end before the real method exists

Done when:

- the backend can be triggered independently
- the UI has a visible proxy action
- a placeholder proxy result can be produced and passed through the pipeline

## Step 2. Build A Real 3D Preview Viewport

Implement a proper interactive viewport for polygon meshes.

- use a ready-made rendering path instead of writing rasterization from scratch if possible
- render a real mesh, not a static image
- support orbit camera around the object center
- support mouse drag rotation
- support mouse wheel zoom
- use a simple Matcap-style material
- keep the viewport responsive and lightweight
- make the viewport suitable for repeated iteration, but not a full DCC scene editor

Done when:

- the viewport opens inside the Qt shell
- the camera can orbit the model center
- the camera can zoom in and out
- the mesh is rendered smoothly and interactively
- the viewport can display the current placeholder mesh before simplification exists

## Step 3. Add Proxy Preview UI

Make the viewport usable for iteration.

- place the viewport in a dedicated proxy preview window or panel
- add only the controls needed for iteration
- show method name, budget mode, and key metrics
- keep the UI simple and readable
- allow preview regeneration on user action

Done when:

- the user can open the proxy preview from the Geometry tab
- the preview shows a real 3D mesh
- the visible controls are enough to inspect the current proxy result

## Step 4. Implement Separate Proxy Export

Write the proxy as its own USD file.

- export to a separate `_proxy.usda`
- keep the proxy file sibling to the main USDA output
- keep the proxy export deterministic
- do not merge the proxy into the main skeletal export
- keep preview and export using the same generated mesh

Done when:

- proxy export writes a real file
- the file imports in Unreal as a static mesh
- the proxy asset is separate from the main tree asset

## Step 5. Implement The First Real Simplification Method

Build the first usable proxy algorithm end-to-end.

- start with `density_field`
- generate kernels from repeated foliage or small vegetation elements
- scatter kernels through the tree using canonical instance data
- accumulate them into a sparse density field
- extract a surface
- simplify with QEM

Done when:

- the placeholder proxy is replaced by a real proxy result
- the proxy still stays within budget
- the result is visually inspectable in the viewport
- the exported proxy matches the preview

## Step 6. Add The Simplification Backend

Choose and integrate the QEM reducer that will be used by the first method.

- research a usable QEM backend for Python and Windows packaging
- verify that the backend is easy to ship in the current environment
- verify that it is stable on real proxy meshes
- keep the choice replaceable if packaging or quality is poor

Done when:

- QEM runs inside the proxy pipeline
- simplification is visible in the viewport
- the proxy can be reduced to the target budget without breaking the silhouette

## Step 7. Validate In Unreal Engine

Check the result on the actual target importer path.

- import the proxy asset into UE 5.7.x
- inspect the mesh as a static mesh
- check if the silhouette and volume are useful for distance-field and shadow testing
- compare at least one sparse tree and one dense tree

Done when:

- UE imports the exported proxy successfully
- the proxy is useful enough to continue iteration

## Step 8. Add Alternative Methods

Keep research branches for other proxy strategies.

- `triangle_soup`
- `sphere_blob`
- `df_emulation`

These should be compared after the first working method exists.

Done when:

- the codebase can switch between methods
- each method can be tested against the same tree input

## Step 9. Tighten Controls After The First Pass

Reduce the UI and keep only what is actually useful.

- decide whether the long-term control should be triangle budget, density budget, or both
- remove controls that do not help the iteration loop
- keep the viewport and export path stable

Done when:

- the feature is easy to use
- the controls are not redundant
- the proxy generation path is still deterministic

