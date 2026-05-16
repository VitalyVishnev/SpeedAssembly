# Project Map

## Role

This is the navigation entry point for architecture reviews and AI-assisted
codebase exploration.

It does not override the importer-facing contract. For product intent and
verified UE behavior, read documents in this order:

1. `AGENTS.md`
2. `docs/ue_import_contract.md`
3. `docs/speedtree_mapping.md`
4. `docs/workflow_status.md`
5. `docs/local-python-environment.md`

Use this file to find the right module, test surface, and reference material
before proposing architectural changes.

## Architecture review inputs

- `docs/GLOSSARY.md`
  Project domain vocabulary for architecture suggestions.
- `docs/ARCHITECTURE.md`
  Current module map, interfaces, seams, adapters, and review rules.
- `docs/DECISIONS.md`
  Decisions that should not be re-litigated without new evidence.
- `docs/developer_architecture.md`
  Historical developer map kept as a compatibility pointer.

## Source of truth roots

- `vault/`
  Primary comparison source for UE schema files, importer source, known-good
  examples, and reverse-engineering notes.
- `samples/`
  Controlled SpeedTree samples and expected authored outputs.
- `tests/`
  Regression surface for parser, normalization, material policy, validation,
  GUI/application contracts, runtime behavior, and writer behavior.

## Code map

### Domain modules

Pure conversion concepts and rules. These modules should stay deterministic and
free of UI, process, launcher, and package-build behavior.

- `src/xml_to_usda/models.py`
- `src/xml_to_usda/normalizer.py`
- `src/xml_to_usda/material_resolver.py`
- `src/xml_to_usda/source_validation.py`
- `src/xml_to_usda/resolution_validation.py`
- `src/xml_to_usda/authoring_validation.py`
- `src/xml_to_usda/validation_common.py`
- `src/xml_to_usda/validator.py`
- `src/xml_to_usda/skeleton_rules.py`
- `src/xml_to_usda/source_transform.py`
- `src/xml_to_usda/naming.py`
- `src/xml_to_usda/prototype_keys.py`
- `src/xml_to_usda/payload_partition.py`
- `src/xml_to_usda/geometry_buffers.py`

### Application modules

Use-case modules that translate caller intent into stable domain/runtime
contracts.

- `src/xml_to_usda/conversion_service.py`
- `src/xml_to_usda/discovery_service.py`
- `src/xml_to_usda/settings_service.py`
- `src/xml_to_usda/wind_service.py`
- `src/xml_to_usda/conversion_orchestrator.py`
- `src/xml_to_usda/canonical_loader.py`
- `src/xml_to_usda/assembly_resolution.py`
- `src/xml_to_usda/prototype_resolution.py`
- `src/xml_to_usda/material_assignment_resolution.py`
- `src/xml_to_usda/source_analysis.py`

### Infrastructure modules

Filesystem, USDA writing, FBX import, subprocess, runtime workspace, and
environment-facing implementation details.

- `src/xml_to_usda/usda_authoring.py`
- `src/xml_to_usda/usda_writer.py`
- `src/xml_to_usda/fbx_adapter.py`
- `src/xml_to_usda/fbx_import_supervisor.py`
- `src/xml_to_usda/fbx_worker_subprocess.py`
- `src/xml_to_usda/conversion_process.py`
- `src/xml_to_usda/output_resolution.py`
- `src/xml_to_usda/runtime_paths.py`
- `src/xml_to_usda/job_control.py`
- `src/xml_to_usda/prototype_sources.py`
- `src/xml_to_usda/wind_pipeline.py`

### UI modules

Operator-facing adapters over application contracts.

- `src/xml_to_usda/qt_ui/`
- `src/xml_to_usda/gui.py`
- `src/xml_to_usda/gui_app.py`
- `src/xml_to_usda/gui_models.py`
- `src/xml_to_usda/gui_*_panel.py`
- `src/xml_to_usda/gui_persistence.py`
- `src/xml_to_usda/gui_background_jobs.py`

### Public facades

Compatibility surfaces. They should remain thin.

- `src/xml_to_usda/pipeline.py`
- `src/xml_to_usda/usda_writer.py`
- `src/xml_to_usda/gui.py`

## High-value exploration paths

- Conversion path:
  `cli.py` or UI -> `conversion_service.py` -> `conversion_orchestrator.py` ->
  `canonical_loader.py` -> `normalizer.py` -> `material_resolver.py` ->
  `assembly_resolution.py` -> staged validation -> `usda_writer.py` ->
  `usda_authoring.py`
- Prototype source path:
  `discovery_service.py` -> `assembly_resolution.py` ->
  `prototype_resolution.py` -> `prototype_sources.py` ->
  `fbx_import_supervisor.py` or `fbx_adapter.py` ->
  `material_assignment_resolution.py` -> `material_resolver.py` ->
  `usda_authoring.py`
- Wind path:
  `wind_service.py` -> `wind_pipeline.py` -> `dynamic_wind.py`
- Qt operator path:
  `qt_ui/window.py` and `qt_ui/panels.py` -> `qt_ui/operator_state.py` ->
  `settings_service.py` and application services

## Review discipline

Before suggesting a new seam, verify whether there are at least two real
adapters or one real adapter plus a concrete regression-test adapter. Otherwise
treat the seam as hypothetical.

Before suggesting a module deletion, apply the deletion test: if deleting it
would spread importer contract knowledge, transform policy, material policy, or
runtime failure handling across callers, the module is probably earning its
keep.
