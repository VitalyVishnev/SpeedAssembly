from __future__ import annotations

import json
import os
import time
from array import array
from dataclasses import dataclass
from pathlib import Path

from .job_control import ConversionCancelledError, apply_process_profile, emit_telemetry, throw_if_cancelled
from .models import CompactMeshSection, ConversionPhase, CpuProfile, FbxMaterialSlotSpec, GeometryBuffer, Joint, Matrix4d, Vector3


_MIN_NUMPY_CONTROL_POINT_COUNT = 100_000
_NUMPY_CONTROL_POINT_CHUNK_SIZE = 262_144
_MIN_NUMPY_POLYGON_VERTEX_COUNT = 300_000
_NUMPY_POLYGON_VERTEX_CHUNK_SIZE = 262_144
_MAX_NUMPY_UV_DIRECT_COUNT = 5_000_000


class FbxImportError(ValueError):
    pass


class FbxBackendUnavailableError(FbxImportError):
    pass


class FbxVertexColorReadError(FbxImportError):
    pass


@dataclass(frozen=True, slots=True)
class _LayerElementReader:
    mapping_mode: str
    reference_mode: str
    direct_array: object
    direct_count: int
    index_array: object | None
    index_count: int

    def read(self, *, control_point_index: int, polygon_vertex_index: int):
        if self.mapping_mode == "eByPolygonVertex":
            element_index = polygon_vertex_index
        elif self.mapping_mode == "eByControlPoint":
            element_index = control_point_index
        elif self.mapping_mode == "eAllSame":
            element_index = 0
        else:
            return None
        if element_index < 0:
            return None
        direct_index = element_index
        if self.reference_mode in {"eIndexToDirect", "eIndex"}:
            if self.index_array is None or element_index >= self.index_count:
                return None
            direct_index = int(self.index_array.GetAt(element_index))
        if direct_index < 0 or direct_index >= self.direct_count:
            return None
        return self.direct_array.GetAt(direct_index)


