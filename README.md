# XML to USDA Converter

`v1` scaffold for converting observed SpeedTree Raw XML into self-contained USDA aimed at Unreal Engine 5.7 skeletal nanite assembly import.

## Local Environment

This project uses a local `.venv` inside the repository. After the environment is created, install and run everything from that environment instead of relying on global `python`, `pytest`, or globally installed packages.

### Windows PowerShell bootstrap

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[dev]
```

### Smoke check

```powershell
python --version
python -m pytest
python -m xml_to_usda inspect .\references\speedtree\xml\SkeletyalAssemblyTest_01.xml
python -m xml_to_usda convert .\references\speedtree\xml\SkeletyalAssemblyTest_01.xml .\references\usd\generated\SkeletyalAssemblyTest_01.generated.usda
python -m xml_to_usda gui
```

If commands fail after dependency installation, the usual cause is that `.venv` is not activated in the current PowerShell session.

## Commands

```powershell
python -m xml_to_usda inspect path\to\tree.xml
python -m xml_to_usda convert path\to\tree.xml path\to\tree.usda
python -m xml_to_usda gui
```

## Current Phases

- `Phase 1`: golden sample pipeline and observed export comparison for one controlled SpeedTree 10 tree
- `Phase 2`: thin desktop GUI and later `exe` packaging
- `Phase 3`: external branch reuse from existing Unreal Engine project assets
- `Phase 4`: Dynamic Wind JSON generation

## Status

- Targets `UE 5.7 Interchange importer` by default.
- Implements a deterministic `inspect` report for observed XML schema exploration.
- Implements a canonical model and USDA writer for `trunk + skeleton + leaf references`.
- Reads real SpeedTree-style packed arrays for `Objects/Object/Points`, `Triangles/PointIndices`, `LeafReferences`, and `Bones`.
- Emits USDA closer to the attached skeletal assembly reference, including `rel unreal:naniteAssembly:skeleton`, `SkelBindingAPI`, and `primvars:unreal:naniteAssembly:*` bind data.
- Exposes a `tkinter` desktop GUI as a thin wrapper over the same conversion pipeline used by CLI.
- Protects the immutable `vault/` from generated outputs.

## Repo Areas

- `references/` holds validated reference files and generated comparison artifacts.
- `samples/` is for controlled experiment inputs and expected outputs.
- `vault/` is for immutable third-party or engine-side reference materials.

## Reference docs

- `docs/local-python-environment.md`
- `docs/project-roadmap.md`
- `docs/golden-sample-workflow.md`
- `references/README.md`
- `references/notes/observed-speedtree-xml.md`
- `references/notes/reference-usda-assembly.md`
