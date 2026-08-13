# Known Bugs

## Limitation: UE 5.7 in-place foliage orientation requires a dedicated Skeleton

Status: Fail-loud

The UE 5.7 Asset Action repair refuses a selected Skeletal Mesh when another
Skeletal Mesh references the same Skeleton Asset. `SkeletonModifier` only
merges a shared Skeleton and does not replace its existing reference-pose
transforms, while changing that shared pose would also alter unselected assets.
Use a dedicated Skeleton per vegetation mesh before running the repair. The
operation intentionally changes reference frames in place; authored animation,
sockets, Physics Assets, and reimport behavior remain operator validation items.

Exact bone-name preservation currently costs two Skeletal Mesh commits. The
first applies orientation and a transient leaf rename so UE synchronizes the
Skeleton reference pose; the second restores that name. Nanite Assemblies can
therefore compile twice. A one-commit production implementation requires a
small UE 5.7 C++/Blueprint bridge exposing
`USkeleton::UpdateReferencePoseFromMesh`; leaving a renamed helper bone or an
altered hierarchy was rejected.

Related files:
- `scripts/ue57_fix_selected_foliage_bones.py`
- `docs/wiki/experiments.md`

## Limitation: Wind Auto Hierarchy assumes immediate preorder continuation

Status: Unverified outside conforming SpeedTree order

The shared Generator Continuation contract selects the lowest-index direct
child at a fork. Wind Preview currently recognizes it only when that child is
exactly `parent index + 1`, which is the normal SpeedTree preorder shape. The UE
5.7 repair uses the general lowest-direct-child rule. A reordered or filtered
external skeleton could therefore group differently between the two consumers.

Next step:
Retain a real counterexample before changing behavior. If non-immediate
continuation is observed, make Wind Preview use the same lowest-direct-child
helper and preserve explicit `Continue line` behavior for non-SpeedTree inputs.

Related files:
- `src/xml_to_usda/wind_viewport_scene.py`
- `scripts/ue57_fix_selected_foliage_bones.py`
- `docs/wiki/decisions.md`

## Bug: Restored very large XML could destabilize GUI startup

Status: Mitigated; packaged validation passed, operator validation pending

Symptoms:
With the 148.5 MB `WorldTree.xml` persisted as the default input, repeated
launches either stopped after the `app.start` trace event or failed during
module import with `'builtin_function_or_method' object has no attribute
'GenericAlias'`.

Confirmed boundary:
The shell synchronously ran two full XML discovery scans before showing the
window. Importing the discovery facade also eagerly imported the native
Autodesk FBX SDK even though normal XML startup did not need it. No matching
SpeedAssembly Application Error or WER record identified the final failing
instruction, so the exact corruption source remains unverified.

Current behavior:
XML discovery and Wind inspection at or above 5 MiB run in fresh file-backed
workers; latest input wins and Wind auto-refresh waits for discovery. Autodesk FBX
loads only for an actual FBX-backed action. Python bootstrap failures are now
persisted in `gui_runtime.log`. A source-mode WorldTree startup constructed the
window in 0.421 s, returned one material row plus two prototype rows, then
loaded six Wind groups in 8.64 s total without running either source scan in
the GUI process.
The packaged executable reproduced the same sequence: source discovery
completed in 4.42 s, isolated Wind inspection completed 2.56 s later with six
groups, and the timed shell exited normally.

Related files:
- `src/xml_to_usda/discovery_service.py`
- `src/xml_to_usda/source_discovery_worker_subprocess.py`
- `src/xml_to_usda/qt_ui/background_jobs.py`
- `src/xml_to_usda/qt_ui/window.py`

## Bug: Generic source-model caching can crash while serializing a very large tree

Status: Open

The former Big Spruce cache regression triggered `0xC0000005` in Python while
the generic worker-payload encoder serialized the model. The normal cache
contract now uses Simple Tree, so the default suite remains stable; this does
not prove generic full-model caching is safe at Big Spruce scale.
During 2026-07-24 profiling, one default-cache Big Spruce load reconstructed a
`Vector3` where the planner expected its face-owner tuple; a clean XML load
with source caching disabled passed immediately. This strengthens the cache
boundary concern but does not identify a new fracture-ownership cause.

