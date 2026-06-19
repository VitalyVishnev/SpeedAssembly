# Known Problems

## Role

Track postponed issues, limitations, and dead ends so future refactors do not
repeat the same obvious steps.

## Current Items

- `src/xml_to_usda/normalizer.py`
  - Problem: the remaining hot path is still object extraction and face-varying
    authoring.
  - Why deferred: the packed-point / packed-triangle child-scan rewrite was
    slower on `BigSpruce`, and the vertex-skinning loop simplification did not
    produce a stable win. Caching object child nodes and precomputing leaf
    reference transforms also lost on `BigSpruce`.
  - Likely next step: take a broader profile across more than one sample and
    look for a structural change, not another local loop tweak.

- `tests/data/leafrefs_on_trunk.xml`, `tests/data/leafrefs_on_branch_levels.xml`,
  `tests/data/invalid_leaf_bone.xml`, `tests/data/missing_leaf_refs.xml`,
  `tests/data/missing_skeleton.xml`, `tests/data/non_default_metadata.xml`
  - Problem: these are synthetic contract fixtures, not verified real exports.
  - Why deferred: they intentionally encode error, warning, and edge-case
    branches that are hard to source from a single observed SpeedTree sample.
  - Likely next step: replace any fixture with a real export if one becomes
    available; otherwise keep the smallest fixture that expresses the contract
    cleanly.

- `src/xml_to_usda/udim_resolver.py`, `src/xml_to_usda/material_resolver.py`,
  `src/xml_to_usda/assembly_resolution.py`
  - Problem: piece-local UDIM isolation is covered by automated tests and the
    current baseline sample, but it has not yet been validated across a wider
    set of real SpeedTree structures with different base/prototype material
    layouts.
  - Why deferred: the current change closed the cross-piece overwrite bug; the
    remaining work is broader sample coverage, not a known logic failure.
  - Likely next step: run the piece-local UDIM cases on base geometry, repeated
    parts, and FBX slot prototypes across the real tree/shrub/grass sample
    matrix already used for breadth validation.
