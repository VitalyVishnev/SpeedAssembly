from __future__ import annotations

from .models import (
    AssemblyPartInstance,
    CanonicalTreeModel,
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
from .ue_schema import DEFAULT_UE_SCHEMA_CONTRACT, UeSchemaContract


def render_usda(
    model: CanonicalTreeModel,
    diagnostics: tuple[ValidationIssue, ...],
    contract: UeSchemaContract = DEFAULT_UE_SCHEMA_CONTRACT,
) -> UsdAssemblyDocument:
    error_codes = [issue.code for issue in diagnostics if issue.severity == "error"]
    if error_codes:
        raise ValueError(
            "Cannot author USDA while validation errors are present: " + ", ".join(sorted(dict.fromkeys(error_codes)))
        )

    base_animation = _render_base_animation(model, contract)
    base_mesh = _render_base_mesh(model, contract)
    main_skeleton = _render_main_skeleton(model, contract)
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
    {contract.skeleton_relationship_attr}

{_indent(materials, 1)}

{_indent(prototype_library, 1)}

    def SkelRoot "{contract.base_skel_root_name}" (
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
    return UsdAssemblyDocument(text=text, diagnostics=diagnostics)


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


def _render_material_binding(mesh: MeshData) -> str:
    if not mesh.sections:
        return ""
    if len(mesh.sections) == 1:
        section = mesh.sections[0]
        return f'rel material:binding = </Tree/Materials/{_material_prim_name_from_id(section.material_id)}>'
    subsets = "\n".join(_render_geom_subset(section) for section in mesh.sections)
    return f'''uniform token subsetFamily:materialBind:familyType = "nonOverlapping"
{subsets}'''


def _render_geom_subset(section: MeshSection) -> str:
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


def _render_base_mesh(model: CanonicalTreeModel, contract: UeSchemaContract) -> str:
    if model.base_mesh is None:
        raise ValueError("Base skeletal tree mesh is required before USDA authoring.")

    mesh = model.base_mesh
    joint_paths = _render_joint_paths(model)
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

    return f'''def Mesh "{contract.base_mesh_name}" (
    prepend apiSchemas = ["{contract.skel_binding_api}"]
)
{{
    uniform token[] skel:joints = [{joint_paths}]
    uniform matrix4d primvars:skel:geomBindTransform = {_identity_matrix()}
    append rel skel:skeleton = {contract.main_skeleton_path}
    uniform token subdivisionScheme = "none"
{_indent(material_binding, 1)}
    {_render_mesh_payload(mesh, contract.mesh_orientation)}{skinning}
}}'''


def _render_main_skeleton(model: CanonicalTreeModel, contract: UeSchemaContract) -> str:
    return f'''def Skeleton "{contract.skeleton_name}" (
    prepend apiSchemas = ["{contract.skel_binding_api}"]
)
{{
    uniform matrix4d[] bindTransforms = [{_render_bind_transforms(model)}]
    uniform token[] jointNames = [{_render_joint_basenames(model)}]
    uniform token[] joints = [{_render_joint_paths(model)}]
    uniform token purpose = "guide"
    uniform matrix4d[] restTransforms = [{_render_rest_transforms(model)}]
    append rel skel:animationSource = {contract.base_animation_path}
    uniform token visibility = "invisible"
}}'''


def _render_base_animation(model: CanonicalTreeModel, contract: UeSchemaContract) -> str:
    joints = _render_joint_paths(model)
    rotations = ", ".join(_identity_quaternion() for _ in model.skeleton)
    scales = ", ".join("(1, 1, 1)" for _ in model.skeleton)
    translations = _render_joint_rest_translations(model)
    return f'''def SkelAnimation "{contract.base_animation_name}"
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
    if prototype.mesh is None:
        raise ValueError(f"Prototype {prototype.identity.prim_name} is missing mesh payload.")

    material_binding = _render_material_binding(prototype.mesh)
    return f'''    def Xform "{prototype.identity.prim_name}" (
        kind = "component"
    )
    {{
        token visibility = "invisible"
        def Mesh "{contract.base_mesh_name}"
        {{
            uniform token subdivisionScheme = "none"
{_indent(material_binding, 3)}
            {_render_mesh_payload(prototype.mesh, contract.mesh_orientation)}
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
    if prototype.mesh is None:
        raise ValueError(f"Prototype {prototype.identity.prim_name} is missing mesh payload.")

    name = prototype.identity.prim_name
    skinning = _render_single_joint_skinning(prototype.mesh, contract)
    material_binding = _render_material_binding(prototype.mesh)
    return f'''        def Xform "{name}"
        {{
            def SkelRoot "{contract.part_skel_root_name}" (
                kind = "component"
            )
            {{
                def SkelAnimation "{contract.part_animation_name}"
                {{
                    uniform token[] joints = ["root"]
                    quath[] rotations = [{_identity_quaternion()}]
                    half3[] scales = [(1, 1, 1)]
                    float3[] translations = [(0, 0, 0)]
                }}

                def Mesh "{contract.part_mesh_name}" (
                    prepend apiSchemas = ["{contract.skel_binding_api}"]
                )
                {{
                    uniform token[] skel:joints = ["root"]
                    uniform matrix4d primvars:skel:geomBindTransform = {_identity_matrix()}
                    append rel skel:skeleton = {contract.part_skeleton_path(name)}
                    uniform token subdivisionScheme = "none"
{_indent(material_binding, 5)}
                    {_render_mesh_payload(prototype.mesh, contract.mesh_orientation)}
{_indent(skinning, 5)}
                }}

                def Skeleton "{contract.part_skeleton_name}" (
                    prepend apiSchemas = ["{contract.skel_binding_api}"]
                )
                {{
                    uniform matrix4d[] bindTransforms = [{_identity_matrix()}]
                    uniform token[] jointNames = ["root"]
                    uniform token[] joints = ["root"]
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


def _render_joint_paths(model: CanonicalTreeModel) -> str:
    path_map = _build_joint_path_map(model)
    return ", ".join(f'"{path_map[joint.name]}"' for joint in model.skeleton)


def _render_joint_basenames(model: CanonicalTreeModel) -> str:
    return ", ".join(f'"{joint.name}"' for joint in model.skeleton)


def _render_joint_rest_translations(model: CanonicalTreeModel) -> str:
    return ", ".join(joint.rest_translate.to_usda() for joint in model.skeleton)


def _render_mesh_payload(mesh: MeshData, mesh_orientation: str) -> str:
    # The source-to-stage conversion is a pure rotation plus uniform scale, so winding is preserved.
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


def _render_single_joint_skinning(mesh: MeshData, contract: UeSchemaContract) -> str:
    joint_indices = ", ".join("0" for _ in mesh.points)
    joint_weights = ", ".join("1" for _ in mesh.points)
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


def _build_joint_path_map(model: CanonicalTreeModel) -> dict[str, str]:
    joints_by_name = {joint.name: joint for joint in model.skeleton}
    path_map: dict[str, str] = {}

    def resolve(name: str) -> str:
        if name in path_map:
            return path_map[name]
        joint = joints_by_name[name]
        if joint.parent is None:
            path_map[name] = joint.name
        else:
            path_map[name] = f"{resolve(joint.parent)}/{joint.name}"
        return path_map[name]

    for joint in model.skeleton:
        resolve(joint.name)
    return path_map


def _identity_matrix() -> str:
    return "( (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1) )"


def _render_bind_transforms(model: CanonicalTreeModel) -> str:
    return ", ".join(joint.bind_transform.to_usda() for joint in model.skeleton)


def _render_rest_transforms(model: CanonicalTreeModel) -> str:
    return ", ".join(joint.rest_transform.to_usda() for joint in model.skeleton)


def _identity_quaternion() -> str:
    return "(1, 0, 0, 0)"
