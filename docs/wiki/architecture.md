# Architecture

The codebase is organized around one deterministic conversion system with different execution strategies around the edges.

For current contracts and problem tracking, see:

- [Decisions](decisions.md)
- [Known Bugs](known-bugs.md)
- [Encountered Crashes](encountered-crashes.md)
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
- `src/xml_to_usda/discovery_service.py` and `src/xml_to_usda/source_discovery_worker_subprocess.py` - lightweight material/prototype row discovery; XML files at or above 5 MiB are inspected outside the GUI process.
- `src/xml_to_usda/cache_maintenance.py` - bounded runtime cache maintenance for job leftovers, FBX payloads, source-model caches, Proxy Source Projection caches, legacy Fracture Preview cache files, and stale cache temp files.
- `src/xml_to_usda/proxy_mesh_service.py`, `src/xml_to_usda/fracture_service.py`, and related workers - companion workflows.
- `src/xml_to_usda/qem_simplification.py` - shared topology-preserving `fast-simplification` QEM backend used by Proxy Mesh and Fracture Preview diagnostic geometry.
- `src/xml_to_usda/fracture_geometry.py` - deep Fracture Geometry module shared by preview and export; owns subtree-local Cut Surfaces, deterministic noisy clipping, attribute interpolation, intersection-loop caps, and manual cross-section snapping. Cut planning supplies the shared automatic physical-bone offset, so flat and Detailed Cuts start at the same site. Repeated Part attachment ownership stays outside geometry.
- `src/xml_to_usda/boolean_fracture_prototype.py` - connectivity-first Manifold Boolean backend used by production Detailed Cuts and the standalone prototype viewers. A source context prepares analysis, triangulation, and connectivity once; prepared cut sessions own closed solids and cache their last result. Independent components build separately. Cuts sharing one shell split the current parent region sequentially in Fracture Plan order, preserving distinct cap provenance and final piece ownership. Multi-cut replans reuse unchanged independent sessions/results by exact cut-site identity.
- `src/xml_to_usda/qt_ui/boolean_prototype.py` - standalone `boolean-prototype` stage viewer and `boolean-multi-prototype` whole-tree piece viewer.
- `src/xml_to_usda/fracture_worker_subprocess.py` - crash-isolated Fracture Preview and export worker protocol. Detailed Cuts run in one fresh worker per request so native Boolean state cannot outlive a result.
- `src/xml_to_usda/qt_ui/preview_jobs.py` - shared latest-request lifecycle for process-backed previews. Each preview type owns at most one active job and one coalesced pending request; settings changes never terminate active native work, and stale results/errors are discarded before the latest request starts.
- `src/xml_to_usda/wind_preview_service.py`, `src/xml_to_usda/wind_viewport_scene.py`, `src/xml_to_usda/wind_group_stack.py`, and `src/xml_to_usda/wind_external_skeleton.py` - Wind Preview source service, Qt-free viewport scene adapter, manual override stack, and skeleton-only external FBX/USD loading.
- `src/xml_to_usda/proxy_source_projection.py` - typed Proxy Source Projection loading/cache for Proxy Mesh jobs that need base geometry and skin binding, +X-oriented skeleton facts, repeated-part transforms, and source prototype geometry.
- `src/xml_to_usda/proxy_collision.py` - deterministic Box/Capsule fitting for Proxy Mesh trunk collision using the Fracturing stem-axis contract.
- `src/xml_to_usda/collision_primitives.py` - shared oriented Box/Capsule mesh builders used by Proxy Mesh and Fracturing.
- `src/xml_to_usda/mesh_pruning.py` - shared deterministic percentage-based face pruning for preview/proxy workflows that need to drop the smallest disconnected base-mesh islands before their own simplification pass.

Proxy Preview treats render-mesh generation and collision fitting as separate
worker actions. Collision-only settings reuse the current `ProxyMeshResult`;
On/Off reuses the retained fitted collision immediately, while fit changes load
the cached Proxy Source Projection without rerunning voxel extraction or QEM.
The Proxy viewport frames and places its grid from the render mesh and explicit
tree pivot, never from guide collision bounds.

Important data flow:

1. XML is parsed and normalized into canonical source facts.
2. Operator intent is resolved into an authored assembly model.
3. Validation checks source, resolution, and authoring invariants in order.
4. USDA authoring emits the importer-facing scene shape.

Canonical normalization keeps its public model unchanged while avoiding hot-path
allocation churn: immutable source UV values are reused across face corners,
normal axes are remapped in batches without temporary vectors, scalar packed
fields use a direct parse path, schema inspection uses plain local maps, and
cyclic GC is suspended only while the acyclic cold-load graph is built. Keep
these choices benchmark-backed. On the 9.7 MB Big Spruce sample with source
cache disabled, an order-balanced one-core comparison reduced the complete
`read + inspect + normalize + validate` phase from 1.689 s to 1.114 s wall
median and from 1.648 s to 1.078 s CPU median: 34.0% and 34.6% respectively,
without changing model output.

