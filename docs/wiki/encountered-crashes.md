# Encountered Crashes

This ledger preserves native/process failures after their immediate fix so
recurring classes can be solved systemically. `Known Bugs` remains the list of
current risks; this page keeps both resolved and open incidents.

Evidence labels:

- `Confirmed` - the failing boundary and cause were reproduced or directly
  identified by a stack/dump.
- `Strong` - logs isolate the boundary and the fix removes the failure, but no
  native dump proves the final instruction.
- `Unverified` - a plausible hypothesis only; do not present it as root cause.

## Crash classes

- `NATIVE-LIFETIME` - native objects outlive their safe owner/session.
- `GLOBAL-STATE` - process-global mutation crosses tests, threads, or workers.
- `WORKER-MEMORY` - payload expansion or serialization exhausts a worker.
- `WORKER-CACHE` - reconstructed cached arrays cross an unstable native/runtime boundary.
- `GPU-LIFECYCLE` - OpenGL work occurs outside Qt's current-context lifecycle.
- `GPU-PRESSURE` - viewport expansion or command volume overwhelms the render path.
- `PACKAGE-NATIVE` - frozen dependency/binary composition changes native stability.

## Incidents

### CR-001 - Wind Preview used a divergent viewport upload path

- Date: 2026-07-05
- Status/evidence: Resolved / Strong
- Signature: packaged Wind Preview viewport terminated while opening/rendering.
- Boundary: Qt/OpenGL GUI process.
- Class: `GPU-LIFECYCLE`
- Cause/fix: removed the Wind-only upload path and routed static precompute and
  upload through shared `MatcapViewport`; packaged Wind smoke guards opening,
  upload, and bone overlay.

### CR-002 - Frozen Wind worker native dependency instability

- Date: 2026-07-10
- Status/evidence: Resolved / Strong
- Signature: packaged Wind Preview worker exited natively at startup.
- Boundary: frozen worker process.
- Class: `PACKAGE-NATIVE`
- Cause/fix: the SpeedTree XML path was coupled to unused External FBX/USD
  imports and an oversized OpenUSD hook. The paths were separated and the hook
  was narrowed to runtime `Usd`/`UsdSkel` dependencies.

### CR-003 - Big Spruce Wind payload exceeded practical process memory

- Date: 2026-07-11
- Status/evidence: Resolved / Confirmed
- Signature: worker grew past 5 GB, then exited with `0xC0000005`.
- Boundary: Wind Preview worker serialization/scene construction.
- Class: `WORKER-MEMORY`
- Cause/fix: stopped returning the full canonical model beside the scene,
  reused one face-range table, and bounded interactive repeated geometry. The
  result became a compact payload while retaining all logical placements.

### CR-004 - Manifold session lifetime combined with global tempfile mutation

- Date: 2026-07-17
- Status/evidence: Resolved / Confirmed
- Signature: full-suite native instability required Boolean tests followed by a
  cache-maintenance test and another Boolean test.
- Boundary: one pytest process containing Manifold/oneTBB and cache tests.
- Classes: `NATIVE-LIFETIME`, `GLOBAL-STATE`
- Cause/fix: native Manifold sessions survived beyond their intended work and
  a test monkeypatched the singleton stdlib `tempfile` module. Sessions now
  close deterministically; tests patch only the project temp-root seam. The
  minimal combination and full suite passed afterward.

### CR-005 - Fracture buffer upload outside `paintGL`

- Date: 2026-07-17
- Status/evidence: Resolved / Strong
- Signature: rapid Detailed Cuts replacement ended after
  `viewport.upload_end`, before `set_preview` returned.
- Boundary: Qt/OpenGL GUI process; Fracture worker completed normally.
- Class: `GPU-LIFECYCLE`
- Cause/fix: callbacks no longer force `makeCurrent()`/buffer upload/
  `doneCurrent()`. They mark buffers dirty and Qt performs upload in `paintGL`.
  Packaged rapid-toggle smoke guards this boundary.

### CR-006 - Fracture typed source-cache reconstruction

- Date: 2026-07-17
- Status/evidence: Resolved / Confirmed
- Signature: packaged worker `0xC0000005` while garbage-collecting/iterating
  cached arrays in `_mesh_from_arrays`.
- Boundary: persistent Fracture Preview worker.
- Class: `WORKER-CACHE`
- Cause/fix: removed production `.npz` reconstruction. A clean worker reads XML
  once and retains the slim source model in memory; recovery starts cleanly
  from XML. Packaged stability and crash-recovery smoke guard the worker path.

### CR-007 - Flattened Repeated Parts exhausted viewport memory

- Date: 2026-07-17
- Status/evidence: Resolved / Strong
- Signature: 3613 instances expanded to about 2.07 GB of vertex data; the GUI
  later disappeared while inspecting the viewport.
- Boundary: Qt/OpenGL GUI process.
- Class: `GPU-PRESSURE`
- Cause/fix: unique source geometry is uploaded once and placements remain
  instances. The upload guard measures unique bytes, not logical triangles.

### CR-008 - Per-instance OpenGL command loop after preserved instancing

