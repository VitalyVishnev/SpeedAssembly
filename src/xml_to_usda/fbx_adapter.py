from __future__ import annotations

import json
from array import array
from dataclasses import dataclass
from pathlib import Path

from .job_control import apply_process_profile, throw_if_cancelled
from .models import CpuProfile, GeometryBuffer


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
        telemetry_callback=None,
        cancel_event=None,
    ) -> GeometryBuffer:
        raise NotImplementedError


@dataclass(frozen=True)
class AutodeskFbxBackend(FbxBackend):
    def load_mesh_payload(
        self,
        fbx_path: str,
        prototype_name: str,
        *,
        cpu_profile: CpuProfile,
        telemetry_callback=None,
        cancel_event=None,
    ) -> GeometryBuffer:
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

            anim_stack_criteria = fbx.FbxCriteria.ObjectType(fbx.FbxAnimStack.ClassId)
            if scene.GetSrcObjectCount(anim_stack_criteria) > 0:
                raise FbxImportError("Animated FBX files are not supported for Assembly Part import.")

            geometry_converter = fbx.FbxGeometryConverter(sdk_manager)
            geometry_converter.Triangulate(scene, True)

            mesh_nodes: list = []
            _collect_mesh_nodes(scene.GetRootNode(), mesh_nodes, fbx)
            if not mesh_nodes:
                raise FbxImportError(f"FBX file does not contain any polygon mesh nodes: {fbx_path}")

            point_components = array("f")
            face_vertex_counts = array("i")
            face_vertex_indices = array("i")
            uv_components = array("f")
            vertex_color_components = array("f")
            point_offset = 0
            usable_vertex_colors = True

            for node in mesh_nodes:
                throw_if_cancelled(cancel_event)
                mesh = node.GetMesh()
                if mesh is None:
                    continue
                if mesh.GetDeformerCount() > 0:
                    raise FbxImportError("Skinned FBX files are not supported for Assembly Part import.")

                transform = node.EvaluateGlobalTransform()
                control_points = mesh.GetControlPoints()
                local_point_count = mesh.GetControlPointsCount()
                for point_index in range(local_point_count):
                    control_point = _transform_control_point(fbx, transform, control_points[point_index])
                    point_components.extend((float(control_point[0]), float(control_point[1]), float(control_point[2])))

                mesh_color_components = [0.0] * (local_point_count * 4)
                has_colors = False
                assigned_color_flags = bytearray(local_point_count)
                referenced_point_flags = bytearray(local_point_count)
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
                    for vertex_order in range(polygon_size):
                        control_point_index = int(mesh.GetPolygonVertex(polygon_index, vertex_order))
                        if control_point_index < 0 or control_point_index >= local_point_count:
                            raise FbxImportError(
                                f"FBX polygon index is out of bounds for control points in {Path(fbx_path).name}."
                            )
                        referenced_point_flags[control_point_index] = 1
                        face_vertex_indices.append(point_offset + control_point_index)
                        if default_uv_set is not None:
                            uv = fbx.FbxVector2()
                            mapped = mesh.GetPolygonVertexUV(polygon_index, vertex_order, default_uv_set, uv)
                            if mapped:
                                uv_components.extend((float(uv[0]), float(uv[1])))

                        color = _read_vertex_color(mesh, polygon_index, vertex_order)
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

            if not point_components or not face_vertex_counts or not face_vertex_indices:
                raise FbxImportError(f"FBX file does not contain readable mesh topology: {fbx_path}")

            return GeometryBuffer(
                name=prototype_name,
                point_components=point_components,
                face_vertex_counts=face_vertex_counts,
                face_vertex_indices=face_vertex_indices,
                uv_components=uv_components,
                vertex_color_components=vertex_color_components,
            )
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
            vertex_color_components=array("f", payload.get("vertex_color_components", [])),
        )


_BACKEND_OVERRIDE: FbxBackend | None = None


def set_fbx_backend_for_testing(backend: FbxBackend | None) -> None:
    global _BACKEND_OVERRIDE
    _BACKEND_OVERRIDE = backend


def get_fbx_backend(fbx_path: str) -> FbxBackend:
    if _BACKEND_OVERRIDE is not None:
        return _BACKEND_OVERRIDE
    if Path(fbx_path).suffix.lower() == ".json":
        return JsonGeometryBackend()
    return AutodeskFbxBackend()


def load_fbx_geometry(
    fbx_path: str,
    prototype_name: str,
    *,
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
    telemetry_callback=None,
    cancel_event=None,
) -> GeometryBuffer:
    backend = get_fbx_backend(fbx_path)
    return backend.load_mesh_payload(
        fbx_path,
        prototype_name,
        cpu_profile=cpu_profile,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
    )


def _collect_mesh_nodes(node, mesh_nodes: list, fbx_module) -> None:
    if node is None:
        return
    mesh = node.GetMesh()
    if mesh is not None:
        mesh_nodes.append(node)
    for child_index in range(node.GetChildCount()):
        _collect_mesh_nodes(node.GetChild(child_index), mesh_nodes, fbx_module)


def _read_vertex_color(mesh, polygon_index: int, vertex_order: int) -> tuple[float, float, float, float] | None:
    if mesh.GetElementVertexColorCount() <= 0:
        return None
    color_element = mesh.GetElementVertexColor(0)
    if color_element is None:
        return None
    polygon_vertex_index = mesh.GetPolygonVertexIndex(polygon_index) + vertex_order
    direct_array = color_element.GetDirectArray()
    if direct_array.GetCount() <= 0:
        return None
    mapping_mode = color_element.GetMappingMode()
    reference_mode = color_element.GetReferenceMode()
    if mapping_mode not in (0, 1, 3):  # eByControlPoint, eByPolygonVertex, eAllSame
        return None

    if mapping_mode == 3:
        direct_index = 0
    elif mapping_mode == 1:
        direct_index = polygon_vertex_index
    else:
        direct_index = mesh.GetPolygonVertex(polygon_index, vertex_order)

    if reference_mode == 1:  # eIndexToDirect
        index_array = color_element.GetIndexArray()
        if direct_index >= index_array.GetCount():
            return None
        direct_index = index_array.GetAt(direct_index)

    if direct_index >= direct_array.GetCount():
        return None
    color = direct_array.GetAt(direct_index)
    return (float(color.mRed), float(color.mGreen), float(color.mBlue), float(color.mAlpha))


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


def _transform_control_point(fbx_module, transform, control_point):
    try:
        w = float(control_point[3])
    except (IndexError, TypeError):
        w = 1.0
    vector = fbx_module.FbxVector4(
        float(control_point[0]),
        float(control_point[1]),
        float(control_point[2]),
        w,
    )
    try:
        return transform.MultT(vector)
    except TypeError as exc:
        raise FbxImportError(
            "Autodesk FBX SDK matrix transform call failed while reading control points. "
            "This usually indicates a Python binding mismatch in the installed FBX SDK."
        ) from exc
