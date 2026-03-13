# Golden Sample Workflow

## Purpose

Use `SimpleTree_01.xml` as the single baseline sample for the current skeletal assembly milestone.

## Locked baseline

- input: `samples/speedtree/simple_tree/variants/SimpleTree_01.xml`
- current authoring target: deterministic USDA for UE 5.7 skeletal Nanite Assembly import
- current parsing policy: `skeleton-first`, `spine-optional`

The other exported variants remain useful for reference and comparison, but they are not the active development baseline.

## Expected observed signature

`SimpleTree_01.xml` currently normalizes to:

- `63` source objects
- `1` trunk object
- `22` branch objects
- `39` twig objects with leaf references
- hierarchy depth `4`
- `105` bones
- `23` objects carrying `Spine`
- `39` leaf instances
- `2` reusable twig meshes in the mesh library

## Baseline workflow

1. Run `inspect` on `SimpleTree_01.xml` and verify the observed signature stays stable.
2. Run `convert` and ensure validation passes with no blocking errors.
3. Review the generated USDA for trunk `SkelRoot`, `Skeleton`, `PointInstancer`, prototype scope, and Unreal skeletal binding primvars.
4. Use this output as the golden regression sample until a verified UE import proves that a different baseline is stronger.

## Selection result

Variant selection is currently resolved as follows:

- `SimpleTree_01.xml` is the active baseline because it preserves object hierarchy, non-zero relative transforms, explicit leaf bindings, real skeleton data, and optional `Spine` data.
- `Spine` is parsed and stored, but the writer does not depend on it for the current skeletal import path.
- leaf binding comes directly from XML `LeafReferences/BoneID`; the converter does not use nearest-joint heuristics for this sample.

## Regression expectations

Golden-path tests should fail if any of the following drift:

- object hierarchy disappears or depth changes unexpectedly
- trunk mesh extraction stops working
- skeleton hierarchy changes shape without an explicit fixture update
- leaf `BoneID` set changes unexpectedly
- leaf mesh usage changes unexpectedly
- USDA skeletal binding arrays lose `elementSize = 1`
