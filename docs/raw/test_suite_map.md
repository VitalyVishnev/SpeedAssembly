# Test Suite Map

Snapshot date: `2026-05-30`

This is the current intent map for the active pytest suite. It is a routing
aid, not a rewrite plan.

## Intent Groups

| Intent | Current owner files | Notes |
| --- | --- | --- |
| Source normalization | `tests/test_source_analysis.py`, `tests/test_validation_stages.py`, `tests/test_pipeline.py`, `tests/test_normalizer.py` | XML inspection, canonical load, source transform facts, and source-validation boundaries. |
| Material resolution | `tests/test_assembly_resolution.py`, `tests/test_resolved_assembly_model.py`, `tests/test_udim_resolver.py`, `tests/test_udim_resolver_perf.py`, `tests/test_settings_service.py` | Source-material policy, explicit overrides, FBX material modes, and UDIM handling. |
| Assembly resolution | `tests/test_assembly_resolution.py`, `tests/test_resolved_assembly_model.py`, `tests/test_pipeline.py` | Canonical assembly model, repeated-part identity, and prototype projection. |
| USDA authoring | `tests/test_resolved_authoring.py`, `tests/test_usda_authoring_contract.py`, `tests/test_export_modes.py` | USDA text/file sinks, structural contract, binding rules, and UE schema shape. |
| USDA writing / sinks | `tests/test_usda_writer.py` | Render/write parity, authoring stream/file sinks, partial-file cleanup, and low-level writer edge cases. |
| FBX prototype sources | `tests/test_fbx_prototype_sources.py`, `tests/test_fbx_read_options.py`, `tests/test_fbx_payload_cache.py`, `tests/test_fbx_worker_entry.py` | Prototype source config loading, FBX replacement payloads, helper/supervisor integration, and source-specific IO. |
| Wind pipeline | `tests/test_wind_pipeline.py` | Dynamic wind group discovery, JSON generation, and legacy generator-level contracts. |
| Runtime Job / cleanup / FBX helper | `tests/test_conversion_process.py`, `tests/test_runtime_paths.py`, `tests/test_fbx_worker_entry.py`, `tests/test_fbx_read_options.py`, `tests/test_fbx_payload_cache.py`, `tests/test_release_bundle.py`, `tests/test_release_build.py`, `tests/test_output_resolution.py` | Worker process flow, partial-file cleanup, helper commands, cache behavior, and output selection. |
| Qt operator state and workflow | `tests/test_qt_ui_operator_state.py`, `tests/test_qt_ui_workflows.py`, `tests/test_qt_ui_persistence.py`, `tests/test_qt_ui_theme.py`, `tests/test_qt_ui_adjust_ui.py`, `tests/test_qt_ui_smoke.py`, `tests/test_qt_ui_helpers.py` | Operator intent, persistence, workflow wiring, and UI-facing behavior. |
| Compatibility / migration facades | `tests/test_compatibility_facades.py` | Legacy-shape coverage, retired Tk facade guard, and facade parity. Keep as explicit compatibility tests until step 4. |
| Deep modules | `tests/test_naming.py`, `tests/test_geometry_buffers.py`, `tests/test_conversion_orchestrator.py` | Direct contract coverage for low-level helpers that used to rely on indirect pipeline coverage. |

## Compatibility Tests

These tests exist only to protect caller stability or migration parity, not
current domain ownership:

- `tests/test_pipeline.py`
  - small smoke/regression coverage for source and assembly loading
- `tests/test_compatibility_facades.py`
  - explicit parity coverage for prebuilt source-node canonical loading, resolved authoring, resolved render/write, validator facade shape, public facade exports, and retired Tk facade behavior

## Reading Order

When touching tests, start from the file that owns the behavior category. Use
`tests/test_pipeline.py` only as an umbrella until the Step 2 split finishes.
