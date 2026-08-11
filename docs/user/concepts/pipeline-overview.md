# Pipeline overview

SpeedAssembly separates source interpretation from operator choices and USDA authoring. That separation is what keeps the same input and settings deterministic and inspectable.

```text
SpeedTree Raw XML
        ↓
Normalized source facts
        ↓
Operator choices are resolved
        ↓
Structural and authoring validation
        ↓
USDA + optional companion outputs
        ↓
Unreal Engine USD/Interchange import
```

## Source facts

The XML is normalized into a canonical tree model. Skeleton hierarchy, unique geometry, repeated-part prototypes, placements, and source materials remain source-level facts at this stage.

The converter does not author USDA directly while traversing raw XML.

## Operator choices

Conversion mode, replacement geometry, material assignments, output naming, and related settings are resolved after normalization. A request-specific choice therefore does not change what the XML itself means.

## Validation

Validation is staged so errors identify the boundary that failed:

1. source interpretation;
2. operator-choice resolution;
3. importer-facing USDA authoring.

When required skeleton, transform, prototype, or binding facts cannot be determined safely, conversion stops instead of emitting a guessed scene.

## Primary output shapes

### Skeletal Assembly

The primary workflow authors a Main Skeleton, unique Base Skeletal Tree geometry, and repeated skeletal Assembly Parts.

### Static Assembly

The secondary rigid workflow uses the same normalized source facts but does not redefine the skeletal contract.

### Parts libraries

Skeletal Parts and Static Parts write each resolved repeated prototype once for reuse. They do not write the complete placed tree.

## Companion workflows

Dynamic Wind, [Proxy Mesh](../workflows/proxy-mesh.md), and Fracturing use narrower workflow-specific data when possible. They remain separate from the primary assembly export so their performance and validation boundaries do not silently change the main USDA.
