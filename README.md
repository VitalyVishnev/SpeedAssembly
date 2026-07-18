# [SpeedAssembly](https://github.com/VitalyVishnev/SpeedAssembly)

> A standalone tool for bringing **SpeedTree Raw XML** trees into the new
> **Unreal Engine 5.7–5.8** vegetation pipeline.

## [Download SpeedAssembly](https://github.com/VitalyVishnev/SpeedAssembly/releases)



![SpeedAssembly main workspace, Dynamic Wind, Proxy Mesh, and Fracture Preview](assets/readme/speedassembly-workflows.png)

SpeedAssembly converts SpeedTree Raw XML into Unreal-ready USDA and keeps skeletal structure, repeated twigs
and leaves, materials, wind data, and optional companion assets.

## Built for the new Unreal vegetation workflow

- **Dynamic Wind.** Generate and tune wind JSON for Dynamic Wind Plugin,
  including the full set of wind-group settings needed by the new pipeline.
- **Unreal Engine 5.7 and 5.8.** Export a Skeletal Mesh-ready USDA from a
  SpeedTree Raw XML source.
- **Instanced twigs and leaves.** Preserve repeated parts as instances inside nanite assembly
- **Materials.** Map SpeedTree materials to Unreal materials and control
  repeated-part material handling.
- **Proxy Mesh.** Generate a lightweight proxy mesh for collision, distance
  fields, and lower-cost shadow workflows.
- **Tree fracturing.** Preview and export destructible tree pieces with
  optional collision shapes.
- **More export choices.** Export static mesh assembly or individual parts

## Quick start

1. [Download the latest SpeedAssembly build](https://github.com/VitalyVishnev/SpeedAssembly/releases).
2. Open SpeedAssembly and select your **SpeedTree Raw XML** file.
3. Review the tree, materials, part sources, and wind settings.
4. Generate the USDA.
5. Import the result into Unreal Engine 5.7 or 5.8 through the USD/Interchange
   workflow.
6. Use the generated wind JSON with Dynamic Wind Plugin, then tune the final
   look in Unreal.

## What SpeedAssembly is for

SpeedAssembly is for environment artists and technical artists who already use
SpeedTree and want a practical route to Unreal's current vegetation workflow.
It is not a generic XML converter: it is built around SpeedTree tree data and
Unreal import behavior.

## Included workflows

| Workflow | Use it when you need |
| --- | --- |
| Skeletal Mesh export | A tree ready for the Unreal vegetation pipeline |
| Dynamic Wind JSON | Wind groups and animation controls for Dynamic Wind Plugin |
| Instanced parts | Repeated twigs and leaves without duplicated mesh payloads |
| Proxy Mesh | A simplified companion mesh for collision, distance fields, and lower-cost shadows |
| Fracturing | Breakable tree pieces and optional collision output |
| Part export / replacement | Individual parts or a custom downstream asset workflow |


## Project status

The primary workflow has been validated in Unreal Engine 5.7 and 5.8. Real
asset coverage continues to grow across different tree and vegetation forms.

---

*A short visual walkthrough will be added here: SpeedTree → SpeedAssembly →
Unreal Engine, ending with the imported tree moving in the viewport.*
