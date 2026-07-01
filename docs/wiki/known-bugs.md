# Known Bugs

This page stores current bugs, limitations, and validation gaps. It should stay focused on dangerous or still-open issues.

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

## Bug: Automatic fracture priority still needs trunk-first ordering

Status: Open

Symptoms:
Automatic Fracture can still split simple trunks unevenly.

Likely cause:
Cut priority is not yet based on skeleton path trunk/branch structure.

Current workaround:
Use the current planner and avoid treating the automatic split order as final.

Do not repeat:
Do not assume trunk-first ordering falls out of hierarchy shape on its own.

Related files:
- `docs/raw/KNOWN_PROBLEMS.md`
- `src/xml_to_usda/fracture_service.py`

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

## Bug: Fracturing cut-plane geometry is still approximate

Status: Open

Symptoms:
Boundary caps are deterministic, but triangles crossing the intended cut plane are not truly split.

Likely cause:
The current path uses whole-face ownership and centroid side tests instead of cut-plane clipping.

Current workaround:
Use the current cap generation and do not treat it as boolean-accurate interior geometry.

Do not repeat:
Do not imply cut-plane exactness where only whole-face partitioning exists.

Related files:
- `docs/raw/KNOWN_PROBLEMS.md`
- `src/xml_to_usda/fracture_geometry.py`
- `src/xml_to_usda/fracture_service.py`

## Bug: Manual segment fracture cuts do not classify repeated-part bounds rigorously

Status: Open

Symptoms:
Manual `parent->child@t` cuts assign repeated parts by existing skeleton binding instead of spatially classifying bounds across the cut.

Likely cause:
Repeated-part side assignment is separate from base-mesh cap generation and has not been given its own bounds test.

Current workaround:
Reject ambiguous cases loudly rather than guessing.

Do not repeat:
Do not classify repeated parts by eyeballing the segment.

Related files:
- `docs/raw/KNOWN_PROBLEMS.md`
- `src/xml_to_usda/fracture_service.py`
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

## Bug: Proxy Mesh zoned simplification is not implemented

Status: Open

Symptoms:
The current proxy simplification runs QEM on one mesh instead of applying separate importance zones.

Likely cause:
The first release pass prioritized deterministic output over zoned tuning.

Current workaround:
Keep the current one-mesh QEM approach until the zone policy exists.

Do not repeat:
Do not treat shell/interior/outside importance as already implemented.

Related files:
- `docs/raw/KNOWN_PROBLEMS.md`
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

