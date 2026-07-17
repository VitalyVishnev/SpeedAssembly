# Known Bugs

## Bug: Generic source-model caching can crash while serializing a very large tree

Status: Open

The former Big Spruce cache regression triggered `0xC0000005` in Python while
the generic worker-payload encoder serialized the model. The normal cache
contract now uses Simple Tree, so the default suite remains stable; this does
not prove generic full-model caching is safe at Big Spruce scale.

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
SimpleTree, multi-stem stump cuts, and packaged stability smoke. Broader visual
validation across unrelated SpeedTree assets and Unreal import remains pending.

Related files:
- `src/xml_to_usda/boolean_fracture_prototype.py`
- `src/xml_to_usda/fracture_preview_service.py`
- `src/xml_to_usda/fracture_export_service.py`

This page stores current bugs, limitations, and validation gaps. It should stay focused on dangerous or still-open issues.

## Bug: Fracture Preview worker could access-violate during cached mesh reconstruction

Status: Resolved in code; packaged/operator stress remains pending

Symptoms:
The packaged persistent worker sometimes exited with `0xC0000005` inside
`_mesh_from_arrays`. Disabling cyclic GC reduced but did not eliminate it; the
same failure recurred while switching Detailed Cuts off on Big Spruce.

Current behavior:
Fracture Preview no longer reads or writes the typed `.npz` source-model cache.
A clean worker loads XML once, then the persistent server reuses the slim model
and analysis cache in memory for later settings changes. Local Big Spruce cold
loading changed from about 0.50 s to 0.79 s, removing the failing native path
for a roughly 0.29 s one-time cost.

Do not repeat:
Do not restore a disk source-model cache for this worker without a packaged
stability result that justifies crossing the NumPy/PyInstaller boundary. Do
not kill/restart native preview workers for every slider tick.

Related files:
- `src/xml_to_usda/fracture_worker_subprocess.py`
- `src/xml_to_usda/fracture_preview_service.py`
- `src/xml_to_usda/qt_ui/preview_jobs.py`
- `src/xml_to_usda/qt_ui/background_jobs.py`

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
Missing Autodesk FBX SDK bindings, a non-rigid FBX, unreadable mesh payloads, missing vertex colors, or an SDK vertex-color access error.

Current workaround:
Use a rigid FBX with readable polygon mesh data and vertex colors. Strict `vertex_color_split` retries once in a fresh worker process before surfacing the final error.

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
contract. Local Big Spruce profiling still identifies cutter noise generation
and attribute transfer as the main regeneration costs; the Boolean operation
itself is comparatively small. Outer multi-process execution remains disabled
until it demonstrates at least 25% speedup without excessive RSS or packaged
native instability.

Do not repeat:
Do not enable a thread pool around Python bindings: the binding does not release
the GIL and the wheel already uses internal oneTBB parallelism.

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
Fracture Preview bypasses the generic cache and reuses its slim source model in
the persistent worker only. Normal conversion callers still use the existing
generic cache until a faster typed cache is justified for the full source
model. Runtime cache maintenance bounds generic source-model and Proxy Source
Projection cache growth and removes legacy Fracture Preview cache files.

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
