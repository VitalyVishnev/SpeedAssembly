from __future__ import annotations

import time
from pathlib import Path

from .geometry_buffers import geometry_buffer_to_mesh
from .job_control import emit_telemetry, throw_if_cancelled
from .models import (
    AssemblyPartInstance,
    CanonicalTreeModel,
    CompactMeshSection,
    ConversionPhase,
    ExportStats,
    GeometryBuffer,
    InstanceBinding,
    MaterialSpec,
    MeshData,
    MeshSection,
    Prototype,
    PrototypeResolutionMode,
    PrototypeStrategy,
    SkeletalSupportPrimvars,
    UsdAssemblyDocument,
    ValidationIssue,
)
from .naming import make_stable_prim_name
from .ue_schema import DEFAULT_UE_SCHEMA_CONTRACT, UeSchemaContract


def render_usda(
    model: CanonicalTreeModel,
    diagnostics: tuple[ValidationIssue, ...],
    contract: UeSchemaContract = DEFAULT_UE_SCHEMA_CONTRACT,
    base_mesh_name: str | None = None,
) -> UsdAssemblyDocument:
    error_codes = [issue.code for issue in diagnostics if issue.severity == "error"]
    if error_codes:
        raise ValueError(
            "Cannot author USDA while validation errors are present: " + ", ".join(sorted(dict.fromkeys(error_codes)))
        )

    resolved_base_mesh_name = make_stable_prim_name(base_mesh_name or contract.base_mesh_name, fallback=contract.base_mesh_name)
    resolved_base_skel_root_name = (
        make_stable_prim_name(f"{resolved_base_mesh_name}_Geo", fallback=contract.base_skel_root_name)
        if base_mesh_name
        else contract.base_skel_root_name
    )
    resolved_skeleton_name = (
        make_stable_prim_name(f"{resolved_base_mesh_name}_Skeleton", fallback=contract.skeleton_name)
        if base_mesh_name
        else contract.skeleton_name
    )
    resolved_base_animation_name = "animation" if base_mesh_name else contract.base_animation_name
    resolved_base_joint_root_name = (
        _resolved_root_joint_alias(model, resolved_base_mesh_name)
        if base_mesh_name
        else None
    )
    base_animation = _render_base_animation(model, resolved_base_animation_name, resolved_base_joint_root_name)
    base_mesh = _render_base_mesh(
        model,
        contract,
        resolved_base_mesh_name,
        resolved_base_skel_root_name,
        resolved_skeleton_name,
        resolved_base_joint_root_name,
    )
    main_skeleton = _render_main_skeleton(
        model,
        contract,
        resolved_base_skel_root_name,
        resolved_base_animation_name,
        resolved_skeleton_name,
        resolved_base_joint_root_name,
    )
    point_instancer = _render_point_instancer(model, contract)
    materials = _render_materials_scope(model.materials, contract.root_prim_name)
    prototype_library = (
        _render_prototype_library(model, contract) if model.prototype_strategy == PrototypeStrategy.REFERENCED_SCOPE else ""
    )
    skelroot_support = _render_skelroot_support_primvars(model.skeletal_support_primvars)

    text = f'''#usda 1.0
(
    defaultPrim = "{contract.root_prim_name}"
    metersPerUnit = {contract.stage_meters_per_unit:g}
    upAxis = "{contract.stage_up_axis}"
)

    def Xform "{contract.root_prim_name}" (
        prepend apiSchemas = ["{contract.root_api}"]
        kind = "{contract.root_kind}"
)
{{
    uniform token {contract.mesh_type_attr} = "{contract.mesh_type_value}"
    {('custom rel' if base_mesh_name else 'rel')} unreal:naniteAssembly:skeleton = </{contract.root_prim_name}/{resolved_base_skel_root_name}/{resolved_skeleton_name}>

{_indent(materials, 1)}

{_indent(prototype_library, 1)}

    def SkelRoot "{resolved_base_skel_root_name}" (
        kind = "component"
    )
    {{
{_indent(skelroot_support, 2)}
        matrix4d xformOp:transform = {_identity_matrix()}
        uniform token[] xformOpOrder = ["xformOp:transform"]

{_indent(base_animation, 2)}

{_indent(base_mesh, 2)}

{_indent(main_skeleton, 2)}
    }}

{_indent(point_instancer, 1)}
}}
'''
    return UsdAssemblyDocument(text=text, diagnostics=diagnostics, stats=ExportStats(streamed=False))


