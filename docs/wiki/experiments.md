# Experiments

## Experiment: Shared-memory process pool for FBX material partition

Status: Superseded by bounded zero-copy NumPy.

The former large-payload path copied face counts, indices, and colors into
three shared-memory blocks, spawned workers, then merged face buckets. Process
startup, full-buffer copies, cleanup, and an infrastructure fallback made the
module substantially more complex than the work required.

The replacement views the existing `GeometryBuffer` arrays with
`numpy.frombuffer` and classifies bounded face chunks in-process. On the real
Big Spruce topology (58,463 faces, 175,389 corners), the exact result improved
from 0.03242 s to 0.00570 s, or 82.4%. Keep the scalar path below 50,000 faces.

## Experiment: Bulk `FbxMesh.GetPolygonVertices()` for huge FBX topology

Status: Rejected for memory stability.

The Autodesk binding returns a Python `list[int]`, not a zero-copy numeric
view. A 14.2-million-triangle payload would materialize 42.5 million Python
integers in addition to the final packed index array, creating a multi-gigabyte
transient peak. The production path instead keeps per-face SDK index reads,
reduces Python loop count, and vectorizes only indexed UV expansion in bounded
chunks. Reconsider only if the binding exposes a real buffer/pointer contract.

## Experiment: Outer parallel execution for independent Boolean components

Status: Rejected on the current Windows spawn/oneTBB runtime.

The available parallel unit is one connectivity component, not one arbitrary
cut. Cuts on the same shell remain sequential. Big Spruce provided 12 and 37
independent Boolean component groups for the measured 11- and 36-branch plans
with a stump.

Three prototypes reused the production Boolean implementation: per-cut process
jobs, workers initialized from one read-only source context, and larger
per-worker batches initialized from the model plus analysis cache. Every
returned parent/child/cutter `MeshData` and diagnostic value matched the
sequential result exactly. The prepared full 36-branch session serialized to
about 27.6 MiB and took about 0.7-0.8 s to pickle/unpickle per worker, before
native work.

End-to-end-favorable measurements still failed the 25% gate. At 37 independent
cuts, sequential took 6.81-6.88 s. Two spawned processes took 6.99-7.34 s
across three batched runs; four took 7.92-8.05 s. At 12 cuts, sequential took
2.78 s versus 4.00 s with two processes. Estimated child peak RSS was about
382-403 MiB for two processes and 577-751 MiB for four. A shared-memory
thread prototype also failed: 2/4/8 threads took 6.96/6.85/7.17 s against a
6.81 s sequential baseline.

Keep the sequential backend. Windows process startup, model transport, result
transport, and oneTBB oversubscription erase the independent-cut gain. Revisit
only after a material runtime change such as a zero-copy worker boundary or a
different Boolean backend; do not retain a dormant parallel subsystem.

## Experiment: Connectivity-first Manifold Boolean fracture

Status: production integrated; broad real-tree and UE runtime validation remains open.

The `boolean-prototype` command isolates one whole connected branch before any face-ownership split, closes its oriented boundary loops, and splits it with a closed triangular-lattice cutter displaced by one-sided deterministic fractal noise. `manifold3d` provenance removes temporary source closures while retaining cutter-derived caps. Requested amplitude is uniformly limited before the next physical terminal, branch, or bend above `Max Bend Angle`. Exact source-triangle provenance transfers UV0/UV1, colors, material sections, and skinning; caps receive planar UVs and nearest boundary-ring attributes. Its viewer can regenerate the same source in place with editable cut/noise controls while the deterministic seed remains fixed. The synthetic open-cylinder case, Simple Tree `bone_086`, and Big Spruce `bone_508` pass locally.

The `boolean-multi-prototype` command prepares source analysis/triangulation/connectivity once and assembles untouched faces, parent stubs, and detached branches by Fracture Plan ownership. Independent components build separately. Same-shell cuts split their current parent region sequentially with distinct cap provenance; this covers the real SimpleTree stump-plus-branch case without overlapping geometry. Structural `auto_stem_length` pieces reuse already disconnected source shells. Collision and export remain downstream consumers; any external process pool remains separate work.

