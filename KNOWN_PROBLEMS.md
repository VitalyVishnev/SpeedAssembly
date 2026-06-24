# Known Problems

## Worker Request Origin Constraint Pending

- Issue: Worker request/result/event payloads no longer use `pickle`, but helper commands still accept any readable JSON request path supplied on the command line.
- Location: `src/xml_to_usda/worker_file_protocol.py`, `src/xml_to_usda/conversion_worker_subprocess.py`, `src/xml_to_usda/proxy_mesh_worker_subprocess.py`, `src/xml_to_usda/fracture_worker_subprocess.py`, `src/xml_to_usda/fbx_worker_subprocess.py`
- Reason for deferral: The current pass removed the code-executing deserialization sink. Request origin constraints need a separate parent-created token/root contract so packaged workers do not reject legitimate temp files.
- Likely next step: Add a parent-generated nonce or runtime workspace root check to worker requests and validate it before reading source/output paths.

## FBX Payload Cache Pickle Hardening Deferred

- Issue: Persistent FBX payload cache entries are still serialized and loaded with `pickle`.
- Location: `src/xml_to_usda/fbx_payload_cache.py`
- Reason for deferral: The current security hardening pass intentionally excluded persistent cache deserialization; cache poisoning requires write access to the runtime cache and a matching cache key.
- Likely next step: Replace the persistent cache payload format with a non-executing typed format such as `.npz` or structured JSON plus binary arrays, then add a malicious-cache regression test.

## Qt Shell Preset And Preview Cache Ownership Pending

- Issue: `MainWindow` still owns preset dialog orchestration and Proxy Mesh preview cache lifecycle. Phase 4 only extracted diagnostics bundle request construction and removed an obsolete dependency entry; a broader controller split was deferred.
- Location: `src/xml_to_usda/qt_ui/window.py`
- Reason for deferral: Current preset handling is tightly coupled to dialogs/widgets, and preview cache state does not yet have enough shared lifecycle behavior to justify a separate controller without creating a shallow abstraction.
- Likely next step: Revisit when a concrete preset workflow change or a second preview-cache consumer appears; then extract only the behavior that hides real complexity behind a smaller interface.

## Normalizer Hot Path Broader Profiling Pending

- Issue: The remaining normalizer hot path is still object extraction and face-varying authoring.
- Location: `src/xml_to_usda/normalizer.py`
- Reason for deferral: The packed-point / packed-triangle child-scan rewrite was slower on `BigSpruce`, and vertex-skinning loop simplification did not produce a stable win. Caching object child nodes and precomputing leaf reference transforms also lost on `BigSpruce`.
- Likely next step: Profile across more than one real sample and look for a structural change, not another local loop tweak.

## Synthetic Contract Fixture Replacement Pending

- Issue: Some contract fixtures are synthetic and not verified real SpeedTree exports.
- Location: `tests/data/leafrefs_on_trunk.xml`, `tests/data/leafrefs_on_branch_levels.xml`, `tests/data/invalid_leaf_bone.xml`, `tests/data/missing_leaf_refs.xml`, `tests/data/missing_skeleton.xml`, `tests/data/non_default_metadata.xml`
- Reason for deferral: They intentionally encode error, warning, and edge-case branches that are hard to source from a single observed SpeedTree sample.
- Likely next step: Replace any fixture with a real export if one becomes available; otherwise keep the smallest fixture that expresses the contract cleanly.

## Fracturing UE Runtime Validation Pending

- Issue: Fracture Preview and export are stable enough on the dense Spruce sample for iteration, but the final runtime replacement workflow has not yet been validated in UE 5.7.x with vehicle impact/destruction behavior.
- Location: `src/xml_to_usda/fracture_service.py`, `src/xml_to_usda/fracture_export_service.py`, `src/xml_to_usda/fracture_preview_service.py`, `src/xml_to_usda/qt_ui/fracture_preview.py`
- Reason for deferral: UE runtime replacement requires an engine scene and destruction test harness, not just USDA import or Qt preview.
- Likely next step: Import the intact tree and exported fracture pieces into UE 5.7.x, replace the skeletal tree with the root-pivoted Static Mesh Assembly pieces at runtime, and compare neutral-pose visual alignment.

