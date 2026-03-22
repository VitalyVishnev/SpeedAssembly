# UE Import Contract

## Role

This document is normative for importer-facing USDA structure and required UE/USD contract fields.

## Target import shape

The target asset is a **Skeletal Nanite Assembly**.

It consists of:

- one `Assembly Root`
- one `Base Skeletal Tree`
- one shared `Main Skeleton`
- one or more `PointInstancer` prims for repeated `Assembly Parts`
- skeletal part prototypes, each resolved either as:
  - an inline skeletal part subtree with a one-bone `Part Skeleton`
  - an external referenced Unreal skeletal asset

Static assemblies exist in UE, but this project targets the skeletal tree path only.

## Current structural contract

The current validated structure is:

- root `Xform` with `NaniteAssemblyRootAPI`
- root `unreal:naniteAssembly:meshType = "skeletalMesh"`
- root relationship to the descendant `Main Skeleton`
- base `SkelRoot` containing real unique tree geometry
- base mesh prim name comes from the output USDA file stem
- base `Skeleton` and skeletal base mesh binding contract
- `PointInstancer` carrying skeletal assembly binding data
- prototype prims under `PointInstancer/Prototypes`
- prototype prim names come from SpeedTree XML mesh names, sanitized only as needed for USD validity
- inline prototypes authored as skeletal part subtrees, not as bare meshes
- external reused prototypes authored as `Xform` prims with `NaniteAssemblyExternalRefAPI`
- when external reuse is enabled, the prototype must be authored as a pure external ref subtree
  - do not keep an inline `Mesh` payload for the same prototype
  - the USDA should show `NaniteAssemblyExternalRefAPI` and `unreal:naniteAssembly:meshAssetPath`, but not a fallback `PartMesh` geometry subtree for that prototype

## File And Prim Naming

Generated filenames and the base skeletal prim names are intentionally linked.

For exported USDA files:

- the generated file name is `<stem>.usda`
- the `stem` of the output USDA file is the canonical authored name for the base skeletal tree
- the base mesh prim name uses that stem directly
- the base `SkelRoot` uses `<stem>_Geo`
- the shared `Skeleton` uses `<stem>_Skeleton`
- the base `SkelAnimation` remains `animation`
- the assembly root prim stays contract-driven, usually `Tree`, and is not derived from the output filename

This is the naming rule used by the converter when an explicit output path is provided.
It is not derived from the first bone name, and it is not derived from the XML source filename.

For example, if the output file is `SkeletyalAssemblyTest_Spruce_Big_low_twoTrunkGenerators.usda`, the base skeletal prims are authored as:

- `def Mesh "SkeletyalAssemblyTest_Spruce_Big_low_twoTrunkGenerators"`
- `def SkelRoot "SkeletyalAssemblyTest_Spruce_Big_low_twoTrunkGenerators_Geo"`
- `def Skeleton "SkeletyalAssemblyTest_Spruce_Big_low_twoTrunkGenerators_Skeleton"`

Conceptually:

- `Base Skeletal Tree` = all unique tree geometry
- `Assembly Parts` = repeated skeletal parts sourced from `LeafReferences`

## Required UE-facing fields

The converter must preserve the UE-facing contract that importer behavior depends on:

- required API schemas on the correct prims
- required primvars with correct names, placement, interpolation, and `elementSize`
- required USD attributes
- required relationships
- required skeletal arrays with matching counts where applicable

At minimum, current validated notes require:

- `NaniteAssemblyRootAPI` on the root `Xform`
- `NaniteAssemblySkelBindingAPI` on the relevant `PointInstancer`
- `NaniteAssemblyExternalRefAPI` on external reused prototype `Xform` prims when that mode is enabled
- `SkelBindingAPI` on skeletal meshes that participate in the skeletal contract
- `primvars:unreal:naniteAssembly:bindJoints`
- `primvars:unreal:naniteAssembly:bindJointWeights`
- `unreal:naniteAssembly:meshAssetPath` on external reused prototype `Xform` prims
- a descendant root-to-skeleton relationship for the assembly
- valid `Skeleton` data for the `Main Skeleton`
- valid skeletal binding data for the Base Skeletal Tree

## External reuse debugging rule

When an external `PartMesh` override appears to be ignored, check the generated USDA first:

1. if `NaniteAssemblyExternalRefAPI` is missing, the bug is in the exporter path before UE import
2. if `meshAssetPath` is present but UE still imports the low-poly mesh, verify that UE is using the Interchange USD importer path
3. if the path is present in USDA but not in UE, confirm the package/object path exactly matches the asset in Content Browser

Do not simplify away importer-relevant fields just because the USDA remains syntactically valid.

## Part contract

An `Assembly Part` is not a generic mesh placeholder.

For the current target pipeline:

- each part is instanced through `PointInstancer`
- each instance binds back to the `Main Skeleton`
- each prototype resolves in one of two ways:
  - inline skeletal mesh with one-bone local `Part Skeleton`
  - external reused Unreal skeletal mesh asset via `NaniteAssemblyExternalRefAPI`

The one-bone local part skeleton exists so the inline part remains in the skeletal import path.

External asset reuse is an optional `Phase 1` mode. It exists to reuse already-imported project `PartMesh` assets without removing the safe inline baseline path.

## Material contract

Material bindings must stay on real mesh prims or face subsets.

For the current contract:

- no `material:binding` is authored on the assembly root
- no `material:binding` is authored on the base `SkelRoot`
- no `material:binding` is authored on the `PointInstancer`
- single-material meshes use direct mesh-level binding
- multi-material meshes use `GeomSubset` with `familyName = "materialBind"`
- external reused `PartMesh` assets are expected to carry their own material setup inside the referenced Unreal asset

## Current validated defaults

Use these until UE validation proves otherwise:

- `metersPerUnit = 1`
- `upAxis = "Y"`

## Validation rule

A contract change is accepted only if UE 5.7.x still imports the generated file as the intended skeletal Nanite Assembly.

Current verified state:

- the baseline sample imports as assembly input instead of failing as empty or invalid
- the importer accepts the current skeletal assembly structure
- mixed inline and external prototype resolution is covered by automated regression tests
- visual fidelity is still incomplete and requires later transform and rig refinement
