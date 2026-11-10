---
title: Export PVE Growth Data
description: Export a SpeedTree skeleton and branch radii as Growth Data JSON for Unreal Engine 5.8.
---

# Export PVE Growth Data

This mode creates a JSON file so you can keep working on your tree in the **Procedural Vegetation Editor** in Unreal Engine 5.8. The file preserves the tree’s shape, branch lengths, and the thickness of the trunk and branches.

## Export from SpeedAssembly

1. Select your SpeedTree Raw XML in **Input XML**.
2. Open the gear beside **Convert to USDA** and choose **PVE Growth Data (UE 5.8)**.
3. Click **Export Growth Data**. By default, **Output JSON** uses the XML's folder and base name.

The export needs no material, geometry, or wind settings. SpeedAssembly uses Spine curves when available and valid. If it uses Bones instead, the yellow status message explains why.

## Load the JSON in Unreal

Enable **Procedural Vegetation Editor**. In the Content Browser, choose **Add → Data → Data Asset** and create a **Procedural Vegetation Growth Data Asset**. Open it, set **Internal → Json Directory Path** to the folder containing the JSON, click **UpdateDataAsset**, and save. The button loads all JSON files in that folder as variations.

In a PVE graph, assign the asset to **Growth Data Loader**. Connect the variation output to **Mesh Builder** and assign a material under **Generation Materials** to preview the tree.
