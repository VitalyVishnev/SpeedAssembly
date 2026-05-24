# UE Import Contract

## Role

This document is normative for importer-facing USDA structure and required UE/USD contract fields.

## Target import shape

The target asset family now has two supported UE import shapes:

- a **Skeletal Nanite Assembly** baseline
- a **Static Mesh Assembly** export mode for non-skinned vegetation and other rigid vegetation clusters

It consists of:

- one `Assembly Root`
- one `Base Skeletal Tree`
- one shared `Main Skeleton`
- one or more `PointInstancer` prims for repeated `Assembly Parts`
- skeletal part prototypes, each resolved either as:
  - an inline skeletal part subtree with a one-bone `Part Skeleton`
  - an inline skeletal part subtree whose mesh payload was replaced from an explicit disk FBX file
  - an external referenced Unreal skeletal asset

Static assemblies are now a supported exporter contract, but the skeletal tree
path remains the primary project goal and baseline import shape.

## Export modes

The converter now has three supported authoring modes plus one disabled future mode:

- `skeletal_assembly`
  - the validated UE import contract
  - authors the full assembly root, base skeletal tree, main skeleton, and `PointInstancer`
- `skeletal_parts`
  - a reusable part-library export mode
  - writes one USDA file per prototype
  - each generated file uses the prototype name as both filename stem and root prim name
  - omits the assembly root API, base skeletal tree, main skeleton, and real `PointInstancer`
  - is valid only when prototype payloads are present
- `static_assembly`
  - authors a single USDA file as a static Nanite Assembly
  - uses `NaniteAssemblyRootAPI`, `meshType = "staticMesh"`, and a plain `PointInstancer`
  - omits skeletons, binding arrays, and all `primvars:skel:*` fields
  - writes unique base geometry as one synthetic static prototype at the assembly pivot
- `static_parts`
  - remains disabled for this pass
  - is reserved for a later static part-library export shape

Missing base mesh and missing main skeleton are hard failures only in `skeletal_assembly` mode.
They are expected omissions in `skeletal_parts` mode.
Static assemblies require renderable geometry, but they do not require a skeleton or skeletal binding.

## Current skeletal structural contract

The current validated structure is `skeletal_assembly` mode:

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
- inline prototype single-joint names come from the prototype prim name, sanitized only as needed for USD validity
- external reused prototypes authored as `Xform` prims with `NaniteAssemblyExternalRefAPI`
- explicit FBX prototype replacement keeps the same inline skeletal part subtree shape as XML-inline mode
  - only the prototype mesh payload changes
  - `LeafReferences` instance transforms and main-skeleton bindings do not change
- when external reuse is enabled, the prototype must be authored as a pure external ref subtree
  - do not keep an inline `Mesh` payload for the same prototype
  - the USDA should show `NaniteAssemblyExternalRefAPI` and `unreal:naniteAssembly:meshAssetPath`, but not a fallback `PartMesh` geometry subtree for that prototype
- base skeleton root-joint aliasing to the output stem is valid only when the `Main Skeleton` has exactly one root joint
  - multi-root skeletons must preserve distinct root-joint names in `jointNames`, `joints`, `skel:joints`, and base animation paths

## File And Prim Naming

Generated filenames and the base skeletal prim names are intentionally linked.

For exported USDA files:

- the generated file name is `<stem>.usda`
- the `stem` of the output USDA file is the `Output Stem`
- the Output Stem is the canonical Authored Asset Name for the base skeletal tree
- the base mesh Prim Name uses that stem directly
- the base `SkelRoot` Prim Name uses `<stem>_Geo`
- the shared `Skeleton` Prim Name uses `<stem>_Skeleton`
- the base `SkelAnimation` remains `animation`
- the assembly root prim stays contract-driven, usually `Tree`, and is not derived from the output filename

For `skeletal_parts` exports:

- the chosen output path is treated as a container path
- the converter writes a sibling directory using that path stem
- each prototype writes as `<Prototype>.usda` inside that directory
- each part file uses `defaultPrim = "<Prototype>"`
- each part file root Prim Name is also `<Prototype>`

For `static_assembly` exports:

- the generated file name is still `<stem>.usda`
- the root Prim Name uses the chosen Output Stem or assembly stem directly
- the synthetic base prototype name is the root stem plus a deterministic suffix such as `_BaseMesh`
- repeated prototype prim names continue to come from source XML mesh names or resolved FBX stems, sanitized only as needed for USD validity

This is the naming rule used by the converter when an explicit output path is
provided. It is not derived from the first bone Source Name, and it is not
derived from the XML source filename.

For example, if the output file is `SkeletalAssemblyTest_Spruce_Big_low_twoTrunkGenerators.usda`, the base skeletal prims are authored as:

- `def Mesh "SkeletalAssemblyTest_Spruce_Big_low_twoTrunkGenerators"`
- `def SkelRoot "SkeletalAssemblyTest_Spruce_Big_low_twoTrunkGenerators_Geo"`
- `def Skeleton "SkeletalAssemblyTest_Spruce_Big_low_twoTrunkGenerators_Skeleton"`

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
- stable root-joint naming across base animation, base mesh binding arrays, and `Main Skeleton`

