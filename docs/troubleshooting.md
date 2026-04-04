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
- check the GUI `Log` after startup: the top `Build info:` block is sourced from `dist\build_info.json` and is now the fastest way to confirm which launcher/package build you actually launched

## Runtime temp files seem to accumulate

Symptoms:

- `%LOCALAPPDATA%/XMLtoUSDAConverter/cache/jobs` keeps growing
- you see old job manifests or abandoned temp folders after interrupted sessions

Checks:

- normal conversion runs should clean runtime job dirs automatically
- `.partial` output files should not remain after success, cancel, or failure
- stale job dirs older than 24 hours are removed during startup sweep

Expected behavior:

- only UI settings persist by default
- runtime temp dirs are removed unless `Preserve temp files for debugging` or `--preserve-temp-files` is enabled
- build folders such as `build/` and `dist/` are unrelated to runtime cache cleanup

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

## FBX prototype replacement fails before export

Symptom:

- a repeated part row is switched to `FBX file`
- conversion fails before USDA is written

What to check first:

1. Verify the selected file is the explicit FBX replacement file you intended, not an XML-authored `LOD/@Filename`.
2. Verify the file exists on disk.
3. Verify the FBX is rigid-only for this workflow.
4. Verify the mesh provides vertex colors on the imported points.

Common causes:

- Autodesk FBX SDK Python bindings are not installed, so `fbx` / `FbxCommon` cannot be imported
- the chosen FBX contains animation or skin deformers
- the chosen FBX has no readable polygon mesh nodes
- the chosen FBX has no usable vertex colors
- Autodesk FBX SDK raised an internal `SystemError` while reading vertex colors in a long-running session

Practical rule:

- FBX mode is explicit, rigid-only, and vertex-color-driven in v1
- if the error mentions missing SDK bindings, fix the local FBX SDK install before debugging the XML or USDA path
- the GUI stage-1 workflow does not rely on `auto`; it exposes explicit `vertex_color_split` and `single_material` instead
- `auto` is still supported in CLI/JSON config as a compatibility mode and may degrade to single-material fallback when vertex colors are unusable
- explicit `vertex_color_split` should now either succeed, or fail with a detailed reason that mentions missing/unusable colors or an Autodesk SDK vertex-color access failure
- for strict `vertex_color_split`, the converter now performs one retry in a fresh worker process before surfacing the final error

## Large GUI conversion crashes or gets less stable after repeated runs

Symptom:

- the GUI works for one or two huge conversions, then later conversions become more crash-prone
- crashes happen during `fbx_import`, `usda_writing`, or immediately after pressing `Convert`

What to know:

- large conversions now run in a dedicated worker subprocess instead of inside the Tk process
- the worker subprocess may also spawn additional worker processes for parallel FBX prototype import
- the old failure pattern came from doing too much native FBX and huge-export work inside the GUI process

Checks:

1. Rebuild the launcher build so the executable matches the current source.
2. Verify the log shows staged telemetry such as `xml_normalization`, `fbx_import`, and `usda_writing`.
3. If the crash leaves a job manifest behind, inspect the recorded phase under `%LOCALAPPDATA%/XMLtoUSDAConverter/cache/jobs`.
4. Check the GUI `Log` panel and `~/.xml_to_usda/gui_runtime.log` for the full traceback.
5. Compare the startup `Runtime info:` banner and the manifest `runtime_context` block to confirm whether the failing run was `launcher`-style or a frozen packaged executable.

Practical rule:

- if a large-job crash reproduces only in an older launcher or packaged exe, rebuild first
- if the current build still crashes, preserve temp files and inspect the last recorded phase before debugging XML content
- if parallel FBX import cannot start in the current environment, the converter should now fall back to sequential import instead of terminating the job immediately
- packaged frozen runs also prefer sequential multi-FBX import on purpose; lower CPU usage there is expected if that tradeoff avoids standalone crashes

## Huge FBX export appears busy for a long time

