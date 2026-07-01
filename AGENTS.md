# AGENTS.md

## Mission

Build a deterministic converter from SpeedTree Raw XML to USDA for the UE 5.7.x vegetation pipeline. This is not a generic XML-to-USD tool.

## Read Order

Use these maintained docs in this order:

1. `docs/wiki/index.md`
2. `docs/wiki/project-overview.md`
3. `docs/wiki/architecture.md`
4. `docs/wiki/decisions.md`
5. `docs/wiki/known-bugs.md`
6. `docs/wiki/experiments.md`
7. `docs/wiki/glossary.md`

For importer-facing contract details, read these raw source docs next:

1. `docs/raw/ue_import_contract.md`
2. `docs/raw/speedtree_mapping.md`
3. `docs/raw/workflow_status.md`
4. `docs/raw/local-python-environment.md`

If they conflict, this order wins.

For architecture reviews, use:

1. `docs/wiki/architecture.md`
2. `docs/wiki/glossary.md`
3. `docs/wiki/decisions.md`
4. `docs/raw/PROJECT_MAP.md`
5. `docs/raw/GLOSSARY.md`
6. `docs/raw/ARCHITECTURE.md`
7. `docs/raw/DECISIONS.md`

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

## Project Memory / LLM Wiki

This repository uses an LLM Wiki-style documentation system.

Before meaningful changes, read the maintained wiki pages listed in `Read Order`.

Documentation roles:

- `docs/raw/` contains original or historical source material. Do not edit files in `docs/raw/` unless explicitly asked.
- `docs/wiki/` contains maintained project memory. Keep it concise, current, and useful for future agents.
- `docs/log.md` records meaningful documentation updates.

After meaningful project changes:

- update the relevant page in `docs/wiki/`
- add important new decisions to `docs/wiki/decisions.md`
- add new bugs, limitations, or failed approaches to `docs/wiki/known-bugs.md`
- add experiments or uncertain ideas to `docs/wiki/experiments.md`
- append a short entry to `docs/log.md`

Rules:

- Do not invent facts.
- If something is uncertain, mark it as `Unverified`.
- Prefer compact summaries over long duplicated text.
- Preserve rejected approaches if they explain why the current solution exists.
- Keep raw sources separate from maintained wiki pages.

## Core Rules

- Do not invent UE schema names, USD attributes, relationship names, XML field meanings, or transform conventions.
- Do not write USDA directly from raw XML traversal. Keep parsing, normalization, resolution, validation, and authoring separate.
- The same input plus the same config must produce the same logical USDA output.
- If required structural, architectural, or importer-contract decisions are unresolved, stop and ask before coding.
- Keep side effects at the edges. Keep core transformation logic deterministic and inspectable.
- Minimize hidden mutable state.
- If Goal is active, do not finish goal after first iteration.
- After all code changes run build: "$ & '.\scripts\build_qt_gui_exe.cmd' -Package"; packaged high-risk smoke is part of this gate. If `-SkipSmoke` is used, report the reason explicitly.
- Don't use unnecessary words, talk short and professional.
- Не делай костыли, сделай сразу систему так, чтобы работала. Чтобы не пришлось переделывать.
- Переиспользуй готовые решения, которые есть в проекте, не изобретай велосипед.
- For subagents use GPT-5.4 mini (medium).
- Use ponytail skill by default.

## Simplicity and Architecture Requirements

1. Prefer the simplest working solution. Use the least necessary complexity. After each change, do one simplification pass. Do not add abstraction, configuration, indirection, or generic systems unless they solve a real current need.
2. Aim for deep modules, not shallow ones. Keep interfaces small and meaningful. Avoid layers, wrappers, and concepts that do not remove complexity. Prefer fewer strong boundaries over many weak ones.
3. Track postponed issues explicitly. If a known problem, limitation, incomplete edge case, technical debt item, or "fix later" item remains after a change, record it in `docs/wiki/known-bugs.md` with the issue, location, reason for deferral, and likely next step. Use `docs/wiki/decisions.md` for current contracts and `docs/wiki/experiments.md` for rejected or superseded approaches. Do not maintain a separate active root `KNOWN_PROBLEMS.md`; it is legacy-only.

## Fail Loudly

If the converter cannot safely determine skeleton hierarchy, prototype identity, instance transforms, required UE schema fields, or binding data, fail loudly. Say what failed, where it failed, and which assumption is missing. Do not emit broken USDA.

## Validation

Importer-facing changes are not done until they are covered by tests and validated in UE 5.7.x. For fixed XML and config, output must stay logically stable, skeleton topology must match, and instance counts must match. Compare against `vault` examples when useful.

Test density should stay practical. Preserve existing tests, but do not add or rewrite tests after every small edit, polish pass, or experiment iteration. Add the smallest useful test only when behavior becomes a stable feature, a new module or public contract is introduced, or an importer-facing invariant could regress silently. Prefer broad intent-level regression checks over exhaustive case-by-case encoding; when such a test fails, inspect the code to find the precise cause.

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

## Additional Rules

### Rule 1 - Think Before Coding
State assumptions explicitly. Ask rather than guess.
Push back when a simpler approach exists. Stop when confused.

### Rule 2 - Simplicity First
Minimum code that solves the problem. Nothing speculative.
No abstractions for single-use code.

### Rule 3 - Surgical Changes
Touch only what you must. Don't improve adjacent code.
Match existing style. Don't refactor what isn't broken.

### Rule 4 - Goal-Driven Execution
Define success criteria. Loop until verified.
Strong success criteria let Claude loop independently.

### Rule 5 - Surface conflicts, don't average them
If two patterns contradict, pick one (more recent / more tested).
Explain why. Flag the other for cleanup.
Don't blend conflicting patterns.

### Rule 6 - Read before you write
Before adding code, read exports, immediate callers, shared utilities.
If unsure why existing code is structured a certain way, ask.

### Rule 7 - Tests verify intent, not just behavior
Tests must encode WHY behavior matters, not just WHAT it does.
A test that can't fail when business logic changes is wrong.
Do not test every implementation detail or every intermediate experiment.
For simple edits, run the relevant existing checks instead of creating new tests by default.

### Rule 8 - Match the codebase's conventions, even if you disagree
Conformance > taste inside the codebase.
If you think a convention is harmful, surface it. Don't fork it silently.

## Final Rule

If forced to choose between elegant abstraction, theoretical correctness, and what UE 5.7 actually imports, choose what UE 5.7 actually imports.
