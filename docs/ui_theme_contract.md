# UI Theme Contract

## Role

This document defines the bundled visual-theme contract for the PySide6 beta
shell.

## Theme manifest

Each bundled theme must provide:

- `name`
- `display_name`
- `colors`
- `font_sizes`
- `radii`
- `spacing`
- `control_heights`
- `border_widths`
- `layout`
- `glass`
- `chrome`
- `effects`
- `assets`

## Runtime override layer

The `Next` shell loads theme data in 3 layers:

1. bundled `theme.json`
2. optional `~/.xml_to_usda/ui_next_theme_overrides.json`
3. runtime-only live preview values from `Adjust UI`

The editor must never mutate the bundled theme during ordinary preview/save
usage. Bundled defaults only change through the explicit export/bake flow.

## Main glass controls

The first editor version gives the most detailed control to the main glass
shell:

- tint color and opacity
- top light gradient opacity and height
- bottom dark gradient opacity and height
- border color, opacity, and width
- noise asset selection
- noise opacity
- noise scale

Cards, title bar, buttons, inputs, tabs, and layout stay editable too, but via
simpler token groups.

## Interaction surfaces affected by theme tokens

The current token contract styles these important shell surfaces:

- title bar chrome, including `LOG` and `Adjust UI`
- file picker buttons and path fields
- the split main action for conversion:
  - `Convert to USDA`
  - its attached gear segment
  - the divider between them
- right-column secondary action buttons such as `Generate Wind JSON`
- the `Refresh Wind Groups` button embedded inside the `Wind` tab
- tab buttons and card surfaces inside the glass panel

When theme behavior appears inconsistent between the main shell and the editor,
verify whether the surface is driven by shared button tokens or by a dedicated
surface-specific token group.

## Behavior rules

- the background image fills the full window and uses cover/crop behavior on
  resize
- the glass panel uses the blurred background asset plus a semi-transparent
  tint, gradients, optional noise overlay, and border
- `Adjust UI` live-preview changes in the running shell without restarting it
- visual theme state is stored separately from operator conversion settings
- release defaults are updated only through the bake flow documented in
  [ui_theme_bake.md](/D:/3D%20Personal/VibeCode/XMLtoUSDAconverter/docs/ui_theme_bake.md)
- the execute area uses a separate size tier from the file pickers:
  - `Input XML` and `Output USDA` stay aligned to the file rows
  - `Convert to USDA` and `Generate Wind JSON` may be larger
- `Refresh Wind Groups` is intentionally styled as a quieter tab-local button,
  not as a primary action button
- theme application may trigger a post-show layout refresh so that the first
  visible shell uses the same geometry as a manually repolished shell
- the glass-panel blur slice must track the same cover/crop transform as the
  full-window background, otherwise the glass illusion breaks during resize

## First milestone defaults

The initial bundled theme is a bootstrap approximation only. It is expected to
change after screenshot review and visual iteration.