- Date: 2026-07-17
- Status/evidence: Mitigated in code / Strong boundary, unverified root cause
- Signature: the Fracture worker completed and returned all 3613 instances;
  the GUI later disappeared immediately after a viewport-ready result. No WER
  event or dump was produced, and the worker remained orphaned.
- Boundary: Qt/OpenGL GUI process after scene delivery.
- Class: `GPU-PRESSURE`
- Current hypothesis: geometry was instanced in memory, but the renderer still
  issued 3613 transform/uniform/draw sequences every frame.
- Current behavior: transforms are batched into one GPU instance buffer and the
  renderer issues one hardware-instanced draw per unique source mesh. The
  packaged Big Spruce rapid-settings scenario passed three consecutive runs
  with all 3613 instances and no retry. Keep status open until operator use
  confirms the crash is gone.

### CR-009 - Mutable material lookup failed during Detailed Cuts attribute transfer

- Date: 2026-07-17
- Status/evidence: Superseded by CR-010 / Traceback confirmed, trigger unverified
- Signature: handled worker error `'int' object does not support item assignment`
  in `_attributed_mesh_data`; this was not a native process crash.
- Boundary: Fracture Preview worker while transferring source material IDs to
  Big Spruce Detailed Cuts output.
- Class: Unclassified Python state corruption or stale frozen runtime.
- Evidence: the reported frozen traceback points to assignment into a local
  material lookup. The exact settings and a Detailed/flat/Detailed sequence do
  not reproduce the failure on current source.
- The atomic lookup avoids one unsafe mutation but did not explain later
  unrelated native and Python failures in the same persistent worker. It is
  retained as deterministic code, not treated as the crash fix.

### CR-010 - Persistent Detailed Cuts worker produced unrelated heap-corruption signatures

- Date: 2026-07-17
- Status/evidence: Mitigated / Strong boundary, native instruction unverified
- Signature: Big Spruce preview produced `0xC0000005` in XML normalization and
  source limits, a `dictobject.c:1605` internal error during attribute
  transfer, and a float-index TypeError in normalizer code. These locations
  cannot share a normal input-validation cause.
- Boundary: long-lived Fracture Preview worker after native Manifold work.
- Class: `NATIVE-LIFETIME`
- Cause/fix: the exact native instruction is unverified. The persistent worker
  retained native Boolean state across requests, allowing a later request to
  observe corruption. Detailed/flat previews now run in one fresh worker per
  request; latest-request coalescing remains in the GUI, so requests do not
  overlap.
- Regression gate: focused worker-lifecycle tests plus repeated packaged Big
  Spruce interactive and rapid-settings smoke. A worker crash or retry fails
  the gate.

### CR-011 - Intermittent cross-process access violations after fresh-worker isolation

- Date: 2026-07-19
- Status/evidence: Open / Strong external context, application-local cause unverified
- Signature: the GUI runtime log records two Big Spruce Detailed Cuts requests
  at 03:58 and 03:59 with neither a result nor a handled worker error. Historic
  Windows Error Reporting records also contain access violations in the former
  `XMLtoUSDAConverter.exe`/`python310.dll`, standalone Python, PowerShell, and
  `AppXSvc`/`msxml6.dll`; WER retains older `0x3B` and LiveKernelEvent 141
  reports as additional system-context evidence.
- Boundary: unknown for the current request. The old
  `xml_to_usda_fracture_preview_server_*` artifacts belong to the retired
  persistent-worker executable, not the current one-request-worker build.
- Class: Unclassified external/system context.
- Cause: Unverified. There are no WHEA hardware-error events in the preceding
  14 days, so RAM/CPU failure is not established. A driver, injected process,
  stale executable, or an application-native defect remain possible.
- Fix/workaround: no code change claimed. On the next reproduction, retain the
  exact executable path/build ID, worker stderr, and matching WER Event 1000/
  1001 before assigning a process boundary. Test the current packaged
  `SpeedAssembly.exe`, not a retained `XMLtoUSDAConverter.exe`.
- 2026-07-24 observation: an interactive `python.exe` process displayed a
  null-address write error after Fracture Preview had already logged a complete
  38-piece viewport result. No dump, WER event, or surviving process identified
  the failing boundary, and the operator reported regular instability in other
  computer workloads. This remains system-context evidence, not an
  application-local root cause; no speculative code change was made.

## System rules derived from the incidents

1. Keep heavy/native geometry in crash-isolated workers; when a native backend
   shows nondeterministic heap faults, use a fresh worker per interactive
   request. Keep Qt/OpenGL in the GUI process and only inside Qt's
   current-context callbacks.
2. Never mutate stdlib or dependency singleton state in tests; patch a narrow
   project seam.
3. Budget transported bytes, unique uploaded bytes, instance count, and GPU
   command count separately. Logical triangle count alone is insufficient.
4. A worker retry is containment, not a fix. Preserve stderr/faulthandler
   evidence and keep repeated failure fail-loud.
5. Do not mark a native crash resolved from a passing unit test alone; require
   the packaged boundary that previously failed.
6. Keep system-level evidence separate from an application-local root cause:
   unrelated-process access violations are diagnostic context, not proof that
   the converter is fixed or at fault.
