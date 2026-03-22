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

```powershell
python -m xml_to_usda inspect path\to\tree.xml
python -m xml_to_usda convert path\to\tree.xml path\to\tree.usda
python -m xml_to_usda gui
```

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

- the default build is a fast launcher copy from `.venv\Scripts\xml-to-usda-gui.exe`
- the fast build depends on the local `.venv`
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