For `skeletal_parts` mode, the contract is narrower:

 - each file root prim is the prototype name
 - no `NaniteAssemblyRootAPI`
 - no assembly `unreal:naniteAssembly:meshType`
 - no assembly relationship to a descendant `Main Skeleton`
 - no base `SkelRoot`
 - no real `PointInstancer`
 - no instance arrays, bindings, or assembly root data
 - one prototype is authored per file as a standalone skeletal subtree
 - each part file still contains its own local `Part Skeleton`

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

These required fields apply to `skeletal_assembly` mode. The `skeletal_parts` mode intentionally omits the assembly-only fields.

## Static mesh assembly contract

For `static_assembly` mode, the required importer-facing shape is:

- root `Xform` with `NaniteAssemblyRootAPI`
- root `unreal:naniteAssembly:meshType = "staticMesh"`
- root `kind = "group"`
- the stage root does not require a `defaultPrim`; the root prim itself is the assembly root
- no skeleton relationship on the root
- no `SkelRoot`
- no `Skeleton`
- no `SkelBindingAPI`
- no `primvars:skel:*` fields anywhere in the authored USDA
- one `PointInstancer` carrying the placed assembly instances
- prototype prims under `PointInstancer/Prototypes`
- unique base geometry authored as a synthetic static prototype at the tree pivot when a base mesh exists
- repeated part prototypes authored as static `Xform` + `Mesh` subtrees or as external Nanite assembly references
- inline static `Mesh` prims use the `SM_` naming convention when the source prototype name does not already have it

The static assembly root name is derived from the assembly/output stem, not from the skeletal `Tree` contract.

## External reuse debugging rule

When an external `PartMesh` override appears to be ignored, check the generated USDA first:

1. if `NaniteAssemblyExternalRefAPI` is missing, the bug is in the exporter path before UE import
2. if `meshAssetPath` is present but UE still imports the low-poly mesh, verify that UE is using the Interchange USD importer path
3. if the path is present in USDA but not in UE, confirm the Unreal Asset Path
   exactly matches the package/object path in Content Browser

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

Authored Material Bindings must stay on real mesh prims or face subsets.

For the current contract:

- no `material:binding` is authored on the assembly root
- no `material:binding` is authored on the base `SkelRoot`
- no `material:binding` is authored on the `PointInstancer`
- single-material meshes use direct mesh-level binding
- multi-material meshes use `GeomSubset` with `familyName = "materialBind"`
- external reused `PartMesh` assets are expected to carry their own material setup inside the referenced Unreal asset
- explicit FBX-replaced inline prototypes still author material binding in USDA from resolved face buckets

The exporter now has explicit material-policy modes:

- `source_material_roles`
  - compatibility mode only
  - raw XML material ids `1` and `2` are still interpreted as primary/leaves semantic slots
  - the old missing-role validation remains active only in this mode
- `single_material`
  - ignore XML material ids and vertex colors
  - synthesize one canonical USD material
  - collapse each base mesh / prototype mesh to one direct material binding
- `vertex_color_split`
  - ignore XML material ids
  - synthesize two canonical USD materials
  - assign a face to bucket `1` only if every vertex on that face is exact white `(1,1,1)`
  - assign all non-white and gray faces to bucket `2`
  - if usable vertex colors are missing, warn and fall back to bucket `1`

Explicit FBX prototype material baseline:

- explicit repeated-part FBX material modes now include:
  - `single_material`
  - `vertex_color_split`
  - `material_slots`
- `vertex_color_split`
  - exact-black faces are assigned to the leaves bucket
  - every non-black face is assigned to the bark bucket
  - missing vertex colors are a hard failure in strict mode
- `material_slots`
  - only FBX material slots actually used by faces are surfaced
  - repeated FBX material names are merged into one logical slot override row
  - if some slot rows are blank, one filled Unreal material path is reused with a warning
- if all slot rows are blank, conversion fails

## UDIM UV contract

UDIM support is an explicit per-material operator choice and is disabled by default.

Supported modes:

- `off`
  - leaves authored UVs unchanged
- `shift_primary_uv`
  - offsets primary face-varying `primvars:st` for faces assigned to the selected resolved material id
  - uses fixed `base_udim = 1001`
- `write_secondary_uv_offset`
  - preserves primary `primvars:st`
  - writes a second full-size face-varying UV channel with the selected UDIM tile offset plus `0.5`
  - untouched material faces receive `(0.5, 0.5)`, representing the first UDIM tile

Current authoring uses `texCoord2f[] primvars:st1` for the second UV channel.
This name is covered by automated USDA regression tests but still requires UE
5.7.x import validation before being treated as importer-proven.

Raw SpeedTree XML material ids must be treated as opaque Source Material
metadata. `source_material_roles` may infer bark/leaves buckets from authored
source usage, but it must not treat numeric ids like `1/2` as a required
contract.
They are not semantic bark/leaves roles for the generic pipeline contract.

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
- explicit inline FBX prototype replacement is covered by automated streaming-writer regression tests
- static assembly export is implemented, unit-tested, and confirmed to import
  normally in UE 5.7.x; keep validating it on new real vegetation structures
  without letting it redefine the primary skeletal baseline
- visual fidelity is still incomplete and requires later transform and rig refinement
