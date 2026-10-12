# Tree hierarchy calibration

Implemented 2026-10-12 as `Auto Hierarchy (Tree)` in Advanced Wind Settings.
This is an operator comparison candidate, not a validated universal classifier.
The original Auto and PVE modes remain available. Skeleton poses, names,
topology, binding, and USDA authoring are unchanged.

## Inputs and rules

`src/xml_to_usda/wind_tree_hierarchy.py::analyze_tree_hierarchy` receives only
joint identity, parent links, and absolute bind poses. Names identify joints;
their spelling and array order do not classify them. Generator labels,
source IDs, XML endpoints, source filenames, meshes, and neighboring files are
not classification features.

- Normalize bind-pose +X. Varied axes are treated as directional bone frames,
  consistent with the Dynamic Wind +X contract. An arbitrary DCC rig whose +X
  does not describe bone direction still needs source diagnostics/UE validation.
- When axes are uniform, infer outgoing direction from the principal axis of
  direct-child attachment offsets. Degenerate axes/fork ties are marked
  ambiguous; no child wins from its name or position in the array.
- Derive downstream fork counts and subtree sizes in one reverse traversal.
- At the root, a compact group of similarly sized subtrees, or a basal plane
  of stems, can seed independent stems at level 0.
- At forks, continuation requires direction agreement and distal attachment.
  A continuing branched structure takes precedence over a terminal chain.
  Other children start the next level.
- A strong direction change can start a branch along an unbranched connection.
  Once a terminal branch has been identified, its bends do not keep creating
  groups. This prevents curved twig chains from becoming per-bone groups.

Current calibration constants: fork alignment 45 degrees, chain alignment
30 degrees, distal attachment at 95% of the parent's maximum projected child
offset, basal scale 10% of centered bounding-sphere diameter, uniform-forward variation
0.01. These are explicit geometric rules, not fitted rules keyed to species.
They remain provisional and must be reassessed against independent assets.

The existing Groups 1-10 cap merges deeper levels into the final group. Manual
layers retain precedence. GUI analysis is cached only for the loaded preview
and invalidated by every source result; unit/up-axis display transforms do not
change the input rig or assignments.

## Reference corpus and results

The operator selected every paired USDA/JSON in
`D:/3D Personal/XMLtoUSD_miscFiles/for_assembly`, plus these XMLs:
Norway Spruce 01, Willow 12 with long hierarchies removed, 03_28mil, and Big
Spruce low. JSON is the reference for prepared assets; XML Generator groups
are the reference for the explicit XML list. All compared methods receive
the same bare skeleton, with generator metadata and endpoints removed.

`scripts/benchmark_wind_hierarchy.py` writes Markdown and per-joint JSON
differences. It selects a USD Skeleton by matching reference joints, never by
largest count. It handles the documented single-root alias and reports an
importer-added synthetic root omitted by the reference separately. The corpus
fixture contains skeleton data only, with anonymous joint identifiers; no mesh,
texture, or source-path dependency enters the regression test or application.

Configured group counts match each reference. Numbers below count mismatched
labelled joints. Norway 01 XML and USDA/JSON are the same rig; exclude the XML
duplicate from the independent aggregate.

| Reference | Joints | Order | PVE | Tree |
| --- | ---: | ---: | ---: | ---: |
| Black Alder 01 | 346 | 124 | 124 | 35 |
| Black Alder 03 | 632 | 212 | 206 | 11 |
| Norway Spruce 01 | 244 | 0 | 2 | 1 |
| Norway Spruce 08 | 247 | 3 | 0 | 0 |
| Siberian Tea 01 | 34 | 0 | 0 | 0 |
| Siberian Tea 02 | 31 | 0 | 0 | 0 |
| Siberian Tea 04 | 34 | 0 | 0 | 0 |
| Willow reduced | 115 | 74 | 90 | 31 |
| 03_28mil | 545 | 28 | 119 | 47 |
| Big Spruce low | 1108 | 44 | 267 | 8 |

Ten independent inputs contain 3336 labelled joints. Order mismatches 485,
PVE 808, Tree 133: 85.5%, 75.8%, 96.0% agreement respectively. These are
calibration results, not held-out generalization. A sibling reference and the
same rig in another format do not provide independent accuracy evidence.
Tea's one-group configured result alone is trivial; the regression additionally
checks that its uncapped analysis identifies all stems at level 0.

The regression uses one corpus contract: at least 95% pooled agreement, at
least 70% for every selected input, and exact invariance under renaming,
reordering, a non-axis-aligned rigid rotation, translation, scale x1000, forged generator labels,
and forged XML endpoints. It also requires explicit ambiguity at a symmetric
bare fork. These gates prevent regressions without pretending every source
generator boundary is geometrically identifiable.

## Preview and export boundaries

Tree mode colors guides starting at each joint pivot. XML uses its known
physical endpoint for display only. Without an endpoint, the guide extends
along the analyzed axis toward the furthest projected attachment; a terminal
joint gets a short direction marker. These are labelled display guides, not
new authored bones or certified recovered lengths. Original parent/child
attachment connectors therefore do not repaint the trunk with child colors.
The shared MatcapViewport still owns rendering, selection and GPU lifetime.

The Dynamic Wind JSON gate now permits same-group forks for groups explicitly
marked Trunk. Local UE 5.8 `DynamicWindEval.usf:187` uses a separate trunk path
that does not consume chain influence/length. This supports the selected
Alder multi-stem references without removing the branch-chain guard. Non-trunk
same-group forks still fail. Ground Cover alone does not grant this exception.
This is source-backed and locally regression-tested; new runtime UE validation
remains open. Do not automatically change operator Trunk/Ground Cover flags.

## Remaining limitations

- 03_28mil regresses from 28 to 47 mismatches versus Order. Willow still has
  31/115 mismatches; Alder 01 has 35/346. Retain these as explicit counterexamples.
- Some generator changes occur on a near-collinear single-child chain, such
  as Willow bone_009 -> bone_010 at roughly three degrees. A group boundary
  cannot be certified solely from that geometry. Reference differences remain
  available for operator review rather than hidden by file-specific branches.
- Directional-frame interpretation, basal-root detection and terminal-chain
  rules need independent tree families, broader FBX validation and operator
  inspection. Calibration agreement is not proof of Unreal wind quality.
- A multi-joint rig with no spatial extent cannot describe tree branches; Tree
  rejects it with a named error. The UI keeps an available prior grouping mode.
- Merging many branch levels can create forbidden non-trunk forks. Increase
  Groups or use manual corrections; the export gate remains explicit.

Rejected in research: a shallow fitted edge classifier generalized poorly when
whole tree families were excluded, and accumulated root errors shifted entire
subtrees. It was not shipped. Runtime has no learned asset lookup or training
dependency. Diagnostic experiments remain under ignored `tmp/`; the maintained
benchmark and compact regression corpus are the reproducible evidence.
