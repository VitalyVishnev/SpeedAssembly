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

Wind groups are derived from the normalized skeleton, with a controlled fallback from the source object hierarchy.

Rules:

- trunk is always `Simulation Group 0`
- additional groups are created from branching depth and hierarchical branch levels
- if the tree has `1 trunk + 1 branch level`, the result should be `2` groups
- if the tree has `1 trunk + 4 branch levels`, the result should be `5` groups

### Important correction

During UE validation, a failure mode was found where the trunk bent only at the base while the upper trunk behaved like branch groups.

Cause:

- the original fallback logic applied source object logical depth to every skinned joint referenced by an object mesh
- this could incorrectly promote upper trunk joints into higher branch groups

Current fix:

- source object depth hints are now applied only to one anchor joint per object
- the anchor joint is chosen from the object skinning data by dominant joint usage, with deeper joints preferred on ties

This keeps the fallback useful for chain-like SpeedTree exports, but avoids pulling large portions of the trunk out of `Group 0`.

## Current UI contract

The GUI exposes:

- `Refresh Wind Groups`
- `Generate Wind JSON`
- one `Influence` slider per group
- one `Shift Top` slider per group
- `Gust Attenuation`
- `Ground Cover`

Current slider ranges:

- `Influence`: `0.0 .. 1.0`
- `Shift Top`: `0.0 .. 1.0`

Persisted settings from older runs that exceed the current slider range are clamped when reloaded.

## Meaning of the settings

### Influence

The overall wind strength applied to a simulation group.

Practical interpretation:

- lower values make the group stiffer
- higher values make the group bend more

Current default:

- trunk default is `0.2`
- branch groups currently default to `1.0`

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

- only single influence is implemented in the UI and JSON export path
- dual influence is documented but not exposed yet

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
- numeric defaults are based on current local validation and may still require further tuning against more UE reference assets
- dual influence is not yet exposed

## Tests

Wind behavior is currently covered by automated tests for:

- hierarchy-driven group count
- chain-like fallback using source object hierarchy
- JSON payload generation
- GUI slider collection and persistence

Relevant tests:

- [test_pipeline.py](D:/3D%20Personal/VibeCode/XMLtoUSDAconverter/tests/test_pipeline.py)
- [test_app_layers.py](D:/3D%20Personal/VibeCode/XMLtoUSDAconverter/tests/test_app_layers.py)