Keep Big Spruce validation in an explicit stress/packaged run. The likely next
step is to replace generic full-model JSON caching only if it is required by a
real workflow and can be measured against the existing typed projections.

Related files:
- `src/xml_to_usda/canonical_loader.py`
- `src/xml_to_usda/worker_file_protocol.py`
- `tests/test_canonical_loader_cache.py`

## Limitation: Detailed Boolean cuts need broad real-tree validation

Status: Partially verified

Detailed Cuts are integrated into Fracture Preview and export, retain Repeated
Parts by skeleton attachment, author transferred/cap normals, and feed the
existing collision builders. Automated coverage includes synthetic geometry,
SimpleTree, multi-stem stump cuts, sibling-collar ownership, a three-sample
ownership matrix, and packaged stability smoke. Broader visual validation
across unrelated SpeedTree assets and Unreal import remains pending.

Related files:
- `src/xml_to_usda/boolean_fracture_prototype.py`
- `src/xml_to_usda/fracture_preview_service.py`
- `src/xml_to_usda/fracture_export_service.py`

## Limitation: Detailed Repeated Part pivots outside a cutter projection keep skeleton ownership

Status: Deliberate fallback

Detailed ownership evaluates only Repeated Parts in the current cut's child
subtree. If an eligible instance pivot projects inside the built cutter
triangles, the exact barycentric surface height decides parent versus child.
Some foliage pivots lie outside the finite Base Mesh cutter projection; no
geometric side exists there, so they retain skeleton ownership.

Do not extend ownership from the nearest cutter edge or a global noise field:
the Big Spruce reproduction moved 230 parts instead of the 88 supported by the
actual cutter triangles. If an outside-projection visual defect remains, the
next step is an explicit source attachment-point contract.

Related files:
- `src/xml_to_usda/boolean_fracture_prototype.py`
- `tests/test_boolean_fracture_prototype.py`

This page stores current bugs, limitations, and validation gaps. It should stay focused on dangerous or still-open issues.

## Bug: Detailed Cuts worker previously retained unsafe native state

Status: Mitigated; native root cause remains unverified

Symptoms:
The former persistent worker sometimes exited with `0xC0000005` in unrelated
normalization/source-limit paths after Detailed Cuts, and also emitted
impossible Python internal errors during attribute transfer. Disabling cyclic
GC did not provide a reliable fix.

Current behavior:
Fracture Preview no longer reads or writes the typed `.npz` source-model cache
and runs every request in a fresh worker. The GUI still coalesces changes to
one active request plus the latest pending settings, so no native workers
overlap. This accepts the measured sub-second startup/cache cost in exchange
for containing unsafe native state to one result.

Do not repeat:
Do not restore the persistent native worker or a disk source-model cache for
this path without a packaged stability result that identifies and removes the
native root cause.

Related files:
- `src/xml_to_usda/fracture_worker_subprocess.py`
- `src/xml_to_usda/fracture_preview_service.py`
- `src/xml_to_usda/conversion_process.py`
- `src/xml_to_usda/qt_ui/preview_jobs.py`

## Bug: Rapid Fracture Preview geometry replacement could crash the Qt process

Status: Mitigated; packaged stress validation passed, broader operator validation pending

Symptoms:
After several Detailed Cuts on/off transitions, the worker completed normally
but the GUI process could terminate while replacing the viewport mesh.

Likely cause:
Trace ended after `viewport.upload_end` and before `set_preview` returned. Scene
callbacks eagerly called `makeCurrent()`, uploaded buffers, then called
`doneCurrent()` outside `paintGL`, creating an unsafe Qt/OpenGL context lifecycle.

Current behavior:
Scene replacement only marks mesh/grid buffers dirty. The next `paintGL` owns
the upload with Qt's context already current. The packaged rapid-toggle scenario
passed; keep this issue open until broader operator use remains stable.

Do not repeat:
Do not upload QOpenGLBuffer data directly from preview-result callbacks.

Related files:
- `src/xml_to_usda/qt_ui/viewport.py`
- `src/xml_to_usda/qt_ui/fracture_preview.py`

