# Reference USDA Assembly Notes

This note captures findings from `references/usd/skeletal_assemblies/example_assembly.usda`.

The local UE 5.7 schema files are now the primary source of truth for UE-specific API names and allowed prim targets. This note is useful for layout comparison, but it is secondary to:

- `C:\Program Files\Epic Games\UE_5.7\Engine\Plugins\Runtime\USDCore\Resources\UsdResources\Win64\X64\plugins\unreal\resources\unreal\schema.usda`
- `C:\Program Files\Epic Games\UE_5.7\Engine\Plugins\Runtime\USDCore\Resources\UsdResources\Win64\X64\plugins\unreal\resources\generatedSchema.usda`

## Confirmed structural expectations

- Root prim is an `Xform` with `apiSchemas = ["NaniteAssemblyRootAPI"]`.
- Root carries `uniform token unreal:naniteAssembly:meshType = "skeletalMesh"`.
- Root also carries `rel unreal:naniteAssembly:skeleton` targeting the base skeleton.
- Base content is authored as `SkelRoot -> Skeleton + Mesh`.
- Base mesh uses `apiSchemas = ["SkelBindingAPI"]` and `rel skel:skeleton`.
- Part instancing is authored with `PointInstancer`.
- Binding data on the instancer is authored as:
  - `uniform token[] primvars:unreal:naniteAssembly:bindJoints`
  - `uniform float[] primvars:unreal:naniteAssembly:bindJointWeights`
- Prototypes are not plain `Xform` placeholders. They are authored as `SkelRoot` subgraphs with their own `Skeleton` and `Mesh`.

## Current implementation decisions

- The writer now follows the reference shape for skeleton relationships and primvar naming.
- Prototype geometry is still placeholder geometry in `v1`, but its container structure matches the skeletal-assembly reference more closely.
- Older project code used `NaniteSkelBindingAPI` on the instancer because it matched the attached USDA reference.
- Local UE 5.7 schema files confirm the verified API name is `NaniteAssemblySkelBindingAPI`, so the reference file should no longer override schema-backed naming.

## Open questions to revisit later

- Exact required joint path format versus short joint names for `bindJoints`.
- Whether prototype skeletons need richer rest transforms or additional schema metadata.
- Whether importer behavior requires anything beyond the schema-documented `elementSize` metadata for `PointInstancer` joint binding arrays.
