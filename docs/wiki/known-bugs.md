# Known Bugs

Current defects, fail-loud limits, and validation gaps only. Resolved crash
history lives in [Encountered Crashes](encountered-crashes.md); rejected fixes
and benchmark detail live in [Experiments](experiments.md).

## Limitation: UE 5.7 foliage orientation requires a dedicated Skeleton

Status: Fail-loud

The in-place Asset Action refuses a Skeletal Mesh whose Skeleton Asset is
shared. Updating that pose would also alter unselected meshes, while UE 5.7
Python cannot safely replace it. Use a dedicated Skeleton per vegetation mesh.
The pure-Python repair requires two commits to preserve exact bone names;
animation, sockets, Physics Assets, and reimport remain operator checks.

Related:
- `scripts/ue57_fix_selected_foliage_bones.py`
- [Experiments](experiments.md#experiment-reorient-an-imported-ue-skeletal-mesh-without-reimport)

## Limitation: Wind Auto Hierarchy assumes immediate preorder continuation

Status: Unverified outside conforming SpeedTree order

Generator Continuation is the lowest-index direct child, but Wind Preview
currently recognizes it only at `parent index + 1`. This matches observed
SpeedTree preorder; a reordered external skeleton may differ from the UE repair.
Retain a real counterexample before generalizing the implementation.

Related:
- `src/xml_to_usda/wind_viewport_scene.py`
- `scripts/ue57_fix_selected_foliage_bones.py`

## Bug: Generic full-model cache is unsafe and slow on very large trees

Status: Open; avoided by typed projection and fresh-worker paths

Big Spruce triggered `0xC0000005` during generic JSON serialization and once
reconstructed a `Vector3` where a face-owner tuple was expected. Even successful
large-model serialization can cost more than XML parsing and normalization.
Proxy Mesh therefore uses its typed projection cache; Fracture Preview reloads
XML in a fresh worker. Normal conversion still uses the generic cache.

Do not restore this cache for Proxy or Fracture, or add another persistent cache
without registering it in `cache_maintenance.py`. Replace the generic format
only when a real conversion workflow justifies and stress-validates it.

Related:
- `src/xml_to_usda/canonical_loader.py`
- `src/xml_to_usda/worker_file_protocol.py`
- `src/xml_to_usda/proxy_source_projection.py`
- `tests/test_canonical_loader_cache.py`

## Risk: Fracture native and viewport stability lacks broad operator confirmation

Status: Mitigated; native root cause partly unverified

Fresh workers contain Detailed Cuts native state. Qt uploads only from
`paintGL`, and Repeated Parts use hardware instancing. Packaged stress gates
pass, but earlier failures produced incomplete dumps and one current incident
still has ambiguous host/application ownership. Treat recurrence as a crash
investigation: retain build ID, worker stderr, and matching WER evidence before
changing code.

Do not restore a persistent Detailed Cuts worker, disk source-model cache,
callback-side OpenGL upload, or flattened instance geometry.

Related:
- [Encountered Crashes](encountered-crashes.md#cr-008---per-instance-opengl-command-loop-after-preserved-instancing)
- [Encountered Crashes](encountered-crashes.md#cr-011---intermittent-cross-process-access-violations-after-fresh-worker-isolation)
- `src/xml_to_usda/fracture_worker_subprocess.py`
- `src/xml_to_usda/qt_ui/viewport.py`

## Limitation: Detailed Boolean cuts need broader real-tree validation

Status: Partially verified

Preview/export, attachment ownership, normals, collision inputs, synthetic
geometry, SimpleTree, multi-stem cuts, and packaged stability are covered.
Unrelated SpeedTree assets and UE import/runtime behavior still need a wider
visual matrix.

Related:
- `src/xml_to_usda/boolean_fracture_prototype.py`
- `src/xml_to_usda/fracture_export_service.py`

## Limitation: Detailed ownership has no geometric answer outside the cutter

Status: Deliberate fallback

An eligible Repeated Part is classified geometrically only when its pivot
projects inside the cutter triangles. Outside that finite projection it keeps
skeleton ownership. Nearest-edge/global-noise extrapolation was rejected: on
Big Spruce it moved 230 parts where only 88 had cutter support. A remaining
visual defect requires an explicit source attachment-point contract.

Related:
- `src/xml_to_usda/boolean_fracture_prototype.py`
- `tests/test_boolean_fracture_prototype.py`

## Limitation: Detailed Cut cost grows with cut count and density

Status: Open performance limit

Prepared sessions substantially reduce repeat work, but cutter generation and
attribute transfer still scale with selected cuts and Cut Detail. Production
remains sequential: measured thread variants were neutral/slower, and Windows
spawn pools were slower while adding hundreds of MiB of child RSS. Revisit
parallelism only after removing its cold-start and serialization boundary.

Related:
- `src/xml_to_usda/boolean_fracture_prototype.py`
- [Experiments](experiments.md)

## Bug: FBX prototype replacement can fail before export

Status: Open

Rigid FBX replacement still depends on Autodesk bindings, readable polygon and
vertex-color data, and native binding stability. WorldTree exposed intermittent
`FbxVector2` access failures under helper concurrency; remaining payloads now
retry with lower concurrency and a repeated single-helper failure surfaces.
Preview/import transforms avoid the unstable per-point `MultT` call. Use a
rigid FBX with vertex colors; never infer replacement from XML `LOD/@Filename`.

Related:
- `src/xml_to_usda/fbx_adapter.py`
- `docs/raw/local-python-environment.md`

## Validation gap: Fracturing in UE 5.7.x

Status: Unverified

USDA generation and dense-sample preview stability do not prove runtime piece
replacement. Likewise, `UCX_`/`UCP_`/`USP_` naming does not prove that the
USD/Interchange path attaches Fracture collision. Keep runtime replacement and
collision provisional until tested in a UE scene and destruction harness.

Related:
- `src/xml_to_usda/fracture_export_service.py`
- `src/xml_to_usda/fracture_collision.py`

## Validation gap: UDIM breadth

Status: Unverified beyond current samples

General and piece-local UDIM contracts are covered by automated tests and the
baseline sample, not a broad tree/shrub/grass UE matrix. Do not generalize that
evidence until material inspection covers representative real exports.

Related:
- `src/xml_to_usda/udim_resolver.py`
- `src/xml_to_usda/material_resolver.py`
- `src/xml_to_usda/assembly_resolution.py`

## Validation gap: Proxy Mesh visual and lighting quality

Status: Open

Proxy USDA import and Box/Capsule collision are confirmed. Distance-field and
low-cost shadow behavior are not. Density/QEM quality, component pruning, and
optional one-millimeter base-mesh welding also need comparison across sparse
trees, dense crowns, grass, and moss. These controls are targeted policies,
not general foliage/interior/shell zoning.

Keep QEM until representative comparisons justify a replacement. Do not infer
lighting usefulness or topology quality from successful import.

Related:
- `src/xml_to_usda/proxy_mesh_service.py`
- `src/xml_to_usda/mesh_pruning.py`

## Limitation: Non-mesh LeafReferences transform space is unresolved

Status: Fail-loud for non-zero host transforms

Observed samples establish Object-local `LeafReferences` on mesh hosts and
equivalent local/world positions on zero-transform non-mesh hosts. No real
sample establishes a non-mesh host with non-zero `Abs*`. Normalization rejects
that shape rather than guessing. Extend the contract only from a retained real
SpeedTree export.

Related:
- `src/xml_to_usda/normalizer.py`
- `src/xml_to_usda/proxy_source_projection.py`

## Validation gap: Skinning Quality 2-4 in UE

Status: Code-mitigated; runtime cost and wider bindings unverified

Quality 2 adds a two-weight collar at child attachments; qualities 3/4 inherit
ancestor deformation for Base Mesh and Repeated Parts. Automated invariants
pass, but representative UE 5.7.x tests must confirm runtime appearance, GPU
cost, and importer preservation of three-/four-weight Part bindings.

Related:
- `src/xml_to_usda/skeleton_processing.py`
- `src/xml_to_usda/authoring_validation.py`
- `tests/test_skeleton_processing.py`
