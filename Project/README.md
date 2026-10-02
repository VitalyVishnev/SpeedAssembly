# SpeedAssembly development

SpeedAssembly converts SpeedTree Raw XML into USDA for the Unreal Engine
vegetation pipeline. See the [program overview](../README.md) for features
and downloads.

Application source, tests, samples, build scripts, and documentation live in
this directory. Run Python, pytest, and MkDocs commands from `Project/`.
The local Python environment stays in `.venv310/` at the repository root.

## Setup

From the repository root on Windows, with Python 3.10 and MSVC build tools:

```powershell
py -3.10 -m venv .venv310
.\.venv310\Scripts\Activate.ps1
python -m pip install -e './Project[dev,ui-next]'
cd Project
python -m xml_to_usda gui
```

After relocating an existing checkout, rerun the editable install so it points
to `Project/src`.

## Tests and builds

From `Project/`:

```powershell
.\scripts\run_tests.cmd Full
.\scripts\build_qt_gui_exe.cmd -Quick
.\scripts\build_qt_gui_exe.cmd -Package
```

Quick creates a source-backed preview in `dist-preview/`. Package builds the
standalone executable and release ZIP in `dist-next/`, runs packaged contracts,
and validates real results through the packaged smoke tests.

## Versions and release drafts

Edit only `src/xml_to_usda/version.py::__version__` when a new release version
is explicitly requested. Full builds preserve it. Setuptools derives the Python
package version; packaging embeds the same application version and portable Git
commit/time identity in the EXE. The top bar and About display it, and source
previews add DEV. `SpeedAssembly.exe --build-info PATH` writes that build's
identity as JSON without opening Qt.

After the full test/Package gate, prepare a GitHub draft with a `v`-prefixed tag
on the exact source commit, title `SpeedAssembly v<version>`, the verified ZIP,
and a short bullet-only change list. Mark alpha/beta/rc as Pre-release. The
operator reviews and publishes manually; published tags/assets are preserved.

## Documentation

```powershell
python -m pip install -r requirements-docs.txt
python -m mkdocs build --strict
.\scripts\preview_documentation.cmd
```

The [engineering wiki](docs/wiki/index.md) records architecture, contracts,
known limitations, and validation evidence. Public documentation lives in
`docs/user/`; GitHub Actions publishes it independently of the application.

Paths in engineering documents are relative to `Project/` unless stated
otherwise. Historical notes in `docs/raw/` may describe the former layout.

The local `LICENSE` copy is included in Python source distributions and
application release ZIPs and must match the repository-root license.
