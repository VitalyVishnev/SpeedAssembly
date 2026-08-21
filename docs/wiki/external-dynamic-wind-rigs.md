# External Dynamic Wind Rigs

## Scope

This page records the contract for using an FBX or USD skeleton with Unreal
Dynamic Wind outside the SpeedTree XML conversion path.

Advanced Wind Settings is a rig-diagnostic, skeleton-grouping, and Dynamic Wind
JSON authoring tool. Its External Skeleton path does not convert an FBX mesh to
USDA and does not repair the source. For FBX it reads the rest mesh, skin
clusters, weights, bind records, local bone frames, and source metadata. Display
Transform changes only viewport draw calls, bone segments, and bounds; it never
changes the source skeleton, mesh, joint names, group assignments, or JSON.

Evidence levels used below:

- `Validated` means reproduced in this project, OpenUSD, or UE 5.7.x.
- `Source-backed` means supported by the local Unreal plugin schema/example or
  the supplied UE-source analysis, but not reproduced in this audit.
- `Unverified` marks the unresolved PCG-specific behavior.

## Dynamic Wind rig contract

A usable rig needs all of these systems to agree:

1. Skeleton topology: unique stable joint names, valid parents, no cycles, and
   physically distributed joint pivots.
2. Bone frames: orthonormal transforms with unit scale and local +X pointing
   along the functional bone segment. This is a validated Dynamic Wind forward
   axis, not a DCC display convention.
3. Bind state: mesh, skeleton reference pose, and inverse bind matrices describe
   the same pose and transform space.
4. Skinning: every deforming vertex has valid, finite, normalized influences on
   the intended joints. Different deforming regions must not collapse onto one
   root influence.
5. Geometry: enough vertices and edge loops exist where smooth bending is
   expected. A rigid appendage may instead use one joint and rotate at its
   physical hinge.
6. Wind metadata: JSON joint names match the imported Unreal Skeleton exactly;
   groups, trunk flags, influence values, and Ground Cover mode are intentional.
7. Unreal ownership: the Skeletal Mesh used at runtime owns the imported Dynamic
   Wind asset data, and its assigned Skeleton Asset has the same reference pose.

The local +X rule and Skeleton Asset ownership are validated in UE 5.7. The
non-trunk shader also has a pole singularity when Bone Forward is exactly
parallel to Unreal +Z. Converter-authored SpeedTree assets receive a coherent
one-degree correction. External skeletons are only warned about and are never
edited.

One logical root is recommended for an independently authored wind object.
UsdSkel and this converter support multiple roots, but that does not prove that
an arbitrary multi-root layout has the intended Dynamic Wind chain semantics.

## FBX checklist

Before export:

- apply mesh and armature object transforms together; avoid negative scale,
  non-uniform bone scale, and shear;
- place the structural root at the intended asset pivot and every deform joint
  at its physical hinge;
- make local +X follow each trunk or appendage segment and keep roll continuous;
- bind only to exported deform bones, remove unused influences, normalize every
  vertex, and deliberately limit influence count;
- provide transition weights and topology only where smooth bending is wanted;
- reimport the FBX into an empty DCC scene and repeat the deformation test.

For the first Unreal diagnostic import:

- create a new Skeletal Mesh and a new Skeleton instead of reusing a merely
  name-compatible Skeleton;
- leave `Use T0As Ref Pose` and reference-pose updates disabled unless frame 0
  was deliberately authored as the skin bind pose;
- verify bone count, names, parents, positions, axes, scales, and actual Skin
  Weight visualization after import;
- manually rotate a lower, middle, branch, and terminal joint. The expected
  region must move around that joint's own pivot and return exactly to the
  reference pose;
- import the Dynamic Wind JSON onto that exact Skeletal Mesh and verify its
  joint names and simulation groups after any skeleton reimport.

The manual rotation test is the primary boundary test. If it fails, the problem
is FBX skin/bind import. If it passes directly but the same asset becomes rigid
only after PCG placement, investigate the PCG representation and runtime asset
ownership instead of changing the skeleton blindly.

## USD checklist

For plain UsdSkel correctness:

- author intentional `upAxis` and `metersPerUnit` once for mesh and skeleton;
- keep Skeleton and skinned Mesh in one coherent SkelRoot transform space;
- keep `joints`, `jointNames`, `bindTransforms`, and `restTransforms` lengths
  equal, with parents preceding children in joint-path order;
- author absolute skeleton-space bind transforms and parent-local rest
  transforms from the same pose;
- apply `SkelBindingAPI`, target the correct Skeleton, and author a correct
  `geomBindTransform`;
- keep joint indices and weights shape-compatible, set the intended primvar
  interpolation and `elementSize`, and normalize each influence tuple;
- preserve one joint order across Skeleton, mesh weights, assembly attachments,
  and Dynamic Wind metadata.

`DynamicWindSkeletonAPI` is required when wind metadata is carried in USD and
the Epic example is used to derive JSON. Its local schema defines:

- `unreal:dynamicWind:jointNames`
- `unreal:dynamicWind:jointSimulationGroups`
- `unreal:dynamicWind:simulationGroupInfluences`
- `unreal:dynamicWind:simulationGroupNumInfluences`
- `unreal:dynamicWind:simulationGroupShiftTops`
- `unreal:dynamicWind:trunkSimulationGroups`
- `unreal:dynamicWind:isGroundCover`
- `unreal:dynamicWind:gustAttenuation`

`jointNames` and `jointSimulationGroups` must have equal lengths. Epic's sample
script combines them with `zip()`, so a mismatch silently truncates the longer
array. The SpeedAssembly contract deliberately keeps wind metadata in the
separate `*_DynamicWind.json`; its USDA therefore does not need this API schema.

## SpeedAssembly USD audit

The current Skeletal Assembly authoring path contains the expected UsdSkel
structure:

- a `SkelRoot`, base `Mesh`, `Skeleton`, and `SkelAnimation`;
- `SkelBindingAPI`, `skel:joints`, and the Skeleton relationship on the mesh;
- absolute `bindTransforms`, local `restTransforms`, and matching rest-pose
  rotations/translations in `SkelAnimation`;
- per-vertex joint indices and weights with matching `elementSize` and
  `classicLinear` skinning;
- an identity `geomBindTransform` because authored mesh points and absolute bind
  transforms are already in the same stage/skeleton space.

An OpenUSD 0.25.11 audit of a fresh `SimpleTree_01` conversion opened the stage,
created valid Skeleton and Skinning queries, reconstructed 105 joint transforms,
and found equal 105-entry joint/bind/rest arrays. The 2,077 base-mesh points had
matching vertex joint-index and weight arrays. Existing source validation also
checks hierarchy, parent-before-child joint order, rigid bases, local +X,
bind/rest reconstruction, joint index ranges, influence widths, and normalized
weights before authoring.

No structural UsdSkel defect was found. The identity `geomBindTransform` remains
correct only while mesh points and bind transforms stay in that shared authored
space; any future parent-transform or external-mesh authoring path must rederive
it instead of copying the identity value.

## `TungTungTung.fbx` audit

Status: locally parsed and inspected with vendored ufbx 0.21.3; Unreal PCG
behavior not reproduced.

| Property | Observed value |
| --- | --- |
| Audited file | 506,156 bytes; SHA-256 `D5370B108512BE859D198E9DE55D079ADC647A780CD5ABFA519A0AB027A48548` |
| Producer | Blender 5.2.0 LTS FBX exporter |
| FBX metadata | binary 7.4, centimeters, Y-up |
| Skeleton | 8 unique bones, one hierarchy, distinct bind pivots |
| Mesh | 5,218 vertices, 10,448 triangles, one connected component |
| Shading data | one material, normals and one UV set; no tangents |
| Skin | one linear skin deformer, 8 clusters, no unweighted vertices |
| Influences | maximum 4; 659 vertices use 1, 2,217 use 2, 2,030 use 3, 312 use 4 |
| Bounds | about 2.99 × 6.05 × 2.43 m after interpreting FBX centimeters |

Confirmed strengths:

- The failure modes “all vertices on root,” “all joints at one origin,” and
  “one common bind matrix” are absent.
