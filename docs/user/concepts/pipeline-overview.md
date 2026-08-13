---
title: Pipeline overview
description: See where SpeedAssembly fits between a SpeedTree source and an Unreal vegetation asset.
---

# Pipeline overview

SpeedAssembly acts as a bridge between SpeedTree and the new Nanite vegetation workflow in Unreal Engine. It keeps repeated leaves and branches as real instances, preserves the skeleton for wind animation, then writes a USDA file ready to import into Unreal.

```text
SpeedTree tree
    ↓
Raw XML export
    ↓
SpeedAssembly: configure geometry, materials, and wind
    ↓
USDA and optional companion files
    ↓
Unreal Engine: import and validate the asset
```

!!! note "Unreal setup is required"

    Unreal does not recognize this workflow by itself. Before importing, enable the required plugins and configure the project importer path. The future Unreal prerequisites guide will list the verified setup.

## 1. Prepare and export the tree

Create the tree in SpeedTree as usual, then prepare its skeleton, main trunk and branch mesh, reusable branches and leaves, materials, and UVs for export. Some tree setups need specific preparation; the future SpeedTree preparation guides will cover those requirements and export settings.

Export the tree as a SpeedTree Raw XML file. This is simply the export file you select in **Input XML**.

## 2. Configure the tree in SpeedAssembly

Open SpeedAssembly, select the XML file in **Input XML**, then choose the output path and export mode.

| Export mode | Result |
| --- | --- |
| **Skeletal Assembly** | A complete tree that can use skeleton-driven wind animation. |
| **Static Assembly** | A visually similar tree without a skeleton or wind animation. |
| **Skeletal Assembly Parts** | A separate reusable skeletal asset for every repeated branch or leaf part. |
| **Static Assembly Parts** | A separate reusable static asset for every repeated branch or leaf part. |

The normal tree workflow uses **Skeletal Assembly**. Choose a Parts mode when you need a reusable library of branches or leaves instead of one complete tree.

### Wind

The **Wind** tab controls the base behaviour of bone groups for Dynamic Wind in Unreal. You can revise the wind settings later; use the dedicated Wind workflow when you need to inspect or edit the groups in detail.

### Geometry

The **Geometry** tab controls every reusable branch or leaf part. For each one, choose a source:

- **Use XML Mesh** keeps the geometry exported from SpeedTree.
- **Use FBX File** replaces that part with an external FBX mesh. For example, replace a lightweight SpeedTree branch with a higher-poly branch before import.
- **Use Unreal Reference** reuses an already imported Unreal part asset. This lets multiple trees share the same branch asset instead of importing a new copy for each tree.

### Materials and UDIM

In **Materials**, assign Unreal material object paths to the tree and to its reusable branches and leaves. Copy the object path from the Unreal Content Browser. Required assignments must be complete before conversion can start, so Unreal can resolve the intended material slots during import.

Reusable branches and leaves can use one of these material modes:

- **Single Material** assigns one material to the whole part.
- **Material Slots** maps the material slots used by an FBX replacement to Unreal materials.
- **Vertex Color Split** assigns two materials from the part's vertex colors. Prepare the mesh before export: exact black faces use the leaf material; every other face uses the bark material.

Vertex Color Split is useful when a SpeedTree leaf node needs bark and leaf materials but the Raw XML export provides only one material assignment for that node.

Each applicable material can also use a UDIM policy: keep its original UVs, shift the primary UVs to a UDIM tile, or preserve the primary UVs and write the UDIM offset to a second UV channel. Use this only when the target Unreal material is prepared for the selected policy.

## 3. Convert and import

Select **Convert to USDA** after the configuration is complete. SpeedAssembly writes the main USDA output ready for the configured Unreal USD/Interchange workflow.

Import the file in Unreal using the project setup and import options documented for this pipeline. Then check that the expected tree geometry, repeated branches and leaves, materials, and—when applicable—the skeleton are present. A successful import confirms the file shape, not final wind, lighting, collision, or destruction quality.

## Advanced workflows

Use the following tools after the main tree is configured.

### Wind Preview

**Wind Preview** is a separate viewport for reviewing and editing wind groups. You can use XML groups, create automatic hierarchy-based groups, add manual overrides, and generate Dynamic Wind JSON from the final visible group setup.

It can also load an external FBX or USD skeleton, so you can generate Dynamic Wind JSON for a skeletal plant created outside SpeedTree.

### Proxy Mesh

**Proxy Preview** generates a lower-cost companion Static Mesh with optional trunk collision. It is intended for collision, distance-field, and lower-cost shadow workflows around the main tree—not as a replacement for the Skeletal Assembly.

Import of the Proxy Mesh as a Static Mesh is confirmed. Validate distance fields and shadow quality with the actual asset in the target Unreal scene.

### Fracturing

**Fracture Preview** divides the tree into root-pivoted static pieces and can export optional collision geometry with them. It is an experimental workflow for destruction-oriented asset preparation.

The exported pieces are static geometry; their runtime destruction behaviour still needs validation in the target Unreal project.

### Part Preview

**Part Preview** opens one reusable branch or leaf part in its own viewport. Use it to inspect the part, review its material split or FBX slots, and apply modest simplification before the main conversion.

## See also

- [Quick start](../getting-started/quick-start.md)
- Planned guides: SpeedTree source requirements, Raw XML export, Unreal prerequisites, Unreal import, Dynamic Wind, Proxy Mesh, and Fracturing.
