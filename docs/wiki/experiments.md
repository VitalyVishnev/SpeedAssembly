# Experiments

## Experiment: Connectivity-first Manifold Boolean fracture

Status: production integrated; broad real-tree and UE runtime validation remains open.

The `boolean-prototype` command isolates one whole connected branch before any face-ownership split, closes its oriented boundary loops, and splits it with a closed triangular-lattice cutter displaced by one-sided deterministic fractal noise. `manifold3d` provenance removes temporary source closures while retaining cutter-derived caps. Requested amplitude is uniformly limited before the next physical terminal, branch, or bend above `Max Bend Angle`. Exact source-triangle provenance transfers UV0/UV1, colors, material sections, and skinning; caps receive planar UVs and nearest boundary-ring attributes. Its viewer can regenerate the same source in place with editable cut/noise controls while the deterministic seed remains fixed. The synthetic open-cylinder case, Simple Tree `bone_086`, and Big Spruce `bone_508` pass locally.

The `boolean-multi-prototype` command prepares source analysis/triangulation/connectivity once and assembles untouched faces, parent stubs, and detached branches by Fracture Plan ownership. Independent components build separately. Same-shell cuts split their current parent region sequentially with distinct cap provenance; this covers the real SimpleTree stump-plus-branch case without overlapping geometry. Structural `auto_stem_length` pieces reuse already disconnected source shells. Collision, Repeated Parts, export, and any external process pool remain separate work.

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
