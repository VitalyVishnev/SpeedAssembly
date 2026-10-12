# UE 5.8 PVE mesh extraction and wind grouping

Inspected 2026-10-12. Evidence: local UE source, not a new editor/runtime test.
`Engine/Build/Build.version` identifies the inspected tree as 5.8.2,
CompatibleChangelist 55116800. Root:
`D:/3D Personal/ue5.8 source/UnrealEngine/Engine/`.
The duplicate tree under `ue5.8 source/New folder/` has identical SHA-256
for `PVImportHelpers.cpp` and `PVBoneFacade.cpp`.

PVE reconstructs **whole branch curves and their parent relationships** before
creating animation bones. Its automatic Dynamic Wind groups are **radius
classes**, not branch hierarchy levels. These are separate algorithms.

## Source navigation

Paths below are relative to `Engine/`.
PVE = `Plugins/Experimental/ProceduralVegetationEditor/Source/`.

| File inside PVE | Relevant entry points / lines |
| --- | --- |
| `ProceduralVegetation/Private/Nodes/PVExtractFromMeshSettings.cpp` | `ExecuteInternal`, node calls static-mesh importer |
| `ProceduralVegetation/Private/Params/PVImportStaticMeshParams.h` | source asset, material slot filter, debug stages |
| `ProceduralVegetation/Private/Implementations/PVImporter_StaticMesh.cpp` | centers/radii 118; collapse 442; endpoints 462; connection/tracing 528; roots 952; pipeline 981 |
| `ProceduralVegetation/Private/Helpers/PVImportHelpers.cpp` | root distance 89; tracing 152; continuation/hierarchy 258; branch descriptions 643; hierarchy depth 1034; Growth Data 1183 |
| `ProceduralVegetation/Private/Helpers/PVAttributesHelper.cpp` | `GetBranchPointScale`, 46 |
| `ProceduralVegetation/Private/Facades/PVBoneFacade.cpp` | simulation groups 193; bone creation 251 |
| `ProceduralVegetation/Private/Nodes/PVBoneReductionSettings.cpp` | bone creation and storage, 86 |
| `ProceduralVegetationEditor/Private/Helpers/PVExportHelper.cpp` | per-bone group assignment 1336; bone creation fallback 1402; wind import/settings 1596 |

Wind importer:
`Plugins/Experimental/DynamicWind/Source/DynamicWindEditor/Private/DynamicWindImportData.cpp`,
`ImportSkeletalData`, 9; same-group ancestry processing, 106.

## Extract from Mesh

1. Convert the Static Mesh into `FDynamicMesh3`. Retain triangles using the
   selected material **slot names** and remove unused vertices. Foliage is not
   identified botanically; the operator supplies the structural material mask.
2. Read normals from the mesh normal overlay, or compute vertex normals.
   For each connected triangle component, cast from each vertex opposite its
   normal. Ignore triangles incident to that vertex. Accept the nearest hit
   only when the opposing normal dot product is below -0.5. Center is the
   midpoint; radius is half the distance.
3. If the ray fails, query the nearest vertex near samples 100, 50 and
   33.33 cm opposite the normal. Require opposing normals, project onto the
   opposing plane, then take midpoint/radius. Reject estimates above three
   times the component's mean positive radius. Vertices with no accepted
   estimate retain zero radius and their original position.
4. Collapse the displaced mesh per component. Process larger radii first,
   fuse nearby vertices using a search radius of twice the current radius and
   an additional combined-radius overlap test for positive-radius neighbors.
   Auxiliary filler triangles let the Dynamic Mesh represent line segments;
   filler vertices are excluded from skeletal tracing.
5. Identify endpoints from neighbor directions. The largest coordinate-wise
   spread of normalized outgoing directions must be at most 1.0. This is a
   geometric test, not merely a count of neighbors. Endpoints within the lowest
   10% of the Z bounding-box height become roots.
6. For detached components, collect possible endpoint-to-edge attachments
   where distance is at most 1.25 times the sum of interpolated target radius
   and endpoint radius. Start from root components; attach outward one BFS
   level at a time. Prefer edges already on a traced path, otherwise use the
   closest valid candidate. Split edges and merge endpoints, then retrace after
   each level. One already-connected component skips attachment.
7. Compute shortest accumulated edge distance from roots by repeated distance
   relaxation. Trace reachable endpoints toward decreasing root distance,
   minimizing neighbor root distance plus segment distance. Traces merge into
   shared parent paths. Unreachable endpoints are skipped.
8. Walk the traced hierarchy outward and choose a continuation at each fork.
   Keep that continuation in the current branch curve; start other children
   as new branch curves with explicit parent-branch indices.
9. Convert curves to Growth Data with positions, radii and branch ancestry.
   A trunk has `branchHierarchyNumber = 0`; a child branch gets parent depth
   plus one. Additional points along the same branch do not increase depth.

