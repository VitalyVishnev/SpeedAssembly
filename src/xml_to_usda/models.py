"""Domain models and stable public value types for the conversion pipeline.

Layer: domain.

This module defines the typed contracts shared across parsing, normalization,
application services, orchestration, USDA authoring, CLI, subprocess workers,
and UI adapters. It should stay free of GUI, filesystem, and process-control
implementation details.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

try:
    from enum import StrEnum
except ImportError:
    class StrEnum(str, Enum):
        pass


@dataclass(frozen=True, slots=True)
class Vector3:
    x: float
    y: float
    z: float

    def to_usda(self) -> str:
        return f"({self.x:g}, {self.y:g}, {self.z:g})"


@dataclass(frozen=True, slots=True)
class Vector2:
    x: float
    y: float

    def to_usda(self) -> str:
        return f"({self.x:g}, {self.y:g})"


@dataclass(frozen=True, slots=True)
class Color4:
    r: float
    g: float
    b: float
    a: float = 1.0

    def is_exact_black(self) -> bool:
        return self.r == 0.0 and self.g == 0.0 and self.b == 0.0

    def is_exact_white(self) -> bool:
        return self.r == 1.0 and self.g == 1.0 and self.b == 1.0


@dataclass(frozen=True, slots=True)
class Quaternion:
    real: float
    i: float
    j: float
    k: float

    def to_usda(self) -> str:
        return f"({self.real:g}, {self.i:g}, {self.j:g}, {self.k:g})"


class StaticCollisionPrimitiveType(StrEnum):
    CAPSULE = "capsule"
    SPHERE = "sphere"


class OutputMode(StrEnum):
    SELF_CONTAINED = "self_contained"
    EXTERNAL_REFS = "external_refs"


class ConversionMode(StrEnum):
    SKELETAL_ASSEMBLY = "skeletal_assembly"
    SKELETAL_PARTS = "skeletal_parts"
    STATIC_ASSEMBLY = "static_assembly"
    STATIC_PARTS = "static_parts"

    @classmethod
    def parse(cls, raw: "ConversionMode | str | None") -> "ConversionMode":
        if isinstance(raw, cls):
            return raw
        if raw is None:
            return cls.SKELETAL_ASSEMBLY
        normalized = str(raw).strip()
        return cls(normalized)


class MaterialPolicy(StrEnum):
    SOURCE_MATERIALS = "source_materials"
    SOURCE_MATERIAL_ROLES = "source_material_roles"
    SINGLE_MATERIAL = "single_material"
    VERTEX_COLOR_SPLIT = "vertex_color_split"

    @classmethod
    def parse(cls, raw: "MaterialPolicy | str | None") -> "MaterialPolicy":
        """Parse the canonical operator-facing material-policy values."""
        if isinstance(raw, cls):
            return raw
        if raw is None:
            return cls.SOURCE_MATERIALS
        normalized = str(raw).strip()
        if normalized == cls.SOURCE_MATERIAL_ROLES.value:
            return cls.SOURCE_MATERIALS
        return cls(normalized)

    @classmethod
    def cli_choices(cls) -> tuple[str, ...]:
        """Return the supported canonical CLI values."""
        return (
            cls.SOURCE_MATERIALS.value,
            cls.SINGLE_MATERIAL.value,
            cls.VERTEX_COLOR_SPLIT.value,
        )


class UdimMode(StrEnum):
    OFF = "off"
    SHIFT_PRIMARY_UV = "shift_primary_uv"
    WRITE_SECONDARY_UV_OFFSET = "write_secondary_uv_offset"

    @classmethod
    def parse(cls, raw: "UdimMode | str | None") -> "UdimMode":
        if isinstance(raw, cls):
            return raw
        if raw is None:
            return cls.OFF
        normalized = str(raw).strip()
        return cls(normalized)


class PrototypeStrategy(StrEnum):
    INLINE_SKELETAL_PART = "inline_skeletal_part"
    INLINE_STATIC_PART = "inline_static_part"
    REFERENCED_SCOPE = "referenced_scope"


class PrototypeResolutionMode(StrEnum):
    INLINE_MESH = "inline_mesh"
    EXTERNAL_ASSET = "external_asset"


class PrototypeSourceMode(StrEnum):
    XML_MESH = "xml_mesh"
    UNREAL_ASSET = "unreal_asset"
    FBX_FILE = "fbx_file"


class FbxMaterialMode(StrEnum):
    AUTO = "auto"
    VERTEX_COLOR_SPLIT = "vertex_color_split"
    SINGLE_MATERIAL = "single_material"
    MATERIAL_SLOTS = "material_slots"


class CpuProfile(StrEnum):
    BALANCED = "balanced"
    MAX_SPEED = "max_speed"
    QUIET = "quiet"


class CleanupPolicy(StrEnum):
    EPHEMERAL = "ephemeral"
    PRESERVE_FOR_DEBUGGING = "preserve_for_debugging"


class ConversionPhase(StrEnum):
    PREPARING = "preparing"
    XML_NORMALIZATION = "xml_normalization"
    PROTOTYPE_RESOLUTION = "prototype_resolution"
    FBX_IMPORT = "fbx_import"
    MATERIAL_RESOLUTION = "material_resolution"
    USDA_WRITING = "usda_writing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Joint:
    name: str
    source_id: int | None = None
    parent: str | None = None
    generator_label: str | None = None
    generator_level: int | None = None
    bind_transform: "Matrix4d" = field(default_factory=lambda: Matrix4d.identity())
    rest_transform: "Matrix4d" = field(default_factory=lambda: Matrix4d.identity())
    bind_end_transform: "Matrix4d | None" = None

    @property
    def bind_translate(self) -> Vector3:
        return self.bind_transform.translation

    @property
    def rest_translate(self) -> Vector3:
        return self.rest_transform.translation

    @property
    def bind_end_translate(self) -> Vector3 | None:
        bind_end_transform = getattr(self, "bind_end_transform", None)
        return None if bind_end_transform is None else bind_end_transform.translation


@dataclass(frozen=True, slots=True)
class MeshData:
    name: str
    points: tuple[Vector3, ...]
    face_vertex_counts: tuple[int, ...]
    face_vertex_indices: tuple[int, ...]
    uv_coords: tuple[Vector2, ...] = ()
    secondary_uv_coords: tuple[Vector2, ...] = ()
    vertex_colors: tuple[Color4, ...] = ()
    sections: tuple["MeshSection", ...] = ()
    skel_joint_indices: tuple[int, ...] = ()
    skel_joint_weights: tuple[float, ...] = ()
    skel_element_size: int = 0

    def __post_init__(self) -> None:
        for field_name in (
            "points",
            "face_vertex_counts",
            "face_vertex_indices",
            "uv_coords",
            "secondary_uv_coords",
            "vertex_colors",
            "sections",
            "skel_joint_indices",
            "skel_joint_weights",
        ):
            object.__setattr__(self, field_name, _materialized_tuple_field(self, field_name))


def _materialized_tuple_field(owner: object, field_name: str) -> tuple:
    value = getattr(owner, field_name)
    if isinstance(value, tuple):
        return value
    if isinstance(value, (str, bytes)):
        raise TypeError(f"{type(owner).__name__}.{field_name} must be tuple-compatible, got {type(value).__name__}.")
    try:
        return tuple(value)
    except TypeError as exc:
        raise TypeError(
            f"{type(owner).__name__}.{field_name} must be tuple-compatible, got {type(value).__name__}."
        ) from exc


@dataclass(frozen=True, slots=True)
class StaticCollisionPrimitive:
    name: str
    primitive_type: StaticCollisionPrimitiveType
    center: Vector3
    radius: float
    height: float = 0.0
    orientation: Quaternion = field(default_factory=lambda: Quaternion(1.0, 0.0, 0.0, 0.0))


@dataclass(frozen=True, slots=True)
class MaterialSpec:
    source_id: int
    name: str
    two_sided: bool = False
    maps: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()
    ue_asset_path: str | None = None
    source_material_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class BaseMaterialOverride:
    source_id: int
    source_name: str = ""
    ue_asset_path: str | None = None


@dataclass(frozen=True, slots=True)
class UdimMaterialSetting:
    material_id: int
    mode: UdimMode = UdimMode.OFF
    udim_id: int = 1001


@dataclass(frozen=True, slots=True)
class FbxMaterialSlotSpec:
    source_id: int
    name: str
    face_count: int = 0


@dataclass(frozen=True, slots=True)
class FbxMaterialSlotOverride:
    slot_name: str
    ue_asset_path: str | None = None
    udim_mode: UdimMode = UdimMode.OFF
    udim_id: int = 1001


@dataclass(frozen=True, slots=True)
class MeshSection:
    material_id: int
    face_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class CompactMeshSection:
    material_id: int
    face_indices: array = field(default_factory=lambda: array("i"))

    @property
    def face_count(self) -> int:
        return len(self.face_indices)


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
class Prototype:
    identity: "PrototypeIdentity"
    mesh: MeshData | None
    source_key: str
    source_mesh_id: int | None
    source_name: str
    prototype_type: str = "assembly_part"
    resolution_mode: PrototypeResolutionMode = PrototypeResolutionMode.INLINE_MESH
    source_mode: PrototypeSourceMode = PrototypeSourceMode.XML_MESH
    fbx_material_mode: FbxMaterialMode = FbxMaterialMode.AUTO
    mesh_asset_path: str | None = None
    fbx_source_path: str | None = None
    single_material_path: str | None = None
    single_material_udim_mode: UdimMode = UdimMode.OFF
    single_material_udim_id: int = 1001
    black_material_path: str | None = None
    black_material_udim_mode: UdimMode = UdimMode.OFF
    black_material_udim_id: int = 1001
    white_material_path: str | None = None
    white_material_udim_mode: UdimMode = UdimMode.OFF
    white_material_udim_id: int = 1001
    fbx_material_slot_overrides: tuple["FbxMaterialSlotOverride", ...] = ()
    simplification_percent: int = 100
    geometry_payload: "GeometryBuffer | None" = None

    def has_active_udim_settings(self) -> bool:
        return (
            self.single_material_udim_mode != UdimMode.OFF
            or self.black_material_udim_mode != UdimMode.OFF
            or self.white_material_udim_mode != UdimMode.OFF
            or any(override.udim_mode != UdimMode.OFF for override in self.fbx_material_slot_overrides)
        )


@dataclass(frozen=True, slots=True)
class GeometryBuffer:
    name: str
    point_components: array
    face_vertex_counts: array
    face_vertex_indices: array
    uv_components: array = field(default_factory=lambda: array("f"))
    secondary_uv_components: array = field(default_factory=lambda: array("f"))
    vertex_color_components: array = field(default_factory=lambda: array("f"))
    vertex_color_warning: str | None = None
    fbx_material_slots: tuple["FbxMaterialSlotSpec", ...] = ()
    sections: tuple[CompactMeshSection, ...] = ()
    skel_joint_indices: array = field(default_factory=lambda: array("i"))
    skel_joint_weights: array = field(default_factory=lambda: array("f"))
    skel_element_size: int = 0

    @property
    def point_count(self) -> int:
        return len(self.point_components) // 3

    @property
    def face_count(self) -> int:
        return len(self.face_vertex_counts)

    @property
    def uv_count(self) -> int:
        return len(self.uv_components) // 2

    @property
    def secondary_uv_count(self) -> int:
        return len(self.secondary_uv_components) // 2

    @property
    def vertex_color_count(self) -> int:
        return len(self.vertex_color_components) // 4

    @property
    def has_vertex_colors(self) -> bool:
        return self.vertex_color_count > 0


@dataclass(frozen=True, slots=True)
class PrototypeSourceConfig:
    source_key: str
    source_name: str = ""
    mode: PrototypeSourceMode = PrototypeSourceMode.XML_MESH
    fbx_material_mode: FbxMaterialMode = FbxMaterialMode.AUTO
    asset_path: str | None = None
    fbx_path: str | None = None
    single_material_path: str | None = None
    single_material_udim_mode: UdimMode = UdimMode.OFF
    single_material_udim_id: int = 1001
    black_material_path: str | None = None
    black_material_udim_mode: UdimMode = UdimMode.OFF
    black_material_udim_id: int = 1001
    white_material_path: str | None = None
    white_material_udim_mode: UdimMode = UdimMode.OFF
    white_material_udim_id: int = 1001
    fbx_material_slot_overrides: tuple["FbxMaterialSlotOverride", ...] = ()
    simplification_percent: int = 100

    def has_active_udim_settings(self) -> bool:
        return (
            self.single_material_udim_mode != UdimMode.OFF
            or self.black_material_udim_mode != UdimMode.OFF
            or self.white_material_udim_mode != UdimMode.OFF
            or any(override.udim_mode != UdimMode.OFF for override in self.fbx_material_slot_overrides)
        )


@dataclass(frozen=True, slots=True)
class PrototypeDiscoveryEntry:
    source_key: str
    source_mesh_id: int | None
    source_name: str
    instance_count: int = 0


@dataclass(frozen=True, slots=True)
class ConversionTelemetry:
    phase: ConversionPhase
    completed_units: int = 0
    total_units: int = 0
    message: str = ""
    output_bytes_written: int = 0
    elapsed_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class ExportStats:
    bytes_written: int = 0
    duration_seconds: float = 0.0
    streamed: bool = False


@dataclass(frozen=True, slots=True)
class ConversionJobResult:
    result: "ConversionResult | None" = None
    telemetry: ConversionTelemetry | None = None
    cancelled: bool = False
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class Bounds:
    minimum: Vector3
    maximum: Vector3


@dataclass(frozen=True, slots=True)
class SpineCurve:
    source_object_id: str
    points: tuple[Vector3, ...]
    radii: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class MeshLibraryEntry:
    mesh_id: int
    name: str
    mesh: MeshData
    original_scale: float | None = None


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
class BranchSegment:
    object_id: str
    parent_id: str | None
    name: str
    mesh: MeshData
    spine: SpineCurve | None = None
    source_joint: str | None = None


@dataclass(frozen=True, slots=True)
class BaseTreePart:
    object_id: str
    parent_id: str | None
    name: str
    translate: Vector3
    point_offset: int
    point_count: int
    face_offset: int
    face_count: int


@dataclass(frozen=True, slots=True)
class RepeatedPartInstance:
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


@dataclass(frozen=True, slots=True)
class AuthoredAssemblyPartInstance:
    name: str
    prototype_key: str
    position: Vector3
    orientation: Quaternion
    scale: Vector3
    binding: InstanceBinding

    @property
    def bind_joint(self) -> str:
        return self.binding.joint_tokens[0] if self.binding.joint_tokens else ""

    @property
    def bind_weight(self) -> float:
        return self.binding.weights[0] if self.binding.weights else 0.0


@dataclass(frozen=True, slots=True)
class PrototypeIdentity:
    source_key: str
    prim_name: str
    prototype_type: str = "assembly_part"


@dataclass(frozen=True, slots=True)
class SourceSampleMetadata:
    sample_id: str
    source_path: str
    speedtree_version: str | None = None
    export_profile: str | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResourceIndexEntry:
    resource_path: str
    category: str
    source_label: str
    version_hint: str | None = None
    acquired_on: str | None = None
    purpose: str = ""


@dataclass(frozen=True, slots=True)
class ExportMetadata:
    source_path: str
    source_version: str | None
    meters_per_unit: float = 1.0
    up_axis: str = "Y"
    warnings: tuple[str, ...] = ()
    unknown_sections: tuple[str, ...] = ()
    output_mode: OutputMode = OutputMode.SELF_CONTAINED
    material_policy: MaterialPolicy = MaterialPolicy.SOURCE_MATERIALS
    conversion_mode: ConversionMode = ConversionMode.SKELETAL_ASSEMBLY


@dataclass(frozen=True, slots=True)
class SkeletalSupportPrimvars:
    capture_paths: tuple[str, ...]
    ue_joint_names: tuple[str, ...]
    hierarchical_depths: tuple[int, ...]
    logical_depths: tuple[int, ...]
    local_transform: Matrix4d = field(default_factory=Matrix4d.identity)


@dataclass(frozen=True, slots=True)
class SourceXmlDocument:
    source_path: str
    root_tag: str
    tree: Any


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
class TreeAsset:
    metadata: ExportMetadata
    materials: tuple[MaterialSpec, ...]
    source_objects: tuple[SourceObject, ...]
    base_mesh: MeshData | None
    skeleton: tuple[Joint, ...]
    assembly_parts: tuple[RepeatedPartInstance, ...]
    base_tree_parts: tuple[BaseTreePart, ...] = ()
    branch_segments: tuple[BranchSegment, ...] = ()
    mesh_library: tuple[MeshLibraryEntry, ...] = ()
    prototypes: tuple[Prototype, ...] = ()
    prototype_strategy: PrototypeStrategy = PrototypeStrategy.REFERENCED_SCOPE
    skeletal_support_primvars: SkeletalSupportPrimvars | None = None
    spines: tuple[SpineCurve, ...] = ()
    dynamic_wind: "DynamicWindData | None" = None
    static_collision_meshes: tuple[MeshData, ...] = ()
    static_collision_primitives: tuple[StaticCollisionPrimitive, ...] = ()

    def __getattribute__(self, name: str):
        if name in {"static_collision_meshes", "static_collision_primitives"}:
            try:
                return object.__getattribute__(self, name)
            except AttributeError:
                object.__setattr__(self, name, ())
                return ()
        return object.__getattribute__(self, name)

    @property
    def binding_mode(self) -> str:
        if not self.repeated_parts:
            return "none"
        max_width = max(part.binding.element_size for part in self.repeated_parts)
        return "single_joint" if max_width <= 1 else "multi_joint_capable"

    def __setstate__(self, state) -> None:
        values = list(state)
        if len(values) == 14:
            values.append(())
        if len(values) == 15:
            values.append(())
        fields = (
            "metadata",
            "materials",
            "source_objects",
            "base_mesh",
            "skeleton",
            "assembly_parts",
            "base_tree_parts",
            "branch_segments",
            "mesh_library",
            "prototypes",
            "prototype_strategy",
            "skeletal_support_primvars",
            "spines",
            "dynamic_wind",
            "static_collision_meshes",
            "static_collision_primitives",
        )
        for name, value in zip(fields, values):
            object.__setattr__(self, name, value)

    @property
    def binding_element_size(self) -> int:
        return max((part.binding.element_size for part in self.repeated_parts), default=0)

    @property
    def repeated_parts(self) -> tuple[RepeatedPartInstance, ...]:
        """Preferred source-level name for repeated part records from LeafReferences."""
        return self.assembly_parts


CanonicalTreeModel = TreeAsset


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    severity: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ResolvedAssemblyModel:
    """Authoring-stage model: source facts plus operator intent resolution."""
    source_model: CanonicalTreeModel
    authoring_model: CanonicalTreeModel
    conversion_mode: ConversionMode
    output_stem: str | None = None
    udim_material_settings: tuple[UdimMaterialSetting, ...] = ()
    source_diagnostics: tuple[ValidationIssue, ...] = ()
    resolution_diagnostics: tuple[ValidationIssue, ...] = ()
    authoring_diagnostics: tuple[ValidationIssue, ...] = ()

    @property
    def diagnostics(self) -> tuple[ValidationIssue, ...]:
        return self.source_diagnostics + self.resolution_diagnostics + self.authoring_diagnostics


@dataclass(frozen=True, slots=True)
class UsdAssemblyDocument:
    text: str | None
    diagnostics: tuple[ValidationIssue, ...]
    stats: ExportStats = field(default_factory=ExportStats)


@dataclass(frozen=True, slots=True)
class ConversionRequest:
    input_paths: tuple[str, ...]
    output_path: str | None = None
    output_directory: str | None = None
    output_naming_template: str | None = None
    output_mode: OutputMode = OutputMode.SELF_CONTAINED
    material_policy: MaterialPolicy = MaterialPolicy.SOURCE_MATERIALS
    bark_material_path: str | None = None
    leaves_material_path: str | None = None
    single_material_path: str | None = None
    base_material_overrides: tuple[BaseMaterialOverride, ...] = ()
    udim_material_settings: tuple[UdimMaterialSetting, ...] = ()
    cpu_profile: CpuProfile = CpuProfile.BALANCED
    cleanup_policy: CleanupPolicy = CleanupPolicy.EPHEMERAL
    use_explicit_material_contract: bool = False
    prototype_source_configs: tuple[PrototypeSourceConfig, ...] = ()
    conversion_mode: ConversionMode = ConversionMode.SKELETAL_ASSEMBLY
    fbx_cache_max_bytes: int = 20 * 1024 * 1024 * 1024
    fbx_cache_max_age_seconds: int = 14 * 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class ConversionResult:
    input_path: str
    output_path: str | None
    diagnostics: tuple[ValidationIssue, ...]
    usda_document: UsdAssemblyDocument | None = None
    telemetry: tuple[ConversionTelemetry, ...] = ()
    runtime_job_dir: str | None = None


@dataclass(frozen=True, slots=True)
class DynamicWindJointAssignment:
    joint_name: str
    simulation_group_index: int
    branch_order: int


@dataclass(frozen=True, slots=True)
class DynamicWindSimulationGroup:
    group_index: int
    branch_order: int
    influence: float = 1.0
    shift_top: float = 0.5
    is_trunk_group: bool = False
    use_dual_influence: bool = True
    min_influence: float = 0.5
    max_influence: float = 1.0


@dataclass(frozen=True, slots=True)
class DynamicWindData:
    joint_assignments: tuple[DynamicWindJointAssignment, ...]
    simulation_groups: tuple[DynamicWindSimulationGroup, ...]
    is_ground_cover: bool = False
    gust_attenuation: float = 0.0


@dataclass(frozen=True, slots=True)
class WindJsonResult:
    input_path: str
    output_path: str
    dynamic_wind: DynamicWindData
