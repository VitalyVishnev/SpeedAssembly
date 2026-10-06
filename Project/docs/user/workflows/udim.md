---
title: UDIM workflow
description: Select UDIM tiles for plant materials, shift leaf UVs, or keep bark tiling with offset data in UV1.
---

# UDIM workflow

Set a UDIM mode and tile **ID** for each material assignment in **Materials**. The same controls are available for repeated parts in **Geometry > Preview/Edit**.

## Why use UDIMs?

UDIMs let you combine branch texture atlases, tiling bark textures, and other plant textures into one large virtual texture. Many different plants can then share one material that samples this atlas, instead of requiring a new material instance with different textures for each plant. This reduces the number of different materials used across the Nanite vegetation.

Unreal imports a UDIM image set as a Virtual Texture asset. Prepare the textures and material in Unreal first, with virtual texturing enabled and compatible texture samplers. SpeedAssembly assigns tiles through UV data; it does not pack the atlas or create the material. See [Epic's Streaming Virtual Texturing guide](https://dev.epicgames.com/documentation/unreal-engine/streaming-virtual-texturing-in-unreal-engine?lang=en-US) for texture setup.


## Select a mode and tile

1. In SpeedAssembly, open **Materials** and locate the relevant base-mesh or repeated-part material.
2. Assign its Unreal material Object Path.
3. Choose **Shift UV** or **Write UV1 Offset** in the UDIM dropdown.
4. Set **ID** to the tile containing the texture, for example `1002`.

![UDIM mode dropdowns and tile ID fields highlighted for repeated-part material assignments](../assets/images/udim-material-controls.png)

For a repeated part, you can also open **Geometry > Preview/Edit**, set the same material and UDIM controls, and click **Apply**.

**UDIM Off** leaves the UVs unchanged. The two other modes need different material UV setups.

## Shift UV {#shift-uv}

Use **Shift UV** for UVs contained in the `0–1` square, such as a leaf mesh. This square is UDIM tile `1001`. SpeedAssembly moves the UVs by the offset of the selected tile without changing their shape or scale.

For example, choosing `1002` adds one to U and leaves V unchanged. In Unreal, connect **TexCoord[0]** directly to the UDIM Texture Sample's **UVs** input.

This mode does not make a texture repeat inside one tile. UVs extending beyond that tile can address neighboring tiles. For tiling bark, use **Write UV1 Offset** instead.

## Write UV1 Offset {#write-uv1-offset}

Use **Write UV1 Offset** when the primary UVs need to repeat, such as bark running along a trunk. There is no need to cut the mesh into sections just to fit those UVs inside `0–1`.

SpeedAssembly keeps **UV0** unchanged and writes the selected tile's offset into **UV1**, the second UV channel. The Unreal material wraps UV0 into `0–1`, then adds the tile offset from UV1. The bark texture repeats across the mesh while every repetition samples the same UDIM tile.

!!! note "Reserve UV1 for tile data"

    This mode replaces existing UV1 data. Do not use that channel for another purpose or overwrite it during import.

### Build the material UVs

In Unreal's Material Editor:

1. Connect **TexCoord[0]** to **Frac**.
2. Connect **TexCoord[1]** to **Floor**.
3. Connect both results to **Add**.
4. Connect **Add** to the **UVs** input of the UDIM texture samples.

![Unreal material graph combining Frac of TexCoord 0 and Floor of TexCoord 1 before sampling Albedo and Normal](../assets/images/udim-uv1-material.png)

The equivalent HLSL expression is:

```hlsl
float2 sampleUV = frac(UV0) + floor(UV1);
```

**Frac** repeats the primary UVs within a tile. **Floor** recovers the tile offset stored in UV1. Use the same result for the texture maps that share this UDIM layout.

This graph is specifically for **Write UV1 Offset**. Applying Frac to UV0 from **Shift UV** removes its tile offset. If bark and leaves share a material built with this graph, use **Write UV1 Offset** for both so UV1 selects the correct tile.

## How SpeedAssembly writes the UVs {#uv-formula}

UDIM numbering starts at `1001`, with ten columns per row. The following HLSL-style example matches the converter's offset calculation for a valid tile ID:

```hlsl
int tileIndex = udimId - 1001;
float2 tileOffset = float2(tileIndex % 10, tileIndex / 10);

// Shift UV: write the shifted coordinates to UV0.
float2 shiftedUV0 = UV0 + tileOffset;

// Write UV1 Offset: keep UV0 and write these coordinates to UV1.
float2 encodedUV1 = tileOffset + float2(0.5, 0.5);
```

For tile `1012`, the offset is `(1, 1)` and the encoded UV1 value is `(1.5, 1.5)`. The material's Floor node reads it back as `(1, 1)`. The extra `0.5` stores the value at the tile center, away from its integer boundaries.

## Convert and check

Convert the plant and [import it into Unreal](unreal-import.md). Check that each surface reads the intended tile and that bark repeats without changing to another texture. If the tile is wrong, compare the selected **ID** with the material's UV setup before changing the mesh.

For material assignment and the rest of the export steps, see [Convert in SpeedAssembly](basic-conversion.md#4-assign-materials).
