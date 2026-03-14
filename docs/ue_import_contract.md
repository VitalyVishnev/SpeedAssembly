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
- skeletal part prototypes, each with a one-bone `Part Skeleton`

Static assemblies exist in UE, but this project targets the skeletal tree path only.

## Current structural contract

The current validated structure is:

- root `Xform` with `NaniteAssemblyRootAPI`
- root `unreal:naniteAssembly:meshType = "skeletalMesh"`
- root relationship to the descendant `Main Skeleton`
- base `SkelRoot` containing real unique tree geometry
- base `Skeleton` and skeletal base mesh binding contract
- `PointInstancer` carrying skeletal assembly binding data
- inline skeletal part prototypes under `PointInstancer/Prototypes`
- each prototype authored as a skeletal part subtree, not as a bare mesh

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
- `SkelBindingAPI` on skeletal meshes that participate in the skeletal contract
- `primvars:unreal:naniteAssembly:bindJoints`
- `primvars:unreal:naniteAssembly:bindJointWeights`
- a descendant root-to-skeleton relationship for the assembly
- valid `Skeleton` data for the `Main Skeleton`
- valid skeletal binding data for the Base Skeletal Tree

Do not simplify away importer-relevant fields just because the USDA remains syntactically valid.

## Part contract

An `Assembly Part` is not a generic mesh placeholder.

For the current target pipeline:

- each part is a skeletal mesh
- each part has a one-bone `Part Skeleton`
- each part is instanced through `PointInstancer`
- each instance binds back to the `Main Skeleton`

The one-bone local part skeleton exists so the part remains in the skeletal import path.

## Current validated defaults

Use these until UE validation proves otherwise:

- `metersPerUnit = 1`
- `upAxis = "Y"`

## Validation rule

A contract change is accepted only if UE 5.7.x still imports the generated file as the intended skeletal Nanite Assembly.

Current verified state:

- the baseline sample imports as assembly input instead of failing as empty or invalid
- the importer accepts the current skeletal assembly structure
- visual fidelity is still incomplete and requires later transform and rig refinement