## Bug: Expanded Repeated Parts could exhaust Fracture Viewport memory

Status: Mitigated; packaged GPU validation passed, operator validation pending

Symptoms:
Big Spruce expanded 3613 Repeated Parts into 30,454,695 vertices and a 2.07 GB
OpenGL upload. The process later disappeared while the bone overlay was active.
The trace contains no failing bone segment; all 1108 overlay segments were
present and non-zero length.

Likely cause:
The diagnostic renderer baked every instance transform into a unique vertex
payload, discarding the source scene's existing instancing contract.

Current behavior:
Fracture Preview uploads unique geometry and one compact transform buffer, then
issues one hardware-instanced draw per unique source mesh. Big Spruce therefore
keeps all 3613 placements without either the former multi-gigabyte flattened
buffer or 3613 draw/uniform sequences per frame. The 256 MiB guard remains on
the actual unique vertex upload. Three consecutive packaged Big Spruce rapid-
settings runs passed with all instances and no worker retry; keep operator
validation open because the original GUI disappearance produced no dump.

Do not repeat:
Do not flatten instanced viewport scenes or treat an API maximum buffer size as
a safe interactive memory budget.

Related files:
- `src/xml_to_usda/qt_ui/fracture_preview.py`
- `src/xml_to_usda/qt_ui/viewport.py`

## Bug: External PartMesh override can look ignored

Status: Workaround

Symptoms:
The UI shows an Unreal asset path, but UE still appears to import the low-poly inline part.

Likely cause:
The USDA may be missing `NaniteAssemblyExternalRefAPI` and `unreal:naniteAssembly:meshAssetPath`, or UE may be using the wrong import path.

Current workaround:
Inspect the USDA first. Verify the external-ref schema and the exact UE package/object path before changing exporter logic.

Do not repeat:
Do not assume the UI is wrong until the USDA proves it.

Related files:
- `docs/raw/troubleshooting.md`
- `docs/raw/ue_import_contract.md`

## Bug: FBX prototype replacement can fail before export

Status: Open

Symptoms:
A prototype row switched to `FBX file` fails before USDA is written.

Likely cause:
Missing Autodesk FBX SDK bindings, a non-rigid FBX, unreadable mesh payloads,
missing vertex colors, an SDK vertex-color access error, or transient binding
instability while several exceptionally large FBX payloads overlap. Frozen
Preview also reproduced an invalid `MultT(FbxVector4)` dispatch after repeated
per-control-point calls on a HIGH WorldTree branch.

Current workaround:
Use a rigid FBX with readable polygon mesh data and vertex colors. The observed
WorldTree `FbxVector2.__getitem__(): not enough arguments` failure now retries
only the remaining payloads at lower helper concurrency. A repeat at one helper
still surfaces normally. Per-point Preview/import transforms no longer call
`MultT`; oversized Part Preview display geometry is sampled to 50,000 faces
without changing export geometry.

Do not repeat:
Do not treat XML `LOD/@Filename` as the replacement source.

Related files:
- `docs/raw/troubleshooting.md`
- `docs/raw/local-python-environment.md`

## Bug: Qt shell preset and preview cache ownership is still too broad

Status: Open

Symptoms:
`MainWindow` still owns preset dialog orchestration and Proxy Mesh preview cache lifecycle.

Likely cause:
The current preset handling is tightly coupled to dialogs/widgets, and preview cache state does not yet have enough shared lifecycle behavior to justify a separate controller without a shallow abstraction.

Current workaround:
Keep the ownership in the shell until a real second consumer or workflow change justifies extraction.

Do not repeat:
Do not split this into a controller just to make the file count smaller.

Related files:
- `docs/raw/KNOWN_PROBLEMS.md`
- `src/xml_to_usda/qt_ui/window.py`

## Bug: Synthetic contract fixtures are not real SpeedTree exports

Status: Unverified

Symptoms:
Some contract fixtures are synthetic instead of observed exports.

Likely cause:
They encode edge cases and failures that are hard to source from a single real sample.

Current workaround:
Keep the smallest fixture that expresses the contract cleanly.

Do not repeat:
Do not replace useful edge-case fixtures with weaker real samples just to simplify the tree.

