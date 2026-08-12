# Decisions

This page stores active project contracts. Rejected or superseded approaches live in [experiments.md](experiments.md). Current limitations and bugs live in [known-bugs.md](known-bugs.md).

## Decision: Public standalone identity is SpeedAssembly

Status: Active

The distributed executable is `SpeedAssembly.exe`; the release archive is
`SpeedAssembly_release.zip`; the Qt application title, Windows application ID,
runtime settings/cache root, diagnostics archive, package help, and current
operator-facing documentation use `SpeedAssembly`.

The release ZIP contains only `SpeedAssembly.exe` and
`examples/SimpleTree_01.xml`. Keep `build_info.json` beside the local package
for diagnostics, but do not distribute it; a concise HTML quick-start may be
added to the archive later.

The internal Python package remains `xml_to_usda` so existing source imports,
worker commands, and file-format contracts remain stable. Legacy
`XMLtoUSDAWorker.exe` references are retained only for cleanup of obsolete
sidecar releases.

The baseline import workflow has been manually confirmed in UE 5.7 and UE 5.8.
Proxy Mesh exists as a companion Static Mesh for collision, distance-field, and
lower-cost shadow workflows; import confirmation does not by itself validate
lighting quality.

## Decision: Public user documentation is an isolated MkDocs site

Status: Active

Public operator documentation lives only in `docs/user/`. MkDocs Material
builds that directory through `mkdocs.yml`; the GitHub Pages workflow publishes
the generated static `site/` artifact independently from application releases.
`docs/wiki/`, `docs/raw/`, drafts, templates, and local Obsidian state must not
enter the public artifact.

Documentation dependencies are pinned in `requirements-docs.txt` and remain
outside the application runtime and packaged EXE. Local authoring uses the
canonical `.venv310` environment and `scripts/preview_documentation.cmd`.

Contextual application help will target explicit stable anchors such as
`reference/proxy-mesh/#density-resolution`; heading copy may change without
removing an anchor already used by a released application.

Related files:
- `mkdocs.yml`
- `requirements-docs.txt`
- `.github/workflows/documentation.yml`
- `docs/user/`
- `scripts/preview_documentation.cmd`

## Decision: Tests are organized by system contract and execution boundary

Status: Active

Core tests protect fast deterministic invariants with synthetic fixtures.
Integration tests cover source workflows plus worker/Qt request transport.
Packaged tests prove the frozen executable boundary and must validate actual
geometry results. UE import validation stays manual and separate from pytest.

Simple Tree is the normal workflow fixture and the three-trunk variant owns
multi-stem/stump behavior. Big Spruce is not a general regression fixture: use
it only for measured scale/performance or packaged stress. See
[Test Policy](testing.md) for the contract map and commands.

## Decision: Fast UI previews are source-backed and separate from releases

Status: Active

Low-risk UI iteration uses `build_qt_gui_exe.cmd -Quick` after relevant tests.
It performs an import check and writes the source-backed launcher
`dist-preview/SpeedAssembly_preview.cmd`. It deliberately skips PyInstaller,
packaged contracts, the release ZIP, and smoke, so it must never be treated as
evidence about frozen behavior or as `dist-next/SpeedAssembly.exe`.

The full `-Package` gate remains mandatory for importer-facing/backend work,
worker and cache lifecycle, FBX/USD/OpenGL/native boundaries, packaging or
dependency changes, packaged-only failures, native crashes, and releases.
Ordinary UI defects iterate in Quick and receive one full Package gate after
the fix; defects unique to frozen/native execution validate each candidate with
Package.

## Decision: Detailed Boolean Fracture is the production cut backend

The connectivity-first physical Boolean now serves Detailed Cuts in preview and export; the standalone prototype commands remain diagnostic viewers for the same backend.

Keep the `boolean-prototype` UI separate from the production Fracture Preview, but share its geometry backend. It resolves the existing cut semantics, uses the flat plan only to identify the whole connected branch shell, closes every valid degree-two boundary loop, and runs a deterministic `manifold3d` split. Temporary closures and cutter caps have distinct provenance. Manifold can triangulate complementary caps differently, so a small deterministic simplification removes redundant collinear split vertices and the child reuses the parent cap topology with opposite winding.

When several disconnected child-subtree shells cross one cut plane, select the
unique shell with the strongest face ownership by the cut bone. Descendant twig
shells with only transition faces owned by that bone remain untouched in their
planned child piece. Equal strongest evidence remains an explicit error.

Requested noise amplitude is scaled uniformly, never hard-clamped per lattice vertex, to the first physical skeleton terminal, real branch, or local bend above the operator threshold. One lattice edge is reserved before that limiter. Source-derived Boolean faces carry exact source-triangle provenance for barycentric UV, color, material, and skin-weight transfer. Cutter caps use planar cutter-space UVs, inherit the boundary-ring material and attributes, and remain explicitly tagged.

The multi-cut prototype stays sequential. Do not add an outer thread pool: the
wheel already has internal oneTBB and the Python binding does not release the
GIL. A Windows spawn-based process pool was also rejected after the documented
1/2/4-process gate: even 37 independent cuts did not beat the sequential
end-to-end path, while worker RSS scaled with process count. Reconsider only if
the runtime boundary changes enough to remove model/session serialization and
cold worker startup; repeat speed, RSS, exact-result, and packaged-stability
gates before production use.

Interactive Boolean regeneration must use explicit prepared sessions scoped to its window/job. Base Mesh analysis, triangulation, and connectivity are shared once per source context; boundary closure, provenance, and the closed branch Manifold are immutable per cut. Noise controls rebuild only cutters and complementary results. A changed cut plan creates a new multi session. Do not use a global model cache.

Multi-cut replanning must reuse an unchanged cut session and its last result when both the resolved `FractureCutSite` and cutter settings are identical. Enabling a stump or raising branch count may build only newly introduced cuts; ownership and untouched source slices may still change. Never reuse by joint name alone when the resolved cut site differs.

Cuts on one connectivity shell are evaluated sequentially in plan order. Each cut splits the current region owned by its resolved parent Fracture Piece, leaves the intersection in that parent, and assigns the complementary child to the cut piece. If the parent region does not yet exist, fail loudly rather than reorder cuts heuristically. Every cutter keeps a distinct provenance tag so all final adjacent caps can be canonicalized and attributed independently.

Production Boolean geometry preserves source-side normals and uses an unconditional hard edge along the source/Boolean-cap perimeter. Within the Boolean cap, edges with dihedral angle greater than or equal to 90 degrees are hard; shallower edges may smooth. This is encoded as mesh data/export behavior, not only as viewport shading.

Fracture Piece ownership resolves the deepest selected cut by one parent-chain walk per skeleton joint. Do not restore the previous selected-cuts × joints × ancestry scan; the same shared planner serves Preview, Export, and Boolean preparation.

Repeated Part ownership starts from skeleton binding, then applies only the
selected segment cuts on that binding's ancestor chain. Flat cuts classify the
instance pivot with the existing physical-bone projection and `segment_t`
plane already used for Base Mesh ownership; unrelated sibling cuts are never
evaluated. A pivot behind several nested cuts may climb through those parent
pieces in order.

Detailed ownership continues from that flat result only after the corresponding
Boolean cutter exists. The instance pivot is classified against the
already-built triangular cutter surface by barycentric height; no second cutter
or noise field may be generated. Nested cuts resolve deepest-first. If the
pivot projection does not intersect that specific cutter surface, retain the
flat ownership instead of borrowing a nearby edge or another branch's surface.

