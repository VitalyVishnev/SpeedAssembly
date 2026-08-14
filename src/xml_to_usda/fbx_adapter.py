"""FBX adapter backed by the vendored official ufbx C library.

The public contract is deliberately small: rigid prototype geometry and a
skeleton-only preview.  The native module runs only in the already isolated
FBX helper process for prototype imports; Wind Preview has its own worker.
"""

from __future__ import annotations

import json
import os
import time
from array import array
from dataclasses import dataclass
from pathlib import Path

from .job_control import apply_process_profile, emit_telemetry, throw_if_cancelled
from .models import CompactMeshSection, ConversionPhase, CpuProfile, FbxMaterialSlotSpec, GeometryBuffer, Joint, Matrix4d, Vector3


class FbxImportError(ValueError):
    pass


class FbxBackendUnavailableError(FbxImportError):
    pass


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
