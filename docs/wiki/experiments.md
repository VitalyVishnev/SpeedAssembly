# Experiments

Rejected, superseded, and partially validated work. Current contracts live in
[decisions.md](decisions.md); active gaps live in [known-bugs.md](known-bugs.md).

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