An automatic branch cut may claim a face dominated by its immediate parent
only when at least one positive skin influence belongs to that cut's child
subtree. Centroid projection still decides which side of the cut contains that
eligible transition face. Parent-only faces and collars influenced by a sibling
stay with the parent regardless of their projection along the selected branch.
The planner derives this eligibility once per source face and shares it between
flat and Detailed paths.

Why: preview and export need one deterministic topology, attribute, collision, and Repeated Part ownership contract; the diagnostic viewer should expose that implementation rather than define a second one.

## Decision: Manual cut `t` is measured on the physical child bone

SpeedTree hierarchy edges may be connector links from a trunk or parent branch to the start of a child branch. They are not necessarily the physical bone displayed for that child.

Keep the token format `parent->child@t`, but interpret `t` on `child.bind → child.bind_end`. Use `parent.bind → child.bind` only when the source has no `bind_end`. The planner, preview overlay, exact Fracture Geometry, and Boolean prototype share this contract. Manual spatial ownership is limited to the child subtree plus local faces owned by the immediate parent; sibling branches sharing that parent must never enter the cut piece.

## Decision: Skeletal assembly remains the primary contract

Status: Active

Context:
The project now supports both skeletal and static assembly export shapes.

Decision:
Keep `skeletal_assembly` as the primary importer-facing contract. Treat `static_assembly` as a supported secondary mode.

Reasoning:
The project goal is still the skeletal vegetation pipeline, and UE behavior for that path is the highest-value validation target.

Consequences:
Static-mode simplifications must not erase locality for skeleton, binding, or part-skeleton rules.

Related files:
- `AGENTS.md`
- `docs/raw/ue_import_contract.md`
- `docs/raw/workflow_status.md`

## Decision: Static Assembly Parts is a prototype-library export

Status: Active; operator-validated in Unreal

`static_parts` uses the same resolved prototype set and output-directory rule
as `skeletal_parts`, then writes one USDA per prototype. Inline XML and FBX
payloads become a root `Xform` with one `SM_`-prefixed static `Mesh`. The file
contains no Assembly Root API, Base Mesh, PointInstancer, skeleton, skeletal
binding, or instance transforms. Explicit Unreal asset reuse remains a pure
external-reference prototype because no geometry payload exists to bake.

This is not Fracture export: it neither clips the Base Mesh nor creates one file
per Fracture Piece. It exports each unique Repeated Part prototype once.

Manual operator validation confirmed that the standalone static parts import as
expected and that a full Static Assembly using those imported assets through
Unreal Reference imports normally.

The main UI shows the `Create Parts Folder` checkbox only for Skeletal Assembly Parts and
Static Assembly Parts. It is enabled by default to preserve the isolated-output
workflow. Enabled output directories are named `<OutputStem>_SkeletalParts` or
`<OutputStem>_StaticParts`; disabled writes the prototype files directly beside
the selected Output USDA. This is path routing only and does not change USDA
authoring.

For either Parts mode, if every discovered prototype uses Unreal Reference,
the UI does not start an empty conversion. It reports `Nothing to export` in
the existing status card without opening an error dialog.

Related files:
- `src/xml_to_usda/conversion_orchestrator.py`
- `src/xml_to_usda/usda_authoring.py`
- `src/xml_to_usda/qt_ui/window.py`
- `tests/test_export_modes.py`

## Decision: The canonical model is source-normalized

Status: Active

Context:
The project works from observed SpeedTree XML, not from a public XML spec.

Decision:
Treat the canonical model as normalized source facts, not as a skeletal-only authoring model.

Reasoning:
Static assembly and skeletal assembly both need the same normalized source interpretation.

Consequences:
Authoring mode is chosen after normalization, not inside raw XML traversal.

Related files:
- `docs/raw/speedtree_mapping.md`
- `docs/raw/DECISIONS.md`

## Decision: Mesh-bearing Object LeafReferences use Object-local positions

Status: Active

Observed SpeedTree Raw XML may place `LeafReferences` beside the enclosing
Object's `Points` and `Triangles`. In that shape, both mesh points and repeated
part positions are Object-local and must receive the same `Object/@Abs*`
translation during normalization. Apply this once in the shared Repeated Part
builder used by canonical conversion and Proxy Source Projection; do not infer
position space from hierarchy depth, Object names, instance count, or bounds.

An Object with zero `Abs*` remains unchanged. A non-mesh LeafReferences host
with non-zero `Abs*` is currently ambiguous and must fail loudly until a real
SpeedTree export establishes its transform contract. Source-model and Proxy
Source Projection cache schema versions must change with this normalization
semantic so stale positions cannot survive an application update.

Evidence:

- `SK_Willow_Assembly_12.xml` contains 1,086 mesh-bearing hosts with non-zero
  `Abs*` and 7,894 local repeated-part positions.
- Object-local LeafReferences bounds match their sibling local mesh bounds;
  applying `Abs*` aligns both in world space.
- The shortened Willow, Simple Tree, and three-trunk samples have zero `Abs*`
  on their non-mesh LeafReferences hosts and remain unchanged.

Related files:
- `src/xml_to_usda/normalizer.py`
- `src/xml_to_usda/proxy_source_projection.py`
- `src/xml_to_usda/canonical_loader.py`
- `tests/data/leafrefs_on_branch_levels.xml`

## Decision: Resolved assembly is the seam between source facts and operator intent

Status: Active

Context:
Prototype replacement, explicit material choices, output naming, and export mode all depend on caller intent.

Decision:
Keep a resolved authoring model between canonical source facts and USDA authoring.

Reasoning:
Source facts and operator intent have different lifecycles and failure modes.

Consequences:
Request-specific behavior stays out of normalization.

Related files:
- `docs/raw/ARCHITECTURE.md`
- `docs/raw/DECISIONS.md`

## Decision: Validation is staged

Status: Active

Context:
Different invariants belong to source interpretation, request resolution, or USDA authoring.

Decision:
Use source validation, resolution validation, and authoring validation as separate stages.

Reasoning:
The stages have different inputs and different failure modes.

Consequences:
Tests and failures stay closer to the invariant that owns them.

Related files:
- `docs/raw/DECISIONS.md`
- `docs/raw/ARCHITECTURE.md`

## Decision: Test density is practical, not exhaustive

Status: Active

Context:
The test suite already protects many conversion, UI, runtime, and importer-contract paths. During experimental work, repeatedly adding or rewriting tests for every small attempt slows implementation and can encode temporary behavior before the operator has confirmed that the feature works.

Decision:
Keep existing tests, but add new tests selectively. New modules, public contracts, stable feature behavior, and importer-facing invariants need focused regression coverage. Simple edits, UI polish, documentation, mechanical cleanup, and intermediate experiments should usually rely on relevant existing checks until the behavior is accepted.

Reasoning:
Tests should protect completed intent and dangerous contracts, not mirror every implementation step. Prefer broad intent-level tests that catch meaningful breakage; when they fail, inspect the code to locate the exact cause.

Consequences:
Agents should not treat every small code change as requiring a new test. For experiments, prove the behavior with the smallest useful manual or focused check first, then freeze the accepted behavior with a compact regression test.

Related files:
- `AGENTS.md`
- `docs/raw/test_tiers.md`
- `docs/raw/test_suite_map.md`

## Decision: Repeated Part is source-level, Assembly Part is authored

Status: Active

Context:
`LeafReferences` are source records, while `PointInstancer` emits authored repeated geometry.

Decision:
Use `Repeated Part` for source-level repeated geometry and `Assembly Part` for authored repeated geometry.

