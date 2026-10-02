# Experiments

Rejected, superseded, and partially validated work. Current contracts live in
[decisions.md](decisions.md); active gaps live in [known-bugs.md](known-bugs.md).

## Reparenting a populated viewport dialog into the main shell

Status: Rejected; reproduced with Qt 6.11 on Windows.

`configure_preview_dialog` previously called `dialog.setParent(owner, Window)`
after constructing its QOpenGLWidget. The owner emitted Hide, surface destruction,
HWND changes, surface creation, and Show, changing from RasterSurface to
OpenGLSurface. This was window recreation, not a process crash. Creating the
preview's native window independently and assigning a QWindow transient owner
keeps the shell raster surface and HWND intact while preserving WindowModal
blocking and reopening. Do not hide/show the shell to work around this lifecycle.

Qt documents native-window recreation on dynamic OpenGL widget insertion in
[QOpenGLWidget limitations](https://doc.qt.io/qt-6/qopenglwidget.html#limitations-and-other-considerations).

## Future external rig conversion mode

Status: Deferred, Unverified.

An arbitrary skinned FBX/USD input needs explicit policies for joint mapping,
bind-pose ownership, weights, axes/units, topology, materials, and loss
reporting. Current FBX support is read-only diagnostics. Viewport transforms
must not enter a conversion model.

## Python ufbx wrappers

Status: Rejected.

`pyufbx` returned corrupt geometry; an upstream-named wrapper crashed reading
the Alder skeleton, recorded as CR-015. Use vendored ufbx C through the local
CPython bridge.

## Shared-memory FBX material partition

Status: Superseded.

Shared-memory buffers and worker lifecycle exceeded the work. `numpy.frombuffer`
now classifies existing packed buffers in-process. Big Spruce improved from
0.03242 s to 0.00570 s for 58,463 faces. Keep scalar work below 50,000 faces.

## Python-list topology for huge FBX payloads

Status: Rejected.

`list[int]` materializes tens of millions of Python objects and a multi-GB
transient peak. The ufbx bridge writes packed buffers directly.

## Outer parallel Boolean execution

Status: Rejected on Windows spawn/oneTBB.

Independent components matched sequential output exactly, but transport and
oneTBB oversubscription lost. At 37 cuts, sequential was 6.81-6.88 s, two
processes 6.99-7.34 s, four 7.92-8.05 s; RSS rose to 382-403 MiB and
577-751 MiB. Same-shell cuts are always sequential. Revisit only after a
zero-copy boundary or different backend, with speed, RSS, exact-result, and
packaged-stability gates.

## Connectivity-first Manifold Boolean fracture

Status: Production integrated; broader real-tree and UE validation open.

Detailed Cuts isolate a connected branch shell, close valid degree-two loops,
then split it with a deterministic noisy triangular cutter. `manifold3d`
provenance removes temporary closures, retains caps, and transfers source UVs,
colors, materials, and skinning. Multi-cut runs reuse prepared analysis;
same-shell cuts run sequentially with distinct cap provenance.

Key retained results:

- Dominant cut-bone ownership selects one crossing shell; equal evidence fails.
- Binding-gated automatic ownership removed 422 foreign Big Spruce faces. A
  12-run matrix checked 318 cuts and 133,764 face assignments with no
  cross-subtree violations.
- Actual cutter surfaces, not extended projections, classify Detailed Repeated
  Parts. Flat planes moved 26 parts, cutter surfaces 88, and unjustified edge
  extension 230.
- Prepared Big Spruce regeneration reached a 0.835 s five-run median; fresh
  preview processes were 3.30-3.47 s. These are local measurements.

## Face-sampled preview simplification

Status: Rejected.

Sampling made disconnected clouds and holes, including after fracture caps.
Use shared `fast-simplification` QEM after exact clipping.

## Fracture Preview Qt thread

Status: Superseded.

Native crashes required isolated preview workers.

## Packaged sidecar worker

Status: Superseded.

The packaged app reuses its own executable in worker mode. Worker dispatch must
remain before Qt bootstrap.

## Normalizer and USDA micro-optimizations

Status: Rejected beyond retained simple changes.

Single-pass UV rewrite, local child-scan rewrites, larger authoring chunks,
`StringIO`, C-level maps, and NumPy identity factoring produced no stable
material gain on Big Spruce. Keep split UV work, direct formatting, small
identity/string and low-cardinality integer caches. Profile representative
end-to-end work before adding a branch.

## Automatic trunk refinement and synthetic fill

Status: Superseded.

Hierarchy refinement and spatial face splitting shredded simple trunks. Auto
fracture now detaches only stump, independent stems, and length-ranked branch
bases; manual cuts handle trunk or mid-segment cuts. Candidate exhaustion clamps
with a diagnostic.

## Noisy geometry as automatic-cut validation

Status: Rejected.

Noisy preflight rejected Big Spruce's stump and long branches, then chose six
micro-branches. Plan from skeleton and operator settings. Noise affects only
resolved Cut Surfaces; ownership follows skeleton attachment.

## Largest USD skeleton autoselection

Status: Rejected.

Joint count is a hidden heuristic. Enumerate USD Skeleton prims and require
operator selection; text fallback may parse them but must not choose by size.

## UE Skeletal Mesh reorientation without reimport

Status: UE 5.7 in-place path validated; duplicate route superseded.

Reorienting only a Skeletal Mesh changes editor display but not Dynamic Wind:
UE reads the assigned Skeleton Asset reference pose. The current UE 5.7 Asset
Action updates selected meshes and their dedicated Skeleton Assets. It refuses
shared Skeleton Assets, performs a transient leaf rename to force reference-pose
rebuild, restores the name in a second commit, and validates exact Mesh/Skeleton
local-pose agreement.

SpeedTree forks use Reference Skeleton order: lowest-index child continues the
generator line; other children start lines. Each bone +X follows that line;
leaves use their incoming segment, coincident terminals inherit a usable line,
and transported parent +Y controls roll. Runtime wind and branching/terminal
orientation were manually confirmed in UE 5.7.

Limits: sockets, physics frames, authored animation, and reimport are not
compensated. Scripts: `scripts/ue57_fix_selected_foliage_bones.py`,
`scripts/ue57_make_foliage_asset_action_command.py`, and the console variant.

## Proxy collision from simplified viewport mesh

Status: Rejected.

Density/QEM output has crown geometry but loses base-mesh skin ownership.
Fitting would need a new heuristic and can repeat multi-stem width errors. Keep
the compact stem-joint/base-point source retained by preview generation.

## Reduce high-resolution Proxy QEM input

Status: Rejected.

On the 28M sample, a prepass reduced a 256 grid from 1.65M to 0.93M triangles
but slowed QEM from 2.25 s to 3.56 s. Aggressiveness 10 was also slower than 7
at 512, 9.30 s vs 8.98 s. Voxel-strip merging risks T-junctions. Keep direct
QEM plus dense-grid/quadratic NumPy acceleration.

## Inherited deformation at branch attachments

Status: Implemented behind Skinning Quality; UE 5.7.x Part validation open.

At a child attachment, inherit the parent's influence vector, then blend to
child influence. Quality 1 is rigid; 2 uses the established two-weight collar;
3/4 recursively inherit and clamp to three/four slots. In quality 2, the first
20% reaches rigid parent and remaining 80% transitions parent to child. Parts
receive the same distribution at their instance position. Earlier Base Mesh
quality 2-4 tests passed; Part widths and runtime cost remain unverified.

## `TungTungTung.fbx` after rigid PCG wind

Status: FBX inspected; PCG cause Unverified.

The Blender FBX has eight distributed bones, one 5,218-vertex mesh, eight
clusters, no unweighted vertices, at most four influences, coherent main-chain
+X, and no exact source-up singularity. It disproves all-root, coincident-pivot,
and shared-bind-matrix hypotheses. Normalize weights in DCC: 1,733 vertex sums
are outside 1.0 by >0.01, range 0.9340-1.0252. Confirm terminal axes and replace
generic names before JSON becomes durable.

Next test: compare direct placement and PCG using the same Skeletal Mesh and
wind data. If only PCG is rigid, capture component class, asset, Skeleton, and
Dynamic Wind data before changing FBX or grouping. Full audit:
[External Dynamic Wind Rigs](external-dynamic-wind-rigs.md).

## Dynamic Wind transform addressing budget

Status: Source-verified encoding/allocation; aggregate capacity estimate only.

Both local UE 5.7 and 5.8 trees allocate
`UniqueAnimationCount * MaxTransformCount * 2` transform records in
`Renderer/Private/Skinning/SkinningSceneExtension.cpp` (5.7:925, 5.8:1311).
Dynamic Wind defines eight directionality slices in
`Plugins/Experimental/DynamicWind/Shaders/Shared/DynamicWindCommon.ush`.
The multiplier two stores current and previous transforms, not two simulations.

`Shaders/Shared/SkinningDefinitions.h` encodes TransformBufferOffset in 22 bits
(5.7:80-90, 5.8:161-173), with offset checks in SkinningSceneExtension.h.
`2^22 / (8 * 2) = 262144` therefore estimates the aggregate bone budget for
densely packed Dynamic-Wind-only transform allocations. It is not an exact
universal scene limit: the encoded restriction is on allocation start offsets,
the final allocation can cross the range, other providers share storage, and
allocator holes affect offsets. UE 5.7's check also admits the unrepresentable
`2^22` boundary; UE 5.8's maximum correctly uses `2^22 - 1`.

This is separate from the wind dispatch limit
`sum(ceil(BatchBones / 64) * 8)` in DynamicWindProvider.cpp. Do not present the
dispatch-derived roughly 524k count as the complete scene budget. No runtime
overflow reproduction or link to the author's earlier bug has been established.

SpeedTree preparation guidance uses author-recommended bone counts, not a
guaranteed engine limit. The author also confirmed that Leaf Flip does not
survive the tested XML workflow; its mechanism remains unverified.

## Nanite Assembly part sizing budgets

Status: Source-verified in local UE 5.7 and 5.8; performance advice needs scene profiling.

Public guide: `docs/user/wiki/choosing-assembly-parts.md`, adapted from the
author's `nanite_assembly_foliage_guide.html`. Keep public Wiki separate from
this engineering memory.

Source navigation in both engines:
- `Source/Developer/NaniteBuilder/Private/NaniteAssemblyBuild.cpp` rejects final
  transform counts above `NANITE_HIERARCHY_MAX_ASSEMBLY_TRANSFORMS` (65535).
- `Source/Runtime/Renderer/Private/Nanite/NaniteShared.cpp` defaults
  `r.Nanite.MaxVisibleAssemblyParts` to `256 * 1024`.
- `Shaders/Private/Nanite/NaniteClusterCulling.usf` requests three transform
  records with active skinning, otherwise one, then checks capacity.
- `Shaders/Private/Nanite/NanitePrintStats.usf` prints
  `AssemblyTransformsWriteOffset` as Assembly Parts / Visible. This is requested
  transform demand, including overflow requests, not unweighted part count.

The roughly 87k fully active part estimate is distinct from Dynamic Wind bone
storage and dispatch limits. A 70-75% reserve and cluster sizes are authoring
recommendations, not engine guarantees. Test actual placement density/motion.

## Dynamic Wind runtime overview

Status: Source-verified in local UE 5.8.2; not a new runtime validation.

Public guide: `docs/user/wiki/how-dynamic-wind-works.md`, registered beside
Choosing what to instance. The article explains mechanisms, dependencies, and
failure causes; procedural setup belongs in the workflow guides. Engine paths
below are relative to `Engine/`.

- `Plugins/Experimental/DynamicWind/Source/DynamicWindEditor/Private/DynamicWindImportData.cpp`
  matches JSON names against the mesh RefSkeleton and groups same-group ancestry
  under one chain origin. Same-group forks aggregate both paths into one count;
  chain-length data sums differences of parent/current local-pose translations,
  so do not describe it as a verified physical branch length.
- `DynamicWind/Private/DynamicWindSkeletalData.cpp` ramps dual influence by chain
  index, not distance. `Shaders/DynamicWindEval.usf` applies influence to branch
  motion, not trunk sway; Ground Cover removes final branch-height attenuation.
  Zero branch influence still inherits ancestor motion. Sine mode bypasses
  groups, influences, pivots, and amplitude; it only tests provider/render motion.
- `DynamicWind/Private/DynamicWindProvider.cpp` reads the assigned Skeleton Asset
  pose and keys bone data by Skeleton GUID plus bone-map mode. Distinct metadata
  on meshes sharing this key overwrites the same entry. Runtime reproduction is
  still open; see Known Bugs.
- `DynamicWind/Private/DynamicWindData.cpp` provides eight shared yaw slices,
  GPU-only transforms, and no animation-specific bounds. This is not an
  independent phase/simulation per placed instance or a CPU collision update.
- `DynamicWind/Public/DynamicWindParameters.h` contains SimulationCenter/Extents,
  but the provider does not forward them to the evaluation shader. Stock noise
  uses time and skeleton-relative positions, not a per-instance world wind field.
- The six `DynamicWind.*` console variables are defined in Provider/Subsystem.
  Enable is read-only and gates subsystem creation; rate-of-change smooths the
  amplitude override, not arbitrary Blueprint parameter updates. Renderer
  provider/cutoff defaults live in `SkinningSceneExtension.cpp`; instanced debug
  drawing lives in `SkinnedMeshDebugView.cpp`.

Paths abbreviated as `DynamicWind/Private` or `DynamicWind/Public` above are
inside `Plugins/Experimental/DynamicWind/Source/`.
