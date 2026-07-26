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


class FbxVertexColorReadError(FbxImportError):
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

                transform_coefficients = _fbx_point_transform_coefficients(node.EvaluateGlobalTransform())
                control_points = mesh.GetControlPoints()
                local_point_count = mesh.GetControlPointsCount()
                for point_index in range(local_point_count):
                    control_point = _transform_control_point(transform_coefficients, control_points[point_index])
                    point_components.extend((float(control_point[0]), float(control_point[1]), float(control_point[2])))

                mesh_color_components = [0.0] * (local_point_count * 4) if read_vertex_colors else []
                has_colors = False
                vertex_colors_disabled_for_mesh = (not read_vertex_colors) or not usable_vertex_colors
                assigned_color_flags = bytearray(local_point_count) if read_vertex_colors else bytearray()
                referenced_point_flags = bytearray(local_point_count) if read_vertex_colors else bytearray()
                uv_element = mesh.GetElementUV(0) if mesh.GetElementUVCount() > 0 else None
                default_uv_set = uv_element.GetName() if uv_element is not None else None
                for polygon_index in range(mesh.GetPolygonCount()):
                    if polygon_index % 10_000 == 0:
                        throw_if_cancelled(cancel_event)
                    polygon_size = mesh.GetPolygonSize(polygon_index)
                    if polygon_size != 3:
                        raise FbxImportError(
                            f"FBX triangulation produced a non-triangle polygon in {Path(fbx_path).name}."
                        )
                    face_vertex_counts.append(3)
                    if read_material_slots:
                        _append_face_to_material_slot_sections(
                            node,
                            mesh,
                            polygon_index,
                            face_index=len(face_vertex_counts) - 1,
                            material_slot_face_indices=material_slot_face_indices,
                            material_slot_order=material_slot_order,
                        )
                    for vertex_order in range(polygon_size):
                        control_point_index = int(mesh.GetPolygonVertex(polygon_index, vertex_order))
                        if control_point_index < 0 or control_point_index >= local_point_count:
                            raise FbxImportError(
                                f"FBX polygon index is out of bounds for control points in {Path(fbx_path).name}."
                            )
                        if read_vertex_colors:
                            referenced_point_flags[control_point_index] = 1
                        face_vertex_indices.append(point_offset + control_point_index)
                        if default_uv_set is not None:
                            uv = fbx.FbxVector2()
                            mapped = mesh.GetPolygonVertexUV(polygon_index, vertex_order, default_uv_set, uv)
                            if mapped:
                                uv_components.extend((float(uv[0]), float(uv[1])))

                        if vertex_colors_disabled_for_mesh:
                            continue
                        try:
                            color = _read_vertex_color(mesh, polygon_index, vertex_order)
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
                for polygon_index in range(mesh.GetPolygonCount()):
                    if polygon_index % 10_000 == 0:
                        throw_if_cancelled(cancel_event)
                    _append_face_to_material_slot_sections(
                        node,
                        mesh,
                        polygon_index,
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
        polygon_vertex_index = mesh.GetPolygonVertexIndex(polygon_index) + vertex_order
        direct_array = color_element.GetDirectArray()
        if direct_array.GetCount() <= 0:
            return None
        mapping_mode = _enum_name(color_element.GetMappingMode())
        reference_mode = _enum_name(color_element.GetReferenceMode())
        if mapping_mode not in {"eByControlPoint", "eByPolygonVertex", "eAllSame"}:
            return None

        if mapping_mode == "eAllSame":
            direct_index = 0
        elif mapping_mode == "eByPolygonVertex":
            direct_index = polygon_vertex_index
        else:
            direct_index = mesh.GetPolygonVertex(polygon_index, vertex_order)

        if reference_mode in {"eIndexToDirect", "eIndex"}:
            index_array = color_element.GetIndexArray()
            if direct_index >= index_array.GetCount():
                return None
            direct_index = index_array.GetAt(direct_index)

        if direct_index >= direct_array.GetCount():
            return None
        color = direct_array.GetAt(direct_index)
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


def _append_face_to_material_slot_sections(
    node,
    mesh,
    polygon_index: int,
    *,
    face_index: int,
    material_slot_face_indices: dict[str, array],
    material_slot_order: list[str],
) -> None:
    slot_name = _read_polygon_material_slot_name(node, mesh, polygon_index)
    face_indices = material_slot_face_indices.get(slot_name)
    if face_indices is None:
        face_indices = array("i")
        material_slot_face_indices[slot_name] = face_indices
        material_slot_order.append(slot_name)
    face_indices.append(face_index)


def _read_polygon_material_slot_name(node, mesh, polygon_index: int) -> str:
    local_material_index = _resolve_polygon_material_index(node, mesh, polygon_index)
    if local_material_index is None or local_material_index < 0:
        return "Unassigned"
    material_count = int(node.GetMaterialCount())
    if 0 <= local_material_index < material_count:
        material = node.GetMaterial(local_material_index)
        if material is not None:
            material_name = str(material.GetName()).strip()
            if material_name:
                return material_name
    return f"MaterialSlot_{local_material_index}"


def _resolve_polygon_material_index(node, mesh, polygon_index: int) -> int | None:
    try:
        if mesh.GetElementMaterialCount() > 0:
            material_element = mesh.GetElementMaterial(0)
            if material_element is not None:
                mapping_mode = _enum_name(material_element.GetMappingMode())
                index_array = material_element.GetIndexArray()
                if mapping_mode == "eAllSame" and index_array.GetCount() > 0:
                    return int(index_array.GetAt(0))
                if mapping_mode in {"eByPolygon", "eByPolygonVertex"} and polygon_index < index_array.GetCount():
                    return int(index_array.GetAt(polygon_index))
        if int(node.GetMaterialCount()) == 1:
            return 0
    except Exception:
        return None
    return None


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