## Automatic Fracture Priority Policy Pending

- Issue: Automatic Fracture can still split simple trunks unevenly because cut priority is not yet based on skeleton path trunk/branch structure.
- Location: `src/xml_to_usda/fracture_service.py`
- Reason for deferral: Current pass fixed collision stability/performance; replacing automatic cut priority is a separate planner change.
- Likely next step: Use ordered skeleton paths to split large branches from trunk first, then split trunk/branches by preserve-trunk bias and even path distance.

## Fracture Collision UE Import Validation Pending

- Issue: Fracture collision generation now authors UE-style `UCX_`, `UCP_`, and `USP_` mesh names in per-piece Static Mesh Assembly USDA files, but USD/Interchange recognition as collision has not yet been manually validated in UE 5.7.x.
- Location: `src/xml_to_usda/fracture_collision.py`, `src/xml_to_usda/fracture_export_service.py`, `src/xml_to_usda/usda_authoring.py`, `src/xml_to_usda/qt_ui/fracture_preview.py`
- Reason for deferral: Epic documents these names for FBX static mesh import, but the project still needs an actual UE 5.7.x USD/Interchange import check to prove the meshes are consumed as collision and not imported as visible geometry.
- Likely next step: Export one fracture piece for each collision mode, import through UE 5.7.x Interchange USD, inspect Static Mesh collision view and scene visibility, then either mark the naming contract validated or keep collision export disabled by default.

## Fracturing Cut-Plane Geometry Refinement Pending

- Issue: Fracture export and preview can generate deterministic boundary-loop triangle-fan caps, but Base Mesh partitioning still uses whole-face ownership/centroid side tests. It does not split triangles that cross an intended cut plane or create boolean-accurate interior surfaces.
- Location: `src/xml_to_usda/fracture_geometry.py`, `src/xml_to_usda/fracture_service.py`, `src/xml_to_usda/fracture_export_service.py`
- Reason for deferral: Boundary caps are enough for first inspection/export parity, while true cut-plane clipping needs a separate mesh refinement pass and UE validation.
- Likely next step: Add cut-plane triangle splitting for manual segment and automatic cut sites, then feed those new boundary loops into the existing cap generation path.

## Fracturing Closely Spaced Manual Cuts Need Rejection

- Issue: If two manual fracture cuts are placed too close together, the planner can still fail to build a non-empty mesh for one of the pieces and report that the mesh was not generated.
- Location: `src/xml_to_usda/fracture_service.py`, `src/xml_to_usda/fracture_geometry.py`
- Reason for deferral: The current planner is now stable and the remaining issue is a geometry validity rule for cut spacing and empty-piece rejection, not a crash fix.
- Likely next step: Reject or merge cuts that collapse a piece below the minimum face budget before cap generation and preview authoring start.

## Fracturing Synthetic Cut Instance Assignment Pending

- Issue: The fracture planner can synthesize deterministic mid-segment base-face splits for safe pieces without repeated instances, allowing a single long trunk to split roughly in half when the hierarchy has no usable joint cut site. It still does not split a segment that owns repeated parts, because assigning those instances to one side of an intra-bone cut requires spatial side classification instead of skeleton ownership alone.
- Location: `src/xml_to_usda/fracture_service.py`
- Reason for deferral: Repeated-part side assignment inside one skeleton segment is a separate geometric classification problem; guessing it would break the root-pivoted static assembly contract.
- Likely next step: Add split-plane side tests for repeated-part instance origins/bounds and reject ambiguous instances loudly instead of assigning by fallback.

## Manual Segment Fracture Cut Repeated-Part Classification Pending

