# Local Python Environment

## Purpose

This repository uses a workspace-local Python 3.10 virtual environment so project dependencies stay inside the workspace instead of depending on whatever is installed globally on the machine.

## Current environment contract

Use `.venv310` as the default and canonical working environment for future development chats, GUI runs, CLI runs, tests, and build work.

Why `.venv310` is the primary environment:

- Autodesk FBX Python SDK `2020.3.4` provides a ready-made wheel for CPython `3.10` on Windows
- the real FBX import path is validated against that wheel in `.venv310`
- the older `.venv` or global Python installs should not be assumed to have working Autodesk FBX bindings
- build helpers are expected to consume `.venv310`, not `.venv`

## What this solves

- `pytest` and other packages are installed per-project
- commands are reproducible across machines
- the project does not depend on globally installed Python packages
- the environment can be deleted and recreated without affecting other tools

## What this does not solve

- a base system Python is still required once to create `.venv310`
- if the system Python is removed, `.venv310` may need to be recreated

## Standard workflow

Primary FBX-capable workflow:

```powershell
py -3.10 -m venv .venv310
.\.venv310\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[dev]
python -m pip install "C:\Program Files\Autodesk\FBX\FBX Python SDK\2020.3.4\fbx-2020.3.4-cp310-none-win_amd64.whl"
```

After activation, run project commands through `.venv310`:

```powershell
python -m pytest
python -m xml_to_usda inspect .\samples\speedtree\simple_tree\variants\SimpleTree_01.xml
python -m xml_to_usda gui
```

Build helpers also use `.venv310`:

```powershell
.\scripts\build_qt_gui_exe.cmd -Package
.\scripts\build_qt_gui_exe.cmd -Package -Clean
```

The primary release artifact is `dist-next\XMLtoUSDAConverter.exe`. Each package build also writes `dist-next\build_info.json`. The GUI reads that file on startup and prints a `Build info:` banner at the top of the in-app `Log`, so package testing no longer depends on the executable file timestamp.

Large-job execution note:

- the GUI now launches big conversion jobs through a spawned worker subprocess
- on Windows, that worker may itself launch additional `spawn` worker processes for parallel FBX prototype import
- the primary `dist-next` one-file package reuses `XMLtoUSDAConverter.exe` for packaged `fbx-worker` helper mode instead of requiring a sidecar worker executable
- this is why `.venv310`, `multiprocessing.freeze_support()`, and a real file-backed Python entry point matter for stress tests and packaged builds

## Runtime temp files and cache hygiene

- UI settings remain separate from runtime conversion temp data
- runtime conversion temp data lives under `%LOCALAPPDATA%/XMLtoUSDAConverter/cache/jobs`
- default runtime behavior is `ephemeral`: per-job temp dirs are removed on success, cancel, and failure
- the GUI `Preserve temp files for debugging` switch and CLI `--preserve-temp-files` flag keep the job dir and manifest on disk for investigation
- stale job dirs older than 24 hours are cleaned during startup sweep
- GUI-side runtime errors are appended to `~/.xml_to_usda/gui_runtime.log` so failures can be reviewed later without relying on modal popups
- build artifacts such as `build/`, `build-next/`, `dist/`, and `dist-next/` are not part of runtime cache hygiene and are only cleaned by build helpers

## Recreate the environment

If the primary FBX-capable environment is broken or out of sync:

```powershell
deactivate
Remove-Item -Recurse -Force .\.venv310
py -3.10 -m venv .venv310
.\.venv310\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[dev]
python -m pip install "C:\Program Files\Autodesk\FBX\FBX Python SDK\2020.3.4\fbx-2020.3.4-cp310-none-win_amd64.whl"
```

## Expected rule

Use the activated `.venv310` for all normal project commands unless a task explicitly requires interpreter comparison.

Do not rely on globally installed `pytest`, globally installed project packages, or a global Autodesk FBX module outside the workspace workflow.
