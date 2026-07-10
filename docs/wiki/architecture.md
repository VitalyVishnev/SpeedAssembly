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
- `src/xml_to_usda/wind_preview_service.py`, `src/xml_to_usda/wind_viewport_scene.py`, `src/xml_to_usda/wind_group_stack.py`, and `src/xml_to_usda/wind_external_skeleton.py` - Wind Preview source service, Qt-free viewport scene adapter, manual override stack, and skeleton-only external FBX/USD loading.
- `src/xml_to_usda/proxy_source_projection.py` - typed Proxy Source Projection loading/cache for Proxy Mesh jobs that need only base geometry, repeated-part transforms, and source prototype geometry.
- `src/xml_to_usda/mesh_pruning.py` - shared deterministic percentage-based face pruning for preview/proxy workflows that need to drop the smallest disconnected base-mesh islands before their own simplification pass.

Important data flow:

1. XML is parsed and normalized into canonical source facts.
2. Operator intent is resolved into an authored assembly model.
3. Validation checks source, resolution, and authoring invariants in order.
4. USDA authoring emits the importer-facing scene shape.

Interactive preview flows may stop earlier when they inspect source facts rather
than authored output. Wind Preview V1 loads canonical XML source facts, derives
Dynamic Wind groups, and adapts those facts to viewport batches for inspection.
Wind Preview keeps the same shared viewport and worker boundary while using a
deterministic wind-group stack: XML Generator Groups or Auto Hierarchy provide a
base, manual override layers sit above it, and the flattened result writes the
existing Dynamic Wind JSON schema. Auto Hierarchy derives groups from skeleton
topology and SpeedTree/file joint ordering, not from XML wind generator labels.
Optional per-layer `Continue line` flags let endpoint-continuous child chains
stay in the same group when explicitly enabled. External Skeleton loading reads
FBX or USD/UsdSkel payloads as skeleton-only previews. Source loading, USD
Skeleton prim enumeration, and scene build run in a file-backed worker process
so XML/external skeleton faults do not crash the Qt shell. The GUI consumes the
worker-built initial scene directly; only actual grouping edits rebuild it. The Wind Preview right panel uses
one global settings scroll; the Layers block is the only nested scroll and can
be resized vertically with a local handle even when the global panel scrollbar
is visible. External Skeleton USD loading uses OpenUSD/`pxr` from `usd-core`
for normal USD support. Text `.usda` and ASCII `.usd` files can still be read
through the deterministic text fallback, but multiple Skeleton prims require
an explicit operator choice instead of any largest-skeleton heuristic.
The SpeedTree XML worker path does not import the External Skeleton backend.
Release packaging includes only the OpenUSD modules, plugin metadata, and
release DLLs required by `Usd.Stage`/`UsdSkel`; debug and unrelated pxr
binaries stay outside the GUI package.

Preview dialogs must share the same viewport system. Mode-specific dialogs
may own controls, source loading, and Qt-free scene adapters, but rendering,
upload lifecycle, camera behavior, bone overlay, picking, and static-scene
precompute belong behind the public `MatcapViewport` interface. If a viewport
stability or rendering fix would help more than one preview, put it in the
shared viewport module rather than in a Wind/Fracture/Proxy-only path.
Visual-only selection changes should update overlay/visibility state through
the shared viewport instead of rebuilding and re-uploading static mesh buffers.
Viewport-specific shortcuts should be shown as small contextual translucent text
in the bottom-right corner of the viewport.

The Wind Preview right panel is the compact-control reference for every
viewport dialog. Proxy Mesh, Fracture, and Prototype Preview reuse its shared
dropdown/popup styling, wide adjustable panel geometry, and vertically
scrollable settings structure. Fracture retains its parameter-wheel filter so
wheel input scrolls settings rather than changing an unfocused value.
The Wind, Geometry, and Materials tabs on the main shell reuse the same
compact controls inside their existing rounded cards. UDIM tile IDs are styled
as explicit editable fields rather than passive numeric labels.

For visual UI iteration, use direct PySide screenshots before packaging. Start
a `QApplication` from `.venv310`, construct the target dialog/widget with a
small fixture or fake result, call `show()` and `app.processEvents()`, then save
`widget.grab()` to `tmp/*.png` and inspect it. Example shape:

```python
from pathlib import Path
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(["ui-preview"])
dialog = build_dialog_with_fixture_data()
dialog.resize(1000, 720)
dialog.show()
app.processEvents()
Path("tmp").mkdir(exist_ok=True)
dialog.settings_panel.grab().save("tmp/ui_preview.png")
dialog.close()
```

This screenshot loop is a design preflight, not final validation. Keep the
packaged smoke/build gate for completed UI changes.

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
