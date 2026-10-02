# Typography audit and proposal

Status: proposal for operator review, 2026-10-03. Runtime styles are unchanged.

## Observed baseline

- No explicit font-family, application font, or bundled font asset was found
  in the Qt shell. A local QApplication/QFontInfo probe resolved Segoe UI,
  with a 9 pt application default. Main-shell QSS replaces sizes in pixels.
  The source does not record an intentional family-selection rationale.
- Bundled theme values are `title: 11`, `body: 13`, `small: 12`.
  These are base design sizes before runtime scaling, not physical screen pixels.
- Main labels and controls mostly inherit body. Editor section titles use
  body/600. Program status title uses body/700, state uses title/700, and
  summary/section captions use small/400 or small/700.
- A local 13 px/600 QLabel resolved Segoe UI Semibold. Selected skinning
  ticks use `setBold`, while local preview titles often use 700.
- Help/Support titles use fixed 20 px/700, Boolean diagnostic titles use
  18 px/700, preview checkboxes use fixed 11 px, and Wind layers use fixed
  12 px. These local values bypass theme font-size scaling.
- Caption targets/marks, top gear and preset dots currently depend on the
  small-text size. Text changes must preserve the approved icon geometry.

Source navigation: `qt_ui/theme.py`, `qt_ui/themes/default/theme.json`,
`qt_ui/panels.py`, `qt_ui/dialogs.py`, `qt_ui/preview_shell.py`,
`qt_ui/wind_preview.py`, `qt_ui/window.py`.

## Recommended family

Keep Segoe UI for UI text and explicitly select it, falling back to the Qt
system UI font if unavailable. This preserves the operator-approved appearance
while making the family choice intentional. Use installed system fonts;
there is no need to copy font binaries into the package.

Use Consolas for diagnostic logs and code, with the Qt fixed-pitch system font
as fallback. Keep filenames, paths, counters and ordinary parameter values in
Segoe UI unless a particular column requires fixed-width alignment.

Taste contributes same-family emphasis and a restrained sans-serif hierarchy.
Its landing-page display sizes, font shortlist and tightly spaced headlines
are not requirements for this desktop parameter editor. Fluent's native-font,
semantic-role and sentence-case guidance fits this application more closely.

## Proposed roles

Values below are base logical px at runtime scale 1.0. The 13 px body preserves
current density. Fluent's 14 px body is a useful comparison, not a copied rule.

| Role | Size | Weight | Application |
| --- | ---: | ---: | --- |
| Window heading | 20 | 600 | Help slide, Support, preview window heading |
| Major section | 16 | 600 | Distinct settings block with subordinate controls |
| Group heading | 13 | 600 | Wind group, material group, Status section |
| Body and controls | 13 | 400 | Parameter labels, fields, descriptions, secondary buttons |
| Emphasis | 13 | 600 | Primary action, selected tab/tick, current status value |
| Supporting text | 12 | 400 | Clarification, units, counts, status summary metadata |
| Diagnostic text | 12 | 400 | Consolas logs/code, rather than ordinary UI copy |

Use 400 and 600 as the normal vocabulary. Reserve 700 for a rare explicit
exception rather than every title. Errors also need a clear message and status
color; font weight alone must not communicate failure.

Use sentence case for section captions. Preserve technical capitalization such
as XML, USDA, FBX, UDIM and Unreal names. Align labels/descriptions left, numbers
in comparable columns right, and short button captions centrally. Keep default
letter spacing. For multi-line explanatory copy, target a line pitch around
1.4 times the font size using Qt-supported text layout; do not rely on web CSS
`line-height` in a plain QLabel stylesheet.

## Implementation boundary

Reuse theme.py, the existing theme payload and Adjust UI controls. No separate
typography engine or new dependency. Assign semantic roles in shared styles,
then replace conflicting local font rules in existing dialogs/previews.
Persisted presets must remain loadable; new fields need defaults if introduced.

Keep text scale and icon geometry independent during the migration. Validate
long paths, counts, bold selected ticks, and dense preview rows with the widest
permitted text style. The proposed 16 px role belongs to major blocks, not every
repeated Wind card, and must fit existing containers before it is applied.

Check actual rendered font family/weight, text bounds and multiline wrapping at
runtime scales 0.90, 1.00 and 1.75. Use existing relevant Qt checks plus Quick
during visual iteration; Package after final UI approval.

## References

- [Taste skill, typography section](C:/Users/User/.codex/skills/taste-skill/SKILL.md)
- [Fluent typography](https://fluent2.microsoft.design/typography)
- [Qt QFontInfo](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QFontInfo.html)
- [Qt system font selection](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QFontDatabase.html)
