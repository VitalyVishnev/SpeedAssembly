# Quick start

This guide covers the shortest path from a SpeedTree Raw XML source to a USDA file for Unreal Engine.

## Before you begin

You need:

- a SpeedTree Raw XML export;
- `SpeedAssembly.exe` from the project release;
- Unreal Engine 5.7 or 5.8 with the required USD/Interchange workflow available;
- valid Unreal material object paths for the material rows required by your selected source and material mode.

!!! warning "Do not use arbitrary XML"

    SpeedAssembly understands observed SpeedTree Raw XML structures. It does not attempt to convert unrelated XML documents.

## Convert the tree

1. Open SpeedAssembly.
2. Select **Input XML** and choose the SpeedTree Raw XML file.
3. Review the automatically derived **Output USDA** path.
4. Choose the required conversion mode from the menu beside **Convert to USDA**.
5. Review the **Wind**, **Geometry**, and **Materials** tabs.
6. Fill every required Unreal material assignment. Conversion does not start while a required discovered material row is empty.
7. Select **Convert to USDA**.
8. Wait until the Program Status card confirms that the USDA was written.

## Import into Unreal Engine

Import the generated USDA through the project’s USD/Interchange workflow. After import, verify:

- the Base Skeletal Tree is present;
- the skeleton hierarchy is intact;
- repeated parts are present and correctly placed;
- material assignments resolve to the intended Unreal assets;
- the instance count and visible topology are plausible for the source tree.

Import success proves that the file satisfies the tested importer shape. It does not by itself validate lighting, wind quality, collision behavior, or runtime destruction.

## Optional companion outputs

After the main tree is configured, use the dedicated preview windows for:

- Dynamic Wind JSON;
- [Proxy Mesh](../workflows/proxy-mesh.md);
- Fracturing and collision pieces.

These outputs complement the main tree. They do not replace its importer contract.