Reasoning:
Source terminology and authored terminology serve different layers.

Consequences:
Static and skeletal exports can share the same source facts without sharing the same importer contract.

Related files:
- `docs/raw/GLOSSARY.md`
- `docs/raw/DECISIONS.md`

## Decision: Attachment is source/resolution, Skeletal Binding is authored

Status: Active

Context:
Source placement facts such as `BoneID` are not yet authored USD skeletal binding arrays.

Decision:
Use `Attachment` for source or resolved placement relationships and `Skeletal Binding` only for authored USD binding.

Reasoning:
Static assembly can interpret source placement without authoring skeletal binding.

Consequences:
Binding bugs and placement bugs stay distinguishable.

Related files:
- `docs/raw/GLOSSARY.md`
- `docs/raw/DECISIONS.md`

## Decision: Material terminology is staged

Status: Active

Context:
Source materials, resolved material assignment, and authored material binding are different layers.

Decision:
Keep those terms separate in code and documentation.

Reasoning:
XML ids, operator overrides, and USD material bindings have different meanings.

Consequences:
Explicit FBX material modes and piece-local UDIM rules stay readable.

Related files:
- `docs/raw/GLOSSARY.md`
- `docs/raw/DECISIONS.md`

## Decision: Naming and transform terminology stay explicit

Status: Active

Context:
The project has had regressions around naming and transform-space confusion.

Decision:
Keep `Source Name`, `Output Stem`, `Prim Name`, `Authored Asset Name`, `Source Space`, `Stage Space`, `Prototype Space`, `Attachment Space`, and `Instance Transform` distinct.

Reasoning:
Naming and transform bugs are easier to reason about when the terms are precise.

Consequences:
Code and docs should not collapse those concepts into generic labels.

Related files:
- `docs/raw/GLOSSARY.md`
- `docs/raw/DECISIONS.md`

## Decision: PySide6 is the supported desktop shell

Status: Active

Context:
The old Tk shell has been retired.

Decision:
Keep PySide6 as the supported UI path and treat the old Tk path as retired.

Reasoning:
One supported shell keeps the UI contract and runtime behavior easier to maintain.

Consequences:
UI work should stay behind the PySide6 adapter layer.

Related files:
- `docs/raw/ui_next_architecture.md`
- `docs/raw/DECISIONS.md`

## Decision: UDIM resolution is piece-local

Status: Active

Context:
The same numeric material id can appear in different authored pieces without conflict.

Decision:
Apply UDIM settings independently per authored piece.

Reasoning:
Piece-local resolution matches operator expectations and avoids cross-piece overwrite.

Consequences:
Duplicate active settings within one piece, or a target that matches nothing, must fail loudly.

Related files:
- `docs/raw/DECISIONS.md`
- `docs/raw/ARCHITECTURE.md`

## Decision: Balanced stays the visible CPU profile

Status: Active

Context:
Large jobs need runtime stability more than exposed tuning knobs.

Decision:
Keep `balanced` as the visible default runtime profile.

Reasoning:
The operator should not need to reason about concurrency knobs for the normal workflow.

Consequences:
Deeper runtime tuning stays internal unless a validated need appears.

Related files:
- `docs/raw/DECISIONS.md`
- `docs/raw/workflow_status.md`

## Decision: Conversion preflight requires every discovered Unreal material assignment

Status: Active

The USDA conversion worker must not start while a discovered Base Mesh material
row or a required inline Part material row is blank. `single_material` requires
Single, `vertex_color_split` requires Black and White, and `material_slots`
requires every discovered slot. Reused Unreal Part assets keep their own
materials and are exempt; Proxy Mesh remains a separate workflow.

This check belongs in application request planning so GUI and CLI callers share
one launch boundary and no Runtime Job is created for an incomplete material
contract.

Related files:
- `src/xml_to_usda/conversion_service.py`
- `src/xml_to_usda/qt_ui/window.py`

## Decision: Known transient FBX binding failures reduce helper concurrency

Status: Active

Prototype FBX imports still start at the requested helper concurrency. If the
Autodesk binding reports the observed transient
`FbxVector2.__getitem__(): not enough arguments` failure, keep completed
payloads and retry only the remaining FBX tasks with one fewer helper. At one
helper the same failure remains fail-loud.

This is narrower than retrying arbitrary Python or payload errors. The
WorldTree evidence showed both HIGH FBX files overlap in the failing run, while
the same `SM_BigBranch_02_HIGH.fbx` completed sequentially with 16,813,048
points and 21,029,320 triangles.

Related files:
- `src/xml_to_usda/fbx_import_supervisor.py`
- `tests/test_fbx_prototype_sources.py`

## Decision: Large FBX dense arrays use bounded NumPy paths

Status: Active

Keep `GeometryBuffer` and the Autodesk helper-process boundary unchanged.
Above measured thresholds, transform control points in bounded NumPy chunks,
expand indexed `eByPolygonVertex` UVs from a bounded direct table plus index
chunks, and traverse triangle topology once per face when no per-corner work
remains. Release the SDK control-point wrapper list before topology traversal.
Small payloads retain the scalar path because a cold NumPy import is larger
than their possible saving.

Large vertex-color material partition views the existing `array` buffers with
`numpy.frombuffer`; it does not copy them into shared memory or start a process
pool. Cancellation is checked between bounded chunks. Exact-invalid topology
and color-index behavior remains fail-safe, and the returned section order is
unchanged.

Evidence: `SM_BigBranch_01_HIGH.fbx` produced byte-identical point, face-count,
face-index, and UV buffers while improving 97.724 s to 57.598 s. The real
58,463-face partition improved 0.03242 s to 0.00570 s. Do not replace this with
`FbxMesh.GetPolygonVertices()`: on the same class of asset it materializes tens
of millions of Python integers and creates a multi-gigabyte transient peak.

Related files:
- `src/xml_to_usda/fbx_adapter.py`
- `src/xml_to_usda/payload_partition.py`
- `tests/test_fbx_prototype_sources.py`
- `tests/test_payload_partition.py`

## Decision: Large GUI jobs run outside the UI process

Status: Active

Context:
Heavy conversions were unstable when too much FBX or USDA work happened inside the UI shell.

Decision:
Run large conversions in a dedicated worker subprocess and keep the UI shell out of the heavy native path. Source-row discovery and Wind group inspection for XML files at or above 5 MiB follow the same rule, including a restored input at application startup.

Reasoning:
Process isolation keeps the interface responsive and contains native failures. A restored 148.5 MB WorldTree must not be parsed synchronously before the main window is shown.

Consequences:
Packaged smoke and stability gates stay required for the worker path. GUI startup must also avoid importing the Autodesk FBX SDK merely to define discovery helpers; FBX is loaded lazily only when an FBX-backed action needs it. Bootstrap Python exceptions are appended to the persistent GUI runtime log before being re-raised.

Related files:
- `src/xml_to_usda/discovery_service.py`
- `src/xml_to_usda/source_discovery_worker_subprocess.py`
- `src/xml_to_usda/qt_ui/entry.py`
- `src/xml_to_usda/qt_ui/window.py`
- `docs/raw/workflow_status.md`
- `docs/raw/troubleshooting.md`

## Decision: Preview stability must not redefine mesh quality contracts

Status: Active

Context:
Proxy Mesh and Fracture Preview needed crash containment without changing the meaning of the exported geometry.

Decision:
Keep QEM-based Proxy Mesh and Fracture Preview simplification and file-first worker completion rules intact.

Reasoning:
Cheaper diagnostic paths are acceptable only when they do not weaken the exported topology contract.

