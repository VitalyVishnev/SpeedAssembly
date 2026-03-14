# Golden Sample Workflow

## Purpose

Use `SimpleTree_01.xml` as the primary XML fixture for the current skeletal assembly milestone.

## Locked baseline

- input: `samples/speedtree/simple_tree/variants/SimpleTree_01.xml`
- current authoring target: deterministic USDA for UE 5.7 skeletal Nanite Assembly import
- current parsing policy: `skeleton-first`, `spine-optional`
- current verified importer status: imports in UE 5.7.x, but pose / placement is still incorrect

The other exported variants remain useful for reference and comparison, but they are not the active development driver.

## Expected workflow invariants

`SimpleTree_01.xml` should continue to normalize with these qualitative guarantees:

- source object hierarchy is present
- base geometry is merged from trunk plus branch body meshes
- skeleton hierarchy is preserved from XML `Bones/Bone`
- reusable twig instances carry explicit skeletal bindings derived from XML `BoneID`
- prototype library is authored through an inline skeletal `PointInstancer/Prototypes` subtree
- `Spine` remains optional source data and is not required by the writer

## Baseline workflow

1. Run `inspect` on `SimpleTree_01.xml` and verify the qualitative shape stays stable.
2. Run `convert` and ensure validation passes with no blocking errors.
3. Review the generated USDA for base `SkelRoot`, `Skeleton`, `PointInstancer`, inline skeletal twig prototype scope, and Unreal skeletal binding primvars.
4. Specifically verify the `Skeleton` contract:
   - `bindTransforms` and `restTransforms` are both `matrix4d[]`
   - `jointNames`, `joints`, `bindTransforms`, and `restTransforms` have matching counts
   - `SkelAnimation.translations` is local, not a world-space surrogate
5. Regenerate `samples/speedtree/simple_tree/variants/SimpleTree_01.usda` at the end of every importer-focused pass so UE can be tested against the exact new output.
6. Use this output as the golden regression sample until a verified UE import proves that a different baseline is stronger.
7. Record every importer-facing milestone in `docs/import_validation.md` before changing the contract again.

## Selection result

Variant selection is currently resolved as follows:

- `SimpleTree_01.xml` is the active baseline because it preserves object hierarchy, non-zero relative transforms, explicit leaf bindings, real skeleton data, and optional `Spine` data.
- `Spine` is parsed and stored, but the writer does not depend on it for the current skeletal import path.
- repeated twig binding comes directly from XML `LeafReferences/BoneID` and is normalized into the general UE binding model; the converter does not use nearest-joint heuristics for this sample.

## Regression expectations

Golden-path tests should fail if any of the following drift:

- object hierarchy disappears
- base mesh extraction stops working
- skeleton hierarchy disappears or loses parentage
- reusable twig instances lose explicit skeletal binding data
- prototype authoring falls back to non-skeletal or reference-only structure unexpectedly
- USDA skeletal binding arrays or UE support primvars disappear
- `Skeleton` falls back to `restTransforms:translations` or any other non-matrix substitute
