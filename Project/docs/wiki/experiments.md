# Experiments

## Storage policy

Keep experiment source code and durable evidence outside the repository at:

`D:/3D Personal/XMLtoUSD_miscFiles/SpeedAssembly_Experiments`

This is the external experiment archive, beside the test trees under the
historical XMLtoUSD asset-folder name. Use one directory per experiment. Keep
code, configuration, documents, useful measurements, compact profiles, summaries,
environment details and hashes. Preserve failed approaches when they explain a
decision. Keep current conclusions and contracts in this wiki and production
Rust modules in `Project/native/`.

Do not store generated USD/FBX, imported asset caches, serialized full models,
native build products, executables, runtime IPC, UI state or temporary files in
the archive. Run those in disposable scratch space outside the archive, such
as OS temp or the ignored `Project/tmp/`, and clean them after extracting useful
results. New experiment scripts must accept explicit repository and scratch
paths instead of deriving them from the archive location. Disable Python
bytecode writes when running archived code, or direct them to scratch; set
`CARGO_TARGET_DIR` outside the archive for Rust builds. Do not recreate
`Project/experiments/` or make builds/tests depend on the external archive.

On 2026-10-18 all five existing experiments were archived: `xml_opening`,
`rust_conversion`, `rust_xml`, `rust_usda` and `source_extraction`. The archive
contains 242 original files verified with SHA-256, plus its README and manifest.
409 generated or temporary files were discarded. Historical scripts retain
their original path assumptions; consult the archive README before rerunning
them. The external archive is not backed up by this repository's Git history.

References starting with `<archive>/` below use this external root. Older
`experiments/<name>/...` references in the project log now map to
`<archive>/<name>/...`. The archive manifest records retained files and omissions.

## Release-validation duration, 2026-11-05

