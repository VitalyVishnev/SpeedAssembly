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
    "fbx_material_mode": "auto",
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

Huge FBX branch replacement notes:

- the converter ignores XML `LOD/@Filename` for this workflow
- FBX mode is explicit and per prototype
- rigid polygon meshes only are supported in v1
- FBX source config also supports `fbx_material_mode`:
  - `auto`
  - `vertex_color_split`
  - `single_material`
- `auto` uses vertex-color split only when vertex colors exist and produce more than one bucket
- if vertex colors are missing, incomplete, or effectively uniform, FBX prototypes fall back to a single material section
- exact black faces become leaves, every non-black face becomes bark when FBX vertex-color split is usable
- huge FBX jobs stream USDA directly to disk instead of building one giant in-memory string
- runtime conversion temp files live in a separate cache root under `%LOCALAPPDATA%/XMLtoUSDAConverter/cache/jobs`
- by default the converter removes per-job runtime temp data on success, cancel, and failure
- the GUI `Preserve temp files for debugging` switch and CLI `--preserve-temp-files` flag keep the job manifest/temp dir for inspection
- stale runtime job dirs older than 24 hours are swept on startup
- the GUI `CPU Profile` field controls how many logical CPUs remain available to the system during heavy jobs

Autodesk FBX SDK note:

- real `.fbx` import uses the official Autodesk FBX SDK Python bindings when the `fbx` module is importable
- the current known-good Windows setup is:
  - `Python 3.10`
  - `.venv310`
  - `C:\Program Files\Autodesk\FBX\FBX Python SDK\2020.3.4\fbx-2020.3.4-cp310-none-win_amd64.whl`
- `.json` geometry payloads are supported only as a deterministic test backend for automated regression tests

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