Big Spruce `bone_033` exposed a disconnected descendant twig crossing the same
plane with three transition faces owned by the cut bone. The production selector
now chooses the unique component with dominant cut-bone evidence and leaves the
twig intact in its child piece. A local matrix covering 7/11/19/37/64 requested
branches, height bias from -1 to +1, stump, and separate-stem variants completed.

Big Spruce profiling showed that the former `select_component` timing mostly measured repeated planning rather than component selection: two `plan_fracture` calls consumed about 2.9 s under `cProfile`, while `_select_component` itself consumed about 35 ms. A prepared one-cut session reduced repeated `bone_508`, Density 8 regeneration to a 56 ms median. The shared planner owner lookup reduced the normal 11-cut Big Spruce plan from 122 ms to 90 ms and a 64-cut stress plan from 1695 ms to 481 ms. The sequential 11-cut Big Spruce multi session at Intensity 20 / Density 8 prepared in about 1.31 s and regenerated in about 0.88 s locally. These are local measurements, not cross-machine guarantees.

Exact-site/result reuse reduced adding a Big Spruce stump to an already built 11-cut session to about 353 ms of replan/slicing plus 99 ms for the new stump Boolean; the 11 unchanged branch results were reused. On SimpleTree, a four-cut plan containing a stump and branch on the same shell completed sequential geometry in about 192 ms locally.

After automatic branch cuts moved to physical segment positions, a 2026-07-24
Big Spruce pass at 11 cuts, Intensity 20, and Cut Detail 8 observed 5.60 s
preparation and a 1.70 s three-run regeneration median before optimization.
Caching face centroids per plan, using DFS ancestry intervals, prefiltering
segment cuts per source bone, hashing one prebuilt source-byte payload, reusing
the source material lookup, and skipping unused result-face normals reduced
preparation to a 1.49 s five-run median and regeneration to a 0.835 s five-run
median. Three fresh-process Fracture Preview runs completed in 3.30–3.47 s
(3.32 s median). The points/indices/normals/UV signature remained unchanged.
A per-cutter Perlin-gradient dictionary was measured, produced only a
noise-level improvement, and was removed.

The 2026-07-24 Big Spruce ownership reproduction found 422 parent-dominated
faces assigned to automatic child pieces even though none had skin influence
from the corresponding child subtree. They were disconnected sibling collars
whose centroids happened to project beyond another branch's cut plane. After
binding-gated ownership, a 12-run matrix across all three local SpeedTree
samples, 7-64 requested branches, 15-80% cut offsets, both height-bias
directions, stump, and separate-stem modes checked 318 automatic cuts and
133,764 assigned face observations with zero cross-subtree violations. The
exact reported Big Spruce settings retained 38 pieces and all 36 requested
automatic branches while reducing foreign parent-face assignments from 422 to
zero. A full Detailed Boolean build at Intensity 33.9, Cut Scale 0.64, and Cut
Detail 8 completed with 38 non-empty pieces and 37 cuts including the stump.

Detailed Repeated Part ownership was compared on the same 36-branch Big Spruce
case. The existing flat physical-bone planes moved 26 child-owned instances;
this is now the shared planner baseline. A maximum-amplitude plane moved 200,
while the existing triangular cutter surfaces supported 88 total parent-side
moves while preserving all 3,613 instances exactly once. Reusing the actual
cutter surface added about 0.155 s under `cProfile`; point-side work itself was
about 0.014 s. Extending a cutter from its nearest projected edge was rejected
because it moved 230 parts, including descendant pivots for which that spatial
calculation was not justified.

This page stores rejected, superseded, or otherwise non-current approaches that still matter because they explain why the present contract exists.

## Experiment: Preview simplification by deterministic face sampling

Status: Rejected

Context:
Face sampling was tested as a cheaper alternative to QEM for Proxy Mesh and
later reused in Fracture Preview, including after noisy clipping.

Outcome:
It produced disconnected triangle clouds and visible missing triangles. In
Fracture Preview it could break otherwise valid clipped and capped surfaces.

