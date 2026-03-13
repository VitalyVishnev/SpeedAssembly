from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


@dataclass(frozen=True)
class Vector3:
    x: float
    y: float
    z: float

    def to_usda(self) -> str:
        return f"({self.x:g}, {self.y:g}, {self.z:g})"


@dataclass(frozen=True)
class Quaternion:
    real: float
    i: float
    j: float
    k: float

    def to_usda(self) -> str:
        return f"({self.real:g}, {self.i:g}, {self.j:g}, {self.k:g})"


class OutputMode(StrEnum):
    SELF_CONTAINED = "self_contained"
    EXTERNAL_REFS = "external_refs"


@dataclass(frozen=True)
class Joint:
    name: str
    parent: str | None = None
    bind_translate: Vector3 = field(default_factory=lambda: Vector3(0.0, 0.0, 0.0))


@dataclass(frozen=True)
class MeshData:
    name: str
    points: tuple[Vector3, ...]
    face_vertex_counts: tuple[int, ...]
    face_vertex_indices: tuple[int, ...]


@dataclass(frozen=True)
class LeafReference:
    name: str
    prototype_key: str
    position: Vector3
    orientation: Quaternion
    scale: Vector3
    bind_joint: str
    bind_weight: float = 1.0


@dataclass(frozen=True)
class Bounds:
    minimum: Vector3
    maximum: Vector3


@dataclass(frozen=True)
class SpineCurve:
    source_object_id: str
    points: tuple[Vector3, ...]
    radii: tuple[float, ...]


@dataclass(frozen=True)
class MeshLibraryEntry:
    mesh_id: int
    name: str
    mesh: MeshData


@dataclass(frozen=True)
class SourceObject:
    object_id: str
    parent_id: str | None
    name: str
    abs_translate: Vector3
    rel_translate: Vector3
    bounds: Bounds | None = None
    mesh: MeshData | None = None
    leaf_instance_count: int = 0
    spine: SpineCurve | None = None


@dataclass(frozen=True)
class BranchSegment:
    object_id: str
    parent_id: str | None
    name: str
    mesh: MeshData
    spine: SpineCurve | None = None
    source_joint: str | None = None


@dataclass(frozen=True)
class LeafInstance:
    name: str
    prototype_key: str
    position: Vector3
    orientation: Quaternion
    scale: Vector3
    bind_joint: str
    source_object_id: str | None
    source_mesh_id: int | None
    source_bone_id: int | None
    mesh_lod: int | None = None
    bind_weight: float = 1.0


@dataclass(frozen=True)
class PrototypeIdentity:
    source_key: str
    prim_name: str
    prototype_type: str = "leaf"


@dataclass(frozen=True)
class SourceSampleMetadata:
    sample_id: str
    source_path: str
    speedtree_version: str | None = None
    export_profile: str | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResourceIndexEntry:
    resource_path: str
    category: str
    source_label: str
    version_hint: str | None = None
    acquired_on: str | None = None
    purpose: str = ""


@dataclass(frozen=True)
class ExportMetadata:
    source_path: str
    source_version: str | None
    meters_per_unit: float = 0.01
    up_axis: str = "Z"
    warnings: tuple[str, ...] = ()
    unknown_sections: tuple[str, ...] = ()
    output_mode: OutputMode = OutputMode.SELF_CONTAINED


@dataclass(frozen=True)
class SourceXmlDocument:
    source_path: str
    root_tag: str
    tree: Any


@dataclass(frozen=True)
class ObservedXmlSchemaReport:
    source_path: str
    root_tag: str
    tag_counts: dict[str, int]
    attributes_by_tag: dict[str, tuple[str, ...]]
    known_sections: dict[str, int]
    unknown_sections: tuple[str, ...]
    version: str | None
    units_hint: str | None
    up_axis_hint: str | None
    object_class_counts: dict[str, int] = field(default_factory=dict)
    hierarchy_depth: int = 0
    spine_object_count: int = 0
    leaf_binding_distribution: dict[str, int] = field(default_factory=dict)
    leaf_mesh_distribution: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class CanonicalTreeModel:
    metadata: ExportMetadata
    source_objects: tuple[SourceObject, ...]
    trunk_mesh: MeshData | None
    skeleton: tuple[Joint, ...]
    leaf_instances: tuple[LeafInstance, ...]
    branch_segments: tuple[BranchSegment, ...] = ()
    mesh_library: tuple[MeshLibraryEntry, ...] = ()
    spines: tuple[SpineCurve, ...] = ()

    @property
    def leaf_references(self) -> tuple[LeafInstance, ...]:
        return self.leaf_instances


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    message: str


@dataclass(frozen=True)
class UsdAssemblyDocument:
    text: str
    diagnostics: tuple[ValidationIssue, ...]


@dataclass(frozen=True)
class ConversionRequest:
    input_paths: tuple[str, ...]
    output_path: str | None = None
    output_directory: str | None = None
    output_naming_template: str | None = None
    output_mode: OutputMode = OutputMode.SELF_CONTAINED


@dataclass(frozen=True)
class ConversionResult:
    input_path: str
    output_path: str | None
    diagnostics: tuple[ValidationIssue, ...]
    usda_document: UsdAssemblyDocument | None = None