Interactive preview flows may stop earlier when they inspect source facts rather
than authored output. Wind Preview V1 loads canonical XML source facts, derives
Dynamic Wind groups, and adapts those facts to viewport batches for inspection.
Wind Preview keeps the same shared viewport and worker boundary while using a
deterministic wind-group stack: XML Generator Groups or Auto Hierarchy provide a
base, manual override layers sit above it, and the flattened result writes the
existing Dynamic Wind JSON schema. Auto Hierarchy derives groups from skeleton
topology and SpeedTree/file joint ordering, not from XML wind generator labels.
Optional per-layer `Continue line` flags let endpoint-continuous child chains
stay in the same group when explicitly enabled. A restored valid XML path
automatically refreshes the main Wind groups after startup; the manual Refresh
button remains available. A Preview request made during that refresh is queued
until inspection finishes, so the GUI and isolated preview worker do not load
the same large source concurrently. External Skeleton loading reads
FBX or USD/UsdSkel payloads as skeleton-only previews. Source loading, USD
Skeleton prim enumeration, and scene build run in a file-backed worker process
so XML/external skeleton faults do not crash the Qt shell. The GUI consumes the
worker-built initial scene directly. Selecting an external file starts loading
immediately; a multi-skeleton USD waits only for the operator to select its
Skeleton prim, then loads without a separate confirmation button. The worker
result keeps only the compact
base-mesh viewport scene and skeleton; Repeated Parts are intentionally absent
because Wind Preview is a skeleton inspection workflow. It does not serialize
the full CanonicalTreeModel beside the scene. Grouping edits recolor that scene and
replace its bone overlay without rebuilding source geometry. Base-mesh face
ranges are computed once per scene rather than once per joint. The Wind Preview
right panel uses
one global settings scroll; the Layers block is the only nested scroll and can
be resized vertically with a local handle even when the global panel scrollbar
is visible. External Skeleton USD loading uses OpenUSD/`pxr` from `usd-core`
for normal USD support. Text `.usda` and ASCII `.usd` files can still be read
through the deterministic text fallback, but multiple Skeleton prims require
an explicit operator choice instead of any largest-skeleton heuristic.
The SpeedTree XML worker path does not import the External Skeleton backend.
An unexpected native Wind Preview worker exit is retried once in a clean
process. Worker subprocesses enable Python faulthandler so a repeated native
failure leaves a diagnostic stack in the captured stderr file.
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
Shared camera navigation includes left-button orbit, middle-button pan in the
camera plane, wheel zoom, double-left-click mesh focus, and `F` frame-all.
Wheel zoom can approach to 0.1% of the framed scene radius, with a distance-
adaptive near plane for close cut inspection. Scene setters only mark OpenGL
buffers dirty; GPU uploads run in `paintGL` while Qt owns the current context.
Fracture Preview uploads each unique Base/Repeated Part mesh once, stores
placement transforms in a compact GPU instance buffer, and issues one hardware-
instanced draw per unique source mesh. The 256 MiB guard covers unique vertex
buffers rather than logical instance-expanded geometry.

The Wind Preview right panel is the compact-control reference for every
viewport dialog. Proxy Mesh, Fracture, and Prototype Preview reuse its shared
dropdown/popup styling, wide adjustable panel geometry, and vertically
scrollable settings structure. Fracture groups controls into collapsible
Preview Geometry, Automatic Cuts, Cut Surface, Viewport, Collision, and Manual
Cuts sections. It retains its parameter-wheel filter so wheel input scrolls
settings rather than changing an unfocused value.
The Wind, Geometry, and Materials tabs on the main shell reuse the same
compact controls inside their existing rounded cards. UDIM tile IDs are styled
as explicit editable fields rather than passive numeric labels.

The main shell keeps one `ProgramStatusCard` beside those tabs. It consumes the
existing `ConversionTelemetry` directly, groups backend phases into five
operator-facing conversion stages, and represents other background jobs as a
compact current operation. The same card owns the short XML/material/mode
summary; detailed runtime settings and full paths remain in their owning tabs,
Settings, and the conversion-start log. `MainWindow.status_label` remains an
alias to the card's message label for packaged and adapter compatibility.

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

The main shell never imports Autodesk FBX solely to build its XML discovery
panels. FBX loading is lazy at the actual FBX action boundary. Restored large
XML inputs are shown immediately, discovered in a fresh file-backed worker,
then inspected for Wind groups in the existing isolated Wind worker; the
source reads do not overlap.

Testing has four separate execution boundaries: Core (synthetic deterministic
contracts), Integration (source/worker/Qt workflows), Packaged (frozen EXE and
runtime cache/worker boundaries), and manual UE 5.7.x validation. The first
three use pytest markers managed by `tests/conftest.py`; UE validation is never
folded into pytest. The current contract map and commands live in
[`testing.md`](testing.md).

Important folders:

- `src/xml_to_usda/` - production code.
- `src/xml_to_usda/skeleton_processing.py` - deterministic +X bone frames, parent/current bindings, and mandatory skeleton/skinning invariant validation.
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