Consequences:
Face sampling stays rejected for Proxy Mesh and Fracture Preview because it creates disconnected triangle holes. Preview/proxy base-mesh paths may apply deterministic connected-component pruning before their own simplification pass to discard tiny disconnected terminal details: `Remove Small Branches` is a percentage of smallest connected islands to remove, not a relative size cutoff. Both workflows use the shared QEM topology simplification backend. Fracture Preview must not apply a hidden per-piece ceiling below the visible Preview Polycount range. Worker polling must drain result/error files before treating a stopped worker as a crash.

Related files:
- `docs/raw/DECISIONS.md`
- `docs/raw/ARCHITECTURE.md`

## Decision: Preview shell is shared infrastructure, not a mode switcher

Status: Active

Context:
Proxy Mesh Preview and Fracture Preview share window behavior but not the same mode payloads.

Decision:
Use one preview shell module for ownership, modality, focus, and layout, but keep mode-specific dialogs separate.

Reasoning:
A shared shell removes duplicated window behavior without coupling payload lifetimes or settings ownership.

Consequences:
Do not introduce a hot-swappable runtime preview shell unless the product becomes a real mode switcher.

Related files:
- `docs/raw/DECISIONS.md`
- `docs/raw/ARCHITECTURE.md`

## Decision: Manual fracture cuts are current XML session state

Status: Active

Context:
Pinned fracture cut sites depend on the current source skeleton and do not travel safely across files.

Decision:
Keep manual fracture cut sites in the active Fracture Preview session only.

Reasoning:
Cross-file reuse would create hidden coupling between unrelated trees.

Consequences:
Manual picks are not part of global presets or persisted operator settings.

Related files:
- `docs/raw/DECISIONS.md`
- `docs/raw/ARCHITECTURE.md`

## Decision: Fracturing uses one planner

Status: Active

Context:
Operator-facing Fracturing is now a single planner with pinned cuts and deterministic fill.

Decision:
Keep Manual Fracturing as one planner instead of several separate fracture methods.

Reasoning:
Separate modes made the UI look more powerful than the underlying planner.

Consequences:
Legacy fracture method ids should be rejected loudly.

Related files:
- `docs/raw/DECISIONS.md`
- `docs/raw/ARCHITECTURE.md`

## Decision: V1 automatic fracturing detaches natural weak points only

Status: Active

Context:
The old automatic fill could refine trunk chains and synthetic face regions, producing visibly unnatural trunk shredding on simple trees.

Decision:
Treat `target_piece_count` as operator-facing Auto Branches / Branch Count. Automatic V1 cuts may add a stump piece, separate independent root-level stems, and detach branch bases ranked by skeleton path length with optional height bias. Stump and separated stems are counted outside Branch Count. Manual pinned cuts still run first and may cut trunks explicitly. Automatic branch cuts use one configurable physical-bone offset (5–95%, default 30%) in flat and Detailed paths. Detailed Cuts change only Cut Surface geometry; they must not change selected bones or piece structure.

Reasoning:
Length-first branch detachment better matches the perceived weak points of vehicle impact and nearby blast workflows while preserving manual control for exceptional cuts.

Consequences:
`preserve_trunk_bias` remains settings-compatible but is no longer an operator-facing V1 control. Preview skeleton segments must use the same realtime exploded offset as their owning pieces. Fracture Preview scales the vertical component of that offset by the fixed factor `0.2`; this is viewport behavior, not an operator setting.

Related files:
- `src/xml_to_usda/fracture_service.py`
- `src/xml_to_usda/fracture_preview_service.py`
- `src/xml_to_usda/qt_ui/fracture_preview.py`
- `docs/fracturing_v1_working_plan.md`

## Decision: Packaged workers use the self executable

Status: Active

Context:
The release now ships one executable and launches worker commands through that executable.

Decision:
Keep packaged worker commands before Qt imports and before GUI bootstrap.

Reasoning:
Worker processes must not construct the UI shell, and one executable keeps distribution simple.

Consequences:
The release must not recreate a separate worker executable layout.

Related files:
- `docs/raw/DECISIONS.md`
- `docs/raw/troubleshooting.md`

## Decision: UI shells are adapters over application interfaces

Status: Active

Context:
The supported PySide6 shell is only one adapter around the shared conversion system.

Decision:
Keep UI code thin and keep conversion semantics out of the shell.

Reasoning:
One UI surface keeps the package and launcher behavior aligned.

Consequences:
UI state, operator intent, and runtime jobs must stay distinct.

Related files:
- `docs/raw/ARCHITECTURE.md`
- `docs/raw/ui_next_architecture.md`

## Decision: Interactive workflows optimize for low latency by default

Status: Active

Context:
The operator repeatedly previews Proxy Mesh, Fracture Preview, materials, and export-adjacent settings while judging visual quality.

Decision:
Treat avoidable UI pauses as product defects. Preview and setup paths should prefer narrow projections, typed caches, incremental reuse, and measured hot-path simplification over broad object reconstruction.

Reasoning:
The converter is an operator tool, not only a batch exporter. A technically correct result that repeatedly blocks the workflow for several seconds still damages the pipeline.

Consequences:
Before adding a broad cache or full-model reload to an interactive path, measure it against a narrow workflow-specific payload. Generic worker-payload JSON remains acceptable for IPC, but not as the default persistent cache for large preview/source models. Keep importer-facing correctness first, but make the default UX target as close to real-time as the workflow safely allows.

Related files:
- `src/xml_to_usda/proxy_source_projection.py`
- `src/xml_to_usda/mesh_pruning.py`
- `src/xml_to_usda/fracture_preview_service.py`

## Decision: Proxy source loading bypasses the generic source-model cache

Status: Active

Context:
Proxy Mesh generation on large SpeedTree XML files needs only base geometry, repeated-part transforms, and source prototype geometry. The generic JSON source-model cache can cost more to read or write than reparsing and normalizing the XML, especially on branch-heavy real samples.

Decision:
Keep the generic cache for normal conversion callers, but use a dedicated Proxy Source Projection and typed `.npz` cache for the Proxy Mesh source request path.

Reasoning:
Measured Proxy Mesh timings on `SK_BirchAltai_Assembly_13.xml` improved from about 17.1s before the speed work to about 3.5s cold and about 1.85s warm after Proxy Source Projection cache and local hot-path polish, without changing QEM simplification, pruning policy, output geometry settings, or importer-facing contracts. Projection output matched canonical-derived proxy output on the temporary Birch sample and repo samples.

Consequences:
Proxy preview/export no longer builds a full `CanonicalTreeModel` through authoring resolution. The Projection cache must stay typed and loaded with pickle disabled. Do not put material, skeleton, or authoring-resolution fields into it unless Proxy Mesh starts using them directly.

Related files:
- `src/xml_to_usda/proxy_source_projection.py`
- `src/xml_to_usda/proxy_mesh_service.py`

## Decision: Main UI export parameters are grouped and tooltip-backed

Status: Active

Context:
The main PySide6 UI exposes export-tree parameters for wind, prototype source assignment, material overrides, Proxy Mesh, and Fracture Preview. Dense ungrouped lists made it hard to tell whether a value affected source loading, preview mesh quality, fracture planning, viewport-only display, or collision output.

Decision:
Every operator-facing export parameter in the main UI should have a short English tooltip. Sliders and numeric fields should state what the value controls and what lower versus higher values do. Dense parameter panels should use functional groups with a subtle divider and compact group label.

Reasoning:
The operator should not need code knowledge to distinguish preview-only controls from exported geometry contracts.

