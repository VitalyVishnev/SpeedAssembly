# Project Overview

This project is a deterministic converter from SpeedTree Raw XML to USDA for the UE 5.7.x vegetation pipeline. It is not a generic XML-to-USD tool.

The current goal is to preserve the importer contract while keeping the pipeline inspectable and deterministic. The validated primary path is `skeletal_assembly` (Skeletal Assembly, or `Skeletal Mesh Nanite Assembly`). `static_assembly` is supported as a secondary export shape (`Static Mesh Nanite Assembly`), but it must not redefine the skeletal contract.

The maintained memory split is:

- [Architecture](architecture.md)
- [Decisions](decisions.md)
- [Known Bugs](known-bugs.md)
- [Experiments](experiments.md)
- [Glossary](glossary.md)

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
