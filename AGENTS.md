# AGENTS.md

## Mission

Build a deterministic converter from SpeedTree Raw XML to USDA for the UE 5.7.x vegetation pipeline. This is not a generic XML-to-USD tool.
## Read Order

Use these docs in this order:

1. `docs/ue_import_contract.md`
2. `docs/speedtree_mapping.md`
3. `docs/workflow_status.md`
4. `docs/local-python-environment.md`

If they conflict, this order wins.

For architecture reviews, use:

1. `docs/PROJECT_MAP.md`
2. `docs/GLOSSARY.md`
3. `docs/ARCHITECTURE.md`
4. `docs/DECISIONS.md`

## Source Of Truth

When docs conflict with reality, trust:

1. Actual successful import in UE 5.7.x
2. UE local schema files
3. UE importer/plugin source
4. Official Epic docs/tutorials/forum replies from Epic staff
5. OpenUSD docs
6. Real SpeedTree XML samples
7. Community sources only as hints

If theory and UE behavior disagree, UE behavior wins.

## Core Rules

- Do not invent UE schema names, USD attributes, relationship names, XML field meanings, or transform conventions.
- Do not write USDA directly from raw XML traversal. Keep parsing, normalization, resolution, validation, and authoring separate.
- The same input plus the same config must produce the same logical USDA output.
- If required structural, architectural, or importer-contract decisions are unresolved, stop and ask before coding.
- Keep side effects at the edges. Keep core transformation logic deterministic and inspectable.
- Minimize hidden mutable state.
- If Goal is active, do not finish goal after first iteration.
- After all code changes run build: "$ & '.\scripts\build_qt_gui_exe.cmd' -Package"
- Don't use unnecessary words, talk short and professional.

## Simplicity and Architecture Requirements

1. Prefer the simplest working solution. Use the least necessary complexity. After each change, do one simplification pass. Do not add abstraction, configuration, indirection, or generic systems unless they solve a real current need.
2. Aim for deep modules, not shallow ones. Keep interfaces small and meaningful. Avoid layers, wrappers, and concepts that do not remove complexity. Prefer fewer strong boundaries over many weak ones.
3. Track postponed issues explicitly. If a known problem, limitation, incomplete edge case, technical debt item, or "fix later" item remains after a change, record it in `KNOWN_PROBLEMS.md` with the issue, location, reason for deferral, and likely next step.

## Fail Loudly

If the converter cannot safely determine skeleton hierarchy, prototype identity, instance transforms, required UE schema fields, or binding data, fail loudly. Say what failed, where it failed, and which assumption is missing. Do not emit broken USDA.

## Validation

Importer-facing changes are not done until they are covered by tests and validated in UE 5.7.x. For fixed XML and config, output must stay logically stable, skeleton topology must match, and instance counts must match. Compare against `vault` examples when useful.

## Forbidden Shortcuts

- Guess UE schema attributes from memory
- Bake repeated Assembly Parts into unique meshes
- Call a static assembly skeletal
- Encode unresolved behavior in undocumented hardcoded branches
- Ignore `vault` examples
- Mix local, world, and source transform spaces
- Use a temporary architectural shortcut when the correct contract is still unknown
- Silently create fallback geometry without logging it
- Trust community snippets over schema inspection and working imports

additional rules

## Rule 1 — Think Before Coding
State assumptions explicitly. Ask rather than guess.
Push back when a simpler approach exists. Stop when confused.

## Rule 2 — Simplicity First
Minimum code that solves the problem. Nothing speculative.
No abstractions for single-use code.

## Rule 3 — Surgical Changes
Touch only what you must. Don't improve adjacent code.
Match existing style. Don't refactor what isn't broken.

## Rule 4 — Goal-Driven Execution
Define success criteria. Loop until verified.
Strong success criteria let Claude loop independently.

## Rule 5 — Surface conflicts, don't average them
If two patterns contradict, pick one (more recent / more tested).
Explain why. Flag the other for cleanup.
Don't blend conflicting patterns.

## Rule 6 — Read before you write
Before adding code, read exports, immediate callers, shared utilities.
If unsure why existing code is structured a certain way, ask.

## Rule 7 — Tests verify intent, not just behavior
Tests must encode WHY behavior matters, not just WHAT it does.
A test that can't fail when business logic changes is wrong.

## Rule 8 — Match the codebase's conventions, even if you disagree
Conformance > taste inside the codebase.
If you think a convention is harmful, surface it. Don't fork it silently.

## Final Rule

If forced to choose between elegant abstraction, theoretical correctness, and what UE 5.7 actually imports, choose what UE 5.7 actually imports.