Related files:
- `docs/raw/KNOWN_PROBLEMS.md`
- `tests/data/leafrefs_on_trunk.xml`
- `tests/data/leafrefs_on_branch_levels.xml`
- `tests/data/invalid_leaf_bone.xml`
- `tests/data/missing_leaf_refs.xml`
- `tests/data/missing_skeleton.xml`
- `tests/data/non_default_metadata.xml`

## Bug: Fracturing UE runtime validation is still missing

Status: Unverified

Symptoms:
Fracture Preview and export are stable on the dense Spruce sample, but runtime replacement behavior is not yet validated in UE 5.7.x.

Likely cause:
Runtime replacement needs an engine scene and destruction harness, not just USDA import or Qt preview.

Current workaround:
Treat the workflow as not fully validated until a UE runtime test exists.

Do not repeat:
Do not call the workflow complete based only on import or preview evidence.

Related files:
- `docs/raw/KNOWN_PROBLEMS.md`
- `src/xml_to_usda/fracture_service.py`
- `src/xml_to_usda/fracture_export_service.py`
- `src/xml_to_usda/fracture_preview_service.py`

## Bug: Fracture collision import still lacks UE 5.7.x confirmation

Status: Unverified

Symptoms:
Fracture collision meshes are authored with UE-style `UCX_`, `UCP_`, and `USP_` names, but USD/Interchange recognition has not been validated in UE 5.7.x.

Likely cause:
FBX naming conventions do not automatically prove USD import behavior.

Current workaround:
Treat the collision output as provisional until the UE import check is done.

Do not repeat:
Do not assume naming alone is enough evidence.

Related files:
- `docs/raw/KNOWN_PROBLEMS.md`
- `src/xml_to_usda/fracture_collision.py`
- `src/xml_to_usda/fracture_export_service.py`

## Limitation: Detailed Cut cost scales with cut count and cutter density

Status: Open

Symptoms:
Large trees with many selected cuts update more slowly than flat cuts. Higher
Cut Detail increases lattice construction, Boolean, validation, and attribute
transfer work.

Current behavior:
Preview reuses prepared source/cut sessions and export uses the same final mesh
contract. A local 11-cut Big Spruce pass at Intensity 20 / Cut Detail 8 reduced
prepared-session setup from an observed 5.60 s to a 1.49 s five-run median and
regeneration from a 1.70 s three-run median to a 0.835 s five-run median. Three
fresh-process Fracture Preview runs completed in 3.30–3.47 s. Cutter noise
generation and attribute transfer remain the main regeneration costs; the
Boolean operation itself is comparatively small. A 2026-07-24 Windows
spawn-based prototype kept exact cut meshes and diagnostics but failed the
speed gate: at 37 independent cuts, sequential took 6.81-6.88 s, two processes
took 6.99-7.34 s, and four took 7.92-8.05 s before final assembly. At 12 cuts
the process pool was substantially slower. Estimated child peak RSS was about
382-403 MiB for two processes and 577-751 MiB for four. Production therefore
remains sequential.

Do not repeat:
Do not enable a thread pool around Python bindings: the binding does not release
the GIL and the wheel already uses internal oneTBB parallelism. The measured
2/4/8-thread variants were equal or slower. Do not retry a spawn process pool
without first removing its cold-start and serialization boundary.

Related files:
- `src/xml_to_usda/boolean_fracture_prototype.py`
- `src/xml_to_usda/fracture_preview_service.py`
- `src/xml_to_usda/fracture_export_service.py`

## Bug: UDIM real-sample coverage is incomplete

Status: Unverified

Symptoms:
UDIM authoring works on automated tests and the baseline sample, but not across a broad real-sample matrix.

Likely cause:
The project still needs broader UE 5.7.x import and material inspection coverage.

Current workaround:
Treat current coverage as partial, not final.

Do not repeat:
Do not promote baseline-only evidence to a full contract.

Related files:
- `docs/raw/KNOWN_PROBLEMS.md`
- `src/xml_to_usda/udim_resolver.py`
- `src/xml_to_usda/material_resolver.py`

## Bug: Proxy Mesh distance-field and shadow usefulness are unverified

