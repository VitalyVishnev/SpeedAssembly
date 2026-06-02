# Glossary

## Role

This glossary gives architecture reviews a stable project language.

`AGENTS.md` remains normative for mission terms. If this file and `AGENTS.md`
disagree, `AGENTS.md` wins.

## Architecture review terms

Use these terms in architecture suggestions:

- **Module**
  Anything with an interface and an implementation: function, class, file,
  package, UI adapter, writer path, or conversion slice.
- **Interface**
  Everything callers must know to use a module correctly: types, invariants,
  ordering, error modes, configuration, and performance expectations.
- **Implementation**
  Code inside a module.
- **Depth**
  Leverage at the interface. A deep module hides meaningful behavior behind a
  small interface; a shallow module mostly renames its implementation.
- **Seam**
  Where an interface lives and behavior can vary without editing the caller.
- **Adapter**
  A concrete implementation at a seam.
- **Leverage**
  What callers get from a deep module.
- **Locality**
  What maintainers get when change, bugs, knowledge, and verification are
  concentrated in one place.

Avoid using generic words such as component, service, API, or boundary when the
architecture terms above are more precise.

## Project domain terms

- **Converter**
  The deterministic SpeedTree Raw XML to USDA pipeline for UE 5.7 Nanite
  Assembly import. Its primary path is `Skeletal Nanite Assembly`; its supported
  secondary path is `Static Mesh Assembly`.
- **Observed Source XML**
  A real SpeedTree Raw XML sample. It is treated as observed schema, not as a
  stable public specification.
- **Skeletal Nanite Assembly**
  USD scene structure that UE imports through the skeletal Nanite Assembly path:
  one Assembly Root, one Main Skeleton, one Base Skeletal Tree for unique
  geometry, and repeated skeletal Assembly Parts placed through PointInstancer.
- **Static Mesh Assembly**
  Supported secondary USDA export shape that UE imports as a static Nanite
  Assembly: one Assembly Root, rigid renderable prototypes, and repeated static
  Assembly Parts placed through PointInstancer, without skeletons or skeletal
  binding arrays.
- **Proxy Mesh**
  A separate companion USDA asset for the main tree export. It starts from the
  `Canonical Tree Model`, is derived from the `Resolved Assembly Model`, uses
  `Leaf References` input for repeated-part multiplicity, and writes as a
  sibling `.usda` file with a `_proxy` suffix. It is geometry-only and is not a
  separate export mode.
- **Proxy Mesh Source Request**
  The narrowed request projection used by Proxy Mesh preview/export. It carries
  the source XML path, proxy output path, output mode, CPU profile, and FBX
  cache limits, but not main-export material overrides, prototype replacement,
  UDIM settings, or conversion mode intent.
- **Assembly Root**
  Root prim of the USDA scene. It marks the scene as a Nanite Assembly and, in
  skeletal assembly mode, points UE at the descendant Main Skeleton.
- **Canonical Tree Model**
  The source-normalized vegetation model consumed by validation and USDA
  authoring. It represents observed SpeedTree XML concepts after normalization:
  unique geometry, repeated parts, prototype identities, source skeleton data
  when present, materials, and metadata. In code this is `CanonicalTreeModel`,
  currently an alias of `TreeAsset`. It is not a skeletal-only authoring model;
  `ConversionMode` decides which parts of it are authored.
- **Resolved Assembly Model**
  Authoring-stage model that combines `CanonicalTreeModel` source facts with
  operator intent from `ConversionRequest`, prototype source config, material
  overrides, export mode, and output naming. In code this is
  `ResolvedAssemblyModel`, built through the Assembly Resolution Module. It is
  the seam between source facts and authored assembly output.
- **Source Facts**
  Data observed or derived from the SpeedTree XML itself: hierarchy, source
  skeleton, unique geometry, repeated part placements, prototype identities,
  source material metadata, and source transforms.
