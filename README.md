# XML to USDA Converter

Deterministic converter for SpeedTree Raw XML that emits USDA targeting Unreal Engine 5.7 skeletal Nanite Assembly import.

This is not a generic XML-to-USD tool. It is a skeletal tree assembly authoring pipeline.

## Project model

The project treats the source tree as two major components:

- `Base Skeletal Tree`
  All unique tree geometry on the `Main Skeleton`.
- `Assembly Parts`
  Everything sourced from `LeafReferences`, instanced through `PointInstancer`, each part authored as a skeletal mesh with a one-bone local skeleton.

## Current baseline

The active baseline sample is:

- `samples/speedtree/simple_tree/variants/SimpleTree_01.xml`

Current status:

- UE accepts the generated baseline USDA as skeletal Nanite Assembly input
- the remaining v1 work is broader validation across multiple real tree, shrub, palm, and grass structures

## Commands

Environment note:

- use [`.venv310`](D:/3D%20Personal/VibeCode/XMLtoUSDAconverter/.venv310) as the default working environment for this repository
- real FBX import support is wired through Autodesk `FBX Python SDK 2020.3.4` installed into `.venv310`
- tests and build helpers should also run from `.venv310`
- do not assume the legacy `.venv` or global Python install has working FBX bindings

```powershell
python -m xml_to_usda inspect path\to\tree.xml
python -m xml_to_usda convert path\to\tree.xml path\to\tree.usda
python -m xml_to_usda convert path\to\tree.xml path\to\tree.usda --part-source-config part_sources.json --cpu-profile balanced
python -m xml_to_usda convert path\to\tree.xml path\to\tree.usda --preserve-temp-files
python -m xml_to_usda gui
```

`part_sources.json` is a JSON object keyed by prototype name or `Mesh_<id>`, for example:

```json
{
  "Twig_01": {
    "mode": "fbx_file",
    "fbx_material_mode": "vertex_color_split",
    "fbx_path": "D:/Trees/HeroBranch.fbx"
  },
  "Mesh_2": {
    "mode": "unreal_asset",
    "asset_path": "/Game/TreeParts/SK_Twig02.SK_Twig02"
  }
}
```

Supported per-prototype source modes:

- `xml_mesh`
- `unreal_asset`
- `fbx_file`

GUI material workflow, stage 1:

- `Base XML materials` are discovered from the XML `Materials/Material` list
- в этот список попадают только те XML material slots, которые реально используются `Base Skeletal Tree`, а не prototype-only материалы из instanced веток
- each base XML material row exposes its source `ID`, source `Name`, and one Unreal material path field
- assigning the same Unreal path to multiple XML rows is valid; it intentionally reuses one UE material asset across multiple XML source slots
- repeated part prototypes have a separate material contract from the base tree
- part rows currently expose:
  - `vertex_color_split`
  - `single_material`
- `vertex_color_split` on part rows is explicit black/white bucketing, not a hidden bark/leaves fallback
- `single_material` on part rows uses its own dedicated Unreal material path field
- the planned `get materials from FBX` mode is not part of stage 1 yet

Huge FBX branch replacement notes:

- the converter ignores XML `LOD/@Filename` for this workflow
- FBX mode is explicit and per prototype
- rigid polygon meshes only are supported in v1
- CLI/JSON source config still supports `fbx_material_mode`:
  - `auto`
  - `vertex_color_split`
  - `single_material`
