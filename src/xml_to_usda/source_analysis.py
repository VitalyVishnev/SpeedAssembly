"""Read-only XML/source analysis helpers for reports and UI discovery.

Layer: application/domain boundary.

These helpers inspect source XML and derive report/discovery data without
performing full conversion orchestration or USDA writing.

Fast discovery helpers are UI adapters, but supported prototype and base
material rows must remain parity-tested against `CanonicalTreeModel`.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import replace

from .models import BaseMaterialOverride, CanonicalTreeModel, ObservedXmlSchemaReport, PrototypeDiscoveryEntry
from .normalizer import normalize_to_canonical
from .xml_reader import analyze_xml, read_source_xml


def inspect_source(input_path: str) -> ObservedXmlSchemaReport:
    """Inspect one source XML file and enrich the observed-schema report."""
    document = read_source_xml(input_path)
    analysis = analyze_xml(document)
    report = analysis.report
    model = normalize_to_canonical(document, report, source_nodes=analysis.source_nodes)
    return replace(
        report,
        base_geometry_mode=_base_geometry_mode(model),
        base_mesh_part_count=len(model.base_tree_parts),
        base_mesh_point_count=len(model.base_mesh.points) if model.base_mesh is not None else 0,
        base_mesh_face_count=len(model.base_mesh.face_vertex_counts) if model.base_mesh is not None else 0,
        base_material_distribution=_mesh_material_distribution(model.base_mesh),
        prototype_material_distribution=_prototype_material_distribution(model),
        prototype_structure=model.prototype_strategy.value,
        binding_mode=model.binding_mode,
        binding_element_size=model.binding_element_size,
        support_primvars=_support_primvars(model),
        orientation_sample=tuple(part.orientation.to_usda() for part in model.repeated_parts[:3]),
    )


def discover_part_prototypes(input_path: str) -> tuple[PrototypeDiscoveryEntry, ...]:
    """Discover repeated-part prototype identities from streamed `LeafReferences`."""
    mesh_names_by_id: dict[int, str] = {}
    mesh_instance_counts_by_id: dict[int, int] = {}
    ordered_mesh_ids: list[int] = []
    seen_mesh_ids: set[int] = set()
    saw_leaf_references = False
    leaf_without_mesh_id_instance_count = 0

    for _event, elem in ET.iterparse(input_path, events=("end",)):
        if elem.tag == "Mesh":
            raw_mesh_id = elem.attrib.get("ID")
            if raw_mesh_id is not None and raw_mesh_id.isdigit():
                mesh_id = int(raw_mesh_id)
                mesh_names_by_id[mesh_id] = elem.attrib.get("Name", f"Mesh_{mesh_id}")
            elem.clear()
            continue
        if elem.tag != "LeafReferences":
            continue

        saw_leaf_references = True
        mesh_ids = _read_streamed_mesh_ids(elem.findtext("MeshID"))
        instance_count = _read_leaf_reference_instance_count(elem)
        if mesh_ids:
            mesh_count_deltas = _mesh_instance_count_deltas(mesh_ids, instance_count)
            for mesh_id in mesh_ids:
                if mesh_id in seen_mesh_ids:
                    continue
                seen_mesh_ids.add(mesh_id)
                ordered_mesh_ids.append(mesh_id)
                mesh_instance_counts_by_id.setdefault(mesh_id, 0)
            for mesh_id, count_delta in mesh_count_deltas.items():
                mesh_instance_counts_by_id[mesh_id] = mesh_instance_counts_by_id.get(mesh_id, 0) + count_delta
        elif _leaf_reference_has_instances(elem):
            leaf_without_mesh_id_instance_count += max(instance_count, 1)
        elem.clear()

    prototypes = tuple(
        PrototypeDiscoveryEntry(
            source_key=f"Mesh_{mesh_id}",
            source_mesh_id=mesh_id,
            source_name=mesh_names_by_id.get(mesh_id, f"Mesh_{mesh_id}"),
            instance_count=mesh_instance_counts_by_id.get(mesh_id, 0),
        )
        for mesh_id in ordered_mesh_ids
    )
    if prototypes or not saw_leaf_references or not leaf_without_mesh_id_instance_count:
        return prototypes
    return (
        PrototypeDiscoveryEntry(
            source_key="LeafPrototype",
            source_mesh_id=None,
            source_name="LeafPrototype",
            instance_count=leaf_without_mesh_id_instance_count,
        ),
    )


def discover_source_materials(input_path: str) -> tuple[BaseMaterialOverride, ...]:
    """Discover base-tree XML material slots while ignoring prototype-only materials."""
    material_names_by_id: dict[int, str] = {}
    material_id_order: list[int] = []
    used_base_material_ids: set[int] = set()
    element_stack: list[str] = []

    for event, elem in ET.iterparse(input_path, events=("start", "end")):
        if event == "start":
            element_stack.append(elem.tag)
            continue

        if elem.tag == "Material":
            raw_source_id = elem.attrib.get("ID")
            if raw_source_id is not None and raw_source_id.lstrip("-").isdigit():
                source_id = int(raw_source_id)
                if source_id not in material_names_by_id:
                    material_id_order.append(source_id)
                material_names_by_id[source_id] = elem.attrib.get("Name", f"Material_{source_id}")
        elif elem.tag == "Triangles":
            raw_source_id = elem.attrib.get("Material")
            if (
                raw_source_id is not None
                and raw_source_id.lstrip("-").isdigit()
                and "Object" in element_stack
                and "Mesh" not in element_stack
            ):
                used_base_material_ids.add(int(raw_source_id))

        if element_stack:
            element_stack.pop()
        elem.clear()

    return tuple(
        BaseMaterialOverride(
            source_id=source_id,
            source_name=material_names_by_id.get(source_id, f"Material_{source_id}"),
        )
        for source_id in material_id_order
        if source_id in used_base_material_ids
    )


def _base_geometry_mode(model: CanonicalTreeModel) -> str:
    if not model.base_tree_parts:
        return "missing"
    return "merged" if len(model.base_tree_parts) > 1 else "single_object"


def _support_primvars(model: CanonicalTreeModel) -> tuple[str, ...]:
    if model.skeletal_support_primvars is None:
        return ()
    return ("boneCapture_pCaptPath", "ueJointNames", "hierarchicalDepth", "logicalDepth", "localtransform")


def _mesh_material_distribution(mesh) -> dict[str, int]:
    if mesh is None:
        return {}
    return {str(section.material_id): len(section.face_indices) for section in mesh.sections}


def _prototype_material_distribution(model: CanonicalTreeModel) -> dict[str, int]:
    distribution: dict[str, int] = {}
    for prototype in model.prototypes:
        section_source = prototype.geometry_payload.sections if prototype.geometry_payload is not None else (
            prototype.mesh.sections if prototype.mesh is not None else ()
        )
        for section in section_source:
            key = str(section.material_id)
            distribution[key] = distribution.get(key, 0) + len(section.face_indices)
    return dict(sorted(distribution.items(), key=lambda item: int(item[0]) if item[0].lstrip("-").isdigit() else item[0]))


def _read_streamed_mesh_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    mesh_ids: list[int] = []
    for token in raw.replace(",", " ").split():
        if token.lstrip("-").isdigit():
            mesh_ids.append(int(token))
    return mesh_ids


def _leaf_reference_has_instances(elem: ET.Element) -> bool:
    for tag_name in ("MeshID", "X", "Y", "Z"):
        text = elem.findtext(tag_name)
        if text and text.strip():
            return True
    return False


def _read_leaf_reference_instance_count(elem: ET.Element) -> int:
    raw_count = (elem.attrib.get("Count") or "").strip()
    if raw_count.isdigit():
        parsed = int(raw_count)
        if parsed > 0:
            return parsed
    return max(
        _count_streamed_value_tokens(elem.findtext(tag_name))
        for tag_name in ("MeshID", "X", "Y", "Z", "Scale", "BoneID")
    )


def _count_streamed_value_tokens(raw: str | None) -> int:
    if raw is None:
        return 0
    text = raw.strip()
    if not text:
        return 0
    return len(text.split())


def _mesh_instance_count_deltas(mesh_ids: list[int], instance_count: int) -> dict[int, int]:
    if not mesh_ids:
        return {}
    if len(mesh_ids) == 1 and instance_count > 1:
        return {mesh_ids[0]: instance_count}
    counts: dict[int, int] = {}
    for mesh_id in mesh_ids:
        counts[mesh_id] = counts.get(mesh_id, 0) + 1
    return counts
