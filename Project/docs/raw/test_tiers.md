# Test Tiers

The suite is split by cost, not by taste.

## Default

Fast, always-on regression coverage:

```powershell
python -m pytest -q
```

This is the normal developer gate.

## Qt

Qt workflow coverage. Runs with the default suite when `PySide6` and `pytest-qt`
are installed, and can be selected explicitly:

```powershell
python -m pytest -q -m qt
```

## Stress

Heavy or optional runtime checks. These stay out of the normal loop and are
run only when requested:

```powershell
python -m pytest -q -m stress
```

Some stress checks also require an environment path:

```powershell
$env:XMLTOUSDA_RUN_PERF = "1"
$env:XMLTOUSDA_HEAVY_FBX_STRESS_PATH = "D:\path\to\big.fbx"
python -m pytest -q -m stress
```

## UE Manual

Manual UE 5.7 import validation. Not a pytest tier.

- Follow [docs/workflow_status.md](/D:/3D%20Personal/VibeCode/XMLtoUSDAconverter/docs/workflow_status.md)
- Follow [docs/stage0_stress_validation.md](/D:/3D%20Personal/VibeCode/XMLtoUSDAconverter/docs/stage0_stress_validation.md)
- Record any new importer contract in the docs before generalizing
