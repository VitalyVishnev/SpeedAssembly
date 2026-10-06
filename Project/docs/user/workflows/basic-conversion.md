---
title: Convert in SpeedAssembly
description: Load your SpeedTree export, configure wind and geometry, assign Unreal materials, and export USDA and Wind JSON.
---

# Convert in SpeedAssembly

Start with the XML exported using the settings in [Prepare SpeedTree](prepare-speedtree.md). Your Unreal project should also be [prepared for import](prepare-unreal.md), with the materials you want to use already available in its Content Browser.

## 1. Select the input and output

1. In SpeedAssembly, click **Input XML** and select your SpeedTree XML file.
2. Check **Output USDA**. By default, it uses the XML's folder and filename with a `.usda` extension.
3. Optional: Click **Output USDA** to choose a different destination or filename.

![Input XML and Output USDA fields highlighted in SpeedAssembly](../assets/images/conversion-input-output.png)

SpeedAssembly analyzes the file automatically. The **Wind**, **Geometry**, and **Materials** tabs show the detected wind groups, repeated branches and leaves, and material slots. Wait for the analysis to finish before configuring them.

## 2. Configure Wind

For a skeletal plant, open the **Wind** tab to choose how the geometry bends and how each detected group responds to wind.

![Wind tab with Skinning Quality and detected wind groups](../assets/images/conversion-wind.png)

### Choose Skinning Quality

Set **Skinning Quality** before conversion:

- **1 weight** attaches each vertex to one bone. Bending has distinct joints rather than smooth curves. This is the default, lowest-cost setting and the recommended starting point for trees.
- **2 weights** blend between bones for smoother bending. Use this when stem deformation is noticeable, such as tall grass or ferns. Branch junctions may need closer inspection.
- **3 weights** and **4 weights** preserve more of the deformation inherited from parent branches. They cost more at runtime and can improve motion at complex junctions.

<div style="display: flex; gap: 16px;" markdown="1">
<figure style="flex: 1; min-width: 0; margin: 0;" markdown="1">

<div style="position: relative; overflow: hidden; aspect-ratio: 1134 / 830;" markdown="1">

![Fern stem with an angular bend using one skinning weight](../assets/images/conversion-skinning-one-weight.png){ style="position: absolute; width: 200%; max-width: none; height: auto; left: -50%; top: -50%;" }

</div>

<figcaption>1 weight</figcaption>
</figure>
<figure style="flex: 1; min-width: 0; margin: 0;" markdown="1">

<div style="position: relative; overflow: hidden; aspect-ratio: 1134 / 830;" markdown="1">

![Fern stem with a smoother curve using two skinning weights](../assets/images/conversion-skinning-two-weights.png){ style="position: absolute; width: 200%; max-width: none; height: auto; left: -50%; top: -50%;" }

</div>

<figcaption>2 weights</figcaption>
</figure>
</div>

Skinning Quality determines the weights written into the USDA geometry. It is not part of Wind JSON. To change it later, convert the plant again with the new setting and reimport it.

### Set group behavior

1. Review the detected groups, such as **Group 0**, **Group 1**, and **Group 2**.
2. Mark trunk groups with **Trunk**.
3. Adjust **Influence**, or enable **Dual Influence** and adjust **Min Influence**, **Max Influence**, and **Shift Top**.
4. Adjust **Gust Attenuation** for trunk gust response.
5. Enable **Ground Cover** for low-growing plants when appropriate.

These group and wind settings go into Wind JSON, which you import onto the Skeletal Mesh in Unreal. You can change them later in Skeletal Mesh settings in Unreal. If you are unsure, keep the defaults and tune the motion in Unreal.

**Total bones** shows the current skeleton count. Click **Refresh Wind Groups** to repeat the analysis, or **Advanced Wind Settings** to inspect the skeleton and edit group assignments in a separate viewport.

For background on the wind controls, see [How Dynamic Wind works](../wiki/how-dynamic-wind-works.md).

<!-- Add Wind tab and Advanced Wind Settings procedure links when those guides exist. -->

### Leaf-only plants

If the XML contains only repeated leaf geometry, with no base mesh or skeleton, SpeedAssembly automatically shows **Scattered Rig Mode** instead of Skinning Quality. It also shows **Average Instance Orientation** option.

The available rig types are **Whole Mesh (Skinned)**, **Per Cluster (Rigid)**, **Per Cluster (Skinned)**, and **Per Instance (Rigid)**. The two Per Cluster options require detected clusters. These controls let SpeedAssembly create a skeleton for the plant; they are separate from the export-mode selection.

![Wind tab with Scattered Rig Mode and Average Instance Orientation highlighted for leaf-only input](../assets/images/conversion-scattered-rig.png)

<!-- Add the dedicated Scattered Rig workflow link when that guide exists. -->

## 3. Review Geometry