Consequences:
Do not add new main-UI export sliders, checkboxes, combos, path fields, or material/UDIM controls without a concise tooltip. Keep UI-settings controls separate from this rule unless they affect exported tree data.

Related files:
- `src/xml_to_usda/qt_ui/panels.py`
- `src/xml_to_usda/qt_ui/proxy_preview.py`
- `src/xml_to_usda/qt_ui/fracture_preview.py`

## Decision: First-launch tutorial prompt stays inside the main shell

Status: Active

Decision:
The tutorial prompt is a regular child `QFrame` of `MainWindow`, positioned
under the `How to use` button. It is never a Qt `Tool`, popup, or native
top-level window.

Consequences:
The callout uses main-window coordinates and cannot appear outside a restored
non-maximized shell. Closing it persists immediately for the current build.
The prompt resets only when the persisted build signature changes, so every
new package can be checked once without repeating during later launches of
that same build.

Related files:
- `src/xml_to_usda/qt_ui/window.py`
- `src/xml_to_usda/qt_ui/persistence.py`

## Decision: Viewport previews are modal to the main shell

Status: Active

Decision:
All operational viewport previews use Qt `WindowModal` ownership through the
shared preview shell. A preview stays above the SpeedAssembly main window and
blocks its controls until the preview is closed.

Consequences:
Preview dialogs must not use popup dismissal behavior or be configured
individually as non-modal. The modality is scoped to this application window;
it does not force the preview above unrelated desktop applications.

Related files:
- `src/xml_to_usda/qt_ui/preview_shell.py`

## Decision: FBX Prototype Preview loads the selected payload directly

Status: Active

Context:
Prototype Preview is an interactive inspection workflow for one repeated-part
prototype. The FBX mode previously resolved the full assembly model before
showing one selected FBX replacement, which widened native failure surface and
added avoidable latency.

Decision:
For `FBX file` Prototype Preview, load the chosen FBX payload directly through
the same FBX read options and payload cache used by export. Keep the full
resolved assembly path for XML mesh preview, where source prototypes and
source material metadata come from the normalized XML model.

Reasoning:
The operator needs a responsive local preview of the selected replacement
payload and material split. Full assembly resolution is unnecessary for that
case and can make a preview crash look like an export-contract failure.

Consequences:
FBX Prototype Preview stays isolated from the UI process, keeps strict
vertex-color validation for `vertex_color_split`, and reuses the bounded FBX
payload cache. Node transforms are read once and applied with equivalent
row-vector arithmetic instead of calling the unstable FBX `MultT` binding for
every control point. The viewport receives at most 50,000 evenly sampled source
faces for oversized prototypes; source/export triangle counts remain exact and
export geometry is unchanged. It does not redefine exported instance
transforms, attachment, or skeletal binding.

Related files:
- `src/xml_to_usda/part_preview_service.py`
- `src/xml_to_usda/qt_ui/part_preview.py`

## Decision: Fracture Preview does not remove small branches by default

Status: Active

Context:
`Remove Small Branches` is useful as a manual preview simplification control,
but a persisted high value made Fracture Preview hide child branch geometry on
the three-trunk sample and made separated stems look branchless.

Decision:
Fracture Preview defaults `Remove Small Branches` to `0.0` and does not restore
that field from persisted GUI settings. The operator can still raise it during
the current session when intentionally inspecting a simplified base mesh.

Reasoning:
Fracture Preview is primarily a fracture-plan diagnostic. Its default must show
the complete source base geometry for every piece, otherwise missing branches
look like planner or ownership bugs.

Consequences:
Keep Proxy Mesh pruning defaults separate from Fracture Preview. Do not make
Fracture Preview inherit the shared mesh-pruning default again.

Related files:
- `src/xml_to_usda/fracture_preview_service.py`
- `src/xml_to_usda/settings_service.py`

## Decision: Fracture Preview repeated-part visibility is viewport-only

Status: Active

Context:
Rapid or unlucky `Hide Repeated Parts` toggles could crash the packaged Qt
process with a native `0xc0000005` fault while rebuilding and re-uploading the
Fracture Preview OpenGL payload. Keeping the full payload resident also failed
on BigSpruce: 3613 hidden instances expanded to 38,044,065 vertices and a
2.59 GB upload, beyond Qt's signed buffer-size limit.

Decision:
When Repeated Parts are hidden, build and upload only the Base Mesh payload.
On the first explicit show, upload every unique prototype/piece-color batch
once and keep every placement in a compact GPU instance buffer. Render one
hardware-instanced draw per unique source mesh. Later hide/show changes only
the visible instance batches. The 256 MiB safety budget applies to unique
source vertices, not the logical instance-expanded triangle count.

Reasoning:
The checkbox is a visual inspection filter, not an operator setting that changes
fracture ownership. Hidden geometry must consume neither CPU expansion memory
nor GPU upload capacity. Reusing a successfully loaded full payload keeps later
toggles realtime without restoring the startup overflow.

Consequences:
Opening Fracture Preview with the default hidden state is bounded by Base Mesh
geometry. Showing Repeated Parts may perform one deliberate upload; later
toggles reuse it, and all source instances remain visible. Future visual-only
controls should update viewport state or shader uniforms whenever possible.

Related files:
- `src/xml_to_usda/qt_ui/fracture_preview.py`
- `src/xml_to_usda/qt_ui/viewport.py`

## Decision: Fracture Preview Detailed Cuts use a fresh native worker per request

Status: Active

Context:
The former persistent Fracture Preview worker intermittently produced access
violations and unrelated Python internal errors after Detailed Cuts. A typed
`.npz` cache was already removed after a separate packaged NumPy boundary
failure.

Decision:
Run each Fracture Preview request in one crash-isolated worker. It loads XML
directly and exits after it writes the result; it does not reconstruct Fracture
source facts from disk or retain native Boolean state for the next request.

Reasoning:
The retained persistent state could poison a later request at unrelated Python
locations. The measured fresh-worker overhead on Big Spruce is below one
second, which is preferable to a nondeterministic crash.

Consequences:
The GUI still coalesces to one active request plus the latest settings. A
worker crash is contained to its own result and cannot poison the next job. Do
not reintroduce a persistent native worker, generic JSON cache, or disk source
model cache without packaged evidence that identifies and eliminates the root
native fault.

Related files:
- `src/xml_to_usda/fracture_preview_service.py`
- `tests/test_fracture_preview_service.py`

## Decision: Interactive process previews coalesce instead of cancelling

Status: Active

Context:
Rapid UI edits previously terminated an in-flight preview process for every
new value. A result file could additionally exist before the UI consumed it,
leaving a short lifecycle window that was not represented by
`process.is_alive()`.

Decision:
Every `PreviewProcessJob` owns at most one active lifecycle and one pending
request. New requests replace only the pending request. They never terminate
the active process. A lifecycle remains active until its result/error handles
are consumed, even if the PID already exited. When current work completes, its
stale result/error is suppressed and only the latest pending request starts
after the existing debounce. Explicit dialog close/cancel may terminate work.

Independent preview types are not globally serialized: they do not share a
mutable job payload and a project-wide mutex would create unnecessary stalls.
Conversion/export actions keep their existing single-action guards rather than
entering the interactive latest-request queue.

Consequences:
Fast sliders may wait for the current computation, but cannot create overlapping
jobs or process-restart storms. Crash retry never replaces a newer pending
request. Active-state checks use owned handles, not only live-PID state.

Related files:
- `src/xml_to_usda/qt_ui/preview_jobs.py`
- `src/xml_to_usda/qt_ui/background_jobs.py`
- `tests/test_preview_jobs.py`
- `tests/test_qt_ui_workflows.py`