- **Operator Intent**
  User or caller choices that are not facts of the XML: export mode, output
  path, material overrides, prototype replacement source, cleanup policy, and
  persisted GUI settings. Internal runtime tuning such as CPU profile is not an
  ordinary operator choice.
- **Operator State**
  Current operator-selected values in the UI for a conversion workflow. In the
  target UX, this is remembered globally across trees and can be captured as
  named presets. A subset of Operator State becomes Operator Intent for a
  `ConversionRequest`.
- **Global Remembered State**
  The saved operator values shared across trees and sessions. It is the default
  state restored at startup and the source for named presets.
- **Persisted Operator Settings**
  Saved global operator values and named presets. Loading these values restores
  Operator State; it does not change source facts.
- **Named Preset**
  A user-saved snapshot of Global Remembered State that can be selected from
  the preset dropdown.
- **Factory-Defaults Preset**
  The built-in preset that represents shipped defaults and always exists in the
  preset dropdown.
- **UI Shell State**
  State of the UI shell itself, such as window geometry, theme overrides, open
  tabs, or visual preferences. UI Shell State is not conversion Operator Intent.
- **Source Validation**
  Validation of source facts before operator intent is applied: XML structure,
  source hierarchy, source skeleton, repeated part placement data, prototype
  identity, source bindings, and source geometry.
- **Resolution Validation**
  Validation of source facts combined with operator intent: export mode
  contract, prototype source replacement, Unreal asset paths, material
  overrides, FBX material slot choices, and output naming.
- **Authoring Validation**
  Validation of the USDA contract that will be written: required schemas,
  mode-specific required/omitted fields, binding arrays, prototype/instance
  counts, and absence of illegal fallback geometry.
- **Export Mode**
  The requested USDA authoring shape: primary `skeletal_assembly`, supported
  secondary `static_assembly`, reusable `skeletal_parts`, or reserved
  `static_parts`.
- **Base Skeletal Tree**
  Unique tree geometry bound to the Main Skeleton: trunk, major branches,
  optional roots, and any other non-instanced tree geometry. It is not a
  trunk-only placeholder.
- **Base Mesh**
  Geometry payload of the Base Skeletal Tree. It is not a trunk-only mesh and
  not a minimal placeholder mesh.
- **Main Skeleton**
  Shared skeleton of the tree. The Base Skeletal Tree binds to it, and skeletal
  Assembly Parts attach relative to it through authored Skeletal Binding.
- **Assembly Part**
  Authored repeated geometry part emitted through `PointInstancer` inside a
  larger tree assembly. It is mode-neutral: skeletal exports author skeletal
  Assembly Parts, static exports author static Assembly Parts. In code, USDA
  authoring projects source repeated parts into `AuthoredAssemblyPartInstance`
  values.
- **Repeated Part**
  Source-level repeated part record interpreted from SpeedTree `LeafReferences`.
  In code, it is normalized as `RepeatedPartInstance` and then projected into
  an authored Assembly Part during resolution and USDA authoring.
- **Part Skeletal Mesh**
  Skeletal mesh payload of one Assembly Part prototype.
- **Part Skeleton**
  Local skeleton of one Assembly Part. For the current target pipeline, each
  inline part has one local bone at the part pivot or base.
- **PointInstancer**
  USD mechanism that places Assembly Parts. It stores prototype targets,
  instance transforms, and, for skeletal assembly mode, skeletal assembly
  binding data back to the Main Skeleton.
- **Prototype**
  Stage-dependent shorthand for reusable repeated-part identity, payload, or
  authored USDA subtree. Prefer `Source Prototype`, `Resolved Prototype`, or
  `Authored Prototype` when precision matters.
- **Source Prototype**
  Source-level reusable repeated-part definition from SpeedTree `Meshes/Mesh`,
  keyed by observed XML identity such as `MeshID` and source mesh name.
- **Resolved Prototype**
  Prototype after source facts are combined with operator intent: selected
  payload source, replacement mode, material behavior, and authoring-ready
  identity.