Open **Geometry** to review the repeated branches and leaves. Each row shows a mesh and how many times the plant uses it.

![Geometry tab with a repeated branch set to Use FBX File](../assets/images/conversion-geometry.png)

For each mesh, choose its **Source Mode**:

- **Use XML Mesh** keeps the geometry exported from SpeedTree.
- **Use FBX File** replaces it with a mesh from an external FBX.
- **Use Unreal Reference** reuses a mesh already imported into Unreal.

To reference an imported part:

1. In Unreal's **Content Browser**, right-click the part's **Skeletal Mesh** for Skeletal Assembly, or its **Static Mesh** for Static Assembly.
2. Click **Copy Object Path**.
3. In SpeedAssembly's **Geometry** tab, choose **Use Unreal Reference** for the matching part and paste the path into its **Unreal Path** field.

For detailed plants, use low-poly branches while working in SpeedTree, then replace them with high-poly FBX files or Unreal assets here. The replacement must match the original branch's pivot, orientation, and real-world size. See [Prepare repeated branches and leaves](prepare-speedtree.md#prepare-repeated-branches-and-leaves).

For XML and FBX meshes, click **Preview/Edit** to inspect the branch, optionally reduce its polygon count, and assign materials in the preview window.

### Create a proxy

A proxy is recommended for day-to-day tree preparation when you need collision, distance fields, or lower-cost shadow geometry. It is a separate export, not a requirement for converting the main plant.

1. In **Geometry**, click **Preview Proxy Mesh**.
2. Configure the proxy and inspect its shape.
3. Export it from the preview window.

Follow [Proxy Mesh](proxy-mesh.md) for the settings and export procedure. Proxy generation is unavailable for leaf-only Scattered Rig input.

**Preview Fracturing** opens the optional experimental workflow for exporting static tree pieces for destruction.

<!-- Add Geometry tab, Preview/Edit, and Fracturing guide links when available. -->

## 4. Assign Materials

Before conversion, fill every required material field under **Base Mesh Materials** and **Instanced Part Materials**. SpeedAssembly blocks conversion when assignments are missing to prevent incorrect material binding during import.

1. In Unreal's **Content Browser**, right-click the material or material instance you want to use.
2. Click **Copy Object Path**.

![Copy Object Path highlighted in an Unreal material's context menu](../assets/images/conversion-copy-object-path.png){ style="max-height: 550px; width: auto;" }

3. In SpeedAssembly's **Materials** tab, paste the path into the matching material field.
4. Repeat for all required slots. Check the fields required by the selected **Part Material Mode**, including both **Black Material** and **White Material** for **Vertex Color Split**.

![Materials tab with Unreal Object Paths assigned to base and repeated-part materials](../assets/images/conversion-materials.png)

Use the full Object Path, such as `/Game/MI_Bark.MI_Bark`. Unreal assigns those materials during import. Parts using **Use Unreal Reference** retain the materials on their existing Unreal assets.

### Optional UDIM settings

Choose a UDIM mode and tile **ID** for the relevant material:

- **UDIM Off** leaves its UVs unchanged.
- **Shift UV** moves the primary UVs to the selected UDIM tile.
- **Write UV1 Offset** leaves the primary UVs unchanged and writes tile-offset data into the second UV channel for your Unreal material to use.

See [UDIM workflow](udim.md) for tile selection and the Unreal material graph for tiling bark with UV1 offset data.

## 5. Convert geometry and generate wind data

1. Click the gear beside **Convert to USDA** and choose an export mode.

| Mode | Result |
| --- | --- |
| **Skeletal Assembly** | The full plant with repeated branches and a skeleton for wind animation. |
| **Skeletal Assembly Parts** | A separate skeletal mesh file for each unique repeated part, without the base tree. |
| **Static Assembly** | The full plant as a static Nanite Assembly, with instanced parts but no skeleton or skeletal wind animation. |
| **Static Assembly Parts** | A separate static mesh file for each unique repeated part, without the base tree. |

Use a Parts mode to build a branch library in Unreal first. Then convert full plants using **Use Unreal Reference** to share those imported branches between trees. In Parts modes, **Create Parts Folder** places the exported files in a dedicated folder; turn it off to write them beside the selected Output USDA.

2. Click **Convert to USDA** and wait for conversion to finish.
3. For a skeletal plant using Dynamic Wind, click **Generate Wind JSON** to export its wind settings separately.

![Convert to USDA, export-mode gear, and Generate Wind JSON highlighted](../assets/images/conversion-export.png)

The full-plant modes produce a USDA at the selected output path. Parts modes produce the individual part files. Wind JSON supplies the group assignments and settings needed for Dynamic Wind in Unreal; generating the USDA alone does not connect the wind data.

Next, [import the exported assets and apply Wind JSON in Unreal Engine](unreal-import.md).
