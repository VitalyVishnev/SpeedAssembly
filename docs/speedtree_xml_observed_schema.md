# SpeedTree XML Observed Schema

## Active baseline

This note documents the currently selected reverse-engineering baseline:

- `samples/speedtree/simple_tree/variants/SimpleTree_01.xml`

It is an observed field guide, not a formal XSD.

## High-level signature

Observed from the current `SimpleTree_01.xml` export:

- root tag: `SpeedTreeRaw`
- version: `10.0`
- object hierarchy is present with trunk, branch, twig, and root-like objects
- non-zero relative transforms are present
- bones are present in a real parented hierarchy
- spine-bearing objects are present
- leaf references are present with explicit `BoneID` and `MeshID`
- mesh library entries are present for reusable twig/leaf geometry

## Sections currently used by the converter

### `Meshes/Mesh/LOD`

Reusable twig prototypes are read from `Meshes/Mesh`.

Relevant observed fields:

- `Mesh/@ID`
- `Mesh/@Name`
- `LOD/@Level`
- `LOD/Vertices/X|Y|Z`
- `LOD/TriangleIndices`
- `LOD/QuadIndices`

Current policy:

- prefer `LOD Level="0"`
- read `Vertices` as packed point arrays
- read both triangle and quad index payloads
- preserve quads as `faceVertexCounts = 4` instead of triangulating them in the normalizer

### `Objects/Object`

The object graph is the structural backbone of the baseline sample.

Relevant observed fields:

- `Object/@ID`
- `Object/@ParentID`
- `Object/@Name`
- `Object/@AbsX|AbsY|AbsZ`
- `Object/@RelX|RelY|RelZ`
- `Object/@BoundsMin*`
- `Object/@BoundsMax*`
- `Object/Points/X|Y|Z`
- `Object/Triangles/PointIndices`

Current policy:

- keep the full source object graph in the normalized model
- determine base mesh from the available trunk/base body geometry instead of hardcoding a sample count
- keep branch objects as separate branch segments in the normalized model
- do not try to deduplicate branch meshes into prototypes yet

### `Object/LeafReferences`

Leaf instances are authored from explicit per-object `LeafReferences` blocks.

Relevant observed fields:

- `LeafReferences/@Count`
- `LeafReferences/X|Y|Z`
- `LeafReferences/Scale`
- `LeafReferences/RotAxisX|RotAxisY|RotAxisZ`
- `LeafReferences/RotAngle`
- `LeafReferences/MeshID`
- `LeafReferences/MeshLOD`
- `LeafReferences/BoneID`

Current policy:

- leaf instances are created directly from these arrays
- `MeshID` selects the reusable prototype mesh
- `BoneID` is the authoritative skeletal binding source
- single `BoneID` values are normalized into the general binding model rather than a sample-specific rigid binding shortcut
- no nearest-joint heuristic is used for the baseline sample

Observed distributions for the current export are useful for regression analysis, but they are not converter contract values.

### `Bones/Bone`

The skeletal hierarchy is read directly from `Bones/Bone`.

Relevant observed fields:

- `Bone/@ID`
- `Bone/@ParentID`
- `Bone/@StartX|StartY|StartZ`
- `Bone/@EndX|EndY|EndZ`
- `Bone/@Generator`

Current policy:

- create one normalized joint per XML bone
- preserve parent chain exactly
- use `End*` as the current rest-translation source in the emitted USDA
- require skeleton presence for skeletal export
- derive UE support primvars from the normalized skeleton topology when the XML does not provide them explicitly

### `Object/Spine`

`Spine` exists on trunk and branch objects in the baseline sample.

Relevant observed fields:

- `Spine/X|Y|Z`
- `Spine/Radius`

Current policy:

- parse and preserve `Spine` in the normalized model
- do not require `Spine` for USDA writing
- reserve `Spine` for validation, debug, and future wind work

## Noise currently ignored by the converter

The baseline sample contains additional data that is not needed for the current milestone:

- `AO`
- `Blend`
- `Normal*`
- `Binormal*`
- `Tangent*`
- `VertexColor*`
- most material-map payload details

These fields are still useful for future material or shading work, but they are not part of the current skeletal assembly authoring path.

## Baseline mapping rules

Current explicit mapping rules for `SimpleTree_01.xml`:

- base mesh: trunk plus branch body meshes selected from the object graph
- skeleton: `Bones/Bone`
- prototypes: `Meshes/Mesh` LOD0 meshes keyed by `MeshID`
- leaf instances: `Object/LeafReferences`
- leaf skeletal binding: `LeafReferences/BoneID`, normalized into the general UE binding model
- optional validation geometry: `Object/Spine`

## Failure conditions enforced by the converter

The converter currently treats the following as blocking errors for the baseline path:

- missing object hierarchy
- missing base body mesh
- missing skeleton
- missing explicit leaf `BoneID`
- inconsistent packed array lengths or malformed face index payloads
