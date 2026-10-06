---
title: How Dynamic Wind works
description: How Unreal's Dynamic Wind turns skeletons and wind groups into GPU animation, its asset dependencies, and the causes of common motion problems.
---

# How Dynamic Wind works

Dynamic Wind generates procedural bone motion for skeletal Nanite vegetation. The skeleton defines where the plant can bend, wind groups define its response, and the GPU calculates the transforms used to render it. Animation clips, an Animation Blueprint, and a Physics Asset are not required for this wind path.

Dynamic Wind is Experimental. Project setup is covered in [Prepare Unreal Engine](../workflows/prepare-unreal.md).

## From asset to moving plant {#pipeline}

The input is a Skeletal Mesh with a Skeleton Asset, reference pose, and skin weights or skeletal Assembly attachments. Unreal stores its wind metadata as **Dynamic Wind Skeletal Data** in the mesh's Asset User Data. During metadata import, the importer matches bone names, assigns simulation groups, and builds chain data.

A component using the Dynamic Wind transform provider registers the skeleton with the world's wind system. Each frame, a GPU compute shader calculates bone motion from the reference pose, time, and wind parameters. Nanite uses the resulting transforms to move the geometry.

SpeedAssembly supplies the mesh and skeleton through USDA and wind metadata through a separate `*_DynamicWind.json`. The JSON contains bone-to-group assignments and response settings. It contains no animation keyframes and does not replace the skeleton or skin weights.

## How it reads the skeleton {#skeleton}

The plugin reads bone parents, pivot positions, and rotations. It does not recognize a trunk from its shape or a branch from its name. Group assignments and the **Is Trunk?** flag provide that meaning.

The JSON importer matches names against the Skeletal Mesh's reference skeleton. The runtime provider reads positions and rotations from its assigned **Skeleton Asset**. Wind data assumes the same bones, order, and reference pose in both. A name-compatible Skeleton with different bone rotations can produce incorrect wind even when the mesh looks correct at rest.

### Bone axes and pivots

For branch motion, the shader treats the bone's reference-pose **local +X** axis as its forward direction. The calculation follows this axis even when it points away from the physical branch segment. This also applies to terminal bones with no children.

Pivots determine where bending occurs. Bone segments, mesh topology, and vertex bindings determine the resulting curvature. Several bones at one pivot or an entire crown weighted to the root cannot produce regional bending.

!!! warning "Exactly vertical branch axes"

    The branch shader constructs an axis from the cross product of bone forward and Unreal +Z. An exactly parallel or opposite direction makes that axis undefined. This depends on the reference-pose +X axis, which can differ from the line drawn between joints. SpeedAssembly corrects this case in its SpeedTree skeletal export; the external-rig path leaves the source axes unchanged.

### Chains come from group boundaries

A bone belongs to the chain formed by walking through parents with the same simulation group. Changing the group starts a new chain. One group can be reused on many separate branches when their parents belong to another group.

The chain calculation assumes a linear same-group path. If a same-group parent splits into two same-group children, the importer aggregates both paths under one chain origin. Its bone count and influence ramp no longer describe either branch independently. A different group on an outgoing path gives that path its own chain origin. SpeedAssembly rejects same-group fork ambiguity when exporting external-skeleton wind JSON.

Bone-name matching uses the names **after Unreal import**. Importers can rename them, for example `Bone.001` to `Bone_001`. Unmatched JSON names leave bones without their intended group; Unreal's wind import does not make this a blocking error. A root-only match can make the whole object move rigidly with its root.

## What the response settings mean {#response-settings}

Simulation groups give parts of the plant a shared wind response. They are separate from materials, mesh sections, skin weights, and repeated-part definitions.

| Setting | Effect |
| --- | --- |
| **Influence** | Scales a non-trunk bone's own bending and torsion. It does not change vertex skin weights. |
| **Use Dual Influence** | Replaces one Influence value with a ramp from **Min Influence** at the chain origin to **Max Influence** at its end. |
| **Shift Top** | Moves more of that ramp toward the chain tip. The ramp follows bone position in the chain by index, not physical distance. |
| **Is Trunk?** | Selects the trunk-specific sway calculation instead of branch motion. The trunk calculation does not use the group's Influence ramp. |
| **Gust Attenuation** | Reduces trunk motion across the asset. At `1`, it suppresses the trunk's own wind rotation; it is not a general branch-strength control. |
| **Is Ground Cover** | Removes the final height-based attenuation of branch rotation so low plants can respond near ground level. It does not replace the trunk's height-dependent calculation. |

A non-trunk bone with zero Influence has no wind rotation of its own, but still inherits motion from its parents. A region's final motion therefore depends on its complete ancestor path and bindings.

Group indices also affect the shader's mixture of texture noise. Adding groups can change the motion pattern even if their Influence values are identical.

## How the animation is calculated {#animation}