- Issue: Manual `parent->child@t` cuts split Base Mesh by whole-face centroid projection and assign repeated parts by existing skeleton binding. They do not spatially classify repeated-part bounds across the selected segment.
- Location: `src/xml_to_usda/fracture_service.py`, `src/xml_to_usda/fracture_export_service.py`, `src/xml_to_usda/qt_ui/fracture_preview.py`
- Reason for deferral: Repeated-part side assignment inside one skeleton segment is separate from Base Mesh cap generation and must not guess when bounds cross the cut.
- Likely next step: Add repeated-part origin/bounds side tests and reject ambiguous instances loudly.

## UDIM Real-Sample Coverage Pending

- Issue: UDIM authoring is covered by automated tests and the current baseline UE 5.7.x sample, but repeated-part and FBX material-slot UDIM rows have not yet been validated across a broad set of real SpeedTree structures.
- Location: `src/xml_to_usda/udim_resolver.py`, `src/xml_to_usda/material_resolver.py`, `src/xml_to_usda/qt_ui/panels.py`
- Reason for deferral: Real-sample UE import and material inspection requires a separate validation matrix beyond the current automated regression surface.
- Likely next step: Run `write_secondary_uv_offset` and `shift_primary_uv` on base XML materials, repeated-part black/white buckets, and FBX material-slot rows across the same tree/shrub/grass sample set used for Phase 1 breadth validation.

## Proxy Mesh Distance Field And Shadow Validation Pending

- Issue: The generated `_proxy.usda` asset now imports into UE as a Static Mesh, but distance-field generation and low-cost shadow usefulness have not yet been validated against UE 5.7.x scene lighting.
- Location: `src/xml_to_usda/proxy_mesh_service.py`
- Reason for deferral: UE distance-field and shadow inspection is outside the current automated test harness.
- Likely next step: Export sparse and dense tree proxy samples, enable distance-field visualization in UE 5.7.x, and record whether volume and silhouette are sufficient.

## Proxy Mesh Simplification Quality Pending

- Issue: `density_field` now keeps base geometry direct, builds foliage volume from instanced kernels, and extracts a shared topology before QEM, but simplification quality has not yet been compared across sparse trees, dense crowns, grass, and moss samples.
- Location: `src/xml_to_usda/proxy_mesh_service.py`
- Reason for deferral: The preview/export loop is working, but method quality needs real vegetation comparison instead of synthetic unit-test evidence.
- Likely next step: Use the OpenGL proxy preview and UE static mesh import on at least one sparse tree and one dense tree, then decide whether `fast-simplification` remains the release backend or becomes a replaceable baseline.

## Proxy Mesh Zoned Simplification Pending

- Issue: The current `density_field` method runs QEM on the extracted proxy surface as one mesh; it does not yet apply separate `shell`, `interior`, and `outside` importance zones.
- Location: `src/xml_to_usda/proxy_mesh_service.py`
- Reason for deferral: The first implementation pass needed a deterministic preview/export loop and a shippable Windows QEM backend before tuning zoned importance rules against real vegetation.
- Likely next step: Classify density-field cells/faces by silhouette contribution and weak isolated features, then either protect shell triangles before QEM or split simplification passes by zone.

## UDIM Piece-Local Real-Sample Coverage Pending

- Issue: Piece-local UDIM isolation is covered by automated tests and the current baseline sample, but it has not yet been validated across a wider set of real SpeedTree structures with different base/prototype material layouts.
- Location: `src/xml_to_usda/udim_resolver.py`, `src/xml_to_usda/material_resolver.py`, `src/xml_to_usda/assembly_resolution.py`
- Reason for deferral: the current change closed the cross-piece overwrite bug; the remaining work is broader sample coverage, not a known logic failure.
- Likely next step: run the piece-local UDIM cases on base geometry, repeated parts, and FBX slot prototypes across the real tree/shrub/grass sample matrix already used for breadth validation.
