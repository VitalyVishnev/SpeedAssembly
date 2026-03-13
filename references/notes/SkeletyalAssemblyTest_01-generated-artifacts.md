# SkeletyalAssemblyTest_01 Generated Artifacts

## Source sample

- XML: `references/speedtree/xml/SkeletyalAssemblyTest_01.xml`
- Inspect report: `references/reports/inspect/SkeletyalAssemblyTest_01.inspect.json`
- Generated USDA: `references/usd/generated/SkeletyalAssemblyTest_01.generated.usda`
- Reference USDA: `references/usd/skeletal_assemblies/example_assembly.usda`

## Observed extraction summary

- SpeedTree version detected: `10.0`
- Skeleton joints extracted: `89`
- Leaf instances extracted: `273`
- Trunk mesh extracted: yes
- Prototype keys observed from mesh library: `Suzanne_Leaf`

## Current output shape

- Root prim has `NaniteAssemblyRootAPI`
- Root sets `unreal:naniteAssembly:meshType = "skeletalMesh"`
- Root authors `rel unreal:naniteAssembly:skeleton`
- Base geometry is emitted under `TrunkSkelRoot` with `SkelBindingAPI`
- Repeated leaves are emitted through `PointInstancer`
- Bind data is emitted through `primvars:unreal:naniteAssembly:bindJoints` and `bindJointWeights`
- Prototypes are emitted as skeletal-shaped `SkelRoot` subtrees

## Known gaps from this run

- Inspect still reports many leaf-array and geometry payload tags as `unknown_sections`; this is currently noisy rather than fatal.
- The generated USDA is structurally useful for regression and UE-side experiments, but it is not yet proof of successful UE 5.7 import.
- Leaf prototype geometry is still placeholder geometry, not reconstructed source leaf mesh topology.
- Joint assignment for leaf instances currently uses nearest bone endpoint, which is a documented heuristic and should be validated against UE import behavior.
