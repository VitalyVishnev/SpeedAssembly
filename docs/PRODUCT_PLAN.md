# Product Plan

## Role

This document is the product-facing implementation queue. It captures the
near-term UX and release work that follows from the current decisions log.

It does not override `AGENTS.md`, `docs/ue_import_contract.md`, or
`docs/workflow_status.md`.

## Fixed product contract

- One global remembered operator state across trees and sessions.
- No per-XML settings as part of the product contract.
- No project concept; presets and global remembered state are the reuse
  mechanism.
- A factory-defaults preset always exists.
- Users can save named presets and choose them from a dropdown.
- Factory defaults and user presets are both visible in the preset selector.
- Last-used XML folder and last-used output folder are remembered separately.
- The first XML selection auto-fills the output path from the XML path.
- If the user already edited the output path manually, later XML selections
  keep that output path style and only update the filename stem.
- Help lives inside the packaged exe as slide-style "How to use" pages with
  topic buttons and next/back arrows.
- A dismissible first-launch prompt near the help affordance invites the user to
  open the guide.
- The user-facing release is a standalone GitHub download.
- Users do not need Python installed to run the packaged app.
- The app is local-only by default; diagnostics do not require network
  telemetry.
- `balanced` is the only ordinary visible CPU profile.
- Named presets can be saved, overwritten, deleted, imported, exported, and
  reset to defaults.

## Near-term queue

1. Collapse settings persistence into global remembered state plus named
   presets.
2. Add preset management actions: save, overwrite, delete, import, export, and
   reset-to-default.
3. Implement the sticky XML/output folder behavior and output-path derivation
   rules.
4. Add the in-app help deck foundation: first-launch prompt, slide pages,
   topic buttons, and the base "How to use" content.
5. Add the diagnostics bundle export and the in-app support/about entry point.
6. Reduce the visible operator CPU controls to `balanced` and keep deeper
   tuning internal.
7. Package example assets and help assets with the release zip if we decide to
   ship example files alongside the exe.

## Deferred future work

- UDIM support.
- Second UV channel support.
- Batch conversion.
- Broader validation on additional real SpeedTree sample families.
- Detailed per-material-slot UV offset rules once the importer contract is
  settled.
