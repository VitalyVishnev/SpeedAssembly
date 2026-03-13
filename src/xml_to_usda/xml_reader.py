from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

from .models import ObservedXmlSchemaReport, SourceXmlDocument


KNOWN_SECTION_HINTS = {
    "skeleton": ("skeleton", "bone", "joint"),
    "trunk_mesh": ("trunk", "mesh", "geometry", "vertices", "faces", "triangles", "points"),
    "leaf_references": ("leaf", "leafref", "leafreference"),
    "object_hierarchy": ("object", "objects"),
    "materials": ("material",),
    "lods": ("lod",),
    "metadata": ("metadata", "version", "units", "axis", "speedtreeraw"),
}

IGNORED_PAYLOAD_TAGS = {
    "AO",
    "BinormalX",
    "BinormalY",
    "BinormalZ",
    "Blend",
    "BoneID",
    "GeometryType",
    "Map",
    "MeshID",
    "MeshLOD",
    "NormalX",
    "NormalY",
    "NormalZ",
    "PointIndices",
    "QuadIndices",
    "Radius",
    "RotAngle",
    "RotAxisX",
    "RotAxisY",
    "RotAxisZ",
    "Scale",
    "SpeedTreeRaw",
    "TangentX",
    "TangentY",
    "TangentZ",
    "TexcoordU",
    "TexcoordV",
    "TriangleIndices",
    "VertexColorA",
    "VertexColorB",
    "VertexColorG",
    "VertexColorR",
    "VertexIndices",
    "X",
    "Y",
    "Z",
}


def read_source_xml(path: str | Path) -> SourceXmlDocument:
    xml_path = Path(path)
    tree = ET.parse(xml_path)
    root = tree.getroot()
    return SourceXmlDocument(source_path=str(xml_path), root_tag=root.tag, tree=tree)


def inspect_xml(document: SourceXmlDocument) -> ObservedXmlSchemaReport:
    root = document.tree.getroot()
    tag_counts: Counter[str] = Counter()
    attributes_by_tag: dict[str, set[str]] = defaultdict(set)

    for elem in root.iter():
        tag_counts[elem.tag] += 1
        attributes_by_tag[elem.tag].update(sorted(elem.attrib.keys()))

    known_sections = {
        name: sum(
            count
            for tag, count in tag_counts.items()
            if any(hint in tag.lower() for hint in hints)
        )
        for name, hints in KNOWN_SECTION_HINTS.items()
    }

    unknown_sections = tuple(
        sorted(
            tag
            for tag in tag_counts
            if tag not in IGNORED_PAYLOAD_TAGS
            if not any(hint in tag.lower() for hints in KNOWN_SECTION_HINTS.values() for hint in hints)
        )
    )

    version = _extract_version(root)
    units_hint = root.attrib.get("units") or _find_first_attr(root, "units")
    up_axis_hint = (
        root.attrib.get("upAxis")
        or root.attrib.get("up_axis")
        or _find_first_attr(root, "upAxis")
        or _find_first_attr(root, "up_axis")
    )

    object_class_counts, hierarchy_depth, spine_object_count = _inspect_object_hierarchy(root)
    leaf_binding_distribution, leaf_mesh_distribution = _inspect_leaf_bindings(root)

    return ObservedXmlSchemaReport(
        source_path=document.source_path,
        root_tag=document.root_tag,
        tag_counts=dict(sorted(tag_counts.items())),
        attributes_by_tag={tag: tuple(sorted(attrs)) for tag, attrs in sorted(attributes_by_tag.items())},
        known_sections=known_sections,
        unknown_sections=unknown_sections,
        version=version,
        units_hint=units_hint,
        up_axis_hint=up_axis_hint,
        object_class_counts=object_class_counts,
        hierarchy_depth=hierarchy_depth,
        spine_object_count=spine_object_count,
        leaf_binding_distribution=leaf_binding_distribution,
        leaf_mesh_distribution=leaf_mesh_distribution,
    )


def render_inspect_report(report: ObservedXmlSchemaReport) -> str:
    payload = {
        "source_path": report.source_path,
        "root_tag": report.root_tag,
        "version": report.version,
        "units_hint": report.units_hint,
        "up_axis_hint": report.up_axis_hint,
        "known_sections": report.known_sections,
        "unknown_sections": list(report.unknown_sections),
        "object_class_counts": report.object_class_counts,
        "hierarchy_depth": report.hierarchy_depth,
        "spine_object_count": report.spine_object_count,
        "leaf_binding_distribution": report.leaf_binding_distribution,
        "leaf_mesh_distribution": report.leaf_mesh_distribution,
        "tag_counts": report.tag_counts,
        "attributes_by_tag": {k: list(v) for k, v in report.attributes_by_tag.items()},
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _find_first_attr(root: ET.Element, attr_name: str) -> str | None:
    for elem in root.iter():
        if attr_name in elem.attrib:
            return elem.attrib[attr_name]
    return None


def _find_first_text(root: ET.Element, tag_hint: str) -> str | None:
    for elem in root.iter():
        if tag_hint in elem.tag.lower() and elem.text and elem.text.strip():
            return elem.text.strip()
    return None


def _extract_version(root: ET.Element) -> str | None:
    major = root.attrib.get("VersionMajor") or _find_first_attr(root, "VersionMajor")
    minor = root.attrib.get("VersionMinor") or _find_first_attr(root, "VersionMinor")
    if major and minor:
        return f"{major}.{minor}"
    return (
        root.attrib.get("version")
        or _find_first_attr(root, "version")
        or _find_first_text(root, "version")
    )


def _inspect_object_hierarchy(root: ET.Element) -> tuple[dict[str, int], int, int]:
    objects = root.findall(".//Object")
    class_counts: Counter[str] = Counter()
    parents: dict[str, str | None] = {}
    spine_object_count = 0

    for obj in objects:
        name = obj.attrib.get("Name", "")
        if name == "Trunk":
            class_counts["trunk"] += 1
        elif name.startswith("Branches"):
            class_counts["branch"] += 1
        elif name.startswith("Twigs"):
            class_counts["twig"] += 1
        else:
            class_counts["other"] += 1

        object_id = obj.attrib.get("ID")
        if object_id is not None:
            parents[object_id] = obj.attrib.get("ParentID")
        if obj.find("Spine") is not None:
            spine_object_count += 1

    def depth_for(object_id: str) -> int:
        depth = 0
        current = object_id
        seen: set[str] = set()
        while current in parents and parents[current] not in {None, ""}:
            parent_id = parents[current]
            if parent_id is None or parent_id in seen:
                break
            seen.add(parent_id)
            current = parent_id
            depth += 1
        return depth

    hierarchy_depth = max((depth_for(object_id) for object_id in parents), default=0)
    class_counts["total"] = len(objects)
    return dict(sorted(class_counts.items())), hierarchy_depth, spine_object_count


def _inspect_leaf_bindings(root: ET.Element) -> tuple[dict[str, int], dict[str, int]]:
    bone_counts: Counter[str] = Counter()
    mesh_counts: Counter[str] = Counter()

    for leaf_ref in root.findall(".//LeafReferences"):
        bone_counts.update(_read_tokens(leaf_ref.findtext("BoneID")))
        mesh_counts.update(_read_tokens(leaf_ref.findtext("MeshID")))

    return _sort_numeric_key_dict(bone_counts), _sort_numeric_key_dict(mesh_counts)


def _read_tokens(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [token for token in raw.replace(",", " ").split() if token]


def _sort_numeric_key_dict(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: (not item[0].lstrip("-").isdigit(), int(item[0]) if item[0].lstrip("-").isdigit() else item[0])))
