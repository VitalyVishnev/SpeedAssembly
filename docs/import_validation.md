# Import Validation

## Current verified status

Validated against the current generated sample:

- source XML: `samples/speedtree/simple_tree/variants/SimpleTree_01.xml`
- generated USDA: `samples/speedtree/simple_tree/variants/SimpleTree_01.usda`
- target importer: Unreal Engine 5.7.x USD / Interchange path

Current result:

- the USDA now imports instead of failing with `There was no data to import in the provided source data`
- the previous warning `Failed to find any valid base/part meshes for NaniteAssemblyRootAPI prim '/Tree'` is no longer the blocking outcome for the current sample
- import shape is still visually incorrect and needs a later transform / rig fidelity pass

## Contract that is currently validated by import

- unique base skeletal mesh:
  - trunk plus large branch body meshes
  - authored under `TrunkSkelRoot`
  - bound to the shared authored skeleton
- repeated instanced parts:
  - only reusable twig-with-leaf assemblies from `LeafReferences`
  - instanced through `PointInstancer`
  - bound back to the shared trunk skeleton through `bindJoints` and `bindJointWeights`
- twig prototypes:
  - authored inline under `PointInstancer/Prototypes`
  - authored as skeletal subtrees, not bare meshes
  - contain `SkelRoot`, `SkelAnimation`, `Mesh`, and `Skeleton`

## Known remaining problems

- visual pose / placement is still wrong
- further work is still needed on:
  - transform fidelity
  - prototype local rig fidelity
  - possible orientation / pivot / local-space mismatches

## Practical interpretation

At this point the repo has passed the first hard gate:

- UE accepts the file as importable skeletal Nanite Assembly input

It has not passed the final quality gate yet:

- imported result is not visually correct enough to treat transform authoring as done
