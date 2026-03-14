# SpeedTree Mapping

## Role

This document is normative for how observed SpeedTree XML sections map into project concepts.

## Baseline interpretation

Treat SpeedTree Raw XML as an observed schema built from real samples, not as a formal public spec.

The active baseline remains:

- `samples/speedtree/simple_tree/variants/SimpleTree_01.xml`

## Canonical mapping

The converter splits the source tree into two major components:

- regular XML hierarchy plus skeleton data -> `Base Skeletal Tree`
- `LeafReferences` -> `Assembly Parts`

This split is structural and explicit. It is not based on botanical names.

## Section-to-concept mapping

### `Objects/Object`

This is the source of the regular tree hierarchy and unique geometry.

Use it for:

- unique object hierarchy
- unique tree mesh payloads
- the geometry that becomes the `Base Skeletal Tree`

`Branches_*` style body geometry belongs to the Base Skeletal Tree, not to instanced parts.

### `Bones/Bone`

This is the source of the `Main Skeleton`.

Use it for:

- joint identity
- parent chain
- joint transform derivation

Missing required skeleton coordinates are a hard failure for skeletal export.

### `LeafReferences`

This is the source of `Assembly Parts`.

Use it for:

- repeated part placement
- repeated part prototype selection
- repeated part binding back to the `Main Skeleton`

`LeafReferences` does not mean the payload is semantically only leaves. It is the XML source of repeated parts.

### `Meshes/Mesh`

This is the reusable geometry library for part prototypes.

Use it for:

- prototype mesh selection keyed by `MeshID`
- part geometry reconstruction

## Current part interpretation

For the current project contract:

- repeated parts are emitted as `Assembly Parts`
- each part is authored as a skeletal part
- each part has a one-bone local `Part Skeleton`
- the instance binds back to the `Main Skeleton`

## Failure conditions

Fail loudly when the baseline path cannot safely determine:

- the regular unique tree hierarchy
- the `Main Skeleton`
- the `Base Skeletal Tree`
- explicit repeated part identity
- repeated part transforms
- repeated part skeletal binding source
