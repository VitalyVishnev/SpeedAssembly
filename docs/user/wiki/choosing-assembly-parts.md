---
title: Choosing what to instance
description: Choose repeated branches and leaf clusters that save geometry without creating excessive runtime work or limiting wind motion.
---

# Choosing what to instance

Choose the largest repeated group of geometry that can move as one piece without losing the motion you need.

An Assembly Part is a reusable mesh, such as a branch or leaf cluster. Unreal stores its geometry once and places copies throughout the plant. Every placed copy still requires transforms, visibility checks, and processing for animation. Smaller parts can save more duplicated geometry, but require more copies to build the same plant.

## Two different limits

The following limits apply to Nanite Assembly in Unreal Engine 5.7 and 5.8. They concern Assembly transforms, not skeleton bones or the separate Dynamic Wind bone budget.

### Per-asset limit

One built Assembly asset can contain up to **65,535 Assembly transforms**. This counts placements in the final assembly, not distinct meshes in your branch library.

Fitting within this limit only means the asset can be built. It does not establish how many copies of that plant a level can render efficiently.

### Runtime transform budget

`r.Nanite.MaxVisibleAssemblyParts` defaults to **262,144**. It sets the capacity of the Assembly transform buffer used during rendering.

Each processed part uses:

- One transform record without active skinning.
- Three transform records with active skinning.

With all parts actively skinned, the default capacity allows approximately **87,000 parts**. Static and animated parts share the buffer, so the available capacity depends on their combination.

If the transform budget is exceeded, parts that do not fit are omitted from the affected rendering pass. In the camera view, this can make patches of leaves, branches, or grass disappear. It is not just a performance slowdown.

## Example: individual leaves or leaf clusters

Suppose you need to place 10,000 leaves on a tree. You can instance one leaf at a time, or instance a mesh containing five leaves.

Assume a single leaf has 20 triangles and the five-leaf cluster has 100:

| Construction | Reusable mesh | Parts per tree | Parts across 20 trees |
| --- | --- | --- | --- |
| Individual leaves | 20 triangles | 10,000 | 200,000 |
| Five-leaf clusters | 100 triangles | 2,000 | 40,000 |

Both versions contain the same number of leaves and triangles before simplification. The cluster mesh stores five times as much geometry, but requires one fifth as many placements.

If every part across those 20 trees is processed with active skinning, individual leaves require 600,000 transform records. Clusters require 120,000. Visibility and distance determine the actual counts in a rendered frame.

For simple leaves, storing a larger cluster mesh can therefore save substantial runtime work at a small geometry-memory cost. With a detailed branch, the geometry-memory trade-off may be different.

## Which geometry benefits from instancing?

A pine branch with secondary twigs and thousands of triangles of needles can save considerable memory when reused dozens or hundreds of times. Branch tips, larger branch sections, leaf clusters, and groups of needles are useful candidates when the same shape repeats.

A simple grass blade, needle, or petal may contain only a few triangles. Instancing each one saves little geometry per copy, while a field or forest can require hundreds of thousands of copies. Compare grouping them into larger parts with keeping them in the main mesh.

Unique trunk sections, connecting geometry, rarely repeated shapes, and small decorative details often belong in the main mesh. Give them separate Assembly Parts only when reuse or independent movement justifies the additional transforms.

### Practical starting points

Use these approximate polygon counts to plan a part library:

- **Below 1,000 polygons:** usually combine the mesh with neighboring details or keep it in the main mesh rather than making it a separate repeated part.
- **Above about 1,500 polygons, repeated more than 50 times:** a good candidate for an Assembly Part.
- **A 5,000-polygon branch repeated 500 times:** a strong use case, with enough repeated geometry to make reuse worthwhile.

These are practical authoring guidelines, not engine thresholds or benchmark results. Use them to plan the first version, then check motion, transform demand, and performance in the intended scene.

## Choose boundaries by movement

In Unreal Engine 5.7 and 5.8, Skeletal Nanite Assembly parts move rigidly with their attachment bones and do not bend internally.

If several leaves can share the same movement, combine them into a cluster. Keep them separate when their individual motion is visible from the intended camera distance.

