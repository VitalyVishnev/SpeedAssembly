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
- placement of `LeafReferences` on any supported hierarchy level

`Branches_*` style body geometry belongs to the Base Skeletal Tree, not to instanced parts.

Current observed implementation rule:

- `Trunk` and `Branches_*` objects are merged into the `Base Skeletal Tree`

Treat this as the current supported rule, not as a formal SpeedTree guarantee. If additional real exports prove the rule too narrow, update the normalizer only after validating the new pattern.

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
- fallback material assignment when the mesh library prototype has no face-authored material sections

`LeafReferences` does not mean the payload is semantically only leaves. It is the XML source of repeated parts.

Current supported structural cases:

- `LeafReferences` may appear on `Trunk`
- `LeafReferences` may appear on intermediate branch levels
- `LeafReferences` may appear on deeper branch levels before the final repeated detail
- `BoneID` may point at trunk or branch joints as long as it resolves into the `Main Skeleton`

Current explicit non-goal for `Phase 1`:

- nested `part-on-part` hierarchy is not supported as a structural model
- inherited binding from one repeated part instance to another repeated part instance is not supported

### `Meshes/Mesh`

This is the reusable geometry library for part prototypes.

Use it for:

- prototype mesh selection keyed by `MeshID`
- part geometry reconstruction
- prototype face-level material sections derived from `Triangles Material="..."`

If the reusable mesh library prototype already carries face-authored material sections, those sections win over `LeafReferences Material`.

Current conflict policy:

- mesh-authored material sections take precedence
- `LeafReferences Material` becomes a fallback only when the prototype mesh carries no sections
- a mismatch is logged as a warning, not treated as a hard failure, if the prototype mesh itself is internally valid

Current material-role baseline:

- material id `1` = primary tree / branch material
- material id `2` = leaves material
- legacy `0/2` exports are not the active baseline anymore

Current vertex-color override for instanced part prototypes:

- if the prototype mesh carries exact-black vertex color on all authored vertices of a face, that face is assigned to material id `2`
- all other prototype faces are assigned to material id `1`
- this override applies only to `Assembly Parts`, not to the `Base Skeletal Tree`

## Current part interpretation

For the current project contract:

- repeated parts are emitted as `Assembly Parts`
- each inline part is authored as a skeletal part
- each inline part has a one-bone local `Part Skeleton`
- the instance binds back to the `Main Skeleton`
- an optional external reuse path may map a prototype key such as `Mesh_1` to an existing Unreal skeletal mesh asset

## Failure conditions

Fail loudly when the baseline path cannot safely determine:

- the regular unique tree hierarchy
- the `Main Skeleton`
- the `Base Skeletal Tree`
- explicit repeated part identity
- repeated part transforms
- repeated part skeletal binding source