@dataclass(frozen=True, slots=True)
class _MaterialSlotReader:
    index_array: object | None
    index_count: int
    mapping_mode: str | None
    slot_names: tuple[str, ...]

    def slot_name(self, polygon_index: int) -> str:
        local_index: int | None = None
        if self.index_array is not None:
            element_index = 0 if self.mapping_mode == "eAllSame" else polygon_index
            if self.mapping_mode in {"eAllSame", "eByPolygon", "eByPolygonVertex"} and element_index < self.index_count:
                try:
                    local_index = int(self.index_array.GetAt(element_index))
                except Exception:
                    local_index = None
        if local_index is None and len(self.slot_names) == 1:
            local_index = 0
        if local_index is None or local_index < 0:
            return "Unassigned"
        if local_index < len(self.slot_names) and self.slot_names[local_index]:
            return self.slot_names[local_index]
        return f"MaterialSlot_{local_index}"


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
class AutodeskFbxBackend(FbxBackend):
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
        try:
            import fbx  # type: ignore
        except ImportError as exc:
            raise FbxBackendUnavailableError(
                "Autodesk FBX SDK Python bindings are required for FBX import. "
                "Install the official SDK bindings so the 'fbx' module is available."
            ) from exc

        sdk_manager, scene = _initialize_sdk_objects(fbx)
        try:
            if not _load_scene(fbx, sdk_manager, scene, str(fbx_path)):
                raise FbxImportError(f"Failed to load FBX scene: {fbx_path}")
            _emit_fbx_stage(telemetry_callback, f"Loaded FBX scene {Path(fbx_path).name}.", started_at)

            anim_stack_criteria = fbx.FbxCriteria.ObjectType(fbx.FbxAnimStack.ClassId)
            if scene.GetSrcObjectCount(anim_stack_criteria) > 0:
                raise FbxImportError("Animated FBX files are not supported for Assembly Part import.")

            geometry_converter = fbx.FbxGeometryConverter(sdk_manager)
            geometry_converter.Triangulate(scene, True)
            _emit_fbx_stage(telemetry_callback, f"Triangulated FBX scene {Path(fbx_path).name}.", started_at)

            mesh_nodes: list = []
            _collect_mesh_nodes(scene.GetRootNode(), mesh_nodes, fbx)
            if not mesh_nodes:
                raise FbxImportError(f"FBX file does not contain any polygon mesh nodes: {fbx_path}")
            _emit_fbx_stage(telemetry_callback, f"Collected {len(mesh_nodes)} FBX mesh node(s).", started_at)

            point_components = array("f")
            face_vertex_counts = array("i")
            face_vertex_indices = array("i")
            uv_components = array("f")
            vertex_color_components = array("f")
            vertex_color_warning: str | None = None
            material_slot_face_indices: dict[str, array] = {}
            material_slot_order: list[str] = []
            point_offset = 0
            usable_vertex_colors = True

            for node in mesh_nodes:
                throw_if_cancelled(cancel_event)
                mesh = node.GetMesh()
                if mesh is None:
                    continue
                if mesh.GetDeformerCount() > 0:
                    raise FbxImportError("Skinned FBX files are not supported for Assembly Part import.")

                control_points = mesh.GetControlPoints()
                local_point_count = mesh.GetControlPointsCount()
                _append_transformed_control_points(
                    point_components,
                    control_points,
                    _fbx_point_transform_coefficients(node.EvaluateGlobalTransform()),
                )
                del control_points

                mesh_color_components = [0.0] * (local_point_count * 4) if read_vertex_colors else []
                has_colors = False
                vertex_colors_disabled_for_mesh = (not read_vertex_colors) or not usable_vertex_colors
                assigned_color_flags = bytearray(local_point_count) if read_vertex_colors else bytearray()
                referenced_point_flags = bytearray(local_point_count) if read_vertex_colors else bytearray()
                uv_element = mesh.GetElementUV(0) if mesh.GetElementUVCount() > 0 else None
                default_uv_set = uv_element.GetName() if uv_element is not None else None
                uv_reader = _prepare_layer_element_reader(
                    uv_element,
                    supported_mapping_modes={"eByPolygonVertex", "eAllSame"},
                ) if uv_element is not None else None
                bulk_uvs = (
                    uv_reader is not None
                    and _append_polygon_vertex_uvs(
                        uv_components,
                        uv_reader,
                        polygon_vertex_count=int(mesh.GetPolygonVertexCount()),
                        cancel_event=cancel_event,
                    )
                )
                color_reader = None
                if read_vertex_colors:
                    try:
                        if mesh.GetElementVertexColorCount() > 0:
                            color_reader = _prepare_layer_element_reader(
                                mesh.GetElementVertexColor(0),
                                supported_mapping_modes={"eByControlPoint", "eByPolygonVertex", "eAllSame"},
                            )
                    except Exception as exc:
                        detailed_reason = (
                            "Autodesk FBX SDK vertex-color access failed for "
                            f"{Path(fbx_path).name} while preparing the color layer: {exc}"
                        )
                        if strict_vertex_colors:
                            raise FbxImportError(detailed_reason) from exc
                        vertex_colors_disabled_for_mesh = True
                        usable_vertex_colors = False
                        vertex_color_components = array("f")
                        if vertex_color_warning is None:
                            vertex_color_warning = detailed_reason
                material_reader = _prepare_material_slot_reader(node, mesh) if read_material_slots else None
                polygon_vertex_index = 0
                polygon_count = int(mesh.GetPolygonCount())
                face_index_offset = len(face_vertex_counts)
                for face_start in range(0, polygon_count, _NUMPY_POLYGON_VERTEX_CHUNK_SIZE):
                    throw_if_cancelled(cancel_event)
                    face_count = min(_NUMPY_POLYGON_VERTEX_CHUNK_SIZE, polygon_count - face_start)
                    face_vertex_counts.extend(array("i", (3,)) * face_count)
                fast_topology = vertex_colors_disabled_for_mesh and (default_uv_set is None or bulk_uvs)
                for polygon_index in range(polygon_count):
                    if polygon_index % 10_000 == 0:
                        throw_if_cancelled(cancel_event)
                    polygon_size = mesh.GetPolygonSize(polygon_index)
                    if polygon_size != 3:
                        raise FbxImportError(
                            f"FBX triangulation produced a non-triangle polygon in {Path(fbx_path).name}."
                        )
                    if material_reader is not None:
                        _append_material_slot_face(
                            material_reader.slot_name(polygon_index),
                            face_index=face_index_offset + polygon_index,
                            material_slot_face_indices=material_slot_face_indices,
                            material_slot_order=material_slot_order,
                        )
                    if fast_topology:
                        index_0 = int(mesh.GetPolygonVertex(polygon_index, 0))
                        index_1 = int(mesh.GetPolygonVertex(polygon_index, 1))
                        index_2 = int(mesh.GetPolygonVertex(polygon_index, 2))
                        if (
                            index_0 < 0 or index_0 >= local_point_count
                            or index_1 < 0 or index_1 >= local_point_count
                            or index_2 < 0 or index_2 >= local_point_count
                        ):
                            raise FbxImportError(
                                f"FBX polygon index is out of bounds for control points in {Path(fbx_path).name}."
                            )
                        face_vertex_indices.extend((
                            point_offset + index_0,
                            point_offset + index_1,
                            point_offset + index_2,
                        ))
                        polygon_vertex_index += 3
                        continue
                    for vertex_order in range(polygon_size):
                        control_point_index = int(mesh.GetPolygonVertex(polygon_index, vertex_order))
                        current_polygon_vertex_index = polygon_vertex_index
                        polygon_vertex_index += 1
                        if control_point_index < 0 or control_point_index >= local_point_count:
                            raise FbxImportError(
                                f"FBX polygon index is out of bounds for control points in {Path(fbx_path).name}."
                            )
                        if read_vertex_colors:
                            referenced_point_flags[control_point_index] = 1
                        face_vertex_indices.append(point_offset + control_point_index)
                        if default_uv_set is not None and not bulk_uvs:
                            uv = fbx.FbxVector2()
                            if mesh.GetPolygonVertexUV(polygon_index, vertex_order, default_uv_set, uv):
                                uv_components.extend((float(uv[0]), float(uv[1])))

                        if vertex_colors_disabled_for_mesh:
                            continue
                        try:
                            try:
                                raw_color = color_reader.read(
                                    control_point_index=control_point_index,
                                    polygon_vertex_index=current_polygon_vertex_index,
                                ) if color_reader is not None else None
                            except Exception as exc:
                                raise FbxVertexColorReadError(
                                    "Autodesk FBX SDK failed while reading vertex colors. "
                                    "Falling back to single-material FBX import is recommended for this payload."
                                ) from exc
                            color = (
                                float(raw_color.mRed),
                                float(raw_color.mGreen),
                                float(raw_color.mBlue),
                                float(raw_color.mAlpha),
                            ) if raw_color is not None else None
                        except FbxVertexColorReadError as exc:
                            detailed_reason = (
                                "Autodesk FBX SDK vertex-color access failed for "
                                f"{Path(fbx_path).name} at polygon {polygon_index}, vertex {vertex_order}: {exc}"
                            )
                            if strict_vertex_colors:
                                raise FbxImportError(detailed_reason) from exc
                            vertex_colors_disabled_for_mesh = True
                            usable_vertex_colors = False
                            vertex_color_components = array("f")
                            if vertex_color_warning is None:
                                vertex_color_warning = detailed_reason
                            continue
                        if color is None:
                            continue
                        has_colors = True
                        color_offset = control_point_index * 4
                        if assigned_color_flags[control_point_index]:
                            existing_color = tuple(mesh_color_components[color_offset:color_offset + 4])
                            if existing_color != color:
                                raise FbxImportError(
                                    "Per-polygon-vertex color splits on shared control points are not supported yet. "
                                    f"Re-export {Path(fbx_path).name} with non-conflicting vertex colors."
                                )
                        mesh_color_components[color_offset:color_offset + 4] = color
                        assigned_color_flags[control_point_index] = 1

                if vertex_colors_disabled_for_mesh:
                    point_offset += local_point_count
                    continue

                if has_colors:
                    missing_vertex_colors = [
                        point_index
                        for point_index in range(local_point_count)
                        if referenced_point_flags[point_index] and not assigned_color_flags[point_index]
                    ]
                    if missing_vertex_colors:
                        usable_vertex_colors = False
                        vertex_color_components = array("f")
                    elif usable_vertex_colors:
                        vertex_color_components.extend(mesh_color_components)
                elif any(referenced_point_flags) and usable_vertex_colors:
                    usable_vertex_colors = False
                    vertex_color_components = array("f")
                point_offset += local_point_count
                _emit_fbx_stage(
                    telemetry_callback,
                    f"Imported FBX mesh node {str(node.GetName()) or '<unnamed>'}.",
                    started_at,
                )

            if not point_components or not face_vertex_counts or not face_vertex_indices:
                raise FbxImportError(f"FBX file does not contain readable mesh topology: {fbx_path}")

            return GeometryBuffer(
                name=prototype_name,
                point_components=point_components,
                face_vertex_counts=face_vertex_counts,
                face_vertex_indices=face_vertex_indices,
                uv_components=uv_components,
                vertex_color_components=vertex_color_components,
                vertex_color_warning=vertex_color_warning,
                fbx_material_slots=_build_fbx_material_slot_specs(material_slot_order, material_slot_face_indices),
                sections=_build_fbx_material_slot_sections(material_slot_order, material_slot_face_indices),
            )
        finally:
            destroy = getattr(sdk_manager, "Destroy", None)
            if callable(destroy):
                destroy()

    def inspect_material_slots(
        self,
        fbx_path: str,
        *,
        cpu_profile: CpuProfile,
        cancel_event=None,
    ) -> tuple[FbxMaterialSlotSpec, ...]:
        apply_process_profile(cpu_profile)
        throw_if_cancelled(cancel_event)
        try:
            import fbx  # type: ignore
        except ImportError as exc:
            raise FbxBackendUnavailableError(
                "Autodesk FBX SDK Python bindings are required for FBX import. "
                "Install the official SDK bindings so the 'fbx' module is available."
            ) from exc

        sdk_manager, scene = _initialize_sdk_objects(fbx)
        try:
            if not _load_scene(fbx, sdk_manager, scene, str(fbx_path)):
                raise FbxImportError(f"Failed to load FBX scene: {fbx_path}")
            geometry_converter = fbx.FbxGeometryConverter(sdk_manager)
            geometry_converter.Triangulate(scene, True)

            mesh_nodes: list = []
            _collect_mesh_nodes(scene.GetRootNode(), mesh_nodes, fbx)
            if not mesh_nodes:
                raise FbxImportError(f"FBX file does not contain any polygon mesh nodes: {fbx_path}")

            material_slot_face_indices: dict[str, array] = {}
            material_slot_order: list[str] = []
            face_index = 0
            for node in mesh_nodes:
                throw_if_cancelled(cancel_event)
                mesh = node.GetMesh()
                if mesh is None:
                    continue
                material_reader = _prepare_material_slot_reader(node, mesh)
                for polygon_index in range(mesh.GetPolygonCount()):
                    if polygon_index % 10_000 == 0:
                        throw_if_cancelled(cancel_event)
                    _append_material_slot_face(
                        material_reader.slot_name(polygon_index),
                        face_index=face_index,
                        material_slot_face_indices=material_slot_face_indices,
                        material_slot_order=material_slot_order,
                    )
                    face_index += 1
            return _build_fbx_material_slot_specs(material_slot_order, material_slot_face_indices)
        finally:
            destroy = getattr(sdk_manager, "Destroy", None)
            if callable(destroy):
                destroy()


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
    return AutodeskFbxBackend()


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
    backend = get_fbx_backend(fbx_path)
    return backend.load_mesh_payload(
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
    backend = get_fbx_backend(fbx_path)
    return backend.inspect_material_slots(
        fbx_path,
        cpu_profile=cpu_profile,
        cancel_event=cancel_event,
    )


def load_fbx_skeleton(fbx_path: str) -> tuple[Joint, ...]:
    try:
        import fbx  # type: ignore
    except ImportError as exc:
        raise FbxBackendUnavailableError(
            "Autodesk FBX SDK Python bindings are required for FBX skeleton import. "
            "Install the official SDK bindings so the 'fbx' module is available."
        ) from exc

    sdk_manager, scene = _initialize_sdk_objects(fbx)
    try:
        if not _load_scene(fbx, sdk_manager, scene, str(fbx_path)):
            raise FbxImportError(f"Failed to load FBX scene: {fbx_path}")
        joints: list[Joint] = []
        seen_names: set[str] = set()
        _collect_skeleton_joints(scene.GetRootNode(), fbx, joints, seen_names, parent_token=None)
        if not joints:
            raise FbxImportError(f"FBX file does not contain a skeleton: {fbx_path}")
        return tuple(joints)
    finally:
        destroy = getattr(sdk_manager, "Destroy", None)
        if callable(destroy):
            destroy()


def _emit_fbx_stage(telemetry_callback, message: str, started_at: float) -> None:
    emit_telemetry(
        telemetry_callback,
        ConversionPhase.FBX_IMPORT,
        message=message,
        started_at=started_at,
    )


def _collect_mesh_nodes(node, mesh_nodes: list, fbx_module) -> None:
    if node is None:
        return
    mesh = node.GetMesh()
    if mesh is not None:
        mesh_nodes.append(node)
    for child_index in range(node.GetChildCount()):
        _collect_mesh_nodes(node.GetChild(child_index), mesh_nodes, fbx_module)


def _collect_skeleton_joints(node, fbx_module, joints: list[Joint], seen_names: set[str], *, parent_token: str | None) -> None:
    if node is None:
        return
    current_parent = parent_token
    attribute = node.GetNodeAttribute()
    if attribute is not None and isinstance(attribute, fbx_module.FbxSkeleton):
        name = str(node.GetName()).strip()
        if not name:
            name = f"joint_{len(joints):03d}"
        if name in seen_names:
            raise FbxImportError(f"fbx_skeleton_duplicate_joint_name: {name}")
        seen_names.add(name)
        translation = _fbx_node_global_translation(node)
        joints.append(
            Joint(
                name=name,
                source_id=len(joints),
                parent=parent_token,
                bind_transform=Matrix4d.from_translation(translation),
                rest_transform=Matrix4d.from_translation(translation),
            )
        )
        current_parent = name
    for child_index in range(node.GetChildCount()):
        _collect_skeleton_joints(node.GetChild(child_index), fbx_module, joints, seen_names, parent_token=current_parent)


def _fbx_node_global_translation(node) -> Vector3:
    matrix = node.EvaluateGlobalTransform()
    try:
        translate = matrix.GetT()
        return Vector3(float(translate[0]), float(translate[1]), float(translate[2]))
    except Exception as exc:
        raise FbxImportError(f"Failed to read global transform for FBX skeleton node {node.GetName()}.") from exc


def _read_vertex_color(mesh, polygon_index: int, vertex_order: int) -> tuple[float, float, float, float] | None:
    try:
        if mesh.GetElementVertexColorCount() <= 0:
            return None
        color_element = mesh.GetElementVertexColor(0)
        if color_element is None:
            return None
        reader = _prepare_layer_element_reader(
            color_element,
            supported_mapping_modes={"eByControlPoint", "eByPolygonVertex", "eAllSame"},
        )
        if reader is None:
            return None
        polygon_vertex_index = mesh.GetPolygonVertexIndex(polygon_index) + vertex_order
        color = reader.read(
            control_point_index=int(mesh.GetPolygonVertex(polygon_index, vertex_order)),
            polygon_vertex_index=polygon_vertex_index,
        )
        if color is None:
            return None
        return (float(color.mRed), float(color.mGreen), float(color.mBlue), float(color.mAlpha))
    except Exception as exc:
        raise FbxVertexColorReadError(
            "Autodesk FBX SDK failed while reading vertex colors. "
            "Falling back to single-material FBX import is recommended for this payload."
        ) from exc


def _enum_name(value) -> str:
    name = getattr(value, "name", None)
    if isinstance(name, str) and name:
        return name
    text = str(value)
    if "." in text:
        return text.rsplit(".", 1)[-1]
    return text


def _prepare_layer_element_reader(
    element,
    *,
    supported_mapping_modes: set[str],
) -> _LayerElementReader | None:
    mapping_mode = _enum_name(element.GetMappingMode())
    if mapping_mode not in supported_mapping_modes:
        return None
    direct_array = element.GetDirectArray()
    direct_count = int(direct_array.GetCount())
    if direct_count <= 0:
        return None
    reference_mode = _enum_name(element.GetReferenceMode())
    index_array = None
    index_count = 0
    if reference_mode in {"eIndexToDirect", "eIndex"}:
        index_array = element.GetIndexArray()
        index_count = int(index_array.GetCount())
    return _LayerElementReader(
        mapping_mode=mapping_mode,
        reference_mode=reference_mode,
        direct_array=direct_array,
        direct_count=direct_count,
        index_array=index_array,
        index_count=index_count,
    )


def _append_polygon_vertex_uvs(
    target: array,
    reader: _LayerElementReader,
    *,
    polygon_vertex_count: int,
    cancel_event=None,
) -> bool:
    if polygon_vertex_count < _MIN_NUMPY_POLYGON_VERTEX_COUNT:
        return False

    import numpy as np

    initial_length = len(target)
    try:
        if reader.mapping_mode == "eAllSame":
            direct_index = 0
            if reader.reference_mode in {"eIndexToDirect", "eIndex"}:
                if reader.index_array is None or reader.index_count < 1:
                    return False
                direct_index = int(reader.index_array.GetAt(0))
            if direct_index < 0 or direct_index >= reader.direct_count:
                return False
            value = reader.direct_array.GetAt(direct_index)
            repeated_value = np.asarray((float(value[0]), float(value[1])), dtype=np.float32).reshape((1, 2))
            for start in range(0, polygon_vertex_count, _NUMPY_POLYGON_VERTEX_CHUNK_SIZE):
                throw_if_cancelled(cancel_event)
                chunk_count = min(_NUMPY_POLYGON_VERTEX_CHUNK_SIZE, polygon_vertex_count - start)
                target.frombytes(np.repeat(repeated_value, chunk_count, axis=0).tobytes())
            return True
        if reader.mapping_mode != "eByPolygonVertex":
            return False
        if reader.reference_mode not in {"eIndexToDirect", "eIndex"}:
            if reader.direct_count < polygon_vertex_count:
                return False
            for start in range(0, polygon_vertex_count, _NUMPY_POLYGON_VERTEX_CHUNK_SIZE):
                throw_if_cancelled(cancel_event)
                end = min(polygon_vertex_count, start + _NUMPY_POLYGON_VERTEX_CHUNK_SIZE)
                direct_chunk = np.fromiter(
                    (
                        float(component)
                        for index in range(start, end)
                        for value in (reader.direct_array.GetAt(index),)
                        for component in (value[0], value[1])
                    ),
                    dtype=np.float32,
                    count=(end - start) * 2,
                )
                target.frombytes(direct_chunk.tobytes())
            return True
        if (
            reader.index_array is None
            or reader.index_count < polygon_vertex_count
            or reader.direct_count > _MAX_NUMPY_UV_DIRECT_COUNT
        ):
            return False

        direct_values = np.fromiter(
            (
                float(component)
                for index in range(reader.direct_count)
                for value in (reader.direct_array.GetAt(index),)
                for component in (value[0], value[1])
            ),
            dtype=np.float32,
            count=reader.direct_count * 2,
        ).reshape((-1, 2))

        for start in range(0, polygon_vertex_count, _NUMPY_POLYGON_VERTEX_CHUNK_SIZE):
            throw_if_cancelled(cancel_event)
            end = min(polygon_vertex_count, start + _NUMPY_POLYGON_VERTEX_CHUNK_SIZE)
            indices = np.fromiter(
                (int(reader.index_array.GetAt(index)) for index in range(start, end)),
                dtype=np.int64,
                count=end - start,
            )
            if np.any(indices < 0) or np.any(indices >= reader.direct_count):
                del target[initial_length:]
                return False
            target.frombytes(direct_values[indices].tobytes())
        return True
    except ConversionCancelledError:
        del target[initial_length:]
        raise
    except Exception:
        del target[initial_length:]
        return False


def _prepare_material_slot_reader(node, mesh) -> _MaterialSlotReader:
    slot_names = tuple(
        str(material.GetName()).strip() if material is not None else ""
        for material in (node.GetMaterial(index) for index in range(int(node.GetMaterialCount())))
    )
    if mesh.GetElementMaterialCount() <= 0:
        return _MaterialSlotReader(None, 0, None, slot_names)
    element = mesh.GetElementMaterial(0)
    if element is None:
        return _MaterialSlotReader(None, 0, None, slot_names)
    index_array = element.GetIndexArray()
    return _MaterialSlotReader(
        index_array=index_array,
        index_count=int(index_array.GetCount()),
        mapping_mode=_enum_name(element.GetMappingMode()),
        slot_names=slot_names,
    )


def _append_material_slot_face(
    slot_name: str,
    *,
    face_index: int,
    material_slot_face_indices: dict[str, array],
    material_slot_order: list[str],
) -> None:
    face_indices = material_slot_face_indices.get(slot_name)
    if face_indices is None:
        face_indices = array("i")
        material_slot_face_indices[slot_name] = face_indices
        material_slot_order.append(slot_name)
    face_indices.append(face_index)


def _build_fbx_material_slot_specs(
    material_slot_order: list[str],
    material_slot_face_indices: dict[str, array],
) -> tuple[FbxMaterialSlotSpec, ...]:
    return tuple(
        FbxMaterialSlotSpec(
            source_id=index,
            name=slot_name,
            face_count=len(material_slot_face_indices.get(slot_name, ())),
        )
        for index, slot_name in enumerate(material_slot_order, start=1)
    )


def _build_fbx_material_slot_sections(
    material_slot_order: list[str],
    material_slot_face_indices: dict[str, array],
) -> tuple[CompactMeshSection, ...]:
    return tuple(
        CompactMeshSection(
            material_id=index,
            face_indices=material_slot_face_indices.get(slot_name, array("i")),
        )
        for index, slot_name in enumerate(material_slot_order, start=1)
        if material_slot_face_indices.get(slot_name)
    )


def _initialize_sdk_objects(fbx_module):
    sdk_manager = fbx_module.FbxManager.Create()
    if sdk_manager is None:
        raise FbxImportError("Failed to create Autodesk FBX SDK manager.")
    ios = fbx_module.FbxIOSettings.Create(sdk_manager, fbx_module.IOSROOT)
    sdk_manager.SetIOSettings(ios)
    scene = fbx_module.FbxScene.Create(sdk_manager, "")
    return sdk_manager, scene


def _load_scene(fbx_module, sdk_manager, scene, fbx_path: str) -> bool:
    importer = fbx_module.FbxImporter.Create(sdk_manager, "")
    try:
        if not importer.Initialize(fbx_path, -1, sdk_manager.GetIOSettings()):
            return False

        if importer.IsFBX():
            io_settings = sdk_manager.GetIOSettings()
            io_settings.SetBoolProp(fbx_module.EXP_FBX_MATERIAL, True)
            io_settings.SetBoolProp(fbx_module.EXP_FBX_TEXTURE, True)
            io_settings.SetBoolProp(fbx_module.EXP_FBX_EMBEDDED, True)
            io_settings.SetBoolProp(fbx_module.EXP_FBX_SHAPE, True)
            io_settings.SetBoolProp(fbx_module.EXP_FBX_GOBO, True)
            io_settings.SetBoolProp(fbx_module.EXP_FBX_ANIMATION, True)
            io_settings.SetBoolProp(fbx_module.EXP_FBX_GLOBAL_SETTINGS, True)

        return bool(importer.Import(scene))
    finally:
        importer.Destroy()


def _fbx_point_transform_coefficients(transform) -> tuple[float, ...]:
    try:
        return tuple(
            float(transform.Get(row, column))
            for column in range(3)
            for row in range(4)
        )
    except Exception as exc:
        raise FbxImportError("Autodesk FBX SDK failed while reading a node transform matrix.") from exc


def _append_transformed_control_points(
    target: array,
    control_points,
    transform_coefficients: tuple[float, ...],
) -> None:
    if len(control_points) < _MIN_NUMPY_CONTROL_POINT_COUNT:
        for control_point in control_points:
            target.extend(_transform_control_point(transform_coefficients, control_point))
        return

    import numpy as np

    (
        m00,
        m10,
        m20,
        m30,
        m01,
        m11,
        m21,
        m31,
        m02,
        m12,
        m22,
        m32,
    ) = transform_coefficients
    for start in range(0, len(control_points), _NUMPY_CONTROL_POINT_CHUNK_SIZE):
        chunk = control_points[start:start + _NUMPY_CONTROL_POINT_CHUNK_SIZE]
        try:
            values = np.fromiter(
                (
                    float(component)
                    for point in chunk
                    for component in (point[0], point[1], point[2], point[3])
                ),
                dtype=np.float64,
                count=len(chunk) * 4,
            ).reshape((-1, 4))
        except Exception as exc:
            raise FbxImportError("Autodesk FBX SDK failed while reading mesh control points.") from exc

        x = values[:, 0]
        y = values[:, 1]
        z = values[:, 2]
        w = values[:, 3]
        transformed = np.empty((len(chunk), 3), dtype=np.float32)
        transformed[:, 0] = x * m00 + y * m10 + z * m20 + w * m30
        transformed[:, 1] = x * m01 + y * m11 + z * m21 + w * m31
        transformed[:, 2] = x * m02 + y * m12 + z * m22 + w * m32
        target.frombytes(transformed.tobytes())


def _transform_control_point(transform_coefficients: tuple[float, ...], control_point):
    x = float(control_point[0])
    y = float(control_point[1])
    z = float(control_point[2])
    try:
        w = float(control_point[3])
    except (IndexError, TypeError):
        w = 1.0
    (
        m00,
        m10,
        m20,
        m30,
        m01,
        m11,
        m21,
        m31,
        m02,
        m12,
        m22,
        m32,
    ) = transform_coefficients
    return (
        x * m00 + y * m10 + z * m20 + w * m30,
        x * m01 + y * m11 + z * m21 + w * m31,
        x * m02 + y * m12 + z * m22 + w * m32,
    )
