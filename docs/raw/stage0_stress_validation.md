# Stage 0 Stress Validation

## Role

This document is the required manual stress-validation procedure for `Stage 0`.

It covers the large real production tree that is **not** stored in the repository and therefore cannot be protected by committed `pytest` fixtures alone.

This procedure is part of `Stage 0` acceptance.

## Purpose

The automated suite protects committed fixtures and execution contracts.

This manual procedure protects the current real-world heavy-job behavior:

- launcher or venv GUI stability
- subprocess conversion stability
- runtime manifest behavior
- partial-output cleanup behavior
- top-level operator-visible result on the real huge tree

## Required environment

Use these defaults unless a validated production workflow requires otherwise:

- Python environment: `.venv310`
- runtime: launcher or venv GUI
- CPU profile: `balanced`
- cleanup policy: `preserve temp files for debugging` enabled

If a fresh packaged GUI build already exists for the current branch, run the packaged check too.
If no fresh packaged build exists, the blocking `Stage 0` requirement is the launcher or venv GUI run.

## Required input

Use the current large real production tree outside the repository.

This document intentionally does not hardcode its external disk path into repo docs.

Record the tree identifier or local file name in the validation record.

## Launcher procedure

1. Activate `.venv310`.
2. Launch the GUI from the project environment.
3. Load the large production XML tree.
4. Configure the same heavy prototype replacements used in the known working stress scenario, if that scenario depends on explicit replacements.
5. Keep `CPU Profile = balanced` unless the validation goal explicitly requires another profile.
6. Enable `Preserve temp files for debugging`.
7. Start conversion and let it complete, cancel, or fail naturally.
8. Record the wall-clock duration from start to final visible outcome.
9. Record whether the conversion used the background subprocess path.
10. Record the runtime job directory and `job_manifest.json` path if temp preservation is enabled.
11. Record whether any `.partial` USDA file remained after completion, cancellation, or failure.
12. Record the top-level diagnostics summary visible to the operator.

## Optional packaged procedure

Run this only when a fresh packaged GUI build exists for the current branch.

1. Launch the packaged executable.
2. Repeat the same heavy-job scenario used in the launcher validation.
3. Record the same outputs as the launcher run.
4. Note whether packaged behavior differs from launcher behavior.

Packaged validation is strongly recommended when available, but launcher validation remains the blocking minimum when no fresh package build exists.

## Required record fields

Every `Stage 0` stress run must record:

- date and time
- branch or commit
- input tree identifier or filename
- launcher or packaged runtime
- CPU profile
- whether subprocess execution was used
- whether explicit heavy prototype replacements were used
- duration
- final status:
  - succeeded
  - cancelled
  - failed
- runtime job directory
- manifest path
- whether `.partial` cleanup was correct
- top-level diagnostics summary

## Validation record template

Copy this template into the engineer's working notes, PR notes, or validation log:

```text
Stage 0 stress validation
Date:
Branch/commit:
Runtime: launcher | packaged
Input tree:
CPU profile:
Subprocess used: yes | no
Heavy prototype replacements used: yes | no
Duration:
Final status: succeeded | cancelled | failed
Runtime job dir:
Manifest path:
.partial cleanup correct: yes | no
Diagnostics summary:
Notes:
```

## Acceptance rule

`Stage 0` is not complete until at least one current-branch stress run has been recorded using this procedure.

If launcher and packaged results disagree, record the difference and treat it as an open blocker or explicitly accepted gap.
