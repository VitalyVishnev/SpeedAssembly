# Workflow And Status

## Role

This document is normative for the active baseline sample, current validation state, and milestone workflow.

## Active baseline

The current reverse-engineering baseline is:

- `samples/speedtree/simple_tree/variants/SimpleTree_01.xml`

This sample is the main regression fixture for skeletal assembly work.

## Current validated status

The project has passed the first hard gate:

- UE accepts the generated baseline USDA as skeletal Nanite Assembly input

The project has not passed the final quality gate yet:

- transform fidelity is still incomplete
- visual placement and pose still need refinement

## Expected workflow

For importer-facing work, use this loop:

1. inspect the baseline XML
2. convert it to USDA
3. verify the expected assembly structure
4. import into UE 5.7.x
5. inspect logs and resulting asset
6. compare against `vault` examples
7. record any importer-facing contract change before generalizing

## Workflow invariants

The baseline path should continue to preserve:

- one `Base Skeletal Tree` for all unique tree geometry
- one `Main Skeleton`
- repeated `Assembly Parts` sourced from `LeafReferences`
- `PointInstancer`-based part instancing
- skeletal parts with one-bone local part skeletons

## Current milestone sequence

1. keep the baseline skeletal assembly path stable
2. improve transform and rig fidelity
3. align code naming and comments with the approved terminology
4. only then generalize to additional export variants or later features