## Decision: Runtime caches are centrally bounded

Status: Active

Context:
The converter now has several useful persistent caches: FBX payloads, generic
source models, and Proxy Source Projections. The file-signature keys keep them
correct, but old entries from changed XML files would otherwise accumulate
indefinitely. Maintenance also removes legacy Fracture Preview `.npz` files
left by releases that used the retired disk cache.

Decision:
Keep disk-retention policy in `cache_maintenance.py`. GUI and CLI startup sweep
runtime/job leftovers, bounded FBX payload cache, source-facts caches, and stale
cache temp files through that module. FBX keeps its operator-configurable size
and age limits. Source-facts caches use a shared default budget of `2 GB` and
`14 days`; stale `.tmp`/`.partial` cache files follow the runtime stale-job TTL.
The Global Settings dialog can clear all managed cache entries.

Reasoning:
Cache producers should own payload shape, but not separate unbounded retention
rules. One runtime-facing maintenance module prevents source/proxy caches and
legacy files from becoming invisible disk growth while preserving low-latency
warm preview paths.

Consequences:
New persistent cache directories must be registered with cache maintenance or
explicitly documented as non-user cache. Do not add a workflow cache that only
invalidates by source signature without also giving it age and size cleanup.

Related files:
- `src/xml_to_usda/cache_maintenance.py`
- `src/xml_to_usda/qt_ui/window.py`
- `src/xml_to_usda/cli.py`
- `tests/test_cache_maintenance.py`

## Decision: Wind Preview uses base groups plus manual override layers

Status: Active

Context:
Wind Preview started as a read-only XML inspector with explicit Auto Hierarchy
preview grouping. The current workflow uses the same window to author Dynamic
Wind JSON for both SpeedTree XML skeletons and external FBX/USD skeletons
without creating a separate viewport system.

Decision:
Keep Wind Preview as a separate PySide6 dialog on the shared viewport path, but
move the product contract toward a stack model: XML Generator Groups or Auto
Hierarchy provide the base groups, and manual override layers sit above them.
Higher layers win, empty manual groups are ignored, and final non-empty visible
groups are compacted bottom-up before Dynamic Wind JSON export. Manual edits are
stored as explicit child-joint token assignments, so visual colors and exported
JSON describe the same final result.

Reasoning:
This keeps the XML-derived path, the independent skeleton analyzer, and manual
operator correction in one deterministic model. It also supports non-SpeedTree
trees from Houdini, Blender, or other DCC tools by loading external skeletons
without mesh geometry and running Auto Hierarchy before optional manual fixes.

Consequences:
Group order is bottom-up like layer stacks: group 0/trunks are the bottom layer
and `+` inserts new manual groups above all existing layers. Auto Hierarchy must
not read XML generator labels; it uses SpeedTree/file joint ordering plus the
explicit `Continue line` policy visible only in Auto mode. Missing coverage,
duplicate external joint names, missing skeletons, missing or unreadable joint
transforms, and unavailable import backends fail loudly. Wind Preview JSON
export uses the existing Dynamic Wind JSON schema and output-path derivation
rather than introducing a new schema.
The right panel uses one global settings scroll; Layers is the only nested
scroll, resizes vertically through a local handle even when the global scrollbar
is visible, and owns compact `+`/`-` manual-layer actions. Wind Preview opens
taller than the shared preview default and defaults the right panel to the
midpoint between its minimum and maximum width. Undo/redo remain shortcut-only
and are surfaced through viewport shortcut hints instead of visible panel
buttons. Text `.usda` and ASCII `.usd` external skeleton loading must not depend
on `pxr`; when OpenUSD Python is unavailable, Wind Preview reads text Skeleton
blocks directly. Multiple USD Skeleton prims require an explicit operator
choice through the Skeleton dropdown. The loader must not choose by largest
joint count, prim order, or name. Binary `.usd`/`.usdc` stay behind the `pxr`
requirement.
The SpeedTree worker result must not contain the full CanonicalTreeModel beside
the already-built viewport scene. It carries only the skeleton, Dynamic Wind
data, and compact Base Mesh scene buffers. Repeated Parts are omitted entirely:
Wind Preview inspects the skeleton, and repeated geometry adds visual noise
without changing grouping or JSON. Grouping edits recolor those existing draw
calls and replace the bone overlay. A restored valid XML
path triggers the same Wind-group refresh as the manual button after startup.
If Preview is requested before that refresh finishes, queue it instead of
normalizing the same large XML concurrently in the GUI and preview worker. A
native Wind Preview process crash receives one clean-process retry; a second
failure remains fail-loud. All worker environments enable Python faulthandler
so native failures can populate the existing stderr crash context.
Detailed V2 behavior lives in `docs/wind_viewport_working_plan.md`.

Related files:
- `src/xml_to_usda/wind_preview_service.py`
- `src/xml_to_usda/wind_viewport_scene.py`
- `src/xml_to_usda/qt_ui/wind_preview.py`
- `tests/test_wind_viewport_scene.py`

## Decision: Preview dialogs share one viewport system

Status: Active

Context:
Proxy Preview, Fracture Preview, Part Prototype Preview, and Wind Preview all
render inspection geometry through the Qt/OpenGL viewport. A crash in one
preview is often a viewport lifecycle, upload, camera, or overlay problem that
can affect other previews later.

Decision:
Keep `MatcapViewport` and `ViewportScene` as the shared viewport seam. Preview
mode dialogs may differ in controls, source requests, worker strategy, and
Qt-free scene adapters, but they should not invent separate viewport behavior
for rendering, OpenGL upload, camera fit, bone overlay, picking, static-scene
precompute, or trace milestones. When a viewport fix is generally useful, add a
public `MatcapViewport` interface and route the mode dialog through it.

Reasoning:
The working previews are evidence that the shared viewport system is the safer
contract. A mode-specific rendering path hides native crash fixes in one dialog
and makes future previews drift. A shared interface keeps leverage high: one
fix improves every preview that uses the same upload and overlay path.

Consequences:
Do not import private viewport helpers from mode dialogs to solve a rendering
or upload problem. Do not add a second OpenGL widget for a new preview unless
the existing viewport cannot represent the required primitive after a measured
attempt to extend it. Heavy static scenes should use the shared
`MatcapViewport.set_scene(..., precompute_static=True)` path or a documented
public equivalent. Visual-only selection, highlight, or visibility changes
should not rebuild or re-upload static mesh buffers; add a small public
viewport update method instead. Scene replacement marks GPU buffers dirty and
lets the next `paintGL` upload them with Qt's context current; result callbacks
must not force eager uploads with `makeCurrent()`/`doneCurrent()`. Every viewport window should show active
shortcuts briefly in the bottom-right corner as small translucent text, so
mode-specific interactions remain discoverable without adding instructional UI
blocks. Packaged smoke should cover any new high-risk viewport path.

Related files:
- `src/xml_to_usda/qt_ui/viewport.py`
- `src/xml_to_usda/viewport_scene.py`
- `src/xml_to_usda/qt_ui/wind_preview.py`
- `src/xml_to_usda/qt_ui/fracture_preview.py`
- `src/xml_to_usda/qt_ui/proxy_preview.py`
- `src/xml_to_usda/qt_ui/part_preview.py`
- `src/xml_to_usda/qt_ui/smoke.py`

## Decision: Qt UI polish uses direct widget screenshots before packaging

Status: Active

