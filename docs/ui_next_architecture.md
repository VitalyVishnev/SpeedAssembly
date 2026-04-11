# UI Next Architecture

## Role

This document describes the bootstrap architecture for the PySide6 beta shell.

The current Tk GUI remains the stable operator fallback. The new shell is a
parallel UI track intended for visual iteration, responsive layout work, and a
future full migration once feature parity is reached.

## Layering

The PySide6 shell must remain a thin UI layer over existing application and
runtime services:

- `conversion_service`
- `discovery_service`
- `settings_service`
- `wind_service`
- `conversion_process`

The new UI must not implement conversion semantics, USDA rules, FBX import
rules, or direct pipeline-specific business logic.

## Package layout

The new UI lives in `src/xml_to_usda/qt_ui/` and is split into:

- `entry.py`
  Public beta entrypoint.
- `theme.py`
  Theme token parsing, override merge, asset resolution, and stylesheet generation.
- `persistence.py`
  UI shell state persistence plus theme override persistence.
- `adjust_ui.py`
  Dev-only live theme editor used to tune the `Next` shell.
- `window.py`
  Frameless shell, glass panel rendering, and bootstrap layout.

This is the first milestone only. Real panels, background job bridges, and
operator-state adapters will be added incrementally after visual review.

## Rollout

- stable GUI entrypoint remains `xml_to_usda.gui`
- beta PySide6 entrypoint is `xml_to_usda.qt_ui.entry`
- stable packaged build remains `XMLtoUSDAConverter.exe`
- beta packaged build is `XMLtoUSDAConverterNext.exe`

The two shells must coexist until the PySide6 shell reaches working parity and
passes the same real conversion validation.

## Adjust UI Mode

`Adjust UI` is a development-only editor for the PySide6 shell.

Rules:

- it lives only in `Next`, not in the stable Tk shell
- it edits section-level layout tokens, not arbitrary per-widget drag/drop
- it previews changes live in the running main window
- it saves only to `~/.xml_to_usda/ui_next_theme_overrides.json`
- final approved looks are promoted through export + bake, not by leaving the
  editor in release builds as the source of truth

## Responsiveness Rule

`UI Next` is intentionally a light, operator-facing shell.

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