- the GUI stage-1 workflow intentionally exposes only `vertex_color_split` and `single_material`; `auto` remains a compatibility/config mode, not the recommended interactive workflow
- `auto` uses vertex-color split only when vertex colors exist and produce more than one bucket
- if vertex colors are missing, incomplete, or effectively uniform, `auto` falls back to a single material section
- explicit `vertex_color_split` is strict: it must produce a usable split or the conversion fails with a detailed reason
- if Autodesk FBX SDK bindings throw an internal vertex-color access error during import, the converter retries strict `vertex_color_split` once in a fresh worker process before surfacing the detailed failure
- stage-1 `vertex_color_split` expects exact black and exact white face buckets for part materials
- embedded FBX material-slot import is not implemented yet in the UI workflow
- huge FBX jobs stream USDA directly to disk instead of building one giant in-memory string
- runtime conversion temp files live in a separate cache root under `%LOCALAPPDATA%/XMLtoUSDAConverter/cache/jobs`
- by default the converter removes per-job runtime temp data on success, cancel, and failure
- the GUI `Preserve temp files for debugging` switch and CLI `--preserve-temp-files` flag keep the job manifest/temp dir for inspection
- stale runtime job dirs older than 24 hours are swept on startup
- the GUI `CPU Profile` field controls how many logical CPUs remain available to the system during heavy jobs
- `balanced` is the default and recommended profile for normal work because it prioritizes stable completion and system responsiveness
- GUI errors are now non-modal by default: failures are written to the in-app `Log` panel and to `~/.xml_to_usda/gui_runtime.log` instead of blocking the screen with modal error popups
- wind-group slider settings are now persisted per input XML, so different trees do not overwrite each other's wind tuning
- the GUI runs large conversions in a dedicated worker process instead of inside the Tk process
- multiple explicit FBX prototype imports are fanned out through a `spawn` process pool, so different huge branch FBX files can import in parallel
- `balanced` now matters most when there are multiple independent heavy stages or prototype FBX imports; one single giant FBX is still largely limited by the Autodesk SDK's own single-file import path
- because of that, a huge job can legitimately show low total `% CPU` in Task Manager while still behaving correctly
- current optimization priority is stability, diagnostics, and predictable UE-facing output rather than forcing maximum all-core utilization on a single huge FBX
- packaged frozen runs now prefer sequential multi-FBX prototype import for stability, while launcher/dev runs may still import multiple prototypes in parallel

Autodesk FBX SDK note:

- real `.fbx` import uses the official Autodesk FBX SDK Python bindings when the `fbx` module is importable
- the current known-good Windows setup is:
  - `Python 3.10`
  - `.venv310`
  - `C:\Program Files\Autodesk\FBX\FBX Python SDK\2020.3.4\fbx-2020.3.4-cp310-none-win_amd64.whl`
- `.json` geometry payloads are supported only as a deterministic test backend for automated regression tests
- if the process pool needed for parallel FBX prototype import is unavailable, the converter falls back to sequential FBX import instead of failing

Material-policy note:

- `source_material_roles` does not require XML material ids to be `1/2`
- source material ids are treated as XML-local references only; semantic bark/leaves remapping is handled by the resolver policy, not by hardcoded source-id numbering

## Build helpers

Fast launcher build:

```powershell
.\scripts\build_gui_exe.cmd
```

Standalone PyInstaller build (cleans stale PyInstaller state by default):

```powershell
.\scripts\build_gui_exe.cmd -Package
```

Explicit clean rebuild (same package result):

```powershell
.\scripts\build_gui_exe.cmd -Package -Clean
```

Watch mode for repeated rebuilds:

```powershell
.\scripts\watch_gui_exe.cmd
```

Output exe path:

- `dist\XMLtoUSDAConverter.exe`

Notes:

- the default build is a fast launcher copy from `.venv310\Scripts\xml-to-usda-gui.exe`
- the fast build depends on the local `.venv310`
- `-Package` removes stale build/dist state first, then runs PyInstaller with `--clean` to produce the standalone executable
- every launcher or package build now writes `dist\build_info.json`
- on startup the GUI writes a `Build info:` banner into the in-app `Log`, including build time, build mode, and a short git summary when available
- on startup the GUI also writes a `Runtime info:` banner into the in-app `Log`, including whether the app is frozen, which executable launched it, and which runtime paths are active

## Docs

- `AGENTS.md`
  Mission, hard rules, and canonical terminology.
- `docs/ue_import_contract.md`
  Importer-facing USDA structure and required UE/USD contract.
- `docs/speedtree_mapping.md`
  SpeedTree XML to project-concept mapping.
- `docs/workflow_status.md`
  Baseline sample, current status, and workflow.
- `docs/troubleshooting.md`
  Fast checks for common exporter and UE importer dead-ends.
- `docs/local-python-environment.md`
  Local environment setup.

## Repo areas

- `samples/` holds controlled XML inputs and generated outputs.
- `docs/` holds the compact project documentation set.
- `vault/` holds reference USDA, UE schema, importer source, and related research artifacts.