Keep:
Use the shared `fast-simplification` QEM backend for Proxy Mesh and Fracture
Preview. Simplify only after exact fracture clipping and cap construction.

Related files:
- `docs/raw/DECISIONS.md`
- `docs/wiki/known-bugs.md`

## Experiment: Fracture Preview on a Qt background thread

Status: Superseded

Context:
An earlier version used a Qt-owned background thread for Fracture Preview.

Outcome:
Process isolation replaced it after native crashes were observed.

Keep:
Use isolated worker processes for preview work that can fail natively.

Related files:
- `docs/raw/DECISIONS.md`
- `docs/raw/ARCHITECTURE.md`
- `docs/wiki/known-bugs.md`

## Experiment: Packaged sidecar worker executable

Status: Superseded

Context:
The packaged release briefly used a separate worker executable.

Outcome:
The current release reuses the main executable in worker mode instead.

Keep:
Worker commands must still stay before Qt bootstrap.

Related files:
- `docs/raw/DECISIONS.md`
- `docs/raw/troubleshooting.md`
- `docs/wiki/known-bugs.md`

## Experiment: Single-pass UV rewrite in the normalizer

Status: Rejected

Context:
Several normalizer micro-rewrites tried to collapse UV authoring into fewer passes.

Outcome:
The rewritten path was slower on the large `BigSpruce` sample.

Keep:
Keep the faster split path and profile real samples before changing it again.

Related files:
- `docs/raw/REFRACTOR_LOG.md`
- `docs/wiki/known-bugs.md`

## Experiment: Local loop and child-scan micro-optimizations in the normalizer

Status: Rejected

Context:
Several local binding, child-scan, and payload-precompute tweaks were tried on the hot path.

Outcome:
They did not produce a stable improvement on the large sample and were reverted.

Keep:
Prefer changes that remove duplicate XML work over clever local rewrites.

Related files:
- `docs/raw/REFRACTOR_LOG.md`
- `docs/wiki/known-bugs.md`

## Experiment: Push USDA authoring from one-third to one-half faster

Status: Rejected beyond the retained stdlib hot-path changes

Context:
After formatting reuse and cheaper equivalent scalar formatting passed the 30%
gate, further changes were tested against the same Big Spruce authoring model.

Outcome:
Larger array chunks and `StringIO` produced no stable gain. Two-pass C-level
maps were slower. NumPy identity factorization saved only about 26 ms, roughly
8% of the already optimized path, while adding dependency-sensitive arrays and
still falling short of 50%.

Keep:
Retain the simple identity/string caches, low-cardinality integer cache, direct
matrix formatter, and equivalent `%g` formatting. Do not add a NumPy authoring
branch or tune chunk sizes without a new representative profile showing a
material end-to-end gain.

Related files:
- `src/xml_to_usda/usda_authoring.py`
- `docs/wiki/architecture.md`

## Experiment: Automatic trunk-chain and synthetic fracture fill

Status: Superseded

Context:
Earlier automatic fracturing tried to reach the requested piece count by refining hierarchy joints and, when needed, splitting base faces spatially.

Outcome:
On simple trees this could shred one trunk section while leaving the upper tree intact. V1 replaces this with natural weak-point detachment only: stump, independent stems, and branch bases ranked by skeleton length plus optional height bias.

Keep:
Manual cuts remain the explicit escape hatch for trunk or mid-segment cuts. Automatic fill clamps with a diagnostic when safe branch candidates run out.

Related files:
- `src/xml_to_usda/fracture_service.py`
- `docs/wiki/decisions.md`

## Experiment: Noisy geometry as an automatic cut validator

Status: Rejected

Context:
Noisy Cut preflight rejected candidates whose Repeated Part bounds or cap loops
crossed the displaced surface, then asked the planner for replacement cuts.

Outcome:
On BigSpruce it rejected the stump and every intended long branch, then selected
six micro-branches. Geometry settings silently changed fracture structure.

