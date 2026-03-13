# Immutable Vault

This folder is reserved for external reference materials: Unreal Engine plugin files, schema dumps, tutorials, notes, and export matrices.

## Rules

- raw files placed here are treated as immutable
- code must not write generated outputs into `vault/`
- analysis based on vault materials should be written to project docs or notes outside the raw source files
- every imported resource should be accompanied by provenance: source, version, date, and purpose

## Suggested layout

- `vault/ue_plugins/`
- `vault/usd_schema/`
- `vault/tutorials/`
- `vault/notes/`
- `vault/speedtree_export_matrix/`