Status: Unverified

Symptoms:
The `_proxy.usda` asset imports as a Static Mesh, but distance-field generation and low-cost shadow behavior are not yet validated.

Likely cause:
The current checks stop at import, not scene lighting behavior.

Current workaround:
Treat proxy export as import-validated, lighting-unverified.

Do not repeat:
Do not infer shadow quality from import success alone.

Related files:
- `docs/raw/KNOWN_PROBLEMS.md`
- `src/xml_to_usda/proxy_mesh_service.py`

## Bug: Proxy Mesh simplification quality still needs comparison on real vegetation

Status: Open

Symptoms:
The `density_field` path works, but its quality on sparse trees, dense crowns, grass, and moss is not yet broadly compared.

Likely cause:
The preview/export loop is stable before full real-sample quality tuning.

Current workaround:
Keep QEM as the backend and compare on real samples before changing it.

Do not repeat:
Do not replace QEM with a cheaper-looking proxy that breaks topology.

Related files:
- `docs/raw/KNOWN_PROBLEMS.md`
- `src/xml_to_usda/proxy_mesh_service.py`

## Bug: Proxy Mesh zoned simplification is only partial

Status: Open

Symptoms:
The base-mesh Proxy Mesh path and manually raised Fracture Preview `Remove Small Branches` control can prune tiny disconnected terminal components before simplification, but foliage/interior/shell zone policy is still not broadly tuned across real vegetation.

Likely cause:
The current fix targets branchy base meshes specifically and does not replace the need for real-sample proxy quality comparison.

Current workaround:
Keep QEM as the Proxy Mesh backend. Treat percentage-based base-mesh connected-component pruning as a targeted priority rule, not full vegetation-aware proxy zoning. Fracture Preview defaults this control to zero so fracture diagnostics keep complete branch geometry unless the operator intentionally raises it.
For base meshes made from near-coincident generator sections, enable
`Fuse Base Mesh Vertices`; it welds at one millimeter after component pruning
and before QEM. This improves seam continuity but does not guarantee that QEM
can reach its requested budget on every disconnected source.

Do not repeat:
Do not treat shell/interior/outside importance, foliage coverage, or lighting usefulness as fully validated.

Related files:
- `docs/raw/KNOWN_PROBLEMS.md`
- `src/xml_to_usda/proxy_mesh_service.py`

## Bug: Generic source-model JSON cache is too slow for very large trees

Status: Open

Symptoms:
Large source models can take longer to serialize into the generic worker-payload JSON cache than to parse and normalize from XML.

Likely cause:
The generic cache recursively encodes full dataclass graphs into JSON. That format is useful for safe worker exchange, but inefficient as a large source-model cache.

Current workaround:
Proxy Mesh source loading uses a dedicated typed Proxy Source Projection cache.
Fracture Preview bypasses the generic cache and reloads XML in its fresh native
worker. Normal conversion callers still use the existing generic cache until a
faster typed cache is justified for the full source model. Runtime cache
maintenance bounds generic source-model and Proxy Source Projection cache
growth and removes legacy Fracture Preview cache files.

Do not repeat:
Do not re-enable generic worker-payload JSON caches for Proxy Mesh or Fracture
Preview source models. Keep workflow caches narrow unless that workflow starts
using additional source facts directly.
Do not add another persistent source-facts cache without registering it in
`cache_maintenance.py`.

Related files:
- `src/xml_to_usda/canonical_loader.py`
- `src/xml_to_usda/cache_maintenance.py`
- `src/xml_to_usda/fracture_preview_service.py`
- `src/xml_to_usda/worker_file_protocol.py`
- `src/xml_to_usda/proxy_source_projection.py`
- `src/xml_to_usda/proxy_mesh_service.py`

## Bug: Piece-local UDIM real-sample coverage is incomplete

Status: Unverified

Symptoms:
Piece-local UDIM isolation is covered by tests and the baseline sample, but not by a wider real tree/shrub/grass matrix.

Likely cause:
The current work closed the overwrite bug, not the breadth gap.

Current workaround:
Keep treating the behavior as validated on the current baseline only.

Do not repeat:
Do not generalize from one sample when a broader matrix is still pending.