Keep:
Plan once from skeleton length and operator settings. Apply noise only to the
resulting Cut Surfaces; Repeated Part ownership follows skeleton attachment.

## Experiment: Wind Preview USD largest-skeleton autoselection

Status: Rejected

Context:
External Skeleton loading for converter-authored USDA files first used the
largest Skeleton prim by joint count so the main tree skeleton would win over
small repeated-part skeletons.

Outcome:
This was a hidden heuristic. Multi-skeleton USD files must show an explicit
Skeleton choice instead.

Keep:
Enumerate Skeleton prims in the Wind Preview worker and load only the operator-
selected index. Text USDA fallback may parse Skeleton blocks without `pxr`, but
it must not choose a skeleton by size.

Related files:
- `src/xml_to_usda/wind_external_skeleton.py`
- `src/xml_to_usda/qt_ui/wind_preview.py`
- `docs/wind_viewport_working_plan.md`

## Experiment: Reorient an imported UE Skeletal Mesh without reimport

Status: UE 5.7 in-place path validated; duplicate-and-create path superseded

Settled contracts now live in
[Decisions](decisions.md#decision-imported-foliage-orientation-must-update-mesh-and-skeleton-reference-poses).
This section preserves the failed and superseded routes.

Context:
Some already-imported vegetation assets use world-aligned local bone axes, which
can invert procedural wind response across opposite sides of a tree.

Approach:
`scripts/ue_orient_selected_skeletal_mesh_x.py` duplicates one selected Skeletal
Mesh beside its source and uses UE 5.8's native `SkeletonModifier` to orient
primary +X along the hierarchy. Commit updates the mesh reference skeleton,
mesh-description bone poses, and inverse bind matrices. It saves and selects the
modified mesh in the Content Browser.

Reason for the separate Skeleton:
UE 5.8 Dynamic Wind reads bind transforms from
`SkeletalMesh->GetSkeleton()->GetReferenceSkeleton()`, not from the Skeletal
Mesh reference skeleton. Reorienting only the mesh therefore changes the editor
bone display but not Dynamic Wind simulation.

Python limitation:
`USkeletonFactory::TargetSkeletalMesh` is protected and UE 5.8 rejects setting
it through `set_editor_property`. The public Python API cannot automatically
perform the final Skeleton creation. On the selected result use
`Skeleton > Create Skeleton`; the native asset action initializes and
assigns a new sibling Skeleton from that modified mesh.

Outcome:
The duplicate workflow established that changing only the Skeletal Mesh can
rotate editor bone axes without changing Dynamic Wind. It was superseded by
the UE 5.7 in-place Asset Action, which updates both the original mesh and its
dedicated Skeleton Asset. Manual UE 5.7 testing confirmed correct runtime wind,
branching-bone orientation, and terminal-bone orientation.

UE 5.7 in-place Asset Action:
`scripts/ue57_fix_selected_foliage_bones.py` edits all selected Skeletal Meshes
and their existing dedicated Skeleton Assets. It uses a transient leaf rename
and restores the original name to make UE 5.7 rebuild the Skeleton reference
pose; a transform-only `SkeletonModifier` commit does not do that. It refuses
shared Skeleton Assets because UE 5.7 otherwise preserves their old reference
pose and would also affect unselected meshes.

The native multi-child orientation policy is unsuitable for SpeedTree branch
junctions. The repair instead uses Reference Skeleton order: the lowest-index
child continues the current generator line, while every other child starts its
own line. This matches the converter's automatic Wind Preview branch-order
contract. Each bone's +X points to that continuation; a leaf uses its incoming
segment, and coincident terminal joints inherit the nearest usable line.
Transported parent +Y prevents arbitrary roll changes along a chain.

Orientation and the temporary rename share the first commit; restoring the
exact original name requires the second. This is the minimum available through
pure UE 5.7 Python: transform-only commits do not update the Skeleton Asset,
and `USkeleton::UpdateReferencePoseFromMesh` is not exposed to Python. The
script validates exact Mesh/Skeleton local-pose agreement after both commits.
`scripts/ue57_make_foliage_asset_action_command.py` copies the self-contained
`exec(...)` command for an Execute Python Command node.

For bug reports and Output Log reproduction,
`scripts/ue_orient_selected_skeletal_mesh_x_console.txt` contains the same
experiment as one self-contained Python-console line with no local file lookup.

Limits:
The in-place path intentionally preserves the existing dedicated Skeleton Asset,
but animation tracks, sockets, and Physics Asset local frames are not
compensated. Reimport can replace the result. Reference-pose geometry and
Dynamic Wind are validated; sockets, physics, authored animation, and reimport
remain operator validation items.

## Experiment: Fit Proxy collision from the simplified viewport mesh

Status: Rejected

Context:
Collision-only Proxy Preview updates were slow enough to suggest reusing the
already available low-poly viewport mesh.

Outcome:
The density/QEM mesh no longer retains base-mesh skin ownership and includes
crown geometry. Assigning its points to independent stems would require a new
geometric heuristic and could reproduce the multi-stem width error.

Keep:
Prepare one compact source from primary-stem joints and their owned base-mesh
points during initial preview generation, then refit collision locally. On the
three-trunk sample it contains 19 joints and 180 points; on Big Spruce, 17
joints and 973 points.

Related files:
- `src/xml_to_usda/proxy_collision.py`
- `src/xml_to_usda/proxy_mesh_service.py`

## Experiment: Reduce high-resolution Proxy QEM input before simplification

Status: Rejected

Resolution 512 on the dense 28-million sample produces about 6.77 million raw
surface triangles before the requested 5,000-triangle QEM result. A native
`fast-simplification` lossless prepass reduced a resolution-256 input from
1.65 million to 0.93 million triangles, but total simplification rose from
2.25 to 3.56 seconds. Raising QEM aggressiveness from 7 to 10 on the
resolution-512 input changed the result and was slightly slower: 9.30 seconds
versus 8.98 seconds.

Greedy coplanar voxel-strip merging was also rejected: naïve strip boundaries
introduce T-junctions, so making it topology-safe would require a second mesh
algorithm and substantially more complexity. Keep direct QEM and the retained
dense-grid/quadratic NumPy acceleration. Revisit surface reduction only with a
measured topology-preserving implementation.

Related files:
- `src/xml_to_usda/proxy_mesh_service.py`
- `src/xml_to_usda/qem_simplification.py`

## Experiment: Inherit parent deformation at base-tree branch attachments

Status: Implemented behind operator-selectable experiment; Unverified in UE 5.7.x

For a child joint attached at parameter `t` inside its parent bone, evaluate
the parent's existing influence vector at that position. Use that vector at
the child's start and blend it toward 100% child-joint influence along the
child segment. This preserves positional continuity between the child root and
the already-deforming parent surface without adding synthetic skeleton joints.

Base-tree recursion accumulates one additional ancestor influence at each
branch level. Quality 3/4 evaluates that same distribution at every Assembly
Part position; the Part remains rigid and receives one blended transform.

The Wind panel exposes one discrete `Skinning Quality` slider:

- `1 weight`: default rigid output and lowest runtime cost.
- `2 weights`: the production candidate using the child attachment collar.
- `3 weights (Expensive)`: recursively inherited base-tree weights, deterministically clamped
  and normalized to three slots.
- `4 weights (Expensive)`: the same propagation with four slots.

The two-weight mode leaves parent geometry on its unchanged gradient. At an
  internal child attachment, the child base starts with the parent's exact
  `grandparent + parent` mixture. Over the first 20% of the child segment that
  mixture smoothly reaches `100% parent`; the remaining 80% transitions
  linearly from `parent` to `child`. This keeps two slots and avoids the
  M-shaped parent profile produced by locally hardening parent geometry.

Quality 2 keeps the established two-weight Assembly Part path. Qualities 3/4
author matching inherited three-/four-slot Assembly Part bindings. The quality
selection is persisted as one integer. UE 5.7.x visual wind tests passed for
the earlier Base Mesh qualities 2-4; the new Assembly Part widths and their
runtime cost still require UE 5.7.x validation.