- **Authored Prototype**
  USDA prototype prim or subtree written for `PointInstancer.prototypes`.
  Static assembly may also author a synthetic base Authored Prototype for unique
  base geometry.
- **Instance**
  Stage-dependent shorthand for one placed occurrence of a Prototype. Prefer
  `Repeated Part Instance`, `Resolved Instance`, or `Authored Instance` when
  transform, binding, or authoring stage matters.
- **Repeated Part Instance**
  Source-level placed occurrence interpreted from SpeedTree `LeafReferences`,
  including source placement, scale, rotation, material hint, and binding source
  such as `BoneID`. In code, this is `RepeatedPartInstance`.
- **Resolved Instance**
  Repeated part instance after source facts are combined with operator intent
  and a Resolved Prototype.
- **Authored Instance**
  Per-instance data authored into USDA `PointInstancer` arrays: prototype index,
  position, orientation, scale, and mode-specific binding data when required.
- **Attachment**
  Source or resolved relationship that says which source skeleton object, joint,
  or placement context a Repeated Part Instance belongs to. It is not the USDA
  skeletal binding contract.
- **Skeletal Binding**
  Authored skeletal USDA contract that binds the Base Skeletal Tree or skeletal
  Assembly Parts back to the Main Skeleton. Static Mesh Assembly export does not
  author Skeletal Binding.
- **Leaf References**
  SpeedTree XML source section that the converter interprets as the source of
  Repeated Parts. `LeafReferences` does not promise that the payload is
  literally only leaves.
- **Unique Geometry**
  Tree geometry that stays inside the Base Skeletal Tree and is not instanced.
- **Instanced Geometry**
  Geometry sourced from `LeafReferences` and emitted as Assembly Parts through
  PointInstancer.
- **skeletal**
  In this project, `skeletal` means the asset participates in the skeletal UE
  import path. The Base Skeletal Tree uses the Main Skeleton, and each inline
  Assembly Part is itself a skeletal mesh with a simple local skeleton.
- **Prototype Source**
  The selected payload source for a Prototype: XML mesh, Unreal asset, or disk
  FBX file.
- **Explicit Material Contract**
  Per-base-material and per-prototype material settings from GUI/CLI state.
  This is separate from legacy broad material policies.
- **Source Material**
  Material metadata and face assignment observed in the source XML or source
  payload: XML material ids/names, source face material sections, vertex colors,
  and FBX material slot names before operator overrides.
- **Resolved Material Assignment**
  Material assignment after source materials are combined with operator intent:
  material policy, base XML material overrides, repeated-part material mode,
  FBX material slots, or Unreal material paths.
- **Authored Material Binding**
  USDA material prims, `material:binding` relationships, and `GeomSubset`
  authoring written for the selected export mode.
- **UDIM Material Setting**
  Per-material Operator Intent that either shifts primary face-varying UVs or
  writes a full-size secondary UV channel for resolved inline geometry. It is
  keyed by resolved material id and does not edit external Unreal asset
  prototypes.
- **Source Name**
  Name observed in source data, such as XML object names, `Meshes/Mesh/@Name`,
  material names, or source filenames. Source Names are metadata unless a
  mapping rule explicitly uses them.
- **Output Stem**
  File-stem chosen from the output USDA path. It drives base skeletal prim names
  and some authored asset naming rules.
- **Prim Name**
  USD-valid identifier used for a prim in the authored USDA. It may be derived
  from a Source Name or Output Stem through sanitization and deterministic
  collision handling.
- **Authored Asset Name**
  Name intended for the UE-imported asset or authored USDA asset identity. It is
  not the same thing as a Source Name or Unreal Asset Path.
- **Unreal Asset Path**
  UE package/object path such as `/Game/Trees/SK_Branch.SK_Branch`. This is not
  a USD prim path.
- **Source Space**
  Coordinate and transform space as observed in SpeedTree XML or imported
  source payloads before project axis/basis conversion.
