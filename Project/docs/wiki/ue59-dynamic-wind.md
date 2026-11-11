# UE 5.9 force-based Dynamic Wind

Inspected 2026-11-11. Source-only comparison of the supplied Engine trees:
`D:/3D Personal/ue5.7 source/UnrealEngine/Engine` (5.7.4),
`ue5.8 source/UnrealEngine/Engine` (5.8.2), and
`ue5.9 source/UnrealEngine/Engine` (5.9.0, changelists zero).
The exact 5.9 Preview/commit is not established. The archived report includes
source paths, line references and SHA-256, plus a compact manifest. No engine
files changed. The initial report was source-only; the implementation and
UE 5.9.0 CL60351404 validation below followed that report. No performance
benchmark was performed.

Evidence: `<archive>/dynamic_wind_ue59_2026-11-11/`, under the external archive
defined in [Experiments](experiments.md#storage-policy).

## Architecture findings

- 5.7 already evaluates Dynamic Wind bones with a compute shader. 5.8 retains
  the motion algorithm while changing proxy registration, BoneMap access and
  transform-buffer integration. Its `DynamicWindSkeletalData.cpp`,
  `DynamicWindParameters.h` and editor `DynamicWindImportData.cpp` are
  byte-identical to the supplied 5.7 versions.
- 5.9 defaults `DynamicWind.Mode` to 1: force-driven, persistent sway/flutter
  state, optional directional/torsional aerodynamics and a separate FK pass.
  Mode 0 keeps stateless parametric cardinal animation without local forces.
- Eight cardinal tracks remain shared per mesh asset. Local forces/capsules
  promote affected instances into whole-skeleton tracks. GPU culling, hashing,
  slot assignment and GPU Scene animation-index writes handle that selection.
  Default ceiling is 256 tracks per mesh, initial committed floor 0, grace
  3 seconds and fade 1 second. Exhaustion leaves instances on shared wind.
- CPU still owns source registration, RDG, buffer sizing and asynchronous
  demand readback. `IsGpuOnly()` means no required owning-component game-thread
  tick, not that the entire subsystem has no CPU work.
- Editor/cook mesh analysis supplies mass, inertia, drag area, centers of
  pressure and subtree data. Nanite Assembly geometry is included by default.
  Section geometry, slot names and Two Sided affect wood/leaf classification.
  Missing source MeshDescription/weights prevents a usable bake.
- Physical modal frequency requires valid authored structural radii. Without
  them, force mode still works with the frequency/length-ramp model. The solver
  uses subtree loads and incoming parent-to-joint segments; this is not a
  general Chaos or fluid simulation.

Do not claim a measured speedup. Local integration removes repeated expensive
ancestor evaluation, but state, sources, FK and track management add work.
Packed persistent bend/world state is 32 + 32 bytes per bone per committed
track, including eight cardinal slices; output transforms and other buffers
are additional. Costs depend on bones, paths, assets, active tracks and sources.

## Converter implications

The operator reports that upgraded trees automatically rebaked and respond to
Force Components and Push Capsules. This agrees with `PostLoad` regeneration
of existing `DynamicWindSkeletalData`; it is operator evidence, not a new
validation of every export mode. SpeedAssembly now authors both Wind JSON and
the DynamicWind USD schema for Force Based Skeletal Assembly exports.

Existing skeletons, skinning, groups and Trunk flags remain useful. Legacy
Influence/dual ramps, Ground Cover and Gust Attenuation are consumed by the
parametric path, not general force-response controls. Same-group forks still
affect chain metadata/taper; do not relax the existing export guard.

Implemented authoring contract:

1. Force Based extends the group model/JSON with 5.9 physics overrides, preserving
   absent overrides as project defaults. `WindResponseScale` scales aero area,
   not the direct capsule force. Do not translate Legacy Influence into it.
2. Shared Source extraction supplies Bone sections and Spine samples. Wind maps
   them to incoming joint segments before exporting `AuthoredSegmentLengthM`,
   `AuthoredRadiusSamplesM` and `AuthoredSampleDistancesM`. Whole-branch curves
   still need per-joint section resolution. Physical Bone Segment and Hierarchy
   Connector remain distinct; the mapping preserves units and junctions.
3. Force Based USD uses `DynamicWindSkeletonAPI_1` and named
   `DynamicWindSimulationGroupAPI` instances to automate USD wind import.
   The reader retains the original API too. Its structural arrays use stage
   units; the JSON fields above use meters. The supplied plugin resource tree
   lacks readable `schema.usda`; subsequent real import confirmed registration.

`BaseMaxBendAngle`/`TipMaxBendAngle` in the current structs are degrees. The
local WindSimulationGuide's radians wording is stale. Code also adds modal
frequency behavior beyond that guide. Follow source, not the guide alone.

Reimport replaces SimulationGroups; old JSON can reset 5.9 group tuning to
defaults. MaxActiveInstances is mesh/runtime configuration and is not a field
of the current wind import struct. Merely adding it to JSON will not set it.
Implementation now has independent Legacy/Force Based UI profiles, shared main
and Advanced group controls, and matching JSON/USD authoring. UE 5.9 import
and reimport verified all group overrides, including clearing disabled values.
Runtime derivation accepted authored radii and produced valid modal data for
42 of 42 non-root bones in SimpleTree_01. See the implementation decision and
[remaining validation limits](known-bugs.md#ue-59-validation-limits).

## Source navigation

Under `Engine/Plugins/Experimental/DynamicWind/`:

- `Shaders/DynamicWindEval.usf`: torque, sway/flutter, curvature and FK.
- `Shaders/DynamicWind{Cull,Reconcile,Sweep,Emit}.usf`: instance/track lifecycle.
- `Shaders/Shared/DynamicWindCommon.h`: GPU layouts and limits.
- `Source/DynamicWind/Private/DynamicWindProvider.cpp`: physics resolution,
  asset pools, CPU allocation/readback and GPU dispatch.
- `Source/DynamicWind/Private/DynamicWindMeshAnalyzer.cpp`: geometry bake.
- `Source/DynamicWind/Private/DynamicWindMeshBoneDataCompiler.cpp`:
  authored-profile requirement and modal-frequency bake.
- `Source/DynamicWind/Private/DynamicWindSkeletalData.cpp`: DDC/cook lifecycle.
- `Source/DynamicWindEditor/Public/DynamicWindImportData.h`: JSON fields.
- `Source/DynamicWindEditor/Private/DynamicWindUSDImport.cpp`: both USD APIs.

Also inspect PVE `PVExportHelper.cpp:1417` for structural-profile authoring and
`Engine/Source/Runtime/Engine/Public/Animation/TransformProviderData.h:39`
for the exact GPU-only provider contract.
