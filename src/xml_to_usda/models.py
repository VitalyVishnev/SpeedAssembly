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


class PrototypeStrategy(StrEnum):
    INLINE_SKELETAL_PART = "inline_skeletal_part"
    REFERENCED_SCOPE = "referenced_scope"


class PrototypeResolutionMode(StrEnum):
    INLINE_MESH = "inline_mesh"
    EXTERNAL_ASSET = "external_asset"


@dataclass(frozen=True)
class Joint:
    name: str
    source_id: int | None = None
    parent: str | None = None
    bind_transform: "Matrix4d" = field(default_factory=lambda: Matrix4d.identity())
    rest_transform: "Matrix4d" = field(default_factory=lambda: Matrix4d.identity())

    @property
    def bind_translate(self) -> Vector3:
        return self.bind_transform.translation

    @property
    def rest_translate(self) -> Vector3:
        return self.rest_transform.translation


@dataclass(frozen=True)
class MeshData:
    name: str
    points: tuple[Vector3, ...]
    face_vertex_counts: tuple[int, ...]
    face_vertex_indices: tuple[int, ...]
    sections: tuple["MeshSection", ...] = ()
    skel_joint_indices: tuple[int, ...] = ()
    skel_joint_weights: tuple[float, ...] = ()
    skel_element_size: int = 0


@dataclass(frozen=True)
class MaterialSpec:
    source_id: int
    name: str
    two_sided: bool = False
    maps: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()
    ue_asset_path: str | None = None


@dataclass(frozen=True)
class MeshSection:
    material_id: int
    face_indices: tuple[int, ...]


@dataclass(frozen=True)
class Matrix4d:
    rows: tuple[tuple[float, float, float, float], ...]

    def to_usda(self) -> str:
        row_payload = ", ".join(f"({', '.join(f'{value:g}' for value in row)})" for row in self.rows)
        return f"( {row_payload} )"

    @staticmethod
    def identity() -> "Matrix4d":
        return Matrix4d(
            rows=(
                (1.0, 0.0, 0.0, 0.0),
                (0.0, 1.0, 0.0, 0.0),
                (0.0, 0.0, 1.0, 0.0),
                (0.0, 0.0, 0.0, 1.0),
            )
        )

    @staticmethod
    def from_translation(translate: Vector3) -> "Matrix4d":
        return Matrix4d(
            rows=(
                (1.0, 0.0, 0.0, 0.0),
                (0.0, 1.0, 0.0, 0.0),
                (0.0, 0.0, 1.0, 0.0),
                (translate.x, translate.y, translate.z, 1.0),
            )
        )

    @property
    def translation(self) -> Vector3:
        row = self.rows[3]
        return Vector3(row[0], row[1], row[2])


@dataclass(frozen=True)
class InstanceBinding:
    joint_tokens: tuple[str, ...]
    weights: tuple[float, ...]

    @property
    def element_size(self) -> int:
        return len(self.joint_tokens)

    def padded(self, width: int) -> "InstanceBinding":
        if width <= self.element_size:
            return self
        if self.element_size == 0:
            return InstanceBinding(joint_tokens=("",) * width, weights=(0.0,) * width)
        pad_joint = self.joint_tokens[-1]
        pad_weights = (0.0,) * (width - self.element_size)
        return InstanceBinding(
            joint_tokens=self.joint_tokens + (pad_joint,) * (width - self.element_size),
            weights=self.weights + pad_weights,
        )

    @property
    def mode(self) -> str:
        return "single_joint" if self.element_size <= 1 else "multi_joint"


@dataclass(frozen=True)
class Prototype:
    identity: "PrototypeIdentity"
    mesh: MeshData | None
    source_key: str
    source_mesh_id: int | None
    source_name: str
    prototype_type: str = "assembly_part"
    resolution_mode: PrototypeResolutionMode = PrototypeResolutionMode.INLINE_MESH
    mesh_asset_path: str | None = None


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
    original_scale: float | None = None


