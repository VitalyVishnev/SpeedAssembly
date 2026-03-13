# UE 5.7 Nanite Assembly Schema Notes

This document records the UE-specific USD schema facts currently verified from the local UE 5.7 plugin schema files:

- `C:\Program Files\Epic Games\UE_5.7\Engine\Plugins\Runtime\USDCore\Resources\UsdResources\Win64\X64\plugins\unreal\resources\unreal\schema.usda`
- `C:\Program Files\Epic Games\UE_5.7\Engine\Plugins\Runtime\USDCore\Resources\UsdResources\Win64\X64\plugins\unreal\resources\generatedSchema.usda`

These files are the source of truth for the UE-specific API names and attribute names used by the converter. Reference USDA samples remain useful, but they are secondary to the local UE schema.

## Non-negotiable authoring rule

The converter must always author the required UE-facing schema contract completely:

- required API schemas must be present on the correct prims
- required primvars must be present with the correct names, interpolation, and `elementSize` metadata when applicable
- required USD attributes and relationships must be authored with the correct names and placement

A USDA that is syntactically valid but omits required UE API schemas, primvars, or skeletal attributes is considered invalid for this project.

## Verified APIs

### `NaniteAssemblyRootAPI`

- Type: single-apply API schema
- Can only apply to: `Xform`
- Verified fields:
  - `uniform token unreal:naniteAssembly:meshType = "staticMesh"`
  - `rel unreal:naniteAssembly:skeleton`
- Verified allowed tokens for `unreal:naniteAssembly:meshType`:
  - `"staticMesh"`
  - `"skeletalMesh"`
- Verified behavior note from schema:
  - `unreal:naniteAssembly:skeleton` is valid for `meshType=skeletalMesh` only and must target a descendant prim

### `NaniteAssemblyExternalRefAPI`

- Type: single-apply API schema
- Can only apply to: `Xform`
- Verified field:
  - `uniform token unreal:naniteAssembly:meshAssetPath = ""`

### `NaniteAssemblySkelBindingAPI`

- Type: single-apply API schema
- Can apply to:
  - `Xform`
  - `Mesh`
  - `SkelRoot`
  - `PointInstancer`
- Verified fields:
  - `primvars:unreal:naniteAssembly:bindJoints`
  - `primvars:unreal:naniteAssembly:bindJointWeights`
- Verified behavior note from schema:
  - when applied to a `PointInstancer`, a uniform number of joints per instance must be supplied and described via `primvars` `elementSize` metadata

## Confirmed implications for this repo

- The converter must use `NaniteAssemblySkelBindingAPI`, not `NaniteSkelBindingAPI`.
- Root assembly authoring should remain `def Xform "Tree"` with `apiSchemas = ["NaniteAssemblyRootAPI"]`.
- Skeletal assembly export should continue to author:
  - `uniform token unreal:naniteAssembly:meshType = "skeletalMesh"`
  - `rel unreal:naniteAssembly:skeleton = </Tree/TrunkSkelRoot/TrunkSkeleton>`
- Point-instanced part binding should author `bindJoints` and `bindJointWeights` with `elementSize` metadata.
- Real UE-authored tree USDA samples in `vault/` use path-like joint identity tokens plus primvar interpolation metadata rather than relying on a literal `uniform` qualifier in authored text.
- Base skeletal mesh authoring must preserve required `UsdSkel` data, not just sibling `Skeleton` presence. In practice this includes the relevant `skel:*` relationships/attributes and any required skinning primvars shown by verified UE examples.

## Required review checklist for writer changes

When changing the USDA writer, explicitly check:

- API schema presence
- primvar presence
- attribute names
- relationship names
- interpolation metadata
- `elementSize` metadata
- prim placement within the hierarchy

Do this against both the local UE schema files and working `vault` examples.

## Open Questions

- The schema confirms names, allowed prim types, and some authoring constraints, but it does not by itself prove the minimum importable prim hierarchy for UE 5.7 skeletal Nanite assemblies.
- The schema text allows joint names or joint paths for `bindJoints`; importer behavior still needs to confirm which form is required in practice.
- The schema confirms `elementSize` is required for `PointInstancer` binding data, but importer/source inspection is still needed to prove the exact array layout and support-primvar requirements across all skeletal assembly cases.

## Current v1 policy

- Treat these schema files as authoritative for UE-specific names.
- Treat importer behavior as the next validation layer for required structure and semantics.
- Avoid adding any additional UE-specific fields until they are confirmed from schema files, importer source, or a verified working import.
