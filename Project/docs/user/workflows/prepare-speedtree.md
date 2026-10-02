---
title: Prepare SpeedTree
description: Prepare your plant, repeated branches, skeleton, and export settings for SpeedAssembly.
---

# Prepare SpeedTree

This workflow was tested with SpeedTree Modeler 10.0.0. Prepare your plant in **meters**, use **Leaf** generators for repeated branches and leaves, and add **bones** to the geometry you want to animate.

## Work in meters

1. In SpeedTree, open **Tools > Scene Unit Conversion**.
2. If the scene is not already in meters, set **Convert from** to its current unit and **To** to **Meters**.
3. Click **OK** to convert the scene.

![Scene Unit Conversion with Meters selected as the destination unit](../assets/images/speedtree-scene-unit-conversion.png)

To use meters for future work, open **Edit > Preferences > Tree Window** and set **Scene unit** to **Meter**. This preference does not replace converting an existing scene.

![Tree Window preferences with Scene unit set to Meter](../assets/images/speedtree-meter-preferences.png)

## Prepare repeated branches and leaves

Use **Leaf** generators for the branches or leaf clusters you want Unreal to repeat throughout the plant. In this workflow, Frond and other generators contribute to the main geometry, not to repeated parts.

Create each branch mesh separately in Blender, Maya, Houdini, or another SpeedTree scene, then import it into SpeedTree. You can also use cutout geometry, but fully modeled branches and leaves are recommended.

Before placing the mesh, check its preparation:

- Place its pivot at the attachment point.
- Orient the branch so it grows along **+Y**.
- Use its intended real-world size and set the imported mesh **Scale > Value** to **1**.

![Imported branch mesh with Growth set to +Y and Scale Value set to 1](../assets/images/speedtree-branch-mesh.png)

1. Select the **Leaf** generator.
2. In the **Material** tab, assign the imported **Mesh**.
3. In the **Skin** tab, enable **Use actual size**.

![Leaf Skin settings with Use actual size enabled](../assets/images/speedtree-leaf-actual-size.png)

Avoid importing an oversized branch and compensating with a tiny Leaf size. Prepare reusable branches at the correct size first, then use instance scale for variation.

For faster work in SpeedTree, prepare low-poly and high-poly versions of each branch. Their pivot, orientation, and size must match. Use the low-poly version while building the plant, then replace it in SpeedAssembly with the high-poly FBX or an asset already imported into Unreal.

## Keep variation compatible with instancing

Repeated branches move with the bones they attach to, but do not bend internally. Leaf **Flip**, **Curl**, **Twist**, and other per-leaf mesh deformations do not carry over through this workflow. Each placement uses the same branch geometry.

Vary orientation and scale instead. Use different branch meshes for branch tips, dead branches, or other areas that need a distinct shape.

Keep the plant structure simple: trunk, branches, and repeated foliage. Avoid making every needle a separate repeated part. Choose branch clusters that are neither tiny fragments nor entire crowns.

For the reasoning and scene budgets behind this choice, see [Choosing what to instance](../wiki/choosing-assembly-parts.md).

## Add bones for wind animation

Add bones to the trunk and every branch level you want to animate, including any photogrammetry-based trunk section that should move.

1. Select the generator that creates the trunk or branches.
2. Open the **Physics** tab.
3. Choose **Absolute** or **Relative** for **Bone style**.
4. Adjust **Bones** to give the branch enough segments for its intended movement.

![Physics settings with Bone style and Bones highlighted](../assets/images/speedtree-physics-bones.png)

Add bones to each branch level between the trunk and the smallest branches you want to animate. For example, if the trunk and small branches have bones, the large branches connecting them should have bones too.

![Conifer tree in Unreal Engine with visible bones following the trunk and main branches](../assets/images/cdpr-conifer-skeleton.png){ style="max-height: 500px; width: auto;" }

[Screenshot from a CD PROJEKT RED presentation](https://www.youtube.com/watch?v=EdNkm0ezP0o).

Use the fewest bones that give you the motion you need. These are recommended budgets, not engine limits:

| Plant | Recommended bone budget |
| --- | --- |
| Large tree | Up to about 1,000 |
| Medium tree | About 400 to 600 |
| Understory plant | 50 - 300 |
| Grass | 1 - 30    |

For trees, avoid segments shorter than about 50 cm unless they visibly improve the animation. Do not use one long bone for the entire trunk, but do not subdivide branches without a reason either.

If the skeleton is too detailed, reduce bones on small branches first. There are often many more small branches than large ones, so their bone count adds up quickly.

## Name wind groups

Wind groups let you give the trunk, large branches, small branches, and dead branches different motion settings.

In the generator graph, rename the generators that produce bones using `Group_0`, `Group_1`, `Group_2`, and so on. Start at `Group_0` and keep the numbers consecutive. Give generators the same name when they should share wind settings.

![Generator graph with a Group_0 trunk and branches assigned to Group_1 and Group_2](../assets/images/speedtree-wind-groups.png)

For example, use `Group_0` for the trunk, `Group_1` for large branches, and `Group_2` for smaller branches. Most plants do not need more than four groups. Split groups when you need different motion, rather than simply because you have another generator.

SpeedAssembly reads these group assignments from the export. Naming them here is the recommended approach; you can also edit or generate groups in SpeedAssembly later.

## Export for SpeedAssembly

In the **Export Mesh** window, match the settings in this screenshot exactly. Save them as a preset so you can reuse them for future exports.

![SpeedTree Export Mesh settings for the SpeedAssembly workflow](../assets/images/speedtree-xml-export.png)

The exported XML is the file you select in SpeedAssembly's **Input XML** field.

<!-- Add the Convert in SpeedAssembly link when that article exists. -->