The node returns `UPVGrowthData`, not a finished Skeletal Mesh or a skinning
transfer onto the original mesh. Downstream Mesh Builder constructs geometry;
Bone Reduction or Export builds animation bones and bindings.
This distinction also appears in
[Epic's PVE documentation](https://dev.epicgames.com/documentation/unreal-engine/procedural-vegetation-editor-pve-in-unreal-engine).

## Continuation at a fork

`ExtractBranchHierarchies::FindBestParentPoint` uses:

```text
incoming = normalize(current_position - previous_position)
outgoing_i = normalize(child_i_position - current_position)
D_i = (1 + dot(incoming, outgoing_i)) / 2
L_i = max_reachable_endpoint_root_distance_in_child_subtree
      - child_i_root_distance
score_i = D_i + L_i / sum(L_j)
```

If the length sum is below `UE_SMALL_NUMBER`, every normalized length is zero.
The first strictly highest score wins. A single child continues directly.
`L_i` excludes the edge from the current point to that child. The function
reads `CurrentRadius` but does not use it in the score.
This favors directional continuity and remaining descendant path length.
It is not a botanical classification or proof of the original generator line.

There is an explicit root limitation: if several outgoing hierarchies start
at one root point, retain only the candidate with the most branch records.
The source TODO says multiple branches starting at a root are not handled.
Multiple separately detected root points are processed separately.

## Dynamic Wind groups

`FBoneFacade::CreateBoneData` calls `SetWindSimulationData` by default.
Bone Reduction calls this before storing bones; Export calls it when the
collection has no previously created bones. Extraction itself does not assign
the simulation groups.

For every branch, obtain its base radius through `GetBranchPointScale`.
Let `r_min` and `r_max` be extrema over **all branches in the collection**:

```text
q_i = map_clamped(r_i, [r_min, r_max], [1, 0])
for each branch i in collection order:
    if parent_i is valid and parent_i > 0:
        q_parent_i = min(q_i, q_parent_i)
group_i = RoundToInt32(2 * q_i)
```

Non-degenerate radii therefore produce group indices 0, 1 or 2. Thick branches
tend toward 0, thin branches toward 2. Degenerate input ranges follow Unreal's
range-mapping implementation. This code never reads `branchHierarchyNumber`.
Despite the local name `LogicalDepth`, the value is a quantized radius class.
The parent correction is one forward pass, skips branch index 0, and is not
a recursive hierarchy-depth calculation or a guaranteed bottom-up propagation.

At a fused child junction, the shared first point can carry the parent's
radius. `GetBranchPointScale` estimates the child's base from its next radii,
using `S1 + (S1 - S2) / PI` when a third point exists, with fallback behavior
for non-positive estimates. Thus grouping does not blindly use the parent's
junction radius in UE 5.8.

`BuildWindImportData` assigns every bone the simulation group of its owning
branch. The synthetic global Root has no branch and gets INDEX_NONE.
Group **parameters**, including `bIsTrunkGroup`, come from `UPVWindSettings`
or retained target-mesh settings. A group index of 0 does not itself enable
the Trunk flag. Missing group settings are padded by the Dynamic Wind importer
with Influence 1; their default Trunk flag is false.

The Dynamic Wind importer matches bone names and consumes assigned group
indices. It does not reclassify the mesh or discover a trunk. It walks ancestors
while their group is equal, recording chain origins and counts. Same-group
forks can consequently share one chain record; this is not independent logical
branch segmentation.

## UE 5.7 comparison and SpeedAssembly implications

UE 5.7 `PVBoneFacade.cpp:195` already uses the same min/max radius mapping,
parent correction and three-class rounding. It reads the first point's scale
directly; UE 5.8 uses the branch-aware radius helper. There is no evidence here
of a new hierarchy-based wind classifier or measured superior grouping.

SpeedAssembly `wind_viewport_scene.py::_branch_continuation_child` recognizes
ordered continuation only when the lowest-index child is at parent index + 1.
Otherwise, optional Continue line uses endpoint coincidence. The maintained
[known limitation](known-bugs.md#limitation-wind-auto-hierarchy-assumes-immediate-preorder-continuation)
already records this mismatch with the more general lowest-direct-child-index
SpeedTree contract. It can increase inferred branch order on reordered rigs;
whether it caused the operator's current asset issue is **Unverified**.

For external rigs without meaningful source order, PVE's direction/length score
is a candidate for explicit geometric branch segmentation. It would require
valid physical directions, handling zero-length/coincident joints, stable tie
breaking, and a reference asset comparison. Do not silently substitute it for
the source-backed SpeedTree Generator Continuation contract. Copying PVE's
radius bins would not fulfill a request for trunk / branch / subbranch levels.

Quality on the operator's mesh, end-to-end PVE export behavior, and any proposed
SpeedAssembly replacement remain **Unverified**. No engine or application code
was changed by this investigation.

Follow-up on 2026-10-12: the operator authorized an explicit comparison mode,
implemented as `Auto Hierarchy (PVE)` in Advanced Wind Settings. The original
method remains available. See
[the implementation experiment](experiments.md#pve-style-wind-hierarchy-comparison)
for physical-segment adaptation, group caps, and provisional quality evidence.
