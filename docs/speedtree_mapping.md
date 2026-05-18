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
- `LeafReferences` -> source-level `Repeated Parts`, which become authored
  `Assembly Parts`

This split is structural and explicit. It is not based on botanical names.
Object names are treated as metadata only, not as the basis for structural decisions.

## Explicit mapping decisions

The converter must make these decisions explicitly in code:

1. what becomes the `Base Skeletal Tree`
2. what becomes a `Source Prototype`, `Resolved Prototype`, and `Authored Prototype`
3. what becomes a `Repeated Part Instance`, `Resolved Instance`, and `Authored Instance`
4. how Assembly Parts bind to the `Main Skeleton`
5. how transforms are converted between Source Space, Stage Space, Prototype Space, Attachment Space, and PointInstancer arrays
6. how missing source data is handled
7. how base-tree XML material slots are resolved separately from repeated-part prototype material modes
8. how explicit FBX repeated-part material modes (`single_material`, `vertex_color_split`, `material_slots`) are resolved

No hidden heuristics.

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
- `LeafReferences` rotations are remapped from Source Space into Stage Space by
  axis basis conversion only; the authored rotation sense is preserved, not
  inverted

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

This is the source of source-level `Repeated Parts`.

Use it for:

- repeated part placement
- repeated part prototype selection
- repeated part Attachment source for later skeletal binding back to the `Main Skeleton`
- fallback material assignment when the mesh library prototype has no face-authored material sections

`LeafReferences` does not mean the payload is semantically only leaves. It is
the XML source of repeated parts.

Current supported structural cases:

- `LeafReferences` may appear on any object level that carries repeated part placement data
- `LeafReferences` may appear on intermediate branch levels
- `LeafReferences` may appear on deeper branch levels before the final repeated detail
- `BoneID` may point at trunk or branch joints as long as it resolves into the
  `Main Skeleton` for skeletal export
- each placed record from `LeafReferences` is a source-level `Repeated Part
  Instance`; USDA authoring later turns it into an `Authored Instance` in
  `PointInstancer` arrays
- `BoneID` is treated as a source Attachment input, not as already-authored USD
  Skeletal Binding

Current explicit non-goal for `Phase 1`:

- nested `part-on-part` hierarchy is not supported as a structural model
- inherited binding from one repeated part instance to another repeated part instance is not supported

### `Meshes/Mesh`

This is the reusable geometry library for Source Prototypes.

Use it for:

- Source Prototype mesh selection keyed by `MeshID`
- part geometry reconstruction
- Source Prototype face-level material sections derived from `Triangles Material="..."`

If the reusable mesh library Source Prototype already carries face-authored
material sections, those sections win over `LeafReferences Material`.

Current conflict policy:

- mesh-authored material sections take precedence
- `LeafReferences Material` becomes a fallback only when the Source Prototype mesh carries no sections
- a mismatch is logged as a warning, not treated as a hard failure, if the Source Prototype mesh itself is internally valid

Current material-policy baseline:

- raw XML `Material ID` values are Source Material ids, not semantic roles
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

Outside `source_material_roles`, authored XML material ids are preserved only as
Source Material metadata on canonical materials and instances.

Current GUI material workflow, stage 1:

- the base tree and repeated parts are configured separately in the GUI
- `Base XML materials` are discovered from Source Materials in XML
  `Materials/Material`, but only for ids used by unique base-tree geometry
  under `Objects/Object`
- each base-material row exposes:
  - source `ID`
  - source `Name`
  - one Unreal material path
- multiple XML Source Material rows may intentionally point at the same Unreal material path
- repeated part prototypes do not reuse those base-material rows as their only control surface
- repeated part rows currently expose:
  - `single_material`
  - `vertex_color_split`
  - `material_slots` for `FBX file` rows
- `vertex_color_split` is an explicit black/white split for repeated-part materials
- `material_slots` derives its Source Material slot list from the imported FBX payload instead of from SpeedTree XML
- only FBX slots actually used by imported faces are exposed
- repeated FBX material names are merged into one logical slot row

Naming policy:

- the generated USDA filename provides the `Output Stem`
- the Output Stem is the canonical Authored Asset Name for the base skeletal tree
- the base mesh Prim Name comes from the chosen Output Stem
- the main skeleton Prim Name comes from the same Output Stem with `_Skeleton` appended
- the base `SkelRoot` Prim Name comes from the same Output Stem with `_Geo` appended
- the XML source filename is a Source Name and is not used to derive the skeleton name
- Source Prototype Prim Name seeds come from `Meshes/Mesh/@Name`
- when two Authored Prototype Prim Names collide after USD-safe sanitization, deterministic suffixes are appended in input order
- inline one-bone part skeleton joint names come from the sanitized Authored Prototype Prim Name, not from a hardcoded `root`