Related files:
- `docs/raw/KNOWN_PROBLEMS.md`
- `src/xml_to_usda/udim_resolver.py`
- `src/xml_to_usda/material_resolver.py`
- `src/xml_to_usda/assembly_resolution.py`

## Limitation: Non-mesh LeafReferences hosts with non-zero Object transforms are unverified

Status: Fail-loud

The observed real samples establish Object-local `LeafReferences` when the same
Object carries `Points` and `Triangles`, and establish equivalent local/world
positions when a non-mesh host has zero `Abs*`. No real sample currently
establishes the position space of a non-mesh LeafReferences host with non-zero
`Abs*`.

Current behavior:
Normalization rejects that ambiguous shape instead of guessing and emitting
misplaced repeated geometry. The likely next step is to retain the smallest
real SpeedTree export that demonstrates the missing shape, then extend the
explicit transform contract from that evidence.

Related files:
- `src/xml_to_usda/normalizer.py`
- `src/xml_to_usda/proxy_source_projection.py`

## Resolved: Proxy Box/Capsule collision imports in UE 5.7.x

Status: Resolved (2026-08-08)

Proxy USDA authors baked `UBX_ProxyMesh_*` or `UCP_ProxyMesh_*` guide siblings.
Manual UE 5.7.x import confirmed that both variants attach as simple collision
to the Proxy Static Mesh. Automated tests retain geometry, naming, worker
transport, and USDA structure coverage. Continue to omit USD Physics APIs.

Related files:
- `src/xml_to_usda/proxy_collision.py`
- `src/xml_to_usda/collision_primitives.py`
- `src/xml_to_usda/proxy_mesh_service.py`

## Bug: Base-tree child branches can detach from Dual Skinning deformation

Status: Mitigated by Skinning Quality 2-4; runtime cost still unmeasured

Symptoms:
A child branch whose first joint starts inside a parent bone segment follows
the parent's rigid joint transform, while nearby parent geometry follows a
linear blend of that joint and its parent. During bending, the child root can
separate from or stretch away from the deformed parent surface. Unreal's long
same-colour bone line is the hierarchy edge from the parent joint origin to the
child joint origin; it exposes the mismatch but is not an extra source bone.

Cause:
Current base-mesh Dual Skinning restarts at every source bone: a child segment
starts with 100% parent-joint influence. It does not inherit the parent
segment's blended deformation at the attachment position. The supplied
`SkeletonTest_01.xml` confirms cross-generator child starts throughout parent
segments, not only at their endpoints.

Likely fix:
Propagate the attachment-position influence vector into the child segment and
interpolate from that vector toward the child joint. This requires up to three
influences at one branch level and four at the next. The same inherited vector
now drives Repeated Parts at qualities 3/4, but their wider binding still needs
UE 5.7.x import/runtime validation.

Next step:
Retain the new two-weight collar as the default and compare quality 1-4 on
representative trees, grass, and ferns in UE 5.7.x. Record GPU skinning cost and
confirm that the USD importer preserves widths 3/4 on deeper branch levels.

Related files:
- `src/xml_to_usda/skeleton_processing.py`
- `src/xml_to_usda/authoring_validation.py`
- `tests/test_skeleton_processing.py`

## Resolved: Root-fixed repeated parts failed Skinning Quality 2-4

Status: Resolved (2026-08-13)

Observed SpeedTree exports use `BoneID=-1` for root-fixed Base Mesh vertices
and `LeafReferences` near the trunk base. Base Mesh normalization already
mapped this sentinel to `root`, but Repeated Parts produced the nonexistent
joint `bone_-01`; inherited skinning then failed on the first such Part.

Canonical normalization now maps the sentinel to source bone `0`/`root` for
both payload types. Source-model and Proxy Source Projection cache schemas were
advanced so stale unresolved bindings cannot survive the fix. The regression
test applies four-weight skinning to a `LeafReferences BoneID=-1` attachment.

Related files:
- `src/xml_to_usda/normalizer.py`
- `src/xml_to_usda/canonical_loader.py`
- `src/xml_to_usda/proxy_source_projection.py`
- `tests/test_normalizer.py`
