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
Object names are treated as metadata only, not as the basis for structural decisions.

## Section-to-concept mapping

### `Objects/Object`

This is the source of the regular tree hierarchy and unique geometry.

Use it for:

- unique object hierarchy
- unique tree mesh payloads
- the geometry that becomes the `Base Skeletal Tree`
- placement of `LeafReferences` on any supported hierarchy level

Current observed implementation rule:

- mesh-bearing `Objects/Object` entries in the regular hierarchy are merged into the `Base Skeletal Tree`
- source names are not used to decide whether geometry is base tree geometry; only hierarchy, mesh payloads, and binding data matter
- the converter preserves the authored branch FBX size and orientation as-is; it does not apply hidden prototype scale rebasing or mesh-space compensation
- `LeafReferences` rotations are remapped into stage space by axis basis conversion only; the authored rotation sense is preserved, not inverted

Treat this as the current supported rule, not as a formal SpeedTree guarantee. If additional real exports prove the rule too narrow, update the normalizer only after validating the new pattern.

### `Bones/Bone`

This is the source of the `Main Skeleton`.

Use it for:

- joint identity
- parent chain
- joint transform derivation
- explicit wind generator levels through `Bone/@Generator`

Missing required skeleton coordinates are a hard failure for skeletal export.

Wind-specific contract:

- `Generator` is the authored wind-level source, not a cosmetic label
- `Group_<n>` and variants such as `Group_0 2` normalize to the same level
- multiple generator fragments that share the same normalized level collapse into one wind group
- if a bone does not provide a usable `Generator` label, the wind path rejects the XML instead of inferring levels from hierarchy

### `LeafReferences`

This is the source of `Assembly Parts`.

Use it for:

- repeated part placement
- repeated part prototype selection
- repeated part binding back to the `Main Skeleton`
- fallback material assignment when the mesh library prototype has no face-authored material sections

`LeafReferences` does not mean the payload is semantically only leaves. It is the XML source of repeated parts.

Current supported structural cases:

- `LeafReferences` may appear on any object level that carries repeated part placement data
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

Current material-policy baseline:

- raw XML `Material ID` values are opaque source ids, not semantic roles
- the converter must not assume that XML ids like `3` and `4` mean invalid bark/leaves assignment
- semantic bark/leaves interpretation now exists only in explicit `source_material_roles` mode

Supported exporter material policies:

- `source_material_roles`
  - compatibility mode only
  - keeps the old semantic expectation that material id `1` is primary and id `2` is leaves
  - keeps the old missing-role validation only in this mode
- `single_material`
  - ignores XML material ids and vertex colors
  - remaps the `Base Skeletal Tree` and all `Assembly Parts` to one canonical USD material
  - collapses each mesh to a single full-face section so USDA authors one direct material binding
- `vertex_color_split`
  - ignores XML material ids
  - applies to both the `Base Skeletal Tree` and `Assembly Parts`
  - if every vertex on a face is exact white `(1,1,1)`, that face is assigned to material id `1`
  - any gray or other non-white value is assigned to material id `2`
  - if usable vertex colors are missing, the exporter warns and assigns the mesh to material id `1`

Outside `source_material_roles`, authored XML material ids are preserved only as source metadata on canonical materials and instances.

Current GUI material workflow, stage 1:

- the base tree and repeated parts are configured separately in the GUI
- `Base XML materials` are discovered directly from XML `Materials/Material`, but only for ids used by unique base-tree geometry under `Objects/Object`
- each base-material row exposes:
  - source `ID`
  - source `Name`
  - one Unreal material path
- multiple XML material rows may intentionally point at the same Unreal material path
- repeated part prototypes do not reuse those base-material rows as their only control surface
- repeated part rows currently expose:
  - `single_material`
  - `vertex_color_split`
  - `material_slots` for `FBX file` rows
- `vertex_color_split` is an explicit black/white split for repeated-part materials
- `material_slots` derives its slot list from the imported FBX payload instead of from SpeedTree XML
- only FBX slots actually used by imported faces are exposed
- repeated FBX material names are merged into one logical slot row

Naming policy:

- the generated USDA filename is the canonical authored asset name for the base skeletal tree
- the base mesh prim name comes from the chosen output USDA file stem
- the main skeleton prim name comes from the same output USDA file stem with `_Skeleton` appended
- the base `SkelRoot` comes from the same output USDA file stem with `_Geo` appended
- the XML source filename is not used to derive the skeleton name
- part prototype prim names come from `Meshes/Mesh/@Name`
- when two prototype names collide after USD-safe sanitization, deterministic suffixes are appended in input order
- inline one-bone part skeleton joint names come from the sanitized prototype prim name, not from a hardcoded `root`

## Skeletal parts export mode

The same normalized source data also supports a parts-only library export.

In `skeletal_parts` mode:

- the converter still discovers `Meshes/Mesh` and `LeafReferences`
- prototype discovery, FBX replacement, and Unreal asset reuse stay unchanged
- the chosen output path becomes a container path for a generated parts directory
- one USDA file is written per prototype
- each part file is named from the resolved prototype name, such as `spruce_branch.usda`
- each part file uses the prototype name as `defaultPrim` and root prim name
- no base tree is authored
- no main skeleton prim is authored
- no real `PointInstancer` is authored
- missing base mesh and missing main skeleton are not validation failures
- at least one valid prototype payload is still required

Use this mode when you want to import the repeated parts first and wire them into a project through already-imported part assets later.

## Current part interpretation

For the current project contract:

- repeated parts are emitted as `Assembly Parts`
- each inline part is authored as a skeletal part
- each inline part has a one-bone local `Part Skeleton`
- each inline part uses the prototype-derived one-bone joint name for its local `SkelAnimation`, `Mesh skel:joints`, and `Part Skeleton`
- the instance binds back to the `Main Skeleton`
- an optional external reuse path may map a prototype key such as `Mesh_1` to an existing Unreal skeletal mesh asset
- an optional explicit FBX path may replace one repeated prototype with a rigid high-poly disk mesh payload
- when the external reuse path is enabled, the converter must not leave the original inline prototype mesh attached to that same prototype in USDA
- when the explicit FBX path is enabled, the converter must keep the original `LeafReferences` instance transforms and main-skeleton bindings, and replace only the prototype mesh payload
- the XML mesh library still provides the discovery key and fallback geometry for inline mode, but external mode must author a pure reference-only prototype subtree
- the XML mesh library is also still the prototype-discovery source for explicit FBX replacement; XML `LOD/@Filename` is not used to auto-discover replacement FBX files
- canonical inline XML prototypes are authored at their original branch size by applying SpeedTree `LOD/@OriginalScale` to the prototype mesh payload
- `LeafReferences/Scale` stays a pure per-instance multiplier on top of that prototype size in `PointInstancer.scales`
- explicit FBX replacement keeps the authored FBX prototype size as-is and still uses `LeafReferences/Scale` as the per-instance multiplier

Explicit FBX replacement rules:

- the chosen FBX file must provide rigid polygon mesh data only
- the FBX origin is treated as the attachment pivot
- the converter merges all FBX mesh nodes into one prototype-local payload before USDA authoring
- GUI `vertex_color_split` uses exact black and exact white face buckets
- GUI `material_slots` reads face-used FBX material slots from the imported payload
- if some `material_slots` rows are blank, one filled Unreal material path is reused with a warning
- if all `material_slots` rows are blank, conversion fails
- legacy/config `auto` mode may still use the older fallback-oriented split logic outside the GUI's explicit repeated-part workflow
- missing vertex colors are a hard failure for FBX mode

Main skeleton naming rule:

- when the `Main Skeleton` has exactly one root joint, the converter may alias that root joint name to the output USDA stem for the base skeletal naming contract
- when the `Main Skeleton` has multiple root joints, the converter must preserve distinct root-joint names
- multi-root skeletons must not collapse all roots to the same output-stem alias, because that corrupts base-mesh joint-path authoring

## Common trap

If a part-mesh override looks configured in the UI but the imported USD still contains the low-poly prototype, the first check is whether the generated USDA contains `NaniteAssemblyExternalRefAPI` at all.

- if it does not, the override never reached the exporter
- if it does, but the stage still imports the low-poly mesh in UE, check whether the import path is the Interchange USD importer rather than legacy USD import
- if the path is present but UE still ignores it, verify the exact `/Game/.../Asset.Asset` package/object path against the asset in Content Browser

## Failure conditions

Fail loudly when the baseline `skeletal_assembly` path cannot safely determine:

- the regular unique tree hierarchy
- the `Main Skeleton`
- the `Base Skeletal Tree`
- explicit repeated part identity
- repeated part transforms
- repeated part skeletal binding source