Symptom:

- the GUI stays responsive, but the conversion takes a long time
- the output file may not appear until late in the job

What to know:

- huge FBX prototype payloads now stream USDA through a temporary `.partial` file and atomically replace the final target on success
- `balanced` leaves logical CPUs free for the rest of the system
- `max_speed` uses more of the machine but may feel less responsive during the job
- the current multiprocessing path is mainly across independent prototypes and stages; one single huge Autodesk FBX import may still keep total Task Manager CPU surprisingly low

Practical rule:

- use `balanced` when you want the machine to stay comfortable for background use
- use `max_speed` when throughput matters more than responsiveness
- do not treat low total CPU percentage alone as a regression if the job still completes in acceptable wall-clock time
- if conversion is cancelled or fails, a leftover `.partial` file is treated as a bug

## Material override looks ignored

Symptom:

- a material path is entered in the GUI
- the output still uses the default inline material setup

Checks:

1. Verify the selected material policy matches the intended behavior.
2. Verify the path starts with `/Game/`.
3. Verify the generated USDA contains the expected Unreal material connection.
4. Verify the asset path matches the UE Content Browser object path exactly.

GUI material interpretation, stage 1:

- `Base XML materials`
  - these rows come from the XML `Materials/Material` list, but only for slots actually used by the unique base-tree geometry
  - each row maps one XML material slot to one Unreal material path
  - entering the same Unreal path on multiple rows is valid and intentionally reuses the same UE material asset
- repeated part rows
  - `single_material` assigns one dedicated Unreal material path to that repeated prototype
  - `vertex_color_split` assigns separate Unreal material paths to the explicit `Black` and `White` buckets for that repeated prototype
- stage-1 does not yet expose `get materials from FBX`; if you need embedded FBX material slots, that is a later feature, not a hidden fallback in the current UI

Legacy/CLI material-policy interpretation:

- `source_material_roles`
  - compatibility mode only
  - resolves source XML material references through semantic bark/leaves roles
  - does not require source ids to be `1/2`
- `single_material`
  - ignores XML ids and vertex colors
  - the base mesh and all part prototypes should bind to one material
- `vertex_color_split`
  - ignores XML ids
  - exact-white faces go to bucket `1`
  - gray and other non-white faces go to bucket `2`

Practical rule:

- if a fern or shrub uses source ids like `3/4`, do not debug it as a missing `1/2` material-role error; source ids are arbitrary project-local metadata, not a required bark/leaves numbering contract

## Only Part Meshes import, but the base mesh is missing

Symptom:

- UE imports the `Assembly Parts`
- the `Base Skeletal Tree` is missing or appears to have been skipped
- this often shows up first on fern-like or other multi-root plants

What to check first:

1. Open the generated USDA text.
2. Verify the base mesh `def Mesh "<stem>"` exists at all.
3. Inspect the base `SkelAnimation`, base mesh `skel:joints`, and main `Skeleton` joint arrays.

Interpretation:

- if the base mesh prim is missing, the bug is in normalization or material-policy remapping before USDA writing
- if the base mesh prim exists but the main skeleton collapses multiple root joints to one alias, the bug is in USDA joint naming and UE may skip the base skeletal tree

Known regression pattern:

- a multi-root plant must not alias every root joint to the output file stem
- only single-root skeletons may use the output stem as the root-joint alias

Practical rule:

- when parts import but the base mesh does not, inspect joint arrays before debugging materials

## Imported part skeleton is named `Root_Skeleton`

Symptom:

- one imported part skeleton asset gets a generic `Root_Skeleton`-style name
- another part imports with a prototype-derived skeleton name

Likely cause:

- the inline one-bone part skeleton was authored with a hardcoded local joint name such as `root`

Practical rule:

- the local one-bone joint name should come from the prototype prim name
- if USDA still shows `uniform token[] joints = ["root"]` inside inline prototypes, the exporter is on the old path
