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
python scripts/check_documentation.py
.\scripts\preview_documentation.cmd
```

After navigation changes, run the optional browser contract with Playwright
available to Node.js and a browser installed. Set `DOCS_BROWSER_CHANNEL=msedge`
to use an existing Microsoft Edge installation on Windows.

```powershell
node scripts/check_documentation_navigation.cjs site check 240
node scripts/check_documentation_navigation.cjs site click 120
node scripts/check_documentation_navigation.cjs site hover 120
```

The last two commands measure seven cold-target transitions with a 120 ms
server delay and report click-to-article-paint medians. `hover` gives preloading
500 ms before clicking. Run against a separately saved baseline build to
compare changes; these measurements do not represent deployed Pages latency.

The [engineering wiki](docs/wiki/index.md) records architecture, contracts,
known limitations, and validation evidence. Public documentation lives in
`docs/user/`; GitHub Actions publishes it independently of the application.

Write public user documentation in English first. Unsuffixed `.md` files are
the authoritative originals; sibling `.ru.md` files are Russian translations
only. Keep technical identifiers, UI labels, explicit anchors, and link/image
paths aligned with the original. When an English page changes, review its
translation in the same change.

Russian guides use the language of 3D artists. Keep familiar terms such as
workflow, pipeline, pivot, viewport, skinning, bounds, distance fields, and
shadow proxy in English, alongside exact UI labels. Adapt general descriptions
naturally; keep procedures, structure, constraints, numbers, and formulas close
to the English source. Describe what an artist creates or does, without formal
phrases such as "computational cost" where "simplified mesh" says enough.

ENG is the default at the existing site URLs. RU uses `/ru/`; the header
switches languages without changing the article. Pages without a Russian
translation show English content with a Russian notice. To add a translation,
create `article.ru.md` beside `article.md`; navigation continues to reference
`article.md`. Theme overrides live in `docs/overrides/`, outside public sources.

Paths in engineering documents are relative to `Project/` unless stated
otherwise. Historical notes in `docs/raw/` may describe the former layout.

The local `LICENSE` copy is included in Python source distributions and
application release ZIPs and must match the repository-root license.
