# Developer Architecture Map

## Role

This document explains the post-refactor code layout for engineers working on
the converter after Stage 6.

It does not override:

1. `AGENTS.md`
2. `docs/ue_import_contract.md`
3. `docs/speedtree_mapping.md`
4. `docs/workflow_status.md`

Those remain the normative documents for importer-facing behavior and project
intent. This file is for developer orientation and boundary clarity.

## Layer model

### Domain layer

Pure conversion concepts, normalized tree structures, and business rules.

Representative modules:

- `src/xml_to_usda/models.py`
- `src/xml_to_usda/normalizer.py`
- `src/xml_to_usda/material_resolver.py`
- `src/xml_to_usda/skeleton_rules.py`
- `src/xml_to_usda/asset_paths.py`
- `src/xml_to_usda/prototype_keys.py`

Domain code should not depend on:

- Tkinter/UI modules
- subprocess/process-bridge code
- launcher/package-specific behavior

### Application layer

Typed use-case orchestration between callers and the domain/infrastructure
subsystems.

Representative modules:

- `src/xml_to_usda/conversion_service.py`
- `src/xml_to_usda/discovery_service.py`
- `src/xml_to_usda/settings_service.py`
- `src/xml_to_usda/wind_service.py`
- `src/xml_to_usda/conversion_orchestrator.py`
- `src/xml_to_usda/canonical_loader.py`
- `src/xml_to_usda/source_analysis.py`

Application code may coordinate domain and infrastructure concerns, but should
not become a widget layer or a direct Autodesk/OS/process implementation blob.

### Infrastructure layer

Filesystem, runtime, FBX backend, process management, output writing, and other
environment-facing implementation details.

Representative modules:

- `src/xml_to_usda/fbx_adapter.py`
- `src/xml_to_usda/runtime_paths.py`
- `src/xml_to_usda/conversion_process.py`
- `src/xml_to_usda/output_resolution.py`
- `src/xml_to_usda/job_control.py`
- `src/xml_to_usda/usda_authoring.py`
- `src/xml_to_usda/usda_writer.py`
- `src/xml_to_usda/wind_pipeline.py`
- `src/xml_to_usda/prototype_sources.py`

Infrastructure code may depend on runtime constraints and external SDK behavior,
but should not become the place where UI semantics or unrelated business policy
accumulate.

### UI layer

Thin UI adapters over application services and typed UI/controller state.

Representative modules:

- `src/xml_to_usda/qt_ui/`
- `src/xml_to_usda/gui.py`
- `src/xml_to_usda/gui_app.py`
- `src/xml_to_usda/gui_models.py`
- `src/xml_to_usda/gui_materials_panel.py`
- `src/xml_to_usda/gui_part_sources_panel.py`
- `src/xml_to_usda/gui_wind_panel.py`
- `src/xml_to_usda/gui_persistence.py`
- `src/xml_to_usda/gui_background_jobs.py`
- `src/xml_to_usda/gui_formatters.py`

UI code should not hold core conversion semantics. It should gather operator
state, call application services, and render results.

The repository now has two UI shells:

- the legacy Tk fallback under `src/xml_to_usda/gui*.py`
- the primary PySide6 shell under `src/xml_to_usda/qt_ui/`

Both shells must use the same application/runtime contracts instead of growing
their own conversion rules.

## Stable public facades

These modules are intentionally retained as compatibility surfaces:

- `src/xml_to_usda/pipeline.py`
  Stable conversion/inspection facade for tests, CLI glue, and older imports.
- `src/xml_to_usda/usda_writer.py`
  Stable public writer facade over the shared authoring engine.
- `src/xml_to_usda/gui.py`
  Legacy Tk GUI launch facade for fallback launcher/package/tests.

New internal work should prefer the focused implementation modules behind these
facades when the caller is inside the codebase and does not need the compatibility
surface.

## Retained compatibility paths

These compatibility paths are intentionally still present:

- legacy persisted GUI `material_policy` value `legacy_role_ids`
  Retained only as a settings-load migration into `source_material_roles`.
- legacy GUI settings payloads for `wind_group_settings`
  Retained so packaged or launcher upgrades do not discard saved operator state.
- legacy settings boolean `use_unreal_reference`
  Retained so older persisted part-source settings still reopen correctly.
- legacy `part_mesh_asset_paths` request bridge
  Retained so older request shapes still map into `PrototypeSourceConfig`.

These are not the preferred new authoring paths. They exist to preserve working
operator workflows and backward compatibility.

## Boundary rules

- UI should call application services, not raw XML/FBX internals.
- Public facades should stay thin and should not regrow business logic.
- Runtime strategy differences are allowed, but they must not create separate
  business systems.
- If a compatibility path remains, document why it exists and keep a regression
  test for it.
