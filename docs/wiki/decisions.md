# Decisions

This page stores active project contracts. Rejected or superseded approaches live in [experiments.md](experiments.md). Current limitations and bugs live in [known-bugs.md](known-bugs.md).

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

## Decision: Large GUI jobs run outside the UI process

Status: Active

Context:
Heavy conversions were unstable when too much FBX or USDA work happened inside the UI shell.

Decision:
Run large conversions in a dedicated worker subprocess and keep the UI shell out of the heavy native path.

Reasoning:
Process isolation keeps the interface responsive and contains native failures.

Consequences:
Packaged smoke and stability gates stay required for the worker path.

Related files:
- `docs/raw/workflow_status.md`
- `docs/raw/troubleshooting.md`

## Decision: Preview stability must not redefine mesh quality contracts

Status: Active

Context:
Proxy Mesh and Fracture Preview needed crash containment without changing the meaning of the exported geometry.

Decision:
Keep QEM-based proxy simplification and file-first worker completion rules intact.

Reasoning:
Cheaper diagnostic paths are acceptable only when they do not weaken the exported topology contract.

Consequences:
Face sampling stays rejected for proxy simplification, and worker polling must drain result/error files before treating a stopped worker as a crash.

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
