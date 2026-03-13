# XML to USDA Converter

Deterministic converter for SpeedTree Raw XML that emits USDA targeting Unreal Engine 5.7 skeletal Nanite Assembly import.

## Current baseline

The active reverse-engineering baseline is:

- `samples/speedtree/simple_tree/variants/SimpleTree_01.xml`

This sample is treated as the single source sample for the current milestone. The converter is now built around:

- explicit object hierarchy parsing
- trunk-first base mesh selection
- real `Bones/Bone` skeleton extraction
- explicit leaf `BoneID` and `MeshID` bindings
- optional `Spine` parsing for validation and future wind work

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
python -m xml_to_usda inspect .\samples\speedtree\simple_tree\variants\SimpleTree_01.xml
python -m xml_to_usda convert .\samples\speedtree\simple_tree\variants\SimpleTree_01.xml .\samples\expected_usda\SimpleTree_01.generated.usda
python -m xml_to_usda gui
```

If commands fail after dependency installation, the usual cause is that `.venv` is not activated in the current PowerShell session.

## Commands

```powershell
python -m xml_to_usda inspect path\to\tree.xml
python -m xml_to_usda convert path\to\tree.xml path\to\tree.usda
python -m xml_to_usda gui
```

## Current scope

- `inspect` reports object-class counts, hierarchy depth, spine coverage, and leaf `BoneID` / `MeshID` distributions.
- normalization builds an explicit internal model with source objects, branch segments, mesh library entries, leaf instances, and optional spines.
- USDA writing uses a real trunk mesh, `Skeleton`, leaf prototypes, and `PointInstancer` binding arrays authored from XML `BoneID` values.
- writer emits `elementSize = 1` on Unreal skeletal assembly binding primvars.
- strict validation fails on missing trunk geometry, missing skeleton data, missing explicit leaf bindings, and inconsistent packed arrays.

## Current phases

- `Phase 1`: one verified SimpleTree baseline and deterministic XML -> USDA pipeline
- `Phase 2`: thin desktop GUI and later `exe` packaging
- `Phase 3`: external branch reuse from existing Unreal Engine project assets
- `Phase 4`: Dynamic Wind JSON generation

## Repo areas

- `samples/` holds controlled XML inputs and expected outputs.
- `docs/` holds observed schema notes, workflow notes, and local environment setup.
- `vault/` holds immutable third-party or engine-side references.

## Reference docs

- `docs/local-python-environment.md`
- `docs/project-roadmap.md`
- `docs/golden-sample-workflow.md`
- `docs/speedtree_xml_observed_schema.md`
- `docs/ue_schema_notes.md`