- Root dominates 999 vertices only near the base (`Y = -9.49..34.56 cm`), not
  the full mesh. The main chain owns successive vertical regions.
- `Bone.007` owns the large diagonal side region consistent with the club;
  `Bone.006` owns the small upper side region consistent with the nose.
- Main-chain world +X axes follow their child segments. Bone scales are unity
  within floating-point export noise, and ufbx reported no scene warnings.
- No segment is exactly parallel to source +Y. `Bone.005` is the closest at
  about 1.10 degrees, so the exact vertical singularity was not found.

Required cleanup:

- Normalize all skin weights before FBX export. 1,733 of 5,218 vertices differ
  from a sum of 1.0 by more than 0.01; observed sums range from `0.9340` to
  `1.0252`. Unreal may normalize imported weights, but the source asset should
  not depend on that repair.
- Replace generic names such as `Bone.006` with stable semantic names before the
  JSON becomes a durable asset contract.
- Confirm terminal `Bone.006` and `Bone.007` axes in Unreal. A terminal joint has
  no child segment, so hierarchy alone cannot certify its intended forward axis.
- Tangents are absent. Unreal can generate them, and this does not explain rigid
  wind, but the import setting should be explicit.

The file is structurally capable of regional deformation. It should not be
rebuilt merely because the PCG result was rigid. First compare the same imported
Skeletal Mesh placed directly in the level against the PCG result under the same
wind settings. If direct placement and manual joint rotation deform correctly,
the remaining defect is downstream of FBX skinning.

## Automated FBX diagnostics

The FBX report is non-blocking and does not mutate the file. It checks mesh and
rig counts, source units/up axis, parser warnings, animation and shading data;
hierarchy, coincident pivots, local scale, basis handedness, and local +X;
bind-pose coverage and cluster-matrix consistency; and unweighted, invalid,
non-normalized, excessive, collapsed, or unused skin influences. Exact vertical
links remain tied to the operator-selected Source Up Axis.

The viewport uses the four strongest influences only for diagnostic color
ownership. It does not normalize or write them back. Automatic checks cannot
prove an artist's intended pivot, terminal-bone +X, roll continuity at a fork,
sufficient edge-loop density, or Unreal's final reference pose. Rotating
representative bones after import remains the decisive boundary test.

## Exported USD validation coverage

Before USDA authoring, the converter rejects hierarchy/name errors,
child-before-parent order, non-rigid frames, inconsistent bind/rest transforms,
invalid weight shapes/sums, and wrong joint indices. The deterministic writer
derives matching joint/bind/rest and skin arrays from that model. Contract tests
also open representative output with OpenUSD Skeleton and Skinning queries.

There is no redundant OpenUSD parse of every file after writing. It would not
cover the remaining importer boundary: Unreal schema behavior, reused Skeleton
Assets, Dynamic Wind Asset User Data, Nanite Assembly Parts, or PCG runtime
representation.

## Current subsystem gaps

External USD mesh skinning is not diagnosed yet; the USD path remains
skeleton-only. FBX diagnostics do not repair weights, frames, bind poses, or
topology, and cannot inspect the Skeleton Asset that Unreal may reuse.

The exact PCG component/spawner used for the reported rigid result was not
captured. The PCG cause remains `Unverified`; record the generated component
class, referenced asset, Dynamic Wind asset data, and direct-versus-PCG A/B
before changing either the FBX exporter or the grouping algorithm.

## Evidence

- `src/xml_to_usda/fbx_adapter.py`
- `src/xml_to_usda/_ufbx.c`
- `src/xml_to_usda/usda_authoring.py`
- `src/xml_to_usda/skeleton_processing.py`
- `vault/ue_plugins/DynamicWindPluginResources/UsdResources/Plugins/unrealDynamicWind/resources/dynamicWind/schema.usda`
- `vault/ue_plugins/DynamicWindPluginResources/PythonExamples/export_dynamic_wind_json.py`
- `vault/Quixel trees examples/Tree_Norway_Maple_01_A.usda`
- supplied `TungTungTung.fbx`