A larger cluster reduces part count but makes more foliage move as one rigid piece. Split it if two branches need different movement, the foliage looks stiff, or the silhouette loses its characteristic motion.

The target is the fewest parts that preserve the plant's appearance and movement.

### Example: leaves or whole branch tips

Consider a tree whose foliage consists of 500 similar branch tips, each carrying ten leaves. Before choosing how to instance it, compare two constructions:

- Keep the twig geometry in the main mesh and instance the leaves individually. This requires 5,000 leaf parts.
- Include each twig and its ten leaves in one reusable branch-tip mesh. This requires 500 branch-tip parts.

Both constructions retain the twigs and 5,000 leaves. The second uses a larger reusable mesh and ten times fewer parts. It also makes each branch tip move as one piece, so use it only if that motion suits the plant.

## Building a part library

For trees, start with a small set of reusable shapes:

- Small clusters of three to five leaves.
- Larger clusters of five to ten leaves.
- Branch tips with their leaves.
- Larger branch sections.
- Individual leaves for placements that need a specific shape or independent motion.

These cluster sizes are examples, not requirements. Vary the meshes where needed for branch tips, dead branches, or other distinct areas of the crown.

For grass, consider individual large blades where they define the silhouette, small clumps for visible variation, and larger clumps for dense filler. Grouping blades can reduce part count without reducing the number of visible blades.

## Recognizing parts that are too small

Try larger clusters if:

- Individual parts contain very little geometry.
- Many neighboring parts move together.
- Combining them produces no noticeable visual change.
- A few nearby plants already bring the Assembly transform counter close to its limit.
- Rendering the intended plant density requires a substantial increase to `r.Nanite.MaxVisibleAssemblyParts`.

A high part count in one tree is not enough to judge the result. Count how many such trees the camera can see together. For example, 20,000 parts in one tree become 400,000 placements across 20 trees, before accounting for visibility and animation.

## Test in the intended scene

Test the plant at its intended placement density and camera distances, not only in an isolated asset viewport.

At a distance, Nanite can simplify geometry and use coarser representations. Visibility checks and animation distance also reduce some work. Nearby views still need the detailed foliage structure, so distant simplification does not remove the cost of fine-grained parts everywhere.

### Check the transform demand

1. In Unreal Editor, open the console and enter `NaniteStats`.
2. Find **Assembly Parts > Visible** in the statistics overlay.
3. Explore the level with skeletal wind active.
4. Compare the highest observed value with `r.Nanite.MaxVisibleAssemblyParts`.

Without arguments, `NaniteStats` shows the main camera rasterization view, not shadow passes.

Despite its label, **Visible** counts requested transform records, not individual parts. An actively skinned part already contributes three records to this number. Do not multiply the displayed value by three again. Requests beyond the buffer capacity also increase the counter.

Check dense forest areas, open views with many plants, elevated viewpoints, and the maximum intended draw distance. Use the gameplay camera and include several vegetation types together. Profile shadow-heavy views too; the transform counter does not measure the complete rendering cost.

### Leave a reserve

Aim to keep the worst measured transform demand at about **70 to 75% of the configured capacity**. At the default capacity, this is approximately 184,000 to 197,000 records.

This is a planning recommendation, not an engine requirement or a performance guarantee. Leave room for denser placement, new plant types, a wider camera field of view, and changes to draw or animation distance.

## Before increasing the budget

Increasing `r.Nanite.MaxVisibleAssemblyParts` enlarges the GPU buffer and permits more parts to be processed. Those additional parts can increase visibility-checking, skinning, rasterization, and shadow work. Increasing capacity does not reduce the cost of the existing parts.

First test whether combining small parts reduces transform demand without changing the appearance or motion. Raise capacity when the scene still needs it, then measure GPU memory and rendering performance.

## Making the choice

For each candidate mesh, ask:

1. How much duplicated geometry would instancing save?
2. How many copies will be visible together across the level?
3. Which elements need to move independently?

A branch or foliage cluster is often a better unit than an individual leaf or needle. Choose its size by comparing the geometry saved with the number of runtime parts it creates, then check the movement from the intended camera.

See [Prepare SpeedTree](../workflows/prepare-speedtree.md) for mesh orientation, scale, and Leaf settings.