def write_usda_document(
    model: CanonicalTreeModel,
    diagnostics: tuple[ValidationIssue, ...],
    *,
    output_path: Path | None,
    contract: UeSchemaContract = DEFAULT_UE_SCHEMA_CONTRACT,
    base_mesh_name: str | None = None,
    telemetry_callback=None,
    cancel_event=None,
) -> UsdAssemblyDocument:
    if output_path is None or not _model_requires_streaming_writer(model):
        document = render_usda(model, diagnostics, contract=contract, base_mesh_name=base_mesh_name)
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(document.text or "", encoding="utf-8")
            stats = ExportStats(
                bytes_written=output_path.stat().st_size if output_path.exists() else 0,
                duration_seconds=0.0,
                streamed=False,
            )
            return UsdAssemblyDocument(text=document.text, diagnostics=document.diagnostics, stats=stats)
        return document

    started_at = time.perf_counter()
    emit_telemetry(
        telemetry_callback,
        ConversionPhase.USDA_WRITING,
        message="Streaming USDA to disk.",
        started_at=started_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output_path.with_name(f"{output_path.name}.partial")
    if temp_output.exists():
        temp_output.unlink()
    try:
        with temp_output.open("w", encoding="utf-8", buffering=1024 * 1024) as handle:
            _write_streaming_usda(
                handle,
                model,
                diagnostics,
                contract=contract,
                base_mesh_name=base_mesh_name,
                telemetry_callback=telemetry_callback,
                cancel_event=cancel_event,
                started_at=started_at,
            )
        temp_output.replace(output_path)
        stats = ExportStats(
            bytes_written=output_path.stat().st_size if output_path.exists() else 0,
            duration_seconds=max(0.0, time.perf_counter() - started_at),
            streamed=True,
        )
        emit_telemetry(
            telemetry_callback,
            ConversionPhase.COMPLETED,
            message="USDA export completed.",
            output_bytes_written=stats.bytes_written,
            started_at=started_at,
        )
        return UsdAssemblyDocument(text=None, diagnostics=diagnostics, stats=stats)
    except Exception:
        if temp_output.exists():
            temp_output.unlink()
        raise


def _render_materials_scope(materials: tuple[MaterialSpec, ...], root_prim_name: str) -> str:
    if not materials:
        return ""
    definitions = "\n".join(_render_material(material, root_prim_name) for material in materials)
    return f'''def Scope "Materials"
{{
{definitions}
}}'''


def _render_material(material: MaterialSpec, root_prim_name: str) -> str:
    material_name = _material_prim_name(material)
    shader_name = _material_shader_name(material)
    diffuse_color = _material_diffuse_color(material)
    unreal_output = _render_unreal_material_output(material, root_prim_name)
    return f'''    def Material "{material_name}"
    {{
        token outputs:displacement.connect = </{root_prim_name}/Materials/{material_name}/{shader_name}.outputs:displacement>
        token outputs:surface.connect = </{root_prim_name}/Materials/{material_name}/{shader_name}.outputs:surface>
{_indent(unreal_output, 2)}

        def Shader "{shader_name}"
        {{
            uniform token info:id = "UsdPreviewSurface"
            color3f inputs:diffuseColor = {diffuse_color}
            token outputs:displacement
            token outputs:surface
        }}
    }}'''


def _render_material_binding(mesh: MeshData | GeometryBuffer) -> str:
    sections = mesh.sections
    if not sections:
        return ""
    if len(sections) == 1:
        section = sections[0]
        return f'rel material:binding = </Tree/Materials/{_material_prim_name_from_id(section.material_id)}>'
    subsets = "\n".join(_render_geom_subset(section) for section in sections)
    return f'''uniform token subsetFamily:materialBind:familyType = "nonOverlapping"
{subsets}'''


def _render_geom_subset(section: MeshSection | CompactMeshSection) -> str:
    indices = ", ".join(str(index) for index in section.face_indices)
    return f'''def GeomSubset "{_material_prim_name_from_id(section.material_id)}" (
    prepend apiSchemas = ["MaterialBindingAPI"]
)
{{
    uniform token elementType = "face"
    uniform token familyName = "materialBind"
    int[] indices = [{indices}]
    rel material:binding = </Tree/Materials/{_material_prim_name_from_id(section.material_id)}>
}}'''


def _render_base_mesh(
    model: CanonicalTreeModel,
    contract: UeSchemaContract,
    base_mesh_name: str,
    base_skel_root_name: str,
    skeleton_name: str,
    base_joint_root_name: str | None,
) -> str:
    if model.base_mesh is None:
        raise ValueError("Base skeletal tree mesh is required before USDA authoring.")

    mesh = model.base_mesh
    joint_paths = _render_joint_paths(model, root_joint_name=base_joint_root_name)
    joint_indices = ", ".join(str(index) for index in mesh.skel_joint_indices)
    joint_weights = ", ".join(f"{weight:g}" for weight in mesh.skel_joint_weights)
    skinning = ""
    if mesh.skel_joint_indices and mesh.skel_joint_weights:
        skinning = f'''
    uniform int[] primvars:skel:jointIndices = [{joint_indices}] (
        elementSize = {mesh.skel_element_size or 1}
        interpolation = "vertex"
    )
    uniform float[] primvars:skel:jointWeights = [{joint_weights}] (
        elementSize = {mesh.skel_element_size or 1}
        interpolation = "vertex"
    )
    {contract.skinning_method_attr} = "{contract.skinning_method_value}"'''
    material_binding = _render_material_binding(mesh)

    return f'''def Mesh "{base_mesh_name}" (
    prepend apiSchemas = ["{contract.skel_binding_api}"]
)
{{
    uniform token[] skel:joints = [{joint_paths}]
    uniform matrix4d primvars:skel:geomBindTransform = {_identity_matrix()}
    append rel skel:skeleton = </{contract.root_prim_name}/{base_skel_root_name}/{skeleton_name}>
    uniform token subdivisionScheme = "none"
{_indent(material_binding, 1)}
    {_render_mesh_payload(mesh, contract.mesh_orientation)}{skinning}
}}'''


def _render_main_skeleton(
    model: CanonicalTreeModel,
    contract: UeSchemaContract,
    base_skel_root_name: str,
    base_animation_name: str,
    skeleton_name: str,
    base_joint_root_name: str | None,
) -> str:
    return f'''def Skeleton "{skeleton_name}" (
    prepend apiSchemas = ["{contract.skel_binding_api}"]
)
{{
    uniform matrix4d[] bindTransforms = [{_render_bind_transforms(model)}]
    uniform token[] jointNames = [{_render_joint_basenames(model, root_joint_name=base_joint_root_name)}]
    uniform token[] joints = [{_render_joint_paths(model, root_joint_name=base_joint_root_name)}]
    uniform token purpose = "guide"
    uniform matrix4d[] restTransforms = [{_render_rest_transforms(model)}]
    append rel skel:animationSource = </{contract.root_prim_name}/{base_skel_root_name}/{base_animation_name}>
    uniform token visibility = "invisible"
}}'''


def _render_base_animation(model: CanonicalTreeModel, animation_name: str, root_joint_name: str | None) -> str:
    joints = _render_joint_paths(model, root_joint_name=root_joint_name)
    rotations = ", ".join(_identity_quaternion() for _ in model.skeleton)
    scales = ", ".join("(1, 1, 1)" for _ in model.skeleton)
    translations = _render_joint_rest_translations(model)
    return f'''def SkelAnimation "{animation_name}"
{{
    uniform token[] joints = [{joints}]
    quath[] rotations = [{rotations}]
    half3[] scales = [{scales}]
    float3[] translations = [{translations}]
}}'''


def _render_prototype_library(model: CanonicalTreeModel, contract: UeSchemaContract) -> str:
    if not model.prototypes:
        return ""
    definitions = "\n".join(_render_library_prototype(prototype, contract) for prototype in model.prototypes)
    return f'''def Xform "PrototypeLibrary"
{{
{definitions}
}}'''


def _render_library_prototype(prototype: Prototype, contract: UeSchemaContract) -> str:
    mesh = _prototype_inline_mesh(prototype)
    if mesh is None:
        raise ValueError(f"Prototype {prototype.identity.prim_name} is missing mesh payload.")

    material_binding = _render_material_binding(mesh)
    part_mesh_name = make_stable_prim_name(prototype.identity.prim_name, fallback=contract.part_mesh_name)
    return f'''    def Xform "{prototype.identity.prim_name}" (
        kind = "component"
    )
    {{
        token visibility = "invisible"
        def Mesh "{part_mesh_name}"
        {{
            uniform token subdivisionScheme = "none"
{_indent(material_binding, 3)}
            {_render_mesh_payload(mesh, contract.mesh_orientation)}
        }}
    }}'''


def _render_point_instancer(model: CanonicalTreeModel, contract: UeSchemaContract) -> str:
    assembly_parts = model.assembly_parts
    prototypes = model.prototypes
    if not assembly_parts:
        return ""

    prototype_index_map = {prototype.source_key: index for index, prototype in enumerate(prototypes)}
    proto_indices = ", ".join(str(prototype_index_map.get(part.prototype_key, 0)) for part in assembly_parts)
    positions = ", ".join(part.position.to_usda() for part in assembly_parts)
    orientations = ", ".join(part.orientation.to_usda() for part in assembly_parts)
    scales = ", ".join(part.scale.to_usda() for part in assembly_parts)
    names = ", ".join(f'"{_prototype_name_for_instance(part, prototypes)}"' for part in assembly_parts)
    binding_width, bindings = _normalized_bindings(assembly_parts, contract.point_instancer_joint_element_size)
    bind_joints = ", ".join(f'"{token}"' for binding in bindings for token in binding.joint_tokens)
    bind_weights = ", ".join(f"{weight:g}" for binding in bindings for weight in binding.weights)
    prototype_paths = _prototype_target_paths(model, contract)
    prototype_defs = _render_instancer_prototypes(model, contract)
    binding_support = _render_binding_support_primvars(model, bindings)

    return f'''def PointInstancer "{contract.assembly_parts_instancer_name}" (
    prepend apiSchemas = ["{contract.binding_api}"]
    kind = "group"
)
{{
    int64[] invisibleIds = []
    quath[] orientations = [{orientations}]
    point3f[] positions = [{positions}]
{_indent(binding_support, 1)}
    {contract.bind_joints_attr} = [{bind_joints}] (
        elementSize = {binding_width}
        interpolation = "vertex"
    )
    int[] primvars:unreal:naniteAssembly:bindJoints:indices = None
    {contract.bind_weights_attr} = [{bind_weights}] (
        elementSize = {binding_width}
        interpolation = "vertex"
    )
    int[] primvars:unreal:naniteAssembly:bindJointWeights:indices = None
    int[] protoIndices = [{proto_indices}]
    rel prototypes = [{prototype_paths}]
    float3[] scales = [{scales}]
    string[] primvars:name = [{names}] (
        interpolation = "varying"
    )

    def Scope "{contract.prototype_scope_name}" (
        kind = "group"
    )
    {{
{_indent(prototype_defs, 2)}
    }}
}}'''


def _render_binding_support_primvars(model: CanonicalTreeModel, bindings: tuple[InstanceBinding, ...]) -> str:
    support = model.skeletal_support_primvars
    if support is None or not bindings:
        return ""

    path_map = _build_joint_path_map(model)
    hierarchical_map = {token: depth for token, depth in zip(support.capture_paths, support.hierarchical_depths)}
    logical_map = {token: depth for token, depth in zip(support.capture_paths, support.logical_depths)}
    for joint, hierarchical_depth, logical_depth in zip(
        model.skeleton,
        support.hierarchical_depths,
        support.logical_depths,
        strict=False,
    ):
        hierarchical_map[joint.name] = hierarchical_depth
        logical_map[joint.name] = logical_depth
        hierarchical_map[path_map[joint.name]] = hierarchical_depth
        logical_map[path_map[joint.name]] = logical_depth

    hierarchical_values = [str(hierarchical_map.get(token, 0)) for binding in bindings for token in binding.joint_tokens]
    logical_values = [str(logical_map.get(token, 0)) for binding in bindings for token in binding.joint_tokens]
    lengths = ", ".join(str(binding.element_size) for binding in bindings)
    return f'''int[] primvars:hierarchicalDepth = [{", ".join(hierarchical_values)}] (
        interpolation = "vertex"
    )
    int[] primvars:hierarchicalDepth:lengths = [{lengths}] (
        interpolation = "varying"
    )
    int[] primvars:logicalDepth = [{", ".join(logical_values)}] (
        interpolation = "vertex"
    )
    int[] primvars:logicalDepth:lengths = [{lengths}] (
        interpolation = "varying"
    )'''


def _render_instancer_prototypes(model: CanonicalTreeModel, contract: UeSchemaContract) -> str:
    rendered: list[str] = []
    for prototype in model.prototypes:
        if prototype.resolution_mode == PrototypeResolutionMode.EXTERNAL_ASSET:
            rendered.append(_render_external_instancer_prototype(prototype, contract))
            continue
        if model.prototype_strategy == PrototypeStrategy.INLINE_SKELETAL_PART:
            rendered.append(_render_inline_instancer_prototype(prototype, contract))
            continue
        rendered.append(
            f'''        def "{prototype.identity.prim_name}" (
            append references = </{contract.root_prim_name}/PrototypeLibrary/{prototype.identity.prim_name}>
        )
        {{
            token visibility = None
        }}'''
        )
    return "\n".join(rendered)


def _render_inline_instancer_prototype(prototype: Prototype, contract: UeSchemaContract) -> str:
    mesh = _prototype_inline_mesh(prototype)
    if mesh is None:
        raise ValueError(f"Prototype {prototype.identity.prim_name} is missing mesh payload.")

    name = prototype.identity.prim_name
    part_mesh_name = make_stable_prim_name(name, fallback=contract.part_mesh_name)
    part_joint_name = make_stable_prim_name(name, fallback="root")
    skinning = _render_single_joint_skinning(mesh, contract)
    material_binding = _render_material_binding(mesh)
    return f'''        def Xform "{name}"
        {{
            def SkelRoot "{contract.part_skel_root_name}" (
                kind = "component"
            )
            {{
                def SkelAnimation "{contract.part_animation_name}"
                {{
                    uniform token[] joints = ["{part_joint_name}"]
                    quath[] rotations = [{_identity_quaternion()}]
                    half3[] scales = [(1, 1, 1)]
                    float3[] translations = [(0, 0, 0)]
                }}

                def Mesh "{part_mesh_name}" (
                    prepend apiSchemas = ["{contract.skel_binding_api}"]
                )
                {{
                    uniform token[] skel:joints = ["{part_joint_name}"]
                    uniform matrix4d primvars:skel:geomBindTransform = {_identity_matrix()}
                    append rel skel:skeleton = {contract.part_skeleton_path(name)}
                    uniform token subdivisionScheme = "none"
{_indent(material_binding, 5)}
                    {_render_mesh_payload(mesh, contract.mesh_orientation)}
{_indent(skinning, 5)}
                }}

                def Skeleton "{contract.part_skeleton_name}" (
                    prepend apiSchemas = ["{contract.skel_binding_api}"]
                )
                {{
                    uniform matrix4d[] bindTransforms = [{_identity_matrix()}]
                    uniform token[] jointNames = ["{part_joint_name}"]
                    uniform token[] joints = ["{part_joint_name}"]
                    uniform token purpose = "guide"
                    uniform matrix4d[] restTransforms = [{_identity_matrix()}]
                    append rel skel:animationSource = {contract.part_animation_path(name)}
                    uniform token visibility = "invisible"
                }}
            }}
        }}'''


def _render_external_instancer_prototype(prototype: Prototype, contract: UeSchemaContract) -> str:
    if not prototype.mesh_asset_path:
        raise ValueError(f"Prototype {prototype.identity.prim_name} is missing Unreal asset path.")
    return f'''        def Xform "{prototype.identity.prim_name}" (
            prepend apiSchemas = ["{contract.external_ref_api}"]
            kind = "component"
        )
        {{
            uniform token unreal:naniteAssembly:meshAssetPath = "{prototype.mesh_asset_path}"
        }}'''


def _render_skelroot_support_primvars(support: SkeletalSupportPrimvars | None) -> str:
    if support is None:
        return ""

    capture_paths = ", ".join(f'"{token}"' for token in support.capture_paths)
    ue_joint_names = ", ".join(f'"{token}"' for token in support.ue_joint_names)
    joint_count = len(support.capture_paths)
    hierarchical = ", ".join(str(value) for value in support.hierarchical_depths)
    logical = ", ".join(str(value) for value in support.logical_depths)
    return f'''string[] primvars:boneCapture_pCaptPath = [{capture_paths}] (
            elementSize = 1
            interpolation = "constant"
        )
        int[] primvars:boneCapture_pCaptPath:indices = None
        int[] primvars:boneCapture_pCaptPath:lengths = [{joint_count}] (
            interpolation = "constant"
        )
        int[] primvars:hierarchicalDepth = [{hierarchical}] (
            elementSize = 1
            interpolation = "constant"
        )
        int[] primvars:hierarchicalDepth:indices = None
        int[] primvars:hierarchicalDepth:lengths = [{joint_count}] (
            interpolation = "constant"
        )
        matrix4d primvars:localtransform = {support.local_transform.to_usda()}
        int[] primvars:localtransform:indices = None
        int[] primvars:logicalDepth = [{logical}] (
            elementSize = 1
            interpolation = "constant"
        )
        int[] primvars:logicalDepth:indices = None
        int[] primvars:logicalDepth:lengths = [{joint_count}] (
            interpolation = "constant"
        )
        token[] primvars:ueJointNames = [{ue_joint_names}] (
            elementSize = {joint_count}
            interpolation = "constant"
        )
        int[] primvars:ueJointNames:indices = None
        int[] primvars:ueJointNames:lengths = [{joint_count}] (
            interpolation = "constant"
        )'''


def _prototype_target_paths(model: CanonicalTreeModel, contract: UeSchemaContract) -> str:
    if model.prototype_strategy == PrototypeStrategy.INLINE_SKELETAL_PART:
        return ", ".join(contract.prototype_root_path(prototype.identity.prim_name) for prototype in model.prototypes)
    return ", ".join(
        f"</{contract.root_prim_name}/{contract.assembly_parts_instancer_name}/{contract.prototype_scope_name}/{prototype.identity.prim_name}>"
        for prototype in model.prototypes
    )


def _normalized_bindings(
    assembly_parts: tuple[AssemblyPartInstance, ...],
    target_width: int,
) -> tuple[int, tuple[InstanceBinding, ...]]:
    width = max((part.binding.element_size for part in assembly_parts), default=1)
    width = max(width, target_width, 1)
    return width, tuple(part.binding.padded(width) for part in assembly_parts)


def _prototype_name_for_instance(part: AssemblyPartInstance, prototypes: tuple[Prototype, ...]) -> str:
    for prototype in prototypes:
        if prototype.source_key == part.prototype_key:
            return prototype.source_name
    return part.prototype_key


def _material_prim_name(material: MaterialSpec) -> str:
    return _material_prim_name_from_id(material.source_id)


def _material_prim_name_from_id(material_id: int, name: str | None = None) -> str:
    safe_name = "".join(character if character.isalnum() else "_" for character in (name or f"Material_{material_id}")).strip("_")
    if not safe_name:
        safe_name = f"Material_{material_id}"
    return f"{safe_name}_{material_id}"


def _material_shader_name(material: MaterialSpec) -> str:
    return f"{_material_prim_name(material)}_shader"


def _material_unreal_shader_name(material: MaterialSpec) -> str:
    return f"{_material_prim_name(material)}_unreal_shader"


def _render_unreal_material_output(material: MaterialSpec, root_prim_name: str) -> str:
    if not material.ue_asset_path:
        return ""
    material_name = _material_prim_name(material)
    shader_name = _material_unreal_shader_name(material)
    return f'''token outputs:unreal:surface.connect = </{root_prim_name}/Materials/{material_name}/{shader_name}.outputs:out>

def Shader "{shader_name}"
{{
    uniform token info:implementationSource = "sourceAsset"
    uniform asset info:unreal:sourceAsset = @{material.ue_asset_path}@
    token outputs:out
}}'''


def _material_diffuse_color(material: MaterialSpec) -> str:
    color_map = next((dict(payload) for map_name, payload in material.maps if map_name == "Color"), None)
    if color_map is None:
        return "(0.5, 0.5, 0.5)"
    red = _clamp_material_channel(color_map.get("ColorR"))
    green = _clamp_material_channel(color_map.get("ColorG"))
    blue = _clamp_material_channel(color_map.get("ColorB"))
    return f"({red:g}, {green:g}, {blue:g})"


def _clamp_material_channel(value: str | None) -> float:
    if value is None:
        return 0.5
    try:
        numeric = float(value)
    except ValueError:
        return 0.5
    return max(0.0, min(1.0, numeric))


def _render_joint_paths(model: CanonicalTreeModel, root_joint_name: str | None = None) -> str:
    path_map = _build_joint_path_map(model, root_joint_name=root_joint_name)
    return ", ".join(f'"{path_map[joint.name]}"' for joint in model.skeleton)


def _render_joint_basenames(model: CanonicalTreeModel, root_joint_name: str | None = None) -> str:
    return ", ".join(f'"{_joint_render_name(joint, root_joint_name)}"' for joint in model.skeleton)


def _render_joint_rest_translations(model: CanonicalTreeModel) -> str:
    return ", ".join(joint.rest_translate.to_usda() for joint in model.skeleton)


def _render_mesh_payload(mesh: MeshData | GeometryBuffer, mesh_orientation: str) -> str:
    # The source-to-stage conversion is a pure rotation plus uniform scale, so winding is preserved.
    if isinstance(mesh, GeometryBuffer):
        mesh = geometry_buffer_to_mesh(mesh)
    points = ", ".join(point.to_usda() for point in mesh.points)
    counts = ", ".join(str(value) for value in mesh.face_vertex_counts)
    indices = ", ".join(str(value) for value in mesh.face_vertex_indices)
    uv_payload = ""
    if mesh.uv_coords:
        uvs = ", ".join(uv.to_usda() for uv in mesh.uv_coords)
        uv_payload = f'''
    texCoord2f[] primvars:st = [{uvs}] (
        interpolation = "faceVarying"
    )'''
    return f'''uniform token orientation = "{mesh_orientation}"
    point3f[] points = [{points}] (
        interpolation = "vertex"
    )
    int[] faceVertexCounts = [{counts}]
    int[] faceVertexIndices = [{indices}]{uv_payload}'''


def _render_single_joint_skinning(mesh: MeshData | GeometryBuffer, contract: UeSchemaContract) -> str:
    point_count = mesh.point_count if isinstance(mesh, GeometryBuffer) else len(mesh.points)
    joint_indices = ", ".join("0" for _ in range(point_count))
    joint_weights = ", ".join("1" for _ in range(point_count))
    return f'''uniform int[] primvars:skel:jointIndices = [{joint_indices}] (
    elementSize = 1
    interpolation = "vertex"
)
uniform float[] primvars:skel:jointWeights = [{joint_weights}] (
    elementSize = 1
    interpolation = "vertex"
)
{contract.skinning_method_attr} = "{contract.skinning_method_value}"'''


def _indent(value: str, level: int) -> str:
    if not value:
        return ""
    prefix = " " * 4 * level
    return "\n".join(f"{prefix}{line}" if line else "" for line in value.splitlines())


def _build_joint_path_map(model: CanonicalTreeModel, root_joint_name: str | None = None) -> dict[str, str]:
    joints_by_name = {joint.name: joint for joint in model.skeleton}
    path_map: dict[str, str] = {}

    def resolve(name: str) -> str:
        if name in path_map:
            return path_map[name]
        joint = joints_by_name[name]
        if joint.parent is None:
            path_map[name] = _joint_render_name(joint, root_joint_name)
        else:
            path_map[name] = f"{resolve(joint.parent)}/{_joint_render_name(joint, root_joint_name)}"
        return path_map[name]

    for joint in model.skeleton:
        resolve(joint.name)
    return path_map


def _joint_render_name(joint, root_joint_name: str | None) -> str:
    if root_joint_name and joint.parent is None:
        return root_joint_name
    return joint.name


def _resolved_root_joint_alias(model: CanonicalTreeModel, default_name: str) -> str | None:
    root_joint_count = sum(1 for joint in model.skeleton if joint.parent is None)
    if root_joint_count == 1:
        return default_name
    return None


def _identity_matrix() -> str:
    return "( (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1) )"


def _render_bind_transforms(model: CanonicalTreeModel) -> str:
    return ", ".join(joint.bind_transform.to_usda() for joint in model.skeleton)


def _render_rest_transforms(model: CanonicalTreeModel) -> str:
    return ", ".join(joint.rest_transform.to_usda() for joint in model.skeleton)


def _identity_quaternion() -> str:
    return "(1, 0, 0, 0)"


def _prototype_inline_mesh(prototype: Prototype) -> MeshData | GeometryBuffer | None:
    if prototype.mesh is not None:
        return prototype.mesh
    if prototype.geometry_payload is not None:
        return prototype.geometry_payload
    return None


def _model_requires_streaming_writer(model: CanonicalTreeModel) -> bool:
    return any(prototype.geometry_payload is not None for prototype in model.prototypes)


def _write_streaming_usda(
    handle,
    model: CanonicalTreeModel,
    diagnostics: tuple[ValidationIssue, ...],
    *,
    contract: UeSchemaContract,
    base_mesh_name: str | None,
    telemetry_callback=None,
    cancel_event=None,
    started_at: float | None = None,
) -> None:
    error_codes = [issue.code for issue in diagnostics if issue.severity == "error"]
    if error_codes:
        raise ValueError(
            "Cannot author USDA while validation errors are present: " + ", ".join(sorted(dict.fromkeys(error_codes)))
        )

    resolved_base_mesh_name = make_stable_prim_name(base_mesh_name or contract.base_mesh_name, fallback=contract.base_mesh_name)
    resolved_base_skel_root_name = (
        make_stable_prim_name(f"{resolved_base_mesh_name}_Geo", fallback=contract.base_skel_root_name)
        if base_mesh_name
        else contract.base_skel_root_name
    )
    resolved_skeleton_name = (
        make_stable_prim_name(f"{resolved_base_mesh_name}_Skeleton", fallback=contract.skeleton_name)
        if base_mesh_name
        else contract.skeleton_name
    )
    resolved_base_animation_name = "animation" if base_mesh_name else contract.base_animation_name
    resolved_base_joint_root_name = (
        _resolved_root_joint_alias(model, resolved_base_mesh_name)
        if base_mesh_name
        else None
    )
    base_animation = _render_base_animation(model, resolved_base_animation_name, resolved_base_joint_root_name)
    base_mesh = _render_base_mesh(
        model,
        contract,
        resolved_base_mesh_name,
        resolved_base_skel_root_name,
        resolved_skeleton_name,
        resolved_base_joint_root_name,
    )
    main_skeleton = _render_main_skeleton(
        model,
        contract,
        resolved_base_skel_root_name,
        resolved_base_animation_name,
        resolved_skeleton_name,
        resolved_base_joint_root_name,
    )
    materials = _render_materials_scope(model.materials, contract.root_prim_name)
    prototype_library = (
        _render_prototype_library(model, contract) if model.prototype_strategy == PrototypeStrategy.REFERENCED_SCOPE else ""
    )
    skelroot_support = _render_skelroot_support_primvars(model.skeletal_support_primvars)

    handle.write(
        f'''#usda 1.0
(
    defaultPrim = "{contract.root_prim_name}"
    metersPerUnit = {contract.stage_meters_per_unit:g}
    upAxis = "{contract.stage_up_axis}"
)

def Xform "{contract.root_prim_name}" (
    prepend apiSchemas = ["{contract.root_api}"]
    kind = "{contract.root_kind}"
)
{{
    uniform token {contract.mesh_type_attr} = "{contract.mesh_type_value}"
    {('custom rel' if base_mesh_name else 'rel')} unreal:naniteAssembly:skeleton = </{contract.root_prim_name}/{resolved_base_skel_root_name}/{resolved_skeleton_name}>

'''
    )
    if materials:
        handle.write(_indent(materials, 1) + "\n\n")
    if prototype_library:
        handle.write(_indent(prototype_library, 1) + "\n\n")
    handle.write(
        f'''    def SkelRoot "{resolved_base_skel_root_name}" (
        kind = "component"
    )
    {{
'''
    )
    if skelroot_support:
        handle.write(_indent(skelroot_support, 2) + "\n")
    handle.write(
        f'''        matrix4d xformOp:transform = {_identity_matrix()}
        uniform token[] xformOpOrder = ["xformOp:transform"]

{_indent(base_animation, 2)}

{_indent(base_mesh, 2)}

{_indent(main_skeleton, 2)}
    }}

'''
    )
    _write_streaming_point_instancer(
        handle,
        model,
        contract,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
        started_at=started_at,
    )
    handle.write("}\n")


def _write_streaming_point_instancer(
    handle,
    model: CanonicalTreeModel,
    contract: UeSchemaContract,
    *,
    telemetry_callback=None,
    cancel_event=None,
    started_at: float | None = None,
) -> None:
    assembly_parts = model.assembly_parts
    prototypes = model.prototypes
    if not assembly_parts:
        return

    prototype_index_map = {prototype.source_key: index for index, prototype in enumerate(prototypes)}
    binding_width, bindings = _normalized_bindings(assembly_parts, contract.point_instancer_joint_element_size)
    binding_support = _render_binding_support_primvars(model, bindings)
    prototype_paths = _prototype_target_paths(model, contract)

    handle.write(
        f'''    def PointInstancer "{contract.assembly_parts_instancer_name}" (
        prepend apiSchemas = ["{contract.binding_api}"]
        kind = "group"
    )
    {{
        int64[] invisibleIds = []
'''
    )
    _write_formatted_array_attribute(
        handle,
        2,
        "quath[] orientations",
        (part.orientation.to_usda() for part in assembly_parts),
    )
    _write_formatted_array_attribute(
        handle,
        2,
        "point3f[] positions",
        (part.position.to_usda() for part in assembly_parts),
    )
    if binding_support:
        handle.write(_indent(binding_support, 2) + "\n")
    _write_formatted_array_attribute(
        handle,
        2,
        contract.bind_joints_attr,
        (f'"{token}"' for binding in bindings for token in binding.joint_tokens),
        metadata_lines=(
            f"elementSize = {binding_width}",
            'interpolation = "vertex"',
        ),
    )
    handle.write("        int[] primvars:unreal:naniteAssembly:bindJoints:indices = None\n")
    _write_formatted_array_attribute(
        handle,
        2,
        contract.bind_weights_attr,
        (f"{weight:g}" for binding in bindings for weight in binding.weights),
        metadata_lines=(
            f"elementSize = {binding_width}",
            'interpolation = "vertex"',
        ),
    )
    handle.write("        int[] primvars:unreal:naniteAssembly:bindJointWeights:indices = None\n")
    _write_formatted_array_attribute(
        handle,
        2,
        "int[] protoIndices",
        (str(prototype_index_map.get(part.prototype_key, 0)) for part in assembly_parts),
    )
    handle.write(f"        rel prototypes = [{prototype_paths}]\n")
    _write_formatted_array_attribute(
        handle,
        2,
        "float3[] scales",
        (part.scale.to_usda() for part in assembly_parts),
    )
    _write_formatted_array_attribute(
        handle,
        2,
        "string[] primvars:name",
        (f'"{_prototype_name_for_instance(part, prototypes)}"' for part in assembly_parts),
        metadata_lines=('interpolation = "varying"',),
    )
    handle.write(
        f'''
        def Scope "{contract.prototype_scope_name}" (
            kind = "group"
        )
        {{
'''
    )
    for index, prototype in enumerate(model.prototypes, start=1):
        throw_if_cancelled(cancel_event)
        _write_streaming_instancer_prototype(handle, prototype, contract)
        emit_telemetry(
            telemetry_callback,
            ConversionPhase.USDA_WRITING,
            completed_units=index,
            total_units=len(model.prototypes),
            message=f"Writing prototype {prototype.identity.prim_name}.",
            started_at=started_at,
        )
    handle.write("        }\n    }\n")


def _write_streaming_instancer_prototype(handle, prototype: Prototype, contract: UeSchemaContract) -> None:
    if prototype.resolution_mode == PrototypeResolutionMode.EXTERNAL_ASSET:
        handle.write(_indent(_render_external_instancer_prototype(prototype, contract), 2) + "\n")
        return
    mesh = _prototype_inline_mesh(prototype)
    if mesh is None:
        raise ValueError(f"Prototype {prototype.identity.prim_name} is missing mesh payload.")

    name = prototype.identity.prim_name
    part_mesh_name = make_stable_prim_name(name, fallback=contract.part_mesh_name)
    part_joint_name = make_stable_prim_name(name, fallback="root")
    handle.write(
        f'''        def Xform "{name}"
        {{
            def SkelRoot "{contract.part_skel_root_name}" (
                kind = "component"
            )
            {{
                def SkelAnimation "{contract.part_animation_name}"
                {{
                    uniform token[] joints = ["{part_joint_name}"]
                    quath[] rotations = [{_identity_quaternion()}]
                    half3[] scales = [(1, 1, 1)]
                    float3[] translations = [(0, 0, 0)]
                }}

                def Mesh "{part_mesh_name}" (
                    prepend apiSchemas = ["{contract.skel_binding_api}"]
                )
                {{
                    uniform token[] skel:joints = ["{part_joint_name}"]
                    uniform matrix4d primvars:skel:geomBindTransform = {_identity_matrix()}
                    append rel skel:skeleton = {contract.part_skeleton_path(name)}
                    uniform token subdivisionScheme = "none"
'''
    )
    _write_streaming_material_binding(handle, mesh, 5)
    _write_streaming_mesh_payload(handle, mesh, contract.mesh_orientation, 5)
    _write_streaming_single_joint_skinning(handle, mesh, contract, 5)
    handle.write(
        f'''                }}

                def Skeleton "{contract.part_skeleton_name}" (
                    prepend apiSchemas = ["{contract.skel_binding_api}"]
                )
                {{
                    uniform matrix4d[] bindTransforms = [{_identity_matrix()}]
                    uniform token[] jointNames = ["{part_joint_name}"]
                    uniform token[] joints = ["{part_joint_name}"]
                    uniform token purpose = "guide"
                    uniform matrix4d[] restTransforms = [{_identity_matrix()}]
                    append rel skel:animationSource = {contract.part_animation_path(name)}
                    uniform token visibility = "invisible"
                }}
            }}
        }}
'''
    )


def _write_streaming_material_binding(handle, mesh: MeshData | GeometryBuffer, indent_level: int) -> None:
    sections = mesh.sections
    if not sections:
        return
    prefix = " " * 4 * indent_level
    if len(sections) == 1:
        handle.write(f'{prefix}rel material:binding = </Tree/Materials/{_material_prim_name_from_id(sections[0].material_id)}>\n')
        return
    handle.write(f'{prefix}uniform token subsetFamily:materialBind:familyType = "nonOverlapping"\n')
    for section in sections:
        handle.write(
            f'''{prefix}def GeomSubset "{_material_prim_name_from_id(section.material_id)}" (
{prefix}    prepend apiSchemas = ["MaterialBindingAPI"]
{prefix})
{prefix}{{
{prefix}    uniform token elementType = "face"
{prefix}    uniform token familyName = "materialBind"
'''
        )
        _write_formatted_array_attribute(
            handle,
            indent_level + 1,
            "int[] indices",
            (str(index) for index in section.face_indices),
        )
        handle.write(
            f'{prefix}    rel material:binding = </Tree/Materials/{_material_prim_name_from_id(section.material_id)}>\n'
            f"{prefix}}}\n"
        )


def _write_streaming_mesh_payload(handle, mesh: MeshData | GeometryBuffer, mesh_orientation: str, indent_level: int) -> None:
    prefix = " " * 4 * indent_level
    handle.write(f'{prefix}uniform token orientation = "{mesh_orientation}"\n')
    _write_formatted_array_attribute(
        handle,
        indent_level,
        "point3f[] points",
        _iter_payload_point_strings(mesh),
        metadata_lines=('interpolation = "vertex"',),
    )
    _write_formatted_array_attribute(
        handle,
        indent_level,
        "int[] faceVertexCounts",
        _iter_payload_face_count_strings(mesh),
    )
    _write_formatted_array_attribute(
        handle,
        indent_level,
        "int[] faceVertexIndices",
        _iter_payload_face_index_strings(mesh),
    )
    if _payload_has_uvs(mesh):
        _write_formatted_array_attribute(
            handle,
            indent_level,
            "texCoord2f[] primvars:st",
            _iter_payload_uv_strings(mesh),
            metadata_lines=('interpolation = "faceVarying"',),
        )


def _write_streaming_single_joint_skinning(handle, mesh: MeshData | GeometryBuffer, contract: UeSchemaContract, indent_level: int) -> None:
    point_count = mesh.point_count if isinstance(mesh, GeometryBuffer) else len(mesh.points)
    _write_formatted_array_attribute(
        handle,
        indent_level,
        "uniform int[] primvars:skel:jointIndices",
        ("0" for _ in range(point_count)),
        metadata_lines=(
            "elementSize = 1",
            'interpolation = "vertex"',
        ),
    )
    _write_formatted_array_attribute(
        handle,
        indent_level,
        "uniform float[] primvars:skel:jointWeights",
        ("1" for _ in range(point_count)),
        metadata_lines=(
            "elementSize = 1",
            'interpolation = "vertex"',
        ),
    )
    handle.write(f'{" " * 4 * indent_level}{contract.skinning_method_attr} = "{contract.skinning_method_value}"\n')


def _write_formatted_array_attribute(
    handle,
    indent_level: int,
    attribute_decl: str,
    values,
    *,
    metadata_lines: tuple[str, ...] = (),
    chunk_size: int = 4096,
) -> None:
    prefix = " " * 4 * indent_level
    handle.write(f"{prefix}{attribute_decl} = [")
    _write_formatted_values(handle, values, chunk_size=chunk_size)
    handle.write("]")
    if metadata_lines:
        handle.write(" (\n")
        for line in metadata_lines:
            handle.write(f"{prefix}    {line}\n")
        handle.write(f"{prefix})\n")
    else:
        handle.write("\n")


def _write_formatted_values(handle, values, *, chunk_size: int) -> None:
    pending: list[str] = []
    wrote_any = False
    for value in values:
        pending.append(value)
        if len(pending) >= chunk_size:
            if wrote_any:
                handle.write(", ")
            handle.write(", ".join(pending))
            wrote_any = True
            pending.clear()
    if pending:
        if wrote_any:
            handle.write(", ")
        handle.write(", ".join(pending))


def _iter_payload_point_strings(mesh: MeshData | GeometryBuffer):
    if isinstance(mesh, GeometryBuffer):
        for index in range(0, len(mesh.point_components), 3):
            yield f"({mesh.point_components[index]:g}, {mesh.point_components[index + 1]:g}, {mesh.point_components[index + 2]:g})"
        return
    for point in mesh.points:
        yield point.to_usda()


def _iter_payload_face_count_strings(mesh: MeshData | GeometryBuffer):
    if isinstance(mesh, GeometryBuffer):
        for value in mesh.face_vertex_counts:
            yield str(value)
        return
    for value in mesh.face_vertex_counts:
        yield str(value)


def _iter_payload_face_index_strings(mesh: MeshData | GeometryBuffer):
    if isinstance(mesh, GeometryBuffer):
        for value in mesh.face_vertex_indices:
            yield str(value)
        return
    for value in mesh.face_vertex_indices:
        yield str(value)


def _iter_payload_uv_strings(mesh: MeshData | GeometryBuffer):
    if isinstance(mesh, GeometryBuffer):
        for index in range(0, len(mesh.uv_components), 2):
            yield f"({mesh.uv_components[index]:g}, {mesh.uv_components[index + 1]:g})"
        return
    for uv in mesh.uv_coords:
        yield uv.to_usda()


def _payload_has_uvs(mesh: MeshData | GeometryBuffer) -> bool:
    if isinstance(mesh, GeometryBuffer):
        return bool(mesh.uv_components)
    return bool(mesh.uv_coords)
