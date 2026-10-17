# Tree hierarchy calibration

Implemented 2026-10-12 as `Auto Hierarchy (Tree)` in Advanced Wind Settings.
This is an operator comparison candidate, not a validated universal classifier.
The original Auto and PVE modes remain available. Skeleton poses, names,
topology, binding, and USDA authoring are unchanged.

## Interactive tuning, 2026-10-13

Tree is now the primary automatic mode for newly loaded external rigs and XML
without generator groups. XML with valid labels retains Generator XML Groups;
saved operator choices retain precedence. UI order: Generator XML Groups, Auto
Hierarchy (Tree), Auto Hierarchy (PVE), Auto Hierarchy (Skeleton Order). Stable
mode keys and the JSON/grouping algorithms remain unchanged.

Grouping directions chooses the classifier's direction source. It does not
choose displayed bone directions. Display guides always use the reliable
automatic model: varying bind axes or inferred attachment axes for uniform
frames. Forcing bind +X on a uniform-frame rig can still give poor grouping;
the control explains this near the choice. It no longer makes the skeleton
horizontal. Equivalent-fork choices have individual dropdown/selected-control
tooltips. Degree/percent symbols appear as numeric suffixes, without label
parentheses.

Wind errors have a large operator explanation and relevant file path in the
popup/preview status. Known skeleton error codes map to short explanations;
unknown errors report failure without claiming an invented cause. The raw
worker error and traceback remain in the main log/diagnostic trace, not the
popup. A missing chosen Skeleton index is distinct from a file with no skeleton.

## Opaque GPU bone display, 2026-10-13

Bone strokes now render in one OpenGL triangle batch with opaque unlit RGB,
round ends, no lighting/Matcap, and no alpha blending. The bone pass clears mesh
depth while preserving mesh color, then uses hardware depth among bones. It
keeps the inspector overlay above meshes without CPU pairwise visibility cuts.
Picking compares projected depth for strokes under the cursor. QPainter remains
only for sparse cut/hover markers and at most 32 selected-joint text labels;
large subtree selections still highlight every stroke.

Endpoints clip/project together in NumPy using one camera matrix. Geometry,
projection, shadow events and GPU vertices have separate input-based caches.
Changing shadow strength/radius only updates uniforms; camera movement updates
one compact VBO. A context-owned renderer releases buffers/program/VAO through
MatcapViewport's existing context lifecycle.

AO is a small unlit color modulation only on the rear bone at a strict interior
screen crossing with a nearer unrelated bone. Adjacent parent/child segments,
endpoint contacts, equal-depth intersections, parallel proximity and collinear
segments do not cast this approximation. A vectorized X-bound sweep generates
candidate intersections in 64-row blocks; all candidate math is vectorized.
GPU work is bounded to eight nearest foreground crossing centers per bone.
Very dense geometry can still increase CPU candidate counts; current profiling
covers the operator's 347-joint Alder and the 1108-joint reference rig.

Wind defaults are shading enabled, Overlap shadow 50% and Shadow radius 1.20.
The three controls share an initially expanded, collapsible Bones Shading section.
Saved session values take precedence. Overlap shadow is 0-100%; Shadow radius
is a unitless 0-3 scale. One unit occupies 1/120 of monitor height, exactly 12 physical pixels
at 1440p. QScreen logical height makes DPI cancel in physical-screen proportion.
Zero radius removes AO. Moving/resizing updates the draw uniforms naturally.
New sessions save bone_overlap_radius_scale; legacy pixel values migrate by
value/12. Existing strength, checkbox, source choices and group assignments
persist. Session writes remain debounced 200 ms and flush on close.

Measured after optimization, rotating camera with shadows enabled, 120 warm
frames and glFinish inside paintGL, excluding swap/vsync and initial compilation:
347 joints median 2.16 ms / p95 2.48 ms; 1108 joints median 6.22 ms / p95 6.90 ms.
This includes CPU preparation, grid/bone draw and GPU completion on this machine.
The prior CPU/painter path cost about 20 ms for planning alone on Alder. Real
pixels verify opaque front blue/red colors, local rear shading, unchanged
foreground/distant colors and no shadow after making the same crossing adjacent.
These are measured frame costs, not a promise for arbitrary GPUs or mesh sizes.

## Interactive thresholds and update boundary

Tree now defaults to `Keep parent level` at equivalent forks. Daughter
subtrees are compared by joint count, longest descendant link path including
entry links, angle to the parent and distal attachment. Thickness is not used.
Ambiguous attachment axes cannot certify angles/projections; these cases use
size/path evidence and remain ambiguous for operator review. `Advance together`
starts both daughters at the next level. `Choose continuation (previous)`
preserves the earlier algorithm, including its symmetric-tie behavior.

All semantic thresholds are editable in Tree hierarchy settings:

| Control | Default |
| --- | ---: |
| Continuation angle | 45 degrees |
| Chain split angle | 30 degrees |
| Distal attachment | 95% |
| Equivalent angle difference | 10 degrees |
| Equivalent subtree size, smallest/largest | 80% |
| Equivalent link-path length, shortest/longest | 80% |
| Basal distance / centered sphere diameter | 10% |
| Compact basal subtree balance | 25% |
| Stem plane second/first principal spread | 10% |
| Normalized bind direction variation | 1% |

