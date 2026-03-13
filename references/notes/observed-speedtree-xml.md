# Observed SpeedTree XML Notes

This note captures findings from `references/speedtree/xml/SkeletyalAssemblyTest_01.xml`.

## Source metadata

- Root tag is `SpeedTreeRaw`.
- Version is encoded as `VersionMajor="10"` and `VersionMinor="0"`.
- `Source` points back to the originating `.spm` file.

## High-value sections

- `Meshes/Mesh`
  Contains prototype mesh library entries. In the current sample there is one reusable mesh named `Suzanne_Leaf`.
- `Objects/Object Name="Branches"`
  Contains trunk or branch geometry as packed arrays under `Points/X|Y|Z` and `Triangles/PointIndices`.
- `Objects/Object Name="Leaves"/LeafReferences`
  Contains instance placement as packed arrays:
  `X`, `Y`, `Z`, `Scale`, `RotAxisX`, `RotAxisY`, `RotAxisZ`, `RotAngle`, `MeshID`, `MeshLOD`.
- `Bones/Bone`
  Contains explicit procedural skeleton data with `ID`, `ParentID`, `Start*`, `End*`, `Radius`, `Mass`, and `Generator`.

## Practical mapping implications

- The canonical skeleton should be derived from `Bones`, not from guessed joint tags.
- Trunk geometry should prefer `Objects/Object/Points + Triangles` over mesh-library geometry.
- Leaf references are instance data, not standalone meshes.
- `MeshID` in `LeafReferences` should resolve through the mesh library to a prototype name.
- `RotAxis* + RotAngle` should be converted into quaternions for USDA `PointInstancer.orientations`.
- Bone binding for leaves can be approximated in `v1` by nearest bone endpoint while a more exact mapping is still unknown.
