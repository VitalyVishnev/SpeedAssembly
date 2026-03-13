# SpeedTree XML Observed Schema

## Active baseline

This note documents the currently selected reverse-engineering baseline:

- `samples/speedtree/simple_tree/variants/SimpleTree_01.xml`

It is an observed field guide, not a formal XSD.

## High-level signature

Observed from the current `SimpleTree_01.xml` export:

- root tag: `SpeedTreeRaw`
- version: `10.0`
- objects: `63`
- hierarchy depth: `4`
- object classes:
  - trunk: `1`
  - branch: `22`
  - twig: `39`
  - other: `1` root object
- bones: `105`
- spine-bearing objects: `23`
- leaf references: `39`
- mesh library entries: `2`

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
- use `Trunk` object mesh as the base skeletal mesh candidate
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
- `BoneID` is the authoritative rigid skeletal binding source
- no nearest-joint heuristic is used for the baseline sample

Observed distributions for the current export:

- leaf `MeshID`: `{1: 13, 2: 26}`
- leaf `BoneID` set: `17, 19, 20, 22, 24, 30, 32, 34, 35, 36, 44, 46, 49, 51, 56, 57, 59, 61, 63, 64, 66, 67, 68, 70, 71, 77, 78, 80, 84, 90, 92, 94, 96, 98, 99, 100, 101, 102, 104`

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

- base mesh: `Object Name="Trunk"`
- skeleton: `Bones/Bone`
- prototypes: `Meshes/Mesh` LOD0 meshes keyed by `MeshID`
- leaf instances: `Object/LeafReferences`
- leaf skeletal binding: `LeafReferences/BoneID`
- optional validation geometry: `Object/Spine`

## Failure conditions enforced by the converter

The converter currently treats the following as blocking errors for the baseline path:

- missing object hierarchy
- missing trunk mesh
- missing skeleton
- missing explicit leaf `BoneID`
- inconsistent packed array lengths or malformed face index payloads
