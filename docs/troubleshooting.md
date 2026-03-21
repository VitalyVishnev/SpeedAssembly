# Troubleshooting

This page collects the fast checks for common importer dead-ends.

## `build_gui_exe.cmd -Package` looks stuck or reuses stale output

Symptom:

- the package build appears to hang in PowerShell
- `dist\XMLtoUSDAConverter.exe` still looks old after a recent code change
- PyInstaller seems to spend time in `Analysis` on repeated runs

What to know:

- `.\scripts\build_gui_exe.cmd -Package` now removes `build/` and `dist/` before invoking PyInstaller
- the package build also passes `--clean` so stale analysis state is not reused
- the old failure pattern was caused by incremental PyInstaller state, not by the wind-group code

Practical rule:

- if the standalone build ever looks suspicious, rerun `.\scripts\build_gui_exe.cmd -Package`
- do not trust an older `dist\XMLtoUSDAConverter.exe` timestamp as proof that the current source was packaged

## External PartMesh override looks ignored

Symptom:

- the UI shows `Use Unreal reference`
- you enter a UE object path like `/Game/.../PartMesh.PartMesh`
- the exported USDA still appears to import the low-poly inline part

What to check first:

1. Open the generated USDA text before changing UE settings.
2. Search for `NaniteAssemblyExternalRefAPI`.
3. Search for `unreal:naniteAssembly:meshAssetPath`.

Interpretation:

- if both are missing, the override did not reach the exporter
- if both are present, the exporter is correct and the problem is likely in the UE import path or in the exact asset path

Common causes:

- the part was still exported with an inline `PartMesh` payload instead of a pure external-ref prototype
- the UI path was not in the exact `/Game/.../Asset.Asset` object-path form
- the asset exists, but UE is importing through the legacy USD path rather than the Interchange USD importer

Practical rule:

- when debugging this feature, inspect the USDA first
- do not assume the UI failed until the USDA confirms it

## Material override looks ignored

Symptom:

- bark or leaves paths are entered in the GUI
- the output still uses the default inline material setup

Checks:

1. Verify the path starts with `/Game/`.
2. Verify the generated USDA contains the expected Unreal material connection.
3. Verify the asset path matches the UE Content Browser object path exactly.
