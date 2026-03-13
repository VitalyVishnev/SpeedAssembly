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
    "metadata": ("metadata", "version", "units", "axis"),
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
