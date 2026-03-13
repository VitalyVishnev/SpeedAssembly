# Golden Sample Workflow

## Purpose

Use `SimpleTree_01.xml` as the primary XML fixture for the current skeletal assembly milestone.

## Locked baseline

- input: `samples/speedtree/simple_tree/variants/SimpleTree_01.xml`
- current authoring target: deterministic USDA for UE 5.7 skeletal Nanite Assembly import
- current parsing policy: `skeleton-first`, `spine-optional`

The other exported variants remain useful for reference and comparison, but they are not the active development driver.

## Expected workflow invariants

`SimpleTree_01.xml` should continue to normalize with these qualitative guarantees:

- source object hierarchy is present
- base geometry is merged from trunk plus branch body meshes
- skeleton hierarchy is preserved from XML `Bones/Bone`
- reusable part instances carry explicit skeletal bindings derived from XML `BoneID`
- prototype library is authored through a reference-oriented `PointInstancer/Prototypes` subtree
- `Spine` remains optional source data and is not required by the writer

## Baseline workflow

1. Run `inspect` on `SimpleTree_01.xml` and verify the qualitative shape stays stable.
2. Run `convert` and ensure validation passes with no blocking errors.
3. Review the generated USDA for base `SkelRoot`, `Skeleton`, `PointInstancer`, reference-oriented prototype scope, and Unreal skeletal binding primvars.
4. Use this output as the golden regression sample until a verified UE import proves that a different baseline is stronger.

## Selection result

Variant selection is currently resolved as follows:

- `SimpleTree_01.xml` is the active baseline because it preserves object hierarchy, non-zero relative transforms, explicit leaf bindings, real skeleton data, and optional `Spine` data.
- `Spine` is parsed and stored, but the writer does not depend on it for the current skeletal import path.
- leaf binding comes directly from XML `LeafReferences/BoneID` and is normalized into the general UE binding model; the converter does not use nearest-joint heuristics for this sample.

## Regression expectations

Golden-path tests should fail if any of the following drift:

- object hierarchy disappears
- base mesh extraction stops working
- skeleton hierarchy disappears or loses parentage
- reusable instances lose explicit skeletal binding data
- prototype authoring falls back to non-reference-oriented structure unexpectedly
- USDA skeletal binding arrays or UE support primvars disappear