## Skeletal parts export mode

The same normalized source data also supports a parts-only library export.

In `skeletal_parts` mode:

- the converter still discovers `Meshes/Mesh` and `LeafReferences`
- Source Prototype discovery, FBX replacement, and Unreal asset reuse stay unchanged
- the chosen output path becomes a container path for a generated parts directory
- one USDA file is written per Resolved Prototype
- each part file is named from the resolved prototype name, such as `spruce_branch.usda`
- each part file uses the Authored Prototype name as `defaultPrim` and root prim name
- no base tree is authored
- no main skeleton prim is authored
- no real `PointInstancer` is authored
- missing base mesh and missing main skeleton are not validation failures
- at least one valid prototype payload is still required

Use this mode when you want to import the repeated parts first and wire them into a project through already-imported part assets later.

## Static assembly export mode

The static assembly path reuses the same normalized source data but changes the authored USDA contract.

In `static_assembly` mode:

- the converter still discovers `Objects/Object`, `Meshes/Mesh`, and `LeafReferences`
- the regular XML hierarchy still provides the unique base geometry
- `LeafReferences` still provide repeated part placement
- `LeafReferences` position, rotation, and scale data become Instance Transform
  input, then `PointInstancer` placement data on Authored Instances
- the authoring result is a single USD file with `NaniteAssemblyRootAPI` and `meshType = "staticMesh"`
- the root prim is the stage root itself; a `defaultPrim` is not required for this mode
- the root `PointInstancer` carries all placed geometry, including one synthetic base Authored Prototype at the tree pivot when a base mesh exists
- no skeleton data is authored
- no skeletal binding arrays are authored
- inline repeated parts become static `Xform` + `SM_`-prefixed `Mesh` prototypes when the source name does not already start with `SM_`
- external Unreal reuse becomes static `Xform` prototypes with `NaniteAssemblyExternalRefAPI`

Use this mode when the tree or vegetation should behave as rigid static Nanite assembly geometry rather than as a skeletal tree.

## Current part interpretation

For the current project contract:

- repeated parts are emitted as `Assembly Parts`
- `Repeated Parts` are the source-level records from `LeafReferences`; `Assembly
  Parts` are the authored repeated parts in the generated USDA
- in code, source repeated parts are `RepeatedPartInstance` values and USDA
  authoring projects them into `AuthoredAssemblyPartInstance` values
- each inline part is authored as a skeletal part
- each inline part has a one-bone local `Part Skeleton`
- each inline part uses the prototype-derived one-bone joint name for its local `SkelAnimation`, `Mesh skel:joints`, and `Part Skeleton`
- skeletal exports bind each Authored Instance back to the `Main Skeleton`
  through Skeletal Binding
- an optional external reuse path may map a Source Prototype key such as
  `Mesh_1` to an existing Unreal skeletal mesh asset by Unreal Asset Path
- an optional explicit FBX path may replace one Resolved Prototype with a rigid high-poly disk mesh payload
- when the external reuse path is enabled, the converter must not leave the original inline Source Prototype mesh attached to that same Authored Prototype in USDA
- when the explicit FBX path is enabled, the converter must keep the original
  Repeated Part Instance transforms and Attachment-derived skeletal binding, and replace
  only the Resolved Prototype payload
- the XML mesh library still provides the discovery key and fallback geometry for inline mode, but external mode must author a pure reference-only Authored Prototype subtree
- the XML mesh library is also still the Source Prototype discovery source for explicit FBX replacement; XML `LOD/@Filename` is not used to auto-discover replacement FBX files
- canonical inline XML prototypes are authored at their original branch size by applying SpeedTree `LOD/@OriginalScale` to the Authored Prototype mesh payload
- `LeafReferences/Scale` stays a pure per-instance multiplier on top of that
  prototype size in `PointInstancer.scales`
- explicit FBX replacement keeps the authored FBX prototype size as-is and still uses `LeafReferences/Scale` as the per-instance multiplier

Explicit FBX replacement rules:

- the chosen FBX file must provide rigid polygon mesh data only
- the FBX origin is treated as the Attachment Space pivot for that Resolved
  Prototype
- the converter merges all FBX mesh nodes into one Resolved Prototype payload before USDA authoring
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
