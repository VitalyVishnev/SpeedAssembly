# Architecture

The codebase is organized around one deterministic conversion system with different execution strategies around the edges.

For current contracts and problem tracking, see:

- [Decisions](decisions.md)
- [Known Bugs](known-bugs.md)
- [Experiments](experiments.md)
- [Glossary](glossary.md)

Main systems:

- `src/xml_to_usda/normalizer.py` - turns observed SpeedTree XML into canonical source facts.
- `src/xml_to_usda/material_resolver.py` - resolves source materials and explicit material policy.
- `src/xml_to_usda/assembly_resolution.py` - combines source facts with operator intent into an authored model.
- `src/xml_to_usda/prototype_resolution.py` - resolves prototype payload choice and replacement.
- `src/xml_to_usda/usda_authoring.py` - authors the final USDA structure.
- `src/xml_to_usda/usda_writer.py` - writes USDA through the shared authoring contract.
- `src/xml_to_usda/conversion_service.py` and `src/xml_to_usda/conversion_orchestrator.py` - normalize caller intent and run conversions.
- `src/xml_to_usda/qt_ui/` - supported PySide6 shell and preview adapters.
- `src/xml_to_usda/fbx_adapter.py` and `src/xml_to_usda/fbx_import_supervisor.py` - Autodesk FBX integration and helper process control.
- `src/xml_to_usda/cache_maintenance.py` - bounded runtime cache maintenance for job leftovers, FBX payloads, source-model caches, Proxy Source Projection caches, Fracture Preview source-facts caches, and stale cache temp files.
- `src/xml_to_usda/proxy_mesh_service.py`, `src/xml_to_usda/fracture_service.py`, and related workers - companion workflows.
- `src/xml_to_usda/proxy_source_projection.py` - typed Proxy Source Projection loading/cache for Proxy Mesh jobs that need only base geometry, repeated-part transforms, and source prototype geometry.
- `src/xml_to_usda/mesh_pruning.py` - shared deterministic percentage-based face pruning for preview/proxy workflows that need to drop the smallest disconnected base-mesh islands before their own simplification pass.

Important data flow:

1. XML is parsed and normalized into canonical source facts.
2. Operator intent is resolved into an authored assembly model.
3. Validation checks source, resolution, and authoring invariants in order.
4. USDA authoring emits the importer-facing scene shape.
5. Runtime wrappers handle worker isolation, cleanup, packaging, and diagnostics.

Important folders:

- `src/xml_to_usda/` - production code.
- `tests/` - regression coverage and contract checks.
- `samples/` - controlled XML fixtures and example outputs.
- `vault/` - reference USDA, importer, schema, and research material.
- `docs/raw/` - preserved historical documentation.
- `docs/wiki/` - maintained project memory.

External dependencies:

- UE 5.7.x import behavior is the final contract check.
- Autodesk FBX Python SDK 2020.3.4 is the real FBX import backend in `.venv310`.
- PySide6 is the supported desktop shell.
- PyInstaller builds the packaged executable.

Current technical assumptions:

- the same input plus the same config must produce the same logical USDA output
- raw XML traversal must not write USDA directly
- static and skeletal export modes share normalized source facts but not the same importer contract
- runtime strategy may change, but conversion semantics must not
- interactive preview/setup paths should minimize avoidable pauses and use narrow measured payloads before broad model reconstruction
