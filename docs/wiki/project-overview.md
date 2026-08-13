# Project Overview

SpeedAssembly is a deterministic converter from SpeedTree Raw XML to USDA for the UE 5.7–5.8 vegetation pipeline. It is not a generic XML-to-USD tool.

The current goal is to preserve the importer contract while keeping the pipeline inspectable and deterministic. The validated primary path is `skeletal_assembly` (Skeletal Assembly, or `Skeletal Mesh Nanite Assembly`). `static_assembly` is supported as a secondary export shape (`Static Mesh Nanite Assembly`), but it must not redefine the skeletal contract.

The two parts-library modes write one USDA per resolved Repeated Part prototype:
`skeletal_parts` keeps the local Part Skeleton, while inline `static_parts`
payloads become plain static meshes without assembly, instancing, skeleton, or
skinning fields. Static parts have been imported and reused by a full Static
Assembly through Unreal Reference in the current Unreal target workflow.

The standalone release is named `SpeedAssembly.exe` and its release bundle is
`SpeedAssembly_release.zip`. The release ZIP contains the executable, MIT
`LICENSE`, `THIRD_PARTY_NOTICES.md`, and `examples/SimpleTree_01.xml`;
`build_info.json` remains beside the executable
in `dist-next` for local diagnostics and is not distributed. The primary
baseline workflow has been manually confirmed in UE 5.7 and UE 5.8. Proxy Mesh
is a companion Static Mesh workflow for collision, distance-field, and
lower-cost shadow use; detailed lighting quality validation remains separate
from import confirmation.

The maintained memory split is:

- [Architecture](architecture.md)
- [Decisions](decisions.md)
- [Known Bugs](known-bugs.md)
- [Encountered Crashes](encountered-crashes.md)
- [Experiments](experiments.md)
- [Glossary](glossary.md)
- [Test Policy](testing.md)

Current working assumptions:

- the baseline sample is `samples/speedtree/simple_tree/variants/SimpleTree_01.xml`
- the supported desktop shell is PySide6
- the canonical local Python environment is `.venv310`
- raw historical documentation lives in `docs/raw/`

What a new agent should understand first:

1. Read `AGENTS.md`.
2. Read this wiki index and the other maintained wiki pages.
3. Read the raw importer-contract docs only when the task needs source-level detail.
4. Do not invent UE schema behavior, XML meanings, or transform rules.
5. Fail loudly if the skeleton, prototype identity, transforms, or binding data cannot be determined safely.
