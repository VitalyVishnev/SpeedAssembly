# Experiments

This page stores rejected, superseded, or otherwise non-current approaches that still matter because they explain why the present contract exists.

## Experiment: Proxy simplification by deterministic face sampling

Status: Rejected

Context:
Face sampling was tested as a cheaper alternative to QEM for proxy geometry.

Outcome:
It produced disconnected triangle clouds and broke the proxy topology contract.

Keep:
Use QEM through `fast-simplification` for proxy simplification.

Related files:
- `docs/raw/DECISIONS.md`
- `docs/wiki/known-bugs.md`

## Experiment: Fracture Preview on a Qt background thread

Status: Superseded

Context:
An earlier version used a Qt-owned background thread for Fracture Preview.

Outcome:
Process isolation replaced it after native crashes were observed.

Keep:
Use isolated worker processes for preview work that can fail natively.

Related files:
- `docs/raw/DECISIONS.md`
- `docs/raw/ARCHITECTURE.md`
- `docs/wiki/known-bugs.md`

## Experiment: Packaged sidecar worker executable

Status: Superseded

Context:
The packaged release briefly used a separate worker executable.

Outcome:
The current release reuses the main executable in worker mode instead.

Keep:
Worker commands must still stay before Qt bootstrap.

Related files:
- `docs/raw/DECISIONS.md`
- `docs/raw/troubleshooting.md`
- `docs/wiki/known-bugs.md`

## Experiment: Single-pass UV rewrite in the normalizer

Status: Rejected

Context:
Several normalizer micro-rewrites tried to collapse UV authoring into fewer passes.

Outcome:
The rewritten path was slower on the large `BigSpruce` sample.

Keep:
Keep the faster split path and profile real samples before changing it again.

Related files:
- `docs/raw/REFRACTOR_LOG.md`
- `docs/wiki/known-bugs.md`

## Experiment: Local loop and child-scan micro-optimizations in the normalizer

Status: Rejected

Context:
Several local binding, child-scan, and payload-precompute tweaks were tried on the hot path.

Outcome:
They did not produce a stable improvement on the large sample and were reverted.

Keep:
Prefer changes that remove duplicate XML work over clever local rewrites.

Related files:
- `docs/raw/REFRACTOR_LOG.md`
- `docs/wiki/known-bugs.md`

## Experiment: Automatic trunk-chain and synthetic fracture fill

Status: Superseded

Context:
Earlier automatic fracturing tried to reach the requested piece count by refining hierarchy joints and, when needed, splitting base faces spatially.

Outcome:
On simple trees this could shred one trunk section while leaving the upper tree intact. V1 replaces this with natural weak-point detachment only: stump, independent stems, and branch bases ranked by skeleton length plus optional height bias.

Keep:
Manual cuts remain the explicit escape hatch for trunk or mid-segment cuts. Automatic fill clamps with a diagnostic when safe branch candidates run out.

Related files:
- `src/xml_to_usda/fracture_service.py`
- `docs/wiki/decisions.md`
