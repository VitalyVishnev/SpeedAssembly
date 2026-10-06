---
title: Import into Unreal Engine
description: Import SpeedAssembly assets with Interchange, apply Wind JSON, and test Dynamic Wind in Blueprint or PCG.
---

# Import into Unreal Engine

Before importing, complete [Prepare Unreal Engine](prepare-unreal.md). The required plugins and Nanite Foliage setting must be enabled. Have your exported USDA and, for a skeletal plant, its matching Wind JSON ready.

## 1. Import the USDA

1. In Unreal's **Content Browser**, open the folder where you want the plant assets.
2. Drag the exported `.usda` file into that folder. The Interchange **Import Content** window opens.
3. Select **Default USD Assets Pipeline** and apply the settings in the tables.

![Interchange Import Content window with Default USD Assets Pipeline selected](../assets/images/unreal-import-dialog.png){ style="max-height: 700px; width: auto;" }

### Common

| Setting | Value |
| --- | --- |
| Scene Name Sub Folder | Off |
| Asset Type Sub Folders | Off |

### Common Meshes

| Setting | Value |
| --- | --- |
| Force All Mesh as Type | None |
| Import Lods | Off |
| Bake Meshes | Off |
| Recompute Normals | Off |

### Common Skeletal Meshes and Animations

| Setting | Value |
| --- | --- |
| Import Only Animations | Off |
| Try Auto Select Skeleton | Off |
| Skeleton | None |

!!! warning "Check Skeleton before each import"

    Do not reuse another tree's Skeleton. Unreal can preselect an existing Skeleton when importing into a folder that already contains skeletal assets. Clear the field to **None** so the imported plant receives its own Skeleton.

### Static Meshes

| Setting | Value |
| --- | --- |
| Import Static Meshes | On |
| Import Collisions | On |
| Build Nanite | On |

Keep static mesh import enabled even when importing a skeletal plant. The same setup can then import Static Assembly, standalone static parts, and Proxy Mesh files. **Import Collisions** allows the prepared proxy collision to import.

### Skeletal Meshes

| Setting | Value |
| --- | --- |
| Import Skeletal Meshes | On |
| Import Morph Targets | Off |
| Create Physics Asset | Off |

Dynamic Wind does not require a Physics Asset or animation clips. Disabling their creation avoids unnecessary assets in the Content Browser. Morph targets are not used by this workflow.

### Animations, materials, and other asset types

| Section | Setting | Value |
| --- | --- | --- |
| Animations | Import Animations | Off |
| Materials | Import Materials | On |
| Textures | Import Textures | Off |
| Sparse Volume Textures | Import Sparse Volume Textures | Off |
| Grooms | Enable Groom Types Import | Off |

Keep **Import Materials** enabled so Interchange reads the material assignments in the USDA. The Unreal materials assigned in SpeedAssembly must already exist in the project.

Leave other settings unchanged. Unreal remembers pipeline settings for later imports, but always check **Skeleton** and the selected pipeline. **Use the same settings for subsequent files** applies the current setup to subsequent files in the import operation.

4. Click **Import** and wait for mesh and Nanite compilation to finish.

## 2. Check the imported assets

The expected result depends on the export mode:

| Export mode | Expected assets |
| --- | --- |
| Skeletal Assembly | The complete plant as a Skeletal Mesh with its Skeleton, plus each exported part as a Skeletal Mesh with its part Skeleton. |
| Static Assembly | The base geometry and exported parts as Static Meshes, plus the assembled plant as a Static Mesh Nanite Assembly. |
| Skeletal Assembly Parts | The individual skeletal parts and their Skeletons, without the assembled tree. |
| Static Assembly Parts | The individual Static Mesh parts, without the assembled tree. |

Parts using **Use Unreal Reference** reuse the assets you supplied instead of creating another copy. Fully baked Scattered Rig exports import as ordinary Skeletal Meshes rather than assemblies with separate parts.

Open the final plant and check its size, orientation, and materials. For an assembly, inspect **Nanite Assembly References** under **Nanite Settings** to check the referenced parts.

### Static Assembly fallback in UE 5.7

In UE 5.7, a Static Assembly can generate a fallback mesh retaining the full tree's geometry. For a high-poly tree, this produces an unnecessarily large fallback and takes a long time to build.

To reduce an oversized fallback:

1. Open the final Static Mesh Assembly asset.
2. Under **Nanite Settings**, set **Fallback Target** to **Percent Triangles**.
3. Lower **Fallback Triangle Percent**, then apply the changes and let Unreal rebuild the mesh.

The same manual correction was not needed in the tested UE 5.8 workflow.

![Nanite Settings with Fallback Target set to Percent Triangles and a low Fallback Triangle Percent](../assets/images/unreal-static-fallback.png)

The screenshot shows a very low percentage as an example, not a universal setting. Check the rebuilt fallback against its intended use before choosing the final value.

### Import a proxy

Drag the separately exported Proxy USDA into the desired Content Browser folder using the same import setup. It imports as a Static Mesh. Check that its prepared simple collision is present. See [Proxy Mesh](proxy-mesh.md) for generation and use.

