# Proxy Mesh parameter reference

Proxy Preview exposes one production method: **Density Field**. The former method selector is intentionally hidden; other internal methods are diagnostic baselines, not operator choices.

## Simplification

### Final Polycount {#final-polycount}

Target triangle budget for the completed Proxy Mesh.

| Property | Value |
| --- | --- |
| Default | `5,000` |
| UI range | `6–100,000` |
| Lower values | Cheaper, rougher silhouette |
| Higher values | More source shape retained |

This is a target, not a guaranteed exact result. The simplifier may return the minimum topology it can safely reach, or the complete extracted surface when the requested value is above the source triangle count.

## Extraction

### Bounds Inflation {#bounds-inflation}

Expands or contracts the density volume around the source tree.

| Property | Value |
| --- | --- |
| Default | `1.0` |
| UI range | `0.1–5.0` |
| Lower values | Tighter volume |
| Higher values | More margin around the source |

Change this when the proxy shell clips the outside of the tree or leaves excessive empty margin. It changes the extraction volume and therefore requires proxy regeneration.

### Density Resolution {#density-resolution}

Longest-axis voxel resolution used to extract the density surface.

| Property | Value |
| --- | --- |
| Default | `64` |
| UI range | `2–512` |
| Lower values | Faster, softer, less detailed |
| Higher values | Finer structure, greater memory and QEM cost |

Raise resolution to improve the source silhouette before raising Final Polycount. A high triangle budget cannot recover detail that was never captured by the density grid.

Resolution `512` is intentionally bounded. It can create millions of source triangles before simplification, so the final QEM stage may dominate generation time.

## Source Priority

### Base Mesh Priority {#base-mesh-priority}

Reserves a fraction of the target budget for unique Base Mesh geometry when foliage volume is present.

| Property | Value |
| --- | --- |
| Default | `0.33` |
| UI range | `0.0–1.0` |
| Lower values | Favors foliage volume |
| Higher values | Preserves more trunk and branch geometry |

Use this to correct a proxy that preserves the crown but loses too much trunk structure, or the reverse.

### Fuse Base Mesh Vertices {#fuse-base-mesh-vertices}

Welds Base Mesh vertices that are within `1 mm` of each other.

| Property | Value |
| --- | --- |
| Default | Off |
| Threshold | Fixed at `0.001 m` |

Disconnected-component pruning runs first; welding then removes near-coincident seams before QEM simplification. This is a narrow seam repair, not a Boolean union or general remeshing operation. Leave it off unless the source trunk is visibly split into near-coincident generator sections.

### Remove Small Branches {#remove-small-branches}

Removes the smallest disconnected Base Mesh components before simplification.

| Property | Value |
| --- | --- |
| Default | `0.25` |
| UI range | `0.0–1.0` |
| `0.0` | Keep every component |
| Higher values | Remove a larger fraction of the smallest components |

Components are ranked deterministically by area and spatial extent. At least one component is retained. This control does not remove connected twigs from a continuous trunk mesh.

## Collision

### Generate Collision {#generate-collision}

Controls whether fitted trunk collision is written beside the visible Proxy Mesh.

| Property | Value |
| --- | --- |
| Default | On |
| Off | Export visible Proxy Mesh only |

Toggling this option reuses retained collision guides and does not regenerate the visible Proxy Mesh.

### Type {#collision-type}

Selects the authored simple-collision primitive.

| Option | Authored prefix | Shape |
| --- | --- | --- |
| Box | `UBX_` | Oriented box |
| Capsule | `UCP_` | Capsule fitted along the trunk axis |

The default is **Box**. Collision transforms are baked into mesh points for the validated Unreal import path.

### One Primitive per Stem {#one-primitive-per-stem}

| Property | Value |
| --- | --- |
| Default | Off |
| Off | One combined primitive around the selected stems |
| On | One independently fitted primitive per stem |

Enable this for multi-stem vegetation when one combined primitive would fill the empty space between trunks.

### Height {#collision-height}

Fraction of the selected main-stem axes covered upward from the root.

| Property | Value |
| --- | --- |
| Default | `0.5` |
| UI range | `0.0–1.0` |
| `0.0` | Omit collision |

Height is measured from skeleton-derived stem axes, not from the rendered Proxy Mesh bounds.

### Width {#collision-width}

Multiplier applied to the automatically fitted trunk width.

| Property | Value |
| --- | --- |
| Default | `1.0` |
| UI range | `0.0–10.0` |
| `0.0` | Omit collision |

Use values above or below `1.0` only after checking the guide against the actual trunk. Width does not include unrelated crown geometry.

## Generate Proxy

### Output Path {#output-path}

Exact USDA destination for the Proxy Mesh. By default it is derived beside the main output as `<OutputStem>_proxy.usda`. A manually entered path is not given a second suffix.

### Generate Proxy {#generate-proxy}

Writes the current Proxy Mesh and collision configuration. A matching completed preview is written directly; otherwise the isolated Proxy worker generates the requested result first.