Context:
Small visual changes in PySide6 dialogs were previously validated mostly by
building the packaged app, then having the operator open the UI manually. That
loop is slow and misses obvious layout issues until late.

Decision:
For UI layout/style work, first render the target Qt widget or dialog directly
from `.venv310`, call `show()`, `QApplication.processEvents()`, then save a
PNG with `widget.grab().save(...)`. Inspect that image before running the
slower packaged gate. Use this especially for right panels, preview dialogs,
button density, scroll behavior, dropdown styling, and text overlap.

Reasoning:
This is the shortest reliable feedback loop for visual regressions. It keeps
design iteration local to the changed widget and lets the agent see the same
layout problems the operator would see, without waiting for PyInstaller.

Consequences:
Direct screenshots do not replace tests or packaged high-risk smoke. They are
a preflight visual check before final validation. Prefer grabbing the smallest
useful widget, for example `dialog.settings_panel.grab()`, so the screenshot is
easy to inspect. Delete temporary screenshots after use unless the user asks to
keep them.

Related files:
- `src/xml_to_usda/qt_ui/`
- `tests/test_qt_wind_preview_dialog.py`
- `docs/wiki/architecture.md`

## Decision: Main-shell status is one telemetry-backed card

Status: Active

Context:
Two narrow runtime/material cards and free text above the main tabs split one
workflow across three visual areas and placed transient text directly over the
blurred background.

Decision:
Use one opaque, internally scrollable `ProgramStatusCard` for current state,
message, progress, conversion stages, and the compact source/configuration
summary. Map the existing conversion phases to Prepare, Normalize XML, Resolve
Geometry, Resolve Materials, and Write USDA; keep FBX detail in the current
message. Other background jobs use the same card without a staged list. Success
resets after five seconds; error and cancellation persist until the next action.
Use semantic terminal colors: green for success/completed stages and red for
errors. Working indicators rotate inside fixed-width marker columns so status
text never shifts. Compact long paths to their basename in the card while
retaining the complete value in the tooltip and log.

Consequences:
Backend telemetry and request models remain unchanged. Full material paths and
runtime choices stay in their owning controls and are copied to the conversion-
start log. The legacy `MainWindow.status_label` name remains an alias to the
card's primary message label.

Related files:
- `src/xml_to_usda/qt_ui/status_card.py`
- `src/xml_to_usda/qt_ui/background_jobs.py`
- `src/xml_to_usda/qt_ui/window.py`

## Decision: Fracture Geometry is one deep preview/export module

Status: Active

Context:
The former Fracture path assigned whole faces by centroid and generated caps
from ownership boundaries. Preview, export, collision, Repeated Part ownership,
and cap behavior could not remain exact through that interface.

Decision:
Keep planning in `fracture_service.py`. Flat cuts use the shared
`prepare_fracture_geometry(...)` contract; Detailed Cuts use the connectivity-
first Manifold backend in `boolean_fracture_prototype.py` and adapt its result
to that same geometry contract. Preview simplifies only after this boundary;
export and collision consume the same final per-piece mesh.

Consequences:
Turning Detailed Cuts off preserves the fast flat path. Repeated Parts remain
with the Fracture Piece determined by their skeleton binding/source bone; their
topology and prototype bounds do not veto cuts. Detailed mode closes each
connectivity-selected source shell temporarily, splits it with a closed
triangular-lattice cutter, removes temporary closures by provenance, transfers
source attributes, and keeps the cutter-derived matching caps. Generate Caps is
therefore forced on in Detailed mode. Displacement is one-sided toward the
detached child and is limited before the next fork, terminal bone, or configured
sharp bend. `Stump Piece` plans one cut per independent stem, including
multi-stem sources. Collision continues to use the existing convex/sphere/
capsule builders on the final Boolean piece mesh.

Fracture Preview uses one persistent crash-isolated worker for sequential
settings changes. This preserves process isolation while avoiding packaged
Python startup and source-cache reconstruction on every slider release. Rapid
changes coalesce behind current work instead of terminating the server. Explicit
cancel terminates the server; the next request starts a clean one. Cyclic GC is
disabled only for this bounded worker lifetime because its payloads are
reference-counted and a packaged access violation was observed during cyclic
collection while rebuilding cached mesh objects. Viewport triangle packing is
NumPy-vectorized rather than a per-vertex Python loop.

Related files:
- `src/xml_to_usda/fracture_geometry.py`
- `src/xml_to_usda/boolean_fracture_prototype.py`
- `src/xml_to_usda/fracture_preview_service.py`
- `src/xml_to_usda/fracture_export_service.py`

## Decision: Proxy base-mesh vertex fusion is opt-in and post-prune

Status: Active

Context:
Some SpeedTree generators emit a visually continuous trunk as separate,
near-coincident base-mesh sections. QEM preserves their disconnected seams and
can saturate above its requested triangle budget.

Decision:
Proxy Mesh exposes `Fuse Base Mesh Vertices`, disabled by default. When enabled,
the density-field path deterministically welds base-mesh points within `0.001`
stage meters and removes faces made degenerate by the weld. Existing
connected-component pruning runs first, so welding does not change which small
branches that control removes. QEM runs after the weld.

Consequences:
Existing trees retain their previous output unless the operator enables the
option. The fixed one-millimeter threshold is intentionally narrow and is not a
general remeshing or Boolean-union operation.

Related files:
- `src/xml_to_usda/proxy_mesh_service.py`
- `src/xml_to_usda/qt_ui/proxy_preview.py`
- `src/xml_to_usda/settings_service.py`

## Decision: Proxy collision fits Fracturing stem axes

Status: Active

Proxy Mesh collision defaults to one enabled Box fitted from the lower `0.5`
of the same base-mesh-owned stem axes used by Fracturing. Width `1.0` is the
largest transverse local AABB span of vertices owned by the selected stem
segments. Each axis stops when the initial stem generator level changes, so a
descendant side branch cannot inflate the collision height or width. Height and
Width zero deliberately omit collision.

Multi-stem sources default to one combined PCA-fitted primitive. `One Primitive
per Stem` instead emits one independently fitted `UBX_` or `UCP_` guide sibling
per stem. Per-stem width excludes vertices owned by the first stem joint when
more than one stem exists: observed SpeedTree skin binding assigns all base
rings to one shared root, so using that ownership measures the distance between
stems instead of one diameter. The next selected stem joints retain an
unambiguous trunk cross-section. Combined and single-stem fitting keep their
existing root coverage. Collision transforms are baked into mesh points because
UE ignored collision prim transforms in the validated Fracture path. Do not
author USD Physics APIs on these siblings.

Box and Capsule import as simple collision on the Proxy Static Mesh was manually
confirmed in UE 5.7.x on 2026-08-08. Proxy Preview retains the fitted collision
when hidden, so `Generate Collision` On/Off never regenerates Proxy Mesh. Other
collision fit changes rebuild locally from a compact stem-only source retained
with the preview result; they do not start a worker or reload the full Proxy
Source Projection. The simplified viewport mesh is not used because it has no
per-stem skin ownership. Guide collision does not contribute to camera/grid
bounds; the grid stays at the tree pivot.

Related files:
- `src/xml_to_usda/proxy_collision.py`
- `src/xml_to_usda/collision_primitives.py`
- `src/xml_to_usda/proxy_source_projection.py`
- `src/xml_to_usda/proxy_mesh_service.py`

## Decision: Proxy UI exposes one density method with resolution up to 512

Status: Active

Density Field is the only supported operator-facing Proxy Mesh method. The
Method control is hidden and UI requests always emit `density_field`; the
internal `instance_bounds` path remains only as a diagnostic baseline. Density
Resolution accepts `1..512`, and imported larger values clamp to 512.

