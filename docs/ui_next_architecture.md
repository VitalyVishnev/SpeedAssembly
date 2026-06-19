# PySide6 UI Architecture

## Role

This document describes the bootstrap architecture for the PySide6 release shell.

The PySide6 shell is the supported operator release path. The old Tk GUI is
retired and no longer part of the supported contract.

## Layering

The PySide6 shell must remain a thin UI layer over existing application and
runtime services:

- `conversion_service`
- `discovery_service`
- `settings_service`
- `wind_service`
- `conversion_process`

The PySide6 UI must not implement conversion semantics, USDA rules, FBX import
rules, or direct pipeline-specific business logic.

## Package layout

The PySide6 UI lives in `src/xml_to_usda/qt_ui/` and is split into:

- `entry.py`
  Public primary GUI entrypoint.
- `theme.py`
  Theme token parsing, override merge, asset resolution, and stylesheet generation.
- `persistence.py`
  UI shell state persistence plus theme override persistence.
- `adjust_ui.py`
  Dev-only live theme editor used to tune the PySide6 shell.
- `window.py`
  Frameless shell, glass panel rendering, and bootstrap layout.

The shell now owns the primary operator workflow while staying thin over the
shared application services.

The shell applies a runtime screen scale on top of the resolved theme. The
stored theme and `Adjust UI` values remain reference design units; the live
stylesheet and layout use a scaled copy derived from the current screen's
available logical geometry.

## Rollout

- primary release GUI entrypoint is `xml_to_usda.qt_ui.entry`
- `python -m xml_to_usda gui` and `xml-to-usda-gui` route to the PySide6 shell
- primary packaged build is `dist-next\XMLtoUSDAConverter.exe`
- packaged worker commands route to the dedicated `dist-next\XMLtoUSDAWorker.exe`
  sidecar so heavy geometry work does not re-enter the GUI executable

The release target is now the PySide6 shell. Any missing operator parity should
be treated as release-blocking work for `dist-next`, not as a reason to revive
the old Tk shell.

## Current Shell Interaction Contract

The current PySide6 shell uses the following operator-facing interaction rules:

- the two file pickers are labeled `Input XML` and `Output USDA`
- the output field is still derived automatically from the selected XML path by
  replacing the suffix with `.usda`
- file-pick buttons intentionally use a smaller size tier than the main action
  buttons so the operator can scan file inputs without the action column
  dominating the shell
- the main execute control is a split action:
  - left side runs `Convert to USDA`
  - while conversion is active, the same control turns into `Cancel`
  - right-side gear opens the future conversion-mode menu
- the conversion-mode menu already exposes:
  - `Skeletal Assembly`
  - `Skeletal Parts`
  - `Static Assembly`
  - `Static Parts`
- only `Skeletal Assembly` is currently enabled; the other entries are visible
  placeholders so the shell structure stays stable when those backends are
  added later
- `Refresh Wind Groups` lives inside the `Wind` tab next to the global wind
  controls instead of the top-right action column
- `Refresh Wind Groups` uses a quieter secondary button style so it reads as a
  tab-local maintenance action instead of a primary conversion command
- the shell performs a post-show layout activation pass so size-sensitive
  controls settle to their intended dimensions on first launch instead of only
  after an `Adjust UI` round-trip
- startup normal geometry is recomputed from the current screen instead of
  blindly replaying raw saved dimensions from another monitor

This interaction contract is intentional and should be treated as the default
layout baseline for future PySide6 iterations unless a later UI review replaces
it explicitly.

## Adjust UI Mode

`Adjust UI` is a development-only editor for the PySide6 shell.

Rules:

- it lives only in the PySide6 shell
- it edits section-level layout tokens, not arbitrary per-widget drag/drop
- it previews changes live in the running main window
- it saves only to `~/.xml_to_usda/ui_next_theme_overrides.json`
- final approved looks are promoted through export + bake, not by leaving the
  editor in release builds as the source of truth

## Responsiveness Rule

The PySide6 UI is intentionally a light, operator-facing shell.

Active implementation rule:

- prefer responsiveness, resize stability, and low system load over expensive
  decorative effects
- avoid heavy live recomputation during drag-resize, especially full-window
  image resampling and large visual caches that update every pixel
- keep background, glass, and shadow effects visually simple enough that the
  shell stays fast on ordinary production machines
- if a visual effect conflicts with smooth interaction, smooth interaction wins

If a future visual requirement needs a heavier rendering path, treat that as an
explicit architecture decision and review it before implementation.

Additional rule for future UI work:

- if a behavior can be implemented in either a visually richer but heavier way
  or a simpler but noticeably more responsive way, the simpler responsive path
  wins by default