Direction mode can force Bind-pose +X or Attachment geometry, or select between
them automatically. Independent-stem detection, preference for branched
continuations and terminal chain bend preservation have separate checkboxes.
Reset restores every Tree setting. Numerical degeneracy/tie tolerances remain
internal; they are not botanical thresholds. Settings persist in the existing
version-4 Wind session; sessions without Tree settings use the new defaults.

`prepare_tree_hierarchy` validates and retains topology, subtree counts,
longest paths, root geometry, both direction models, alignments, projections
and display guides once per rig. `classify_tree_hierarchy` performs one forward
O(joints + links) pass without geometry, PCA, reverse traversal or recursion.
The existing `analyze_tree_hierarchy` remains the batch convenience entry.

Controls coalesce changes on the next Qt event-loop turn. Base wind data and
flattened manual layers are cached by their inputs. Stable layer rows update
counts in place; a changed layer structure rebuilds them. Manual assignments,
wind settings, undo history and camera survive tuning. Disk persistence is
debounced 200 ms and flushed on close.

Wind uses the existing instanced Matcap path. Mesh geometry is prepared once;
tint-specific instance batches use a shader uniform. Live changes upload only
instance data and update bone overlays. They do not flatten/transform vertices
or recreate the large GPU vertex buffer. Default untinted callers retain their
rendering behavior. Bounds still update for display unit/axis changes.

Local CPU measurements: 1108 joints, preparation 69.3 ms; classification median
1.75 ms / p95 2.11 ms over 200 settings; full skeleton UI update median 11.44 ms
/ p95 24.32 ms over 100 settings. SimpleTree, 105 joints and 11412 rendered
vertices: UI update median 2.21 ms / p95 2.58 ms. These include layer/scene/
instance data, exclude GPU paint and disk writes, and are not a universal frame
rate guarantee. Real OpenGL pixel inspection confirmed independently red/blue
instances change to green without replacing the prepared mesh vertices.

Default Keep parent level produces 137/3336 reference mismatches, 95.89%
agreement. Willow changes from 31 to 32 and Big Spruce from 8 to 10; the other
rows below stay the same. This implements the requested fork policy, not a
claimed accuracy improvement. The table below records the previous classifier,
now an explicit choice. `benchmark_wind_hierarchy.py --equivalent-forks` selects
a policy and records the exact settings in the JSON report. The corpus gate
preserves the previous accuracy contract and verifies both policies' invariance;
a small branch fixture checks default equal-daughter behavior and the length
threshold. Qt checks verify preparation/mesh/camera/manual-state reuse.

Keep parent level is available at every preview level. If the final stack
contains a non-Trunk same-group fork, the summary reports the export block and
Generate JSON returns a named error before writing. Advance together, more
Groups or manual assignments can resolve it. Do not enable Trunk merely to
bypass the chain guard. No new chain IDs, simulation groups or flags are
silently authored; new UE runtime validation remains open.

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
  ambiguous; no child wins from its name or position in the array. Equivalent
  daughters use the selected fork policy described above.
- Derive downstream fork counts and subtree sizes in one reverse traversal.
- At the root, a compact group of similarly sized subtrees, or a basal plane
  of stems, can seed independent stems at level 0.
- At forks, continuation requires direction agreement and distal attachment.
  A continuing branched structure takes precedence over a terminal chain.
  Other children start the next level unless the equivalent-fork policy applies.
- A strong direction change can start a branch along an unbranched connection.
  Once a terminal branch has been identified, its bends do not keep creating
  groups. This prevents curved twig chains from becoming per-bone groups.

Current calibration constants: fork alignment 45 degrees, chain alignment
30 degrees, distal attachment at 95% of the parent's maximum projected child
offset, basal scale 10% of centered bounding-sphere diameter, uniform-forward variation
0.01. These are explicit geometric rules, not fitted rules keyed to species.
They are now editable and remain provisional for independent assets.

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

The previous-continuation regression preserves the corpus contract: at least 95% pooled agreement, at
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

- 03_28mil has 47 mismatches versus Order's 28. Willow has 32/115 with Keep
  parent level, 31 with previous continuation; Alder 01 has 35/346. Retain
  these as explicit counterexamples.
- Some generator changes occur on a near-collinear single-child chain, such
  as Willow bone_009 -> bone_010 at roughly three degrees. A group boundary
  cannot be certified solely from that geometry. Reference differences remain
  available for operator review rather than hidden by file-specific branches.
- Directional-frame interpretation, basal-root detection and terminal-chain
  rules need independent tree families, broader FBX validation and operator
  inspection. Calibration agreement is not proof of Unreal wind quality.
- A multi-joint rig with no spatial extent cannot describe tree branches; Tree
  rejects it with a named error. The UI keeps an available prior grouping mode.
- Keep parent level or merging many branch levels can create forbidden non-trunk forks. Increase
  Groups or use manual corrections; the export gate remains explicit.

Rejected in research: a shallow fitted edge classifier generalized poorly when
whole tree families were excluded, and accumulated root errors shifted entire
subtrees. It was not shipped. Runtime has no learned asset lookup or training
dependency. Diagnostic experiments remain under ignored `tmp/`; the maintained
benchmark and compact regression corpus are the reproducible evidence.
