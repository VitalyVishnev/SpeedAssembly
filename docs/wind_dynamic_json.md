# Dynamic Wind JSON

## Role

This document records the current Dynamic Wind pipeline, the verified findings from `vault`, and the practical authoring rules discovered during UE validation.

This document is supplemental to the core skeletal assembly contract docs. It is focused only on wind.

## Current project behavior

The converter currently exports wind tuning to a separate Unreal Dynamic Wind JSON file.

Current scope:

- wind data is generated from the normalized skeleton
- wind data is written to `*_DynamicWind.json`
- the JSON is intended for Unreal `WindData` import
- wind tuning is not currently authored into USDA

This separation is intentional because the skeletal assembly import path was stabilized first, and wind tuning must not regress materials or skeletal assembly structure.

## Entry points

Wind generation is currently exposed through:

- CLI: `generate-wind-json`
- GUI: `Generate Wind JSON`

Relevant implementation files:

- [dynamic_wind.py](D:/3D%20Personal/VibeCode/XMLtoUSDAconverter/src/xml_to_usda/dynamic_wind.py)
- [pipeline.py](D:/3D%20Personal/VibeCode/XMLtoUSDAconverter/src/xml_to_usda/pipeline.py)
- [gui.py](D:/3D%20Personal/VibeCode/XMLtoUSDAconverter/src/xml_to_usda/gui.py)
- [models.py](D:/3D%20Personal/VibeCode/XMLtoUSDAconverter/src/xml_to_usda/models.py)

## Output location

GUI behavior:

- if `Output USDA` is filled, wind JSON is written next to it as `<stem>_DynamicWind.json`
- if `Output USDA` is empty, wind JSON is written next to the XML with the same naming pattern

Changing wind settings requires regenerating and reimporting the wind JSON only. It does not require reimporting the tree USDA.

## Verified findings from `vault`

Primary references used:

- [Tree_Norway_Maple_01_A_DynamicWind.json](D:/3D%20Personal/VibeCode/XMLtoUSDAconverter/vault/Quixel%20trees%20examples/Tree_Norway_Maple_01_A_DynamicWind.json)
- [Tree_Aleppo_Pine_01_A_DynamicWind.json](D:/3D%20Personal/VibeCode/XMLtoUSDAconverter/vault/Quixel%20trees%20examples/Tree_Aleppo_Pine_01_A_DynamicWind.json)
- [export_dynamic_wind_json.py](D:/3D%20Personal/VibeCode/XMLtoUSDAconverter/vault/ue_plugins/DynamicWindPluginResources/PythonExamples/export_dynamic_wind_json.py)
- [generatedSchema.usda](D:/3D%20Personal/VibeCode/XMLtoUSDAconverter/vault/ue_plugins/DynamicWindPluginResources/UsdResources/Plugins/unrealDynamicWind/resources/generatedSchema.usda)

Verified observations:

- Quixel `*_DynamicWind.json` examples mostly store `Joints` plus top-level flags, while `SimulationGroups` is often empty.
- The Unreal plugin exporter reconstructs `SimulationGroups` from USDA `DynamicWindSkeletonAPI` attrs when those attrs are present.
- If USDA does not provide numeric group attrs, the exporter falls back to Unreal defaults:
  - `Influence = 1.0`
  - `ShiftTop = 0.0`
- `GustAttenuation` affects trunk simulation groups only.
- `trunkSimulationGroups` is the flag that marks which simulation groups are trunk groups.

Important implication:

- comparing only against Quixel JSON is not enough to understand numeric wind tuning
- JSON structure alone does not fully describe the effective wind behavior unless the source USDA attrs are also known

## Current group-building logic

Wind groups are derived from explicit `Bones/Bone/@Generator` labels.

Rules:

- `Group_<n>` is the authored wind level contract
- variants such as `Group_0 2` normalize to the same level as `Group_0`
- all joints that normalize to the same level share the same wind group
- wind groups are ordered by sorted unique generator levels, not by object hierarchy shape
- `Group 0` remains the trunk group unless `Ground Cover` is enabled
- `Ground Cover` stays a separate UE wind flag and does not change the group count
- when `Ground Cover` is enabled, no generated group is marked as trunk
- if a joint is missing `Generator` or the label cannot be normalized to a numeric level, wind generation fails loudly instead of guessing

## Current UI contract

The GUI exposes:

- `Refresh Wind Groups`
- `Generate Wind JSON`
- a `Dual Influence` checkbox per group, enabled by default
- `Influence` for single mode
- `Min Influence`, `Max Influence`, and `Shift Top` for dual mode
- `Gust Attenuation`
- `Ground Cover`

Current slider ranges:

- `Influence`: `0.0 .. 1.0`
- `Shift Top`: `0.0 .. 1.0`

Persisted settings from older runs that exceed the current slider range are clamped when reloaded.

## Meaning of the settings

### Influence

The overall wind strength applied to a simulation group when `Dual Influence` is disabled.

Practical interpretation:

- lower values make the group stiffer
- higher values make the group bend more

Current default:

- trunk default is `0.2`
- branch groups currently default to `1.0`

### Dual Influence

Controls whether the group is authored as a dual-influence group.

Practical interpretation:

- enabled by default in the GUI
- when enabled, the group exports `bUseDualInfluence = true`
- when enabled, `Min Influence`, `Max Influence`, and `Shift Top` are used
- when disabled, only `Influence` is exported and dual-specific values are ignored

### Shift Top

A per-group attenuation parameter used by Unreal to change how influence is distributed along the group.

Practical interpretation:

- `0.0` gives more even behavior through the group
- higher values change how motion is attenuated toward the top/end of the chain

### Gust Attenuation

Controls gust attenuation for trunk groups only.

Practical interpretation:

- `0.0` means gusts are not attenuated
- higher values reduce trunk reaction to gusts

### Ground Cover

Marks the wind data as ground cover.

Typical use:

- `false` for trees
- potentially `true` for grass or very low shrubs

Contract:

- when `Ground Cover` is enabled, the converter clears `bIsTrunkGroup` on every generated simulation group
- this keeps Unreal from treating any of the generated layers as a trunk-controlled wind band
- `Ground Cover` does not change group count and does not reassign generator levels

## Dual Influence

Unreal Dynamic Wind supports two group modes:

- single influence
- dual influence

Single influence:

- one `Influence` value per group

Dual influence:

- one `MinInfluence` and one `MaxInfluence` per group
- Unreal interpolates inside the group instead of using a single constant value

Current project status:

- dual influence is exposed in the GUI and enabled by default
- single influence remains available through the per-group checkbox

## Practical UE workflow

Current recommended loop:

1. generate or refresh USDA as needed
2. click `Refresh Wind Groups`
3. adjust per-group sliders
4. click `Generate Wind JSON`
5. reimport the generated wind JSON in Unreal
6. compare behavior against a known-good reference tree under the same wind controller settings

## Known limitations

- wind tuning is currently JSON-only in project output
- USDA-side Dynamic Wind authoring is not yet used by the converter
- wind authoring currently requires explicit `Group_<n>` generator labels; legacy XML without usable generator levels is rejected by the wind path
- dual influence is exposed in the GUI, but the JSON still remains separate from USDA authoring

## Tests

Wind behavior is currently covered by automated tests for:

- explicit generator-level grouping
- strict failure on missing or malformed `Generator` labels
- JSON payload generation
- GUI slider collection and persistence

Relevant tests:

- [test_pipeline.py](D:/3D%20Personal/VibeCode/XMLtoUSDAconverter/tests/test_pipeline.py)
- [test_app_layers.py](D:/3D%20Personal/VibeCode/XMLtoUSDAconverter/tests/test_app_layers.py)
