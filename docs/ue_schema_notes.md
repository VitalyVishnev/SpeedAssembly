# UE 5.7 Nanite Assembly Schema Notes

This note tracks two different kinds of truth:

- local UE schema files for API names and allowed prim placements
- verified importer behavior from working USDA files and actual UE log output

Schema files used for naming and placement:

- `C:\Program Files\Epic Games\UE_5.7\Engine\Plugins\Runtime\USDCore\Resources\UsdResources\Win64\X64\plugins\unreal\resources\unreal\schema.usda`
- `C:\Program Files\Epic Games\UE_5.7\Engine\Plugins\Runtime\USDCore\Resources\UsdResources\Win64\X64\plugins\unreal\resources\generatedSchema.usda`

Working USDA and UE logs are still required because the schema alone does not tell us the minimum importable `UsdSkel` contract.

## Non-negotiable authoring rule

The converter must author the full UE-facing contract that importer behavior depends on:

- required API schemas on the correct prims
- required primvars with the correct names, interpolation, and `elementSize`
- required `UsdSkel` arrays and relationships with the correct placement

Syntactically valid USD is not enough if importer-relevant skeletal data is missing or malformed.

## Verified schema facts

### `NaniteAssemblyRootAPI`

- single-apply API schema
- allowed prim type: `Xform`
- verified fields:
  - `uniform token unreal:naniteAssembly:meshType`
  - `rel unreal:naniteAssembly:skeleton`
- verified `meshType` tokens:
  - `"staticMesh"`
  - `"skeletalMesh"`
- schema note:
  - `unreal:naniteAssembly:skeleton` is only valid for `meshType = "skeletalMesh"` and must target a descendant prim

### `NaniteAssemblyExternalRefAPI`

- single-apply API schema
- allowed prim type: `Xform`
- verified field:
  - `uniform token unreal:naniteAssembly:meshAssetPath = ""`

### `NaniteAssemblySkelBindingAPI`

- single-apply API schema
- allowed prim types:
  - `Xform`
  - `Mesh`
  - `SkelRoot`
  - `PointInstancer`
- verified fields:
  - `primvars:unreal:naniteAssembly:bindJoints`
  - `primvars:unreal:naniteAssembly:bindJointWeights`
- schema note:
  - `PointInstancer` bindings require a uniform number of joints per instance, represented through `elementSize`

## Practical importer findings

These are not pure schema facts; they are current UE-validated or UE-log-backed rules for this repo.

- Working tutorial and Quixel USDA files use:
  - `metersPerUnit = 1`
  - `upAxis = "Y"`
  - `primvars:skel:skinningMethod = "classicLinear"`
  - `vertex` interpolation for skeletal joint indices and weights
- Working tutorial USDA also shows two importer-relevant binding facts:
  - `PointInstancer` `bindJoints` entries name actual skeleton joints such as `point_4`, not auxiliary capture tokens
  - twig prototypes are authored inline under `PointInstancer/Prototypes`, not only as references back into a hidden library scope
- Working tutorial USDA also shows that instanced parts are safer when each prototype is authored as a skeletal subtree instead of a bare `Mesh`:
  - outer `Xform`
  - nested `SkelRoot`
  - nested `SkelAnimation`
  - nested `Mesh` with `SkelBindingAPI`
  - nested `Skeleton`
- Working tutorial USDA authors `Skeleton` with:
  - `uniform matrix4d[] bindTransforms`
  - `uniform token[] jointNames`
  - `uniform token[] joints`
  - `uniform token purpose = "guide"`
  - `uniform matrix4d[] restTransforms`
  - `append rel skel:animationSource = ...`
  - `uniform token visibility = "invisible"`
- UE log from importing generated `SimpleTree_01.usda` showed:
  - `size of 'restTransforms' attr [0] does not match the number of joints in the 'joints' attr [105]`
- Practical conclusion:
  - `float3[] restTransforms:translations` is not an acceptable substitute for `uniform matrix4d[] restTransforms` on this skeletal import path
  - `bindJoints` must resolve to real ancestor skeleton joint names or paths; capture-path helper tokens are not a safe substitute
  - base mesh `jointIndices` and `jointWeights` must match authored `points` when using `interpolation = "vertex"`

## Current repo implications

- Use `NaniteAssemblySkelBindingAPI`, not guessed variants.
- Keep the root as `def Xform "Tree"` with `NaniteAssemblyRootAPI`.
- Author:
  - `uniform token unreal:naniteAssembly:meshType = "skeletalMesh"`
  - descendant skeleton relationship to `</Tree/TrunkSkelRoot/TrunkSkeleton>`
- For base mesh authoring, preserve the full practical `UsdSkel` contract:
  - `SkelBindingAPI`
  - `skel:skeleton`
  - `skel:joints`
  - `primvars:skel:geomBindTransform`
  - `primvars:skel:jointIndices`
  - `primvars:skel:jointWeights`
  - `primvars:skel:skinningMethod = "classicLinear"`
- For `PointInstancer`, author `bindJoints` and `bindJointWeights` with uniform width and explicit `:indices = None`.
- For current tutorial-parity output, prefer inline skeletal twig prototypes under `PointInstancer/Prototypes` over reference-only library scopes.
- Keep the unique base skeletal mesh as trunk plus large branch body geometry; only repeated twig assemblies from `LeafReferences` should be instanced.

## Writer review checklist

When changing the writer, compare against both the local schema and working `vault` USDA:

- API schema presence
- primvar presence
- attribute names
- relationship names
- interpolation metadata
- `elementSize`
- array counts for `joints`, `jointNames`, `bindTransforms`, `restTransforms`
- prim placement inside the hierarchy

## Still open

- The schema confirms names and allowed prim types, but it does not prove the full minimum hierarchy for every skeletal Nanite Assembly case.
- The schema allows multiple possible binding token forms; importer behavior still decides which forms are practical.
- After the `Skeleton` contract is valid, remaining base/part mesh discovery issues should be investigated against inline skeletal twig prototype shape and point-count skinning payloads before adding more Houdini-specific structure.
