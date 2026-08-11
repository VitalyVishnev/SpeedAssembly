# Proxy Mesh

Proxy Mesh generates a simplified companion Static Mesh from the current SpeedTree source. It is intended for collision, distance-field participation, and lower-cost shadow workflows around the main tree asset.

It is not a replacement for the Skeletal Assembly.

## What the workflow produces

The shipping method is **Density Field**:

1. the Base Mesh contributes its source geometry;
2. repeated parts contribute foliage volume kernels;
3. a density volume is extracted into one surface;
4. the surface and Base Mesh budget are simplified with topology-preserving QEM;
5. optional trunk collision is fitted from skeleton-owned source points;
6. the preview result can be written directly to USDA.

## Open Proxy Preview

1. Select a valid **Input XML** and **Output USDA** in the main window.
2. Open **Proxy Preview** from the Geometry workflow.
3. Wait for the initial mesh.
4. Adjust extraction, source-priority, simplification, and collision settings.
5. Inspect the result in the viewport.
6. Choose the Proxy output path and select **Generate Proxy**.

When the visible preview matches the current settings, export reuses that result instead of generating the mesh again.

## Recommended tuning order

1. Set **Density Resolution** high enough to capture the required silhouette.
2. Use **Bounds Inflation** only when the extracted volume is too tight or too broad.
3. Balance trunk and foliage using **Base Mesh Priority**.
4. Remove unwanted disconnected terminal geometry with **Remove Small Branches**.
5. Enable **Fuse Base Mesh Vertices** only for visibly near-coincident Base Mesh seams.
6. Set the final cost with **Final Polycount**.
7. Configure collision after the visible proxy shape is acceptable.

Changing collision visibility or fit uses the retained skeleton-owned collision source. It does not use the simplified viewport mesh as a fitting source.

## Viewport navigation

- Left mouse button: orbit.
- Middle mouse button: pan.
- Mouse wheel: zoom.
- Double-click the mesh: focus the clicked region.
- `F`: frame the complete scene.

## Validation status

Proxy USDA import as a Static Mesh has been confirmed. Box and Capsule simple collision import has also been confirmed in Unreal Engine 5.7.x.

!!! warning "Lighting remains asset-dependent"

    Import confirmation does not prove distance-field quality, shadow quality, or the best settings for sparse trees, dense crowns, grass, and moss. Validate those results in the target Unreal scene.

See the complete [Proxy Mesh parameter reference](../reference/proxy-mesh.md).