@dataclass(frozen=True)
class SourceObject:
    object_id: str
    parent_id: str | None
    name: str
    abs_translate: Vector3
    rel_translate: Vector3
    bounds: Bounds | None = None
    mesh: MeshData | None = None
    assembly_part_reference_count: int = 0
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
class BaseTreePart:
    object_id: str
    parent_id: str | None
    name: str
    translate: Vector3
    point_offset: int
    point_count: int
    face_offset: int
    face_count: int


@dataclass(frozen=True)
class AssemblyPartInstance:
    name: str
    prototype_key: str
    position: Vector3
    orientation: Quaternion
    scale: Vector3
    binding: InstanceBinding
    source_object_id: str | None
    source_mesh_id: int | None
    source_material_id: int | None = None
    source_bone_ids: tuple[int, ...] = ()
    mesh_lod: int | None = None

    @property
    def bind_joint(self) -> str:
        return self.binding.joint_tokens[0] if self.binding.joint_tokens else ""

    @property
    def bind_weight(self) -> float:
        return self.binding.weights[0] if self.binding.weights else 0.0

    @property
    def source_bone_id(self) -> int | None:
        return self.source_bone_ids[0] if self.source_bone_ids else None


@dataclass(frozen=True)
class PrototypeIdentity:
    source_key: str
    prim_name: str
    prototype_type: str = "assembly_part"


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
    meters_per_unit: float = 1.0
    up_axis: str = "Y"
    warnings: tuple[str, ...] = ()
    unknown_sections: tuple[str, ...] = ()
    output_mode: OutputMode = OutputMode.SELF_CONTAINED


@dataclass(frozen=True)
class SkeletalSupportPrimvars:
    capture_paths: tuple[str, ...]
    ue_joint_names: tuple[str, ...]
    hierarchical_depths: tuple[int, ...]
    logical_depths: tuple[int, ...]
    local_transform: Matrix4d = field(default_factory=Matrix4d.identity)


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
    leaf_source_object_distribution: dict[str, int] = field(default_factory=dict)
    material_count: int = 0
    base_material_distribution: dict[str, int] = field(default_factory=dict)
    prototype_material_distribution: dict[str, int] = field(default_factory=dict)
    base_geometry_mode: str = "unknown"
    base_mesh_part_count: int = 0
    base_mesh_point_count: int = 0
    base_mesh_face_count: int = 0
    prototype_structure: str = "unknown"
    binding_mode: str = "none"
    binding_element_size: int = 0
    support_primvars: tuple[str, ...] = ()
    orientation_sample: tuple[str, ...] = ()


@dataclass(frozen=True)
class TreeAsset:
    metadata: ExportMetadata
    materials: tuple[MaterialSpec, ...]
    source_objects: tuple[SourceObject, ...]
    base_mesh: MeshData | None
    skeleton: tuple[Joint, ...]
    assembly_parts: tuple[AssemblyPartInstance, ...]
    base_tree_parts: tuple[BaseTreePart, ...] = ()
    branch_segments: tuple[BranchSegment, ...] = ()
    mesh_library: tuple[MeshLibraryEntry, ...] = ()
    prototypes: tuple[Prototype, ...] = ()
    prototype_strategy: PrototypeStrategy = PrototypeStrategy.REFERENCED_SCOPE
    skeletal_support_primvars: SkeletalSupportPrimvars | None = None
    spines: tuple[SpineCurve, ...] = ()

    @property
    def binding_mode(self) -> str:
        if not self.assembly_parts:
            return "none"
        max_width = max(part.binding.element_size for part in self.assembly_parts)
        return "single_joint" if max_width <= 1 else "multi_joint_capable"

    @property
    def binding_element_size(self) -> int:
        return max((part.binding.element_size for part in self.assembly_parts), default=0)


CanonicalTreeModel = TreeAsset


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
    bark_material_path: str | None = None
    leaves_material_path: str | None = None
    use_existing_part_meshes: bool = False
    part_mesh_asset_paths: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ConversionResult:
    input_path: str
    output_path: str | None
    diagnostics: tuple[ValidationIssue, ...]
    usda_document: UsdAssemblyDocument | None = None
