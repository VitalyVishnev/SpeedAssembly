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