The branch calculation combines scrolling texture noise, gust waves, bending toward the wind, torsion around the bone's forward axis, and vertical bounce. It adjusts the response using bone height, direction relative to wind, chain-length data, and group settings. The trunk uses a separate, slower sway calculation.

For each output bone, the shader walks up to the root and accumulates ancestor rotations and pivot offsets. A branch therefore follows trunk motion while adding its own movement. This is a procedural motion model. It does not solve wood stiffness, mass, collisions, or branch-to-branch contact through physics.

### Shared animation across instances

Dynamic Wind batches compatible skeletons and calculates **eight directional variants**, spaced at 45 degrees around Unreal's vertical axis. Each instance selects a variant from its world yaw, rounded to the nearest slice.

Copies in the same batch and direction slice share bone motion. The stock path does not run an independent simulation or generate an independent phase for every planted tree. Variation in placement rotation changes the selected slice, but identical copies can still move together.

The transform buffer stores both current and previous bone transforms for rendering motion. This doubles transform storage, not the number of wind simulations.

### Global wind controls

The world's **Dynamic Wind Subsystem** receives parameters through **Update Wind Parameters**, exposed to Blueprint. A project's wind controller supplies direction, speed, amplitude, and an optional wind texture. [Epic's subsystem API](https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Plugins/DynamicWind/UDynamicWindSubsystem) documents this entry point.

- **Wind Speed** affects both temporal motion and strength. It is a shader control value rather than a calibrated wind velocity in meters per second.
- **Wind Amplitude** scales the normal wind rotations.
- **Wind Texture** supplies noise for branch flow. If none is available, the provider uses a white texture; motion still runs, but loses that texture's variation.

The stock shader uses time and skeleton-relative positions. It does not sample a world-space wind field at each planted instance.

## Runtime dependencies {#requirements}

The runtime path depends on several connected systems:

- Project rendering features and plugins provide Nanite foliage and the Dynamic Wind subsystem. Their configuration is described in [Prepare Unreal Engine](../workflows/prepare-unreal.md).
- The skeletal asset supplies the hierarchy, pivots, +X axes, bindings, and matching mesh and Skeleton reference poses.
- Wind metadata belongs to the **Skeletal Mesh used by the runtime component**. Importing JSON onto another mesh does not configure this one.
- An **Instanced Skinned Mesh Component** uses a **Dynamic Wind Data** transform provider. This is separate from the mesh's Dynamic Wind Skeletal Data. A Static Mesh instancer does not gain skeletal wind from a JSON file.
- The world's Dynamic Wind Subsystem supplies wind settings. Console overrides can take precedence over the controller's speed and amplitude.

The editor Blueprint action **Import Dynamic Wind Skeletal Data from File** loads JSON onto a target Skeletal Mesh and builds its cached chain data. Changes to bone names, hierarchy, or group assignments leave that cache outdated until the metadata is imported again. [Epic documents the import action](https://dev.epicgames.com/documentation/en-us/unreal-engine/BlueprintAPI/DynamicWind/ImportDynamicWindSkeletalDatafro-).

## Practical limits {#limits}

**Geometry determines the visible deformation.** The main skinned mesh can bend where its bones, weights, and topology support it. In this workflow, skeletal Nanite Assembly Parts move rigidly through their attachments and do not bend internally. Separate parts allow distinct attachment motion, at the cost of more runtime transforms. This trade-off is covered in [Choosing what to instance](choosing-assembly-parts.md#choose-boundaries-by-movement).

**GPU motion does not update a CPU physics rig.** Dynamic Wind Data is a GPU-only transform provider. Its rendered deformation does not automatically propagate to collision, Physics Asset bodies, or gameplay socket queries. Those systems have separate motion paths.

**Animation can stop before rendering stops.** Instanced skinned components have an **Animation Min Screen Size** cutoff. `0` uses the renderer's global threshold; a negative component value disables the cutoff. A visible distant plant can therefore stop animating without an asset failure.

**Culling depends on mesh bounds.** The Dynamic Wind provider supplies no animation-specific bounds. Branches moving beyond the mesh's bounds can disappear near view edges.

**Shared Skeleton Assets also share wind registration.** Meshes sharing a Skeleton can reuse the same runtime wind-bone data. Separate Skeleton Assets isolate variants with different wind metadata.

**Bone and Assembly budgets are separate.** Wind cost depends on the skeleton batches, transformed bones, eight directional variants, and ancestor depth. Rendering also processes the placed geometry and Assembly Parts. Increasing `r.Nanite.MaxVisibleAssemblyParts` does not expand wind-bone storage or reduce wind computation. There is no universal safe tree count for a level.

## Console reference {#console-reference}

The following console variables control subsystem creation, wind overrides, and shader behavior. Defaults are from the inspected UE 5.8 source; project configuration can override them.

### Dynamic Wind variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `DynamicWind.Enable` | `1` | Controls creation of the world subsystem at startup. Read-only at runtime. |
| `DynamicWind.OverrideSpeed` | `-1` | Overrides Wind Speed at values `0` or above. Any negative value returns control to the supplied wind parameters. |
| `DynamicWind.OverrideAmplitude` | `-1` | Overrides Wind Amplitude at values `0` or above. A negative value returns control after the override blend becomes negative. |
| `DynamicWind.OverrideRateOfChange` | `0.5` | Rate per second at which the amplitude override blends toward its target. This is not a bone-motion frequency or general controller interpolation setting. |
| `DynamicWind.UseSine` | `0` | Replaces normal wind with simple sine-driven rotation. Useful for checking the rendering/provider connection; bypasses normal groups, influences, and branch behavior. |
| `DynamicWind.PreferAsyncCompute` | `0` | Requests async compute when the GPU supports efficient async compute. |

In sine mode, rotation depends on speed and time, and does not use Wind Amplitude. A successful sine test proves neither correct group matching nor correct normal wind deformation.

### Related diagnostics

| Command or variable | Function |
| --- | --- |
| `r.Skinning.TransformProviders` | Global transform-provider switch, default `1`. Disabling it affects providers beyond Dynamic Wind. |
| `r.Skinning.DefaultAnimationMinScreenSize` | Global animation cutoff, default `0.1`, used when a component's cutoff is `0`. Explains why distant visible instances can stop moving. |
| `r.InstancedSkinnedMeshes.DebugDraw` | Enables instanced-skinned-mesh debug drawing at `1` and disables it at `0`, in builds with debug drawing support. |
| `stat GPU` | Displays GPU timings, including DynamicWind work, in builds with GPU statistics available. |
| `NaniteStats` | Displays Assembly transform demand rather than a Dynamic Wind bone count. Its counter semantics are covered in [Choosing what to instance](choosing-assembly-parts.md#check-the-transform-demand). |
| `r.Nanite.MaxVisibleAssemblyParts` | Assembly transform-buffer capacity, default `262144`. Exhausting it can omit parts under dense placement, independently of wind correctness. |

## How motion problems arise {#diagnostics}

Different failures occur at different boundaries:

| Boundary | Effect of a mismatch |
| --- | --- |
| Mesh binding | Incorrect weights or pivots move the wrong region or prevent regional bending, independently of wind metadata. |
| Names and reference pose | Unmatched JSON names lose group assignments. Different Skeleton Asset rotations change the forward axes used at runtime. |
| Runtime component | Wind data on another mesh, or a component without the wind provider, does not configure the rendered asset. Direct and PCG placement can therefore produce different results if their runtime connections differ. |
| Wind controls | Speed and amplitude overrides take precedence over controller values. Sine mode bypasses normal group response and does not demonstrate correct normal wind behavior. |
| Group response | Same-group forks distort chain data. Zero local Influence still permits ancestor motion, and trunk groups use a separate calculation. |
| Rendering | Screen-size cutoff stops distant animation; insufficient bounds can cull moving branches; exhausted Assembly capacity can omit parts. These symptoms do not imply the same underlying failure. |

## Source notes {#sources}

The behavior above was checked against these files in the local UE 5.8 tree. Paths are relative to `Engine/`.

??? info "Source map for technical artists and developers"

    | Source | What it establishes |
    | --- | --- |
    | `Plugins/Experimental/DynamicWind/Source/DynamicWindEditor/Private/DynamicWindImportData.cpp` | JSON name matching, same-group chains, and mesh Asset User Data. |
    | `Plugins/Experimental/DynamicWind/Source/DynamicWind/Private/DynamicWindSkeletalData.cpp` | Influence ramps and chain-index interpolation. |
    | `Plugins/Experimental/DynamicWind/Source/DynamicWind/Private/DynamicWindProvider.cpp` | Skeleton Asset reference pose, registration, console defaults, texture fallback, and GPU dispatch. |
    | `Plugins/Experimental/DynamicWind/Shaders/DynamicWindEval.usf` | Branch/trunk motion, ancestor accumulation, +X convention, height attenuation, and sine mode. |
    | `Plugins/Experimental/DynamicWind/Source/DynamicWind/Private/DynamicWindData.cpp` | Eight yaw slices, shared animation, GPU-only provider, and absence of animation bounds. |
    | `Source/Runtime/Engine/Classes/Components/InstancedSkinnedMeshComponent.h` | Component provider and animation screen-size cutoff. |
    | `Source/Runtime/Renderer/Private/Skinning/SkinningSceneExtension.cpp` | Renderer provider switch, global cutoff, and transform allocation. |
    | `Source/Runtime/Renderer/Private/Skinning/SkinnedMeshDebugView.cpp` | Instanced skinned debug-draw variable. |

## Related articles {#see-also}

- [Choosing what to instance](choosing-assembly-parts.md)
- [Prepare SpeedTree](../workflows/prepare-speedtree.md)
- [Prepare Unreal Engine](../workflows/prepare-unreal.md)
- [Epic's Dynamic Wind Skeletal Data API](https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Plugins/DynamicWind/UDynamicWindSkeletalData)