High-resolution occupancy uses one bounded dense NumPy boolean grid. Prepared
ellipsoid kernels are evaluated through their mathematically equivalent
quadratic form, the surface builder processes only boundary cells, and the QEM
adapter accepts the resulting triangles without a Python face loop. This keeps
the existing extraction and simplification contract rather than introducing a
second high-resolution algorithm.

On `SkeletalAssemblyTest_03_28mil.xml`, the observed full resolution-512 path
improved from 83.1 seconds before this work to a 23.2-second median across three
fresh worker-equivalent processes. All three produced the same mesh SHA-256.
Big Spruce resolution 64 and 256 retained their previous byte-identical mesh
hashes. QEM remains the dominant cost at 512; higher QEM aggressiveness and a
lossless prepass were measured and rejected because they did not improve total
time without changing quality.

The main file action row contains Convert to USDA and Generate Wind JSON only.
Proxy Preview owns its export action in a bottom `Generate Proxy` block. The
displayed path defaults to `<main Output stem>_proxy.usda`, remains editable,
and is treated as the exact destination rather than being suffixed a second
time. If current preview settings match the cached mesh, export writes that
mesh; otherwise the existing isolated Proxy worker generates it.

Related files:
- `src/xml_to_usda/proxy_mesh_service.py`
- `src/xml_to_usda/qem_simplification.py`
- `src/xml_to_usda/qt_ui/proxy_preview.py`
- `src/xml_to_usda/settings_service.py`

Proxy collision guides use a brighter cyan tint with opacity `0.30` in Proxy
Preview. This is a 20% opacity increase over the former `0.25`; the brighter
tint also strengthens the existing rim/Fresnel contribution without adding a
separate shader path.

## Decision: Mouse wheel does not edit UI parameters

Status: Active

The application-level Qt event filter consumes wheel input over parameter
sliders, spin boxes, combo boxes, and dials. It forwards vertical movement to
the nearest scroll area when one exists. Scroll bars and 3D viewports retain
their native wheel behavior. This prevents accidental parameter regeneration
while browsing any main or preview settings panel.

Related files:
- `src/xml_to_usda/qt_ui/window.py`
- `tests/test_qt_parameter_wheel.py`

## Decision: Local +X and Skinning Quality are the default skeleton contract

Status: Active

Every normalized bone frame points local +X from `Bone.Start` to `Bone.End`.
Child frames project the parent Y axis onto the new perpendicular plane to
limit chain twist, and SkelAnimation authors the matching local rest rotations.
UE 5.7 tests on fern and spruce assets confirmed that identity local rotations
were incorrect: branches on opposite sides of the trunk bent in opposite wind
directions. +X frames make them bend consistently with the wind, so this is now
the default contract without a UI control or filename suffix.

If an older source omits Bone.End, normalization deterministically infers the
direction from the parent segment or a root child and records a warning. An
isolated bone with no usable direction retains its source frame and warns.

`Skinning Quality` is a discrete Wind-panel setting and the single conversion
contract for skeletal influence width. Quality 1 is the default and preserves
normalized rigid bindings at the lowest runtime cost. Quality 2 uses a two-weight child attachment
collar: the child base inherits the parent surface's `grandparent + parent`
mixture, reaches rigid parent over the first 20% of the child segment, then
transitions `parent -> child`. Qualities 3 and 4 recursively inherit the
parent's deformation vector at child attachments and deterministically clamp
and normalize it to their selected width. The setting does not alter the
output filename.

Repeated Parts stay rigid at quality 1 and use the established two-weight
parent/current path at quality 2. At qualities 3 and 4, each rigid Part receives
the same recursively inherited distribution that Base Mesh has at the instance
position, clamped and padded to the selected width. Persisted settings store one integer `skinning_quality`.
Legacy `dual_skinning` and `attachment_skinning_mode` fields are accepted only
at the JSON loading seam and migrated to qualities 1-4.

UE 5.8 source inspection establishes that assembly builder ignores zero and
nearly-zero weights, normalizes, quantizes, sorts, and stores the actual
non-zero influence count per Assembly Part. Therefore fixed-width USD padding
does not add a runtime GPU iteration. For Base Mesh Nanite skinning, the builder
reads per-vertex weights until the first zero and stores the maximum active
influence count per cluster; non-zero weights must precede zero padding. One
active high-width vertex raises the cost of its cluster, not necessarily the
whole mesh. Treat matching UE 5.7.x behavior as pending import/runtime validation.

The base-mesh implementation uses bounded NumPy chunks behind this interface;
Repeated Part instances retain their object-level scalar path. Validation uses
the same bounded strategy while preserving first-invalid-vertex order and the
joint-before-weight diagnostic priority at one vertex. On Big Spruce, the full
operations improved from 0.2824 s to 0.0921 s for the original two-weight path and from
0.1227 s to 0.0267 s for validation. The complete cold source load improved by
about 6.7%; the authored 14,339,986-character USDA remained byte-identical.

Related files:
- `src/xml_to_usda/skeleton_processing.py`
- `src/xml_to_usda/usda_authoring.py`
- `src/xml_to_usda/qt_ui/panels.py`

## Decision: Skeleton and influence invariants are mandatory export gates

Status: Active

Source validation rejects duplicate joints, missing parents, hierarchy cycles,
non-finite or non-rigid bases, local +X misalignment, zero-length bones, and
rest transforms that do not reconstruct absolute bind transforms. Multi-root
skeletons are valid. A transported-frame roll above 75 degrees is a warning,
not an error. Missing endpoints remain warnings because older inputs may need
the documented hierarchy-based direction inference.

Skeletal Assembly authoring validates base-mesh and repeated-Part influence
widths, array shapes, joint references, finite `[0, 1]` weights, and per-element
weight sums. Base meshes and Repeated Parts accept one to four influences and
must share the selected Skinning Quality width. Diagnostics identify the exact bone, vertex,
or Part where possible. Errors stop USDA authoring through the existing gate;
warnings use the existing diagnostics/status/log path.

Related files:
- `src/xml_to_usda/skeleton_processing.py`
- `src/xml_to_usda/source_validation.py`
- `src/xml_to_usda/authoring_validation.py`

## Decision: Missing intermediate bone Generator groups warn but do not block export

Status: Active

Source Discovery detects numeric gaps between the minimum and maximum
`Generator` levels authored on XML bones. A gap such as `Group_0`, `Group_1`,
`Group_3` produces a modal GUI warning naming `Group_2`, because later bones may
be attached directly to an earlier group and create long, animation-sensitive
connections. The dialog requires `OK`, but conversion remains available because
an operator may have authored the gap intentionally. The main Program Status
card also keeps a compact yellow warning visible until a gap-free XML is
selected. Object names are not used for this check; they do not reliably
describe bone assignment.

Related files:
- `src/xml_to_usda/source_analysis.py`
- `src/xml_to_usda/discovery_service.py`
- `src/xml_to_usda/qt_ui/window.py`

## Decision: Persist Output together with its Input

Status: Active

The main shell persists the exact Output USDA path currently shown and records
which Input XML it belongs to. Startup restores that pair only when the Input
matches; missing or legacy-unpaired output state is regenerated beside the
Input with the `.usda` suffix. This preserves explicit custom output names
without allowing an older tree's output path to leak into a newer input.

Related files:
- `src/xml_to_usda/qt_ui/operator_state.py`
- `src/xml_to_usda/qt_ui/window.py`
- `src/xml_to_usda/settings_service.py`
