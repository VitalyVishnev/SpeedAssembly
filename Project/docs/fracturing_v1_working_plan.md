# Fracturing V1 Working Plan

Status: Implemented; package build and Computer Use verification pending in this iteration.

## Contract

- Automatic fracturing detaches natural weak points only: stump, separate stems, and branch bases.
- Automatic trunk-chain cuts are forbidden. Trunk cuts remain available as manual cuts.
- Branch count means automatic detached branch count. Stump and separate stems are counted separately.
- Branch ranking is based on physical skeleton length from branch base to the farthest descendant tip.
- Branch height bias may favor lower or upper branches, but center remains pure length sorting.
- If safe automatic candidates run out, clamp the result and warn instead of splitting trunk geometry.
- Exploded skeleton preview must follow exploded pieces in realtime without worker rebuilds.

## Iteration Order

1. Add planner/UI tests for the new contract.
2. Implement length-based branch/stem candidates inside `fracture_service.py`.
3. Update settings persistence and Qt controls.
4. Make exploded skeleton follow piece offsets in realtime.
5. Run targeted tests and quick performance probes.
6. Package build and visually verify `SimpleTree_02_three_trunks.xml`.
7. Update maintained wiki/log with the final contract.

## Samples

- `samples/speedtree/simple_tree/variants/SimpleTree_01.xml`
- `samples/speedtree/simple_tree/variants/SimpleTree_02_three_trunks.xml`
