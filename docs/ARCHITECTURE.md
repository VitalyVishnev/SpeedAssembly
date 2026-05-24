# Architecture

## Role

This document is the architecture-review entry point for module depth, locality,
interfaces, seams, and adapters.

It does not redefine the UE importer contract. For USDA structure and
source-of-truth order, use `AGENTS.md`, `docs/ue_import_contract.md`,
`docs/speedtree_mapping.md`, and `docs/workflow_status.md` first.

## Architectural intent

The project is an engine-validated reverse-engineering pipeline. Architecture is
useful only when it improves one of these outcomes:

- verified UE import behavior is easier to preserve, especially for the primary
  `skeletal_assembly` path
- source XML interpretation is easier to inspect and test
- transform, material, prototype, and binding rules gain locality
- large conversions remain diagnosable and stable
- the supported UI shell reuses the same conversion contracts

`static_assembly` is a supported secondary export mode. It may share normalized
source data and authoring infrastructure, but it must not force the primary
skeletal path to lose locality around skeleton, binding, or part-skeleton rules.

Avoid refactors that make the code tidier while moving importer facts,
transform policy, or runtime failure handling farther from the tests that prove
them.

## Layer map

### Domain layer

Owns deterministic conversion concepts and rules.

Primary modules:

- `models.py`
- `xml_reader.py`
- `normalizer.py`
- `source_transform.py`
- `skeleton_rules.py`
- `naming.py`
- `prototype_keys.py`
- `payload_partition.py`
- `geometry_buffers.py`
- `material_resolver.py`
- `dynamic_wind.py`
- `source_validation.py`
- `resolution_validation.py`
- `authoring_validation.py`
- `validation_common.py`
- `validator.py`

Expected interface shape:

- typed values in, typed values out
- no widget state
- no launcher/package conditionals
- no direct subprocess ownership
- failures explain the missing assumption instead of inventing fallback USDA

### Application layer

Owns use-case orchestration and caller intent translation.

Primary modules:

- `conversion_service.py`
- `discovery_service.py`
- `settings_service.py`
- `wind_service.py`
- `conversion_orchestrator.py`
- `canonical_loader.py`
- `assembly_resolution.py`
- `prototype_resolution.py`
- `material_assignment_resolution.py`
- `source_analysis.py`

Expected interface shape:

- convert GUI/CLI semantics into stable request models
- validate operator-facing configuration before runtime work starts
- keep UI widgets and Autodesk/OS details behind adapters

### Infrastructure layer

Owns filesystem, process, FBX, runtime, and USDA-writing details.

Primary modules:

- `usda_authoring.py`
- `usda_writer.py`
- `ue_schema.py`
- `fbx_adapter.py`
- `fbx_import_supervisor.py`
- `fbx_worker_subprocess.py`
- `fbx_worker_entry.py`
- `conversion_process.py`
- `runtime_paths.py`
- `output_resolution.py`
- `job_control.py`
- `prototype_sources.py`
- `wind_pipeline.py`

Expected interface shape:

- isolate environment-specific behavior
- keep runtime failure modes explicit
- preserve deterministic output and atomic file writes where applicable
- avoid leaking FBX SDK details into domain or UI modules

### UI layer

Owns operator interaction as adapters over application interfaces.

Primary modules:

- `qt_ui/`
- `gui.py`
- `gui_formatters.py`

Expected interface shape:

- collect operator state
- call application modules
- render results and diagnostics
- avoid owning conversion semantics

## Stable public facades

These modules are public facades and should stay thin:

- `pipeline.py`
  Conversion and inspection facade for CLI glue, tests, and subprocess workers.
- `usda_writer.py`
  Public writer facade over the shared authoring implementation.

Adding behavior to a facade is suspicious unless the behavior protects the
facade's interface. Prefer placing rules behind the focused module that owns the
domain concept.

## Important seams and adapters

- Conversion launch seam:
  `conversion_service.prepare_conversion_plan` produces one `ConversionRequest`
  used by UI and CLI callers.
- Export mode seam:
  `ConversionMode` selects the authoring contract. `skeletal_assembly` remains
  the primary contract; `static_assembly` is supported but omits skeleton and
  binding semantics by design.
- Canonical model seam:
  `canonical_loader.load_source_tree_model` produces the source-normalized
  `CanonicalTreeModel`. `canonical_loader.load_canonical_model` returns the
  resolved authoring model projection for callers that need the authored view.
- Resolved assembly model seam:
  `assembly_resolution.resolve_assembly_model` combines `CanonicalTreeModel`
  source facts with operator intent into `ResolvedAssemblyModel`. Prototype
  source resolution and material assignment resolution sit behind this seam;
  source normalization should not apply request-specific behavior.
