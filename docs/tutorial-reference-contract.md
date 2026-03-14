## Tutorial Reference Contract

This milestone treats [vault/tutorials/nanite_assembly_skelmesh_pointinstancer_example.usda](/D:/3D%20Personal/VibeCode/XMLtoUSDAconverter/vault/tutorials/nanite_assembly_skelmesh_pointinstancer_example.usda) as the primary working reference for skeletal Nanite Assembly authoring.

Fields and structure we intentionally mirror:

- stage metadata: `metersPerUnit = 1`, `upAxis = "Y"`
- root `Xform` with `NaniteAssemblyRootAPI`, `meshType = "skeletalMesh"`, descendant skeleton relationship
- base `SkelRoot`, `Skeleton`, `SkelAnimation`, and real base mesh geometry
- base mesh `primvars:skel:geomBindTransform`
- base mesh `primvars:skel:jointIndices` and `primvars:skel:jointWeights` with `interpolation = "vertex"`
- base mesh skinning arrays sized to authored `points` for `vertex` interpolation, not to face-vertex topology
- base mesh `primvars:skel:skinningMethod = "classicLinear"`
- `Skeleton` arrays as full matrix payloads, not translation surrogates:
  - `uniform matrix4d[] bindTransforms`
  - `uniform token[] jointNames`
  - `uniform token[] joints`
  - `uniform matrix4d[] restTransforms`
- `Skeleton` importer-facing metadata:
  - `uniform token purpose = "guide"`
  - `uniform token visibility = "invisible"`
- `SkelAnimation` local translations aligned with the authored `restTransforms`
- `PointInstancer` with `NaniteAssemblySkelBindingAPI`
- instancer `bindJoints` and `bindJointWeights` with uniform `elementSize` and explicit `:indices = None`
- instancer `bindJoints` entries that name actual ancestor skeleton joints or joint paths
- inline twig prototypes under `PointInstancer/Prototypes`
- per-prototype internal `SkelRoot`, `SkelAnimation`, `Mesh`, and `Skeleton` hierarchy for instanced twig parts

Fields we intentionally do not copy by default:

- Houdini-specific `primvars:pCaptFrame`
- Houdini-specific `primvars:pCaptSkelRoot`
- `NaniteAssemblyExternalRefAPI` on prototypes unless a validated UE import path requires it

Current repo-specific mapping choice derived from this reference:

- joint world-space bind transforms are authored from normalized SpeedTree joint positions
- local `restTransforms` and `SkelAnimation.translations` are authored from parent-relative offsets
- unique base skeletal mesh is trunk plus large branch body geometry from `Object` meshes
- repeated `LeafReferences` are treated as reusable twig-with-leaf instances, not as standalone flat leaves
- twig instance bindings resolve to authored skeleton joint names such as `bone_017`, not to helper capture tokens
- for the current SpeedTree XML baseline, the joint position source is `Bone Start*`, while `Bone End*` remains segment extent data and is not emitted as the joint transform

Decision rule:

- If the tutorial USDA and local schema agree, copy the pattern.
- If the tutorial text and working USDA disagree, trust the working USDA.
- If a field cannot be derived safely from SpeedTree XML, do not invent it just to imitate Houdini output.