The later release-validation timing investigation is archived at
`<archive>/validation_duration_2026-11-05/`. It attributes the long release run
to the separately selected 160-launch stability sweep. The measured split and
current execution policy live in [Test policy](testing.md#full-builds-and-extended-stability).

## Shared source extraction, 2026-10-18

Architecture candidate 3 introduces `source_extraction.py` as the shared owner
for geometry, skinning, skeleton and Repeated Part interpretation. Canonical and
Proxy composition, prototype identity, diagnostics and cache policies remain
separate. No native extraction adapter, cache schema change or performance
claim. The existing Rust experiment now patches parser/skinning functions in
their actual extraction owner and passes its parity runner.

Retained pre-refactor modules match complete canonical models, warning order
and Proxy fields on ten inputs, including WorldTree with 657,878 base points
and 43,263 instances. Simple Tree matches USDA text in all four modes. The
default suite passes 680 tests. Old/new frozen conversion workers also match
USDA bytes and diagnostics for Simple Tree and BigSpruce. Evidence:
`<archive>/source_extraction/RESULTS.md` and its result records. Existing
non-finite OriginalScale validation differs between projections; tracked in
known bugs and intentionally preserved in this refactor.

Full Package passes 27 contracts and all three required smokes; frozen Proxy
Preview also returns and uploads geometry. UE 5.7.4 imports the exact new-worker
USDA with three correct mesh/Skeleton associations, no error-level log entries
and clean shutdown. Existing MaterialBindingAPI warnings remain. Animated Wind
and material appearance were not rerun. Version and publication state unchanged.

## Production USDA numerical adapter, 2026-10-18

Implemented architecture candidate 2. `usda_numbers.py` owns Python/native
numeric arrays and bounded chunk consumption; `native/usda_numbers` uses
borrowed buffers and exact CPython `%g`. Scene declarations, canonical models,
FBX, validation and publication remain in their existing owners. Source-only
Python recovery is retained; packaged builds require native API 1. Streamed
cancellation releases leases and preserves completed destinations.

Three fresh processes per adapter/input, source cache off, one-core affinity,
interleaved order: WorldTree full wall median 31.310 -> 27.453 s, writing
7.287 -> 3.854 s. Heavy FBX full wall 87.115 -> 56.827 s;
writing 45.680 -> 16.560 s and writer CPU 27.000 -> 9.469 s.
Heavy parent peak falls 3331 -> 2103 MiB. Wall time varies;
small-tree total CPU improvement is not established. Unchanged FBX helper/cache
cost remains. Do not extrapolate writer gain to the whole program.

24 byte-identical old-author/new-author pairs cover three sources, all modes
and packed prototypes; OpenUSD opens each. Source suite 679, Package contracts
27, all three required real-result smokes, old/new frozen worker parity and
ZIP/native/license checks pass. UE 5.7.4 imported the byte-identical Simple Tree
baseline with three mesh-to-skeleton bindings and no Nanite assembly failure.
The scratch importer needs a startup Nanite CVar and returns a Python Array.
Import-only scope, stock pipeline extras and existing MaterialBindingAPI warnings
are recorded in the report; animated runtime was not rerun.

The original experimental UV cache mishandled NaN combined with signed zero;
production skips those cache keys and has a regression check. No unexpected
native crash, version bump or publication. Evidence:
`<archive>/rust_usda/RESULTS.md` and `results/acceptance.json`.


## Source Opening Facts ownership, 2026-10-18

Implemented architecture candidate 1 without changing Rust exchange or domain
semantics. `opening_xml.py` owns complete opening facts and authored Wind joint
reading; native projection recovery is private. Discovery only merges settings,
and the Wind pipeline retains synthetic-rig resolution and JSON output.

Six-source signatures match retained discovery/Wind results. New source equals
the saved working EXE on four ordinary/grass inputs; the new EXE equals source
on the same four without a full-model source cache. Interleaved frozen runs,
four openings per version: Big Spruce 1.356 -> 1.379 s median, WorldTree
4.189 -> 4.057 s. No new speedup or stable regression is established. Earlier
unpaired WorldTree source-Qt timing rose 3.986 -> 4.367 s; retain that observation
and the stronger paired check rather than treating either as a universal ratio.

670 default tests, 27 packaged contracts, both mandatory real-result smokes and
ZIP/hash/license checks pass. One documented Qt typography flake recurred;
targeted and complete reruns passed without typography edits. No unexpected
native crash or new UE import. Evidence: `<archive>/rust_xml/OPENING_OWNERSHIP.md`
and `<archive>/rust_xml/results/ownership/acceptance.json`.

## Native XML opening and shared Wind snapshot, 2026-10-18

Control: accepted Python-only commit `2621bd2`; source-model cache disabled in
both variants, OS file cache retained. The first Rust DOM projection preserved
too many LeafReferences nodes and only reduced Big Spruce Qt readiness from
2.999 to 2.808 s in its pilot. Python traversals still dominated. Moving scalar
material/prototype/count facts to Rust and returning shared authored Wind data
eliminated both those traversals and a second XML read/worker launch.

43 accepted runs, six real-source exact row/Wind comparisons. Source Qt paste
through Wind readiness: Simple Tree 0.463 -> 0.187 s, Big Spruce 3.454 -> 1.565 s,
WorldTree 15.701 -> 4.085 s. Retaining a second Wind request with the final Rust
reader costs 2.910 s on Big Spruce. Service readiness including reused Wind:
0.907 -> 0.205 s and 12.270 -> 2.411 s for Big Spruce/WorldTree. WorldTree memory
only falls about 533 -> 494 MiB because Rust still builds its native DOM.
Clustered grass has no established total improvement; canonical synthetic-rig
work remains. Single extra-source runs establish parity, not stable speedups.

Native parsing uses roxmltree with explicit full-source budgets and no unsafe
code in the module. Cow text views avoid copying ordinary packed fields;
unusual numeric forms keep the authoritative Python interpretation. All UI
assignment, canonical bone, placement and Scattered Parts owners are reused.
Rust-skills guided memory/error handling and strict Clippy/format checks.
Full report and raw evidence: `<archive>/rust_xml/RESULTS.md`.

Final EXE UI acceptance, two runs per input: Simple Tree 0.113–0.161 s,
Big Spruce 1.071–1.303 s, WorldTree 3.440–3.892 s, from path insertion to
rows and Wind. Complete source/frozen worker results match on Big Spruce,
WorldTree and both grass inputs without source-model cache creation. Passed
664 default tests, 81 focused checks, 27 packaged contracts, both required
real-result smokes, strict native lint/format and ZIP/hash/license validation.
No new UE import or unexpected native crash. Artifact hashes and timing scope
are retained in `<archive>/rust_xml/results/acceptance.json`.

## Initial XML opening projection, 2026-10-17

The original discovery service normalized/cached a full canonical model, then
parsed XML three more times for material rows, prototypes and Generator gaps.
The historical Phase 5 architecture plan explicitly avoided this heavy path;
subsequent Scattered Parts detection and vertical-joint warnings explain why
canonical structure was added, but authored skeletons do not need mesh payloads.

Discovery now reuses one hardened document, canonical skeleton normalization and
LeafReferences count/position-space checks. No geometry construction or source
JSON cache is needed for authored skeletons. Skeletonless sources retain full
canonical classification on that document. Worker isolation is unchanged.

52 accepted fresh-process/Qt opening runs, six real-source parity comparisons.
Real Qt paste through automatic Wind completion: Big Spruce 4.017 -> 2.662 s
with cache off, or 5.514 s cold/4.498 s warm JSON before the change. WorldTree
32.503 -> 13.829 s without application caching. Service-only discovery improves
1.745 -> 0.570 s and 25.775 -> 7.591 s; parent peaks fall 128 -> 73 MiB and
1536 -> 532 MiB. Packaged XML adapter checks independently improve complete
discovery + Wind by about 2.4x. These source timings exclude EXE extraction;
CPU affinity differs from the earlier Rust experiment.

Real clustered/unclustered grass keeps its classification and canonical path;
unchanged leaf-only Wind limits the clustered case to a small total improvement.
Rust XML parsing, a selective streaming reader and combined discovery/Wind IPC
remain Unverified. Parallel duplicate reads were not introduced. Conversion
cache creation can move to the later Convert action. Full results, methodology,
input hashes and reproduction: `<archive>/xml_opening/RESULTS.md`.

Validation: 632 default tests, 59 final focused checks, 27 Package contracts,
repeated Detailed Cuts real-result smoke and injected-failure recovery passed.
Real frozen discovery/source results match on Big Spruce, WorldTree and both
grass inputs without creating a JSON source cache. No unexpected crash, new
dependency, version bump or publication. Actual frozen acceptance timings are
recorded separately from source before/after ratios.

## Rust conversion kernels, 2026-10-17

Status: Source experiment validated; production integration and UE acceptance open.

The operator requested full XML-to-published-USDA profiling, followed by Rust
replacement of measured hot loops while retaining UI and FBX loading. The
isolated PyO3 candidate lives in `<archive>/rust_conversion/`. It moves packed
number parsing, vertex binding, batched point/normal transforms and numerical
USDA arrays. Canonical Python models and the authoring/validation engine remain.
Packed FBX arrays use borrowed buffer views and a UV-value cache preserving
signed-zero first-spelling behavior across output chunks. Float formatting
reuses CPython's proven native `%g` conversion for exact output.

Fresh processes on i9-14900K, one logical CPU, alternating variant order, OS file
cache retained, source-model cache disabled:

| Case | Python | Rust hybrid | Runs per variant |
| --- | ---: | ---: | ---: |
| Simple Tree, quality 1 | 0.244 s | 0.223 s | 6 |
| Big Spruce, quality 1 | 1.358 s | 1.144 s | 6 |
| Big Spruce, quality 4 | 1.488 s | 1.269 s | 6 |
| WorldTree, 148.5 MB XML | 18.972 s | 15.633 s | 6 |
| Big Spruce + 14.16M-triangle FBX | 50.086 s | 32.754 s | 3 |

On the heavy FBX path, writing alone falls from 26.760 s to 9.556 s, 2.80x;
full conversion improves 1.53x. The unchanged helper/cache/IPC boundary remains
21.2-21.4 s. Parent peak working set falls from 3330 to 2105 MiB, but WorldTree
adds about 40 MiB. Normalization is a smaller gain, 1.32x on Big Spruce. Do not
extrapolate these loop replacements into a full-normalizer or multi-threaded
backend claim.

All 126 accepted conversions retained exact output hashes, sizes and diagnostics.
Nine XML canonical models and packed writer payloads match; numeric, invalid
binding and UV-cache boundary checks pass. Existing backend contracts: 71 passed.
OpenUSD opened both large outputs and verified mesh/skeleton/instance counts.
No native crash occurred. Sandbox temp permission failures and cancelled pilot
iterations were excluded and resolved with workspace-local tool/helper temp
roots, without product patches. cProfile's asymmetric overhead is excluded
from speed comparisons; retained function/module tables cover the conversion
parent, not helper internals.

The current JSON source cache separately regresses Big Spruce to 3.073 s cold
or 2.554 s warm versus 1.358 s without it. Conversion cache policy is unchanged;
the subsequent initial-opening change bypasses this cache for row discovery.
Next useful native trial is the numerical writer behind the current authoring
seam. Package, native worker lifecycle and UE 5.7.x gates remain mandatory before
integration. Full report, exact inputs, code and raw evidence:
`<archive>/rust_conversion/RESULTS.md` and `results/` beside it.

## Bone overlay rendering experiments, 2026-10-13

Superseded: QPainter strokes and CPU clipping of projected ribbons. Grid-based
candidate checks cost about 60 ms on Alder; X-bound filtering reduced planning
to about 20 ms, but whole viewport remained slow. Mean-depth sorting was also
incorrect at crossings, and outline-expanded cuts introduced black gaps.
Operator feedback rejected fixed shadow values of 28% and 6%; then preferred
35% and requested relative radius, 0-100% strength and realtime rendering.

Current solution: opaque unlit OpenGL quads, one batch, hardware depth. NumPy
projection and block-vectorized strict-crossing events replace per-bone Qt calls
and pairwise clipping. Adjacent/endpoint/parallel contacts never cast AO. The
shader evaluates at most eight centers per bone. Real pixels and rotating-camera
CPU+GPU-finish measurements passed: 2.16 ms median for 347 joints; 6.22 ms for
1108. Default shadow 35%, radius 1 = 12 pixels at 1440p, normalized to screen
height/DPI. See [Tree hierarchy](wind-tree-hierarchy.md) for current contracts.

Rejected, superseded, and partially validated work. Current contracts live in
[decisions.md](decisions.md); active gaps live in [known-bugs.md](known-bugs.md).

## UE 5.8 PVE extraction and automatic wind groups

Status: Source-verified in local UE 5.8.2; comparative runtime quality Unverified.

Extract from Mesh reconstructs whole branch curves, choosing fork continuation
by direction plus normalized remaining subtree length. Branch hierarchy depth
increments only for side branches. Dynamic Wind assignment is separate: bone
creation quantizes branch-base radii into indices 0/1/2, as in UE 5.7, with a
branch-aware base-radius helper in 5.8. It does not use hierarchy depth.
Geometry-based continuation is a candidate for external rigs, not a replacement
for the established SpeedTree order contract. Details and source navigation:
[UE 5.8 PVE Mesh Extraction](ue58-pve-mesh-extraction.md).

## SpeedTree Raw XML to UE 5.8 PVE Growth Data

Status: Growth Data UI import, reload, corrected fragment preview and Static
Mesh bake verified in UE 5.8.4 (CL 58902052). Full-tree mapping, interactive
editing, skeletal export, and Nanite bake remain Unverified.

Stock USD and Interchange code has no PVE asset translator. PVE's
`Extract from Mesh` reads a Static Mesh and reconstructs branch curves.
For a direct data path, the stock PVE plugin also has a development-only
JSON importer and a Growth Data asset action, `UpdateDataAsset`.
`PVJSONHelper.cpp::LoadGrowthDataJsonToCollection` reads branch points and
ancestry and derives point scale from `budLateralMeristem`. This is an
internal format. `Growth Data Loader` reads saved variations from the asset.

The artist can import without running a script. In the Content Browser use
**Add → Data → Data Asset** and choose **Procedural Vegetation Growth Data
Asset**. Open it, set **Internal → Json Directory Path** to a folder of
Growth Data JSON files, click **UpdateDataAsset**, and save. In a PVE graph,
assign the asset to **Growth Data Loader**. The button replaces the existing
variation list and names each loaded variation after its file. The UI probe
created an empty asset, imported `SimpleTree01_Fragment` and saved the
result. Unreal logged the import and package save. PVE's native button ran
without any Python action. The editor still loaded Python at startup for
other engine plugins.

The separate **Growth Data Json Importer** node reads a file directly.
`PV.DebugMode.Enabled 1` exposes it in the graph menu per engine source.
The UI probe used the asset button only.

In a scratch project, Unreal Python invoked `UpdateDataAsset` with Epic's
sample and then with a JSON fragment from `SimpleTree_01.xml`. The fragment
used 15 animation bones for 17 points and two branch curves. It approximated
the junction with the nearest trunk sample and supplied minimal bud data.
After restarting UE and moving the JSON aside, the stock Loader exposed the
named variation. Python used the stock graph factory, found its embedded
graph by name, and saved it with Loader, Manual Edit and Mesh Builder
connected. The graph's private property was inaccessible through Python.

The inspected SimpleTree, Alder and Spruce XMLs had bone endpoints and radii
but no object spines. The current canonical Joint retains endpoints and
ancestry without the XML radius. A production exporter needs a verified
mapping for full branch chains, attachment points and radii. Mesh Builder
regenerates woody geometry. PVE 5.8's stock Foliage Distributor places new
instances. Exact SpeedTree bark geometry, foliage placements, and editable
SpeedTree generator settings were outside this probe.

The corrected fragment has ten `budStatus` integers per point, derived
from PVE's root, tip and fork rules. It also has a finite, normalized
`budDirection` UpVector perpendicular to the branch tangent. Adding status
alone removed the assert but left a zero UpVector. Mesh Builder normalized it
and produced NaN vertices. With both corrections and one Generation Materials
slot in Mesh Builder, the graph displayed the trunk and branch. PVE reported
153 resampled points, 1,681 vertices and 3,320 triangles and baked a Static
Mesh with Nanite Foliage disabled. Branch-junction fidelity remains
Unverified.

Reproduction and compact logs: `<archive>/pve_growth_import_58/`.
The final fixture, standalone generator and bake evidence are in its
`verified/` directory. The generator reproduces the tested JSON byte for byte.

Source audit: the Growth Data loader reads typed point and branch attributes.
It computes `Scale` in centimeters from `budLateralMeristem[0]` in meters
and recomputes bud IDs and branch source bud IDs. Mesh Builder uses Scale
as the base radial distance, resamples curves, and recalculates gradients
and material UVs. At a fused fork, it estimates the child's base radius from
the child's next samples. XML bone radii are usable inputs, but agreement
with the original bark surface has not been measured. An XML spine radius
profile, where available, or a measured bark section can supply more detail.
The Growth JSON loader does not run the legacy foliage or global attribute
readers. Custom typed attributes can enter the collection; their use and
preservation in downstream nodes require separate verification.

### Full-tree prototype

UE 5.8.4 accepted the current SimpleTree Spine output with 23 branches and
472 input points. The graph connected Growth Data Loader, Manual Edit and
Mesh Builder. The viewport reported 833 resampled points and 15,296
triangles. Static Mesh export completed with Nanite Foliage disabled and
no logged NaN vertices. The previous Bones-only SimpleTree exported
22 branches and 169 input points and rendered 11,359 triangles in PVE.
The packaged worker reproduced both imported files byte for byte.

Spine JSON SHA-256:
`2be16071374a668826d43613ce45b3f6b2ad92ca64ac8995c53a74f250baa226`.
Bones JSON SHA-256:
`37cf55e594d634c6177c2789135f05ff6a9053129eeeb74b6eb81c26c4572e5f`.

## Tree hierarchy from operator-selected reference rigs

Status: Implemented as a comparison candidate; independent/UE validation open.

The operator selected seven prepared USDA/JSON pairs plus four XMLs; one Norway
XML repeats its prepared rig. On ten independent inputs, Tree mismatches
133/3336 labelled joints versus Order 485 and PVE 808 with matched group caps.
Trunk and branch-chain geometry use a single analyzer, not file-specific rules.
It runs on bare bind poses/parents and caches one loaded-rig result in the GUI.
Tree guides start at each joint, removing child-color overdraw on the trunk;
USD terminal guides are explicitly short direction markers. Source rigs and
USDA authoring remain unchanged.

Retained counterexamples: 03_28mil regresses versus Order, Willow and Alder 01
still need manual review, and near-collinear source generator boundaries remain
uncertain. A fitted edge classifier was rejected after whole-family exclusion
showed poor generalization and root-error propagation. Full method, calibration
constants, corpus policy and source-backed Trunk-fork exception:
[Tree hierarchy calibration](wind-tree-hierarchy.md).

## PVE-style Wind hierarchy comparison

Status: Implemented as an explicit alternative; operator/UE quality Unverified.

`Auto Hierarchy (PVE)` scores continuation with `(1 + dot) / 2` plus normalized
longest descendant path. Other children increase branch level. XML physical
segments use `bind -> bind_end`, including the candidate's own segment in its
remaining path; external point rigs use parent/current displacement and exclude
the candidate's entering edge, as in PVE. No radius grouping or new skeleton
extraction. Zero lengths contribute no length score; ties retain file order.
The existing 1-10 Groups slider caps levels into the last group, and manual
overrides remain above either base method. Continue line belongs only to the
original order-based method; switching back retains its settings.

Synthetic comparison produced seven hierarchy groups and invariant geometric
assignments after reordering. SimpleTree changed 45/105 assignments; Big Spruce
changed 115/1108. Both real samples used three effective geometric groups even
with cap 10. Those counts describe classification changes, not better quality.
Combined old/new grouping ran in 0.0028 s and 0.0523 s respectively in one local
run; these are observations, not benchmark medians.

Norway Spruce follow-up: the operator's SpeedAssembly USDA loads the same
249-joint rig as its sibling XML but lacks every physical endpoint. PVE selects
a branch after bone_005 instead of stem bone_184. In-memory endpoint recovery
after exact name/parent matching and a maximum bind component error of 4.9942e-7
restores the physical-XML assignment. It is diagnostic evidence, not an automatic
sidecar-loading contract. The 103 nearly collinear attachment connectors also
overlay the trunk with child colors. See
[the USD round-trip bug](known-bugs.md#bug-external-usd-loses-physical-bone-endpoints-and-overlays-attachment-links).

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
dispatch-derived roughly 524k count as the complete scene budget. On 2026-10-06,
the operator supplied the UE 5.7 composite offset-limit assertion and confirmed
that restoring batching with Wind_TransformProvider fixed the dense PCG crash.
See CR-016. That supports the allocation-overflow mechanism but does not identify
which offset failed or make x16 the no-provider formula: the null-provider
branch sets one animation variant; object-space data is a separate allocation.

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

## Documentation article navigation

Status: Locally browser-validated on 2026-10-07; public deployment pending.

Compared the unchanged static build with Material instant navigation plus
cancellable hover/focus preloading. Headless Microsoft Edge, 1440x1000 viewport,
seven fresh browser contexts per mode; home and shared assets loaded first,
target article initially cold. Local HTTP server adds 120 ms per uncached
successful request and uses `Cache-Control: public, max-age=600`. Target:
home to `wiki/xml-usd-usda-json/`. Timing starts at the click event and ends at
the second animation frame after the target article heading appears. Images
finishing later are outside this metric. No CPU or bandwidth throttle.

| Mode | Median | Range |
| --- | --- | --- |
| Original full navigation | 200.7 ms | 187.6-206.9 ms |
| Instant navigation, no hover | 153.1 ms | 150.3-161.9 ms |
| Instant navigation, 500 ms hover before click | 29.5 ms | 26.4-33.0 ms |

The improvements are 23.7% without hover and 85.3% after preloading. Warm
transitions made no article network request and preserved `performance.timeOrigin`.
These are controlled local results, not measurements of GitHub Pages or a
promise of instantaneous image loading. The retained browser script accepts
any baseline/candidate site directory; see `Project/README.md` commands.

The navigation gate also passed with 240 ms server latency: rapid pointer
sweeps request only the final article; obsolete active requests abort; a click
during a fetch reuses its HTTP cache fill; history, anchors, theme, contextual
ENG/RU switching and cross-language search stay correct. A failed prefetch does
not block real navigation. Touch hover and Save-Data issue no speculative work.
Strict MkDocs and the 24-page bilingual contract pass independently.

Rejected: Material 9.7.7 built-in `navigation.instant.prefetch`. Its shipped
source map shows a 25 ms debounce followed by `distinct` and `exhaustMap`.
A new hover is discarded while the previous prefetch is active; this does not
meet the latest-hover requirement. Reuse native navigation and HTTP caching,
with only a small abortable fetch scheduler owned by this project.
