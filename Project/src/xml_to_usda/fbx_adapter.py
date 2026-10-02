"""FBX adapter backed by the vendored official ufbx C library.

The public contract is deliberately small: rigid prototype geometry plus a
read-only skinned FBX payload for Advanced Wind Settings diagnostics. The
native module runs only in an isolated worker boundary.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from array import array
from dataclasses import dataclass
from pathlib import Path

from .job_control import apply_process_profile, emit_telemetry, throw_if_cancelled
from .models import (
    CompactMeshSection,
    ConversionPhase,
    CpuProfile,
    FbxMaterialSlotSpec,
    GeometryBuffer,
    Joint,
    Matrix4d,
    MeshData,
    ValidationIssue,
    Vector3,
)


class FbxImportError(ValueError):
    pass


class FbxBackendUnavailableError(FbxImportError):
    pass


@dataclass(frozen=True, slots=True)
class FbxSkeletalPreview:
    skeleton: tuple[Joint, ...]
    mesh: MeshData | None
    diagnostics: tuple[ValidationIssue, ...]


class FbxBackend:
    def load_mesh_payload(
        self,
        fbx_path: str,
        prototype_name: str,
        *,
        cpu_profile: CpuProfile,
        strict_vertex_colors: bool = False,
        read_vertex_colors: bool = True,
        read_material_slots: bool = True,
        telemetry_callback=None,
        cancel_event=None,
    ) -> GeometryBuffer:
        raise NotImplementedError

    def inspect_material_slots(
        self,
        fbx_path: str,
        *,
        cpu_profile: CpuProfile,
        cancel_event=None,
    ) -> tuple[FbxMaterialSlotSpec, ...]:
        raise NotImplementedError


@dataclass(frozen=True)
class UfbxBackend(FbxBackend):
    def load_mesh_payload(
        self,
        fbx_path: str,
        prototype_name: str,
        *,
        cpu_profile: CpuProfile,
        strict_vertex_colors: bool = False,
        read_vertex_colors: bool = True,
        read_material_slots: bool = True,
        telemetry_callback=None,
        cancel_event=None,
    ) -> GeometryBuffer:
        started_at = time.perf_counter()
        apply_process_profile(cpu_profile)
        throw_if_cancelled(cancel_event)
        native = _load_ufbx_native()
        try:
            raw = native.load_geometry(
                str(fbx_path),
                bool(read_vertex_colors),
                bool(read_material_slots),
            )
        except ValueError as exc:
            raise FbxImportError(str(exc)) from exc
        throw_if_cancelled(cancel_event)
        _emit_fbx_stage(telemetry_callback, f"Loaded FBX scene {Path(fbx_path).name} with ufbx.", started_at)
        payload = _geometry_from_native_payload(raw, prototype_name)
        if strict_vertex_colors and read_vertex_colors and not payload.vertex_color_components:
            raise FbxImportError(
                f"FBX vertex colors are required for vertex_color_split but are missing or unusable: {Path(fbx_path).name}"
            )
        _emit_fbx_stage(telemetry_callback, f"Imported FBX payload {Path(fbx_path).name}.", started_at)
        return payload

    def inspect_material_slots(
        self,
        fbx_path: str,
        *,
        cpu_profile: CpuProfile,
        cancel_event=None,
    ) -> tuple[FbxMaterialSlotSpec, ...]:
        apply_process_profile(cpu_profile)
        throw_if_cancelled(cancel_event)
        native = _load_ufbx_native()
        try:
            raw_slots = native.inspect_material_slots(str(fbx_path))
        except ValueError as exc:
            raise FbxImportError(str(exc)) from exc
        throw_if_cancelled(cancel_event)
        return tuple(
            FbxMaterialSlotSpec(source_id=index, name=str(name), face_count=int(face_count))
            for index, (name, face_count) in enumerate(raw_slots, start=1)
        )


@dataclass(frozen=True)
class JsonGeometryBackend(FbxBackend):
    """Deterministic test backend for pipeline regression tests."""

    def load_mesh_payload(
        self,
        fbx_path: str,
        prototype_name: str,
        *,
        cpu_profile: CpuProfile,
        strict_vertex_colors: bool = False,
        read_vertex_colors: bool = True,
        read_material_slots: bool = True,
        telemetry_callback=None,
        cancel_event=None,
    ) -> GeometryBuffer:
        payload = json.loads(Path(fbx_path).read_text(encoding="utf-8"))
        return GeometryBuffer(
            name=prototype_name,
            point_components=array("f", payload["point_components"]),
            face_vertex_counts=array("i", payload["face_vertex_counts"]),
            face_vertex_indices=array("i", payload["face_vertex_indices"]),
            uv_components=array("f", payload.get("uv_components", [])),
            vertex_color_components=array(
                "f",
                payload.get("vertex_color_components", []) if read_vertex_colors else [],
            ),
            vertex_color_warning=payload.get("vertex_color_warning"),
            fbx_material_slots=tuple(
                FbxMaterialSlotSpec(
                    source_id=int(slot["source_id"]),
                    name=str(slot["name"]),
                    face_count=int(slot.get("face_count", 0)),
                )
                for slot in payload.get("fbx_material_slots", [])
            ) if read_material_slots else (),
            sections=tuple(
                CompactMeshSection(
                    material_id=int(section["material_id"]),
                    face_indices=array("i", section.get("face_indices", [])),
                )
                for section in payload.get("sections", [])
            ) if read_material_slots else (),
        )

    def inspect_material_slots(
        self,
        fbx_path: str,
        *,
        cpu_profile: CpuProfile,
        cancel_event=None,
    ) -> tuple[FbxMaterialSlotSpec, ...]:
        payload = json.loads(Path(fbx_path).read_text(encoding="utf-8"))
        explicit_slots = payload.get("fbx_material_slots", [])
        if explicit_slots:
            return tuple(
                FbxMaterialSlotSpec(
                    source_id=int(slot["source_id"]),
                    name=str(slot["name"]),
                    face_count=int(slot.get("face_count", 0)),
                )
                for slot in explicit_slots
            )
        return tuple(
            FbxMaterialSlotSpec(
                source_id=index,
                name=f"MaterialSlot_{index}",
                face_count=len(section.get("face_indices", [])),
            )
            for index, section in enumerate(payload.get("sections", []), start=1)
        )


_BACKEND_OVERRIDE: FbxBackend | None = None


def set_fbx_backend_for_testing(backend: FbxBackend | None) -> None:
    global _BACKEND_OVERRIDE
    _BACKEND_OVERRIDE = backend


def get_fbx_backend(fbx_path: str) -> FbxBackend:
    if _BACKEND_OVERRIDE is not None:
        return _BACKEND_OVERRIDE
    if Path(fbx_path).suffix.lower() == ".json":
        if os.environ.get("XML_TO_USDA_ENABLE_JSON_GEOMETRY_BACKEND") != "1":
            raise FbxImportError("JSON geometry backend is test-only and is not enabled for production prototype sources.")
        return JsonGeometryBackend()
    return UfbxBackend()


def load_fbx_geometry(
    fbx_path: str,
    prototype_name: str,
    *,
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
    strict_vertex_colors: bool = False,
    read_vertex_colors: bool = True,
    read_material_slots: bool = True,
    telemetry_callback=None,
    cancel_event=None,
) -> GeometryBuffer:
    return get_fbx_backend(fbx_path).load_mesh_payload(
        fbx_path,
        prototype_name,
        cpu_profile=cpu_profile,
        strict_vertex_colors=strict_vertex_colors,
        read_vertex_colors=read_vertex_colors,
        read_material_slots=read_material_slots,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
    )


def inspect_fbx_material_slots(
    fbx_path: str,
    *,
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
    cancel_event=None,
) -> tuple[FbxMaterialSlotSpec, ...]:
    return get_fbx_backend(fbx_path).inspect_material_slots(
        fbx_path,
        cpu_profile=cpu_profile,
        cancel_event=cancel_event,
    )


def load_fbx_skeleton(fbx_path: str) -> tuple[Joint, ...]:
    native = _load_ufbx_native()
    try:
        rows = native.load_skeleton(str(fbx_path))
    except ValueError as exc:
        raise FbxImportError(str(exc)) from exc
    return tuple(
        Joint(
            name=str(name),
            source_id=index,
            parent=None if not parent else str(parent),
            bind_transform=Matrix4d.from_translation(Vector3(float(x), float(y), float(z))),
            rest_transform=Matrix4d.from_translation(Vector3(float(x), float(y), float(z))),
        )
        for index, (name, parent, x, y, z) in enumerate(rows)
    )


def load_fbx_skeletal_preview(fbx_path: str) -> FbxSkeletalPreview:
    """Load the FBX rest mesh and report source rig defects without repairing it."""
    native = _load_ufbx_native()
    try:
        raw = native.load_skeletal_preview(str(fbx_path))
    except ValueError as exc:
        raise FbxImportError(str(exc)) from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("joints"), list) or not isinstance(raw.get("stats"), dict):
        raise FbxImportError("ufbx returned an invalid skeletal preview payload.")

    joint_rows = raw["joints"]
    joint_names = tuple(str(row[0]) for row in joint_rows)
    skeleton = tuple(
        Joint(
            name=joint_names[index],
            source_id=index,
            parent=joint_names[int(row[1])] if int(row[1]) >= 0 else None,
            bind_transform=_matrix_from_values(row[2], "joint world transform"),
            rest_transform=_matrix_from_values(row[3], "joint local transform"),
        )
        for index, row in enumerate(joint_rows)
    )
    points = _vectors_from_float_bytes(raw.get("point_components"), "point components")
    face_counts = tuple(_array_from_bytes(raw.get("face_vertex_counts"), "i", "face vertex counts"))
    face_indices = tuple(_array_from_bytes(raw.get("face_vertex_indices"), "i", "face vertex indices"))
    joint_indices = tuple(_array_from_bytes(raw.get("skel_joint_indices"), "i", "joint indices"))
    joint_weights = tuple(_array_from_bytes(raw.get("skel_joint_weights"), "f", "joint weights"))
    mesh = None
    if points and face_counts and face_indices:
        mesh = MeshData(
            name=f"{Path(fbx_path).stem}_ExternalPreview",
            points=points,
            face_vertex_counts=face_counts,
            face_vertex_indices=face_indices,
            skel_joint_indices=joint_indices,
            skel_joint_weights=joint_weights,
            skel_element_size=4,
        )
    diagnostics = _external_fbx_diagnostics(
        skeleton,
        joint_rows,
        mesh,
        raw["stats"],
    )
    return FbxSkeletalPreview(skeleton=skeleton, mesh=mesh, diagnostics=diagnostics)


def _external_fbx_diagnostics(
    skeleton: tuple[Joint, ...],
    joint_rows: list,
    mesh: MeshData | None,
    stats: dict,
) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    mesh_count = int(stats.get("mesh_count", 0))
    vertex_count = len(mesh.points) if mesh is not None else 0
    triangle_count = len(mesh.face_vertex_counts) if mesh is not None else 0
    unit_meters = float(stats.get("unit_meters", 0.0))
    up_axis = _FBX_AXIS_NAMES.get(int(stats.get("up_axis", 6)), "unknown")
    issues.append(_fbx_issue(
        "info",
        "external_fbx_summary",
        f"{len(skeleton)} bones, {mesh_count} mesh node(s), {vertex_count} vertices, {triangle_count} triangles; source unit {unit_meters:g} m, up axis {up_axis}.",
    ))
    if mesh is None:
        issues.append(_fbx_issue("error", "external_fbx_missing_mesh", "FBX contains no readable mesh topology; only the skeleton can be previewed."))
    skin_count = int(stats.get("skin_deformer_count", 0))
    if mesh_count and skin_count == 0:
        issues.append(_fbx_issue("error", "external_fbx_missing_skin", "FBX mesh has no skin deformer. Wind can only rotate it as an unskinned rigid object."))
    elif skin_count > mesh_count:
        issues.append(_fbx_issue("warning", "external_fbx_multiple_skins", f"FBX has {skin_count} skin deformers for {mesh_count} mesh node(s); preview uses the first skin on each mesh."))
    non_linear_skins = int(stats.get("non_linear_skin_deformer_count", 0))
    if non_linear_skins:
        issues.append(_fbx_issue("warning", "external_fbx_non_linear_skinning", f"{non_linear_skins} skin deformer(s) use dual-quaternion or blended skinning; verify Unreal's imported linear weights."))

    unweighted = int(stats.get("unweighted_vertex_count", 0))
    if unweighted:
        issues.append(_fbx_issue("error", "external_fbx_unweighted_vertices", f"{unweighted} of {vertex_count} vertices have no usable bone influence."))
    invalid_weights = int(stats.get("invalid_weight_count", 0))
    if invalid_weights:
        issues.append(_fbx_issue("error", "external_fbx_invalid_weights", f"FBX contains {invalid_weights} invalid or unmapped skin influence(s)."))
    invalid_bind_matrices = int(stats.get("invalid_bind_matrix_count", 0))
    if invalid_bind_matrices:
        issues.append(_fbx_issue("error", "external_fbx_invalid_bind_matrices", f"{invalid_bind_matrices} skin cluster(s) contain non-finite bind matrices."))
    bind_mismatches = int(stats.get("bind_pose_mismatch_count", 0))
    if bind_mismatches:
        issues.append(_fbx_issue(
            "warning",
            "external_fbx_bind_pose_mismatch",
            f"{bind_mismatches} skin cluster(s) do not reconstruct the mesh node transform in the static FBX pose. Check bind pose and Unreal reference-pose import options.",
        ))
    non_normalized = int(stats.get("non_normalized_vertex_count", 0))
    if non_normalized:
        minimum = float(stats.get("minimum_weight_sum", 0.0))
        maximum = float(stats.get("maximum_weight_sum", 0.0))
        issues.append(_fbx_issue(
            "warning",
            "external_fbx_unnormalized_weights",
            f"{non_normalized} of {vertex_count} vertices have weights that do not sum to 1 (range {minimum:.6g}–{maximum:.6g}). Normalize before export.",
        ))
    truncated = int(stats.get("truncated_vertex_count", 0))
    if truncated:
        maximum = int(stats.get("max_influences", 0))
        issues.append(_fbx_issue("warning", "external_fbx_excess_influences", f"{truncated} vertices use more than four influences (maximum {maximum}); preview displays the four strongest."))

    issues.extend(_bone_frame_diagnostics(skeleton, joint_rows))
    if mesh is not None and mesh.skel_joint_weights:
        issues.extend(_skin_distribution_diagnostics(skeleton, mesh))
    bind_pose_count = sum(bool(row[5]) for row in joint_rows)
    if bind_pose_count != len(skeleton):
        issues.append(_fbx_issue("warning", "external_fbx_incomplete_bind_pose", f"FBX bind-pose records cover {bind_pose_count} of {len(skeleton)} bones."))
    if int(stats.get("missing_normals_mesh_count", 0)):
        issues.append(_fbx_issue("warning", "external_fbx_missing_normals", "At least one mesh has no normals."))
    if int(stats.get("missing_tangents_mesh_count", 0)):
        issues.append(_fbx_issue("info", "external_fbx_missing_tangents", "At least one mesh has no tangents; make the Unreal tangent-generation setting explicit."))
    if int(stats.get("animation_stack_count", 0)):
        issues.append(_fbx_issue("info", "external_fbx_animation_present", "FBX contains animation. Diagnostics use the static FBX evaluation pose, not frame 0 as a replacement bind pose."))
    warning_count = int(stats.get("ufbx_warning_count", 0))
    if warning_count:
        issues.append(_fbx_issue("warning", "external_fbx_parser_warnings", f"ufbx reported {warning_count} non-fatal warning(s) while reading the file."))
    return tuple(issues)


def _bone_frame_diagnostics(skeleton: tuple[Joint, ...], joint_rows: list) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    roots = [joint.name for joint in skeleton if joint.parent is None]
    if len(roots) != 1:
        issues.append(_named_fbx_issue("warning", "external_fbx_multiple_roots", "Dynamic Wind rigs normally need one intentional root", roots))
    unique_positions = {(joint.bind_translate.x, joint.bind_translate.y, joint.bind_translate.z) for joint in skeleton}
    if len(skeleton) > 1 and len(unique_positions) == 1:
        issues.append(_fbx_issue("error", "external_fbx_collapsed_pivots", "All bone pivots coincide; regional wind deformation will rotate around one point."))
    generic_names = [joint.name for joint in skeleton if _GENERIC_JOINT_NAME.fullmatch(joint.name)]
    if generic_names:
        issues.append(_named_fbx_issue("info", "external_fbx_generic_joint_names", "Use stable semantic names before JSON becomes a durable contract", generic_names))
    scaled: list[str] = []
    invalid_basis: list[str] = []
    for joint, row in zip(skeleton, joint_rows):
        scale = tuple(float(value) for value in row[4])
        if any(not math.isfinite(value) or abs(value - 1.0) > 1.0e-4 for value in scale):
            scaled.append(joint.name)
        local_matrix = _matrix_from_values(row[3], "joint local transform")
        basis = tuple(Vector3(*local_matrix.rows[index][:3]) for index in range(3))
        lengths = tuple(math.sqrt(_dot_vector(axis, axis)) for axis in basis)
        determinant = _dot_vector(basis[0], _cross_vector(basis[1], basis[2]))
        if (
            any(not math.isfinite(length) or abs(length - 1.0) > 1.0e-4 for length in lengths)
            or any(abs(_dot_vector(basis[left], basis[right])) > 1.0e-4 for left, right in ((0, 1), (0, 2), (1, 2)))
            or determinant <= 0.0
        ):
            invalid_basis.append(joint.name)
    if scaled:
        issues.append(_named_fbx_issue("error", "external_fbx_non_unit_bone_scale", "Bone scale is not unit", scaled))
    if invalid_basis:
        issues.append(_named_fbx_issue("error", "external_fbx_invalid_bone_basis", "Bone world basis contains scale, shear, or reflection", invalid_basis))

    children: dict[str, list[Joint]] = {joint.name: [] for joint in skeleton}
    for joint in skeleton:
        if joint.parent in children:
            children[joint.parent].append(joint)
    zero_links: list[str] = []
    misaligned: list[str] = []
    terminals: list[str] = []
    for joint in skeleton:
        child_joints = children[joint.name]
        if not child_joints:
            terminals.append(joint.name)
            continue
        x_axis = Vector3(*joint.bind_transform.rows[0][:3])
        x_axis = _normalized_vector(x_axis)
        directions: list[Vector3] = []
        for child in child_joints:
            direction = Vector3(
                child.bind_translate.x - joint.bind_translate.x,
                child.bind_translate.y - joint.bind_translate.y,
                child.bind_translate.z - joint.bind_translate.z,
            )
            if _dot_vector(direction, direction) <= 1.0e-16:
                zero_links.append(child.name)
            else:
                directions.append(_normalized_vector(direction))
        if directions and max(_dot_vector(x_axis, direction) for direction in directions) < math.cos(math.radians(5.0)):
            misaligned.append(joint.name)
    if zero_links:
        issues.append(_named_fbx_issue("error", "external_fbx_zero_length_links", "Parent and child pivots coincide", zero_links))
    if misaligned:
        issues.append(_named_fbx_issue("error", "external_fbx_misaligned_x_axis", "Local +X misses every child segment by more than 5°", misaligned))
    if terminals:
        issues.append(_named_fbx_issue("info", "external_fbx_terminal_axes_unverified", "Terminal bone +X cannot be certified from hierarchy alone", terminals))
    return issues


def _skin_distribution_diagnostics(skeleton: tuple[Joint, ...], mesh: MeshData) -> list[ValidationIssue]:
    used = [0] * len(skeleton)
    dominant = [0] * len(skeleton)
    width = mesh.skel_element_size
    for point_index in range(len(mesh.points)):
        start = point_index * width
        point_indices = mesh.skel_joint_indices[start:start + width]
        point_weights = mesh.skel_joint_weights[start:start + width]
        for joint_index, weight in zip(point_indices, point_weights):
            if weight > 0.0 and 0 <= joint_index < len(used):
                used[joint_index] += 1
        if point_weights:
            slot = max(range(len(point_weights)), key=lambda item: point_weights[item])
            joint_index = point_indices[slot]
            if point_weights[slot] > 0.0 and 0 <= joint_index < len(dominant):
                dominant[joint_index] += 1
    issues: list[ValidationIssue] = []
    if len(skeleton) > 1 and max(dominant, default=0) == len(mesh.points):
        joint_index = dominant.index(len(mesh.points))
        issues.append(_fbx_issue("error", "external_fbx_single_joint_dominance", f"Every vertex is dominated by {skeleton[joint_index].name!r}; the mesh will deform as one rigid region."))
    unused = [joint.name for joint, count in zip(skeleton, used) if count == 0]
    if unused:
        issues.append(_named_fbx_issue("warning", "external_fbx_unweighted_bones", "No mesh vertex is weighted to these bones", unused))
    return issues


def _matrix_from_values(values: object, field_name: str) -> Matrix4d:
    if not isinstance(values, tuple) or len(values) != 16:
        raise FbxImportError(f"ufbx returned invalid {field_name}.")
    numbers = tuple(float(value) for value in values)
    return Matrix4d(rows=tuple(tuple(numbers[row * 4:(row + 1) * 4]) for row in range(4)))


def _vectors_from_float_bytes(value: object, field_name: str) -> tuple[Vector3, ...]:
    components = _array_from_bytes(value, "f", field_name)
    if len(components) % 3:
        raise FbxImportError(f"ufbx returned malformed {field_name}.")
    return tuple(Vector3(float(components[index]), float(components[index + 1]), float(components[index + 2])) for index in range(0, len(components), 3))


def _fbx_issue(severity: str, code: str, message: str) -> ValidationIssue:
    return ValidationIssue(severity=severity, code=code, message=message)


def _named_fbx_issue(severity: str, code: str, prefix: str, names: list[str]) -> ValidationIssue:
    shown = ", ".join(names[:12])
    suffix = f" (+{len(names) - 12} more)" if len(names) > 12 else ""
    return _fbx_issue(severity, code, f"{prefix}: {shown}{suffix}.")


def _dot_vector(left: Vector3, right: Vector3) -> float:
    return left.x * right.x + left.y * right.y + left.z * right.z


def _cross_vector(left: Vector3, right: Vector3) -> Vector3:
    return Vector3(left.y * right.z - left.z * right.y, left.z * right.x - left.x * right.z, left.x * right.y - left.y * right.x)


def _normalized_vector(value: Vector3) -> Vector3:
    length = math.sqrt(_dot_vector(value, value))
    return Vector3(value.x / length, value.y / length, value.z / length)


_FBX_AXIS_NAMES = {
    0: "+X",
    1: "-X",
    2: "+Y",
    3: "-Y",
    4: "+Z",
    5: "-Z",
}
_GENERIC_JOINT_NAME = re.compile(r"(?:bone(?:[._ -]?\d+)?|joint[._ -]?\d+)", re.IGNORECASE)


def _geometry_from_native_payload(raw: object, prototype_name: str) -> GeometryBuffer:
    if not isinstance(raw, dict):
        raise FbxImportError("ufbx returned an invalid geometry payload.")
    material_slots = raw.get("material_slots", ())
    if not isinstance(material_slots, tuple):
        raise FbxImportError("ufbx returned invalid material sections.")
    slot_specs: list[FbxMaterialSlotSpec] = []
    sections: list[CompactMeshSection] = []
    for source_id, entry in enumerate(material_slots, start=1):
        if not isinstance(entry, tuple) or len(entry) != 2:
            raise FbxImportError("ufbx returned an invalid material section entry.")
        slot_name, face_indices = entry
        indices = _array_from_bytes(face_indices, "i", "material face indices")
        slot_specs.append(FbxMaterialSlotSpec(source_id=source_id, name=str(slot_name), face_count=len(indices)))
        if indices:
            sections.append(CompactMeshSection(material_id=source_id, face_indices=indices))
    return GeometryBuffer(
        name=prototype_name,
        point_components=_array_from_bytes(raw.get("point_components"), "f", "point components"),
        face_vertex_counts=_array_from_bytes(raw.get("face_vertex_counts"), "i", "face vertex counts"),
        face_vertex_indices=_array_from_bytes(raw.get("face_vertex_indices"), "i", "face vertex indices"),
        uv_components=_array_from_bytes(raw.get("uv_components"), "f", "UV components"),
        vertex_color_components=_array_from_bytes(raw.get("vertex_color_components"), "f", "vertex-color components"),
        vertex_color_warning=raw.get("vertex_color_warning"),
        fbx_material_slots=tuple(slot_specs),
        sections=tuple(sections),
    )


def _array_from_bytes(value: object, typecode: str, field_name: str) -> array:
    if not isinstance(value, bytes):
        raise FbxImportError(f"ufbx returned invalid {field_name}.")
    result = array(typecode)
    try:
        result.frombytes(value)
    except ValueError as exc:
        raise FbxImportError(f"ufbx returned malformed {field_name}.") from exc
    return result


def _load_ufbx_native():
    try:
        from . import _ufbx
    except ImportError as exc:
        raise FbxBackendUnavailableError(
            "The bundled ufbx C backend is unavailable. Reinstall SpeedAssembly with its native build dependencies."
        ) from exc
    return _ufbx


def _emit_fbx_stage(telemetry_callback, message: str, started_at: float) -> None:
    emit_telemetry(
        telemetry_callback,
        ConversionPhase.FBX_IMPORT,
        message=message,
        started_at=started_at,
    )
