# SpeedTree Export Guide

This document is intentionally provisional for `v1`.

## Current status

The converter currently derives its observed XML schema from real exported samples rather than from a public XSD. Because of that, the exact export recipe must be finalized only after we validate one or more real sample files through the full pipeline.

## What the converter expects conceptually

- A tree asset with real `trunk/base mesh` data.
- Exported `skeleton / bones / joints`.
- Exported `leaf references`.
- Preferably explicit `units` and `upAxis` metadata.

## What the current real sample already confirms

- Versioning may arrive as `VersionMajor` and `VersionMinor`, not just a single `version` field.
- Trunk geometry may live under `Objects/Object/Points + Triangles`, not only under a simple mesh block.
- Leaf instances may be stored as packed arrays under `LeafReferences`.
- Reusable leaf prototypes may come from `Meshes/Mesh` and be linked by `MeshID`.
- Skeleton data may be encoded as `Bones/Bone` with `ID`, `ParentID`, `Start*`, `End*`, `Radius`, `Mass`, and `Generator`.

## To finalize after first real import validation

- Exact checkbox names in SpeedTree Modeler.
- Whether branch spines are required for later branch segmentation.
- Which grouping/export mode preserves the data most cleanly for observed-schema parsing.
- Supported and unsupported export profiles.
- Whether the current nearest-bone binding heuristic for leaves matches Unreal import expectations closely enough.
