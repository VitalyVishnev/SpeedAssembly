## Tutorial Reference Contract

This milestone treats [vault/tutorials/nanite_assembly_skelmesh_pointinstancer_example.usda](/D:/3D%20Personal/VibeCode/XMLtoUSDAconverter/vault/tutorials/nanite_assembly_skelmesh_pointinstancer_example.usda) as the primary working reference for skeletal Nanite Assembly authoring.

Fields and structure we intentionally mirror:

- stage metadata: `metersPerUnit = 1`, `upAxis = "Y"`
- root `Xform` with `NaniteAssemblyRootAPI`, `meshType = "skeletalMesh"`, descendant skeleton relationship
- base `SkelRoot`, `Skeleton`, `SkelAnimation`, and real base mesh geometry
- base mesh `primvars:skel:geomBindTransform`
- base mesh `primvars:skel:jointIndices` and `primvars:skel:jointWeights` with `interpolation = "vertex"`
- base mesh `primvars:skel:skinningMethod = "classicLinear"`
- `PointInstancer` with `NaniteAssemblySkelBindingAPI`
- instancer `bindJoints` and `bindJointWeights` with uniform `elementSize` and explicit `:indices = None`

Fields we intentionally do not copy by default:

- Houdini-specific `primvars:pCaptFrame`
- Houdini-specific `primvars:pCaptSkelRoot`
- per-prototype internal `SkelRoot` and `Skeleton` hierarchies from the tutorial export
- `NaniteAssemblyExternalRefAPI` on prototypes unless a validated UE import path requires it

Decision rule:

- If the tutorial USDA and local schema agree, copy the pattern.
- If the tutorial text and working USDA disagree, trust the working USDA.
- If a field cannot be derived safely from SpeedTree XML, do not invent it just to imitate Houdini output.
