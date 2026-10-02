# UI Theme Bake Flow

`Adjust UI` in the PySide6 shell is a development tool.

## Runtime editing

- bundled defaults live in `src/xml_to_usda/qt_ui/themes/default/theme.json`
- interactive changes are stored in `~/.xml_to_usda/ui_next_theme_overrides.json`
- `Save` updates only the overrides file
- `Export Current Theme` writes the merged runtime snapshot to `~/.xml_to_usda/ui_next_theme_export.json`

## Bake into the bundled build

Once a look is approved, bake it into the repository theme with:

```powershell
.\.venv310\Scripts\python.exe .\scripts\bake_qt_theme.py --snapshot "$env:USERPROFILE\.xml_to_usda\ui_next_theme_export.json"
```

This overwrites the bundled `theme.json` so future release builds start from the approved look without needing runtime overrides.
