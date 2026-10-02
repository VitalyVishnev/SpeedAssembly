# Refactor Log

Current goal: deepen the converter, keep behavior/UI stable, and reduce tree conversion time.

## Wins

- `src/xml_to_usda/xml_reader.py`
  - Added `SourceXmlAnalysis` and `SourceNodeIndex`.
  - `analyze_xml()` now feeds both the report and the reusable source node index.
  - Combined object inspection into one pass for hierarchy plus leaf binding stats.
  - Added `slots=True` to the tiny analysis wrapper dataclasses.
- `src/xml_to_usda/canonical_loader.py`
  - Reuses `analyze_xml()` so source inspection and canonical loading share one analysis pass.
- `src/xml_to_usda/source_analysis.py`
  - Reuses the same shared analysis path.
- `src/xml_to_usda/source_transform.py`
  - `build_source_transform()` can reuse precollected mesh nodes instead of rescanning XML.
  - `bounds_to_stage()` now uses direct axis-aware min/max math for the known up-axis cases instead of building 8 corners first.
  - `point_components_to_stage()` and `points_components_to_stage()` now skip `* 1.0` work on the common meter-scale path.
- `src/xml_to_usda/normalizer.py`
  - Restored the fast-path UV authoring branch for the common valid-index case.
  - Collapsed the common face-varying UV path to one validation/build pass instead of a separate `all(...)` precheck.
  - Added a direct `range` fast path in face-varying UV authoring.
  - Switched packed point and spine conversion to the new batch point-transform helper.
  - Switched `LeafReferences` and `Spine` payload parsing to one direct child scan instead of repeated `findtext()` calls.
  - Gave `_read_float_list()` and `_read_int_list()` a fast valid-token list-comprehension path.
  - Moved object translation/bounds attribute parsing onto one local attribute block.
- `src/xml_to_usda/models.py`
  - Added `slots=True` across the frozen model dataclasses.
  - Added pickle round-trip guards in tests for the core value types and a representative model sample.
  - `BigSpruce` `load_canonical_model` average improved to about `0.435s`.
- `src/xml_to_usda/material_resolver.py`
  - Replaced per-role linear search with a representative material map.
  - Replaced slot override linear scans with dictionary lookup.
- `src/xml_to_usda/discovery_service.py`
  - Replaced repeated persisted-slot searches with a name lookup map.
- `src/xml_to_usda/usda_authoring.py`
  - Reused prototype maps for point-instancer authoring.

## Dead Ends

- UV single-pass rewrite in `src/xml_to_usda/normalizer.py`
  - Result: slower on `BigSpruce`.
  - Measured average moved from about `0.502s` to about `0.539s`.
  - Action: reverted.
- direct child-text map in `src/xml_to_usda/normalizer.py`
  - Result: slower on `BigSpruce`.
  - Measured average moved from about `0.502s` to about `0.514s`.
  - Action: reverted.
- local binding/index loop tweaks in `src/xml_to_usda/normalizer.py`
  - Result: no stable win on `BigSpruce`.
  - Measured average stayed around `0.498s` to `0.500s`, with no convincing improvement over baseline.
  - Action: reverted.
- base-mesh list-comprehension rewrite in `src/xml_to_usda/normalizer.py`
  - Result: no stable win on `BigSpruce`.
  - Measured average stayed around `0.45s` to `0.46s`, but not better than the previous baseline after a cleaner 5-run check.
  - Action: reverted.
- leaf reference instance local-binding rewrite in `src/xml_to_usda/normalizer.py`
  - Result: no stable win on `BigSpruce`.
  - Measured average moved around `0.43s` to `0.45s`, but not convincingly better than the prior baseline after reruns.
  - Action: reverted.

## Current Focus

- `src/xml_to_usda/normalizer.py`
  - Hot path is still object extraction and face-varying authoring.
  - The packed-point / packed-triangle child-scan rewrite was slower on `BigSpruce`, so it is reverted.
  - The `zip(..., strict=False)` simplification in vertex skinning did not produce a stable win, so it is reverted.
  - Caching object child nodes in `SourceNodeIndex` was slower on `BigSpruce`, so it is reverted.
  - Precomputing leaf-reference positions and orientations in the payload was also slower on `BigSpruce`, so it is reverted.
  - Nothing obvious left here looks like a clear next win without risking another dead end.

## Current Baseline

- Full test suite: `264 passed`.
- `BigSpruce` `load_canonical_model` average: about `0.456s` after the latest update.

## Lessons Learned

- One-sample timing is too noisy to trust for tiny `normalizer.py` tweaks. Keep the median and rerun before calling anything a win.
- The useful wins came from removing duplicate XML work or moving shared analysis earlier, not from clever local loop rewrites.
- `normalizer.py` is still the deep hot module. When local rewrites stop winning, record the dead end and move to a broader profile instead of adding another micro-cache.
