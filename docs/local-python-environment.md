# Local Python Environment

## Purpose

This repository uses a local `.venv` so project dependencies stay inside the workspace instead of depending on whatever is installed globally on the machine.

## What this solves

- `pytest` and other packages are installed per-project
- commands are reproducible across machines
- the project does not depend on globally installed Python packages
- the environment can be deleted and recreated without affecting other tools

## What this does not solve

- a base system Python is still required once to create `.venv`
- if the system Python is removed, `.venv` may need to be recreated

## Standard workflow

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[dev]
```

After activation, run project commands through the environment:

```powershell
python -m pytest
python -m xml_to_usda inspect .\references\speedtree\xml\SkeletyalAssemblyTest_01.xml
python -m xml_to_usda convert .\references\speedtree\xml\SkeletyalAssemblyTest_01.xml .\references\usd\generated\SkeletyalAssemblyTest_01.generated.usda
```

## Recreate the environment

If the environment is broken or out of sync:

```powershell
deactivate
Remove-Item -Recurse -Force .\.venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[dev]
```

## Expected rule

Use the activated `.venv` for all project commands. Do not rely on globally installed `pytest` or globally installed project packages.
