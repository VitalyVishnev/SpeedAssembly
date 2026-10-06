---
title: XML, USD, USDA, and JSON
description: What these file formats contain, where artists encounter them, and why SpeedAssembly uses them.
---

# XML, USD, USDA, and JSON

A tree travels through this workflow in several files. Each carries a different part of the job.

## XML carries the SpeedTree source

XML means *Extensible Markup Language*. It stores structured data as text, using named tags. Applications use it for settings, documents, and data exchange. The tags get their meaning from the application that writes and reads them.

SpeedTree's **Raw XML** export contains the tree's geometry, skeleton, material information, and repeated-part placements. SpeedAssembly reads that structure to reconstruct the tree and its reusable parts. Keep the original SpeedTree project for authoring; XML is the handoff file.

## USD describes a 3D scene

USD means *Universal Scene Description*. Developed at Pixar, it is a system for describing and assembling 3D scenes. It can represent meshes, materials, skeletons, transforms, and instances, with references to other assets. Artists encounter it in DCC exchange, film pipelines, and scene assembly.

SpeedAssembly uses USD to describe both the tree and how its repeated branches or leaves are placed. That structure supports Unreal's Nanite Assembly import workflow.

## USDA is USD you can read

The **A** means *ASCII*: `.usda` is USD's text format. `.usdc` is its binary format; `.usd` can contain either. USDA follows the same scene model, so choosing text does not mean flattening the tree into one mesh.

SpeedAssembly writes `.usda` so its output is inspectable in a text editor. Geometry, skeleton bindings, instances, and Unreal-specific import data can be checked directly when an import needs investigation.

## JSON carries the wind settings

JSON means *JavaScript Object Notation*. Despite the name, many applications and languages use it. It stores named values and lists as text, commonly for settings and data exchange.

Here, `*_DynamicWind.json` supplies Unreal with bone-to-group assignments and wind response settings. The geometry and skeleton stay in USDA. JSON contains no animation keyframes; Unreal's Dynamic Wind generates the motion at runtime.

For the complete handoff, see [Convert in SpeedAssembly](../workflows/basic-conversion.md). For the wind side, see [How Dynamic Wind works](how-dynamic-wind-works.md).
