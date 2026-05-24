# Known Problems

## UDIM secondary UV primvar needs UE import validation

- Issue: UDIM `write_secondary_uv_offset` authors the second UV channel as `texCoord2f[] primvars:st1`, which is the local implementation choice for UV1.
- Location: `src/xml_to_usda/usda_authoring.py`
- Reason for deferral: automated tests verify deterministic USDA authoring, but UE 5.7.x import has not yet confirmed that `st1` maps to the expected second TexCoord channel in the skeletal Nanite Assembly path.
- Likely next step: import a generated USDA with `primvars:st1` into UE 5.7.x, inspect the resulting mesh UV channels/material sampling, and either confirm `st1` in `docs/ue_import_contract.md` or replace it with the importer-validated primvar name.

## GUI UDIM controls currently target base XML material rows

- Issue: The Qt GUI exposes UDIM controls on Base Mesh material rows. CLI and typed requests can target any resolved material id, but repeated-part and FBX material-slot GUI rows do not yet expose stable resolved material ids for UDIM targeting.
- Location: `src/xml_to_usda/qt_ui/panels.py`
- Reason for deferral: repeated-part material rows are prototype/source-mode rows, not resolved material-id rows; adding UDIM controls there without first exposing the actual target id would create misleading operator intent.
- Likely next step: extend repeated-part material discovery to surface explicit resolved material ids for XML, single-material, vertex-color split, and FBX material-slot modes, then add the same UDIM mode/id controls to those rows.