## 3. Import Wind JSON

Skip this step for static exports.

1. In the **Content Browser**, right-click the final plant's **Skeletal Mesh**, not its Skeleton or one of its branch parts.
2. Select **Scripted Asset Actions > Import Dynamic Wind Data**.
3. Select the matching Wind JSON generated by SpeedAssembly.

![Import Dynamic Wind Data in the Skeletal Mesh context menu](../assets/images/unreal-import-wind-json.png)

4. Open the Skeletal Mesh. In **Asset Details**, expand **Skeletal Mesh > Asset User Data** and locate **Dynamic Wind Skeletal Data**.
5. Check that **Is Enabled** is selected, then expand **Simulation Groups** and compare the settings with your SpeedAssembly setup.
6. Save the Skeletal Mesh.

![Dynamic Wind Skeletal Data with Is Enabled and Simulation Groups visible](../assets/images/unreal-wind-asset-data.png){ style="max-height: 650px; width: auto;" }

You can adjust the group response settings here after import. They control bone motion under wind. Use the JSON from the same plant and skeleton; a file from another tree can assign groups incorrectly.

### Optional shape preservation

In the mesh's **Nanite Settings**, choose **Preserve Area** or **Voxelize** for **Shape Preservation** if the foliage loses too much area or volume at a distance. Compare the result in your scene. This is a visual-quality choice, not a requirement for Dynamic Wind.

## 4. Find the wind assets

The sample wind assets are included with **Procedural Vegetation Editor**, which you enabled during project preparation.

1. In the **Content Browser** settings, enable **Show Engine Content** and **Show Plugin Content** if the plugin assets are hidden.
2. Open **Procedural Vegetation Editor > SampleAssets > Materials > GlobalFoliageActor**.

![Procedural Vegetation Editor sample folder containing BP_GlobalFoliageActor_UE5 and Wind_TransformProvider](../assets/images/unreal-wind-sample-assets.png)

This folder contains **Wind_TransformProvider** and **BP_GlobalFoliageActor_UE5**. Use the provider when configuring the components that display your skeletal plants.

!!! warning "Assign Transform Provider before generating vegetation"

    For this Dynamic Wind workflow, always assign **Wind_TransformProvider** to the component or PCG spawner before creating instances. Importing Wind JSON onto a mesh does not configure its component. Without the provider, Dynamic Wind will not animate the instances.

## 5. Test one plant in Blueprint

Use an **Instanced Skinned Mesh** component for the wind test. Placing a regular Skeletal Mesh Actor is not the same setup.

1. Create an Actor Blueprint and add an **Instanced Skinned Mesh** component.
2. In the component's **Details**, assign the final plant to **Skeletal Mesh**.
3. Under **Animation**, set **Transform Provider** to **Wind_TransformProvider**.
4. Under **Instances**, add one array element. Keep its rotation and location at zero and its scale at one for the initial test.
5. Compile and save the Blueprint, then place it in the level.

[![Blueprint with the plant mesh, Wind_TransformProvider, and one instance assigned](../assets/images/unreal-wind-blueprint.png)](../assets/images/unreal-wind-blueprint.png)


### Use the plant in PCG

1. In your PCG graph, use **Instanced Skinned Mesh Spawner**.
2. Set **Mesh Attribute** to the attribute containing your plant's Skeletal Mesh path.
3. In **Template Descriptor**, set **Transform Provider** to **Wind_TransformProvider** before generating the graph.

![PCG Instanced Skinned Mesh Spawner with Wind_TransformProvider assigned](../assets/images/unreal-wind-pcg.png)

Assign the provider before generating the graph, even if you plan to tune wind later. Leaving it unset disables skeleton batching, so Unreal allocates skeleton buffers separately for components instead of sharing them. Dense vegetation can exceed the buffers' offset limits and crash with a `SkinningSceneExtension.h` assertion. This crash was confirmed in UE 5.7; assigning **Wind_TransformProvider** restored batching and resolved it. The same allocation risk remains in UE 5.8 according to source inspection, although the crash has not been reproduced there. The provider is required for Dynamic Wind in both versions.

## 6. Control the wind in the level

Drag **BP_GlobalFoliageActor_UE5** from the sample folder into the level. Use its exposed wind controls to test the plant's response. You can later use the Blueprint as a reference for your own wind controller, including exposing Wind Amplitude if needed.

!!! tip "World Partition"

    Disable **Is Spatially Loaded** in the global wind controller's **World Partition** settings so camera-distance streaming does not unload it. Keep its Data Layer enabled as well. Streaming this controller has caused Unreal crashes; keep it loaded while vegetation uses Dynamic Wind.

Save the controller and your plant Blueprint. Confirm that the plant moves with wind, keeps its material assignments, and has no missing branches or foliage. Test several copies at the density you intend to use before populating the level.

See [How Dynamic Wind works](../wiki/how-dynamic-wind-works.md) for response settings and motion diagnostics, and [Choosing what to instance](../wiki/choosing-assembly-parts.md) for Assembly transform budgets.