- Attachment-to-binding seam:
  Source `Attachment` facts may come from SpeedTree fields such as `BoneID`.
  Skeletal exports resolve them into authored `Skeletal Binding`; static exports
  do not author skeletal binding arrays.
- Material assignment seam:
  `Source Material` facts come from XML, vertex colors, or imported payload
  slots. Resolution turns them into `Resolved Material Assignment` through
  policy and operator overrides. USDA writing emits `Authored Material Binding`.
  Avoid treating source material ids as authored semantic roles.
- Naming seam:
  Keep `Source Name`, `Output Stem`, `Prim Name`, `Authored Asset Name`, and
  `Unreal Asset Path` distinct. Do not infer skeleton or base asset naming from
  source filenames or first-bone names unless a verified contract says so.
- Transform seam:
  Keep `Source Space`, `Stage Space`, `Prototype Space`, `Attachment Space`,
  `Instance Transform`, and `Authored PointInstancer Transform` distinct.
  Transform fixes should preserve explicit axis/basis conversion, pivot rules,
  and per-instance scale semantics instead of hiding errors with corrective
  offsets.
- Runtime execution seam:
  `ConversionRequest` describes caller intent. `Runtime Job` describes one
  executing conversion run with telemetry, cleanup, workers, helpers, and a Job
  Workspace. Launcher/dev and packaged executable behavior are Runtime Adapters
  and must preserve the same conversion semantics.
- Operator state seam:
  `Operator State` is the current UI selection surface. `Persisted Operator
  Settings` restore that state across sessions or input XML files. `UI Shell
  State` belongs to the visual shell and must not become conversion Operator
  Intent.
- Validation seams:
  Source validation checks source facts before operator intent. Resolution
  validation checks source facts plus operator intent. Authoring validation
  checks the USDA contract that will be written. `source_validation.py`,
  `resolution_validation.py`, and `authoring_validation.py` own the stage rules;
  `validator.py` is a public facade over staged validation modules.
- Prototype source seam:
  XML mesh, Unreal asset reference, and FBX file source modes are adapters for
  Resolved Prototype payload selection. `prototype_resolution.py` owns matching
  and projection; `prototype_sources.py` owns FBX loading infrastructure.
- FBX backend seam:
  Autodesk FBX SDK and JSON geometry test backend satisfy the same FBX geometry
  loading role.
- UI shell seam:
  The supported Qt shell should remain an adapter over application modules,
  Operator State, Persisted Operator Settings, and UI Shell State. The retired
  Tk implementation has been removed; `gui.py` must stay a hard-failing
  retired entrypoint, not a second UI shell.
- USDA writing seam:
  `ResolvedAssemblyModel` is the preferred input for USDA writing. Text and
  streaming sinks share the same authoring context.

## Deletion-test warnings

Treat these modules as likely deep until proven otherwise:

- `material_resolver.py`
  Concentrates source material roles, explicit material contracts, FBX material
  modes, and failure behavior.
- `normalizer.py`
  Concentrates observed XML interpretation into the Canonical Tree Model.
- `conversion_service.py`
  Concentrates UI/CLI semantic normalization and request validation.
- `fbx_import_supervisor.py`
  Concentrates packaged/launcher helper behavior, crash recovery, and helper
  count fallback.
- `usda_authoring.py`
  Concentrates importer-facing authoring layout and streaming writer behavior.

Deleting or bypassing these modules would probably spread high-risk knowledge
across callers.

## Architecture review checklist

For each proposed deepening opportunity, answer:

1. Which module interface is shallow or leaking?
2. Which callers currently need to know too much?
3. What behavior would move behind the interface?
4. Which tests should exercise the new interface?
5. Does the change preserve the UE validation loop and `vault` comparison path?
6. Does the change contradict `docs/DECISIONS.md`?
7. Is the change mixing source facts with operator intent before the resolved
   assembly model seam?
8. Which validation stage owns the new invariant: source, resolution, or
   authoring?
9. Is the rule about source Attachment, or about authored Skeletal Binding?
10. Is the rule about Source Material, Resolved Material Assignment, or
    Authored Material Binding?
11. Which naming concept is being changed: Source Name, Output Stem, Prim Name,
    Authored Asset Name, or Unreal Asset Path?
12. Which transform space is being changed: Source Space, Stage Space,
    Prototype Space, Attachment Space, Instance Transform, or Authored
    PointInstancer Transform?
13. Is the rule about caller intent, Runtime Job execution, Job Workspace
    lifecycle, Conversion Worker behavior, FBX Helper behavior, or Runtime
    Adapter note?
14. Is the state Operator State, Persisted Operator Settings, UI Shell State, or
    actual conversion Operator Intent?

Do not propose a new seam unless the second adapter is real: another runtime
adapter, UI shell, test backend, or output mode that already exists or is
immediately planned.
