# Golden Sample Workflow

## Purpose

Use one intentionally simple SpeedTree 10 tree as the baseline experiment for proving the XML -> USDA -> UE path.

## Controlled tree shape

The preferred baseline sample should contain:
- one trunk/base mesh
- a few primary branches
- a few secondary branches
- two leaf meshes reused as instances
- enough structure to make skeleton and instance binding visible in UE

## Export workflow

For the same tree, export multiple XML variants with different export settings. For each variant:
1. place the raw XML into `samples/speedtree/simple_tree/variants/`
2. record the export settings and notes next to it
3. generate an inspect report
4. compare observed sections, skeleton data, and leaf reference structure
5. decide which profile is the strongest baseline for the project

## Expected artifacts

- source XML variants under `samples/speedtree/simple_tree/variants/`
- expected inspect outputs under `samples/expected_reports/`
- generated USDA snapshots under `samples/expected_usda/`
- notes about differences in `vault/speedtree_export_matrix/` or project docs

## Selection criteria

Prefer the export profile that gives:
- explicit skeleton information
- recoverable leaf instance transforms
- stable mesh/prototype identity
- minimum ambiguity around branch hierarchy and object grouping
