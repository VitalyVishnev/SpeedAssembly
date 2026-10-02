# Frequently asked questions

## Can Proxy Mesh replace the skeletal tree?

No. Proxy Mesh is a companion Static Mesh. The Skeletal Assembly remains the primary tree asset and importer-facing contract.

## Why did Final Polycount not produce the exact requested number?

Final Polycount is a simplification target. The extracted surface may contain fewer triangles than requested, or its topology may have a minimum safely reachable count. See [Final Polycount](../reference/proxy-mesh.md#final-polycount).

## Why is collision missing from the Proxy output?

Check the following:

- **Generate Collision** is enabled;
- **Height** is greater than zero;
- **Width** is greater than zero;
- the source contains enough valid skeleton-owned stem geometry to fit the selected primitive.

## Why does increasing Final Polycount not restore small foliage detail?

The detail may have been lost during density extraction. Increase [Density Resolution](../reference/proxy-mesh.md#density-resolution) before increasing the final triangle budget.

## Does successful Proxy import prove good distance fields or shadows?

No. Import has been confirmed, but distance-field and shadow usefulness must still be evaluated per asset in the target Unreal scene.

## Why will the main conversion not start?

Every required discovered Unreal material assignment must be filled for the current material mode. Reused Unreal Part assets are exempt because they retain their own materials.

## Is SpeedAssembly a generic XML converter?

No. It is deliberately built around observed SpeedTree Raw XML structures and the Unreal Engine 5.7–5.8 vegetation importer workflow.
