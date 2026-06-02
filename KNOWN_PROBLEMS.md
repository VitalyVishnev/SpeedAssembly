# Known Problems

## UDIM Real-Sample Coverage Pending

- Issue: UDIM authoring is covered by automated tests and the current baseline UE 5.7.x sample, but repeated-part and FBX material-slot UDIM rows have not yet been validated across a broad set of real SpeedTree structures.
- Location: `src/xml_to_usda/udim_resolver.py`, `src/xml_to_usda/material_resolver.py`, `src/xml_to_usda/qt_ui/panels.py`
- Reason for deferral: Real-sample UE import and material inspection requires a separate validation matrix beyond the current automated regression surface.
- Likely next step: Run `write_secondary_uv_offset` and `shift_primary_uv` on base XML materials, repeated-part black/white buckets, and FBX material-slot rows across the same tree/shrub/grass sample set used for Phase 1 breadth validation.

## Proxy Mesh Distance Field And Shadow Validation Pending

- Issue: The generated `_proxy.usda` asset now imports into UE as a Static Mesh, but distance-field generation and low-cost shadow usefulness have not yet been validated against UE 5.7.x scene lighting.
- Location: `src/xml_to_usda/proxy_mesh_service.py`
- Reason for deferral: UE distance-field and shadow inspection is outside the current automated test harness.
- Likely next step: Export sparse and dense tree proxy samples, enable distance-field visualization in UE 5.7.x, and record whether volume and silhouette are sufficient.

## Proxy Mesh Simplification Quality Pending

- Issue: `density_field` now keeps base geometry direct, builds foliage volume from instanced kernels, and extracts a shared topology before QEM, but simplification quality has not yet been compared across sparse trees, dense crowns, grass, and moss samples.
- Location: `src/xml_to_usda/proxy_mesh_service.py`
- Reason for deferral: The preview/export loop is working, but method quality needs real vegetation comparison instead of synthetic unit-test evidence.
- Likely next step: Use the OpenGL proxy preview and UE static mesh import on at least one sparse tree and one dense tree, then decide whether `fast-simplification` remains the release backend or becomes a replaceable baseline.

## Proxy Mesh Zoned Simplification Pending

- Issue: The current `density_field` method runs QEM on the extracted proxy surface as one mesh; it does not yet apply separate `shell`, `interior`, and `outside` importance zones.
- Location: `src/xml_to_usda/proxy_mesh_service.py`
- Reason for deferral: The first implementation pass needed a deterministic preview/export loop and a shippable Windows QEM backend before tuning zoned importance rules against real vegetation.
- Likely next step: Classify density-field cells/faces by silhouette contribution and weak isolated features, then either protect shell triangles before QEM or split simplification passes by zone.

## Proxy Mesh Worker Crash Isolation

- Issue: Large SpeedTree XML fixtures can trigger intermittent native Windows access violations while source geometry is normalized for proxy generation. Proxy preview/export now run in an isolated worker process and suppress native modal crash dialogs, but the underlying parser/normalizer instability still needs root-cause analysis.
- Location: `src/xml_to_usda/conversion_process.py`, `src/xml_to_usda/qt_ui/proxy_preview.py`, `src/xml_to_usda/qt_ui/background_jobs.py`
- Reason for deferral: The immediate operator blocker is preventing the GUI from crashing or freezing during proxy preview/export. Fixing the native access violation requires a separate focused pass through XML reading/normalization memory behavior.
- Likely next step: Add a reproducible stress test around repeated `load_canonical_model` calls for `SkeletyalAssemblyTest_Spruce_Big_low.xml`, then audit `xml_reader.py`/`normalizer.py` for unsafe C-extension or array lifetime interactions.