- **Stage Space**
  Coordinate and transform space authored into USDA after validated axis/basis
  conversion. Current validated stage defaults are `metersPerUnit = 1` and
  `upAxis = "Y"`.
- **Prototype Space**
  Local payload space of a Source, Resolved, or Authored Prototype. XML inline
  prototypes and FBX replacement payloads must preserve their authored size and
  pivot rules unless a verified contract says otherwise.
- **Attachment Space**
  Space used to interpret how a Repeated Part Instance relates to its source
  Attachment, such as a source joint or object context.
- **Instance Transform**
  Resolved per-instance transform for a Repeated Part Instance: position,
  orientation, scale, pivot behavior, and attachment interpretation before USD
  array authoring.
- **Authored PointInstancer Transform**
  Per-instance transform as written into USDA `PointInstancer` arrays:
  `positions`, `orientations`, `scales`, and `protoIndices`.
- **Runtime Job Workspace**
  Per-conversion temp/cache location used by subprocess conversion, streamed
  USDA writing, FBX worker requests, manifests, cleanup, and diagnostics.
- **Runtime Job**
  One executing conversion run. It owns runtime state such as telemetry,
  cancellation, cleanup, worker/helper processes, and a Job Workspace. It is not
  the same thing as `ConversionRequest`, which describes caller intent.
- **Job Workspace**
  Per-runtime-job directory for temporary files, streamed USDA temp output, FBX
  helper request/response payloads, manifests, cleanup records, and diagnostics.
- **Conversion Worker**
  Process that owns a large conversion outside the UI process. It applies the
  conversion pipeline and reports telemetry back to the UI or caller.
- **FBX Helper**
  Isolated helper process used for native Autodesk FBX import work. It may be
  launched by a Conversion Worker or supervisor and can be retried at reduced
  concurrency after native failures.
- **Runtime Adapter**
  Concrete execution environment adapter, such as launcher/dev runtime or
  packaged frozen executable runtime. Runtime Adapters must preserve the same
  conversion semantics.
- **Dynamic Wind Data**
  Exported wind-group assignment and simulation settings derived from the
  normalized skeleton, not from UI-only state.
- **Public Facade**
  A stable entry module retained for callers/tests. It should delegate to
  focused modules and avoid growing new business rules.
- **Help Deck**
  The in-app slide-style usage guide opened from the help affordance inside the
  packaged exe.
- **Diagnostics Bundle**
  A local-only bug-report artifact containing the active preset, settings
  snapshot, runtime log, output path, and related files needed to reproduce a
  failure.

## Non-negotiable vocabulary

When discussing importer-facing behavior, use the canonical names from
`AGENTS.md`:

- `Skeletal Nanite Assembly`
- `Static Mesh Assembly`
- `Assembly Root`
- `Base Skeletal Tree`
- `Main Skeleton`
- `Assembly Parts`
- `Repeated Parts`
- `Part Skeletal Mesh`
- `Part Skeleton`
- `PointInstancer`
- `Prototype`
- `Source Prototype`
- `Resolved Prototype`
- `Authored Prototype`
- `Instance`
- `Repeated Part Instance`
- `Resolved Instance`
- `Authored Instance`
- `Attachment`
- `Skeletal Binding`
- `Source Material`
- `Resolved Material Assignment`
- `Authored Material Binding`
- `Source Name`
- `Output Stem`
- `Prim Name`
- `Authored Asset Name`
- `Unreal Asset Path`
- `Source Space`
- `Stage Space`
- `Prototype Space`
- `Attachment Space`
- `Instance Transform`
- `Authored PointInstancer Transform`
- `Runtime Job`
- `Job Workspace`
- `Conversion Worker`
- `FBX Helper`
- `Runtime Adapter`
- `Operator State`
- `Persisted Operator Settings`
- `UI Shell State`
- `Leaf References`
- `Unique Geometry`
- `Instanced Geometry`

Do not replace these with looser botanical or generic USD terms in architecture
reviews.
