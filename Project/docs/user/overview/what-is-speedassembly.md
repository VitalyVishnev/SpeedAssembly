---
title: What is SpeedAssembly?
description: Bring SpeedTree plants into Unreal Engine's Nanite Assembly workflow with instanced branches and skeletons for wind animation.
---

# What is SpeedAssembly?

SpeedAssembly is a bridge between SpeedTree and the new Nanite Assembly workflow in Unreal Engine. Create your plants in SpeedTree, then use SpeedAssembly to prepare them for import into Unreal with instanced branches and leaves and a skeleton for wind animation.

Instancing lets the same branch or leaf mesh appear many times throughout a tree. SpeedAssembly keeps those instances so you can reuse branch and leaf assets across different plants. You can also replace lightweight branches used in SpeedTree with more detailed meshes before importing the tree into Unreal.

Alongside the main tree export, SpeedAssembly provides tools for editing wind simulation groups, generating simplified meshes for distance fields, shadow proxies, and collision, and preparing tree pieces for destruction.

## Supported workflows {#supported-workflows}

| Workflow | What you can create or configure |
| --- | --- |
| **Skeletal Assembly** | A complete tree with instanced branches and leaves and a skeleton for wind animation. |
| **Skeletal Assembly Parts** | Individual skeletal branch and leaf assets for reuse in other trees. |
| **Static Assembly** | A complete tree with instanced branches and leaves, without a skeleton. |
| **Static Assembly Parts** | Individual static branch and leaf assets for reuse in other trees. |
| **Dynamic Wind JSON** | Wind settings to import into Unreal for use with Dynamic Wind. |
| **Wind Preview** | Automatic or manual bone groups and their wind settings. You can also generate wind data for an external FBX or USD skeleton. |
| **Proxy Mesh** | A low-poly mesh based on the tree, for distance-field and shadow-proxy workflows, with optional trunk collision. |
| **Fracturing · Experimental** | Separate static tree pieces with optional automatically generated collision, for building a destruction workflow in Unreal. |

## Where to start

Read the [pipeline overview](../concepts/pipeline-overview.md) for the full path from SpeedTree to Unreal. To begin the Basic workflow, [prepare your Unreal project](../workflows/prepare-unreal.md).

For a simplified tree mesh, see the [Proxy Mesh workflow](../workflows/proxy-mesh.md).

<!-- Add links to the dedicated guides when they exist:
     ../wind/preview-workflow.md
     ../wind/unreal-setup.md
     ../fracturing/overview.md
-->
