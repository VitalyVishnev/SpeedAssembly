# Project log

Short history only. Current contracts, open risks, crash evidence, and rejected
routes belong in [wiki/decisions.md](wiki/decisions.md),
[wiki/known-bugs.md](wiki/known-bugs.md),
[wiki/encountered-crashes.md](wiki/encountered-crashes.md), and
[wiki/experiments.md](wiki/experiments.md). Original documentation is retained
under `docs/raw/`; Git retains per-change detail.

## 2026-07-01 - 2026-07-05: memory split, preview foundations

- Migrated active memory to `docs/wiki/`; preserved old docs in `docs/raw/`.
- Established practical test density, cache maintenance, narrow Proxy source
  loading, and low-latency preview paths.
- Built Fracture V1 natural-detach planning and isolated preview workers.
- Built Wind Preview V1: read-only XML inspection, bottom-up groups, Auto
  Hierarchy, shared viewport path, and worker isolation.

## 2026-07-09 - 2026-07-17: Wind V2 and Detailed Cuts

- Added Wind V2 group stack, manual overrides, undo/redo, autosave, external
  FBX/USD skeleton loading, explicit USD Skeleton selection, and frozen-worker
  fixes.
- Standardized compact viewport panels, screenshot preflight, and shared
  rendering/focus behavior.
- Replaced approximate fracture slicing with deterministic Boolean Detailed
  Cuts: physical-bone positions, provenance, caps, noise limits, prepared
  sessions, same-shell sequencing, and cutter-aware part ownership.
- Added the crash ledger, cold-cache/native mitigations, worker coalescing, and
  contract-layered tests. Exact implementation history is in the wiki.

## 2026-07-19 - 2026-07-28: release, failure boundaries, source semantics

- Established public SpeedAssembly identity, minimal release bundle, tutorial,
  modal previews, and cross-process crash context.
- Tightened fail-loud behavior for FBX/material preflight and worker recovery.
- Applied Object-local `LeafReferences` transforms for mesh-bearing hosts;
  non-mesh hosts remain fail-loud when transformed.
- Added optional post-prune Proxy base-mesh vertex fusion and began unified
  main-shell status work.

## 2026-08-02 - 2026-08-12: skeleton, static parts, Proxy Mesh

- Completed telemetry-backed status card and source-backed Quick build loop.
- Made local +X and Skinning Quality the production skeleton contract; added
  UE foliage-orientation repair and external-skeleton loading diagnostics.
- Added `static_parts`, output-folder routing, faster deterministic authoring,
  packed ufbx migration, and license notices.
- Added stem-aware Proxy collision, high-resolution density acceleration,
  collision UI, Proxy export from preview, user-docs foundation, and generator
  group-gap warning.

## 2026-08-13 - 2026-08-20: Scattered Parts and external-rig audit

- Normalized root-fixed SpeedTree attachments, prototype display modes, and
  vertical-skeleton protection.
- Added Scattered Parts assembly resolution and synthetic Dynamic Wind rigs;
  grass imports and animates normally in Unreal.
- Audited known bugs, docs navigation, external FBX diagnostics, and
  `TungTungTung.fbx`; PCG-specific cause remains Unverified.

## 2026-08-21 - Documentation compaction

- Compressed decision prose, experiment history, and this log; removed duplicated
  chronology while preserving contracts, risks, evidence, outcomes, and next tests.
- Retained detailed active contracts and crash records. No raw sources changed.
