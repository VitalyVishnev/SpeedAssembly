from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import xml.etree.ElementTree as ET


@dataclass(frozen=True, slots=True)
class SourceLimits:
    max_xml_bytes: int = 512 * 1024 * 1024
    max_xml_depth: int = 256
    max_packed_field_values: int = 5_000_000
    max_total_packed_values: int = 50_000_000
    max_repeated_part_instances: int = 2_000_000
    max_mesh_face_vertex_entries: int = 10_000_000


DEFAULT_SOURCE_LIMITS = SourceLimits()

PACKED_VALUE_TAGS = {
    "X",
    "Y",
    "Z",
    "Radius",
    "Scale",
    "RotAxisX",
    "RotAxisY",
    "RotAxisZ",
    "RotAngle",
    "MeshID",
    "MeshLOD",
    "BoneID",
    "PointIndices",
    "TriangleIndices",
    "QuadIndices",
    "VertexIndices",
    "TexcoordU",
    "TexcoordV",
    "VertexColorR",
    "VertexColorG",
    "VertexColorB",
    "VertexColorA",
    "NormalX",
    "NormalY",
    "NormalZ",
    "TangentX",
    "TangentY",
    "TangentZ",
    "BinormalX",
    "BinormalY",
    "BinormalZ",
}

FACE_VERTEX_ENTRY_TAGS = {"PointIndices", "TriangleIndices", "QuadIndices", "VertexIndices"}
_PACKED_VALUE_STREAMING_PATTERN = re.compile(r"[^,\s]+")
_PACKED_VALUE_FAST_SPLIT_MAX_CHARS = 1_000_000


@dataclass(slots=True)
class SourceBudgetTracker:
    limits: SourceLimits = DEFAULT_SOURCE_LIMITS
    max_depth: int = 0
    total_packed_values: int = 0
    repeated_part_instances: int = 0
    mesh_face_vertex_entries: int = 0

    def observe_element(self, elem: ET.Element, *, depth: int | None = None) -> None:
        if depth is not None:
            self.max_depth = max(self.max_depth, depth)
            if self.max_depth > self.limits.max_xml_depth:
                raise ValueError(f"XML depth exceeds source budget: {self.max_depth} > {self.limits.max_xml_depth}.")

        if elem.tag in PACKED_VALUE_TAGS:
            value_count = count_packed_values(elem.text)
            self._add_packed_values(elem.tag, value_count)
            if elem.tag in FACE_VERTEX_ENTRY_TAGS:
                self.mesh_face_vertex_entries += value_count
                if self.mesh_face_vertex_entries > self.limits.max_mesh_face_vertex_entries:
                    raise ValueError(
                        "Mesh face-vertex entries exceed source budget: "
                        f"{self.mesh_face_vertex_entries} > {self.limits.max_mesh_face_vertex_entries} values."
                    )

        if elem.tag == "LeafReferences":
            self.repeated_part_instances += max(
                count_packed_values(elem.findtext("MeshID")),
                count_packed_values(elem.findtext("X")),
                count_packed_values(elem.findtext("Y")),
                count_packed_values(elem.findtext("Z")),
            )
            if self.repeated_part_instances > self.limits.max_repeated_part_instances:
                raise ValueError(
                    "Repeated Part Instances exceed source budget: "
                    f"{self.repeated_part_instances} > {self.limits.max_repeated_part_instances}."
                )

    def _add_packed_values(self, tag: str, value_count: int) -> None:
        if value_count > self.limits.max_packed_field_values:
            raise ValueError(
                f"Packed XML field {tag} exceeds source budget: "
                f"{value_count} > {self.limits.max_packed_field_values} values."
            )
        self.total_packed_values += value_count
        if self.total_packed_values > self.limits.max_total_packed_values:
            raise ValueError(
                "Packed XML values exceed source budget: "
                f"{self.total_packed_values} > {self.limits.max_total_packed_values} values."
            )


def enforce_source_file_budget(path: str | Path, limits: SourceLimits = DEFAULT_SOURCE_LIMITS) -> None:
    source_path = Path(path)
    byte_count = source_path.stat().st_size
    if byte_count > limits.max_xml_bytes:
        raise ValueError(f"XML file size exceeds source budget: {byte_count} > {limits.max_xml_bytes} bytes.")


def enforce_source_tree_budgets(
    root: ET.Element,
    *,
    limits: SourceLimits = DEFAULT_SOURCE_LIMITS,
) -> None:
    tracker = SourceBudgetTracker(limits=limits)
    stack: list[tuple[ET.Element, int]] = [(root, 1)]
    while stack:
        elem, depth = stack.pop()
        tracker.observe_element(elem, depth=depth)
        for child in reversed(elem):
            stack.append((child, depth + 1))


def count_packed_values(raw: str | None) -> int:
    if not raw:
        return 0
    if len(raw) <= _PACKED_VALUE_FAST_SPLIT_MAX_CHARS:
        if "," not in raw:
            return len(raw.split())
        return len(raw.replace(",", " ").split())
    return sum(1 for _match in _PACKED_VALUE_STREAMING_PATTERN.finditer(raw))
